"""Object prompts + Redo Selection on the blockout (ComfyUI must be running).

blender -b examples/blockout_raum.blend --python tests/objects_edit_test.py -- <output folder>
Never saves the opened .blend.
"""

import os
import sys

import addon_utils
import bpy
import numpy as np

out = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
os.makedirs(out, exist_ok=True)
mod = next(m.__name__ for m in addon_utils.modules() if m.__name__.endswith("comfy_bridge"))
addon_utils.enable(mod, default_set=True)
ops = sys.modules[mod + ".operators"]
st = sys.modules[mod + ".state"]
pr = sys.modules[mod + ".props"]
passes = sys.modules[mod + ".passes"]
prefs = bpy.context.preferences.addons[mod].preferences
prefs.output_dir = out

scene, layer = bpy.context.scene, bpy.context.view_layer
s = scene.comfy_bridge
ops.connect_sync()
pr.refresh_workflow_items()
s.workflow = next(p for p, _, _ in st.workflow_items if p.endswith("SDXL_Object_Prompts_Depth.json"))
s.edit_workflow = next(p for p, _, _ in st.edit_workflow_items if p.endswith("SDXL_Edit_Selection.json"))
print("TEST info", s.workflow_info, "| slots", s.region_slots)

bpy.data.objects["Tisch"].comfy_prompt = "glossy red lacquer coffee table"
bpy.data.objects["Regal"].comfy_prompt = "white carrara marble bookshelf"
s.seed_random, s.seed = False, 777


def render_and_run(mode):
    _, _, _, wanted = ops.workflow_needs(scene, layer, mode)
    saved = passes.prepare_scene(scene, layer, wanted)
    bpy.ops.render.render()
    job, files, warnings = ops.run_blocking(scene, layer, mode)
    passes.restore_scene(saved)
    print(f"TEST {mode}: status={s.status} | error={s.last_error or '-'} | warnings={warnings}")
    return job, files


job_a, files_a = render_and_run("main")
result_a = s.last_result
print("TEST result A", result_a)

for o in scene.objects:
    o.select_set(o.name.startswith("Sofa"))
s.edit_prompt = "green velvet sofa"
job_b, files_b = render_and_run("edit")
result_b = s.last_result
print("TEST result B", result_b, "| seed", s.last_seed)


def load(path):
    i = passes.oiio.ImageInput.open(path)
    a = i.read_image(format="uint8")
    i.close()
    return a.astype(np.int16)


a, b, m = load(result_a), load(result_b), load(files_b["selection"])[:, :, 0]
outside = m == 0
diff = np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2)
print(f"TEST pixel diff outside mask: max={int(diff[outside].max())} changed={int((diff[outside] > 0).sum())} "
      f"of {int(outside.sum())} | inside mean={float(diff[~outside].mean()):.1f}")

inp = passes.oiio.ImageInput.open(result_b)
spec = inp.spec()
inp.close()
print("TEST png metadata keys", [x.name for x in spec.extra_attribs if x.name in ("prompt", "workflow")])
