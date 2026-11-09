"""Runtime state that does not belong in the .blend (connection, object_info, running job)."""

import uuid

server = None          # e.g. "http://127.0.0.1:8188"
stats = None           # /system_stats
object_info = {}       # /object_info
connect_error = ""
connecting = False

client_id = uuid.uuid4().hex
job = None             # pipeline.Job while one is running
download = None        # installer.Download while one is running
download_message = ""  # last download result for the panel

# Blender requires strings of dynamic enum items to stay referenced.
workflow_items = []
edit_workflow_items = []
package_items = []
enum_item_cache = {}
