"""Find and analyse workflow files (ComfyUI API format).

Convention via node titles (in ComfyUI: right-click node > Title):
  BL:beauty, BL:depth, BL:normal, BL:lineart, BL:mask_<name>
      Load Image nodes that receive the matching image from Blender.
  BL:size     Empty latent node that receives the render resolution.
              Without it, all Empty*LatentImage nodes get the resolution.
  BL:result   Save Image node whose image counts as the main result (optional).
  UI:<Label>  All values of this node appear as fields in the panel.
Model files (checkpoints, ControlNets, ...) always appear as dropdowns.
"""

import glob
import json
import os
import re

from . import comfy_client

PASS_KEYS = ("beauty", "depth", "normal", "lineart")
PASS_LABELS = {"beauty": "Beauty", "depth": "Depth", "normal": "Normal", "lineart": "Line Art"}
SEED_INPUTS = ("seed", "noise_seed")
PROMPT_INPUTS = ("text", "t5xxl", "clip_l", "prompt", "negative_prompt")
FLUX_CLASSES = {"UNETLoader", "UnetLoaderGGUF", "CLIPTextEncodeFlux", "DualCLIPLoader", "DualCLIPLoaderGGUF"}

PRETTY = {
    "strength": "Strength",
    "start_percent": "Start",
    "end_percent": "End",
    "steps": "Steps",
    "cfg": "CFG",
    "denoise": "Denoise",
    "sampler_name": "Sampler",
    "scheduler": "Scheduler",
    "guidance": "Guidance",
    "low_threshold": "Low",
    "high_threshold": "High",
    "text": "Text",
    "prompt": "Positive",
    "negative_prompt": "Negative",
    "resolution": "Reference Resolution",
    "t5xxl": "T5 (sentences)",
    "clip_l": "CLIP-L (keywords)",
    "ckpt_name": "Checkpoint",
    "control_net_name": "ControlNet",
    "unet_name": "Diffusion Model",
    "vae_name": "VAE",
    "clip_name": "Text Encoder",
    "clip_name1": "Text Encoder 1",
    "clip_name2": "Text Encoder 2",
    "lora_name": "LoRA",
    "upscale_model_name": "Upscaler",
}


class WorkflowError(RuntimeError):
    pass


def title_of(node):
    return (node.get("_meta") or {}).get("title", "") or ""


def is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)


def scan(folders):
    """List of (path, display name, is_example) across all folders."""
    found = []
    for folder, is_example in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            name = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
            found.append((path, name + (" (example)" if is_example else ""), is_example))
    return found


def is_edit_workflow(path):
    """Edit workflows take the previous result (BL:result_prev) instead of a fresh render."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return '"bl:result_prev"' in f.read().lower()
    except OSError:
        return False


COMFY_PREFIX = "comfy:"
BLENDER_SETTINGS = {"BlenderSettingFloat": "FLOAT", "BlenderSettingInt": "INT", "BlenderSettingBool": "BOOLEAN"}


def display_info(ui, fallback_name):
    """(menu label, tooltip) of a saved workflow.

    Examples carry extra.lazy_comfy {title, purpose, description}. Own workflows can add a
    Note node titled "Lazy Comfy": first line = purpose, the rest = tooltip.
    """
    extra = ui.get("extra") or {}
    meta = extra.get("lazy_comfy") or extra.get("comfy_bridge") or {}
    title = meta.get("title") or ""
    purpose, tooltip = meta.get("purpose") or "", meta.get("description") or ""
    if not purpose:
        for node in ui.get("nodes", []):
            if node.get("type") in ("Note", "MarkdownNote") and (node.get("title") or "").strip().lower() == "lazy comfy":
                text = str((node.get("widgets_values") or [""])[0]).strip()
                purpose, _, tooltip = text.partition("\n")
                purpose, tooltip = purpose.strip(), tooltip.strip()
                break
    label = title or fallback_name
    if purpose and f"({purpose})" not in label:
        label = f"{label} ({purpose})"
    return label, tooltip


def has_blender_nodes(ui):
    return any(str(n.get("type", "")).startswith("Blender") for n in ui.get("nodes", []))


def load(path, fresh=False):
    """API-format workflow. `comfy:<path>` = saved in ComfyUI (UI format, converted here);
    anything else is an API-format JSON file. `fresh` re-reads the ComfyUI file first."""
    if path.startswith(COMFY_PREFIX):
        from . import state, templates, ui_convert
        rel = path[len(COMFY_PREFIX):]
        entry = state.comfy_workflows.get(path)
        if (fresh or entry is None) and state.server:
            ui = templates.fetch_workflow(state.server, rel)
            if ui is not None:
                entry = state.comfy_workflows[path] = {"ui": ui}
        if entry is None:
            raise WorkflowError(f"Workflow '{rel}' not found in ComfyUI. Reconnect or save it again.")
        try:
            return ui_convert.convert(entry["ui"], state.object_info)
        except ui_convert.ConvertError as e:
            raise WorkflowError(str(e)) from e
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise WorkflowError(f"Can't read workflow: {e}") from e
    if isinstance(data, dict) and "nodes" in data and "links" in data:
        raise WorkflowError("Not in API format. In ComfyUI use Workflow > Export (API).")
    if not isinstance(data, dict) or not all(isinstance(n, dict) and "class_type" in n for n in data.values()):
        raise WorkflowError("Unknown file format: expected a ComfyUI workflow in API format.")
    return data


def _sorted_ids(workflow):
    return sorted(workflow, key=lambda k: (int(k) if str(k).isdigit() else 10**9, str(k)))


def _pretty(name):
    return PRETTY.get(name, name.replace("_", " ").capitalize())


def _is_model_value(value, options):
    if isinstance(value, str) and value.lower().endswith(comfy_client.MODEL_EXTENSIONS):
        return True
    return any(isinstance(o, str) and o.lower().endswith(comfy_client.MODEL_EXTENSIONS) for o in options or [])


def analyze(workflow, object_info):
    """Work out which images, models and controls a workflow needs."""
    result = {
        "images": {},      # pass_key -> [node_id]
        "size_nodes": [],
        "result_nodes": [],
        "params": [],      # dicts, see _param()
        "family": "",
        "warnings": [],
        "regions": {},     # slot number -> {"apply": id, "mask": id, "prompt": id}
        "prev_nodes": [],  # BL:result_prev – previous result for editing
        "selection_nodes": [],
        "edit_prompt_nodes": [],
        "object_nodes": [],         # BlenderObjectPrompts
        "blender_selection": [],    # BlenderSelection
        "node_based": False,        # uses Lazy Comfy nodes instead of title conventions
    }
    classes = {n["class_type"] for n in workflow.values()}
    if any(c.startswith(("QwenImage", "TextEncodeQwenImage")) for c in classes):
        result["family"] = "Qwen-Image"
    elif classes & FLUX_CLASSES:
        result["family"] = "Flux"
    elif "CheckpointLoaderSimple" in classes:
        result["family"] = "SDXL"

    empty_latents = []
    for node_id in _sorted_ids(workflow):
        node = workflow[node_id]
        cls = node["class_type"]
        title = title_of(node).strip()
        inputs = node.get("inputs", {})
        low = title.lower()

        if cls.startswith("Blender"):
            result["node_based"] = True
            if cls == "BlenderPass":
                result["images"].setdefault(inputs.get("pass_type", "beauty"), []).append(node_id)
            elif cls == "BlenderPrompt":
                for name, label in (("positive", "Prompt"), ("negative", "Negative")):
                    if not is_link(inputs.get(name)):
                        result["params"].append(_param(node_id, cls, name, label, "prompt", "STRING",
                                                       inputs.get(name, ""), {"multiline": True}))
            elif cls in BLENDER_SETTINGS:
                kind = BLENDER_SETTINGS[cls]
                opts = {} if kind == "BOOLEAN" else {"min": inputs.get("minimum"), "max": inputs.get("maximum")}
                result["params"].append(_param(node_id, cls, "value", str(inputs.get("label") or "Setting"),
                                               "setting", kind, inputs.get("value"), opts))
            elif cls == "BlenderRenderSize":
                result["size_nodes"].append(node_id)
            elif cls == "BlenderObjectPrompts":
                result["object_nodes"].append(node_id)
            elif cls == "BlenderSelection":
                result["blender_selection"].append(node_id)
            continue

        if low.startswith("bl:"):
            tag = low[3:].strip()
            region = re.fullmatch(r"region_(\d+)(?:_(mask|prompt))?", tag)
            if region:
                slot = result["regions"].setdefault(int(region.group(1)), {})
                slot[region.group(2) or "apply"] = node_id
            elif tag == "result_prev":
                result["prev_nodes"].append(node_id)
            elif tag == "mask_selection":
                result["selection_nodes"].append(node_id)
            elif tag == "edit_prompt":
                result["edit_prompt_nodes"].append(node_id)
            elif tag in PASS_KEYS or tag.startswith("mask_"):
                if "image" not in inputs:
                    result["warnings"].append(f"{title}: node has no image input (use Load Image).")
                else:
                    key = tag if tag in PASS_KEYS else "mask:" + title[3:].strip()[5:]
                    result["images"].setdefault(key, []).append(node_id)
            elif tag == "size":
                result["size_nodes"].append(node_id)
            elif tag == "result":
                result["result_nodes"].append(node_id)
        if "width" in inputs and "height" in inputs and cls.startswith("Empty"):
            empty_latents.append(node_id)

        exposed = low.startswith("ui:")
        label_base = title[3:].strip() if exposed else (title or cls)
        only = None
        # "UI:Prompt [prompt]" exposes only the inputs listed in brackets
        if exposed and label_base.endswith("]") and "[" in label_base:
            label_base, _, listed = label_base[:-1].partition("[")
            label_base = label_base.strip()
            only = {n.strip() for n in listed.split(",") if n.strip()}
        literal = [(k, v) for k, v in inputs.items() if not is_link(v)]
        specs = {k: comfy_client.parse_spec(comfy_client.spec_of(object_info, cls, k)) for k, _ in literal}
        model_inputs = [k for k, v in literal if specs[k][0] == "ENUM" and _is_model_value(v, specs[k][1].get("options"))]
        ui_inputs = []
        for name, value in literal:
            kind, opts = specs[name]
            if name in model_inputs:
                # the node title tells e.g. "ControlNet Canny" from "ControlNet Depth"
                plain = title if title and not low.startswith(("bl:", "ui:")) else (label_base if exposed else "")
                if plain and len(model_inputs) == 1:
                    label = plain
                elif plain:
                    label = f"{plain} · {_pretty(name)}"
                else:
                    label = _pretty(name)
                result["params"].append(_param(node_id, cls, name, label, "model", "ENUM", value, opts))
                continue
            if not exposed or name in SEED_INPUTS or name == "image" or (only is not None and name not in only):
                continue
            ui_inputs.append((name, value, kind, opts))
        prompt_count = sum(1 for n, v, k, o in ui_inputs if _is_prompt(n, v, k, o))
        for name, value, kind, opts in ui_inputs:
            if kind is None:
                kind = {bool: "BOOLEAN", int: "INT", float: "FLOAT"}.get(type(value), "STRING")
            section = "prompt" if _is_prompt(name, value, kind, opts) else "param"
            if len(ui_inputs) == 1:
                label = label_base
            elif section == "prompt" and prompt_count > 1:
                label = _pretty(name)  # e.g. "Positive" / "Negative" instead of "Prompt · Positive"
            else:
                label = f"{label_base} · {_pretty(name)}"
            result["params"].append(_param(node_id, cls, name, label, section, kind, value, opts))

    if not result["size_nodes"] and not result["node_based"]:
        result["size_nodes"] = empty_latents
    for n, slot in sorted(result["regions"].items()):
        if set(slot) != {"apply", "mask", "prompt"}:
            result["warnings"].append(f"Region {n} needs BL:region_{n}, BL:region_{n}_mask and BL:region_{n}_prompt.")
    result["regions"] = {n: s for n, s in result["regions"].items() if set(s) == {"apply", "mask", "prompt"}}
    if not result["images"] and not result["prev_nodes"] and not result["node_based"]:
        result["warnings"].append("No BL:beauty / BL:depth / … node – the workflow gets no image from Blender.")
    return result


def _is_prompt(name, value, kind, opts):
    is_string = kind == "STRING" or (kind is None and isinstance(value, str))
    return is_string and (opts.get("multiline") or name in PROMPT_INPUTS)


def _param(node_id, cls, name, label, section, kind, value, opts):
    return {
        "key": f"{node_id}:{name}",
        "node_id": node_id,
        "node_class": cls,
        "input": name,
        "label": label,
        "section": section,
        "kind": kind,
        "value": value,
        "min": opts.get("min"),
        "max": opts.get("max"),
        "step": opts.get("step"),
        "options": opts.get("options") or [],
        "tooltip": opts.get("tooltip", ""),
    }


def needed_passes(analysis):
    return [k for k in analysis["images"]]


def describe(analysis):
    parts = []
    if analysis["family"]:
        parts.append(analysis["family"])
    names = []
    for key in analysis["images"]:
        names.append(PASS_LABELS.get(key, "Mask " + key[5:] if key.startswith("mask:") else key))
    parts.append(", ".join(names) if names else "no Blender input")
    if analysis["regions"]:
        parts.append(f"{len(analysis['regions'])} object prompts")
    elif analysis["object_nodes"]:
        parts.append("object prompts")
    if analysis["blender_selection"]:
        parts.append("Redo Selection")
    return "  ·  ".join(parts)


def filter_models(options, input_name, family, show_all):
    """Filter ControlNets by model family (by file name – a heuristic)."""
    if show_all or input_name != "control_net_name" or not family:
        return list(options)
    if family == "Flux":
        return [o for o in options if "flux" in o.lower()]
    return [o for o in options if "flux" not in o.lower()]
