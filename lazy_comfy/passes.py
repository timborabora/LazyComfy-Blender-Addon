"""Take render passes from the Render Result and write them as control images (PNG).

Saving the Render Result as multilayer EXR includes all active passes, so the
scene's compositor is left alone. Careful: the EXR is usually multipart –
without seek_subimage OpenImageIO only shows part 0.
"""

import json
import os
import struct

import bpy
import numpy as np

try:
    import OpenImageIO as oiio
except ImportError:  # very old Blender builds
    oiio = None


class PassError(RuntimeError):
    pass


def rendered_layers(scene, view_layer):
    """View layers that the next render actually computes."""
    if scene.render.use_single_layer:
        return [view_layer]
    return [vl for vl in scene.view_layers if vl.use] or [view_layer]


def prepare_scene(scene, view_layer, needed):
    """Enable the passes `needed` on every rendered view layer.

    The active layer alone is not enough: if its "Use for Rendering" is off,
    its pass never reaches the render. Returns values to restore.
    """
    saved = {}

    def setattr_saved(obj, attr, value, key):
        saved[key] = (obj, attr, getattr(obj, attr))
        setattr(obj, attr, value)

    if "lineart" in needed:
        setattr_saved(scene.render, "use_freestyle", True, "freestyle")
    for vl in rendered_layers(scene, view_layer):
        n = vl.name
        if "depth" in needed:
            setattr_saved(vl, "use_pass_z", True, n + ":z")
        if "normal" in needed:
            setattr_saved(vl, "use_pass_normal", True, n + ":normal")
        if "crypto" in needed or any(k.startswith("mask:") for k in needed):
            setattr_saved(vl, "use_pass_cryptomatte_object", True, n + ":crypto")
        if "lineart" in needed:
            setattr_saved(vl, "use_freestyle", True, n + ":vl_freestyle")
            setattr_saved(vl.freestyle_settings, "as_render_pass", True, n + ":fs_pass")
            # a line set without a line style draws nothing ("strokes set empty")
            fs = vl.freestyle_settings
            if not fs.linesets:
                fs.linesets.new("CB Linien")
            for lineset in fs.linesets:
                if lineset.linestyle is None:
                    lineset.linestyle = bpy.data.linestyles.get("CB Linien") or bpy.data.linestyles.new("CB Linien")
    return saved


def restore_scene(saved):
    for obj, attr, value in saved.values():
        try:
            setattr(obj, attr, value)
        except (AttributeError, ReferenceError):
            pass


def _save_render(img, scene, path, media_type, file_format, color_mode, color_depth):
    ims = scene.render.image_settings
    old = (ims.media_type, ims.file_format, ims.color_mode, ims.color_depth)
    try:
        ims.media_type = media_type
        ims.file_format = file_format
        ims.color_mode = color_mode
        ims.color_depth = color_depth
        img.save_render(path, scene=scene)
    finally:
        ims.media_type, ims.file_format = old[0], old[1]
        ims.color_mode, ims.color_depth = old[2], old[3]


def _read_exr(path):
    """{part name: (channel names, array HxWxC)} plus the metadata of all parts."""
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise PassError(f"Can't read EXR: {oiio.geterror()}")
    parts, attribs = {}, {}
    k = 0
    while inp.seek_subimage(k, 0):
        spec = inp.spec()
        channels = list(spec.channelnames)
        pixels = inp.read_image(format="float")
        name = spec.getattribute("name")
        if name and not any(c.count(".") >= 2 for c in channels):
            parts[name] = (channels, pixels)
        else:
            # Interleaved (everything in one part, e.g. "Interleave" on or Cycles denoising):
            # group channels "ViewLayer.Depth.Z" into "ViewLayer.Depth".
            groups = {}
            for idx, ch in enumerate(channels):
                key = ch.rsplit(".", 1)[0] if "." in ch else (name or f"part{k}")
                groups.setdefault(key, []).append(idx)
            for key, idxs in groups.items():
                parts[key] = ([channels[i] for i in idxs], pixels[:, :, idxs])
        for a in spec.extra_attribs:
            attribs[a.name] = a.value
        k += 1
    inp.close()
    return parts, attribs


def write_png(path, arr):
    a = np.clip(np.nan_to_num(arr), 0.0, 1.0)
    if a.ndim == 2:
        a = np.repeat(a[:, :, None], 3, axis=2)
    u8 = (a * 255.0 + 0.5).astype(np.uint8)
    h, w, c = u8.shape
    out = oiio.ImageOutput.create(path)
    if out is None:
        raise PassError(f"Can't write PNG: {oiio.geterror()}")
    out.open(path, oiio.ImageSpec(w, h, c, "uint8"))
    out.write_image(u8)
    out.close()
    return path


def _part(parts, view_layer_name, pass_name):
    for name in (f"{view_layer_name}.{pass_name}", pass_name):
        if name in parts:
            return parts[name][1]
    for name, (_, arr) in parts.items():
        if name.endswith("." + pass_name):
            return arr
    return None


def _missing(pass_name, parts):
    layers = sorted({name.rsplit(".", 1)[0] for name in parts if "." in name}) or ["?"]
    return (f"{pass_name} pass missing in the render (rendered: {', '.join(layers)}). "
            "Use Render & Send – Send Last Render only uses what is already there.")


def depth_image(z):
    """Near = bright, far = dark, background black (as depth ControlNets expect)."""
    z = z[:, :, 0] if z.ndim == 3 else z
    valid = np.isfinite(z) & (z > 0) & (z < 1e9)
    if not valid.any():
        raise PassError("Depth pass is empty – is anything in front of the camera?")
    near = float(z[valid].min())
    far = float(np.percentile(z[valid], 99.5))
    if far - near < 1e-6:
        far = near + 1e-6
    d = np.clip((far - z) / (far - near), 0.0, 1.0)
    # small floor so the farthest object doesn't vanish into the background
    d = np.where(valid, 0.06 + 0.94 * d, 0.0)
    return d


def normal_image(n, camera, flip_x=False):
    """World normals to camera space, as RGB = n*0.5+0.5 (blue = towards camera)."""
    n = n[:, :, :3]
    rot = np.array(camera.matrix_world.to_3x3().normalized(), dtype=np.float32)
    cam = n @ rot  # same as rot.T @ n per pixel
    length = np.linalg.norm(cam, axis=2)
    valid = length > 0.5
    cam = cam / np.maximum(length, 1e-6)[:, :, None]
    if flip_x:
        cam[:, :, 0] *= -1.0
    rgb = cam * 0.5 + 0.5
    rgb[~valid] = (0.5, 0.5, 1.0)
    return rgb


def lineart_image(freestyle):
    """Freestyle pass (RGBA lines on transparent) → white lines on black."""
    return freestyle[:, :, 3] if freestyle.shape[2] >= 4 else freestyle.max(axis=2)


def _crypto_manifest(attribs, view_layer_name):
    manifests = {}
    for key, value in attribs.items():
        if key.startswith("cryptomatte/") and key.endswith("/name"):
            prefix = key[: -len("name")]
            manifests[str(value)] = attribs.get(prefix + "manifest", "{}")
    raw = manifests.get(f"{view_layer_name}.CryptoObject")
    if raw is None and manifests:
        raw = next(iter(manifests.values()))
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def _hex_to_float(h):
    return struct.unpack("<f", struct.pack("<I", int(h, 16)))[0]


def mask_targets(name):
    """Objects for BL:mask_<name>: exact object name, else collection, else name prefix."""
    if name in bpy.data.objects:
        return {name}
    coll = bpy.data.collections.get(name)
    if coll:
        return {o.name for o in coll.all_objects}
    low = name.lower()
    return {o.name for o in bpy.data.objects if o.name.lower().startswith(low)}


def object_mask(parts, attribs, view_layer_name, names):
    """Coverage mask of the given object names. Returns (mask, visible) – visible is False
    when none of the objects is actually in the frame."""
    manifest = _crypto_manifest(attribs, view_layer_name)
    ids = [np.float32(_hex_to_float(h)) for obj, h in manifest.items() if obj in names]
    layers = [_part(parts, view_layer_name, f"CryptoObject0{i}") for i in range(3)]
    layers = [l for l in layers if l is not None]
    if not layers:
        raise PassError("No Cryptomatte pass in the render – render again.")
    mask = np.zeros(layers[0].shape[:2], dtype=np.float32)
    for layer in layers:
        for id_ch, cov_ch in ((0, 1), (2, 3)):
            for target in ids:
                mask += np.where(layer[:, :, id_ch] == target, layer[:, :, cov_ch], 0.0)
    mask = np.clip(mask, 0.0, 1.0)
    return mask, bool(mask.max() > 0.01)


def mask_image(parts, attribs, view_layer_name, name):
    return object_mask(parts, attribs, view_layer_name, mask_targets(name))


def _box_blur(a, r):
    if r <= 0:
        return a
    k = 2 * r + 1
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
        a = (np.take(c, range(k, c.shape[axis]), axis=axis) - np.take(c, range(0, c.shape[axis] - k), axis=axis)) / k
    return a


def grow_feather(mask, grow=0, feather=0):
    """Dilate the mask by `grow` pixels, then soften the edge outwards by `feather` pixels.
    The original area stays fully white."""
    m = (mask > 0.5).astype(np.float32) if grow or feather else mask
    for _ in range(grow):
        m = np.maximum.reduce([m, np.roll(m, 1, 0), np.roll(m, -1, 0), np.roll(m, 1, 1), np.roll(m, -1, 1)])
    if feather:
        core = m.copy()
        for _ in range(feather):  # grow, then blur back: soft falloff outside the core
            m = np.maximum.reduce([m, np.roll(m, 1, 0), np.roll(m, -1, 0), np.roll(m, 1, 1), np.roll(m, -1, 1)])
        m = np.maximum(_box_blur(_box_blur(m, feather // 2 + 1), feather // 2 + 1), core)
    return np.clip(m, 0.0, 1.0)


def resize_nearest(a, width, height):
    h, w = a.shape[:2]
    if (w, h) == (width, height):
        return a
    ys = (np.arange(height) * h / height).astype(int)
    xs = (np.arange(width) * w / width).astype(int)
    return a[ys][:, xs]


def export(scene, view_layer, needed, out_dir, flip_normal_x=False, masks=None):
    """Write all needed control images. Returns ({pass_key: path}, [warnings], {mask_key: visible}).

    `masks` = {key: {"names": set, "grow": px, "feather": px, "size": (w, h) or None}} for
    object masks the add-on builds itself (object prompts, edit selection)."""
    masks = masks or {}
    if oiio is None:
        raise PassError("OpenImageIO is missing in this Blender build.")
    img = bpy.data.images.get("Render Result")
    if img is None:
        raise PassError("No render yet – render first (F12).")
    os.makedirs(out_dir, exist_ok=True)
    files, warnings, visible = {}, [], {}

    beauty = os.path.join(out_dir, "lc_beauty.png")
    try:
        _save_render(img, scene, beauty, "IMAGE", "PNG", "RGB", "8")
    except RuntimeError as e:
        raise PassError(f"Render Result is empty – render first (F12). ({e})") from e
    files["beauty"] = beauty

    rest = [k for k in needed if k != "beauty"]
    if not rest and not masks:
        return files, warnings, visible

    exr = os.path.join(out_dir, "lc_passes.exr")
    _save_render(img, scene, exr, "MULTI_LAYER_IMAGE", "OPEN_EXR_MULTILAYER", "RGBA", "32")
    parts, attribs = _read_exr(exr)
    vl = view_layer.name

    for key in rest:
        path = os.path.join(out_dir, f"lc_{key.replace(':', '_')}.png")
        if key == "depth":
            z = _part(parts, vl, "Depth")
            if z is None:
                raise PassError(_missing("Depth", parts))
            write_png(path, depth_image(z))
        elif key == "normal":
            n = _part(parts, vl, "Normal")
            if n is None:
                raise PassError(_missing("Normal", parts))
            if scene.camera is None:
                raise PassError("The scene has no camera.")
            write_png(path, normal_image(n, scene.camera, flip_normal_x))
        elif key == "lineart":
            fs = _part(parts, vl, "Freestyle")
            if fs is None:
                raise PassError(_missing("Freestyle", parts))
            write_png(path, lineart_image(fs))
        elif key.startswith("mask:"):
            name = key[5:]
            mask, found = mask_image(parts, attribs, vl, name)
            if not found:
                warnings.append(f"Mask '{name}': no object or collection with that name in the image.")
            write_png(path, mask)
        else:
            continue
        files[key] = path

    for key, spec in masks.items():
        mask, seen = object_mask(parts, attribs, vl, spec["names"])
        mask = grow_feather(mask, spec.get("grow", 0), spec.get("feather", 0))
        if spec.get("size"):
            mask = resize_nearest(mask, *spec["size"])
        path = os.path.join(out_dir, f"lc_{key.replace(':', '_')}.png")
        write_png(path, mask)
        files[key], visible[key] = path, seen
    return files, warnings, visible
