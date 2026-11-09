"""Headless test: build the blockout, render it, send it to ComfyUI through Lazy Comfy.

blender -b --python tests/blockout_test.py -- [Workflow-Dateiname] [Ausgabe.blend]
"""

import os
import sys
import time

import addon_utils
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WORKFLOW = argv[0] if argv else "SDXL_Canny_Depth.json"
BLEND = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "examples", "blockout_room.blend")

mod_name = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("lazy_comfy"))
addon_utils.enable(mod_name, default_set=True)
bpy.context.preferences.addons[mod_name].preferences.show_api_files = True  # old API-file examples
import os as _os
bpy.context.preferences.addons[mod_name].preferences.workflow_dir = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "fixtures", "api_workflows")
cb = sys.modules[mod_name]
ops = sys.modules[mod_name + ".operators"]
st = sys.modules[mod_name + ".state"]
pr = sys.modules[mod_name + ".props"]


def box(name, loc, size):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    return o


bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod_name, default_set=True)
scene = bpy.context.scene
# room 6 x 5 m, 3 m high
box("Floor", (0, 0, -0.05), (6, 5, 0.1))
box("Wall_Back", (0, 2.55, 1.5), (6, 0.1, 3))
box("Wall_Left_Low", (-3.05, 0, 0.45), (0.1, 5, 0.9))
box("Wall_Left_High", (-3.05, 0, 2.7), (0.1, 5, 0.6))
box("Wall_Left_Front", (-3.05, -1.9, 1.5), (0.1, 1.2, 3))
box("Wall_Left_Back", (-3.05, 1.9, 1.5), (0.1, 1.2, 3))
box("Sofa_Seat", (0.3, 1.6, 0.22), (2.4, 0.95, 0.44))
box("Sofa_Back", (0.3, 2.0, 0.6), (2.4, 0.2, 0.75))
box("Table", (0.3, 0.3, 0.2), (1.2, 0.7, 0.4))
box("Shelf", (2.4, 2.25, 1.0), (1.0, 0.4, 2.0))

cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 24
cam = bpy.data.objects.new("Camera", cam_data)
scene.collection.objects.link(cam)
cam.location = (2.6, -2.3, 1.5)
cam.rotation_euler = (1.45, 0.0, 0.62)
scene.camera = cam
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 3.0
sun.rotation_euler = (0.9, 0.0, -1.2)
scene.collection.objects.link(sun)
scene.world = bpy.data.worlds.new("World")
scene.world.color = (0.25, 0.25, 0.27)

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = 1024, 768
scene.render.resolution_percentage = 100

os.makedirs(os.path.dirname(os.path.abspath(BLEND)), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(BLEND), compress=True)
if WORKFLOW == "none":  # only (re)build the example scene
    print("TEST scene saved", os.path.abspath(BLEND))
    sys.exit(0)

base = ops.connect_sync()
print("TEST server", base, st.stats["system"]["comfyui_version"])
pr.refresh_workflow_items()
path = next(p for p, label, _ in st.workflow_items if p.endswith(WORKFLOW))
s = scene.lazy_comfy
s.workflow = path
print("TEST info", s.workflow_info, "| warnings:", s.workflow_warnings or "-")
for p in s.params:
    extra = ""
    if p.kind == "ENUM":
        extra = " options=" + ",".join(st.enum_item_cache.get(("opts", p.key), []))
    print(f"TEST param [{p.section}] {p.label} = {p.get_value()!r}{extra}")
print("TEST workflows", [label for _, label, _ in st.workflow_items])

wf_mod = sys.modules[mod_name + ".workflows"]
needed = list(wf_mod.analyze(wf_mod.load(path), st.object_info)["images"].keys())
passes = sys.modules[mod_name + ".passes"]
saved = passes.prepare_scene(scene, bpy.context.view_layer, needed)
t0 = time.time()
bpy.ops.render.render()
print("TEST render s", round(time.time() - t0, 1))
s.seed_random = False
s.seed = 4242
t0 = time.time()
job, files, warnings = ops.run_blocking(scene, bpy.context.view_layer)
passes.restore_scene(saved)
print("TEST files", files)
print("TEST warnings", warnings)
print("TEST status", s.status, "| error:", s.last_error or "-", "| comfy s", round(time.time() - t0, 1))
print("TEST results", job.results)
print("TEST images", [i.name for i in bpy.data.images])
print("TEST history", bpy.data.texts["LazyComfy_History"].as_string()[:300])
bpy.ops.wm.save_mainfile()
