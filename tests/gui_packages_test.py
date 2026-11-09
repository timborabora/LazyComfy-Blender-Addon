"""GUI check of the Model Packages panel: open it as a popup, screenshot, quit.

blender examples/blockout_raum.blend --python tests/gui_packages_test.py -- <screenshot.png> [package_id]
"""

import sys
import time

import addon_utils
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
shot = args[0]
mod_name = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("comfy_bridge"))
st = sys.modules[mod_name + ".state"]
t0 = time.time()
phase = {"n": 0}


def step():
    win = bpy.context.window_manager.windows[0]
    if phase["n"] == 0:
        if not st.server and time.time() - t0 < 30:
            return 0.5
        if len(args) > 1:
            bpy.context.scene.comfy_bridge.package = args[1]
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.call_panel(name="CB_PT_packages", keep_open=True)
        phase["n"] = 1
        return 1.5
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=shot)
    print("GUI screenshot", shot, flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(step, first_interval=2.0)
