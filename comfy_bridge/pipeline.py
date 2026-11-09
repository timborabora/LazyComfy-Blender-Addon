"""Ein Durchlauf: Bilder hochladen, Workflow abschicken, Fortschritt verfolgen, Ergebnis holen.

Läuft in einem eigenen Thread und fasst bpy nicht an. Der Haupt-Thread liest
die Felder (status, progress, done, ...) per Timer.
"""

import os
import threading
import time

from . import comfy_client
from .comfy_client import ComfyError


def _node_label(node):
    title = (node.get("_meta") or {}).get("title") or node.get("class_type", "…")
    return title[3:].strip() if title[:3].lower() in ("ui:", "bl:") else title


class Job:
    def __init__(self, base, workflow, client_id, uploads, out_dir, result_nodes):
        self.base = base
        self.workflow = workflow
        self.client_id = client_id
        self.uploads = uploads          # [(pfad, dateiname, [node_ids])]
        self.out_dir = out_dir
        self.result_nodes = result_nodes
        self.status = "Starte …"
        self.progress = 0.0
        self.done = False
        self.cancelled = False
        self.error = ""
        self.prompt_id = ""
        self.results = []               # [(titel, lokaler pfad)]
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name="ComfyBridgeJob", daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancelled = True
        comfy_client.interrupt(self.base)

    def run(self):
        ws = None
        try:
            for path, name, node_ids in self.uploads:
                self.status = f"Lade {name} hoch …"
                value = comfy_client.upload_image(self.base, path, name)
                for nid in node_ids:
                    self.workflow[nid]["inputs"]["image"] = value
            try:
                ws = comfy_client.WebSocket(self.base, self.client_id)
            except (ComfyError, OSError):
                ws = None  # ohne Websocket gibt es nur keinen Schritt-Fortschritt
            self.status = "In der Warteschlange …"
            self.prompt_id = comfy_client.queue_prompt(self.base, self.workflow, self.client_id)
            self._wait(ws)
            if self.cancelled:
                self.status = "Abgebrochen"
                return
            self.status = "Hole Ergebnis …"
            self._fetch_results()
            self.status = "Fertig"
            self.progress = 1.0
        except Exception as e:  # alles landet lesbar im Panel
            self.error = str(e)
            self.status = "Fehler"
        finally:
            if ws:
                ws.close()
            self.done = True

    def _wait(self, ws):
        last_poll = 0.0
        while not self.cancelled:
            msg = None
            if ws:
                try:
                    msg = ws.recv_json(wait=1.0)
                except (OSError, ConnectionError, ValueError):
                    ws = None
            else:
                time.sleep(1.0)
            if msg:
                kind, data = msg.get("type"), msg.get("data") or {}
                if data.get("prompt_id") not in (None, self.prompt_id):
                    continue
                if kind == "progress" and data.get("max"):
                    self.progress = data["value"] / data["max"]
                    node = self.workflow.get(str(data.get("node")), {})
                    self.status = f"{_node_label(node)}: Schritt {data['value']}/{data['max']}"
                elif kind == "executing" and data.get("node") is not None:
                    self.status = _node_label(self.workflow.get(str(data["node"]), {}))
                elif kind == "execution_error":
                    raise ComfyError(
                        f"ComfyUI-Fehler in {data.get('node_type', '?')}: {data.get('exception_message', '').strip()}"
                    )
                elif kind == "execution_interrupted":
                    self.cancelled = True
                    return
                elif kind == "execution_success" or (kind == "executing" and data.get("node") is None):
                    return
            # Sicherheitsnetz, falls eine Websocket-Nachricht verloren geht
            if time.time() - last_poll > (5.0 if ws else 1.0):
                last_poll = time.time()
                entry = comfy_client.history(self.base, self.prompt_id)
                if entry and entry.get("status", {}).get("completed") is not None:
                    st = entry["status"]
                    if st.get("status_str") == "error":
                        msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                        raise ComfyError("ComfyUI-Fehler: " + ("; ".join(msgs) or "unbekannt"))
                    return

    def _fetch_results(self):
        entry = comfy_client.history(self.base, self.prompt_id) or {}
        outputs = entry.get("outputs", {})
        order = sorted(outputs, key=lambda k: (k not in self.result_nodes, int(k) if k.isdigit() else 10**9))
        images = []
        for nid in order:
            for img in outputs[nid].get("images", []):
                images.append((nid, img))
        final = [x for x in images if x[1].get("type") == "output"] or images
        if not final:
            raise ComfyError("Der Workflow hat kein Bild ausgegeben (SaveImage-Node fehlt?).")
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        for nid, img in final:
            node = self.workflow.get(nid, {})
            title = (node.get("_meta") or {}).get("title") or node.get("class_type", nid)
            dest = os.path.join(self.out_dir, f"{stamp}_{img['filename']}")
            comfy_client.download_image(self.base, img, dest)
            self.results.append((title, dest))
