"""Old Comfy Bridge data in a .blend is taken over when the file is opened.

blender -b --python tests/migration_test.py -- <scratch folder>
"""

import os
import sys

import bpy

out = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "old_comfy_bridge.blend")

# Simulate a file saved by Comfy Bridge: raw ID properties under the old names
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.active_object
cube.name = "Table"
cube["comfy_prompt"] = "glossy red lacquer coffee table"
bpy.context.scene["comfy_bridge"] = {
    "workflow_path": "comfy:Comfy Bridge/SDXL · Canny + Depth.json",
    "saved_values": '{"comfy:Comfy Bridge/SDXL · Canny + Depth.json": {"27:value": 0.5}}',
    "seed": 1234, "seed_random": 0, "edit_prompt": "green velvet sofa",
}
bpy.ops.wm.save_as_mainfile(filepath=path)

import addon_utils  # noqa: E402
mod = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("lazy_comfy"))
addon_utils.enable(mod, default_set=True)
bpy.ops.wm.open_mainfile(filepath=path)  # load_post runs the migration

s = bpy.context.scene.lazy_comfy
obj = bpy.data.objects["Table"]
print("MIGRATE object prompt:", repr(obj.lazy_comfy_prompt), "| old key left:", "comfy_prompt" in obj.keys())
print("MIGRATE scene:", s.workflow_path, "| seed", s.seed, "| random", s.seed_random, "| change", repr(s.edit_prompt))
print("MIGRATE saved values:", s.saved_values, "| old group left:", "comfy_bridge" in bpy.context.scene.keys())
