"""Laufzeit-Zustand, der nicht in die .blend gehört (Verbindung, object_info, laufender Job)."""

import uuid

server = None          # z.B. "http://127.0.0.1:8188"
stats = None           # /system_stats
object_info = {}       # /object_info
connect_error = ""
connecting = False

client_id = uuid.uuid4().hex
job = None             # pipeline.Job, solange einer läuft

# Blender verlangt, dass Strings dynamischer Enum-Items referenziert bleiben.
workflow_items = []
enum_item_cache = {}
