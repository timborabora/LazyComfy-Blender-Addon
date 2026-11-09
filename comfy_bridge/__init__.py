"""Comfy Bridge – Blender rendert, ComfyUI rechnet.

Blender ist nur die Fernbedienung: Render und Render-Pässe gehen per HTTP an das
lokale ComfyUI, das Ergebnis kommt in den Image Editor zurück.
"""

import bpy

from . import operators, props, state, ui


class CB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    server_url: bpy.props.StringProperty(
        name="Server",
        description="Leer lassen = automatisch suchen (Ports 8188, 8000, …). Sonst z.B. http://127.0.0.1:8188",
    )
    workflow_dir: bpy.props.StringProperty(
        name="Eigene Workflows",
        description="Ordner mit eigenen Workflows (API-JSON). Die mitgelieferten Beispiele bleiben zusätzlich verfügbar",
        subtype="DIR_PATH",
    )
    output_dir: bpy.props.StringProperty(
        name="Ergebnis-Ordner",
        description="Leer = Ordner „comfy_bridge_output“ neben der .blend-Datei (oder Temp, wenn ungespeichert)",
        subtype="DIR_PATH",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "server_url")
        layout.prop(self, "workflow_dir")
        layout.prop(self, "output_dir")


def _auto_connect():
    props.refresh_workflow_items()
    operators.connect_async()
    return None


@bpy.app.handlers.persistent
def _on_load(_dummy):
    # Dropdown-Inhalte leben nicht in der .blend, also nach dem Öffnen neu holen
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
