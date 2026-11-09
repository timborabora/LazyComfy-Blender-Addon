import bpy

from . import state


def _draw_param(layout, p):
    if p.kind == "ENUM":
        layout.prop(p, "enum_v", text=p.label)
    elif p.kind == "INT":
        layout.prop(p, "int_v", text=p.label)
    elif p.kind == "FLOAT":
        layout.prop(p, "float01_v" if p.unit_range else "float_v", text=p.label, slider=p.unit_range)
    elif p.kind == "BOOLEAN":
        layout.prop(p, "bool_v", text=p.label)
    else:
        layout.prop(p, "str_v", text=p.label)


class _Sub:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_parent_id = "CB_PT_main"


class CB_PT_main(bpy.types.Panel):
    bl_label = "Comfy Bridge"
    bl_idname = "CB_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge

        # Connection
        box = layout.box()
        row = box.row(align=True)
        if state.connecting:
            row.label(text="Connecting …", icon="SORTTIME")
        elif state.server:
            version = (state.stats or {}).get("system", {}).get("comfyui_version", "")
            row.label(text=f"Connected  ·  ComfyUI {version}", icon="CHECKMARK")
        else:
            row.label(text="Not connected", icon="ERROR")
        row.operator("comfy_bridge.connect", text="", icon="FILE_REFRESH", emboss=False)

        layout.separator(factor=0.5)

        # Workflow
        box = layout.box()
        box.label(text="Workflow", icon="NODETREE")
        row = box.row(align=True)
        row.prop(s, "workflow", text="")
        row.operator("comfy_bridge.reload_workflows", text="", icon="FILE_REFRESH")
        row.operator("comfy_bridge.open_folder", text="", icon="FILE_FOLDER").which = "WORKFLOWS"
        if s.workflow_info:
            box.label(text=s.workflow_info, icon="INFO")
        for line in s.workflow_warnings.splitlines():
            box.label(text=line, icon="ERROR")

        layout.separator(factor=0.5)

        # Actions
        col = layout.column()
        col.scale_y = 1.8
        col.operator("comfy_bridge.render_send", icon="RENDER_STILL")
        layout.separator(factor=0.3)
        col = layout.column()
        col.scale_y = 1.3
        col.operator("comfy_bridge.send", icon="EXPORT")

        layout.separator(factor=0.5)

        # Status
        if s.running:
            row = layout.row(align=True)
            row.progress(factor=s.progress, text=s.status)
            row.operator("comfy_bridge.cancel", text="", icon="CANCEL")
        elif s.last_error:
            box = layout.box()
            first = s.last_error.splitlines()[0]
            box.label(text=first, icon="ERROR" if s.status == "Error" else "INFO")
            if len(s.last_error) > len(first) or len(first) > 60:
                box.operator("comfy_bridge.show_error", text="Details", icon="TEXT")
        else:
            row = layout.row()
            row.label(text=s.status, icon="CHECKMARK" if s.status.startswith("Done") else "DOT")
            row.operator("comfy_bridge.open_folder", text="", icon="FILE_FOLDER", emboss=False).which = "OUTPUT"


class CB_PT_prompts(_Sub, bpy.types.Panel):
    bl_label = "Prompts"

    @classmethod
    def poll(cls, context):
        return any(p.section == "prompt" for p in context.scene.comfy_bridge.params)

    def draw(self, context):
        layout = self.layout
        for p in context.scene.comfy_bridge.params:
            if p.section == "prompt":
                layout.label(text=p.label + ":")
                layout.prop(p, "str_v", text="")
                layout.separator(factor=0.5)


class CB_PT_models(_Sub, bpy.types.Panel):
    bl_label = "Models"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return any(p.section == "model" for p in context.scene.comfy_bridge.params)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column()
        for p in context.scene.comfy_bridge.params:
            if p.section == "model":
                _draw_param(col, p)


class CB_PT_settings(_Sub, bpy.types.Panel):
    bl_label = "Settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.comfy_bridge
        col = layout.column()
        for p in s.params:
            if p.section == "param":
                _draw_param(col, p)
        layout.separator()
        row = layout.row(heading="Seed")
        sub = row.row(align=True)
        sub.enabled = not s.seed_random
        sub.prop(s, "seed", text="")
        row.prop(s, "seed_random", text="", icon="FILE_REFRESH", toggle=True)


class CB_PT_advanced(_Sub, bpy.types.Panel):
    bl_label = "Advanced"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = context.scene.comfy_bridge
        needed = s.workflow_needed.split(",") if s.workflow_needed else []
        col = layout.column(heading="Passes")
        for key, label in (("beauty", "Beauty"), ("depth", "Depth"), ("normal", "Normal"), ("lineart", "Line Art")):
            if key in needed:
                col.label(text=f"{label} (used by workflow)", icon="CHECKBOX_HLT")
            else:
                col.prop(s, "extra_" + key)
        layout.separator()
        col = layout.column()
        col.prop(s, "normal_flip_x")
        col.prop(s, "load_control_images")
        col.prop(s, "show_result")
        col.prop(s, "show_all_models")


classes = (CB_PT_main, CB_PT_prompts, CB_PT_models, CB_PT_settings, CB_PT_advanced)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
