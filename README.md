# Comfy Bridge

Blender-Add-on (ab 5.0): Blender rendert, ComfyUI rechnet. Render und Render-Pässe gehen mit einem Klick an das lokale ComfyUI, das Ergebnis landet im Image Editor.

Das Panel sitzt unter **Render Properties → Comfy Bridge** und ist auf Englisch:

- oben Verbindung und Workflow, darunter Prompt und die Regler des Workflows
- **Render & Generate**, **Send Last Render**
- das Feld „Change“ mit **Redo Selection**
- einklappbar: **Object Prompts**, **Models**, **Settings**, **Advanced**, **Model Packages**

In Blender passiert nur, was Blender weiß: Objekte, Masken, Kamera, Pässe. Die Bildarbeit (Modelle, ControlNets, Sampler, LoRAs, Upscaler) bleibt im ComfyUI-Workflow.

## Ablauf

1. Comfy Desktop starten. Das Add-on findet den Server selbst (8188, 8000, …). Mit ↻ wird neu gesucht.
2. Workflow wählen. Das Panel zeigt Prompt, die Regler des Workflows und was fehlt (Modell-Paket mit **Install**-Knopf, fehlende Nodes).
3. **Render & Generate**. Blender rendert mit den nötigen Pässen, lädt sie hoch und zeigt den Fortschritt. Das Ergebnis heißt im Image Editor `ComfyUI Result`.

**Send Last Render** nimmt den vorhandenen Render. Fehlen Pässe (z. B. Depth), braucht es einen neuen Render.

Jeder Lauf landet als Zeile im Textblock `ComfyBridge_History` (Seed, Workflow, alle Werte). ComfyUI schreibt zusätzlich den kompletten Workflow in die PNG.

## Workflows in ComfyUI (Blender-Nodes)

ComfyUI ist die Werkstatt: Workflows dort anpassen und ganz normal mit **Strg+S** speichern. Ein API-Export ist nicht nötig. Das Dropdown in Blender zeigt alle in ComfyUI gespeicherten Workflows, die mindestens einen Blender-Node enthalten. Das Add-on wandelt sie selbst ins API-Format um.

Die Nodes kommen aus dem Paket `comfy_bridge_nodes`, das mit dem Add-on ausgeliefert wird (Advanced › **Install Blender Nodes**, danach ComfyUI neu starten). Kategorie „Comfy Bridge“:

| Node | Ausgang | Wofür |
|---|---|---|
| Blender Pass | IMAGE | beauty / depth / lineart / normal |
| Blender Prompt | STRING ×2 | Prompt und Negativ-Prompt aus dem Panel |
| Blender Object Prompts | CONDITIONING | nimmt CLIP und Basis-Konditionierung, hängt pro Objekt den maskierten Objekt-Prompt an |
| Blender Selection | MASK, IMAGE, BOOLEAN, STRING | Maske der Auswahl, letztes Ergebnis, „ist Redo Selection?“, Änderungs-Prompt |
| Blender Render Size | INT ×2 | Render-Auflösung |
| Blender Setting (Float / Int / Bool) | Wert | erscheint als Regler im Panel (Label, Wert, Min, Max) |

Alle Nodes haben eingebaute Platzhalter (der Blockout-Raum). So läuft ein Workflow auch allein in ComfyUI.

**Beispiele:** Beim ersten Verbinden und über Advanced › **Install Examples** kopiert das Add-on die Vorlagen nach *Workflows › Comfy Bridge*: „SDXL · Canny + Depth“, „SDXL · Depth + Objects + Inpaint“ und „Qwen 2.1 · Depth (evaluation only)“. Alle sind in Gruppen aufgebaut: Blender Inputs → Model → Prompts → Control → Sampler → Inpaint → Output. Hast du ein Beispiel verändert, bleibt deine Version, und eine neuere Vorlage landet als „<Name> (new).json“ daneben. Am besten kopierst du Beispiele mit **Save As**, bevor du sie änderst.

Workflows mit Subgraphen bitte vor dem Speichern auflösen (Rechtsklick › Unpack Subgraph). Das meldet das Panel auch selbst. Reroutes, Primitive-Nodes sowie gemutete und überbrückte Nodes werden unterstützt.

## Workflows als API-Datei (alte Titel-Konvention)

Funktioniert weiterhin als Fallback: In ComfyUI **Workflow → Export (API)** und die JSON in den Workflow-Ordner aus den Add-on-Einstellungen legen. Gesteuert wird über Node-Titel (Rechtsklick auf den Node → Title):

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
| `BL:region_1`, `BL:region_1_mask`, `BL:region_1_prompt` | Conditioning Set Mask, Load Image Mask, Text Encode | ein Slot für einen Objekt-Prompt (Nummer frei, beliebig viele Slots) |
| `BL:result_prev` | Load Image | Edit-Workflows: das letzte Ergebnis |
| `BL:mask_selection` | Load Image Mask | Edit-Workflows: Maske der ausgewählten Objekte, vergrößert und weich |
| `BL:edit_prompt` | Text Encode | Edit-Workflows: Text aus dem Feld „Change“ |

Fehlt `BL:size`, bekommen alle Empty-Latent-Nodes die Auflösung. Modell-Dateien (Checkpoints, ControlNets, VAE, Encoder, LoRAs) erscheinen immer als Dropdown, gefüllt mit dem, was in ComfyUI liegt. ControlNets werden am Dateinamen nach SDXL/Flux gefiltert. „Show All Models“ (Advanced) hebt den Filter auf. Seeds werden in allen KSamplern gesetzt.

Werte, die du im Panel änderst, merkt sich die .blend pro Workflow.

## Mitgelieferte Beispiele

- **SDXL Canny Depth**: Juggernaut XL, Canny aus dem Beauty-Render plus Depth aus Blender.
- **Flux GGUF Canny Depth**: Flux.1 dev Q8 (GGUF), InstantX Canny, Shakker Depth. Auf 16 GB VRAM sehr langsam.
- **Qwen-Image 2.1 Depth – research license**: Qwen-Image 2.1 (int8) mit Fun ControlNet Union auf dem Depth-Pass. Hält die Blockout-Geometrie am genauesten ein, etwa 23 s pro Bild auf einer RTX 4080. Lizenz qwen-research: nur zur Evaluierung, nicht kommerziell.

Benötigte Dateien im ComfyUI-Modellordner: `juggernautXL_ragnarokBy.safetensors`, `controlnet-canny-sdxl.safetensors` (xinsir), `controlnet-depth-sdxl.safetensors` (xinsir), `flux1-dev-Q8_0.gguf`, `t5-v1_1-xxl-encoder-Q8_0.gguf`, `clip_l.safetensors`, `ae.safetensors`, `flux-canny-instantx.safetensors`, `flux-depth-shakker.safetensors`. Für den Flux-Workflow braucht es außerdem die Custom Nodes ComfyUI-GGUF.

Flux.1 dev steht unter der FLUX Non-Commercial License.

## Objekt-Prompts

In den Objekt-Properties hat jedes Objekt unter **Comfy Bridge** ein Feld **Prompt**, z. B. „glossy red lacquer coffee table“ für den Tisch. Workflows mit Objekt-Slots (Beispiel: **SDXL Object Prompts Depth**, 4 Slots) bekommen für jedes sichtbare Objekt mit Prompt eine Cryptomatte-Maske und den Prompt. Der Hauptprompt gilt weiter für den Rest. Der Bereich **Object Prompts** zeigt, wie viele Slots belegt sind, und regelt mit **Object Prompt Strength**, wie stark der Objekt-Prompt in seiner Maske gegen den Hauptprompt gewinnt.

Objekte, die nicht im Bild sind, werden übersprungen. Sind es mehr Objekte als Slots, gehen die ersten (alphabetisch) durch, der Rest wird mit Warnung ausgelassen. Getestet sind 4 Slots im Blockout, mehr Slots gehen mit mehr Nodes im Workflow.

## Edit Selection

Ändert nur die ausgewählten Objekte im letzten Ergebnis:

1. Render & Send.
2. Objekte im Viewport auswählen, im Bereich **Edit Selection** beschreiben, was sie werden sollen („green velvet sofa“).
3. **Redo Selection**. Blender rendert die Maske der Auswahl (um **Grow** Pixel vergrößert, um **Feather** Pixel weich), der Edit-Workflow malt mit demselben Seed nur dort neu.

Der Beispiel-Workflow **SDXL Edit Selection** nutzt Juggernaut mit Differential Diffusion und Depth, ein eigenes Inpaint-Modell braucht er nicht. Am Ende setzt `ImageCompositeMasked` das neue Bild nur innerhalb der Maske ein: Außerhalb bleibt jedes Pixel gleich (im Test 0 von 700.000 Pixeln geändert). Das Ergebnis wird wieder zum „letzten Ergebnis“, Edits lassen sich also stapeln. Die PNG enthält den Workflow (`prompt`-Metadaten) und lässt sich zur Feinarbeit in ComfyUI ziehen.

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

`tests/blockout_test.py` baut einen Blockout-Raum, rendert ihn und schickt ihn durch ComfyUI (ComfyUI muss laufen). `tests/passes_test.py` prüft nur die Pässe. `tests/nodes_test.py` prüft die Blender-Nodes-Vorlagen (Vergleich mit dem alten Workflow, Objekt-Prompts, Redo Selection), `tests/convert_test.py` lässt die Vorlagen nur mit Platzhaltern laufen. Die Vorlagen entstehen mit `tools/make_templates.py`, das Node-Paket liegt in `comfy_bridge/comfyui_nodes/comfy_bridge_nodes`.

Für einen eigenen Entwicklungsstand ohne Release statt `-r user_default` lokal installieren. Die Version aus dem Update-Repo vorher entfernen (`blender --command extension remove comfy_bridge_github.comfy_bridge`).

Releases: Version in `comfy_bridge/blender_manifest.toml` erhöhen, committen, pushen, dann `tools/release.ps1`. Das Skript baut das Paket und den Extension-Index und legt ein GitHub-Release an. In Blender wird einmal `https://github.com/timborabora/comfy_bridge/releases/latest/download/index.json` als Remote Repository eingetragen. Danach bietet Blender neue Versionen selbst an.
