"""GUI-Test: Blender mit Fenster, Knopf „Rendern & senden“ auslösen, Screenshot, beenden.

blender examples/blockout_raum.blend --python tests/gui_test.py -- <screenshot.png>
"""

import sys
import time

import addon_utils
import bpy

shot = sys.argv[sys.argv.index("--") + 1]
mod_name = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("comfy_bridge"))
st = sys.modules[mod_name + ".state"]
t_start = time.time()
phase = {"name": "connect", "t": time.time()}


def log(*a):
    print("GUI", round(time.time() - t_start, 1), *a, flush=True)


def window_ctx():
    win = bpy.context.window_manager.windows[0]
    props = next(a for a in win.screen.areas if a.type == "PROPERTIES")
    props.spaces.active.context = "RENDER"
    return win, props


def step():
    s = bpy.context.scene.comfy_bridge
    if phase["name"] == "connect":
        if st.server and s.params and not st.connecting:
            log("verbunden", st.server, "| workflow", s.workflow_info)
            log("modelle vorher:", [(p.label, p.str_v) for p in s.params if p.section == "model"])
            win, area = window_ctx()
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.comfy_bridge.render_send()
            phase.update(name="running", t=time.time())
        elif time.time() - phase["t"] > 30:
            log("FEHLER keine Verbindung", st.connect_error)
            bpy.ops.wm.quit_blender()
        return 0.5
    if phase["name"] == "running":
        if s.running:
            log("läuft:", s.status, round(s.progress, 2))
        if not s.running and s.status not in ("Rendering …", "Sending to ComfyUI …") and time.time() - phase["t"] > 3:
            log("ende:", s.status, "| fehler:", s.last_error or "-")
            log("bilder:", [i.name for i in bpy.data.images])
            log("modelle:", [(p.label, p.str_v, p.enum_v) for p in s.params if p.section == "model"])
            log("pfad gleich:", s.workflow == s.workflow_path, "| items:", len(st.workflow_items))
            phase.update(name="shot", t=time.time())
        elif time.time() - phase["t"] > 400:
            log("FEHLER Zeitüberschreitung")
            bpy.ops.wm.quit_blender()
        return 0.5
    if phase["name"] == "shot":
        win, area = window_ctx()
        for a in win.screen.areas:
            a.tag_redraw()
        if time.time() - phase["t"] > 2:
            with bpy.context.temp_override(window=win):
                bpy.ops.screen.screenshot(filepath=shot)
            log("screenshot", shot)
            bpy.ops.wm.quit_blender()
        return 0.5


bpy.app.timers.register(step, first_interval=2.0)
