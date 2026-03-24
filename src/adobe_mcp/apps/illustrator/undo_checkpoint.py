"""Save and restore named snapshots of the drawing state on a layer.

Checkpoints capture all pathItem geometry (anchors, handles, stroke, fill, name)
on the target layer and persist them as JSON files in /tmp/ai_checkpoints/.
Restoring clears the layer and recreates all paths from the snapshot.
"""

import json
import os
from datetime import datetime, timezone

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiUndoCheckpointInput


_CHECKPOINT_DIR = "/tmp/ai_checkpoints"


def _checkpoint_path(name: str) -> str:
    """Build the full path for a checkpoint file."""
    return os.path.join(_CHECKPOINT_DIR, f"{name}.json")


def register(mcp):
    """Register the adobe_ai_undo_checkpoint tool."""

    @mcp.tool(
        name="adobe_ai_undo_checkpoint",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_undo_checkpoint(params: AiUndoCheckpointInput) -> str:
        """Save or restore named snapshots of the drawing state on a layer.

        Actions:
        - save: capture all pathItems on the layer (geometry, stroke, fill, names)
        - restore: clear the layer and recreate paths from a saved checkpoint
        - list: show available checkpoints with metadata
        - delete: remove a checkpoint file
        """
        escaped_layer = escape_jsx_string(params.layer_name)

        # ------------------------------------------------------------------
        # SAVE — capture current layer state
        # ------------------------------------------------------------------
        if params.action == "save":
            read_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{
        return JSON.stringify({{"error": "Layer not found: {escaped_layer}"}});
    }}
    var items = [];
    for (var i = 0; i < layer.pathItems.length; i++) {{
        var pi = layer.pathItems[i];
        var pts = [];
        for (var j = 0; j < pi.pathPoints.length; j++) {{
            var pp = pi.pathPoints[j];
            pts.push({{
                anchor: [pp.anchor[0], pp.anchor[1]],
                left: [pp.leftDirection[0], pp.leftDirection[1]],
                right: [pp.rightDirection[0], pp.rightDirection[1]]
            }});
        }}
        var fillColor = null;
        if (pi.filled) {{
            try {{
                fillColor = [pi.fillColor.red, pi.fillColor.green, pi.fillColor.blue];
            }} catch(e) {{}}
        }}
        var strokeColor = null;
        if (pi.stroked) {{
            try {{
                strokeColor = [pi.strokeColor.red, pi.strokeColor.green, pi.strokeColor.blue];
            }} catch(e) {{}}
        }}
        items.push({{
            name: pi.name,
            closed: pi.closed,
            filled: pi.filled,
            stroked: pi.stroked,
            strokeWidth: pi.strokeWidth,
            opacity: pi.opacity,
            fillColor: fillColor,
            strokeColor: strokeColor,
            points: pts
        }});
    }}
    return JSON.stringify({{items: items, layerName: layer.name}});
}})();
"""
            read_result = await _async_run_jsx("illustrator", read_jsx)
            if not read_result["success"]:
                return f"Error reading layer: {read_result['stderr']}"

            try:
                state = json.loads(read_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return f"Error parsing layer data: {read_result['stdout']}"

            if "error" in state:
                return json.dumps(state)

            # Persist checkpoint to disk
            os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
            checkpoint = {
                "name": params.checkpoint_name,
                "layer": params.layer_name,
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path_count": len(state["items"]),
                "items": state["items"],
            }

            cp_path = _checkpoint_path(params.checkpoint_name)
            with open(cp_path, "w", encoding="utf-8") as fh:
                json.dump(checkpoint, fh, indent=2, ensure_ascii=False)

            return json.dumps({
                "action": "save",
                "checkpoint": params.checkpoint_name,
                "layer": params.layer_name,
                "paths_saved": len(state["items"]),
                "file": cp_path,
            }, indent=2)

        # ------------------------------------------------------------------
        # RESTORE — recreate paths from a saved checkpoint
        # ------------------------------------------------------------------
        elif params.action == "restore":
            cp_path = _checkpoint_path(params.checkpoint_name)
            if not os.path.isfile(cp_path):
                return json.dumps({"error": f"Checkpoint not found: {params.checkpoint_name}"})

            with open(cp_path, "r", encoding="utf-8") as fh:
                checkpoint = json.load(fh)

            items = checkpoint.get("items", [])
            if not items:
                return json.dumps({"error": "Checkpoint contains no path data."})

            items_json = json.dumps(items)

            restore_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}

    // Clear existing paths on the layer
    while (layer.pathItems.length > 0) {{
        layer.pathItems[0].remove();
    }}

    // Recreate paths from checkpoint data
    var items = {items_json};
    var created = 0;
    for (var i = 0; i < items.length; i++) {{
        var item = items[i];
        var anchors = [];
        for (var j = 0; j < item.points.length; j++) {{
            anchors.push(item.points[j].anchor);
        }}

        var path = layer.pathItems.add();
        path.setEntirePath(anchors);
        path.closed = item.closed;
        path.name = item.name;

        // Restore bezier handles
        for (var j = 0; j < path.pathPoints.length; j++) {{
            path.pathPoints[j].leftDirection = item.points[j].left;
            path.pathPoints[j].rightDirection = item.points[j].right;
        }}

        // Restore fill
        if (item.filled && item.fillColor) {{
            path.filled = true;
            var fc = new RGBColor();
            fc.red = item.fillColor[0];
            fc.green = item.fillColor[1];
            fc.blue = item.fillColor[2];
            path.fillColor = fc;
        }} else {{
            path.filled = false;
        }}

        // Restore stroke
        if (item.stroked && item.strokeColor) {{
            path.stroked = true;
            var sc = new RGBColor();
            sc.red = item.strokeColor[0];
            sc.green = item.strokeColor[1];
            sc.blue = item.strokeColor[2];
            path.strokeColor = sc;
            path.strokeWidth = item.strokeWidth || 1;
        }} else {{
            path.stroked = false;
        }}

        if (item.opacity !== undefined) {{
            path.opacity = item.opacity;
        }}

        created++;
    }}

    return JSON.stringify({{restored: created, layer: layer.name}});
}})();
"""
            restore_result = await _async_run_jsx("illustrator", restore_jsx)
            if not restore_result["success"]:
                return f"Error restoring checkpoint: {restore_result['stderr']}"

            try:
                result = json.loads(restore_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                result = {"raw": restore_result["stdout"]}

            return json.dumps({
                "action": "restore",
                "checkpoint": params.checkpoint_name,
                "layer": params.layer_name,
                "paths_restored": result.get("restored", len(items)),
                "created_at": checkpoint.get("created", "unknown"),
            }, indent=2)

        # ------------------------------------------------------------------
        # LIST — show available checkpoints
        # ------------------------------------------------------------------
        elif params.action == "list":
            if not os.path.isdir(_CHECKPOINT_DIR):
                return json.dumps({"checkpoints": [], "total": 0})

            checkpoints = []
            for fname in sorted(os.listdir(_CHECKPOINT_DIR)):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(_CHECKPOINT_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        cp = json.load(fh)
                    checkpoints.append({
                        "name": cp.get("name", fname.replace(".json", "")),
                        "layer": cp.get("layer", "unknown"),
                        "path_count": cp.get("path_count", 0),
                        "created": cp.get("created", "unknown"),
                        "file_size_kb": round(os.path.getsize(fpath) / 1024, 1),
                    })
                except (json.JSONDecodeError, OSError):
                    checkpoints.append({
                        "name": fname.replace(".json", ""),
                        "error": "Could not read checkpoint file",
                    })

            return json.dumps({
                "total": len(checkpoints),
                "checkpoints": checkpoints,
            }, indent=2)

        # ------------------------------------------------------------------
        # DELETE — remove a checkpoint file
        # ------------------------------------------------------------------
        elif params.action == "delete":
            cp_path = _checkpoint_path(params.checkpoint_name)
            if not os.path.isfile(cp_path):
                return json.dumps({"error": f"Checkpoint not found: {params.checkpoint_name}"})

            os.remove(cp_path)
            return json.dumps({
                "action": "delete",
                "checkpoint": params.checkpoint_name,
                "deleted": True,
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {params.action}. Valid actions: save, restore, list, delete"
            })
