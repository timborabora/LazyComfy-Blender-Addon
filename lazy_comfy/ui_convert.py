"""Convert workflows saved in ComfyUI (UI format, Ctrl+S) to the API format /prompt expects.

Handles widget order (from /object_info), links, Reroute and Primitive nodes, bypassed
and muted nodes. Subgraphs are reported instead of guessed.
"""

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
SEED_CONTROL = {"fixed", "increment", "decrement", "randomize"}
VIRTUAL = {"Reroute", "PrimitiveNode", "Note", "MarkdownNote"}
MODE_MUTED, MODE_BYPASS = 2, 4


class ConvertError(RuntimeError):
    pass


def is_ui_format(data):
    return isinstance(data, dict) and "nodes" in data and "links" in data


def _input_order(spec):
    order = spec.get("input_order")
    groups = spec.get("input", {})
    if order:
        return [(g, n) for g in ("required", "optional") for n in order.get(g, [])]
    return [(g, n) for g in ("required", "optional") for n in (groups.get(g) or {})]


def _is_widget(input_spec):
    kind = input_spec[0]
    opts = input_spec[1] if len(input_spec) > 1 and isinstance(input_spec[1], dict) else {}
    if opts.get("forceInput"):
        return False
    return isinstance(kind, list) or kind in WIDGET_TYPES


def _links(ui):
    out = {}
    for link in ui.get("links", []):
        if isinstance(link, dict):
            out[link["id"]] = (link["origin_id"], link["origin_slot"])
        else:
            out[link[0]] = (link[1], link[2])
    return out


def convert(ui, object_info):
    """Returns the API-format dict. Raises ConvertError with a readable message."""
    subgraph_ids = {sg.get("id") for sg in (ui.get("definitions") or {}).get("subgraphs", [])}
    nodes = {n["id"]: n for n in ui.get("nodes", [])}
    if any(n.get("type") in subgraph_ids for n in nodes.values()):
        raise ConvertError("This workflow uses subgraphs. Unpack them in ComfyUI "
                           "(right-click the subgraph › Unpack Subgraph) and save again.")
    unknown = sorted({n["type"] for n in nodes.values()
                      if n.get("type") not in object_info and n.get("type") not in VIRTUAL
                      and n.get("mode", 0) != MODE_MUTED})
    if unknown:
        raise ConvertError("Nodes not installed in ComfyUI: " + ", ".join(unknown))
    links = _links(ui)

    def resolve(link_id, seen=()):
        """Where a link really comes from: ('link', [id, slot]) / ('value', v) / None."""
        if link_id is None or link_id not in links or link_id in seen:
            return None
        origin_id, slot = links[link_id]
        node = nodes.get(origin_id)
        if node is None or node.get("mode", 0) == MODE_MUTED:
            return None
        if node["type"] == "Reroute":
            return resolve((node.get("inputs") or [{}])[0].get("link"), seen + (link_id,))
        if node["type"] == "PrimitiveNode":
            values = node.get("widgets_values") or []
            return ("value", values[0]) if values else None
        if node.get("mode", 0) == MODE_BYPASS:
            out_type = (node.get("outputs") or [{}] * (slot + 1))[slot].get("type")
            for inp in node.get("inputs") or []:
                if inp.get("link") is not None and (inp.get("type") == out_type or out_type in (None, "*")):
                    return resolve(inp["link"], seen + (link_id,))
            return None
        return ("link", [str(origin_id), slot])

    api = {}
    for node_id, node in nodes.items():
        cls = node.get("type")
        if cls in VIRTUAL or node.get("mode", 0) in (MODE_MUTED, MODE_BYPASS):
            continue
        spec = object_info[cls]
        inputs = {}
        values = node.get("widgets_values")
        if isinstance(values, dict):
            for group, name in _input_order(spec):
                if name in values and _is_widget(spec["input"][group][name]):
                    inputs[name] = values[name]
        else:
            values = list(values or [])
            i = 0
            for group, name in _input_order(spec):
                ispec = spec["input"][group][name]
                if not _is_widget(ispec):
                    continue
                if i < len(values):
                    inputs[name] = values[i]
                    i += 1
                    opts = ispec[1] if len(ispec) > 1 and isinstance(ispec[1], dict) else {}
                    # seed widgets carry an extra "control after generate" value
                    if (opts.get("control_after_generate") or name in ("seed", "noise_seed")) \
                            and i < len(values) and values[i] in SEED_CONTROL:
                        i += 1
        for inp in node.get("inputs") or []:
            if inp.get("link") is None:
                continue
            got = resolve(inp["link"])
            if got is None:
                continue
            inputs[inp["name"]] = got[1]
        title = node.get("title") or spec.get("display_name") or cls
        api[str(node_id)] = {"class_type": cls, "inputs": inputs, "_meta": {"title": title}}

    # Drop links to nodes that were removed (muted/bypassed without a pass-through)
    missing = []
    for nid, node in api.items():
        spec = object_info[node["class_type"]]
        for name, value in list(node["inputs"].items()):
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int) and value[0] not in api:
                del node["inputs"][name]
        for name, ispec in (spec.get("input", {}).get("required") or {}).items():
            kind = ispec[0]
            if isinstance(kind, str) and kind.startswith("COMFY_AUTOGROW"):
                continue  # dynamic input lists may stay empty
            if name not in node["inputs"]:
                missing.append(f"{node['_meta']['title']}: '{name}' is not connected")
    if missing:
        raise ConvertError("Workflow is incomplete – " + "; ".join(missing[:5]))
    return api
