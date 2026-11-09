"""GUI check of a Comfy Bridge panel: open it as a popup, screenshot, quit.

blender examples/blockout_raum.blend --python tests/gui_packages_test.py -- <screenshot.png> [package_id] [panel]
Panel defaults to CB_PT_packages. With CB_PT_object_prompts / CB_PT_edit the test sets two object prompts.
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
        s = bpy.context.scene.comfy_bridge
        if len(args) > 1 and args[1] != "-":
            s.package = args[1]
        panel = args[2] if len(args) > 2 else "CB_PT_packages"
        if panel == "CB_PT_main":
            s.workflow = next(p for p, _, _ in st.workflow_items if p.endswith("Depth + Objects + Inpaint.json"))
            bpy.data.objects["Tisch"].comfy_prompt = "glossy red lacquer coffee table"
        elif panel in ("CB_PT_object_prompts", "CB_PT_edit"):
            s.workflow = next(p for p, _, _ in st.workflow_items if p.endswith("SDXL_Object_Prompts_Depth.json"))
            bpy.data.objects["Tisch"].comfy_prompt = "glossy red lacquer coffee table"
            bpy.data.objects["Regal"].comfy_prompt = "white carrara marble bookshelf"
        if panel == "CB_PT_main":
            # call_panel on a panel with sub-panels crashes Blender 5.2 – show the Properties editor instead
            area = next(a for a in win.screen.areas if a.type == "PROPERTIES")
            area.spaces.active.context = "RENDER"
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.screen.screen_full_area()
        else:
            with bpy.context.temp_override(window=win):
                bpy.ops.wm.call_panel(name=panel, keep_open=True)
        phase["n"] = 1
        return 1.5
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=shot)
    print("GUI screenshot", shot, flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(step, first_interval=2.0)
