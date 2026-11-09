# Lazy Comfy – ComfyUI for Blender

Blender add-on (5.0+): Blender renders, ComfyUI generates. One click sends your render and its passes (depth, line art, normals, object masks) to a local ComfyUI; the result comes back into the Image Editor.

The add-on only does what Blender knows – objects, masks, camera, passes. All image work (models, ControlNets, samplers, LoRAs, upscalers) stays in the ComfyUI workflow.

## Install

Download `lazy_comfy-<version>.zip` from the [latest release](https://github.com/timborabora/lazy_comfy/releases/latest) (not "Code › Download ZIP") and drop it onto Blender, or use Preferences › Get Extensions › Install from Disk.

For automatic updates add the repository once: Preferences › Get Extensions › Repositories › **+** › Add Remote Repository:

```
https://github.com/timborabora/lazy_comfy/releases/latest/download/index.json
```

Tick "Check for Updates on Startup". Blender then offers new versions by itself.

Then, in the panel under Advanced › ComfyUI, click **Install** next to "Blender nodes" and restart ComfyUI once.

## The panel

Render Properties › **Lazy Comfy**:

- header: green/red dot for the ComfyUI connection, ↻ to reconnect
- workflow menu – below it only what is missing (model package with an **Install** button, missing nodes)
- prompt (✎ opens a large editor), negative prompt folded away, then the workflow's own controls
- **Render & Generate**, with a dice toggle: on = a new seed for every render
- after the first result: a **Change** field with **Redo Selection**, and the status line with a folder button
- **Object Prompts** (when the workflow supports them) and **Advanced** (models, render & seed incl. Send Last Render, Redo Selection, model packages, ComfyUI nodes and examples)

Objects get their own prompt under Object Properties › Lazy Comfy.

Every run is logged in the text block `LazyComfy_History` (seed, workflow, all values). ComfyUI also embeds the full workflow in the PNG.

## Where results go

- Saved by the add-on: `lazy_comfy_output` next to the .blend (temp folder if the file is unsaved, or the Output Folder from the preferences).
- ComfyUI's own copy: its output folder, subfolder `lazy_comfy`.
- The control images of the last run: `%TEMP%\lazy_comfy\passes`, and in Blender as images `LC · Depth` etc.

## Workflows

ComfyUI is the workshop: build or change a workflow there and save it normally with **Ctrl+S** – no API export. The Blender menu lists every saved workflow that contains at least one Blender node and converts it itself.

Nodes (category "Lazy Comfy", pack `lazy_comfy_nodes`, ships with the add-on):

| Node | Output | Purpose |
|---|---|---|
| Blender Pass | IMAGE | beauty / depth / lineart / normal |
| Blender Prompt | 2 × STRING | prompt and negative prompt from the panel |
| Blender Object Prompts | CONDITIONING | takes CLIP and a base conditioning, adds each object's masked prompt |
| Blender Selection | MASK, IMAGE, BOOLEAN, STRING | selection mask, previous result, "is this Redo Selection?", change prompt |
| Blender Render Size | 2 × INT | render resolution |
| Blender Setting (Float / Int / Bool) | value | shows up as a control in the panel (label, value, min, max) |

Every node has a built-in placeholder (a blockout room), so a workflow also runs on its own in ComfyUI.

**Your own model:** put the model files into ComfyUI's models folder, build the workflow, add Blender Pass instead of Load Image, Blender Prompt into the text encoder, Blender Render Size into the latent size and a Blender Setting for every value you want as a slider, then save. The simplest start is an example copied with Save As.

**Examples** are copied to *Workflows › Lazy Comfy* on the first connection and via Advanced › **Install Examples**: "SDXL · Canny + Depth", "SDXL · Depth + Objects + Inpaint" and "Qwen 2.1 · Depth (evaluation only)". They are laid out in groups: Blender Inputs → Model → Prompts → Control → Sampler → Inpaint → Output. If you changed an example, your version stays and a newer one is added next to it as "<name> (new).json". Copy an example with **Save As** before you change it.

Subgraphs must be unpacked before saving (right-click › Unpack Subgraph); the panel says so. Reroutes, primitive nodes, muted and bypassed nodes are supported.

## Object prompts

Give objects a prompt in Object Properties › Lazy Comfy, e.g. "glossy red lacquer coffee table". Workflows with the Blender Object Prompts node get a Cryptomatte mask plus prompt for every visible object that has one; the main prompt still covers the rest. Objects outside the frame are skipped.

## Redo Selection

Changes only the selected objects in the last result:

1. Render & Generate.
2. Select objects in the viewport, describe the change ("green velvet sofa").
3. **Redo Selection**. Blender renders the selection mask (grown and feathered, see Advanced), the workflow repaints only there with the same seed and composites the result back – everything outside the mask stays pixel-identical. Edits stack.

## Model packages

Advanced › Model Packages installs curated model files plus a matching workflow. The catalog (`lazy_comfy/catalog.json`) lists source, target folder, size and SHA256 per file, and license, VRAM and required nodes per package.

- A dialog shows size, free disk space and license before downloading.
- Downloads run in the background, resume after an interruption (`.part`) and are checked against their SHA256 before they are moved into place.
- Target is the models folder from Comfy Desktop's settings, or the one set in the preferences.
- **Delete** only removes files no other installed package uses.
- No free URL input. Custom nodes are never installed automatically, only reported.
- A Hugging Face token for gated models belongs in the preferences, never in a .blend. The current packages need none.

Licenses: Juggernaut XL and the xinsir ControlNets allow commercial use of images; Flux.1 [dev] is non-commercial; Qwen-Image 2.1 (qwen-research) is for evaluation only.

## Older API-format workflows

Workflows exported with Workflow › Export (API) still work when "Show API Files" is on in the preferences. They use node titles instead of Blender nodes:

| Title | Node | Effect |
|---|---|---|
| `BL:beauty`, `BL:depth`, `BL:normal`, `BL:lineart` | Load Image | receives that pass |
| `BL:mask_Sofa` | Load Image | white mask of object or collection "Sofa" (else all objects starting with "Sofa") |
| `BL:size` | Empty Latent Image | render resolution (rounded to 8) |
| `BL:result` | Save Image | main result |
| `UI:Name` / `UI:Name [a, b]` | any | all (or only the listed) inputs become panel controls |
| `BL:region_1`, `BL:region_1_mask`, `BL:region_1_prompt` | Conditioning Set Mask, Load Image Mask, Text Encode | one object prompt slot |
| `BL:result_prev`, `BL:mask_selection`, `BL:edit_prompt` | Load Image, Load Image Mask, Text Encode | Redo Selection in edit workflows |

## Notes

- Passes are read from the Render Result; the scene's compositor is left alone. The needed passes (and Freestyle for line art) are switched on for the render and back off afterwards, on every rendered view layer.
- Multilayer EXRs are read both multipart and interleaved (Cycles with denoising).
- Normal ControlNets disagree on the red channel; if lighting looks mirrored, tick "Flip Normal X".
- Coming from Comfy Bridge (the add-on's old name): settings of a still-installed Comfy Bridge, object prompts and panel values in .blend files, and the ComfyUI example folder are taken over automatically.

## Development

```
blender --command extension build --source-dir lazy_comfy --output-dir dist
blender --command extension install-file -r user_default -e dist/lazy_comfy-<version>.zip
blender -b --python tests/blockout_test.py -- none examples/blockout_room.blend
```

`tests/blockout_test.py` builds the blockout room (and with a workflow name sends it through ComfyUI). `tests/nodes_test.py` checks the node templates (against the old workflow, object prompts, Redo Selection), `tests/convert_test.py` runs the templates with placeholders only, `tests/passes_test.py` checks the passes. Templates are built with `tools/make_templates.py`; the node pack lives in `lazy_comfy/comfyui_nodes/lazy_comfy_nodes`. To test without touching your own Blender, set `BLENDER_USER_RESOURCES` to a scratch folder.

Releases: bump the version in `lazy_comfy/blender_manifest.toml`, commit, push, then run `tools/release.ps1`.

License: MIT.
