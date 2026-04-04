"""Direct anchor point manipulation for Illustrator pathItems — get, set, add, remove points and bezier handles."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiAnchorEditInput


# JSX helper function injected into every script to resolve the target pathItem
# by name (searching all layers), index, or falling back to current selection.
_TARGET_RESOLVER_JSX = """
function getTargetItem(doc, name, index) {
    if (name !== null && name !== "") {
        for (var l = 0; l < doc.layers.length; l++) {
            var lyr = doc.layers[l];
            for (var s = 0; s < lyr.pathItems.length; s++) {
                if (lyr.pathItems[s].name === name) {
                    return lyr.pathItems[s];
                }
            }
            // Also search inside groups on each layer
            for (var g = 0; g < lyr.groupItems.length; g++) {
                try {
                    var found = lyr.groupItems[g].pathItems.getByName(name);
                    if (found) return found;
                } catch(e) {}
            }
        }
        return null;
    } else if (index !== null) {
        return doc.pathItems[index];
    }
    if (doc.selection.length > 0 && doc.selection[0].typename === "PathItem") {
        return doc.selection[0];
    }
    return null;
}
"""


def _build_target_call(params: AiAnchorEditInput) -> str:
    """Build the JSX call to getTargetItem with the right arguments."""
    if params.name:
        escaped = escape_jsx_string(params.name)
        return f'var item = getTargetItem(doc, "{escaped}", null);'
    elif params.index is not None:
        return f"var item = getTargetItem(doc, null, {params.index});"
    else:
        return 'var item = getTargetItem(doc, null, null);'


def register(mcp):
    """Register the adobe_ai_anchor_edit tool."""

    @mcp.tool(
        name="adobe_ai_anchor_edit",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_anchor_edit(params: AiAnchorEditInput) -> str:
        """Get or set individual anchor points and bezier handles on Illustrator pathItems.

        Actions:
        - get_points: return all anchor points with coordinates and handle positions
        - set_point: move a single anchor point (handles shift by same delta to preserve shape)
        - set_handles: set left/right bezier control handles independently
        - add_point: add a new anchor point at the end of the path
        - remove_point: remove an anchor point by index
        - simplify: remove points whose removal changes the path less than tolerance
        """
        target_call = _build_target_call(params)
        null_check = """
if (item === null) {
    '{"error": "No target pathItem found. Specify name, index, or select a path."}';
} else {
"""
        close_brace = "\n}"

        if params.action == "get_points":
            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    var pts = item.pathPoints;
    var result = [];
    for (var i = 0; i < pts.length; i++) {{
        var p = pts[i];
        var a = p.anchor;
        var ld = p.leftDirection;
        var rd = p.rightDirection;
        var ptype = "corner";
        if (Math.abs(ld[0] - a[0]) > 0.001 || Math.abs(ld[1] - a[1]) > 0.001 ||
            Math.abs(rd[0] - a[0]) > 0.001 || Math.abs(rd[1] - a[1]) > 0.001) {{
            ptype = "smooth";
        }}
        result.push({{
            index: i,
            anchor: [Math.round(a[0] * 1000) / 1000, Math.round(a[1] * 1000) / 1000],
            left_direction: [Math.round(ld[0] * 1000) / 1000, Math.round(ld[1] * 1000) / 1000],
            right_direction: [Math.round(rd[0] * 1000) / 1000, Math.round(rd[1] * 1000) / 1000],
            point_type: ptype
        }});
    }}
    JSON.stringify({{
        name: item.name || "(unnamed)",
        point_count: pts.length,
        closed: item.closed,
        points: result
    }});
{close_brace}
"""

        elif params.action == "set_point":
            if params.point_index is None:
                return "Error: set_point requires 'point_index'"
            if params.x is None or params.y is None:
                return "Error: set_point requires both 'x' and 'y'"
            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    if ({params.point_index} >= item.pathPoints.length) {{
        '{{"error": "point_index {params.point_index} out of range, path has " + item.pathPoints.length + " points"}}';
    }} else {{
        var pt = item.pathPoints[{params.point_index}];
        var dx = {params.x} - pt.anchor[0];
        var dy = {params.y} - pt.anchor[1];
        pt.anchor = [{params.x}, {params.y}];
        pt.leftDirection = [pt.leftDirection[0] + dx, pt.leftDirection[1] + dy];
        pt.rightDirection = [pt.rightDirection[0] + dx, pt.rightDirection[1] + dy];
        JSON.stringify({{
            action: "set_point",
            point_index: {params.point_index},
            new_anchor: [{params.x}, {params.y}],
            delta: [Math.round(dx * 1000) / 1000, Math.round(dy * 1000) / 1000]
        }});
    }}
{close_brace}
"""

        elif params.action == "set_handles":
            if params.point_index is None:
                return "Error: set_handles requires 'point_index'"
            if params.left_x is None and params.right_x is None:
                return "Error: set_handles requires at least left_x/left_y or right_x/right_y"

            # Build handle-setting lines conditionally
            left_line = ""
            if params.left_x is not None and params.left_y is not None:
                left_line = f"pt.leftDirection = [{params.left_x}, {params.left_y}];"
            elif params.left_x is not None or params.left_y is not None:
                return "Error: set_handles requires both left_x and left_y together"

            right_line = ""
            if params.right_x is not None and params.right_y is not None:
                right_line = f"pt.rightDirection = [{params.right_x}, {params.right_y}];"
            elif params.right_x is not None or params.right_y is not None:
                return "Error: set_handles requires both right_x and right_y together"

            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    if ({params.point_index} >= item.pathPoints.length) {{
        '{{"error": "point_index {params.point_index} out of range, path has " + item.pathPoints.length + " points"}}';
    }} else {{
        var pt = item.pathPoints[{params.point_index}];
        {left_line}
        {right_line}
        JSON.stringify({{
            action: "set_handles",
            point_index: {params.point_index},
            left_direction: [Math.round(pt.leftDirection[0] * 1000) / 1000, Math.round(pt.leftDirection[1] * 1000) / 1000],
            right_direction: [Math.round(pt.rightDirection[0] * 1000) / 1000, Math.round(pt.rightDirection[1] * 1000) / 1000]
        }});
    }}
{close_brace}
"""

        elif params.action == "add_point":
            if params.x is None or params.y is None:
                return "Error: add_point requires both 'x' and 'y'"
            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    var newPt = item.pathPoints.add();
    newPt.anchor = [{params.x}, {params.y}];
    newPt.leftDirection = [{params.x}, {params.y}];
    newPt.rightDirection = [{params.x}, {params.y}];
    JSON.stringify({{
        action: "add_point",
        new_index: item.pathPoints.length - 1,
        anchor: [{params.x}, {params.y}],
        total_points: item.pathPoints.length,
        note: "Point added at end of path. Use set_handles to add curvature."
    }});
{close_brace}
"""

        elif params.action == "remove_point":
            if params.point_index is None:
                return "Error: remove_point requires 'point_index'"
            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    if ({params.point_index} >= item.pathPoints.length) {{
        '{{"error": "point_index {params.point_index} out of range, path has " + item.pathPoints.length + " points"}}';
    }} else {{
        var before = item.pathPoints.length;
        item.pathPoints[{params.point_index}].remove();
        JSON.stringify({{
            action: "remove_point",
            removed_index: {params.point_index},
            points_before: before,
            points_after: item.pathPoints.length
        }});
    }}
{close_brace}
"""

        elif params.action == "simplify":
            tolerance = params.tolerance if params.tolerance is not None else 2.0
            jsx = f"""
{_TARGET_RESOLVER_JSX}
var doc = app.activeDocument;
{target_call}
{null_check}
    var tolerance = {tolerance};
    var before = item.pathPoints.length;
    var removed = 0;
    // Iterate backwards from second-to-last to second point to avoid index shift issues.
    // Skip first and last points to preserve path endpoints.
    for (var i = item.pathPoints.length - 2; i >= 1; i--) {{
        var prev = item.pathPoints[i - 1].anchor;
        var curr = item.pathPoints[i].anchor;
        var next = item.pathPoints[i + 1].anchor;
        // Perpendicular distance from curr to line segment prev->next
        var ldx = next[0] - prev[0];
        var ldy = next[1] - prev[1];
        var segLen = Math.sqrt(ldx * ldx + ldy * ldy);
        if (segLen > 0) {{
            var dist = Math.abs(ldx * (prev[1] - curr[1]) - ldy * (prev[0] - curr[0])) / segLen;
            if (dist < tolerance) {{
                item.pathPoints[i].remove();
                removed++;
            }}
        }}
    }}
    JSON.stringify({{
        action: "simplify",
        tolerance: tolerance,
        points_before: before,
        points_after: item.pathPoints.length,
        points_removed: removed
    }});
{close_brace}
"""

        else:
            return f"Unknown anchor_edit action: {params.action}. Valid: get_points, set_point, set_handles, add_point, remove_point, simplify"

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
