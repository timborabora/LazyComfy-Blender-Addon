"""Headless-Test der Pass-Erzeugung ohne ComfyUI.

blender -b examples/blockout_raum.blend --python tests/passes_test.py -- <ausgabeordner>
"""

import sys

import addon_utils
import bpy

out = sys.argv[sys.argv.index("--") + 1]
mod_name = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("comfy_bridge"))
addon_utils.enable(mod_name, default_set=True)
passes = sys.modules[mod_name + ".passes"]

scene, layer = bpy.context.scene, bpy.context.view_layer
needed = ["beauty", "depth", "normal", "lineart", "mask:Sofa", "mask:Gibtsnicht"]
saved = passes.prepare_scene(scene, layer, needed)
bpy.ops.render.render()
files, warnings, _ = passes.export(scene, layer, needed, out)
passes.restore_scene(saved)
print("TEST files", files)
print("TEST warnings", warnings)
print("TEST restored freestyle", scene.render.use_freestyle, "normal", layer.use_pass_normal)
