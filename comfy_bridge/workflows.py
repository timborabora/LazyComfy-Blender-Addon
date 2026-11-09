"""Workflow-Dateien (ComfyUI API-Format) finden und auswerten.

Konvention über Node-Titel (in ComfyUI: Rechtsklick auf Node > Title):
  BL:beauty, BL:depth, BL:normal, BL:lineart, BL:mask_<Name>
      LoadImage-Nodes, die das jeweilige Bild aus Blender bekommen.
  BL:size     Empty-Latent-Node, der die Render-Auflösung bekommt.
              Fehlt er, bekommen alle Empty*LatentImage-Nodes die Auflösung.
  BL:result   SaveImage-Node, dessen Bild als Hauptergebnis gilt (optional).
  UI:<Label>  Alle Werte dieses Nodes erscheinen als Felder im Panel.
Modell-Dateien (Checkpoints, ControlNets, ...) werden immer als Dropdown gezeigt.
"""

import glob
import json
import os

from . import comfy_client

PASS_KEYS = ("beauty", "depth", "normal", "lineart")
PASS_LABELS = {"beauty": "Beauty", "depth": "Depth", "normal": "Normal", "lineart": "Line Art"}
SEED_INPUTS = ("seed", "noise_seed")
PROMPT_INPUTS = ("text", "t5xxl", "clip_l", "prompt")
FLUX_CLASSES = {"UNETLoader", "UnetLoaderGGUF", "CLIPTextEncodeFlux", "DualCLIPLoader", "DualCLIPLoaderGGUF"}

PRETTY = {
    "strength": "Stärke",
    "start_percent": "Start",
    "end_percent": "Ende",
    "steps": "Steps",
    "cfg": "CFG",
    "denoise": "Denoise",
    "sampler_name": "Sampler",
    "scheduler": "Scheduler",
    "guidance": "Guidance",
    "low_threshold": "Low",
    "high_threshold": "High",
    "text": "Text",
    "t5xxl": "T5 (Sätze)",
    "clip_l": "CLIP-L (Stichworte)",
    "ckpt_name": "Checkpoint",
    "control_net_name": "ControlNet",
    "unet_name": "Diffusionsmodell",
    "vae_name": "VAE",
    "clip_name": "Text-Encoder",
    "clip_name1": "Text-Encoder 1",
    "clip_name2": "Text-Encoder 2",
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
    """Liste von (pfad, anzeigename, ist_beispiel) über alle Ordner."""
    found = []
    for folder, is_example in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            name = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
            found.append((path, name + (" (Beispiel)" if is_example else ""), is_example))
    return found


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise WorkflowError(f"Workflow nicht lesbar: {e}") from e
    if isinstance(data, dict) and "nodes" in data and "links" in data:
        raise WorkflowError(
            "Das ist ein normaler ComfyUI-Workflow, kein API-Format. "
            "In ComfyUI über Workflow > Export (API) speichern."
        )
    if not isinstance(data, dict) or not all(isinstance(n, dict) and "class_type" in n for n in data.values()):
        raise WorkflowError("Unbekanntes Dateiformat: erwartet wird ein ComfyUI-Workflow im API-Format.")
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
    """Liest aus einem Workflow, welche Bilder, Modelle und Regler er braucht."""
    result = {
        "images": {},      # pass_key -> [node_id]
        "size_nodes": [],
        "result_nodes": [],
        "params": [],      # dicts, siehe _param()
        "family": "",
        "warnings": [],
    }
    classes = {n["class_type"] for n in workflow.values()}
    if classes & FLUX_CLASSES:
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

        if low.startswith("bl:"):
            tag = low[3:].strip()
            if tag in PASS_KEYS or tag.startswith("mask_"):
                if "image" not in inputs:
                    result["warnings"].append(f"{title}: Node hat keinen image-Eingang (LoadImage verwenden).")
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
        literal = [(k, v) for k, v in inputs.items() if not is_link(v)]
        specs = {k: comfy_client.parse_spec(comfy_client.spec_of(object_info, cls, k)) for k, _ in literal}
        model_inputs = [k for k, v in literal if specs[k][0] == "ENUM" and _is_model_value(v, specs[k][1].get("options"))]
        ui_inputs = []
        for name, value in literal:
            kind, opts = specs[name]
            if name in model_inputs:
                # Node-Titel unterscheidet z.B. "ControlNet Canny" von "ControlNet Depth"
                plain = title if title and not low.startswith(("bl:", "ui:")) else (label_base if exposed else "")
                if plain and len(model_inputs) == 1:
                    label = plain
                elif plain:
                    label = f"{plain} · {_pretty(name)}"
                else:
                    label = _pretty(name)
                result["params"].append(_param(node_id, cls, name, label, "model", "ENUM", value, opts))
                continue
            if not exposed or name in SEED_INPUTS or name == "image":
                continue
            ui_inputs.append((name, value, kind, opts))
        for name, value, kind, opts in ui_inputs:
            if kind is None:
                kind = {bool: "BOOLEAN", int: "INT", float: "FLOAT"}.get(type(value), "STRING")
            label = label_base if len(ui_inputs) == 1 else f"{label_base} · {_pretty(name)}"
            section = "prompt" if kind == "STRING" and (opts.get("multiline") or name in PROMPT_INPUTS) else "param"
            result["params"].append(_param(node_id, cls, name, label, section, kind, value, opts))

    if not result["size_nodes"]:
        result["size_nodes"] = empty_latents
    if not result["images"]:
        result["warnings"].append(
            "Kein Node mit Titel BL:beauty / BL:depth / ... gefunden – der Workflow bekommt kein Bild aus Blender."
        )
    return result


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
        names.append(PASS_LABELS.get(key, "Maske " + key[5:] if key.startswith("mask:") else key))
    parts.append("braucht: " + (", ".join(names) if names else "nichts aus Blender"))
    return " · ".join(parts)


def filter_models(options, input_name, family, show_all):
    """ControlNets nach Modellfamilie filtern (am Dateinamen, das ist eine Heuristik)."""
    if show_all or input_name != "control_net_name" or not family:
        return list(options)
    if family == "Flux":
        return [o for o in options if "flux" in o.lower()]
    return [o for o in options if "flux" not in o.lower()]
