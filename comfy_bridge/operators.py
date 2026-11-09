import copy
import json
import os
import random
import tempfile
import threading
import time

import bpy

from . import comfy_client, passes, pipeline, props, state, workflows
from .comfy_client import ComfyError

HISTORY_TEXT = "ComfyBridge_History"
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

    def work():
        try:
            base, stats = comfy_client.find_server(preferred)
            if not base:
                raise ComfyError("ComfyUI not found. Is Comfy Desktop running?")
            info = comfy_client.get_json(base, "/object_info", timeout=30)
            state.server, state.stats, state.object_info = base, stats, info
        except Exception as e:
            state.server, state.stats = None, None
            state.connect_error = str(e)
        finally:
            state.connecting = False

    threading.Thread(target=work, daemon=True).start()

    def wait():
        if state.connecting:
            return 0.2
        for scene in bpy.data.scenes:
            rebuild_params(scene, save_old=True)
        tag_redraw()
        return None

    bpy.app.timers.register(wait, first_interval=0.2, persistent=True)


def connect_sync(preferred=""):
    """For scripts and tests."""
    base, stats = comfy_client.find_server(preferred)
    if not base:
        raise ComfyError("ComfyUI not found.")
    state.server, state.stats = base, stats
    state.object_info = comfy_client.get_json(base, "/object_info", timeout=30)
    return base


# ---------------------------------------------------------------- parameters

def _current_values(settings):
    return {p.key: p.get_value() for p in settings.params}


def rebuild_params(scene, save_old=True, from_user=False):
    """Re-read the selected workflow and rebuild the panel fields."""
    s = scene.comfy_bridge
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
    if not path:
        s.saved_values = json.dumps(saved)
        return
    try:
        wf = workflows.load(path)
    except workflows.WorkflowError as e:
        s.workflow_warnings = str(e)
        s.saved_values = json.dumps(saved)
        return
    analysis = workflows.analyze(wf, state.object_info)
    s.workflow_info = workflows.describe(analysis)
    s.workflow_family = analysis["family"]
    s.workflow_needed = ",".join(analysis["images"])
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


# ---------------------------------------------------------------- sending

def _output_dir():
    p = prefs()
    if p and p.output_dir:
        return bpy.path.abspath(p.output_dir)
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "comfy_bridge_output")
    return os.path.join(tempfile.gettempdir(), "comfy_bridge", "output")


def _pass_dir():
    return os.path.join(tempfile.gettempdir(), "comfy_bridge", "passes")


def _wanted_passes(s, needed):
    wanted = list(needed)
    for key, flag in (("beauty", s.extra_beauty), ("depth", s.extra_depth),
                      ("normal", s.extra_normal), ("lineart", s.extra_lineart)):
        if flag and key not in wanted:
            wanted.append(key)
    if "beauty" not in wanted:
        wanted.insert(0, "beauty")
    return wanted


def build_job(scene, view_layer):
    """Export the passes and prepare the workflow. Returns (job, control images, warnings, info)."""
    s = scene.comfy_bridge
    if not state.server:
        raise ComfyError("Not connected to ComfyUI.")
    wf = workflows.load(s.workflow)
    analysis = workflows.analyze(wf, state.object_info)
    wanted = _wanted_passes(s, analysis["images"].keys())
    files, warnings = passes.export(scene, view_layer, wanted, _pass_dir(), s.normal_flip_x)

    wf = copy.deepcopy(wf)
    for p in s.params:
        node = wf.get(p.node_id)
        if node and p.input_name in node.get("inputs", {}):
            node["inputs"][p.input_name] = p.get_value()

    if s.seed_random:
        s.seed = random.randint(0, 2**31 - 1)
    for node in wf.values():
        for name in workflows.SEED_INPUTS:
            if name in node.get("inputs", {}) and not workflows.is_link(node["inputs"][name]):
                node["inputs"][name] = s.seed
    s.last_seed = s.seed

    r = scene.render
    width = max(64, int(r.resolution_x * r.resolution_percentage / 100) // 8 * 8)
    height = max(64, int(r.resolution_y * r.resolution_percentage / 100) // 8 * 8)
    for nid in analysis["size_nodes"]:
        wf[nid]["inputs"]["width"], wf[nid]["inputs"]["height"] = width, height

    uploads = []
    for key, node_ids in analysis["images"].items():
        path = files.get(key)
        if not path:
            raise passes.PassError(f"Control image '{key}' is missing.")
        uploads.append((path, os.path.basename(path), node_ids))

    job = pipeline.Job(state.server, wf, state.client_id, uploads, _output_dir(), analysis["result_nodes"])
    info = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workflow": os.path.basename(s.workflow),
        "seed": s.seed,
        "resolution": f"{width}x{height}",
        "values": {p.label: p.get_value() for p in s.params},
    }
    return job, files, warnings, info


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
    s = scene.comfy_bridge
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
    text = bpy.data.texts.get(HISTORY_TEXT) or bpy.data.texts.new(HISTORY_TEXT)
    text.write(json.dumps(info, ensure_ascii=False) + "\n")
    s.status = f"Done · seed {info['seed']}"
    s.last_error = ""


def start_job(scene, job, files, warnings, info):
    s = scene.comfy_bridge
    if s.load_control_images:
        for key, path in files.items():
            load_image("CB · " + PASS_IMAGE_LABELS.get(key, "Mask " + key[5:]), path)
    s.running, s.progress, s.last_error = True, 0.0, "\n".join(warnings)
    s.status = "Sending to ComfyUI …"
    state.job = job
    job.start()
    scene_name = scene.name

    def poll():
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        sc = scene.comfy_bridge
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


def run_blocking(scene, view_layer):
    """Synchronous for scripts/tests: passes from the existing render, send, wait, load the result."""
    job, files, warnings, info = build_job(scene, view_layer)
    job.run()
    finish_job(scene, job, info)
    return job, files, warnings


# ---------------------------------------------------------------- operators

class CB_OT_connect(bpy.types.Operator):
    bl_idname = "comfy_bridge.connect"
    bl_label = "Connect"
    bl_description = "Find ComfyUI and reload its models and nodes"

    def execute(self, context):
        props.refresh_workflow_items(context)
        connect_async()
        return {"FINISHED"}


class CB_OT_reload_workflows(bpy.types.Operator):
    bl_idname = "comfy_bridge.reload_workflows"
    bl_label = "Reload Workflows"
    bl_description = "Rescan the workflow folders and re-read the selected workflow"

    def execute(self, context):
        props.refresh_workflow_items(context)
        rebuild_params(context.scene, save_old=True)
        return {"FINISHED"}


class CB_OT_open_folder(bpy.types.Operator):
    bl_idname = "comfy_bridge.open_folder"
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
        s = context.scene.comfy_bridge
        return state.server and s.workflow and not s.running

    def _send(self, context):
        try:
            job, files, warnings, info = build_job(context.scene, context.view_layer)
        except (ComfyError, passes.PassError, workflows.WorkflowError) as e:
            _fail(context.scene.comfy_bridge, str(e))
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        start_job(context.scene, job, files, warnings, info)
        for w in warnings:
            self.report({"WARNING"}, w)
        return {"FINISHED"}


class CB_OT_render_send(_SendBase, bpy.types.Operator):
    bl_idname = "comfy_bridge.render_send"
    bl_label = "Render & Send"
    bl_description = (
        "Render the scene with the passes the workflow needs, "
        "then send everything to ComfyUI"
    )

    def execute(self, context):
        s = context.scene.comfy_bridge
        wf = workflows.load(s.workflow)
        analysis = workflows.analyze(wf, state.object_info)
        wanted = _wanted_passes(s, analysis["images"].keys())
        saved = passes.prepare_scene(context.scene, context.view_layer, wanted)

        if bpy.app.background:
            bpy.ops.render.render()
            result = self._send(context)
            passes.restore_scene(saved)
            return result

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
                    job, files, warnings, info = build_job(scene, layer)
                    start_job(scene, job, files, warnings, info)
                except Exception as e:
                    _fail(scene.comfy_bridge, str(e))
            elif scene:
                scene.comfy_bridge.status = "Render cancelled"
            passes.restore_scene(saved)
            tag_redraw()
            return None

        bpy.app.timers.register(wait, first_interval=0.2, persistent=True)
        bpy.ops.render.render("INVOKE_DEFAULT")
        return {"FINISHED"}


class CB_OT_send(_SendBase, bpy.types.Operator):
    bl_idname = "comfy_bridge.send"
    bl_label = "Send Last Render"
    bl_description = "Send the existing render without re-rendering. Missing passes need a new render"

    def execute(self, context):
        return self._send(context)


class CB_OT_cancel(bpy.types.Operator):
    bl_idname = "comfy_bridge.cancel"
    bl_label = "Cancel"
    bl_description = "Stop the running job in ComfyUI"

    def execute(self, context):
        if state.job:
            state.job.cancel()
        return {"FINISHED"}


class CB_OT_show_text(bpy.types.Operator):
    bl_idname = "comfy_bridge.show_error"
    bl_label = "Show Message"
    bl_description = "Show the full message"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        for line in context.scene.comfy_bridge.last_error.splitlines():
            self.layout.label(text=line)

    def execute(self, context):
        return {"FINISHED"}


classes = (
    CB_OT_connect,
    CB_OT_reload_workflows,
    CB_OT_open_folder,
    CB_OT_render_send,
    CB_OT_send,
    CB_OT_cancel,
    CB_OT_show_text,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
