"""Carry data over from the add-on's old name (Comfy Bridge).

- preferences of an old installation that is still enabled
- per-object prompts and panel values stored in .blend files
- the example folder and its hash manifest in ComfyUI
"""

import json
import os
import urllib.parse

import bpy

OLD_MODULES = ("bl_ext.comfy_bridge_github.comfy_bridge", "bl_ext.user_default.comfy_bridge", "comfy_bridge")
OLD_PREFIX = "comfy:Comfy Bridge/"
NEW_PREFIX = "comfy:Lazy Comfy/"
PREF_FIELDS = ("server_url", "show_api_files", "workflow_dir", "output_dir", "models_dir", "comfyui_dir", "hf_token")
SCENE_FIELDS = ("workflow_path", "saved_values", "seed", "seed_random", "region_strength", "edit_prompt",
                "edit_grow", "edit_feather", "last_result", "last_seed", "extra_beauty", "extra_depth",
                "extra_normal", "extra_lineart", "normal_flip_x", "load_control_images", "show_result")


def old_addon_module(context=None):
    context = context or bpy.context
    return next((m for m in OLD_MODULES if m in context.preferences.addons), None)


def preferences(new_prefs, context=None):
    """Copy settings from an enabled old installation into empty new ones. Returns copied field names."""
    module = old_addon_module(context)
    if not module or new_prefs is None:
        return []
    old = (context or bpy.context).preferences.addons[module].preferences
    copied = []
    for name in PREF_FIELDS:
        value = getattr(old, name, None)
        if value and not getattr(new_prefs, name):
            setattr(new_prefs, name, value)
            copied.append(name)
    return copied


def _rename_ident(value):
    return NEW_PREFIX + value[len(OLD_PREFIX):] if isinstance(value, str) and value.startswith(OLD_PREFIX) else value


def blend_data():
    """Move old object prompts and scene settings to the new property names. Returns a short report."""
    prompts = scenes = 0
    for obj in bpy.data.objects:
        if "comfy_prompt" in obj.keys():
            old = obj["comfy_prompt"]
            if isinstance(old, str) and old and not obj.lazy_comfy_prompt:
                obj.lazy_comfy_prompt = old
                prompts += 1
            del obj["comfy_prompt"]
    for scene in bpy.data.scenes:
        if "comfy_bridge" not in scene.keys():
            continue
        old = scene["comfy_bridge"]
        old = old.to_dict() if hasattr(old, "to_dict") else {}
        new = scene.lazy_comfy
        for name in SCENE_FIELDS:
            if name not in old:
                continue
            value = old[name]
            if name == "workflow_path":
                value = _rename_ident(value)
            elif name == "saved_values":
                try:
                    value = json.dumps({_rename_ident(k): v for k, v in json.loads(value or "{}").items()})
                except ValueError:
                    continue
            try:
                setattr(new, name, value)
            except (TypeError, ValueError, AttributeError):
                pass
        del scene["comfy_bridge"]
        scenes += 1
    return prompts, scenes


def old_manifest_paths():
    """Where the old add-on kept its example hash manifest (call on the main thread)."""
    import tempfile
    try:
        ext = bpy.utils.user_resource("EXTENSIONS")
    except (ValueError, AttributeError):
        ext = ""
    paths = [os.path.join(ext, ".user", repo, "comfy_bridge", "examples_manifest.json")
             for repo in ("comfy_bridge_github", "user_default")] if ext else []
    return paths + [os.path.join(tempfile.gettempdir(), "comfy_bridge", "examples_manifest.json")]


def comfy_examples(base, manifest_path, old_manifests, client):
    """Move workflows from ComfyUI's old "Comfy Bridge" folder to "Lazy Comfy" and keep the hash manifest."""
    if not os.path.exists(manifest_path):
        for old in old_manifests:
            if os.path.exists(old):
                os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                with open(old, "rb") as src, open(manifest_path, "wb") as dst:
                    dst.write(src.read())
                break
    moved = []
    status, body = client._request(base + "/api/userdata?dir=workflows&recurse=true&split=false", timeout=30)
    if status != 200:
        return moved
    for path in json.loads(body):
        path = path.replace("\\", "/") if isinstance(path, str) else path.get("path", "").replace("\\", "/")
        if not path.startswith("Comfy Bridge/"):
            continue
        new = "Lazy Comfy/" + path[len("Comfy Bridge/"):]
        src = urllib.parse.quote("workflows/" + path, safe="")
        dst = urllib.parse.quote("workflows/" + new, safe="")
        status, _ = client._request(f"{base}/api/userdata/{src}/move/{dst}", data=b"", timeout=30)
        if status == 200:
            moved.append(new)
    return moved
