# Comfy Bridge

Blender-Add-on (ab 5.0): Blender rendert, ComfyUI rechnet. Render und Render-Pässe gehen mit einem Klick an das lokale ComfyUI, das Ergebnis landet im Image Editor.

Das Panel sitzt unter **Render Properties → Comfy Bridge** und ist auf Englisch. Oben stehen Verbindung, Workflow, **Render & Send**, **Send Last Render** und der Status, darunter einklappbare Bereiche:

- **Prompts**: die Prompt-Felder des Workflows.
- **Models** (zugeklappt): Modell-Dropdowns.
- **Settings** (zugeklappt): die `UI:`-Regler und der Seed.
- **Advanced** (zugeklappt): zusätzliche Pässe, Normal-Konvention, Anzeige-Optionen, Modellfilter.

Mehrere ControlNets oder andere Modelle (Qwen-Image usw.) brauchen keinen Add-on-Code. Das regelt allein der Workflow.

## Ablauf

1. Comfy Desktop starten. Das Add-on findet den Server selbst (8188, 8000, …). Mit ↻ wird neu gesucht.
2. Workflow wählen. Das Panel zeigt, welche Pässe der Workflow braucht, und baut Modell-Dropdowns und Regler aus dem Workflow auf.
3. **Render & Send**. Blender rendert mit den nötigen Pässen, erzeugt die Steuerbilder, lädt sie hoch und zeigt den Fortschritt. Das Ergebnis heißt im Image Editor `ComfyUI Result`.

**Send Last Render** nimmt den vorhandenen Render. Fehlen Pässe (z. B. Depth), braucht es einen neuen Render.

Jeder Lauf landet als Zeile im Textblock `ComfyBridge_History` (Seed, Workflow, alle Werte). ComfyUI schreibt zusätzlich den kompletten Workflow in die PNG.

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
| `UI:Name [a, b]` | beliebig | nur die Eingänge `a` und `b` erscheinen (z. B. `UI:Sampler [steps]`, um `cfg` zu verstecken) |

Fehlt `BL:size`, bekommen alle Empty-Latent-Nodes die Auflösung. Modell-Dateien (Checkpoints, ControlNets, VAE, Encoder, LoRAs) erscheinen immer als Dropdown, gefüllt mit dem, was in ComfyUI liegt. ControlNets werden am Dateinamen nach SDXL/Flux gefiltert. „Show All Models“ (Advanced) hebt den Filter auf. Seeds werden in allen KSamplern gesetzt.

Werte, die du im Panel änderst, merkt sich die .blend pro Workflow.

## Mitgelieferte Beispiele

- **SDXL Canny Depth**: Juggernaut XL, Canny aus dem Beauty-Render plus Depth aus Blender.
- **Flux GGUF Canny Depth**: Flux.1 dev Q8 (GGUF), InstantX Canny, Shakker Depth. Auf 16 GB VRAM sehr langsam.
- **Qwen-Image 2.1 Depth – research license**: Qwen-Image 2.1 (int8) mit Fun ControlNet Union auf dem Depth-Pass. Hält die Blockout-Geometrie am genauesten ein, etwa 23 s pro Bild auf einer RTX 4080. Lizenz qwen-research: nur zur Evaluierung, nicht kommerziell.

Benötigte Dateien im ComfyUI-Modellordner: `juggernautXL_ragnarokBy.safetensors`, `controlnet-canny-sdxl.safetensors` (xinsir), `controlnet-depth-sdxl.safetensors` (xinsir), `flux1-dev-Q8_0.gguf`, `t5-v1_1-xxl-encoder-Q8_0.gguf`, `clip_l.safetensors`, `ae.safetensors`, `flux-canny-instantx.safetensors`, `flux-depth-shakker.safetensors`. Für den Flux-Workflow braucht es außerdem die Custom Nodes ComfyUI-GGUF.

Flux.1 dev steht unter der FLUX Non-Commercial License.

## Model Packages

Im Bereich **Model Packages** installiert ein Klick die Modelldateien eines Pakets samt passendem Workflow. Der Katalog (`comfy_bridge/catalog.json`) kommt mit dem Add-on und enthält pro Datei Quelle, Zielordner, Größe und SHA256, pro Paket Lizenz, VRAM-Bedarf und die nötigen ComfyUI-Nodes.

- Vor dem Download zeigt ein Dialog Größe, freien Speicher und Lizenz.
- Geladen wird im Hintergrund. Ein abgebrochener Download macht beim nächsten Mal dort weiter (`.part`-Datei).
- Jede Datei wird gegen ihren SHA256 geprüft und erst danach in den Modellordner verschoben.
- Zielordner ist der Modellordner aus den Comfy-Desktop-Einstellungen. In den Add-on-Einstellungen lässt er sich ändern.
- **Delete** löscht nur Dateien, die kein anderes installiertes Paket braucht.
- Es gibt keine freie URL-Eingabe. Custom Nodes installiert das Add-on nicht, es meldet nur, wenn welche fehlen.
- Ein Hugging-Face-Token für gesperrte Modelle gehört in die Add-on-Einstellungen, nie in die .blend. Die aktuellen Pakete brauchen keinen.

## Hinweise

- Pässe werden aus dem Render Result gelesen. Den Compositor deiner Szene fasst das Add-on nicht an. Für den Render schaltet es die nötigen Pässe (und für Line Art Freestyle) kurz ein und danach wieder aus.
- Normal-ControlNets sind sich bei der Rot-Richtung nicht einig. Wirkt das Ergebnis seitenverkehrt beleuchtet, „Flip Normal X“ (Advanced) anhaken.
- Bei Cycles mit Denoising oder „Interleave“ speichert Blender die EXR einteilig. Das Add-on liest beide Varianten.

## Entwicklung

```
blender --command extension build --source-dir comfy_bridge --output-dir dist
blender --command extension install-file -r user_default -e dist/comfy_bridge-0.1.0.zip
blender -b --python tests/blockout_test.py -- SDXL_Canny_Depth.json
```

`tests/blockout_test.py` baut einen Blockout-Raum, rendert ihn und schickt ihn durch ComfyUI (ComfyUI muss laufen). `tests/passes_test.py` prüft nur die Pässe.

Für einen eigenen Entwicklungsstand ohne Release statt `-r user_default` lokal installieren. Die Version aus dem Update-Repo vorher entfernen (`blender --command extension remove comfy_bridge_github.comfy_bridge`).

Releases: Version in `comfy_bridge/blender_manifest.toml` erhöhen, committen, pushen, dann `tools/release.ps1`. Das Skript baut das Paket und den Extension-Index und legt ein GitHub-Release an. In Blender wird einmal `https://github.com/timborabora/comfy_bridge/releases/latest/download/index.json` als Remote Repository eingetragen. Danach bietet Blender neue Versionen selbst an.
