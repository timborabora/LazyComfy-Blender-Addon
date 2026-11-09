"""Comfy Bridge – Blender renders, ComfyUI computes.

Blender is only the remote control: render and render passes go over HTTP to the
local ComfyUI, the result comes back into the Image Editor.
"""

import bpy

from . import operators, props, state, ui


class CB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    server_url: bpy.props.StringProperty(
        name="Server",
        description="Leave empty to search automatically (ports 8188, 8000, …). Otherwise e.g. http://127.0.0.1:8188",
    )
    workflow_dir: bpy.props.StringProperty(
        name="Workflow Folder",
        description="Folder with your own workflows (API JSON). The bundled examples stay available",
        subtype="DIR_PATH",
    )
    output_dir: bpy.props.StringProperty(
        name="Output Folder",
        description="Empty = folder 'comfy_bridge_output' next to the .blend file (or temp if unsaved)",
        subtype="DIR_PATH",
    )
    models_dir: bpy.props.StringProperty(
        name="ComfyUI Models Folder",
        description="Where model packages are installed. Empty = models folder from Comfy Desktop's settings",
        subtype="DIR_PATH",
    )
    comfyui_dir: bpy.props.StringProperty(
        name="ComfyUI Folder",
        description="ComfyUI folder that holds custom_nodes (for the Blender nodes). Empty = active Comfy Desktop installation",
        subtype="DIR_PATH",
    )
    hf_token: bpy.props.StringProperty(
        name="Hugging Face Token",
        description="Only needed for gated models. Stored in Blender's preferences, never in .blend files",
        subtype="PASSWORD",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "server_url")
        layout.prop(self, "workflow_dir")
        layout.prop(self, "output_dir")
        layout.separator()
        layout.prop(self, "models_dir")
        layout.prop(self, "comfyui_dir")
        layout.prop(self, "hf_token")


def _auto_connect():
    props.refresh_workflow_items()
    operators.connect_async()
    return None


@bpy.app.handlers.persistent
def _on_load(_dummy):
    # Dropdown contents don't live in the .blend, so fetch them again after opening
    props.refresh_workflow_items()
    if state.server:
        for scene in bpy.data.scenes:
            operators.rebuild_params(scene, save_old=True)
    elif not bpy.app.background:
        operators.connect_async()


def register():
    bpy.utils.register_class(CB_Preferences)
    props.register()
    operators.register()
    ui.register()
    bpy.app.handlers.load_post.append(_on_load)
    if not bpy.app.background:
        bpy.app.timers.register(_auto_connect, first_interval=1.0, persistent=True)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if state.job:
        state.job.cancel()
    ui.unregister()
    operators.unregister()
    props.unregister()
    bpy.utils.unregister_class(CB_Preferences)
