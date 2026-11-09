"""Ship the bundled example workflows into ComfyUI's workflow folder (subfolder "Lazy Comfy").

Remembers the SHA256 of every copied file. A later version only replaces files whose
content still matches what was shipped; an edited example stays and the new one is
placed next to it as "<name> (new).json". Other workflows are never touched.
"""

import glob
import hashlib
import json
import os
import urllib.parse

from . import comfy_client

SRC = os.path.join(os.path.dirname(__file__), "workflows", "templates")
DEST_DIR = "Lazy Comfy"
# Earlier file names of the examples (before purpose labels)
RENAMED = ("SDXL · Canny + Depth.json", "SDXL · Depth + Objects + Inpaint.json",
           "Qwen 2.1 · Depth (evaluation only).json")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _userdata_path(name):
    return "workflows/" + DEST_DIR + "/" + name


def _get(base, rel):
    status, body = comfy_client._request(base + "/api/userdata/" + urllib.parse.quote(rel, safe=""), timeout=30)
    return body if status == 200 else None


def _put(base, rel, data):
    url = base + "/api/userdata/" + urllib.parse.quote(rel, safe="") + "?overwrite=true"
    status, body = comfy_client._request(url, data=data, headers={"Content-Type": "application/json"}, timeout=30)
    if status != 200:
        raise comfy_client.ComfyError(f"Could not save {rel} in ComfyUI (HTTP {status})")


def _delete(base, rel):
    comfy_client._request(base + "/api/userdata/" + urllib.parse.quote(rel, safe=""), timeout=30, method="DELETE")


def load_manifest(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def install(base, manifest_path, version=""):
    """Returns a list of (file, action) with action in installed / updated / kept yours, added new / unchanged."""
    manifest = load_manifest(manifest_path)
    report = []
    # Examples that were shipped under another name: remove them only if still untouched
    for old in RENAMED:
        current = _get(base, _userdata_path(old))
        if current is None:
            continue
        if manifest.get(old) == _sha(current):
            _delete(base, _userdata_path(old))
            report.append((old, "renamed"))
        else:
            report.append((old, "kept yours (renamed example)"))
        manifest.pop(old, None)
    for src in sorted(glob.glob(os.path.join(SRC, "*.json"))):
        name = os.path.basename(src)
        with open(src, "rb") as f:
            new = f.read()
        rel = _userdata_path(name)
        current = _get(base, rel)
        shipped = manifest.get(name)
        if current is None:
            _put(base, rel, new)
            action = "installed"
        elif _sha(current) == _sha(new):
            action = "unchanged"
        elif (shipped and _sha(current) == shipped) or current.replace(b"comfy_bridge", b"lazy_comfy") == new:
            _put(base, rel, new)  # untouched since we shipped it (also under the add-on's old name)
            action = "updated"
        elif shipped == _sha(new):
            action = "kept yours"  # edited by the user, and we have nothing newer
        else:
            stem = os.path.splitext(name)[0]
            _put(base, _userdata_path(f"{stem} (new).json"), new)
            action = "kept yours, added new"
        if action not in ("kept yours, added new", "kept yours"):
            manifest[name] = _sha(new)
        report.append((name, action))
    manifest["__version__"] = version
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return report


def list_comfy_workflows(base):
    """All workflows saved in ComfyUI: [(path relative to workflows/, modified)]."""
    status, body = comfy_client._request(
        base + "/api/userdata?dir=workflows&recurse=true&full_info=true&split=false", timeout=30)
    if status != 200:
        return []
    items = json.loads(body)
    out = []
    for it in items:
        path = it["path"] if isinstance(it, dict) else it
        if path.lower().endswith(".json"):
            out.append((path.replace("\\", "/"), it.get("modified", 0) if isinstance(it, dict) else 0))
    return out


def fetch_workflow(base, path):
    data = _get(base, "workflows/" + path)
    return json.loads(data) if data else None
