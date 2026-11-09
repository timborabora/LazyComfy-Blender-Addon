import bpy

from . import state


def _help(layout, s, text):
    if s.show_help:
        col = layout.column(align=True)
        col.scale_y = 0.75
        for line in text.split("\n"):
            col.label(text=line)


def _draw_param(layout, p):
    row = layout.row(align=True)
    if p.kind == "ENUM":
        row.prop(p, "enum_v", text=p.label)
    elif p.kind == "INT":
        row.prop(p, "int_v", text=p.label)
    elif p.kind == "FLOAT":
        row.prop(p, "float01_v" if p.unit_range else "float_v", text=p.label, slider=p.unit_range)
    elif p.kind == "BOOLEAN":
        row.prop(p, "bool_v", text=p.label)
    else:
        row.prop(p, "str_v", text=p.label)


class CB_PT_main(bpy.types.Panel):
    bl_label = "Comfy Bridge"
    bl_idname = "CB_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw_header_preset(self, context):
        self.layout.prop(context.scene.comfy_bridge, "show_help", text="", icon="QUESTION", emboss=False)

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        row = layout.row(align=True)
        if state.connecting:
            row.label(text="Suche ComfyUI …", icon="SORTTIME")
        elif state.server:
            version = (state.stats or {}).get("system", {}).get("comfyui_version", "")
            row.label(text=f"Verbunden · {state.server.split('//')[-1]}  {version}", icon="CHECKMARK")
        else:
            row.label(text="Nicht verbunden", icon="ERROR")
        row.operator("comfy_bridge.connect", text="", icon="FILE_REFRESH")
        if state.connect_error and not state.server:
            _help(layout, s, state.connect_error)
        elif not state.server:
            _help(layout, s, "Comfy Desktop starten, dann auf ↻ klicken.")


class _Sub:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_parent_id = "CB_PT_main"


class CB_PT_workflow(_Sub, bpy.types.Panel):
    bl_label = "Workflow"

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        row = layout.row(align=True)
        row.prop(s, "workflow", text="")
        row.operator("comfy_bridge.reload_workflows", text="", icon="FILE_REFRESH")
        row.operator("comfy_bridge.open_folder", text="", icon="FILE_FOLDER").which = "WORKFLOWS"
        if s.workflow_info:
            layout.label(text=s.workflow_info, icon="INFO")
        for line in s.workflow_warnings.splitlines():
            layout.label(text=line, icon="ERROR")
        _help(layout, s, "Eigene Workflows: in ComfyUI über Workflow > Export (API)\n"
                         "in den Workflow-Ordner speichern. Node-Titel BL:beauty, BL:depth …\n"
                         "bekommen Bilder aus Blender, Titel UI:Name erscheinen als Regler.")


class CB_PT_models(_Sub, bpy.types.Panel):
    bl_label = "Modelle (aus ComfyUI)"

    @classmethod
    def poll(cls, context):
        return any(p.section == "model" for p in context.scene.comfy_bridge.params)

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        col = layout.column(align=True)
        for p in s.params:
            if p.section == "model":
                _draw_param(col, p)
        layout.prop(s, "show_all_models")
        if not state.server:
            layout.label(text="Ohne Verbindung keine Auswahlliste.", icon="ERROR")


class CB_PT_prompt(_Sub, bpy.types.Panel):
    bl_label = "Prompt"

    @classmethod
    def poll(cls, context):
        return any(p.section == "prompt" for p in context.scene.comfy_bridge.params)

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        col = layout.column()
        for p in s.params:
            if p.section == "prompt":
                col.label(text=p.label)
                col.prop(p, "str_v", text="")
        _help(layout, s, "Kamera und Perspektive kommen aus Blender –\n"
                         "keine Brennweite oder Blickwinkel in den Prompt schreiben.")


class CB_PT_params(_Sub, bpy.types.Panel):
    bl_label = "Regler"

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        col = layout.column(align=True)
        for p in s.params:
            if p.section == "param":
                _draw_param(col, p)
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = not s.seed_random
        sub.prop(s, "seed")
        row.prop(s, "seed_random", toggle=True)
        _help(layout, s, "Stärke: wie streng das Bild der Vorlage folgt (1 = exakt).\n"
                         "Ende: ab welchem Anteil der Steps die Vorlage losgelassen wird.")


class CB_PT_passes(_Sub, bpy.types.Panel):
    bl_label = "Render-Pässe"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        needed = s.workflow_info.split("braucht:")[-1] if "braucht:" in s.workflow_info else ""
        grid = layout.grid_flow(columns=2, align=True)
        for key, label in (("beauty", "Beauty"), ("depth", "Depth"), ("normal", "Normal"), ("lineart", "Line Art")):
            row = grid.row()
            if label in needed:
                row.label(text=label, icon="CHECKBOX_HLT")
            else:
                row.prop(s, "extra_" + key)
        layout.prop(s, "normal_flip_x")
        layout.prop(s, "load_control_images")
        _help(layout, s, "Pässe, die der Workflow braucht, sind immer an.\n"
                         "Zusätzliche landen nur als Bild „CB · …“ in Blender.\n"
                         "Masken: Node-Titel BL:mask_<Objekt oder Collection>.")


class CB_PT_send(_Sub, bpy.types.Panel):
    bl_label = "Senden"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge
        col = layout.column(align=True)
        col.scale_y = 1.6
        col.operator("comfy_bridge.render_send", icon="PLAY")
        row = layout.row(align=True)
        row.operator("comfy_bridge.send", icon="EXPORT")
        row.operator("comfy_bridge.open_folder", text="Ergebnisse", icon="FILE_FOLDER").which = "OUTPUT"
        if s.running:
            row = layout.row(align=True)
            row.progress(factor=s.progress, text=s.status)
            row.operator("comfy_bridge.cancel", text="", icon="CANCEL")
        else:
            layout.label(text=s.status + (f" · letzter Seed {s.last_seed}" if s.last_seed and "Seed" not in s.status else ""))
        if s.last_error:
            box = layout.box()
            lines = s.last_error.splitlines()
            for line in lines[:4]:
                box.label(text=line, icon="ERROR" if s.status == "Fehler" else "INFO")
            if len(lines) > 4 or any(len(l) > 60 for l in lines):
                box.operator("comfy_bridge.show_error", text="Ganze Meldung", icon="TEXT")


classes = (CB_PT_main, CB_PT_workflow, CB_PT_models, CB_PT_prompt, CB_PT_params, CB_PT_passes, CB_PT_send)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
