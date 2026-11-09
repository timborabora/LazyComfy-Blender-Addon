"""Render the blockout and run one saved ComfyUI workflow; prints result path and timing.

blender -b <blockout copy>.blend --python tests/template_run.py -- <output folder> <workflow name part> [seed]
"""

import os
import sys
import time

import addon_utils
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out, name = os.path.abspath(args[0]), args[1]
seed = int(args[2]) if len(args) > 2 else 4242
os.makedirs(out, exist_ok=True)
mod = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("lazy_comfy"))
addon_utils.enable(mod, default_set=True)
ops, st, passes = (sys.modules[mod + x] for x in (".operators", ".state", ".passes"))
bpy.context.preferences.addons[mod].preferences.output_dir = out
scene, layer = bpy.context.scene, bpy.context.view_layer
s = scene.lazy_comfy
ops.connect_sync()
print("RUN dropdown:", [label for _, label, _ in st.workflow_items])
s.workflow = next(i for i, label, _ in st.workflow_items if name.lower() in (i + label).lower())
s.seed_random, s.seed = False, seed
_, _, _, wanted = ops.workflow_needs(scene, layer, "main")
saved = passes.prepare_scene(scene, layer, wanted)
bpy.ops.render.render()
t = time.time()
job, files, warnings = ops.run_blocking(scene, layer)
passes.restore_scene(saved)
print(f"RUN {s.workflow} | {s.status} | error={s.last_error or '-'} | {time.time() - t:.1f} s")
print("RUN result", s.last_result)
print("RUN passes", files)
