import hashlib
import json
import os

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths
import node_helpers

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDERS = os.path.join(HERE, "placeholders")
PASSES = ["beauty", "depth", "lineart", "normal"]
CATEGORY = "Comfy Bridge"
SET_BY_BLENDER = "Set by Blender when it sends a render. Empty = built-in placeholder."


def _input_path(name):
    """Path of an uploaded file in ComfyUI's input folder, or None."""
    if name and folder_paths.exists_annotated_filepath(name):
        return folder_paths.get_annotated_filepath(name)
    return None


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _load_image(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None,]


def _load_mask(path, size=None):
    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    if size and img.size != size:
        img = img.resize(size, Image.BILINEAR)
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None,]


class BlenderPass:
    """A render pass from Blender: beauty, depth, line art or normal."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "pass_type": (PASSES, {"default": "depth"}),
            "image": ("STRING", {"default": "", "tooltip": SET_BY_BLENDER}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load"
    CATEGORY = CATEGORY
    DESCRIPTION = "Render pass from Blender. Runs with a placeholder of the blockout room when Blender sent nothing."

    def load(self, pass_type, image):
        path = _input_path(image) or os.path.join(PLACEHOLDERS, f"{pass_type}.png")
        return (_load_image(path),)

    @classmethod
    def IS_CHANGED(cls, pass_type, image):
        path = _input_path(image)
        return _file_hash(path) if path else f"placeholder:{pass_type}"


class BlenderPrompt:
    """Main prompt from the Blender panel."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "positive": ("STRING", {"multiline": True, "default":
                "Photorealistic interior photograph of a modern living room, concrete walls, oak floor, "
                "soft daylight, editorial architecture photography."}),
            "negative": ("STRING", {"multiline": True, "default":
                "cartoon, illustration, drawing, painting, cgi, 3d render, plastic, blurry"}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "get"
    CATEGORY = CATEGORY
    DESCRIPTION = "Prompt and negative prompt. Blender replaces both with the text from its panel."

    def get(self, positive, negative):
        return (positive, negative)


class BlenderObjectPrompts:
    """Adds one masked prompt per Blender object to the conditioning."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": ("CLIP",),
            "conditioning": ("CONDITIONING",),
            "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.05,
                                   "tooltip": "How strongly an object's prompt wins inside its mask"}),
            "objects": ("STRING", {"default": "[]", "tooltip": SET_BY_BLENDER +
                                   " JSON list of {name, prompt, mask}."}),
        }}

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "apply"
    CATEGORY = CATEGORY
    DESCRIPTION = "Object prompts from Blender, each limited to the object's mask. Without objects it passes the conditioning through."

    def apply(self, clip, conditioning, strength, objects):
        try:
            entries = json.loads(objects or "[]")
        except ValueError:
            entries = []
        result = list(conditioning)
        for entry in entries:
            path = _input_path(entry.get("mask", ""))
            prompt = (entry.get("prompt") or "").strip()
            if not path or not prompt:
                continue
            cond = clip.encode_from_tokens_scheduled(clip.tokenize(prompt))
            mask = _load_mask(path)
            result += node_helpers.conditioning_set_values(
                cond, {"mask": mask, "set_area_to_bounds": False, "mask_strength": strength})
        return (result,)

    @classmethod
    def IS_CHANGED(cls, clip, conditioning, strength, objects):
        try:
            entries = json.loads(objects or "[]")
        except ValueError:
            return objects
        hashes = [(_file_hash(p) if (p := _input_path(e.get("mask", ""))) else "") for e in entries]
        return json.dumps([objects, strength, hashes])


class BlenderSelection:
    """Mask of the objects selected in Blender, the previous result and the change prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mask": ("STRING", {"default": "", "tooltip": SET_BY_BLENDER}),
            "previous": ("STRING", {"default": "", "tooltip": SET_BY_BLENDER}),
            "change": ("STRING", {"multiline": True, "default": "",
                                  "tooltip": "What the selected objects should become. Set by Blender."}),
        }}

    RETURN_TYPES = ("MASK", "IMAGE", "BOOLEAN", "STRING")
    RETURN_NAMES = ("mask", "previous", "has_selection", "change")
    FUNCTION = "load"
    CATEGORY = CATEGORY
    DESCRIPTION = ("For Redo Selection in Blender. has_selection is False for a normal render, "
                   "so a switch can skip the inpaint branch.")

    def load(self, mask, previous, change):
        prev_path = _input_path(previous)
        mask_path = _input_path(mask)
        image = _load_image(prev_path or os.path.join(PLACEHOLDERS, "beauty.png"))
        size = (image.shape[2], image.shape[1])
        if prev_path and mask_path:
            return (_load_mask(mask_path, size), image, True, change)
        return (torch.zeros((1, size[1], size[0])), image, False, change)

    @classmethod
    def IS_CHANGED(cls, mask, previous, change):
        parts = [(_file_hash(p) if (p := _input_path(x)) else "") for x in (mask, previous)]
        return json.dumps(parts + [change])


class BlenderRenderSize:
    """Render resolution from Blender (rounded to multiples of 8)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8}),
            "height": ("INT", {"default": 768, "min": 64, "max": 8192, "step": 8}),
        }}

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "get"
    CATEGORY = CATEGORY
    DESCRIPTION = "Resolution from Blender's render settings."

    def get(self, width, height):
        return (width, height)


def _setting(type_name, widget):
    class Setting:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"label": ("STRING", {"default": "Setting",
                                                      "tooltip": "Name of the control in the Blender panel"}),
                                 **widget}}

        RETURN_TYPES = (type_name,)
        RETURN_NAMES = ("value",)
        FUNCTION = "get"
        CATEGORY = CATEGORY
        DESCRIPTION = "Shows up as a control in the Blender panel. Blender sets the value when it sends."

        def get(self, label, value, minimum=None, maximum=None):
            if minimum is not None and maximum is not None and minimum <= maximum:
                value = max(minimum, min(maximum, value))
            return (value,)

    return Setting


BlenderSettingFloat = _setting("FLOAT", {
    "value": ("FLOAT", {"default": 1.0, "min": -10000.0, "max": 10000.0, "step": 0.01}),
    "minimum": ("FLOAT", {"default": 0.0, "min": -10000.0, "max": 10000.0, "step": 0.01}),
    "maximum": ("FLOAT", {"default": 1.0, "min": -10000.0, "max": 10000.0, "step": 0.01}),
})
BlenderSettingInt = _setting("INT", {
    "value": ("INT", {"default": 25, "min": -100000, "max": 100000}),
    "minimum": ("INT", {"default": 1, "min": -100000, "max": 100000}),
    "maximum": ("INT", {"default": 100, "min": -100000, "max": 100000}),
})
BlenderSettingBool = _setting("BOOLEAN", {"value": ("BOOLEAN", {"default": True})})


NODE_CLASS_MAPPINGS = {
    "BlenderPass": BlenderPass,
    "BlenderPrompt": BlenderPrompt,
    "BlenderObjectPrompts": BlenderObjectPrompts,
    "BlenderSelection": BlenderSelection,
    "BlenderRenderSize": BlenderRenderSize,
    "BlenderSettingFloat": BlenderSettingFloat,
    "BlenderSettingInt": BlenderSettingInt,
    "BlenderSettingBool": BlenderSettingBool,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "BlenderPass": "Blender Pass",
    "BlenderPrompt": "Blender Prompt",
    "BlenderObjectPrompts": "Blender Object Prompts",
    "BlenderSelection": "Blender Selection",
    "BlenderRenderSize": "Blender Render Size",
    "BlenderSettingFloat": "Blender Setting (Float)",
    "BlenderSettingInt": "Blender Setting (Int)",
    "BlenderSettingBool": "Blender Setting (Bool)",
}
