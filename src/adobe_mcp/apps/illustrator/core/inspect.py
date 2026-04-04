"""Inspect Illustrator document — list all items, layers, artboards, or get details on a specific item."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiInspectInput


def register(mcp):
    """Register the adobe_ai_inspect tool."""

    @mcp.tool(
        name="adobe_ai_inspect",
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    async def adobe_ai_inspect(params: AiInspectInput) -> str:
        """Inspect Illustrator document — list all items, layers, artboards, or get details on a specific item."""

        if params.action == "list_all":
            jsx = f"""
var doc = app.activeDocument;
var items = [];
var start = {params.offset};
var end = Math.min(doc.pageItems.length, start + {params.limit});
for (var i = start; i < end; i++) {{
    var item = doc.pageItems[i];
    var info = {{
        index: i,
        name: item.name,
        type: item.typename,
        x: item.position[0],
        y: item.position[1],
        width: item.width,
        height: item.height,
        layer: item.layer.name,
        opacity: item.opacity
    }};
    try {{
        if (item.fillColor) {{
            var fc = item.fillColor;
            if (fc.typename === "RGBColor") info.fillColor = {{r: fc.red, g: fc.green, b: fc.blue}};
            else if (fc.typename === "CMYKColor") info.fillColor = {{c: fc.cyan, m: fc.magenta, y: fc.yellow, k: fc.black}};
        }}
    }} catch(e) {{}}
    try {{
        if (item.strokeColor) {{
            var sc = item.strokeColor;
            if (sc.typename === "RGBColor") info.strokeColor = {{r: sc.red, g: sc.green, b: sc.blue}};
            else if (sc.typename === "CMYKColor") info.strokeColor = {{c: sc.cyan, m: sc.magenta, y: sc.yellow, k: sc.black}};
        }}
    }} catch(e) {{}}
    items.push(info);
}}
JSON.stringify({{ total: doc.pageItems.length, offset: start, count: items.length, items: items }}, null, 2);
"""
        elif params.action == "list_layers":
            jsx = """
var doc = app.activeDocument;
var layers = [];
for (var i = 0; i < doc.layers.length; i++) {
    var l = doc.layers[i];
    layers.push({
        index: i,
        name: l.name,
        visible: l.visible,
        locked: l.locked,
        color: String(l.color),
        sublayers: l.layers.length,
        items: l.pageItems.length
    });
}
JSON.stringify({ count: layers.length, layers: layers }, null, 2);
"""
        elif params.action == "get_item":
            if params.name:
                escaped = escape_jsx_string(params.name)
                item_lookup = f'doc.pageItems.getByName("{escaped}")'
            elif params.index is not None:
                item_lookup = f"doc.pageItems[{params.index}]"
            else:
                return "Error: get_item requires 'name' or 'index'"
            jsx = f"""
var doc = app.activeDocument;
var item = {item_lookup};
var info = {{
    name: item.name,
    type: item.typename,
    x: item.position[0],
    y: item.position[1],
    width: item.width,
    height: item.height,
    layer: item.layer.name,
    opacity: item.opacity,
    locked: item.locked,
    hidden: item.hidden
}};
try {{ if (item.fillColor) {{ var fc = item.fillColor; if (fc.typename === "RGBColor") info.fillColor = {{r: fc.red, g: fc.green, b: fc.blue}}; }} }} catch(e) {{}}
try {{ if (item.strokeColor) {{ var sc = item.strokeColor; if (sc.typename === "RGBColor") info.strokeColor = {{r: sc.red, g: sc.green, b: sc.blue}}; }} }} catch(e) {{}}
try {{ info.strokeWidth = item.strokeWidth; }} catch(e) {{}}
try {{
    if (item.typename === "PathItem" && item.pathPoints) {{
        var pts = [];
        for (var j = 0; j < item.pathPoints.length; j++) {{
            pts.push({{ anchor: item.pathPoints[j].anchor, leftDirection: item.pathPoints[j].leftDirection, rightDirection: item.pathPoints[j].rightDirection }});
        }}
        info.pathPoints = pts;
        info.closed = item.closed;
    }}
}} catch(e) {{}}
try {{
    if (item.typename === "TextFrame") {{
        info.contents = item.contents;
        info.characterCount = item.characters.length;
    }}
}} catch(e) {{}}
JSON.stringify(info, null, 2);
"""
        elif params.action == "get_selection":
            jsx = """
var doc = app.activeDocument;
var sel = doc.selection;
if (!sel || sel.length === 0) {
    JSON.stringify({ count: 0, items: [] });
} else {
    var items = [];
    for (var i = 0; i < sel.length; i++) {
        items.push({ name: sel[i].name, type: sel[i].typename, x: sel[i].position[0], y: sel[i].position[1], width: sel[i].width, height: sel[i].height });
    }
    JSON.stringify({ count: items.length, items: items }, null, 2);
}
"""
        elif params.action == "get_artboards":
            jsx = """
var doc = app.activeDocument;
var boards = [];
for (var i = 0; i < doc.artboards.length; i++) {
    var ab = doc.artboards[i];
    var rect = ab.artboardRect;
    boards.push({ index: i, name: ab.name, x: rect[0], y: rect[1], width: rect[2] - rect[0], height: rect[1] - rect[3] });
}
JSON.stringify({ count: boards.length, artboards: boards }, null, 2);
"""
        else:
            return f"Unknown inspect action: {params.action}"

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
