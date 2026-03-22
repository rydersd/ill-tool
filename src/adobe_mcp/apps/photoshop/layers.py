"""Manage Photoshop layers — create, delete, rename, duplicate, merge, flatten, hide, show, reorder, set opacity/blendmode."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.photoshop.models import PsLayerInput


def register(mcp):
    """Register the adobe_ps_layers tool."""

    @mcp.tool(
        name="adobe_ps_layers",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_layers(params: PsLayerInput) -> str:
        """Manage Photoshop layers — create, delete, rename, duplicate, merge, flatten, hide, show, reorder, set opacity/blendmode."""
        actions = {
            "create": f'var l = app.activeDocument.artLayers.add(); l.name = "{params.new_name or "New Layer"}"; l.name;',
            "delete": f'app.activeDocument.activeLayer = app.activeDocument.artLayers.getByName("{params.layer_name}"); app.activeDocument.activeLayer.remove(); "Deleted";',
            "rename": f'app.activeDocument.artLayers.getByName("{params.layer_name}").name = "{params.new_name}"; "Renamed";',
            "duplicate": f'app.activeDocument.artLayers.getByName("{params.layer_name}").duplicate(); "Duplicated";',
            "merge": 'app.activeDocument.mergeVisibleLayers(); "Merged visible";',
            "flatten": 'app.activeDocument.flatten(); "Flattened";',
            "hide": f'app.activeDocument.artLayers.getByName("{params.layer_name}").visible = false; "Hidden";',
            "show": f'app.activeDocument.artLayers.getByName("{params.layer_name}").visible = true; "Shown";',
            "set_opacity": f'app.activeDocument.artLayers.getByName("{params.layer_name}").opacity = {params.opacity or 100}; "Opacity set";',
            "set_blendmode": f'app.activeDocument.artLayers.getByName("{params.layer_name}").blendMode = BlendMode.{params.blend_mode.value if params.blend_mode else "NORMAL"}; "Blend mode set";',
        }

        if params.action == "reorder" and params.position is not None:
            jsx = f'var l = app.activeDocument.artLayers.getByName("{params.layer_name}"); l.move(app.activeDocument.artLayers[{params.position}], ElementPlacement.PLACEBEFORE); "Reordered";'
        elif params.action == "list":
            jsx = """
var layers = [];
for (var i = 0; i < app.activeDocument.artLayers.length; i++) {
    var l = app.activeDocument.artLayers[i];
    layers.push({ name: l.name, visible: l.visible, opacity: l.opacity,
        kind: String(l.kind), blendMode: String(l.blendMode), bounds: [l.bounds[0].value, l.bounds[1].value, l.bounds[2].value, l.bounds[3].value] });
}
JSON.stringify({ count: layers.length, layers: layers }, null, 2);
"""
        elif params.action == "move":
            escaped_name = escape_jsx_string(params.layer_name or "")
            dx = params.dx or 0
            dy = params.dy or 0
            jsx = f"""
var l = app.activeDocument.artLayers.getByName("{escaped_name}");
l.translate(UnitValue({dx}, 'px'), UnitValue({dy}, 'px'));
"Translated layer by ({dx}, {dy})";
"""
        elif params.action == "resize":
            escaped_name = escape_jsx_string(params.layer_name or "")
            sx = params.scale_x or 100
            sy = params.scale_y or 100
            jsx = f"""
var l = app.activeDocument.artLayers.getByName("{escaped_name}");
l.resize({sx}, {sy}, AnchorPosition.MIDDLECENTER);
"Resized layer to {sx}% x {sy}%";
"""
        elif params.action == "get_info":
            escaped_name = escape_jsx_string(params.layer_name or "")
            jsx = f"""
var l = app.activeDocument.artLayers.getByName("{escaped_name}");
var info = {{
    name: l.name,
    kind: String(l.kind),
    visible: l.visible,
    opacity: l.opacity,
    blendMode: String(l.blendMode),
    bounds: [l.bounds[0].value, l.bounds[1].value, l.bounds[2].value, l.bounds[3].value],
    locked: l.allLocked,
    isBackground: l.isBackgroundLayer
}};
try {{ if (l.kind === LayerKind.TEXT) {{ info.textContents = l.textItem.contents; info.textFont = l.textItem.font; info.textSize = l.textItem.size.value; }} }} catch(e) {{}}
JSON.stringify(info, null, 2);
"""
        else:
            jsx = actions.get(params.action, f'"Unknown action: {params.action}"')

        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
