"""Reads a workflow the ComfyUI frontend saved (Ctrl+S), converts it and validates it with /prompt.

python tests/saved_workflow_test.py "Comfy Bridge/SDXL · Canny + Depth.json" [--run]
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comfy_bridge"))
import ui_convert  # noqa: E402

BASE = "http://127.0.0.1:8188"
rel = sys.argv[1]
oi = json.loads(urllib.request.urlopen(BASE + "/object_info", timeout=60).read())
url = BASE + "/api/userdata/" + urllib.parse.quote("workflows/" + rel, safe="")
ui = json.loads(urllib.request.urlopen(url, timeout=30).read())
print("SAVED frontend version:", ui.get("version"), "| nodes:", len(ui["nodes"]), "| links:", len(ui["links"]),
      "| widgets_values style:", type(ui["nodes"][0].get("widgets_values")).__name__)
api = ui_convert.convert(ui, oi)
for nid, n in api.items():
    if n["class_type"].startswith("BlenderSetting"):
        print("SAVED setting", n["inputs"].get("label"), "=", n["inputs"].get("value"))
if "--run" in sys.argv:
    body = json.dumps({"prompt": api, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(BASE + "/prompt", body, {"Content-Type": "application/json"})
    try:
        print("SAVED queued:", json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"])
    except urllib.error.HTTPError as e:
        print("SAVED rejected:", e.read().decode()[:1500])
