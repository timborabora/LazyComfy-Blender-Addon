import copy
import json
import os
import random
import tempfile
import threading
import time

import bpy

from . import comfy_client, installer, migrate, passes, pipeline, props, state, templates, workflows
from .comfy_client import ComfyError


def _addon_version():
    import tomllib
    try:
        with open(os.path.join(os.path.dirname(__file__), "blender_manifest.toml"), "rb") as f:
            return tomllib.load(f)["version"]
    except (OSError, KeyError, ValueError):
        return "dev"


ADDON_VERSION = _addon_version()

HISTORY_TEXT = "LazyComfy_History"
RESULT_IMAGE = "ComfyUI Result"
PASS_IMAGE_LABELS = {"beauty": "Beauty", "depth": "Depth", "normal": "Normal", "lineart": "Line Art"}


def prefs():
    return props._addon_prefs()


def tag_redraw():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in ("PROPERTIES", "IMAGE_EDITOR"):
                area.tag_redraw()


# ---------------------------------------------------------------- connection

def connect_async():
    """Find the server and fetch /object_info without blocking Blender."""
    if state.connecting:
        return
    state.connecting = True
    state.connect_error = ""
    preferred = prefs().server_url if prefs() else ""
    manifest = examples_manifest_path()
    old_manifests = migrate.old_manifest_paths()

    def work():
        try:
            _connect(preferred, manifest, old_manifests)
        except Exception as e:
            state.server, state.stats = None, None
            state.connect_error = str(e)
        finally:
            state.connecting = False

    threading.Thread(target=work, daemon=True).start()

    def wait():
        if state.connecting:
            return 0.2
        props.refresh_workflow_items()
        for scene in bpy.data.scenes:
            rebuild_params(scene, save_old=True)
        tag_redraw()
        return None

    bpy.app.timers.register(wait, first_interval=0.2, persistent=True)


def connect_sync(preferred=""):
    """For scripts and tests."""
    _connect(preferred, examples_manifest_path(), migrate.old_manifest_paths())
    props.refresh_workflow_items()
    return state.server


def _connect(preferred, manifest, old_manifests=()):
    """Find ComfyUI, read its nodes, ship the examples once, list saved workflows. Runs off the main thread."""
    base, stats = comfy_client.find_server(preferred)
    if not base:
        raise ComfyError("ComfyUI not found. Is Comfy Desktop running?")
    info = comfy_client.get_json(base, "/object_info", timeout=30)
    state.server, state.stats, state.object_info = base, stats, info
    moved = migrate.comfy_examples(base, manifest, old_manifests, comfy_client)
    if moved:
        state.examples_message = f"Moved {len(moved)} workflow(s) from 'Comfy Bridge' to 'Lazy Comfy'."
    if manifest and templates.load_manifest(manifest).get("__version__") != ADDON_VERSION:
        try:
            report = templates.install(base, manifest, ADDON_VERSION)
            state.examples_message = _examples_summary(report)
        except ComfyError as e:
            state.examples_message = f"Examples not installed: {e}"
    index_comfy_workflows(base)


def index_comfy_workflows(base):
    index = []
    for path, _ in templates.list_comfy_workflows(base):
        ui = templates.fetch_workflow(base, path)
        if not isinstance(ui, dict) or not workflows.has_blender_nodes(ui):
            continue
        ident = workflows.COMFY_PREFIX + path
        state.comfy_workflows[ident] = {"ui": ui}
        has_sel = any(n.get("type") == "BlenderSelection" for n in ui.get("nodes", []))
        index.append((ident, os.path.splitext(path)[0], has_sel))
    state.comfy_index = sorted(index, key=lambda x: x[1].lower())


def _examples_summary(report):
    changed = [f"{name}: {action}" for name, action in report if action != "unchanged"]
    return "Examples up to date." if not changed else "Examples – " + "; ".join(changed)


def examples_manifest_path():
    try:
        folder = bpy.utils.extension_path_user(__package__, create=True)
    except (ValueError, AttributeError):
        folder = os.path.join(tempfile.gettempdir(), "lazy_comfy")
    return os.path.join(folder, "examples_manifest.json")


# ---------------------------------------------------------------- parameters

def _current_values(settings):
    return {p.key: p.get_value() for p in settings.params}


def rebuild_params(scene, save_old=True, from_user=False):
    """Re-read the selected workflow and rebuild the panel fields."""
    s = scene.lazy_comfy
    # Blender stores dynamic enums as an index – it shifts when workflows are added.
    if (not from_user and s.workflow_path and s.workflow != s.workflow_path
            and any(i[0] == s.workflow_path for i in state.workflow_items)):
        s.workflow = s.workflow_path  # triggers rebuild_params again with the right selection
        return
    saved = s.saved()
    if save_old and s.workflow_path and len(s.params):
        saved[s.workflow_path] = _current_values(s)
    path = s.workflow
    s.workflow_path = path or ""
    s.params.clear()
    s.workflow_info = ""
    s.workflow_family = ""
    s.workflow_needed = ""
    s.workflow_warnings = ""
    s.region_slots = 0
    s.missing_packages = ""
    s.missing_nodes = ""
    if not path:
        s.saved_values = json.dumps(saved)
        return
    try:
        wf = workflows.load(path, fresh=True)
    except workflows.WorkflowError as e:
        _set_dependencies(s, path, None)
        s.workflow_warnings = str(e)
        s.saved_values = json.dumps(saved)
        return
    _set_dependencies(s, path, wf)
    analysis = workflows.analyze(wf, state.object_info)
    s.workflow_info = workflows.describe(analysis)
    s.workflow_family = analysis["family"]
    s.workflow_needed = ",".join(analysis["images"])
    s.region_slots = len(analysis["regions"])
    s.workflow_can_edit = bool(analysis["blender_selection"])
    s.workflow_warnings = "\n".join(analysis["warnings"])
    old = saved.get(path, {})
    for p in analysis["params"]:
        item = s.params.add()
        item.key, item.node_id, item.node_class = p["key"], p["node_id"], p["node_class"]
        item.input_name, item.label, item.section, item.kind = p["input"], p["label"], p["section"], p["kind"]
        item.tooltip = p["tooltip"] or ""
        item.has_min, item.has_max = p["min"] is not None, p["max"] is not None
        if item.has_min:
            item.min_v = p["min"]
        if item.has_max:
            item.max_v = p["max"]
        item.unit_range = item.kind == "FLOAT" and item.has_min and item.has_max and p["min"] >= 0 and p["max"] <= 1
        if item.kind == "ENUM":
            opts = workflows.filter_models(p["options"], p["input"], s.workflow_family, s.show_all_models) \
                if p["section"] == "model" else p["options"]
            state.enum_item_cache[("opts", item.key)] = opts
            state.enum_item_cache[("all", item.key)] = p["options"] or opts
        item.set_value(old.get(item.key, p["value"]))
    s.saved_values = json.dumps(saved)


def _set_dependencies(s, path, api):
    """Model packages and ComfyUI nodes the workflow needs but that are missing."""
    packages, nodes = [], []
    if path.startswith(workflows.COMFY_PREFIX):
        ui = state.comfy_workflows.get(path, {}).get("ui") or {}
        extra = ui.get("extra") or {}
        meta = extra.get("lazy_comfy") or extra.get("comfy_bridge") or {}  # older examples used the old name
        packages = meta.get("packages", [])
        nodes = meta.get("required_nodes") or sorted({n.get("type") for n in ui.get("nodes", [])
                                                      if n.get("type") not in ("Reroute", "PrimitiveNode", "Note", "MarkdownNote")})
    else:
        packages = [p["id"] for p in installer.load_catalog() if p["workflow"] == os.path.basename(path)]
        nodes = sorted({n["class_type"] for n in (api or {}).values()})
    root = models_dir()
    missing_pkgs = [p for p in packages if (pkg := installer.package(p)) and installer.status(root, pkg)[0] != "installed"]
    missing_nodes = [n for n in nodes if state.object_info and n not in state.object_info]
    s.missing_packages = ",".join(missing_pkgs)
    s.missing_nodes = ",".join(missing_nodes)


# ---------------------------------------------------------------- sending

def _output_dir():
    p = prefs()
    if p and p.output_dir:
        return bpy.path.abspath(p.output_dir)
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "lazy_comfy_output")
    return os.path.join(tempfile.gettempdir(), "lazy_comfy", "output")


def _pass_dir():
    return os.path.join(tempfile.gettempdir(), "lazy_comfy", "passes")


def _wanted_passes(s, needed):
    wanted = list(needed)
    for key, flag in (("beauty", s.extra_beauty), ("depth", s.extra_depth),
                      ("normal", s.extra_normal), ("lineart", s.extra_lineart)):
        if flag and key not in wanted:
            wanted.append(key)
    if "beauty" not in wanted:
        wanted.insert(0, "beauty")
    return wanted


def prompt_objects(scene, view_layer):
    """Objects with an object prompt that the render can see, in a stable order."""
    objs = [o for o in scene.objects if o.lazy_comfy_prompt.strip() and o.visible_get(view_layer=view_layer)]
    return sorted(objs, key=lambda o: o.name)


def selected_objects(scene, view_layer):
    return [o for o in scene.objects if o.select_get(view_layer=view_layer) and o.visible_get(view_layer=view_layer)]


def workflow_needs(scene, view_layer, mode):
    """Workflow, its analysis and the passes to render for `mode` ('main' or 'edit')."""
    s = scene.lazy_comfy
    path = s.workflow
    if mode == "edit" and not s.workflow_can_edit:
        path = s.edit_workflow  # title-convention edit workflow (API file)
    if not path:
        raise workflows.WorkflowError("No edit workflow found." if mode == "edit" else "No workflow selected.")
    wf = workflows.load(path, fresh=True)
    analysis = workflows.analyze(wf, state.object_info)
    wanted = _wanted_passes(s, analysis["images"].keys())
    if analysis["regions"] or analysis["selection_nodes"] or analysis["object_nodes"] \
            or (mode == "edit" and analysis["blender_selection"]):
        wanted.append("crypto")
    return path, wf, analysis, wanted


def _image_size(path):
    inp = passes.oiio.ImageInput.open(path)
    if inp is None:
        raise passes.PassError(f"Can't read {path}")
    spec = inp.spec()
    inp.close()
    return spec.width, spec.height


def build_job(scene, view_layer, mode="main"):
    """Export the passes and prepare the workflow. Returns (job, control images, warnings, info)."""
    s = scene.lazy_comfy
    if not state.server:
        raise ComfyError("Not connected to ComfyUI.")
    path, wf, analysis, wanted = workflow_needs(scene, view_layer, mode)
    warnings = []

    masks, region_objects, node_objects = {}, [], []
    if mode == "main":
        region_objects = prompt_objects(scene, view_layer)
        if analysis["object_nodes"]:
            node_objects = region_objects  # Blender Object Prompts node: no slot limit
            for i, obj in enumerate(node_objects, 1):
                masks[f"obj_{i}"] = {"names": {obj.name}}
            region_objects = []
        slots = sorted(analysis["regions"])
        if len(region_objects) > len(slots) and slots:
            skipped = ", ".join(o.name for o in region_objects[len(slots):])
            warnings.append(f"Only {len(slots)} object prompts fit this workflow – skipped: {skipped}")
        region_objects = region_objects[:len(slots)]
        for n, obj in zip(slots, region_objects):
            masks[f"region_{n}"] = {"names": {obj.name}}
    else:
        prev = bpy.path.abspath(s.last_result)
        if not prev or not os.path.isfile(prev):
            raise passes.PassError("No previous result to edit – use Render & Send first.")
        selected = selected_objects(scene, view_layer)
        if not selected:
            raise passes.PassError("Select the objects to change in the viewport first.")
        if not s.edit_prompt.strip():
            raise passes.PassError("Describe the change in the Change field first.")
        masks["selection"] = {"names": {o.name for o in selected}, "grow": s.edit_grow,
                              "feather": s.edit_feather, "size": _image_size(prev)}

    files, pass_warnings, visible = passes.export(scene, view_layer, wanted, _pass_dir(), s.normal_flip_x, masks)
    warnings += pass_warnings

    wf = copy.deepcopy(wf)
    if mode == "main" or analysis["node_based"]:
        for p in s.params:
            node = wf.get(p.node_id)
            if node and p.input_name in node.get("inputs", {}) and not workflows.is_link(node["inputs"][p.input_name]):
                node["inputs"][p.input_name] = p.get_value()
    if mode == "main":
        if s.seed_random:
            s.seed = random.randint(0, 2**31 - 1)
        seed = s.seed
    else:
        seed = s.last_seed  # same noise as the image being edited
        for nid in analysis["edit_prompt_nodes"]:
            node = wf[nid]["inputs"]
            node["text" if "text" in node else "prompt"] = s.edit_prompt
    for node in wf.values():
        for name in workflows.SEED_INPUTS:
            if name in node.get("inputs", {}) and not workflows.is_link(node["inputs"][name]):
                node["inputs"][name] = seed

    r = scene.render
    width = max(64, int(r.resolution_x * r.resolution_percentage / 100) // 8 * 8)
    height = max(64, int(r.resolution_y * r.resolution_percentage / 100) // 8 * 8)
    for nid in analysis["size_nodes"]:
        wf[nid]["inputs"]["width"], wf[nid]["inputs"]["height"] = width, height

    uploads = []
    for key, node_ids in analysis["images"].items():
        if not files.get(key):
            raise passes.PassError(f"Control image '{key}' is missing.")
        uploads.append((files[key], os.path.basename(files[key]), node_ids))

    # Object prompt slots: unused or invisible slots get strength 0 and an empty mask.
    used = []
    for n, slot in sorted(analysis["regions"].items()):
        key = f"region_{n}"
        obj = next((o for k, o in zip(sorted(analysis["regions"]), region_objects) if k == n), None)
        active = obj is not None and visible.get(key)
        if obj is not None and not active:
            warnings.append(f"'{obj.name}' is not in the frame – its object prompt is skipped.")
        mask_file = files.get(key) or _blank_mask(width, height)
        uploads.append((mask_file, f"lc_{key}.png", [slot["mask"]]))
        wf[slot["prompt"]]["inputs"]["text"] = obj.lazy_comfy_prompt if active else ""
        wf[slot["apply"]]["inputs"]["strength"] = s.region_strength if active else 0.0
        if active:
            used.append(f"{obj.name}: {obj.lazy_comfy_prompt}")

    # Blender Object Prompts node: one entry per visible object, masks uploaded alongside.
    entries = []
    for i, obj in enumerate(node_objects, 1):
        key = f"obj_{i}"
        if not visible.get(key):
            warnings.append(f"'{obj.name}' is not in the frame – its object prompt is skipped.")
            continue
        name = f"lc_{key}.png"
        uploads.append((files[key], name, []))
        entries.append({"name": obj.name, "prompt": obj.lazy_comfy_prompt, "mask": f"lazy_comfy/{name}"})
        used.append(f"{obj.name}: {obj.lazy_comfy_prompt}")
    for nid in analysis["object_nodes"]:
        wf[nid]["inputs"]["objects"] = json.dumps(entries)

    # Blender Selection node: empty for a normal render, so the inpaint branch is skipped.
    for nid in analysis["blender_selection"]:
        wf[nid]["inputs"].update({"mask": "", "previous": "", "change": s.edit_prompt if mode == "edit" else ""})

    if mode == "edit":
        prev = bpy.path.abspath(s.last_result)
        if not visible.get("selection"):
            raise passes.PassError("The selected objects are not in the frame.")
        if analysis["prev_nodes"] or analysis["selection_nodes"]:
            uploads.append((prev, "lc_result_prev.png", analysis["prev_nodes"]))
            uploads.append((files["selection"], "lc_selection.png", analysis["selection_nodes"]))
        if analysis["blender_selection"]:
            uploads.append((prev, "lc_result_prev.png", analysis["blender_selection"], "previous"))
            uploads.append((files["selection"], "lc_selection.png", analysis["blender_selection"], "mask"))

    s.last_seed = seed
    job = pipeline.Job(state.server, wf, state.client_id, uploads, _output_dir(), analysis["result_nodes"])
    info = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workflow": os.path.basename(path),
        "seed": seed,
        "resolution": f"{width}x{height}",
        "values": {p.label: p.get_value() for p in s.params} if mode == "main" else {"change": s.edit_prompt},
    }
    if used:
        info["object_prompts"] = used
    if mode == "edit":
        info["edited"] = sorted(masks["selection"]["names"])
    return job, files, warnings, info


def _blank_mask(width, height):
    path = os.path.join(_pass_dir(), f"lc_blank_{width}x{height}.png")
    if not os.path.exists(path):
        os.makedirs(_pass_dir(), exist_ok=True)
        passes.write_png(path, passes.np.zeros((height, width), dtype=passes.np.float32))
    return path


def load_image(name, path):
    img = bpy.data.images.get(name)
    if img and img.source == "FILE":
        img.filepath = path
        img.reload()
    else:
        if img:
            img.name = name + " (old)"
        img = bpy.data.images.load(path, check_existing=False)
        img.name = name
    return img


def show_in_image_editors(img):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = img


def _fail(s, message):
    s.running = False
    s.status = "Error"
    s.last_error = message


def finish_job(scene, job, info):
    s = scene.lazy_comfy
    s.running = False
    s.progress = job.progress
    if job.error:
        _fail(s, job.error)
        return
    if job.cancelled:
        s.status = "Cancelled"
        return
    loaded = []
    for i, (title, path) in enumerate(job.results):
        name = RESULT_IMAGE if i == 0 else f"{RESULT_IMAGE} · {title}"
        loaded.append(load_image(name, path))
    if loaded and s.show_result and not bpy.app.background:
        show_in_image_editors(loaded[0])
    info["prompt_id"] = job.prompt_id
    info["result"] = [p for _, p in job.results]
    if job.results:
        s.last_result = job.results[0][1]
    text = bpy.data.texts.get(HISTORY_TEXT) or bpy.data.texts.new(HISTORY_TEXT)
    text.write(json.dumps(info, ensure_ascii=False) + "\n")
    s.status = f"Done · seed {info['seed']}"
    s.last_error = ""


def start_job(scene, job, files, warnings, info):
    s = scene.lazy_comfy
    if s.load_control_images:
        for key, path in files.items():
            load_image("LC · " + PASS_IMAGE_LABELS.get(key, "Mask " + key[5:]), path)
    s.running, s.progress, s.last_error = True, 0.0, "\n".join(warnings)
    s.status = "Sending to ComfyUI …"
    state.job = job
    job.start()
    scene_name = scene.name

    def poll():
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        sc = scene.lazy_comfy
        sc.progress = job.progress
        sc.status = job.status
        tag_redraw()
        if not job.done:
            return 0.25
        state.job = None
        finish_job(scene, job, info)
        tag_redraw()
        return None

    bpy.app.timers.register(poll, first_interval=0.25, persistent=True)


def run_blocking(scene, view_layer, mode="main"):
    """Synchronous for scripts/tests: passes from the existing render, send, wait, load the result."""
    job, files, warnings, info = build_job(scene, view_layer, mode)
    job.run()
    finish_job(scene, job, info)
    return job, files, warnings


# ---------------------------------------------------------------- operators

class LC_OT_connect(bpy.types.Operator):
    bl_idname = "lazy_comfy.connect"
    bl_label = "Connect"
    bl_description = "Find ComfyUI and reload its models and nodes"

    def execute(self, context):
        props.refresh_workflow_items(context)
        connect_async()
        return {"FINISHED"}


class LC_OT_reload_workflows(bpy.types.Operator):
    bl_idname = "lazy_comfy.reload_workflows"
    bl_label = "Reload Workflows"
    bl_description = "Rescan the workflow folders and re-read the selected workflow"

    def execute(self, context):
        props.refresh_workflow_items(context)
        rebuild_params(context.scene, save_old=True)
        return {"FINISHED"}


class LC_OT_open_folder(bpy.types.Operator):
    bl_idname = "lazy_comfy.open_folder"
    bl_label = "Open Folder"
    bl_description = "Open the folder in the file browser"
    which: bpy.props.EnumProperty(items=[("WORKFLOWS", "Workflows", ""), ("OUTPUT", "Results", "")])

    @classmethod
    def description(cls, context, properties):
        if properties.which == "OUTPUT":
            return "Open the folder where results are saved"
        return "Open the workflow folder. Add your own workflows here (ComfyUI: Workflow > Export (API))"

    def execute(self, context):
        if self.which == "OUTPUT":
            folder = _output_dir()
        else:
            folder = props.workflow_folders(context)[0][0]
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


class _SendBase:
    @classmethod
    def poll(cls, context):
        s = context.scene.lazy_comfy
        return state.server and s.workflow and not s.running

    def _send(self, context):
        try:
            job, files, warnings, info = build_job(context.scene, context.view_layer)
        except (ComfyError, passes.PassError, workflows.WorkflowError) as e:
            _fail(context.scene.lazy_comfy, str(e))
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        start_job(context.scene, job, files, warnings, info)
        for w in warnings:
            self.report({"WARNING"}, w)
        return {"FINISHED"}


class LC_OT_render_send(_SendBase, bpy.types.Operator):
    bl_idname = "lazy_comfy.render_send"
    bl_label = "Render & Generate"
    bl_description = (
        "Render the scene with the passes the workflow needs, "
        "then send everything to ComfyUI"
    )

    def execute(self, context):
        return render_then_send(self, context, "main")


def render_then_send(op, context, mode):
    """Render with the passes the workflow needs, then build and start the job."""
    s = context.scene.lazy_comfy
    try:
        _, _, _, wanted = workflow_needs(context.scene, context.view_layer, mode)
    except workflows.WorkflowError as e:
        _fail(s, str(e))
        op.report({"ERROR"}, str(e))
        return {"CANCELLED"}
    saved = passes.prepare_scene(context.scene, context.view_layer, wanted)

    if bpy.app.background:
        bpy.ops.render.render()
        try:
            job, files, warnings, info = build_job(context.scene, context.view_layer, mode)
        except (ComfyError, passes.PassError, workflows.WorkflowError) as e:
            passes.restore_scene(saved)
            _fail(s, str(e))
            op.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        passes.restore_scene(saved)
        start_job(context.scene, job, files, warnings, info)
        return {"FINISHED"}

    flag = {"state": None}

    def on_complete(*_):
        flag["state"] = "done"

    def on_cancel(*_):
        flag["state"] = "cancel"

    bpy.app.handlers.render_complete.append(on_complete)
    bpy.app.handlers.render_cancel.append(on_cancel)
    s.status = "Rendering …"
    s.last_error = ""
    scene_name = context.scene.name
    layer_name = context.view_layer.name

    def wait():
        if flag["state"] is None:
            return 0.2
        for lst, fn in ((bpy.app.handlers.render_complete, on_complete), (bpy.app.handlers.render_cancel, on_cancel)):
            if fn in lst:
                lst.remove(fn)
        scene = bpy.data.scenes.get(scene_name)
        if flag["state"] == "done" and scene:
            layer = scene.view_layers.get(layer_name) or scene.view_layers[0]
            try:
                job, files, warnings, info = build_job(scene, layer, mode)
                start_job(scene, job, files, warnings, info)
            except Exception as e:
                _fail(scene.lazy_comfy, str(e))
        elif scene:
            scene.lazy_comfy.status = "Render cancelled"
        passes.restore_scene(saved)
        tag_redraw()
        return None

    bpy.app.timers.register(wait, first_interval=0.2, persistent=True)
    bpy.ops.render.render("INVOKE_DEFAULT")
    return {"FINISHED"}


class LC_OT_edit_selection(bpy.types.Operator):
    bl_idname = "lazy_comfy.edit_selection"
    bl_label = "Redo Selection"
    bl_description = (
        "Repaint only the selected objects in the last result: same seed, new prompt, "
        "everything outside the (grown) mask stays pixel-identical"
    )

    @classmethod
    def poll(cls, context):
        s = context.scene.lazy_comfy
        return state.server and (s.workflow_can_edit or s.edit_workflow) and s.last_result and not s.running

    def execute(self, context):
        return render_then_send(self, context, "edit")


class LC_OT_send(_SendBase, bpy.types.Operator):
    bl_idname = "lazy_comfy.send"
    bl_label = "Send Last Render"
    bl_description = "Send the existing render without re-rendering. Missing passes need a new render"

    def execute(self, context):
        return self._send(context)


class LC_OT_cancel(bpy.types.Operator):
    bl_idname = "lazy_comfy.cancel"
    bl_label = "Cancel"
    bl_description = "Stop the running job in ComfyUI"

    def execute(self, context):
        if state.job:
            state.job.cancel()
        return {"FINISHED"}


class LC_OT_edit_prompt(bpy.types.Operator):
    bl_idname = "lazy_comfy.edit_prompt"
    bl_label = "Edit Prompt"
    bl_description = "Edit the prompt in a large window"
    key: bpy.props.StringProperty(options={"HIDDEN"})

    def _param(self, context):
        return next((p for p in context.scene.lazy_comfy.params if p.key == self.key), None)

    def invoke(self, context, event):
        if self._param(context) is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=820, title=self._param(context).label)

    def draw(self, context):
        import textwrap
        p = self._param(context)
        self.layout.prop(p, "str_v", text="")
        col = self.layout.column(align=True)
        col.scale_y = 0.8
        for line in textwrap.wrap(p.str_v, 120) or [""]:
            col.label(text=line)

    def execute(self, context):
        return {"FINISHED"}


class LC_OT_show_text(bpy.types.Operator):
    bl_idname = "lazy_comfy.show_error"
    bl_label = "Show Message"
    bl_description = "Show the full message"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        for line in context.scene.lazy_comfy.last_error.splitlines():
            self.layout.label(text=line)

    def execute(self, context):
        return {"FINISHED"}


# ---------------------------------------------------------------- model packages

def models_dir():
    p = prefs()
    if p and p.models_dir:
        return bpy.path.abspath(p.models_dir)
    return installer.comfy_desktop_models_dir()


def _select_workflow(scene, filename):
    props.refresh_workflow_items()
    for path, _, _ in state.workflow_items:
        if os.path.basename(path) == filename:
            scene.lazy_comfy.workflow = path
            return True
    return False


def _draw_package_facts(layout, pkg, root):
    st, todo = installer.status(root, pkg)
    col = layout.column(align=True)
    col.label(text=f"Download: {installer.human_size(todo)}   ·   Free: {installer.human_size(installer.free_space(root))}",
              icon="IMPORT")
    lic = pkg["license"]
    col.label(text=f"License: {lic['name']}", icon="CHECKMARK" if lic["commercial"] else "ERROR")
    col.label(text="Commercial use: " + ("yes" if lic["commercial"] else "no") + f"  –  {lic['note']}")
    col.label(text=f"Needs about {pkg['vram_gb']} GB VRAM", icon="MEMORY")
    missing = installer.missing_nodes(pkg, state.object_info) if state.object_info else []
    if missing:
        col.label(text="Missing ComfyUI nodes: " + ", ".join(missing), icon="ERROR")


class LC_OT_install_package(bpy.types.Operator):
    bl_idname = "lazy_comfy.install_package"
    bl_label = "Install Package"
    bl_description = "Download the package's model files into ComfyUI's models folder and select its workflow"
    package_id: bpy.props.StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return state.download is None

    def _pkg(self, context):
        return installer.package(self.package_id or context.scene.lazy_comfy.package)

    def invoke(self, context, event):
        if not models_dir():
            self.report({"ERROR"}, "No ComfyUI models folder found. Set one in the add-on preferences.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text="Download")

    def draw(self, context):
        pkg = self._pkg(context)
        self.layout.label(text=pkg["name"], icon="PACKAGE")
        _draw_package_facts(self.layout, pkg, models_dir())
        self.layout.label(text=f"Into: {models_dir()}")

    def execute(self, context):
        pkg = self._pkg(context)
        root = models_dir()
        if not root:
            self.report({"ERROR"}, "No ComfyUI models folder found. Set one in the add-on preferences.")
            return {"CANCELLED"}
        _, todo = installer.status(root, pkg)
        if todo > installer.free_space(root):
            self.report({"ERROR"}, f"Not enough disk space: {installer.human_size(todo)} needed.")
            return {"CANCELLED"}
        p = prefs()
        dl = installer.Download(pkg, root, p.hf_token if p else "")
        state.download, state.download_message = dl, ""
        dl.start()
        scene_name = context.scene.name

        def poll():
            tag_redraw()
            if not dl.done:
                return 0.5
            state.download = None
            if dl.error:
                state.download_message = dl.error
            elif dl.cancelled:
                state.download_message = "Download cancelled – it resumes where it stopped."
            else:
                state.download_message = f"{pkg['name']} installed."
                scene = bpy.data.scenes.get(scene_name)
                if scene:
                    _select_workflow(scene, pkg["workflow"])
                connect_async()  # ComfyUI lists the new files after a refresh
            tag_redraw()
            return None

        bpy.app.timers.register(poll, first_interval=0.5, persistent=True)
        return {"FINISHED"}


class LC_OT_cancel_download(bpy.types.Operator):
    bl_idname = "lazy_comfy.cancel_download"
    bl_label = "Cancel Download"
    bl_description = "Stop the download. It resumes later where it stopped"

    def execute(self, context):
        if state.download:
            state.download.cancel()
        return {"FINISHED"}


class LC_OT_delete_package(bpy.types.Operator):
    bl_idname = "lazy_comfy.delete_package"
    bl_label = "Delete Package Files"
    bl_description = "Permanently delete this package's model files (files used by another installed package stay)"

    @classmethod
    def poll(cls, context):
        return state.download is None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text="Delete")

    def draw(self, context):
        pkg = installer.package(context.scene.lazy_comfy.package)
        files = installer.removable_files(models_dir(), pkg)
        self.layout.label(text=f"Permanently delete {len(files)} file(s)? This can't be undone.", icon="ERROR")
        col = self.layout.column(align=True)
        for f in files:
            col.label(text=os.path.basename(f))

    def execute(self, context):
        pkg = installer.package(context.scene.lazy_comfy.package)
        files = installer.removable_files(models_dir(), pkg)
        for f in files:
            os.remove(f)
        state.download_message = f"Deleted {len(files)} file(s) of {pkg['name']}."
        connect_async()
        return {"FINISHED"}


def comfyui_dir():
    p = prefs()
    if p and p.comfyui_dir:
        return bpy.path.abspath(p.comfyui_dir)
    return installer.comfy_desktop_comfyui_dir()


class LC_OT_install_nodes(bpy.types.Operator):
    bl_idname = "lazy_comfy.install_nodes"
    bl_label = "Install Blender Nodes"
    bl_description = "Copy the Lazy Comfy nodes into ComfyUI's custom_nodes folder. Restart ComfyUI afterwards"

    def execute(self, context):
        try:
            target = installer.install_nodes(comfyui_dir())
        except (installer.InstallError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        state.download_message = "Blender nodes copied – restart ComfyUI (Comfy Desktop) to load them."
        self.report({"INFO"}, f"Installed to {target}")
        return {"FINISHED"}


class LC_OT_install_examples(bpy.types.Operator):
    bl_idname = "lazy_comfy.install_examples"
    bl_label = "Install Examples"
    bl_description = ("Copy the example workflows into ComfyUI (Workflows › Lazy Comfy). "
                      "Edited examples stay – save your changes with 'Save As' to keep them apart")

    @classmethod
    def poll(cls, context):
        return bool(state.server)

    def execute(self, context):
        try:
            report = templates.install(state.server, examples_manifest_path(), ADDON_VERSION)
            index_comfy_workflows(state.server)
        except ComfyError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        state.examples_message = _examples_summary(report)
        props.refresh_workflow_items(context)
        rebuild_params(context.scene, save_old=True)
        self.report({"INFO"}, state.examples_message)
        return {"FINISHED"}


classes = (
    LC_OT_install_nodes,
    LC_OT_install_examples,
    LC_OT_install_package,
    LC_OT_cancel_download,
    LC_OT_delete_package,
    LC_OT_connect,
    LC_OT_reload_workflows,
    LC_OT_open_folder,
    LC_OT_render_send,
    LC_OT_edit_selection,
    LC_OT_send,
    LC_OT_cancel,
    LC_OT_edit_prompt,
    LC_OT_show_text,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
