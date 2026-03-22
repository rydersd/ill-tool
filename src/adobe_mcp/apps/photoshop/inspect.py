"""Inspect Photoshop document — full layer tree with groups, layer details, text contents, selection bounds."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.photoshop.models import PsInspectInput


def register(mcp):
    """Register the adobe_ps_inspect tool."""

    @mcp.tool(
        name="adobe_ps_inspect",
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    async def adobe_ps_inspect(params: PsInspectInput) -> str:
        """Inspect Photoshop document — full layer tree with groups, layer details, text contents, selection bounds."""
        if params.action == "list_all":
            jsx = """
var doc = app.activeDocument;
function describeLayers(container, depth) {
    var result = [];
    try {
        for (var i = 0; i < container.artLayers.length; i++) {
            var l = container.artLayers[i];
            result.push({
                name: l.name, kind: String(l.kind), visible: l.visible,
                opacity: l.opacity, blendMode: String(l.blendMode),
                bounds: [l.bounds[0].value, l.bounds[1].value, l.bounds[2].value, l.bounds[3].value],
                depth: depth, isGroup: false
            });
        }
    } catch(e) {}
    try {
        for (var j = 0; j < container.layerSets.length; j++) {
            var s = container.layerSets[j];
            result.push({
                name: s.name, visible: s.visible, opacity: s.opacity,
                blendMode: String(s.blendMode),
                bounds: [s.bounds[0].value, s.bounds[1].value, s.bounds[2].value, s.bounds[3].value],
                depth: depth, isGroup: true,
                children: describeLayers(s, depth + 1)
            });
        }
    } catch(e) {}
    return result;
}
JSON.stringify({ name: doc.name, width: doc.width.value, height: doc.height.value, resolution: doc.resolution, layers: describeLayers(doc, 0) }, null, 2);
"""
        elif params.action == "get_layer":
            escaped_name = escape_jsx_string(params.layer_name or "")
            jsx = f"""
var l = app.activeDocument.artLayers.getByName("{escaped_name}");
var info = {{
    name: l.name, kind: String(l.kind), visible: l.visible, opacity: l.opacity,
    blendMode: String(l.blendMode), allLocked: l.allLocked,
    bounds: [l.bounds[0].value, l.bounds[1].value, l.bounds[2].value, l.bounds[3].value],
    isBackground: l.isBackgroundLayer
}};
try {{ if (l.kind === LayerKind.TEXT) {{ var t = l.textItem; info.text = {{ contents: t.contents, font: t.font, size: t.size.value, color: {{ r: t.color.rgb.red, g: t.color.rgb.green, b: t.color.rgb.blue }}, justification: String(t.justification) }}; }} }} catch(e) {{}}
try {{ if (l.kind === LayerKind.SMARTOBJECT) {{ info.isSmartObject = true; }} }} catch(e) {{}}
JSON.stringify(info, null, 2);
"""
        elif params.action == "get_selection_bounds":
            jsx = """
try {
    var b = app.activeDocument.selection.bounds;
    JSON.stringify({ x: b[0].value, y: b[1].value, width: b[2].value - b[0].value, height: b[3].value - b[1].value });
} catch(e) {
    JSON.stringify({ error: "No selection active" });
}
"""
        elif params.action == "get_text":
            escaped_name = escape_jsx_string(params.layer_name or "")
            jsx = f"""
var l = app.activeDocument.artLayers.getByName("{escaped_name}");
if (l.kind === LayerKind.TEXT) {{
    var t = l.textItem;
    JSON.stringify({{ name: l.name, contents: t.contents, font: t.font, size: t.size.value, color: {{ r: t.color.rgb.red, g: t.color.rgb.green, b: t.color.rgb.blue }}, justification: String(t.justification) }}, null, 2);
}} else {{
    JSON.stringify({{ error: "Layer is not a text layer", kind: String(l.kind) }});
}}
"""
        else:
            jsx = f'"Unknown inspect action: {params.action}"'

        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
