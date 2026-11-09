"""Node-based workflows saved in ComfyUI (ComfyUI with comfy_bridge_nodes must be running).

blender -b examples/blockout_raum.blend --python tests/nodes_test.py -- <output folder>
1. Examples are shipped and listed from ComfyUI's workflow folder.
2. "SDXL · Canny + Depth" with the old BL: workflow's settings gives the same image.
3. "SDXL · Depth + Objects + Inpaint": object prompts, then Redo Selection on the sofa.
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
bpy.context.preferences.addons[mod].preferences.show_api_files = True  # old API-file examples
ops, st, pr, passes = (sys.modules[mod + x] for x in (".operators", ".state", ".props", ".passes"))
bpy.context.preferences.addons[mod].preferences.output_dir = out
scene, layer = bpy.context.scene, bpy.context.view_layer
s = scene.comfy_bridge

ops.connect_sync()
print("TEST examples:", st.examples_message)
print("TEST dropdown:", [label for _, label, _ in st.workflow_items])
print("TEST edit dropdown:", [label for _, label, _ in st.edit_workflow_items])


def pick(suffix):
    s.workflow = next(i for i, _, _ in st.workflow_items if i.endswith(suffix))
    print(f"TEST picked {suffix}: info={s.workflow_info} | warn={s.workflow_warnings or '-'} "
          f"| missing pkgs={s.missing_packages or '-'} nodes={s.missing_nodes or '-'} | can_edit={s.workflow_can_edit}")
    for p in s.params:
        print(f"TEST    [{p.section}] {p.label} = {p.get_value()!r}")


def render_and_run(mode="main"):
    _, _, _, wanted = ops.workflow_needs(scene, layer, mode)
    saved = passes.prepare_scene(scene, layer, wanted)
    bpy.ops.render.render()
    job, files, warnings = ops.run_blocking(scene, layer, mode)
    passes.restore_scene(saved)
    print(f"TEST {mode}: {s.status} | error={s.last_error or '-'} | warnings={warnings} -> {os.path.basename(s.last_result)}")
    return files


def load(path):
    i = passes.oiio.ImageInput.open(path)
    a = i.read_image(format="uint8")
    i.close()
    return a.astype(np.int16)


def setting(label, value):
    p = next(p for p in s.params if p.label == label)
    p.set_value(value)


s.seed_random, s.seed = False, 4242

# 2) old BL: workflow vs. node template with the same settings
s.workflow = next(i for i, _, _ in st.workflow_items if i.endswith("SDXL_Canny_Depth.json"))
render_and_run()
old = s.last_result
pick("SDXL · Canny + Depth.json")
for label, value in (("Canny Strength", 0.8), ("Canny End", 0.8), ("Depth Strength", 0.6), ("Depth End", 0.8), ("Steps", 25)):
    setting(label, value)
next(p for p in s.params if p.label == "Prompt").set_value(
    "RAW photo, modern living room, concrete walls, oak floor, large windows, soft daylight, photorealistic, 8k uhd, DSLR")
next(p for p in s.params if p.label == "Negative").set_value(
    "cartoon, illustration, drawing, painting, cgi, 3d render, plastic, anime, sketch, blurry")
render_and_run()
new = s.last_result
d = np.abs(load(old) - load(new))
print(f"TEST old vs node template: max diff={int(d.max())} mean={float(d.mean()):.3f}")

# 3) objects + Redo Selection on the node template
pick("SDXL · Depth + Objects + Inpaint.json")
bpy.data.objects["Tisch"].comfy_prompt = "glossy red lacquer coffee table"
bpy.data.objects["Regal"].comfy_prompt = "white carrara marble bookshelf"
s.seed = 777
render_and_run()
a_path = s.last_result
for o in scene.objects:
    o.select_set(o.name.startswith("Sofa"))
s.edit_prompt = "green velvet sofa"
files = render_and_run("edit")
b_path = s.last_result
a, b, m = load(a_path), load(b_path), load(files["selection"])[:, :, 0]
diff = np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2)
outside = m == 0
print(f"TEST redo selection: outside max={int(diff[outside].max())} changed={int((diff[outside] > 0).sum())} "
      f"| inside mean={float(diff[~outside].mean()):.1f}")
print("TEST results", a_path, b_path)
