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
    state.workflow_items = [
        (path, label, path) for path, label, _ in workflows.scan(workflow_folders(context))
    ]
    return state.workflow_items


def _workflow_items(self, context):
    if not state.workflow_items:
        refresh_workflow_items(context)
    return state.workflow_items or [("", "– kein Workflow gefunden –", "")]


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
        label = o if o in available else f"{o}  (fehlt in ComfyUI!)"
        items.append((o, label, o))
    if not items:
        items = [("", "– keine Auswahl –", "")]
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
    unit_range: bpy.props.BoolProperty(description="Wert liegt zwischen 0 und 1 – als Schieberegler zeigen")

    int_v: bpy.props.IntProperty(name="Wert")
    float_v: bpy.props.FloatProperty(name="Wert", precision=3, step=10)
    float01_v: bpy.props.FloatProperty(name="Wert", min=0.0, max=1.0, precision=2, subtype="FACTOR")
    bool_v: bpy.props.BoolProperty(name="Wert")
    str_v: bpy.props.StringProperty(name="Wert")
    enum_v: bpy.props.EnumProperty(name="Wert", items=_param_enum_items, update=_on_enum_changed)

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
        description="ComfyUI-Workflow (API-Format), der mit deinem Render ausgeführt wird",
        items=_workflow_items,
        update=_on_workflow_changed,
    )
    workflow_path: bpy.props.StringProperty()
    workflow_info: bpy.props.StringProperty()
    workflow_family: bpy.props.StringProperty()
    workflow_warnings: bpy.props.StringProperty()
    params: bpy.props.CollectionProperty(type=CB_Param)
    saved_values: bpy.props.StringProperty(default="{}")

    show_all_models: bpy.props.BoolProperty(
        name="Alle Modelle zeigen",
        description="Auch ControlNets anzeigen, die laut Dateiname nicht zur Modellfamilie des Workflows passen",
        update=_on_workflow_changed,
    )
    show_help: bpy.props.BoolProperty(name="Erklärungen", description="Kurze Erklärungen im Panel einblenden", default=True)

    seed: bpy.props.IntProperty(name="Seed", min=0, description="Startwert des Zufallsrauschens. Gleicher Seed + gleiche Einstellungen = gleiches Bild")
    seed_random: bpy.props.BoolProperty(name="Zufall", default=True, description="Bei jedem Senden einen neuen Seed würfeln")

    extra_beauty: bpy.props.BoolProperty(name="Beauty", default=True)
    extra_depth: bpy.props.BoolProperty(name="Depth", description="Abstand zur Kamera: nah = hell, fern = dunkel")
    extra_normal: bpy.props.BoolProperty(name="Normal", description="Ausrichtung der Flächen relativ zur Kamera")
    extra_lineart: bpy.props.BoolProperty(name="Line Art", description="Freestyle-Linien (wird beim Rendern automatisch aktiviert)")
    normal_flip_x: bpy.props.BoolProperty(
        name="Normal: Rot spiegeln",
        description="Manche Normal-ControlNets erwarten Rot = links statt rechts",
    )
    load_control_images: bpy.props.BoolProperty(
        name="Steuerbilder in Blender laden",
        description="Die erzeugten Pässe (Depth, Normal, ...) als Bilder „CB · …“ in Blender laden, zum Kontrollieren im Image Editor",
        default=True,
    )
    show_result: bpy.props.BoolProperty(
        name="Ergebnis anzeigen",
        description="Das Ergebnis automatisch in allen offenen Image Editoren anzeigen",
        default=True,
    )

    running: bpy.props.BoolProperty()
    progress: bpy.props.FloatProperty(subtype="FACTOR", min=0.0, max=1.0)
    status: bpy.props.StringProperty(default="Bereit")
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


def unregister():
    del bpy.types.Scene.comfy_bridge
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
