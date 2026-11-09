"""All four object prompt slots plus one object too many (ComfyUI must be running).

blender -b examples/blockout_raum.blend --python tests/regions_limit_test.py -- <output folder>
"""

import os
import sys

import addon_utils
import bpy

out = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
mod = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("comfy_bridge"))
addon_utils.enable(mod, default_set=True)
bpy.context.preferences.addons[mod].preferences.show_api_files = True  # old API-file examples
ops, st, pr, passes = (sys.modules[mod + x] for x in (".operators", ".state", ".props", ".passes"))
bpy.context.preferences.addons[mod].preferences.output_dir = out
scene, layer = bpy.context.scene, bpy.context.view_layer
s = scene.comfy_bridge
ops.connect_sync()
pr.refresh_workflow_items()
s.workflow = next(p for p, _, _ in st.workflow_items if p.endswith("SDXL_Object_Prompts_Depth.json"))
prompts = {"Regal": "white carrara marble bookshelf", "Sofa_Lehne": "mustard yellow leather sofa backrest",
           "Sofa_Sitz": "mustard yellow leather sofa seat", "Tisch": "glossy red lacquer coffee table",
           "Wand_hinten": "dark green painted wall"}
for name, text in prompts.items():
    bpy.data.objects[name].comfy_prompt = text
s.seed_random, s.seed = False, 777
_, _, _, wanted = ops.workflow_needs(scene, layer, "main")
saved = passes.prepare_scene(scene, layer, wanted)
bpy.ops.render.render()
job, files, warnings = ops.run_blocking(scene, layer)
passes.restore_scene(saved)
print("TEST status", s.status, "| warnings", warnings)
print("TEST result", s.last_result)
