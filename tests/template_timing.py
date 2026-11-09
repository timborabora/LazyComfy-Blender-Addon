"""Generation time of each template at 1024 x 1024 with the model already loaded (placeholders only).

python tests/template_timing.py
"""

import glob
import json
import os
import random
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lazy_comfy"))
import ui_convert  # noqa: E402

BASE = "http://127.0.0.1:8188"
OI = json.loads(urllib.request.urlopen(BASE + "/object_info", timeout=60).read())
folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lazy_comfy", "workflows", "templates")


def run(api):
    for node in api.values():
        if node["class_type"] == "BlenderRenderSize":
            node["inputs"].update(width=1024, height=1024)
        if "seed" in node["inputs"]:
            node["inputs"]["seed"] = random.randint(0, 2**31)  # avoid ComfyUI's cache
    body = json.dumps({"prompt": api, "client_id": uuid.uuid4().hex}).encode()
    pid = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/prompt", body,
                                                                   {"Content-Type": "application/json"})).read())["prompt_id"]
    while True:
        h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid}").read()).get(pid)
        if h and h["status"].get("completed") is not None:
            break
        time.sleep(0.5)
    stamps = {m[0]: m[1].get("timestamp") for m in h["status"]["messages"]}
    return (stamps["execution_success"] - stamps["execution_start"]) / 1000.0


for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
    api = ui_convert.convert(json.load(open(path, encoding="utf-8")), OI)
    warm = [run(json.loads(json.dumps(api))) for _ in range(3)][1:]  # first run loads the models
    name = os.path.basename(path).encode("ascii", "replace").decode()
    print(f"TIMING {name}: {sum(warm) / len(warm):.1f} s (warm runs {', '.join(f'{t:.1f}' for t in warm)})")
