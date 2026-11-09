"""Comfy Bridge nodes: the inputs a workflow gets from Blender.

Every node has a built-in placeholder (the blockout room), so a workflow also runs
on its own in ComfyUI. The Comfy Bridge Blender add-on fills the inputs when it
sends a render: file names of uploaded passes and masks, prompts, settings.
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
