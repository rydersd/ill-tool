"""Snap anchor points to the nearest grid positions in Illustrator.

When grid_spacing is provided, snaps each anchor to the nearest grid intersection.
When grid_spacing is None, reads the Proportion Grid layer's guide positions and
snaps to the nearest guide intersection. Handles are translated by the same delta
to preserve curve shapes.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSnapToGridInput


def _snap_value(val: float, spacing: float) -> float:
    """Snap a single value to the nearest grid line."""
    return round(val / spacing) * spacing


def _snap_to_positions(val: float, positions: list[float], max_dist: float) -> float:
    """Snap a value to the nearest position in a list, if within max_dist."""
    if not positions:
        return val
    nearest = min(positions, key=lambda p: abs(p - val))
    if abs(nearest - val) <= max_dist:
        return nearest
    return val


def register(mcp):
    """Register the adobe_ai_snap_to_grid tool."""

    @mcp.tool(
        name="adobe_ai_snap_to_grid",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_snap_to_grid(params: AiSnapToGridInput) -> str:
        """Snap anchor points to the nearest grid or proportion guide positions.

        If grid_spacing is set, snaps to a regular grid. Otherwise reads guide
        positions from the Proportion Grid layer. Only snaps points within
        snap_distance to avoid large jumps. Bezier handles are translated by
        the same delta to preserve curve shape.
        """
        escaped_layer = escape_jsx_string(params.layer_name)

        # Determine which items to target and read their points
        name_filter = ""
        if params.name:
            escaped_name = escape_jsx_string(params.name)
            name_filter = f'if (pi.name !== "{escaped_name}") continue;'

        # If no grid_spacing, read guide positions from Proportion Grid layer
        guide_read = ""
        if params.grid_spacing is None:
            guide_read = """
    // Read guide positions from Proportion Grid layer
    var gridLayer = null;
    for (var g = 0; g < doc.layers.length; g++) {
        if (doc.layers[g].name === "Proportion Grid") {
            gridLayer = doc.layers[g]; break;
        }
    }
    var hGuides = [];
    var vGuides = [];
    if (gridLayer) {
        for (var g = 0; g < gridLayer.pathItems.length; g++) {
            var gpi = gridLayer.pathItems[g];
            var gb = gpi.geometricBounds;
            var gw = gb[2] - gb[0];
            var gh = gb[1] - gb[3];
            // Horizontal guide: wide and thin
            if (gw > gh * 5) {
                hGuides.push((gb[1] + gb[3]) / 2);
            }
            // Vertical guide: tall and thin
            if (gh > gw * 5) {
                vGuides.push((gb[0] + gb[2]) / 2);
            }
        }
    }
"""

        # Read all path points from the target layer
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

    {guide_read}

    var paths = [];
    for (var i = 0; i < layer.pathItems.length; i++) {{
        var pi = layer.pathItems[i];
        {name_filter}
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
            points: pts
        }});
    }}

    var result = {{paths: paths}};
    {"result.hGuides = hGuides; result.vGuides = vGuides;" if params.grid_spacing is None else ""}
    return JSON.stringify(result);
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
        if not paths:
            return json.dumps({"snapped": 0, "note": "No paths found on layer."})

        # Determine snap mode
        use_grid = params.grid_spacing is not None
        h_guides = data.get("hGuides", [])
        v_guides = data.get("vGuides", [])
        snap_dist = params.snap_distance

        if not use_grid and not h_guides and not v_guides:
            return json.dumps({
                "error": "No grid_spacing provided and no Proportion Grid guides found. "
                         "Set grid_spacing or create a proportion grid first."
            })

        # Compute snapped positions for each point
        total_snapped = 0
        corrections = []  # per-path correction data for JSX

        for path in paths:
            path_corrections = []
            for pt_idx, pt in enumerate(path["points"]):
                ax, ay = pt["anchor"]

                if use_grid:
                    new_x = _snap_value(ax, params.grid_spacing)
                    new_y = _snap_value(ay, params.grid_spacing)
                else:
                    new_x = _snap_to_positions(ax, v_guides, snap_dist)
                    new_y = _snap_to_positions(ay, h_guides, snap_dist)

                dx = new_x - ax
                dy = new_y - ay
                dist = math.sqrt(dx * dx + dy * dy)

                # Only snap if within snap_distance
                if dist > 0.01 and dist <= snap_dist:
                    path_corrections.append({
                        "pt_idx": pt_idx,
                        "new_x": round(new_x, 2),
                        "new_y": round(new_y, 2),
                        "dx": round(dx, 2),
                        "dy": round(dy, 2),
                    })
                    total_snapped += 1

            if path_corrections:
                corrections.append({
                    "path_index": path["index"],
                    "points": path_corrections,
                })

        if not corrections:
            return json.dumps({
                "snapped": 0,
                "paths_checked": len(paths),
                "snap_distance": snap_dist,
                "note": "No points found within snap distance of grid positions.",
            })

        # Apply corrections via JSX
        corrections_json = json.dumps(corrections)
        apply_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}
    var corrections = {corrections_json};
    var totalMoved = 0;
    for (var c = 0; c < corrections.length; c++) {{
        var corr = corrections[c];
        var pi = layer.pathItems[corr.path_index];
        for (var p = 0; p < corr.points.length; p++) {{
            var pt = corr.points[p];
            var pp = pi.pathPoints[pt.pt_idx];
            // Move handles by the same delta to preserve curve shape
            pp.leftDirection = [
                pp.leftDirection[0] + pt.dx,
                pp.leftDirection[1] + pt.dy
            ];
            pp.rightDirection = [
                pp.rightDirection[0] + pt.dx,
                pp.rightDirection[1] + pt.dy
            ];
            pp.anchor = [pt.new_x, pt.new_y];
            totalMoved++;
        }}
    }}
    return JSON.stringify({{totalMoved: totalMoved, pathsAdjusted: corrections.length}});
}})();
"""
        apply_result = await _async_run_jsx("illustrator", apply_jsx)
        if not apply_result["success"]:
            return f"Error applying snap: {apply_result['stderr']}"

        try:
            result = json.loads(apply_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            result = {}

        return json.dumps({
            "points_snapped": result.get("totalMoved", total_snapped),
            "paths_adjusted": result.get("pathsAdjusted", len(corrections)),
            "snap_mode": "grid" if use_grid else "proportion_guides",
            "grid_spacing": params.grid_spacing,
            "snap_distance": snap_dist,
            "guide_counts": {
                "horizontal": len(h_guides),
                "vertical": len(v_guides),
            } if not use_grid else None,
        }, indent=2)
