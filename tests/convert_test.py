"""Converts the UI-format templates to API format and runs them in ComfyUI with placeholders only.

python tests/convert_test.py [template name filter]
"""

import glob
import json
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comfy_bridge"))
import ui_convert  # noqa: E402

BASE = "http://127.0.0.1:8188"
OI = json.loads(urllib.request.urlopen(BASE + "/object_info", timeout=60).read())
pattern = sys.argv[1] if len(sys.argv) > 1 else ""
folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comfy_bridge", "workflows", "templates")
files = sys.argv[2:] or sorted(glob.glob(os.path.join(folder, "*.json")))

for path in files:
    if pattern and pattern.lower() not in os.path.basename(path).lower():
        continue
    ui = json.load(open(path, encoding="utf-8"))
    api = ui_convert.convert(ui, OI)
    body = json.dumps({"prompt": api, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(BASE + "/prompt", body, {"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("CONVERT", os.path.basename(path), "REJECTED", e.read().decode()[:1500])
        continue
    t = time.time()
    while True:
        h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid}", timeout=30).read()).get(pid)
        if h and h.get("status", {}).get("completed") is not None:
            break
        time.sleep(1)
    st = h["status"]
    outs = [img["filename"] for o in h["outputs"].values() for img in o.get("images", []) if img.get("type") == "output"]
    err = [m[1].get("exception_message", "")[:300] for m in st.get("messages", []) if m[0] == "execution_error"]
    print("CONVERT", os.path.basename(path), st.get("status_str"), f"{time.time() - t:.1f} s", outs, err)
