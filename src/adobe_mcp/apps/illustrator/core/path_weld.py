"""Join adjacent path endpoints into continuous paths (weld operation).

Reads all pathItems on a layer (or specific named items), finds pairs of endpoints
within tolerance, and concatenates them into unified paths. The original separate
paths are removed and replaced with the welded result.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPathWeldInput


def _endpoint_distance(
    p1: list[float],
    p2: list[float],
) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _find_weld_pairs(
    paths: list[dict],
    tolerance: float,
) -> list[tuple[int, int, str, str]]:
    """Find pairs of path endpoints within tolerance.

    Returns list of (path_a_index, path_b_index, endpoint_a, endpoint_b)
    where endpoint is "start" or "end".
    """
    pairs = []
    used = set()

    for i, pa in enumerate(paths):
        if i in used:
            continue
        pts_a = pa["points"]
        if not pts_a:
            continue

        a_start = pts_a[0]["anchor"]
        a_end = pts_a[-1]["anchor"]

        for j, pb in enumerate(paths):
            if j <= i or j in used:
                continue
            pts_b = pb["points"]
            if not pts_b:
                continue

            b_start = pts_b[0]["anchor"]
            b_end = pts_b[-1]["anchor"]

            # Check all four endpoint combinations
            candidates = [
                (_endpoint_distance(a_end, b_start), "end", "start"),
                (_endpoint_distance(a_end, b_end), "end", "end"),
                (_endpoint_distance(a_start, b_start), "start", "start"),
                (_endpoint_distance(a_start, b_end), "start", "end"),
            ]

            best_dist, best_ea, best_eb = min(candidates, key=lambda c: c[0])

            if best_dist <= tolerance:
                pairs.append((i, j, best_ea, best_eb))
                used.add(i)
                used.add(j)
                break  # path i is consumed

    return pairs


def _weld_points(
    pts_a: list[dict],
    pts_b: list[dict],
    endpoint_a: str,
    endpoint_b: str,
) -> list[dict]:
    """Concatenate two point lists based on which endpoints are being joined.

    Returns the merged point list in order, averaging the joined endpoints.
    """
    # Orient both paths so the weld point is at the junction
    if endpoint_a == "start":
        pts_a = list(reversed(pts_a))
    if endpoint_b == "end":
        pts_b = list(reversed(pts_b))

    # Average the junction point (last of a, first of b)
    junction_a = pts_a[-1]
    junction_b = pts_b[0]
    avg_anchor = [
        (junction_a["anchor"][0] + junction_b["anchor"][0]) / 2,
        (junction_a["anchor"][1] + junction_b["anchor"][1]) / 2,
    ]
    avg_left = [
        (junction_a["left"][0] + junction_b["left"][0]) / 2,
        (junction_a["left"][1] + junction_b["left"][1]) / 2,
    ]
    avg_right = [
        (junction_a["right"][0] + junction_b["right"][0]) / 2,
        (junction_a["right"][1] + junction_b["right"][1]) / 2,
    ]

    merged_point = {
        "anchor": [round(avg_anchor[0], 2), round(avg_anchor[1], 2)],
        "left": [round(avg_left[0], 2), round(avg_left[1], 2)],
        "right": [round(avg_right[0], 2), round(avg_right[1], 2)],
    }

    # Build combined path: a[0..n-2] + merged_junction + b[1..end]
    result = pts_a[:-1] + [merged_point] + pts_b[1:]
    return result


def register(mcp):
    """Register the adobe_ai_path_weld tool."""

    @mcp.tool(
        name="adobe_ai_path_weld",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_path_weld(params: AiPathWeldInput) -> str:
        """Join adjacent path endpoints into continuous paths.

        Searches pathItems on the specified layer for endpoint pairs within the
        tolerance distance, then welds them by concatenating point arrays and
        averaging the junction point. Original paths are removed and replaced
        with unified welded paths.
        """
        escaped_layer = escape_jsx_string(params.layer_name)

        # Build name filter if specific names are given
        name_filter = ""
        if params.names:
            name_list = [n.strip() for n in params.names.split(",") if n.strip()]
            names_json = json.dumps(name_list)
            name_filter = f"""
    var allowedNames = {names_json};
    function isAllowed(n) {{
        for (var k = 0; k < allowedNames.length; k++) {{
            if (allowedNames[k] === n) return true;
        }}
        return false;
    }}
"""
        else:
            name_filter = "function isAllowed(n) { return true; }"

        # Read all paths from the layer
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

    {name_filter}

    var paths = [];
    for (var i = 0; i < layer.pathItems.length; i++) {{
        var pi = layer.pathItems[i];
        if (!isAllowed(pi.name) && "{params.names or ''}".length > 0) continue;
        if (pi.closed) continue;  // closed paths have no endpoints to weld

        var pts = [];
        for (var j = 0; j < pi.pathPoints.length; j++) {{
            var pp = pi.pathPoints[j];
            pts.push({{
                anchor: [pp.anchor[0], pp.anchor[1]],
                left: [pp.leftDirection[0], pp.leftDirection[1]],
                right: [pp.rightDirection[0], pp.rightDirection[1]]
            }});
        }}
        paths.push({{
            index: i,
            name: pi.name,
            pointCount: pi.pathPoints.length,
            points: pts
        }});
    }}

    return JSON.stringify({{paths: paths, layerName: layer.name}});
}})();
"""
        read_result = await _async_run_jsx("illustrator", read_jsx)
        if not read_result["success"]:
            return f"Error reading paths: {read_result['stderr']}"

        try:
            data = json.loads(read_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return f"Error parsing path data: {read_result['stdout']}"

        if "error" in data:
            return json.dumps(data)

        paths = data["paths"]
        if len(paths) < 2:
            return json.dumps({
                "welded": 0,
                "note": f"Found {len(paths)} open path(s) on layer — need at least 2 to weld.",
            })

        # Find weldable pairs
        weld_pairs = _find_weld_pairs(paths, params.tolerance)

        if not weld_pairs:
            return json.dumps({
                "welded": 0,
                "paths_checked": len(paths),
                "tolerance": params.tolerance,
                "note": "No endpoint pairs found within tolerance.",
            })

        # Compute welded point arrays
        welded_paths = []
        indices_to_remove = set()

        for pa_idx, pb_idx, ea, eb in weld_pairs:
            merged_points = _weld_points(
                paths[pa_idx]["points"],
                paths[pb_idx]["points"],
                ea, eb,
            )
            welded_paths.append(merged_points)
            indices_to_remove.add(paths[pa_idx]["index"])
            indices_to_remove.add(paths[pb_idx]["index"])

        # Build JSX to remove originals and create welded paths
        remove_indices = sorted(indices_to_remove, reverse=True)  # remove from end first
        escaped_result_name = escape_jsx_string(params.result_name)

        welded_anchors_all = []
        welded_lefts_all = []
        welded_rights_all = []
        for wp in welded_paths:
            welded_anchors_all.append([p["anchor"] for p in wp])
            welded_lefts_all.append([p["left"] for p in wp])
            welded_rights_all.append([p["right"] for p in wp])

        create_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}

    // Remove original paths (highest index first to preserve indices)
    var removeIndices = {json.dumps(remove_indices)};
    for (var r = 0; r < removeIndices.length; r++) {{
        layer.pathItems[removeIndices[r]].remove();
    }}

    // Create welded paths
    var allAnchors = {json.dumps(welded_anchors_all)};
    var allLefts = {json.dumps(welded_lefts_all)};
    var allRights = {json.dumps(welded_rights_all)};
    var created = [];

    for (var w = 0; w < allAnchors.length; w++) {{
        var path = layer.pathItems.add();
        path.setEntirePath(allAnchors[w]);
        path.closed = false;
        for (var p = 0; p < path.pathPoints.length; p++) {{
            path.pathPoints[p].leftDirection = allLefts[w][p];
            path.pathPoints[p].rightDirection = allRights[w][p];
        }}
        path.filled = false;
        path.stroked = true;
        path.strokeWidth = 1;
        var black = new RGBColor();
        black.red = 0; black.green = 0; black.blue = 0;
        path.strokeColor = black;
        path.name = "{escaped_result_name}" + (allAnchors.length > 1 ? "_" + w : "");
        created.push({{
            name: path.name,
            pointCount: path.pathPoints.length
        }});
    }}

    return JSON.stringify({{created: created}});
}})();
"""
        create_result = await _async_run_jsx("illustrator", create_jsx)
        if not create_result["success"]:
            return f"Error creating welded paths: {create_result['stderr']}"

        try:
            result = json.loads(create_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            result = {"raw": create_result["stdout"]}

        return json.dumps({
            "welded_count": len(weld_pairs),
            "paths_removed": len(indices_to_remove),
            "paths_created": result.get("created", []),
            "tolerance": params.tolerance,
        }, indent=2)
