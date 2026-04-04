"""Modify existing Illustrator objects — move, resize, rotate, recolor, rename, delete, duplicate, group, etc."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiModifyInput


def register(mcp):
    """Register the adobe_ai_modify tool."""

    @mcp.tool(
        name="adobe_ai_modify",
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_modify(params: AiModifyInput) -> str:
        """Modify existing Illustrator objects — move, resize, rotate, recolor, rename, delete, duplicate, group, etc."""

        # Build the item-lookup JSX fragment (used by most actions)
        if params.name:
            escaped = escape_jsx_string(params.name)
            item_lookup = f'var item = doc.pageItems.getByName("{escaped}");'
        elif params.index is not None:
            item_lookup = f"var item = doc.pageItems[{params.index}];"
        elif params.action not in ("group",):
            # group doesn't require a single target item
            return "Error: must specify 'name' or 'index' to target an item"
        else:
            item_lookup = ""

        if params.action == "select":
            jsx = f"""
var doc = app.activeDocument;
doc.selection = null;
{item_lookup}
item.selected = true;
JSON.stringify({{ selected: item.name, type: item.typename }});
"""
        elif params.action == "move":
            if params.absolute:
                x_val = params.x if params.x is not None else 0
                y_val = params.y if params.y is not None else 0
                jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.position = [{x_val}, {y_val}];
"Moved to (" + {x_val} + ", " + {y_val} + ")";
"""
            else:
                dx = params.x if params.x is not None else 0
                dy = params.y if params.y is not None else 0
                jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.translate({dx}, {dy});
"Translated by (" + {dx} + ", " + {dy} + ")";
"""
        elif params.action == "resize":
            sx = params.scale_x if params.scale_x is not None else 100
            sy = params.scale_y if params.scale_y is not None else 100
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.resize({sx}, {sy});
"Resized to " + {sx} + "% x " + {sy} + "%";
"""
        elif params.action == "rotate":
            angle = params.angle if params.angle is not None else 0
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.rotate({angle});
"Rotated " + {angle} + " degrees";
"""
        elif params.action == "recolor_fill":
            if params.fill_r is None or params.fill_g is None or params.fill_b is None:
                return "Error: recolor_fill requires fill_r, fill_g, fill_b"
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
var fc = new RGBColor();
fc.red = {params.fill_r}; fc.green = {params.fill_g}; fc.blue = {params.fill_b};
item.fillColor = fc;
item.filled = true;
"Fill color set";
"""
        elif params.action == "recolor_stroke":
            if params.stroke_r is None or params.stroke_g is None or params.stroke_b is None:
                return "Error: recolor_stroke requires stroke_r, stroke_g, stroke_b"
            stroke_width_line = ""
            if params.stroke_width is not None:
                stroke_width_line = f"item.strokeWidth = {params.stroke_width};"
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
var sc = new RGBColor();
sc.red = {params.stroke_r}; sc.green = {params.stroke_g}; sc.blue = {params.stroke_b};
item.strokeColor = sc;
item.stroked = true;
{stroke_width_line}
"Stroke set";
"""
        elif params.action == "rename":
            if not params.new_name:
                return "Error: rename requires 'new_name'"
            escaped_new = escape_jsx_string(params.new_name)
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.name = "{escaped_new}";
"Renamed to " + item.name;
"""
        elif params.action == "delete":
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
var n = item.name;
item.remove();
"Deleted: " + n;
"""
        elif params.action == "opacity":
            if params.opacity is None:
                return "Error: opacity action requires 'opacity' value"
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.opacity = {params.opacity};
"Opacity set to " + {params.opacity};
"""
        elif params.action == "arrange":
            z_map = {
                "bring_to_front": "BRINGTOFRONT",
                "bring_forward": "BRINGFORWARD",
                "send_backward": "SENDBACKWARD",
                "send_to_back": "SENDTOBACK",
            }
            if not params.arrange or params.arrange not in z_map:
                return f"Error: arrange requires 'arrange' param: {', '.join(z_map.keys())}"
            z_value = z_map[params.arrange]
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
item.zOrder(ZOrderMethod.{z_value});
"Z-order changed";
"""
        elif params.action == "duplicate":
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
var dup = item.duplicate();
JSON.stringify({{ original: item.name, duplicate: dup.name }});
"""
        elif params.action == "group":
            group_name = escape_jsx_string(params.new_name or "Group")
            jsx_parts = f"""
var doc = app.activeDocument;
var grp = doc.groupItems.add();
grp.name = "{group_name}";
"""
            if params.items:
                names = [n.strip() for n in params.items.split(",")]
                for n in names:
                    escaped_n = escape_jsx_string(n)
                    jsx_parts += f'try {{ doc.pageItems.getByName("{escaped_n}").move(grp, ElementPlacement.INSIDE); }} catch(e) {{}}\n'
            jsx_parts += '"Grouped " + grp.pageItems.length + " items";'
            jsx = jsx_parts

        elif params.action == "ungroup":
            jsx = f"""
var doc = app.activeDocument;
{item_lookup}
if (item.typename === "GroupItem") {{
    var count = item.pageItems.length;
    while (item.pageItems.length > 0) {{
        item.pageItems[0].move(doc, ElementPlacement.PLACEATEND);
    }}
    item.remove();
    "Ungrouped " + count + " items";
}} else {{
    "Item is not a group";
}}
"""
        else:
            return f"Unknown modify action: {params.action}"

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
