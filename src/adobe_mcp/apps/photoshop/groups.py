"""Manage Photoshop layer groups (layer sets) — list, create, add layers, ungroup."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.photoshop.models import PsGroupInput


def register(mcp):
    """Register the adobe_ps_groups tool."""

    @mcp.tool(
        name="adobe_ps_groups",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_groups(params: PsGroupInput) -> str:
        """Manage Photoshop layer groups (layer sets) — list, create, add layers, ungroup."""
        if params.action == "list":
            jsx = """
var doc = app.activeDocument;
function listGroups(container, depth) {
    var groups = [];
    for (var i = 0; i < container.layerSets.length; i++) {
        var s = container.layerSets[i];
        var layers = [];
        for (var j = 0; j < s.artLayers.length; j++) { layers.push(s.artLayers[j].name); }
        groups.push({ name: s.name, visible: s.visible, depth: depth, layers: layers, subgroups: listGroups(s, depth + 1) });
    }
    return groups;
}
JSON.stringify({ count: doc.layerSets.length, groups: listGroups(doc, 0) }, null, 2);
"""
        elif params.action == "create":
            escaped_name = escape_jsx_string(params.new_name or params.group_name or "New Group")
            jsx = f"""
var grp = app.activeDocument.layerSets.add();
grp.name = "{escaped_name}";
JSON.stringify({{ name: grp.name }});
"""
        elif params.action == "add_layer":
            escaped_layer = escape_jsx_string(params.layer_name or "")
            escaped_group = escape_jsx_string(params.group_name or "")
            jsx = f"""
var doc = app.activeDocument;
var l = doc.artLayers.getByName("{escaped_layer}");
var grp = doc.layerSets.getByName("{escaped_group}");
l.move(grp, ElementPlacement.INSIDE);
"Added layer to group";
"""
        elif params.action == "ungroup":
            escaped_group = escape_jsx_string(params.group_name or "")
            jsx = f"""
var doc = app.activeDocument;
var grp = doc.layerSets.getByName("{escaped_group}");
while (grp.artLayers.length > 0) {{ grp.artLayers[0].move(doc, ElementPlacement.PLACEATEND); }}
while (grp.layerSets.length > 0) {{ grp.layerSets[0].move(doc, ElementPlacement.PLACEATEND); }}
grp.remove();
"Ungrouped";
"""
        else:
            jsx = f'"Unknown group action: {params.action}"'

        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
