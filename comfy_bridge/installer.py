"""Model packages: curated downloads from catalog.json into ComfyUI's models folder.

Only catalog URLs are ever downloaded, every file is checked against its SHA256
before it is moved into place. Downloads resume from a .part file.
Runs in a thread and never touches bpy.
"""

import hashlib
import json
import os
import shutil
import threading
import urllib.error
import urllib.request

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "catalog.json")
CHUNK = 4 * 1024 * 1024


class InstallError(RuntimeError):
    pass


def load_catalog():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["packages"]


def package(pkg_id):
    return next((p for p in load_catalog() if p["id"] == pkg_id), None)


def comfy_desktop_models_dir():
    """First models folder from Comfy Desktop's settings, if there is one."""
    path = os.path.join(os.environ.get("APPDATA", ""), "Comfy Desktop", "settings.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            dirs = json.load(f).get("modelsDirs") or []
    except (OSError, ValueError):
        return ""
    return dirs[0] if dirs and os.path.isdir(dirs[0]) else ""


NODES_SRC = os.path.join(os.path.dirname(__file__), "comfyui_nodes", "comfy_bridge_nodes")
NODES_NAME = "comfy_bridge_nodes"


def comfy_desktop_comfyui_dir():
    """ComfyUI folder of the active Comfy Desktop installation (holds custom_nodes)."""
    base = os.path.join(os.environ.get("APPDATA", ""), "Comfy Desktop")
    try:
        with open(os.path.join(base, "installations.json"), "r", encoding="utf-8") as f:
            installs = json.load(f)
    except (OSError, ValueError):
        return ""
    active = ""
    try:
        with open(os.path.join(base, "last-session.json"), "r", encoding="utf-8") as f:
            active = json.load(f).get("installationId", "")
    except (OSError, ValueError):
        pass
    for inst in sorted(installs, key=lambda i: i.get("id") != active):
        path = os.path.join(inst.get("installPath", ""), "ComfyUI")
        if os.path.isdir(os.path.join(path, "custom_nodes")):
            return path
    return ""


def _read_version(folder):
    try:
        with open(os.path.join(folder, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def nodes_status(comfyui_dir, object_info):
    """'loaded' | 'restart' (copied, ComfyUI not restarted) | 'outdated' | 'missing'."""
    target = os.path.join(comfyui_dir, "custom_nodes", NODES_NAME) if comfyui_dir else ""
    copied = bool(target) and os.path.isdir(target)
    if copied and _read_version(target) != _read_version(NODES_SRC):
        return "outdated"
    if "BlenderPass" in object_info:
        return "loaded"
    return "restart" if copied else "missing"


def install_nodes(comfyui_dir):
    """Copy the bundled node pack into ComfyUI's custom_nodes. ComfyUI needs a restart afterwards."""
    if not comfyui_dir or not os.path.isdir(os.path.join(comfyui_dir, "custom_nodes")):
        raise InstallError("ComfyUI folder not found. Set it in the add-on preferences.")
    target = os.path.join(comfyui_dir, "custom_nodes", NODES_NAME)
    shutil.copytree(NODES_SRC, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def target_path(models_dir, entry):
    return os.path.join(models_dir, entry["dir"], entry["name"])


def file_installed(models_dir, entry):
    p = target_path(models_dir, entry)
    return os.path.isfile(p) and os.path.getsize(p) == entry["size"]


def status(models_dir, pkg):
    """('installed' | 'partial' | 'missing', bytes still to download)."""
    if not models_dir:
        return "missing", sum(f["size"] for f in pkg["files"])
    have = [file_installed(models_dir, f) for f in pkg["files"]]
    todo = sum(f["size"] for f, ok in zip(pkg["files"], have) if not ok)
    if all(have):
        return "installed", 0
    return ("partial" if any(have) else "missing"), todo


def free_space(models_dir):
    probe = models_dir
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    return shutil.disk_usage(probe or ".").free


def missing_nodes(pkg, object_info):
    return [n for n in pkg.get("required_nodes", []) if n not in object_info]


def removable_files(models_dir, pkg):
    """Files of `pkg` that no other installed package uses."""
    others = set()
    for p in load_catalog():
        if p["id"] != pkg["id"] and status(models_dir, p)[0] == "installed":
            others.update(target_path(models_dir, f) for f in p["files"])
    paths = [target_path(models_dir, f) for f in pkg["files"]]
    return [p for p in paths if os.path.isfile(p) and p not in others]


def human_size(n):
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{n / 1024**2:.0f} MB"


class Download:
    def __init__(self, pkg, models_dir, hf_token=""):
        self.pkg = pkg
        self.models_dir = models_dir
        self.hf_token = hf_token
        self.files = [f for f in pkg["files"] if not file_installed(models_dir, f)]
        self.total = sum(f["size"] for f in self.files)
        self.done_bytes = 0
        self.current = ""
        self.done = False
        self.cancelled = False
        self.error = ""
        self.thread = None

    @property
    def progress(self):
        return self.done_bytes / self.total if self.total else 1.0

    def start(self):
        self.thread = threading.Thread(target=self.run, name="ComfyBridgeDownload", daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            for entry in self.files:
                if self.cancelled:
                    break
                self._fetch(entry)
        except Exception as e:  # shown in the panel
            self.error = str(e)
        finally:
            self.done = True

    def _fetch(self, entry):
        final = target_path(self.models_dir, entry)
        part = final + ".part"
        os.makedirs(os.path.dirname(final), exist_ok=True)
        self.current = entry["name"]

        # Resume: hash what is already there, then continue with a Range request.
        sha = hashlib.sha256()
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have > entry["size"]:
            os.remove(part)
            have = 0
        if have:
            with open(part, "rb") as f:
                while chunk := f.read(CHUNK):
                    sha.update(chunk)
        self.done_bytes += have

        if have < entry["size"]:
            headers = {"User-Agent": "ComfyBridge-Blender"}
            if have:
                headers["Range"] = f"bytes={have}-"
            if self.hf_token and entry["url"].startswith("https://huggingface.co/"):
                headers["Authorization"] = f"Bearer {self.hf_token}"
            req = urllib.request.Request(entry["url"], headers=headers)
            try:
                resp = urllib.request.urlopen(req, timeout=60)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise InstallError(f"{entry['name']}: access denied (HTTP {e.code}). "
                                       "Gated model? Add a Hugging Face token in the add-on preferences.") from e
                raise InstallError(f"{entry['name']}: HTTP {e.code}") from e
            with resp:
                if have and resp.status != 206:
                    raise InstallError(f"{entry['name']}: server does not support resuming, delete the .part file.")
                with open(part, "ab") as out:
                    while not self.cancelled:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        sha.update(chunk)
                        self.done_bytes += len(chunk)
            if self.cancelled:
                return  # .part stays for the next attempt

        size = os.path.getsize(part)
        if size != entry["size"]:
            raise InstallError(f"{entry['name']}: incomplete ({human_size(size)} of {human_size(entry['size'])}). Try again.")
        if sha.hexdigest() != entry["sha256"]:
            os.remove(part)
            raise InstallError(f"{entry['name']}: checksum mismatch – file deleted, try again.")
        os.replace(part, final)
