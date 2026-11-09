import json
import os

import bpy

from . import state, workflows


def _addon_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def workflow_folders(context=None):
    folders = [(os.path.join(os.path.dirname(__file__), "workflows"), True)]
    prefs = _addon_prefs(context)
    user = prefs.workflow_dir if prefs else ""
    if user:
        folders.insert(0, (bpy.path.abspath(user), False))
    return folders


def refresh_workflow_items(context=None):
    found = workflows.scan(workflow_folders(context))
    state.workflow_items = [(p, label, p) for p, label, _ in found if not workflows.is_edit_workflow(p)]
    state.edit_workflow_items = [(p, label, p) for p, label, _ in found if workflows.is_edit_workflow(p)]
    return state.workflow_items


def _workflow_items(self, context):
    if not state.workflow_items:
        refresh_workflow_items(context)
    return state.workflow_items or [("", "No workflow found", "")]


def _edit_workflow_items(self, context):
    if not state.edit_workflow_items:
        refresh_workflow_items(context)
    return state.edit_workflow_items or [("", "No edit workflow found", "")]


def _package_items(self, context):
    if not state.package_items:
        from . import installer
        state.package_items = [(p["id"], p["name"], p["description"]) for p in installer.load_catalog()]
    return state.package_items


def _on_workflow_changed(self, context):
    from . import operators
    operators.rebuild_params(context.scene, save_old=True, from_user=True)


def _param_enum_items(self, context):
    options = list(state.enum_item_cache.get(("opts", self.key), []))
    if self.str_v and self.str_v not in options:
        options.insert(0, self.str_v)
    items = []
    available = set(state.enum_item_cache.get(("all", self.key), options))
    for o in options:
        label = o if o in available else f"{o}  (missing in ComfyUI!)"
        items.append((o, label, o))
    if not items:
        items = [("", "Nothing to choose", "")]
    state.enum_item_cache[("items", self.key)] = items
    return items


def _on_enum_changed(self, context):
    if self.enum_v:
        self.str_v = self.enum_v


class CB_Param(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty()
    node_id: bpy.props.StringProperty()
    node_class: bpy.props.StringProperty()
    input_name: bpy.props.StringProperty()
    label: bpy.props.StringProperty()
    section: bpy.props.StringProperty()  # model / prompt / param
    kind: bpy.props.StringProperty()     # ENUM / INT / FLOAT / BOOLEAN / STRING
    tooltip: bpy.props.StringProperty()
    has_min: bpy.props.BoolProperty()
    has_max: bpy.props.BoolProperty()
    min_v: bpy.props.FloatProperty()
    max_v: bpy.props.FloatProperty()
    unit_range: bpy.props.BoolProperty(description="Value is between 0 and 1 – shown as a slider")

    int_v: bpy.props.IntProperty(name="Value")
    float_v: bpy.props.FloatProperty(name="Value", precision=3, step=10)
    float01_v: bpy.props.FloatProperty(name="Value", min=0.0, max=1.0, precision=2, subtype="FACTOR")
    bool_v: bpy.props.BoolProperty(name="Value")
    str_v: bpy.props.StringProperty(name="Value")
    enum_v: bpy.props.EnumProperty(name="Value", items=_param_enum_items, update=_on_enum_changed)

    def get_value(self):
        if self.kind == "INT":
            v = self.int_v
        elif self.kind == "FLOAT":
            v = self.float01_v if self.unit_range else self.float_v
        elif self.kind == "BOOLEAN":
            return self.bool_v
        else:
            return self.str_v
        if self.has_min:
            v = max(v, type(v)(self.min_v))
        if self.has_max:
            v = min(v, type(v)(self.max_v))
        return v

    def set_value(self, v):
        if self.kind == "INT":
            self.int_v = int(max(min(int(v), 2**31 - 1), -(2**31)))
        elif self.kind == "FLOAT":
            if self.unit_range:
                self.float01_v = float(v)
            else:
                self.float_v = float(v)
        elif self.kind == "BOOLEAN":
            self.bool_v = bool(v)
        else:
            self.str_v = "" if v is None else str(v)
            if self.kind == "ENUM" and self.str_v:
                try:
                    self.enum_v = self.str_v
                except TypeError:
                    pass


class CB_Settings(bpy.types.PropertyGroup):
    workflow: bpy.props.EnumProperty(
        name="Workflow",
        description="ComfyUI workflow (API format) that runs with your render",
        items=_workflow_items,
        update=_on_workflow_changed,
    )
    workflow_path: bpy.props.StringProperty()
    workflow_info: bpy.props.StringProperty()
    workflow_family: bpy.props.StringProperty()
    workflow_needed: bpy.props.StringProperty()
    workflow_warnings: bpy.props.StringProperty()
    region_slots: bpy.props.IntProperty()
    params: bpy.props.CollectionProperty(type=CB_Param)
    saved_values: bpy.props.StringProperty(default="{}")

    show_all_models: bpy.props.BoolProperty(
        name="Show All Models",
        description="Also list ControlNets whose file name doesn't match the workflow's model family",
        update=_on_workflow_changed,
    )

    seed: bpy.props.IntProperty(name="Seed", min=0, description="Same seed + same settings = same image")
    seed_random: bpy.props.BoolProperty(name="Random", default=True, description="Roll a new seed for every send")

    extra_beauty: bpy.props.BoolProperty(name="Beauty", default=True)
    extra_depth: bpy.props.BoolProperty(name="Depth", description="Distance to camera: near = bright, far = dark")
    extra_normal: bpy.props.BoolProperty(name="Normal", description="Surface direction relative to the camera")
    extra_lineart: bpy.props.BoolProperty(name="Line Art", description="Freestyle lines (enabled automatically while rendering)")
    normal_flip_x: bpy.props.BoolProperty(
        name="Flip Normal X",
        description="Some normal ControlNets expect red = left instead of right",
    )
    load_control_images: bpy.props.BoolProperty(
        name="Load Control Images",
        description="Load the generated passes as images 'CB · …' to check them in the Image Editor",
        default=True,
    )
    show_result: bpy.props.BoolProperty(
        name="Show Result",
        description="Show the result in all open Image Editors",
        default=True,
    )

    region_strength: bpy.props.FloatProperty(
        name="Object Prompt Strength", min=0.0, max=3.0, default=1.0, precision=2,
        description="How strongly an object's own prompt wins over the main prompt inside its mask",
    )
    edit_workflow: bpy.props.EnumProperty(
        name="Edit Workflow",
        description="Workflow that repaints only the selected objects in the last result",
        items=_edit_workflow_items,
    )
    edit_prompt: bpy.props.StringProperty(
        name="Change",
        description="What the selected objects should become, e.g. 'green velvet sofa'",
    )
    edit_grow: bpy.props.IntProperty(
        name="Mask Grow", min=0, max=64, default=8, subtype="PIXEL",
        description="Grow the selection mask so edges and shadows can change too",
    )
    edit_feather: bpy.props.IntProperty(
        name="Mask Feather", min=0, max=64, default=8, subtype="PIXEL",
        description="Soft falloff outside the grown mask",
    )
    last_result: bpy.props.StringProperty(
        name="Last Result", subtype="FILE_PATH",
        description="Image the next Edit Selection starts from",
    )

    package: bpy.props.EnumProperty(
        name="Package",
        description="Curated model package: model files plus a ready workflow",
        items=_package_items,
    )

    running: bpy.props.BoolProperty()
    progress: bpy.props.FloatProperty(subtype="FACTOR", min=0.0, max=1.0)
    status: bpy.props.StringProperty(default="Ready")
    last_error: bpy.props.StringProperty()
    last_seed: bpy.props.IntProperty()

    def saved(self):
        try:
            return json.loads(self.saved_values or "{}")
        except ValueError:
            return {}


classes = (CB_Param, CB_Settings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.comfy_bridge = bpy.props.PointerProperty(type=CB_Settings)
    bpy.types.Object.comfy_prompt = bpy.props.StringProperty(
        name="Object Prompt",
        description="Prompt for this object only. Used by workflows with object prompt slots (BL:region_1 …)",
    )


def unregister():
    del bpy.types.Object.comfy_prompt
    del bpy.types.Scene.comfy_bridge
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
