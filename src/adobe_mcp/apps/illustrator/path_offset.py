"""Create offset (parallel) paths at a specified distance from source paths.

Reads the source path's anchor points and bezier handles from Illustrator via JSX,
computes offset positions in Python using per-point normals derived from adjacent
anchors, then creates the new path back in Illustrator.

Handles join styles at corners:
- miter: extend offset edges to their intersection point
- round: (same as miter for anchor-level offset — true rounding requires arc segments)
- bevel: truncate at the midpoint between the two offset directions
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPathOffsetInput


# ---------------------------------------------------------------------------
# JSX target resolver
# ---------------------------------------------------------------------------

_TARGET_RESOLVER_JSX = """
function getTargetItem(doc, name, index) {
    if (name !== null && name !== "") {
        for (var l = 0; l < doc.layers.length; l++) {
            for (var s = 0; s < doc.layers[l].pathItems.length; s++) {
                if (doc.layers[l].pathItems[s].name === name) {
                    return doc.layers[l].pathItems[s];
                }
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


def _build_target_call(params: AiPathOffsetInput) -> str:
    """Build the JSX call to getTargetItem with the right arguments."""
    if params.name:
        escaped = escape_jsx_string(params.name)
        return f'var item = getTargetItem(doc, "{escaped}", null);'
    elif params.index is not None:
        return f"var item = getTargetItem(doc, null, {params.index});"
    else:
        return 'var item = getTargetItem(doc, null, null);'


# ---------------------------------------------------------------------------
# Python offset computation
# ---------------------------------------------------------------------------


def _normal_at_point(
    prev: list[float],
    curr: list[float],
    nxt: list[float],
    offset: float,
    joins: str,
) -> tuple[float, float]:
    """Compute the offset direction at a point given its neighbors.

    The normal is perpendicular to the average tangent direction (prev->next).
    Offset sign: positive = outward (left of travel direction), negative = inward.
    """
    # Tangent direction: weighted average of incoming and outgoing edges
    dx_in = curr[0] - prev[0]
    dy_in = curr[1] - prev[1]
    dx_out = nxt[0] - curr[0]
    dy_out = nxt[1] - curr[1]

    len_in = math.sqrt(dx_in * dx_in + dy_in * dy_in)
    len_out = math.sqrt(dx_out * dx_out + dy_out * dy_out)

    if len_in < 1e-8 and len_out < 1e-8:
        return 0.0, 0.0

    # Normalize incoming and outgoing tangents
    if len_in > 1e-8:
        dx_in /= len_in
        dy_in /= len_in
    else:
        dx_in, dy_in = dx_out / len_out, dy_out / len_out

    if len_out > 1e-8:
        dx_out /= len_out
        dy_out /= len_out
    else:
        dx_out, dy_out = dx_in, dy_in

    # Average tangent
    tx = dx_in + dx_out
    ty = dy_in + dy_out
    t_len = math.sqrt(tx * tx + ty * ty)

    if t_len < 1e-8:
        # Tangents are exactly opposite — use the incoming perpendicular
        nx = -dy_in
        ny = dx_in
    else:
        tx /= t_len
        ty /= t_len
        # Normal is perpendicular to tangent (rotated 90 degrees CCW)
        nx = -ty
        ny = tx

    # For miter joins, scale the offset by the miter factor (1 / cos(half_angle))
    if joins == "miter":
        # Half-angle between incoming and outgoing normals
        dot = dx_in * dx_out + dy_in * dy_out
        dot = max(-1.0, min(1.0, dot))
        half_cos = math.sqrt((1.0 + dot) / 2.0)
        if half_cos > 0.1:
            miter_scale = 1.0 / half_cos
        else:
            miter_scale = 4.0  # cap miter at 4x to prevent spikes
        return nx * offset * miter_scale, ny * offset * miter_scale
    elif joins == "bevel":
        # Bevel: no miter extension, just use the direct normal
        return nx * offset, ny * offset
    else:
        # Round or default: same as miter for anchor-level computation
        dot = dx_in * dx_out + dy_in * dy_out
        dot = max(-1.0, min(1.0, dot))
        half_cos = math.sqrt((1.0 + dot) / 2.0)
        if half_cos > 0.1:
            miter_scale = 1.0 / half_cos
        else:
            miter_scale = 4.0
        return nx * offset * miter_scale, ny * offset * miter_scale


def _compute_offset_points(
    anchors: list[list[float]],
    closed: bool,
    offset: float,
    joins: str,
) -> list[list[float]]:
    """Compute offset positions for each anchor point."""
    n = len(anchors)
    if n < 2:
        return anchors

    result = []
    for i in range(n):
        if closed:
            prev = anchors[(i - 1) % n]
            nxt = anchors[(i + 1) % n]
        else:
            prev = anchors[max(0, i - 1)]
            nxt = anchors[min(n - 1, i + 1)]

        curr = anchors[i]
        dx, dy = _normal_at_point(prev, curr, nxt, offset, joins)
        result.append([round(curr[0] + dx, 2), round(curr[1] + dy, 2)])

    return result


def register(mcp):
    """Register the adobe_ai_path_offset tool."""

    @mcp.tool(
        name="adobe_ai_path_offset",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_path_offset(params: AiPathOffsetInput) -> str:
        """Create an offset (parallel) path at the specified distance from the source.

        Reads the source path's anchors and handles via JSX, computes offset positions
        in Python using per-vertex normals, then creates a new named path in Illustrator.
        Positive offset = outward, negative = inward. Supports miter, round, and bevel joins.
        """
        target_call = _build_target_call(params)

        # Read the source path's geometry
        read_jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "No target pathItem found. Specify name, index, or select a path."}});
    }}
    var pts = [];
    for (var i = 0; i < item.pathPoints.length; i++) {{
        var pp = item.pathPoints[i];
        pts.push({{
            anchor: [pp.anchor[0], pp.anchor[1]],
            left: [pp.leftDirection[0], pp.leftDirection[1]],
            right: [pp.rightDirection[0], pp.rightDirection[1]]
        }});
    }}
    var sc = [0, 0, 0];
    try {{ sc = [item.strokeColor.red, item.strokeColor.green, item.strokeColor.blue]; }} catch(e) {{}}
    return JSON.stringify({{
        name: item.name || "(unnamed)",
        layerName: item.layer.name,
        closed: item.closed,
        strokeWidth: item.strokeWidth,
        strokeColor: sc,
        points: pts
    }});
}})();
"""
        read_result = await _async_run_jsx("illustrator", read_jsx)
        if not read_result["success"]:
            return f"Error reading path: {read_result['stderr']}"

        try:
            path_data = json.loads(read_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return f"Error parsing path data: {read_result['stdout']}"

        if "error" in path_data:
            return json.dumps(path_data)

        points = path_data["points"]
        if len(points) < 2:
            return json.dumps({"error": "Source path has fewer than 2 points."})

        # Extract anchors and compute offset positions
        anchors = [pt["anchor"] for pt in points]
        offset_anchors = _compute_offset_points(
            anchors, path_data["closed"], params.offset, params.joins,
        )

        # Compute offset handles by shifting each handle by the same delta as its anchor
        offset_points = []
        for i, pt in enumerate(points):
            dx = offset_anchors[i][0] - pt["anchor"][0]
            dy = offset_anchors[i][1] - pt["anchor"][1]
            offset_points.append({
                "anchor": offset_anchors[i],
                "left": [round(pt["left"][0] + dx, 2), round(pt["left"][1] + dy, 2)],
                "right": [round(pt["right"][0] + dx, 2), round(pt["right"][1] + dy, 2)],
            })

        # Create the offset path in Illustrator
        offset_anchors_json = json.dumps([p["anchor"] for p in offset_points])
        lefts_json = json.dumps([p["left"] for p in offset_points])
        rights_json = json.dumps([p["right"] for p in offset_points])
        sc = path_data["strokeColor"]
        escaped_layer = escape_jsx_string(path_data["layerName"])
        escaped_name = escape_jsx_string(params.result_name)
        closed_js = "true" if path_data["closed"] else "false"

        create_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{ layer = doc.layers[0]; }}

    var path = layer.pathItems.add();
    var anchors = {offset_anchors_json};
    path.setEntirePath(anchors);
    path.closed = {closed_js};

    var lefts = {lefts_json};
    var rights = {rights_json};
    for (var i = 0; i < path.pathPoints.length; i++) {{
        path.pathPoints[i].leftDirection = lefts[i];
        path.pathPoints[i].rightDirection = rights[i];
    }}

    path.name = "{escaped_name}";
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = {path_data["strokeWidth"]};
    var sc = new RGBColor();
    sc.red = {sc[0]}; sc.green = {sc[1]}; sc.blue = {sc[2]};
    path.strokeColor = sc;

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        point_count: path.pathPoints.length,
        bounds: [
            Math.round(path.geometricBounds[0] * 100) / 100,
            Math.round(path.geometricBounds[1] * 100) / 100,
            Math.round(path.geometricBounds[2] * 100) / 100,
            Math.round(path.geometricBounds[3] * 100) / 100
        ]
    }});
}})();
"""
        create_result = await _async_run_jsx("illustrator", create_jsx)
        if not create_result["success"]:
            return json.dumps({
                "error": f"Path creation failed: {create_result['stderr']}",
                "offset_points": offset_anchors,
            })

        try:
            placed = json.loads(create_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            placed = {"raw": create_result["stdout"]}

        return json.dumps({
            "source": path_data["name"],
            "offset_distance": params.offset,
            "joins": params.joins,
            "result": placed,
        }, indent=2)
