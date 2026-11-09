"""Installer test without Blender: status against the real models folder,
download + resume + checksum with the smallest catalog file into a temp folder.

python tests/installer_test.py
"""

import copy
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comfy_bridge"))
import installer  # noqa: E402

root = installer.comfy_desktop_models_dir()
print("TEST models dir:", root)
for pkg in installer.load_catalog():
    print("TEST status", pkg["id"], *installer.status(root, pkg))

clip = next(f for p in installer.load_catalog() for f in p["files"] if f["name"] == "clip_l.safetensors")
pkg = {"id": "test", "name": "Test", "files": [clip]}
tmp = tempfile.mkdtemp(prefix="cb_install_")
try:
    # 1) start, cancel after ~60 MB
    dl = installer.Download(pkg, tmp)
    dl.start()
    while dl.done_bytes < 60 * 1024**2 and not dl.done:
        time.sleep(0.2)
    dl.cancel()
    dl.thread.join()
    part = installer.target_path(tmp, clip) + ".part"
    print("TEST cancelled at", installer.human_size(os.path.getsize(part)), "| status", installer.status(tmp, pkg)[0])

    # 2) resume to the end, checksum, move into place
    dl = installer.Download(pkg, tmp)
    t = time.time()
    dl.run()
    print("TEST resumed:", "error=" + (dl.error or "-"), "| status", installer.status(tmp, pkg)[0],
          "| part left:", os.path.exists(part), f"| {time.time() - t:.0f} s")

    # 3) wrong checksum must not end up in the models folder
    os.remove(installer.target_path(tmp, clip))
    bad = copy.deepcopy(pkg)
    bad["files"][0]["sha256"] = "0" * 64
    dl = installer.Download(bad, tmp)
    dl.run()
    print("TEST bad hash:", dl.error, "| file present:", os.path.exists(installer.target_path(tmp, clip)),
          "| part left:", os.path.exists(part))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
