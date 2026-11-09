"""Builds the bundled example workflows in ComfyUI's UI format (what Ctrl+S saves).

python tools/make_templates.py   (ComfyUI with lazy_comfy_nodes must be running)
Writes lazy_comfy/workflows/templates/*.json.
"""

import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "lazy_comfy", "workflows", "templates")
OI = json.loads(urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=60).read())

GROUPS = ["Blender Inputs", "Model", "Prompts", "Control", "Sampler", "Inpaint (Redo Selection)", "Output"]
GROUP_COLORS = ["#3f789e", "#8A8", "#a1309b", "#b58b2a", "#88A", "#b06634", "#444"]
COL_W, ROW_GAP = 380, 40


class Graph:
    def __init__(self, name, packages, description):
        self.name, self.packages, self.description = name, packages, description
        self.nodes, self.links, self.order = {}, [], []
        self.next_link = 1
        self.col_y = {g: 60 for g in GROUPS}

    def add(self, nid, cls, group, title=None, h=None, **widgets):
        spec = OI[cls]
        order = [(g, n) for g in ("required", "optional") for n in spec.get("input_order", {}).get(g, [])]
        ins, wvals = [], []
        for g, name in order:
            ispec = spec["input"][g][name]
            kind = ispec[0]
            opts = ispec[1] if len(ispec) > 1 and isinstance(ispec[1], dict) else {}
            is_widget = (isinstance(kind, list) or kind in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")) and not opts.get("forceInput")
            if is_widget:
                default = opts.get("default", kind[0] if isinstance(kind, list) and kind else "")
                wvals.append(widgets.pop(name, default))
                if opts.get("control_after_generate") or name in ("seed", "noise_seed"):
                    wvals.append("fixed")
                ins.append({"name": name, "type": "COMBO" if isinstance(kind, list) else kind,
                            "widget": {"name": name}, "link": None})
            else:
                ins.append({"name": name, "type": kind, "link": None})
        if widgets:
            raise ValueError(f"{cls}: unknown widgets {list(widgets)}")
        outs = [{"name": n, "type": t, "links": [], "slot_index": i}
                for i, (t, n) in enumerate(zip(spec["output"], spec.get("output_name") or spec["output"]))]
        height = h or (60 + 26 * len(ins) + (60 if any(i.get("type") == "STRING" for i in ins) else 0))
        col = GROUPS.index(group)
        pos = [40 + col * (COL_W + 60), self.col_y[group]]
        self.col_y[group] += height + ROW_GAP
        node = {"id": nid, "type": cls, "pos": pos, "size": [COL_W, height], "flags": {}, "order": len(self.nodes),
                "mode": 0, "inputs": ins, "outputs": outs, "properties": {"Node name for S&R": cls},
                "widgets_values": wvals, "_group": group}
        if title:
            node["title"] = title
        self.nodes[nid] = node

    def link(self, src, slot, dst, name):
        lid = self.next_link
        self.next_link += 1
        s, d = self.nodes[src], self.nodes[dst]
        inp = next(i for i in d["inputs"] if i["name"] == name)
        inp["link"] = lid
        s["outputs"][slot]["links"].append(lid)
        self.links.append([lid, src, slot, dst, d["inputs"].index(inp), s["outputs"][slot]["type"]])

    def save(self, filename):
        groups = []
        for gi, g in enumerate(GROUPS):
            members = [n for n in self.nodes.values() if n["_group"] == g]
            if not members:
                continue
            x = min(n["pos"][0] for n in members) - 20
            y = min(n["pos"][1] for n in members) - 50
            r = max(n["pos"][0] + n["size"][0] for n in members) + 20
            b = max(n["pos"][1] + n["size"][1] for n in members) + 20
            groups.append({"id": gi + 1, "title": g, "bounding": [x, y, r - x, b - y], "color": GROUP_COLORS[gi],
                           "font_size": 24, "flags": {}})
        nodes = []
        for n in self.nodes.values():
            n = dict(n)
            n.pop("_group")
            nodes.append(n)
        used = sorted({n["type"] for n in self.nodes.values()})
        ui = {"id": filename, "revision": 0, "last_node_id": max(self.nodes), "last_link_id": self.next_link - 1,
              "nodes": nodes, "links": self.links, "groups": groups, "config": {},
              "extra": {"ds": {"scale": 0.6, "offset": [40, 40]},
                        "lazy_comfy": {"description": self.description, "packages": self.packages,
                                         "nodes": [c for c in used if c.startswith("Blender")] or [],
                                         "required_nodes": used}},
              "version": 0.4}
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, filename), "w", encoding="utf-8", newline="\n") as f:
            json.dump(ui, f, indent=1)
        print("wrote", filename, len(nodes), "nodes", len(self.links), "links")


NEG = "cartoon, illustration, drawing, painting, cgi, 3d render, plastic, anime, sketch, blurry"


def sdxl_base(g, canny=True):
    g.add(1, "BlenderPrompt", "Blender Inputs", positive="RAW photo, modern living room, concrete walls, oak floor, "
          "large windows, soft daylight, photorealistic, 8k uhd, DSLR", negative=NEG)
    if canny:
        g.add(2, "BlenderPass", "Blender Inputs", title="Blender Pass · Beauty", pass_type="beauty")
    g.add(3, "BlenderPass", "Blender Inputs", title="Blender Pass · Depth", pass_type="depth")
    g.add(4, "BlenderRenderSize", "Blender Inputs")
    g.add(10, "CheckpointLoaderSimple", "Model", ckpt_name="juggernautXL_ragnarokBy.safetensors")
    g.add(11, "CLIPTextEncode", "Prompts", title="Positive")
    g.add(12, "CLIPTextEncode", "Prompts", title="Negative")
    g.link(1, 0, 11, "text"); g.link(10, 1, 11, "clip")
    g.link(1, 1, 12, "text"); g.link(10, 1, 12, "clip")
    pos, neg = (11, 0), (12, 0)
    if canny:
        g.add(20, "Canny", "Control", low_threshold=0.2, high_threshold=0.6)
        g.add(21, "ControlNetLoader", "Control", title="ControlNet Canny", control_net_name="controlnet-canny-sdxl.safetensors")
        g.add(24, "BlenderSettingFloat", "Control", label="Canny Strength", value=0.7, minimum=0.0, maximum=1.5)
        g.add(25, "BlenderSettingFloat", "Control", label="Canny End", value=0.8, minimum=0.0, maximum=1.0)
        g.add(23, "ControlNetApplyAdvanced", "Control", title="Apply Canny")
        g.link(2, 0, 20, "image"); g.link(20, 0, 23, "image"); g.link(21, 0, 23, "control_net")
        g.link(24, 0, 23, "strength"); g.link(25, 0, 23, "end_percent")
        g.link(*pos, 23, "positive"); g.link(*neg, 23, "negative")
        pos, neg = (23, 0), (23, 1)
    g.add(22, "ControlNetLoader", "Control", title="ControlNet Depth", control_net_name="controlnet-depth-sdxl.safetensors")
    g.add(27, "BlenderSettingFloat", "Control", label="Depth Strength", value=0.7, minimum=0.0, maximum=1.5)
    g.add(28, "BlenderSettingFloat", "Control", label="Depth End", value=0.8, minimum=0.0, maximum=1.0)
    g.add(26, "ControlNetApplyAdvanced", "Control", title="Apply Depth")
    g.link(3, 0, 26, "image"); g.link(22, 0, 26, "control_net")
    g.link(27, 0, 26, "strength"); g.link(28, 0, 26, "end_percent")
    g.link(*pos, 26, "positive"); g.link(*neg, 26, "negative")
    g.add(30, "EmptyLatentImage", "Sampler")
    g.add(32, "BlenderSettingInt", "Sampler", label="Steps", value=25, minimum=1, maximum=80)
    g.add(31, "KSampler", "Sampler", steps=25, cfg=7.0, sampler_name="euler_ancestral", scheduler="normal")
    g.link(4, 0, 30, "width"); g.link(4, 1, 30, "height")
    g.link(10, 0, 31, "model"); g.link(26, 0, 31, "positive"); g.link(26, 1, 31, "negative")
    g.link(30, 0, 31, "latent_image"); g.link(32, 0, 31, "steps")
    g.add(40, "VAEDecode", "Output")
    g.link(31, 0, 40, "samples"); g.link(10, 2, 40, "vae")
    g.add(42, "PreviewImage", "Output", title="Control Preview · Depth")
    g.link(3, 0, 42, "images")


# 1) SDXL · Canny + Depth
g = Graph("SDXL · Canny + Depth", ["sdxl_canny_depth"], "Juggernaut XL with Canny from the beauty pass and Blender depth.")
sdxl_base(g)
g.add(41, "SaveImage", "Output", filename_prefix="lazy_comfy/sdxl")
g.link(40, 0, 41, "images")
g.save("SDXL · Canny + Depth.json")

# 2) SDXL · Depth + Objects + Inpaint
g = Graph("SDXL · Depth + Objects + Inpaint", ["sdxl_canny_depth"],
          "Depth-guided SDXL with per-object prompts and Redo Selection (inpaint branch).")
sdxl_base(g, canny=False)
g.add(13, "BlenderObjectPrompts", "Prompts")
g.link(10, 1, 13, "clip"); g.link(11, 0, 13, "conditioning")
# rewire: object prompts feed the depth control instead of the plain positive
for lnk in g.links:
    if lnk[3] == 26 and g.nodes[26]["inputs"][lnk[4]]["name"] == "positive":
        g.nodes[11]["outputs"][0]["links"].remove(lnk[0])
        g.links.remove(lnk)
        g.nodes[26]["inputs"][lnk[4]]["link"] = None
        break
g.link(13, 0, 26, "positive")
g.add(50, "BlenderSelection", "Blender Inputs")
g.add(51, "CLIPTextEncode", "Inpaint (Redo Selection)", title="Change Prompt")
g.add(52, "DifferentialDiffusion", "Inpaint (Redo Selection)")
g.add(53, "ControlNetApplyAdvanced", "Inpaint (Redo Selection)", title="Inpaint Depth", strength=0.6, end_percent=0.8)
g.add(54, "InpaintModelConditioning", "Inpaint (Redo Selection)", noise_mask=True)
g.add(55, "KSampler", "Inpaint (Redo Selection)", title="Inpaint Sampler", steps=28, cfg=6.0,
      sampler_name="dpmpp_2m", scheduler="karras")
g.add(56, "VAEDecode", "Inpaint (Redo Selection)")
g.add(57, "ImageCompositeMasked", "Inpaint (Redo Selection)", title="Keep Outside Mask")
g.link(50, 3, 51, "text"); g.link(10, 1, 51, "clip")
g.link(10, 0, 52, "model")
g.link(51, 0, 53, "positive"); g.link(12, 0, 53, "negative"); g.link(22, 0, 53, "control_net"); g.link(3, 0, 53, "image")
g.link(53, 0, 54, "positive"); g.link(53, 1, 54, "negative"); g.link(10, 2, 54, "vae")
g.link(50, 1, 54, "pixels"); g.link(50, 0, 54, "mask")
g.link(52, 0, 55, "model"); g.link(54, 0, 55, "positive"); g.link(54, 1, 55, "negative"); g.link(54, 2, 55, "latent_image")
g.link(55, 0, 56, "samples"); g.link(10, 2, 56, "vae")
g.link(50, 1, 57, "destination"); g.link(56, 0, 57, "source"); g.link(50, 0, 57, "mask")
g.add(60, "ComfySwitchNode", "Output", title="Redo Selection?")
g.link(50, 2, 60, "switch"); g.link(57, 0, 60, "on_true"); g.link(40, 0, 60, "on_false")
g.add(41, "SaveImage", "Output", filename_prefix="lazy_comfy/sdxl_objects")
g.link(60, 0, 41, "images")
g.save("SDXL · Depth + Objects + Inpaint.json")

# 3) Qwen 2.1 · Depth
g = Graph("Qwen 2.1 · Depth (evaluation only)", ["qwen_image_21_depth"],
          "Qwen-Image 2.1 with ControlNet Union on Blender depth. License qwen-research: evaluation only, no commercial use.")
g.add(1, "BlenderPrompt", "Blender Inputs", positive="Photorealistic interior photograph of a modern living room. "
      "A grey fabric sofa stands against the back wall, a low oak coffee table in front of it, a tall shelf on the right. "
      "Raw concrete walls, warm oak floor, soft daylight, editorial architecture photography.", negative="")
g.add(3, "BlenderPass", "Blender Inputs", title="Blender Pass · Depth", pass_type="depth")
g.add(4, "BlenderRenderSize", "Blender Inputs")
g.add(10, "UNETLoader", "Model", unet_name="qwen_image_2.1_int8_convrot.safetensors")
g.add(11, "QwenImage21Cache", "Model")
g.add(12, "CLIPLoader", "Model", clip_name="qwen3vl_8b_int8_convrot.safetensors", type="qwen_image")
g.add(13, "VAELoader", "Model", vae_name="qwen_image_2.1_vae_bf16.safetensors")
g.link(10, 0, 11, "model")
g.add(20, "TextEncodeQwenImage21", "Prompts", resolution=1024)
g.link(12, 0, 20, "clip"); g.link(1, 0, 20, "prompt"); g.link(1, 1, 20, "negative_prompt")
g.add(21, "ModelPatchLoader", "Control", title="ControlNet Union", name="qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors")
g.add(23, "BlenderSettingFloat", "Control", label="Depth Strength", value=0.9, minimum=0.0, maximum=1.5)
g.add(22, "QwenImageDiffsynthControlnet", "Control", title="Apply Depth")
g.link(11, 0, 22, "model"); g.link(21, 0, 22, "model_patch"); g.link(13, 0, 22, "vae"); g.link(3, 0, 22, "image")
g.link(23, 0, 22, "strength")
g.add(30, "EmptyLatentImage", "Sampler")
g.add(32, "BlenderSettingInt", "Sampler", label="Steps", value=30, minimum=1, maximum=80)
g.add(31, "KSampler", "Sampler", steps=30, cfg=1.0, sampler_name="euler", scheduler="simple")
g.link(4, 0, 30, "width"); g.link(4, 1, 30, "height")
g.link(22, 0, 31, "model"); g.link(20, 0, 31, "positive"); g.link(20, 1, 31, "negative")
g.link(30, 0, 31, "latent_image"); g.link(32, 0, 31, "steps")
g.add(40, "VAEDecode", "Output")
g.link(31, 0, 40, "samples"); g.link(13, 0, 40, "vae")
g.add(41, "SaveImage", "Output", filename_prefix="lazy_comfy/qwen")
g.link(40, 0, 41, "images")
g.add(42, "PreviewImage", "Output", title="Control Preview · Depth")
g.link(3, 0, 42, "images")
g.save("Qwen 2.1 · Depth (evaluation only).json")
