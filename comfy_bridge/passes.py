"""Render-Pässe aus dem Render Result holen und als Steuerbilder (PNG) schreiben.

Blender speichert beim Sichern des Render Results als Multilayer-EXR alle aktiven
Pässe mit. Den Compositor der Szene fassen wir dafür nicht an.
Achtung: Die EXR ist mehrteilig – OpenImageIO zeigt ohne seek_subimage nur Teil 0.
"""

import json
import os
import struct

import bpy
import numpy as np

try:
    import OpenImageIO as oiio
except ImportError:  # sehr alte Blender-Builds
    oiio = None


class PassError(RuntimeError):
    pass


def rendered_layers(scene, view_layer):
    """View Layers, die beim nächsten Render tatsächlich gerechnet werden."""
    if scene.render.use_single_layer:
        return [view_layer]
    return [vl for vl in scene.view_layers if vl.use] or [view_layer]


def prepare_scene(scene, view_layer, needed):
    """Schaltet die für `needed` nötigen Pässe auf allen gerenderten View Layers ein.

    Nur die aktive Layer reicht nicht: Ist bei ihr „Use for Rendering“ aus,
    landet ihr Pass nie im Render. Rückgabe: Werte zum Zurücksetzen.
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
        if any(k.startswith("mask:") for k in needed):
            setattr_saved(vl, "use_pass_cryptomatte_object", True, n + ":crypto")
        if "lineart" in needed:
            setattr_saved(vl, "use_freestyle", True, n + ":vl_freestyle")
            setattr_saved(vl.freestyle_settings, "as_render_pass", True, n + ":fs_pass")
            # Ein LineSet ohne Linienstil zeichnet nichts („strokes set empty“)
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
    """{teilname: (kanalnamen, array HxWxC)} plus alle Metadaten aller Teile."""
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise PassError(f"EXR nicht lesbar: {oiio.geterror()}")
    parts, attribs = {}, {}
    k = 0
    while inp.seek_subimage(k, 0):
        spec = inp.spec()
        name = spec.getattribute("name") or f"part{k}"
        parts[name] = (list(spec.channelnames), inp.read_image(format="float"))
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
        raise PassError(f"PNG nicht schreibbar: {oiio.geterror()}")
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
    return (f"{pass_name}-Pass fehlt im Render (gerendert: {', '.join(layers)}). "
            "Mit „Rendern & senden“ neu rendern – „Letzten Render senden“ nutzt nur, was schon da ist.")


def depth_image(z):
    """Nah = hell, fern = dunkel, Hintergrund schwarz (wie Depth-ControlNets es erwarten)."""
    z = z[:, :, 0] if z.ndim == 3 else z
    valid = np.isfinite(z) & (z > 0) & (z < 1e9)
    if not valid.any():
        raise PassError("Depth-Pass ist leer – ist etwas vor der Kamera?")
    near = float(z[valid].min())
    far = float(np.percentile(z[valid], 99.5))
    if far - near < 1e-6:
        far = near + 1e-6
    d = np.clip((far - z) / (far - near), 0.0, 1.0)
    # kleiner Mindestwert, damit das fernste Objekt nicht im Hintergrund verschwindet
    d = np.where(valid, 0.06 + 0.94 * d, 0.0)
    return d


def normal_image(n, camera, flip_x=False):
    """Welt-Normalen in Kamera-Raum, als RGB = n*0.5+0.5 (blau = zur Kamera)."""
    n = n[:, :, :3]
    rot = np.array(camera.matrix_world.to_3x3().normalized(), dtype=np.float32)
    cam = n @ rot  # entspricht rot.T @ n pro Pixel
    length = np.linalg.norm(cam, axis=2)
    valid = length > 0.5
    cam = cam / np.maximum(length, 1e-6)[:, :, None]
    if flip_x:
        cam[:, :, 0] *= -1.0
    rgb = cam * 0.5 + 0.5
    rgb[~valid] = (0.5, 0.5, 1.0)
    return rgb


def lineart_image(freestyle):
    """Freestyle-Pass (RGBA-Linien auf transparent) → weiße Linien auf Schwarz."""
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
    """Objekte für BL:mask_<name>: exakter Objektname, sonst Collection, sonst Namensanfang."""
    if name in bpy.data.objects:
        return {name}
    coll = bpy.data.collections.get(name)
    if coll:
        return {o.name for o in coll.all_objects}
    low = name.lower()
    return {o.name for o in bpy.data.objects if o.name.lower().startswith(low)}


def mask_image(parts, attribs, view_layer_name, name):
    manifest = _crypto_manifest(attribs, view_layer_name)
    targets = mask_targets(name)
    ids = [np.float32(_hex_to_float(h)) for obj, h in manifest.items() if obj in targets]
    layers = [_part(parts, view_layer_name, f"CryptoObject0{i}") for i in range(3)]
    layers = [l for l in layers if l is not None]
    if not layers:
        raise PassError("Kein Cryptomatte-Pass im Render – bitte neu rendern.")
    mask = np.zeros(layers[0].shape[:2], dtype=np.float32)
    for layer in layers:
        for id_ch, cov_ch in ((0, 1), (2, 3)):
            for target in ids:
                mask += np.where(layer[:, :, id_ch] == target, layer[:, :, cov_ch], 0.0)
    return np.clip(mask, 0.0, 1.0), bool(ids)


def export(scene, view_layer, needed, out_dir, flip_normal_x=False):
    """Schreibt alle benötigten Steuerbilder. Rückgabe: ({pass_key: pfad}, [warnungen])."""
    if oiio is None:
        raise PassError("OpenImageIO fehlt in diesem Blender-Build.")
    img = bpy.data.images.get("Render Result")
    if img is None:
        raise PassError("Kein Render vorhanden – zuerst rendern (F12).")
    os.makedirs(out_dir, exist_ok=True)
    files, warnings = {}, []

    beauty = os.path.join(out_dir, "cb_beauty.png")
    try:
        _save_render(img, scene, beauty, "IMAGE", "PNG", "RGB", "8")
    except RuntimeError as e:
        raise PassError(f"Render Result leer – zuerst rendern (F12). ({e})") from e
    files["beauty"] = beauty

    rest = [k for k in needed if k != "beauty"]
    if not rest:
        return files, warnings

    exr = os.path.join(out_dir, "cb_passes.exr")
    _save_render(img, scene, exr, "MULTI_LAYER_IMAGE", "OPEN_EXR_MULTILAYER", "RGBA", "32")
    parts, attribs = _read_exr(exr)
    vl = view_layer.name

    for key in rest:
        path = os.path.join(out_dir, f"cb_{key.replace(':', '_')}.png")
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
                raise PassError("Szene hat keine Kamera.")
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
                warnings.append(f"Maske „{name}“: kein Objekt oder keine Collection mit diesem Namen im Bild.")
            write_png(path, mask)
        else:
            continue
        files[key] = path
    return files, warnings
