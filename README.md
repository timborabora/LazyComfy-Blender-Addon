# Comfy Bridge

Blender-Add-on (ab 5.0): Blender rendert, ComfyUI rechnet. Render und Render-Pässe gehen mit einem Klick an das lokale ComfyUI, das Ergebnis landet im Image Editor.

Das Panel sitzt unter **Render Properties → Comfy Bridge**.

## Ablauf

1. Comfy Desktop starten. Das Add-on findet den Server selbst (8188, 8000, …). Mit ↻ wird neu gesucht.
2. Workflow wählen. Das Panel zeigt, welche Pässe der Workflow braucht, und baut Modell-Dropdowns und Regler aus dem Workflow auf.
3. **Rendern & an ComfyUI senden**. Blender rendert mit den nötigen Pässen, erzeugt die Steuerbilder, lädt sie hoch und zeigt den Fortschritt. Das Ergebnis heißt im Image Editor `ComfyUI Ergebnis`.

**Letzten Render senden** nimmt den vorhandenen Render. Fehlen Pässe (z. B. Depth), braucht es einen neuen Render.

Jeder Lauf landet als Zeile im Textblock `ComfyBridge_Verlauf` (Seed, Workflow, alle Werte). ComfyUI schreibt zusätzlich den kompletten Workflow in die PNG.

## Eigene Workflows

In ComfyUI bauen, einmal dort testen, dann **Workflow → Export (API)** und die JSON in den Workflow-Ordner legen. Der Ordner wird in den Add-on-Einstellungen gewählt, mit dem 📁-Knopf öffnest du ihn. Gesteuert wird über Node-Titel (Rechtsklick auf den Node → Title):

| Titel | Node | Wirkung |
|---|---|---|
| `BL:beauty` | Load Image | bekommt den normalen Render |
| `BL:depth` | Load Image | Tiefe: nah = hell, fern = dunkel, Hintergrund schwarz |
| `BL:normal` | Load Image | Normalen im Kameraraum (blau = zur Kamera) |
| `BL:lineart` | Load Image | Freestyle-Linien, weiß auf schwarz |
| `BL:mask_Sofa` | Load Image | weiße Maske für Objekt oder Collection „Sofa“ (sonst alle Objekte, die mit „Sofa“ anfangen) |
| `BL:size` | Empty Latent Image | bekommt die Render-Auflösung (auf 8 gerundet) |
| `BL:result` | Save Image | gilt als Hauptergebnis |
| `UI:Name` | beliebig | alle Werte des Nodes erscheinen als Regler im Panel |

Fehlt `BL:size`, bekommen alle Empty-Latent-Nodes die Auflösung. Modell-Dateien (Checkpoints, ControlNets, VAE, Encoder, LoRAs) erscheinen immer als Dropdown, gefüllt mit dem, was in ComfyUI liegt. ControlNets werden am Dateinamen nach SDXL/Flux gefiltert. „Alle Modelle zeigen“ hebt den Filter auf. Seeds werden in allen KSamplern gesetzt.

Werte, die du im Panel änderst, merkt sich die .blend pro Workflow.

## Mitgelieferte Beispiele

- **SDXL Canny Depth**: Juggernaut XL, Canny aus dem Beauty-Render plus Depth aus Blender.
- **Flux GGUF Canny Depth**: Flux.1 dev Q8 (GGUF), InstantX Canny, Shakker Depth.

Benötigte Dateien im ComfyUI-Modellordner: `juggernautXL_ragnarokBy.safetensors`, `controlnet-canny-sdxl.safetensors` (xinsir), `controlnet-depth-sdxl.safetensors` (xinsir), `flux1-dev-Q8_0.gguf`, `t5-v1_1-xxl-encoder-Q8_0.gguf`, `clip_l.safetensors`, `ae.safetensors`, `flux-canny-instantx.safetensors`, `flux-depth-shakker.safetensors`. Für den Flux-Workflow braucht es außerdem die Custom Nodes ComfyUI-GGUF.

Flux.1 dev steht unter der FLUX Non-Commercial License.

## Hinweise

- Pässe werden aus dem Render Result gelesen. Den Compositor deiner Szene fasst das Add-on nicht an. Für den Render schaltet es die nötigen Pässe (und für Line Art Freestyle) kurz ein und danach wieder aus.
- Normal-ControlNets sind sich bei der Rot-Richtung nicht einig. Wirkt das Ergebnis seitenverkehrt beleuchtet, „Normal: Rot spiegeln“ anhaken.

## Entwicklung

```
blender --command extension build --source-dir comfy_bridge --output-dir dist
blender --command extension install-file -r user_default -e dist/comfy_bridge-0.1.0.zip
blender -b --python tests/blockout_test.py -- SDXL_Canny_Depth.json
```

`tests/blockout_test.py` baut einen Blockout-Raum, rendert ihn und schickt ihn durch ComfyUI (ComfyUI muss laufen). `tests/passes_test.py` prüft nur die Pässe.

Releases: `tools/release.ps1` baut das Paket und den Extension-Index und legt ein GitHub-Release an. In Blender wird einmal `https://github.com/<owner>/comfy_bridge/releases/latest/download/index.json` als Remote Repository eingetragen. Danach bietet Blender neue Versionen selbst an.
