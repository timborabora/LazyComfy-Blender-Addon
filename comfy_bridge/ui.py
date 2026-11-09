import os

import bpy

from . import state


def _draw_param(layout, p, text=None):
    text = p.label if text is None else text
    if p.kind == "ENUM":
        layout.prop(p, "enum_v", text=text)
    elif p.kind == "INT":
        layout.prop(p, "int_v", text=text)
    elif p.kind == "FLOAT":
        layout.prop(p, "float01_v" if p.unit_range else "float_v", text=text, slider=p.unit_range)
    elif p.kind == "BOOLEAN":
        layout.prop(p, "bool_v", text=text)
    else:
        layout.prop(p, "str_v", text=text)


def _draw_problems(layout, s):
    """Only what is missing or broken – nothing when the workflow is ready."""
    from . import installer, operators
    for pkg_id in filter(None, s.missing_packages.split(",")):
        pkg = installer.package(pkg_id)
        if not pkg:
            continue
        _, todo = installer.status(operators.models_dir(), pkg)
        row = layout.row(align=True)
        row.alert = True
        row.label(text=f"Missing: {pkg['name']} ({installer.human_size(todo)})", icon="ERROR")
        row.operator("comfy_bridge.install_package", text="Install").package_id = pkg_id
    missing = [n for n in s.missing_nodes.split(",") if n]
    if any(n.startswith("Blender") for n in missing):
        row = layout.row(align=True)
        row.alert = True
        row.label(text="Blender nodes not loaded in ComfyUI", icon="ERROR")
        row.operator("comfy_bridge.install_nodes", text="Install")
    others = [n for n in missing if not n.startswith("Blender")]
    if others:
        layout.label(text="Missing ComfyUI nodes: " + ", ".join(others[:3]) + (" …" if len(others) > 3 else ""),
                     icon="ERROR")
    for line in s.workflow_warnings.splitlines():
        layout.label(text=line, icon="ERROR")


def _section(layout, idname, title, closed=True):
    header, body = layout.panel(idname, default_closed=closed)
    header.label(text=title)
    return body


class CB_PT_main(bpy.types.Panel):
    bl_label = "Comfy Bridge"
    bl_idname = "CB_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw_header_preset(self, context):
        row = self.layout.row(align=True)
        if state.connecting:
            row.label(text="", icon="SORTTIME")
        else:
            row.label(text="", icon="STRIP_COLOR_04" if state.server else "STRIP_COLOR_01")  # green / red dot
        row.operator("comfy_bridge.connect", text="", icon="FILE_REFRESH", emboss=False)

    def draw(self, context):
        layout = self.layout
        s = context.scene.comfy_bridge

        if not state.server and not state.connecting:
            box = layout.box()
            box.label(text="ComfyUI not connected", icon="ERROR")
            box.label(text=state.connect_error or "Start Comfy Desktop, then click ↻")
            return

        # Workflow
        box = layout.box()
        box.prop(s, "workflow", text="")
        _draw_problems(box, s)

        # Prompt
        prompt = next((p for p in s.params if p.section == "prompt" and p.label in ("Prompt", "Positive")), None)
        prompts = [p for p in s.params if p.section == "prompt"]
        main_prompts = [prompt] if prompt else prompts[:1]
        for p in main_prompts:
            row = layout.row(align=True)
            row.label(text=p.label)
            row.operator("comfy_bridge.edit_prompt", text="", icon="GREASEPENCIL", emboss=False).key = p.key
            layout.prop(p, "str_v", text="")
        rest = [p for p in prompts if p not in main_prompts]
        if rest:
            body = _section(layout, "CB_negative", "Negative" if len(rest) == 1 else "More Prompts")
            if body:
                for p in rest:
                    if len(rest) > 1:
                        body.label(text=p.label)
                    row = body.row(align=True)
                    row.prop(p, "str_v", text="")
                    row.operator("comfy_bridge.edit_prompt", text="", icon="GREASEPENCIL").key = p.key

        # The workflow's Blender settings
        settings = [p for p in s.params if p.section == "setting"]
        if settings:
            col = layout.column(align=True)
            col.use_property_split = True
            col.use_property_decorate = False
            for p in settings:
                _draw_param(col, p)

        # Render
        layout.separator(factor=0.5)
        row = layout.row(align=True)
        row.scale_y = 1.8
        row.operator("comfy_bridge.render_send", icon="RENDER_STILL")
        dice = row.row(align=True)
        dice.scale_x = 1.2
        dice.prop(s, "seed_random", text="", icon="MOD_NOISE", toggle=True)

        if s.running:
            row = layout.row(align=True)
            row.progress(factor=s.progress, text=s.status)
            row.operator("comfy_bridge.cancel", text="", icon="CANCEL")
            return

        if s.last_result and (s.workflow_can_edit or state.edit_workflow_items):
            layout.separator(factor=0.5)
            row = layout.row(align=True)
            row.prop(s, "edit_prompt", text="", placeholder="Change, e.g. green velvet sofa")
            row.operator("comfy_bridge.edit_selection", text="Redo Selection", icon="SELECT_SET")

        if s.last_error:
            box = layout.box()
            first = s.last_error.splitlines()[0]
            row = box.row()
            row.label(text=first, icon="ERROR" if s.status == "Error" else "INFO")
            if len(s.last_error) > len(first) or len(first) > 60:
                row.operator("comfy_bridge.show_error", text="", icon="TEXT")
        elif s.status.startswith(("Done", "Cancelled", "Render cancelled")):
            row = layout.row()
            row.label(text=s.status, icon="CHECKMARK" if s.status.startswith("Done") else "INFO")
            row.operator("comfy_bridge.open_folder", text="", icon="FILE_FOLDER", emboss=False).which = "OUTPUT"


class _Sub:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_parent_id = "CB_PT_main"

    @classmethod
    def poll(cls, context):
        return bool(state.server)


class CB_PT_object_prompts(_Sub, bpy.types.Panel):
    bl_label = "Object Prompts"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        s = context.scene.comfy_bridge
        return bool(state.server) and (s.region_slots > 0 or "object prompts" in s.workflow_info)

    def draw(self, context):
        from . import operators
        layout = self.layout
        s = context.scene.comfy_bridge
        objs = operators.prompt_objects(context.scene, context.view_layer)
        limit = s.region_slots or len(objs)
        col = layout.column(align=True)
        for i, o in enumerate(objs):
            row = col.row(align=True)
            row.active = i < limit
            row.label(text=o.name, icon="OBJECT_DATA")
            row.prop(o, "comfy_prompt", text="")
        if not objs:
            layout.label(text="Add prompts in Object Properties › Comfy Bridge", icon="INFO")
        elif s.region_slots and len(objs) > limit:
            layout.label(text=f"Only {limit} fit this workflow", icon="ERROR")
        if s.region_slots:
            layout.prop(s, "region_strength", slider=True)


class CB_PT_advanced(_Sub, bpy.types.Panel):
    bl_label = "Advanced"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        from . import installer, operators
        layout = self.layout
        s = context.scene.comfy_bridge
        layout.use_property_split = True
        layout.use_property_decorate = False

        if s.workflow_info:
            layout.label(text=s.workflow_info, icon="INFO")

        body = _section(layout, "CB_adv_models", "Models")
        if body:
            col = body.column()
            for p in s.params:
                if p.section == "model":
                    _draw_param(col, p)
            col.prop(s, "show_all_models")
            params = [p for p in s.params if p.section == "param"]
            for p in params:
                _draw_param(col, p)

        body = _section(layout, "CB_adv_render", "Render & Seed")
        if body:
            row = body.row(heading="Seed")
            sub = row.row(align=True)
            sub.enabled = not s.seed_random
            sub.prop(s, "seed", text="")
            row.prop(s, "seed_random", text="", icon="MOD_NOISE", toggle=True)
            body.operator("comfy_bridge.send", icon="EXPORT")
            needed = s.workflow_needed.split(",") if s.workflow_needed else []
            col = body.column(heading="Extra Passes")
            for key, label in (("beauty", "Beauty"), ("depth", "Depth"), ("normal", "Normal"), ("lineart", "Line Art")):
                if key not in needed:
                    col.prop(s, "extra_" + key)
            body.prop(s, "normal_flip_x")
            body.prop(s, "load_control_images")
            body.prop(s, "show_result")
            body.operator("comfy_bridge.open_folder", text="Open Results Folder", icon="FILE_FOLDER").which = "OUTPUT"

        body = _section(layout, "CB_adv_edit", "Redo Selection")
        if body:
            body.prop(s, "edit_grow")
            body.prop(s, "edit_feather")
            if not s.workflow_can_edit and state.edit_workflow_items:
                body.prop(s, "edit_workflow", text="Edit Workflow")
            if s.last_result:
                body.label(text=f"From {os.path.basename(s.last_result)} · seed {s.last_seed}")

        body = _section(layout, "CB_adv_packages", "Model Packages")
        if body:
            body.use_property_split = False
            body.prop(s, "package", text="")
            pkg = installer.package(s.package)
            if pkg:
                root = operators.models_dir()
                status, todo = installer.status(root, pkg)
                text = {"installed": "Installed", "partial": f"Partly installed · {installer.human_size(todo)} missing",
                        "missing": f"Not installed · {installer.human_size(todo)}"}[status]
                lic = pkg["license"]
                col = body.column(align=True)
                col.label(text=text, icon="CHECKMARK" if status == "installed" else "IMPORT")
                col.label(text=lic["name"] + ("" if lic["commercial"] else " · non-commercial"),
                          icon="CHECKMARK" if lic["commercial"] else "ERROR")
                col.label(text=f"About {pkg['vram_gb']} GB VRAM", icon="MEMORY")
                dl = state.download
                if dl is not None:
                    row = body.row(align=True)
                    row.progress(factor=dl.progress, text=f"{dl.current} · {installer.human_size(dl.done_bytes)} / "
                                                          f"{installer.human_size(dl.total)}")
                    row.operator("comfy_bridge.cancel_download", text="", icon="CANCEL")
                else:
                    row = body.row(align=True)
                    if status != "installed":
                        row.operator("comfy_bridge.install_package", text="Install", icon="IMPORT").package_id = ""
                    if status != "missing":
                        row.operator("comfy_bridge.delete_package", text="Delete", icon="TRASH")
            if state.download_message:
                body.label(text=state.download_message, icon="INFO")

        body = _section(layout, "CB_adv_comfy", "ComfyUI")
        if body:
            body.use_property_split = False
            status = installer.nodes_status(operators.comfyui_dir(), state.object_info)
            text = {"loaded": "Blender nodes loaded", "restart": "Restart ComfyUI to load the Blender nodes",
                    "outdated": "Blender nodes outdated", "missing": "Blender nodes not installed"}[status]
            row = body.row(align=True)
            row.label(text=text, icon="CHECKMARK" if status == "loaded" else "ERROR")
            row.operator("comfy_bridge.install_nodes", text="Reinstall" if status == "loaded" else "Install")
            row = body.row(align=True)
            row.operator("comfy_bridge.install_examples", icon="DUPLICATE")
            row.operator("comfy_bridge.reload_workflows", text="", icon="FILE_REFRESH")
            if state.examples_message:
                body.label(text=state.examples_message, icon="INFO")
            body.label(text="Copy an example with Save As before you change it.")


class CB_PT_object(bpy.types.Panel):
    bl_label = "Comfy Bridge"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    def draw(self, context):
        self.layout.prop(context.object, "comfy_prompt", text="Prompt")


classes = (CB_PT_main, CB_PT_object_prompts, CB_PT_advanced, CB_PT_object)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
