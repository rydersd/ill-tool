"""Manage Illustrator layers — list, create, delete, rename, visibility, locking, reorder."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiLayerInput


def register(mcp):
    """Register the adobe_ai_layers tool."""

    @mcp.tool(
        name="adobe_ai_layers",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_layers(params: AiLayerInput) -> str:
        """Manage Illustrator layers — list, create, delete, rename, visibility, locking, reorder."""

        if params.action == "list":
            jsx = """
var doc = app.activeDocument;
var layers = [];
for (var i = 0; i < doc.layers.length; i++) {
    var l = doc.layers[i];
    layers.push({ index: i, name: l.name, visible: l.visible, locked: l.locked, sublayers: l.layers.length, items: l.pageItems.length });
}
JSON.stringify({ count: layers.length, layers: layers }, null, 2);
"""
        elif params.action == "create":
            layer_name = escape_jsx_string(params.new_name or "New Layer")
            jsx = f"""
var doc = app.activeDocument;
var l = doc.layers.add();
l.name = "{layer_name}";
JSON.stringify({{ name: l.name }});
"""
        elif params.action == "delete":
            if not params.name:
                return "Error: delete requires 'name'"
            escaped = escape_jsx_string(params.name)
            jsx = f"""
var doc = app.activeDocument;
doc.layers.getByName("{escaped}").remove();
"Deleted layer";
"""
        elif params.action == "rename":
            if not params.name:
                return "Error: rename requires 'name'"
            if not params.new_name:
                return "Error: rename requires 'new_name'"
            escaped = escape_jsx_string(params.name)
            escaped_new = escape_jsx_string(params.new_name)
            jsx = f"""
var doc = app.activeDocument;
var l = doc.layers.getByName("{escaped}");
l.name = "{escaped_new}";
"Renamed to " + l.name;
"""
        elif params.action == "show":
            if not params.name:
                return "Error: show requires 'name'"
            escaped = escape_jsx_string(params.name)
            jsx = f"""
var doc = app.activeDocument;
doc.layers.getByName("{escaped}").visible = true;
"Layer shown";
"""
        elif params.action == "hide":
            if not params.name:
                return "Error: hide requires 'name'"
            escaped = escape_jsx_string(params.name)
            jsx = f"""
var doc = app.activeDocument;
doc.layers.getByName("{escaped}").visible = false;
"Layer hidden";
"""
        elif params.action == "lock":
            if not params.name:
                return "Error: lock requires 'name'"
            escaped = escape_jsx_string(params.name)
            jsx = f"""
var doc = app.activeDocument;
doc.layers.getByName("{escaped}").locked = true;
"Layer locked";
"""
        elif params.action == "unlock":
            if not params.name:
                return "Error: unlock requires 'name'"
            escaped = escape_jsx_string(params.name)
            jsx = f"""
var doc = app.activeDocument;
doc.layers.getByName("{escaped}").locked = false;
"Layer unlocked";
"""
        elif params.action == "reorder":
            if not params.name:
                return "Error: reorder requires 'name'"
            if not params.target:
                return "Error: reorder requires 'target' layer name"
            escaped = escape_jsx_string(params.name)
            escaped_target = escape_jsx_string(params.target)
            jsx = f"""
var doc = app.activeDocument;
var l = doc.layers.getByName("{escaped}");
var target = doc.layers.getByName("{escaped_target}");
l.move(target, ElementPlacement.PLACEBEFORE);
"Layer reordered";
"""
        else:
            return f"Unknown layer action: {params.action}"

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
