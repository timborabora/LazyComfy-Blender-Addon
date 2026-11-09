"""HTTP and websocket connection to ComfyUI.

Standard library only: Blender's Python ships no websocket package,
hence a minimal client (RFC 6455, only what ComfyUI needs).
"""

import base64
import json
import os
import select
import socket
import struct
import urllib.error
import urllib.parse
import urllib.request
import uuid

MODEL_EXTENSIONS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft")
CANDIDATE_PORTS = (8188, 8000, 8189, 8001, 8190)


class ComfyError(RuntimeError):
    pass


def _request(url, data=None, headers=None, timeout=10.0):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        raise ComfyError(f"ComfyUI not reachable ({url}): {e}") from e


def get_json(base, path, timeout=10.0):
    status, body = _request(base + path, timeout=timeout)
    if status != 200:
        raise ComfyError(f"{path}: HTTP {status}")
    return json.loads(body)


def post_json(base, path, payload, timeout=30.0):
    data = json.dumps(payload).encode("utf-8")
    return _request(base + path, data=data, headers={"Content-Type": "application/json"}, timeout=timeout)


def find_server(preferred=""):
    """Find the running ComfyUI server. Comfy Desktop does not always use 8188."""
    candidates = []
    if preferred:
        candidates.append(preferred.rstrip("/"))
    candidates += [f"http://127.0.0.1:{p}" for p in CANDIDATE_PORTS]
    seen = set()
    for base in candidates:
        if base in seen:
            continue
        seen.add(base)
        try:
            stats = get_json(base, "/system_stats", timeout=0.8)
        except Exception:
            continue
        if isinstance(stats, dict) and "system" in stats:
            return base, stats
    return None, None


def upload_image(base, path, name, subfolder="lazy_comfy"):
    """Upload an image into ComfyUI's input folder. Returns the value for LoadImage.image."""
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        content = f.read()
    parts = []
    for key, value in (("subfolder", subfolder), ("type", "input"), ("overwrite", "true")):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
        f"Content-Type: image/png\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    status, body = _request(
        base + "/upload/image",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=60,
    )
    if status != 200:
        raise ComfyError(f"Upload of {name} failed: HTTP {status} {body[:200]!r}")
    info = json.loads(body)
    sub = info.get("subfolder") or ""
    return f"{sub}/{info['name']}" if sub else info["name"]


def queue_prompt(base, workflow, client_id):
    status, body = post_json(base, "/prompt", {"prompt": workflow, "client_id": client_id})
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status == 200 and "prompt_id" in data:
        return data["prompt_id"]
    raise ComfyError(format_prompt_error(data, workflow) or f"ComfyUI rejected the workflow (HTTP {status})")


def format_prompt_error(data, workflow):
    """Turn ComfyUI's validation errors into a readable message."""
    lines = []
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        lines.append(err["message"])
    for node_id, node_err in (data.get("node_errors") or {}).items():
        title = workflow.get(node_id, {}).get("_meta", {}).get("title") or node_err.get("class_type", node_id)
        for e in node_err.get("errors", []):
            detail = e.get("details") or e.get("message", "")
            lines.append(f"• {title}: {detail}")
    return "\n".join(lines)


def interrupt(base):
    try:
        _request(base + "/interrupt", data=b"", timeout=5)
    except ComfyError:
        pass


def history(base, prompt_id):
    data = get_json(base, f"/history/{prompt_id}")
    return data.get(prompt_id)


def download_image(base, image, dest_path):
    query = urllib.parse.urlencode(
        {"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")}
    )
    status, body = _request(f"{base}/view?{query}", timeout=60)
    if status != 200:
        raise ComfyError(f"Could not download {image['filename']} (HTTP {status})")
    with open(dest_path, "wb") as f:
        f.write(body)
    return dest_path


def spec_of(object_info, class_type, input_name):
    node = object_info.get(class_type)
    if not node:
        return None
    inputs = node.get("input", {})
    for group in ("required", "optional"):
        spec = inputs.get(group, {}).get(input_name)
        if spec is not None:
            return spec
    return None


def parse_spec(spec):
    """(kind, opts) from a ComfyUI input spec. Handles old and new COMBO notation."""
    if not spec:
        return None, {}
    kind = spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if isinstance(kind, list):
        return "ENUM", dict(opts, options=list(kind))
    if kind == "COMBO":
        return "ENUM", dict(opts, options=list(opts.get("options", [])))
    if kind in ("INT", "FLOAT", "BOOLEAN", "STRING"):
        return kind, opts
    return None, opts


class WebSocket:
    """Minimal websocket client for ComfyUI's /ws (receives text frames only)."""

    def __init__(self, base, client_id):
        url = urllib.parse.urlparse(base)
        host, port = url.hostname, url.port or 80
        self.sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET /ws?clientId={client_id} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ComfyError("Websocket handshake aborted")
            resp += chunk
        head, _, self.buf = resp.partition(b"\r\n\r\n")
        if b" 101" not in head.split(b"\r\n", 1)[0]:
            raise ComfyError("Websocket handshake rejected")
        self.sock.settimeout(30)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode, payload=b""):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_json(self, wait=1.0):
        """Next text message as a dict, or None if nothing arrived within `wait`."""
        if not self.buf:
            ready, _, _ = select.select([self.sock], [], [], wait)
            if not ready:
                return None
        message, msg_op = b"", None
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if op == 0x8:
                raise ConnectionError("Websocket closed by server")
            if op == 0x9:
                self._send(0xA, payload)
                continue
            if op == 0xA:
                continue
            if op != 0:
                msg_op = op
            message += payload
            if fin:
                break
        if msg_op != 0x1:
            return {}  # ignore binary frames (live previews)
        return json.loads(message.decode("utf-8"))

    def close(self):
        try:
            self._send(0x8)
        except OSError:
            pass
        self.sock.close()
