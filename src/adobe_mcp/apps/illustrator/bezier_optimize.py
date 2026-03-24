"""Smooth jagged polygon paths into clean bezier curves in Illustrator.

Iterates all pathPoints, calculates angles, and sets bezier control handles
based on smoothness factor — preserving corners below the angle threshold.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiBezierOptimizeInput


# JSX helper: find a pathItem by name (searching all layers), index, or selection.
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


def _build_target_call(params: AiBezierOptimizeInput) -> str:
    """Build the JSX call to getTargetItem with the right arguments."""
    if params.name:
        escaped = escape_jsx_string(params.name)
        return f'var item = getTargetItem(doc, "{escaped}", null);'
    elif params.index is not None:
        return f"var item = getTargetItem(doc, null, {params.index});"
    else:
        return 'var item = getTargetItem(doc, null, null);'


def register(mcp):
    """Register the adobe_ai_bezier_optimize tool."""

    @mcp.tool(
        name="adobe_ai_bezier_optimize",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_bezier_optimize(params: AiBezierOptimizeInput) -> str:
        """Smooth a jagged polygon path into clean bezier curves.

        Iterates every anchor point and calculates the angle formed by
        prev -> current -> next vectors.  Points sharper than corner_angle
        (when preserve_corners is True) are kept as hard corners; all other
        points get left/right direction handles set proportional to the
        smoothness parameter, producing clean cubic curves.

        Returns: point count, corners preserved, points smoothed.
        """
        target_call = _build_target_call(params)
        smoothness = params.smoothness
        preserve_corners = "true" if params.preserve_corners else "false"
        corner_angle = params.corner_angle

        jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}

    // --- Angle helper: degrees between vectors a->b and b->c ---
    function angleBetween(a, b, c) {{
        var v1x = a[0] - b[0], v1y = a[1] - b[1];
        var v2x = c[0] - b[0], v2y = c[1] - b[1];
        var dot = v1x * v2x + v1y * v2y;
        var cross = v1x * v2y - v1y * v2x;
        return Math.abs(Math.atan2(cross, dot) * 180 / Math.PI);
    }}

    // --- Distance helper ---
    function dist(a, b) {{
        var dx = b[0] - a[0], dy = b[1] - a[1];
        return Math.sqrt(dx * dx + dy * dy);
    }}

    var doc = app.activeDocument;
    {target_call}

    if (item === null) {{
        return JSON.stringify({{"error": "No target pathItem found. Specify name, index, or select a path."}});
    }} else {{
        var pts = item.pathPoints;
        var n = pts.length;
        var smoothness = {smoothness};
        var preserveCorners = {preserve_corners};
        var cornerAngle = {corner_angle};
        var smoothFactor = smoothness / 100.0;

        var cornersPreserved = 0;
        var pointsSmoothed = 0;

        for (var i = 0; i < n; i++) {{
            var curr = pts[i].anchor;

            // Determine prev and next, wrapping for closed paths
            var prevIdx = (i > 0) ? i - 1 : (item.closed ? n - 1 : -1);
            var nextIdx = (i < n - 1) ? i + 1 : (item.closed ? 0 : -1);

            // Skip endpoints of open paths (no angle to compute)
            if (prevIdx < 0 || nextIdx < 0) {{
                // For open-path endpoints, apply light tangent handles toward the adjacent point
                if (prevIdx < 0 && nextIdx >= 0) {{
                    // First point of open path: handle toward next
                    var nxt = pts[nextIdx].anchor;
                    var d = dist(curr, nxt);
                    var handleLen = smoothFactor * (d / 3.0);
                    var dx = nxt[0] - curr[0];
                    var dy = nxt[1] - curr[1];
                    var dNorm = Math.sqrt(dx * dx + dy * dy);
                    if (dNorm > 0.001) {{
                        pts[i].rightDirection = [
                            curr[0] + (dx / dNorm) * handleLen,
                            curr[1] + (dy / dNorm) * handleLen
                        ];
                    }}
                    pointsSmoothed++;
                }} else if (nextIdx < 0 && prevIdx >= 0) {{
                    // Last point of open path: handle toward prev
                    var prv = pts[prevIdx].anchor;
                    var d = dist(curr, prv);
                    var handleLen = smoothFactor * (d / 3.0);
                    var dx = prv[0] - curr[0];
                    var dy = prv[1] - curr[1];
                    var dNorm = Math.sqrt(dx * dx + dy * dy);
                    if (dNorm > 0.001) {{
                        pts[i].leftDirection = [
                            curr[0] + (dx / dNorm) * handleLen,
                            curr[1] + (dy / dNorm) * handleLen
                        ];
                    }}
                    pointsSmoothed++;
                }}
                continue;
            }}

            var prev = pts[prevIdx].anchor;
            var next = pts[nextIdx].anchor;

            var angle = angleBetween(prev, curr, next);

            // If this is a sharp corner and we want to preserve it, skip
            if (preserveCorners && angle < cornerAngle) {{
                cornersPreserved++;
                continue;
            }}

            // Set smooth bezier handles
            // Direction: tangent along prev -> next
            var tx = next[0] - prev[0];
            var ty = next[1] - prev[1];
            var tLen = Math.sqrt(tx * tx + ty * ty);

            if (tLen < 0.001) {{
                continue;  // degenerate — prev and next overlap
            }}

            // Normalize tangent
            var tnx = tx / tLen;
            var tny = ty / tLen;

            // Handle lengths proportional to distance to adjacent anchors
            var distPrev = dist(curr, prev);
            var distNext = dist(curr, next);
            var leftHandleLen = smoothFactor * (distPrev / 3.0);
            var rightHandleLen = smoothFactor * (distNext / 3.0);

            // Left handle points toward prev (negative tangent direction)
            pts[i].leftDirection = [
                curr[0] - tnx * leftHandleLen,
                curr[1] - tny * leftHandleLen
            ];

            // Right handle points toward next (positive tangent direction)
            pts[i].rightDirection = [
                curr[0] + tnx * rightHandleLen,
                curr[1] + tny * rightHandleLen
            ];

            pointsSmoothed++;
        }}

        return JSON.stringify({{
            name: item.name || "(unnamed)",
            point_count: n,
            corners_preserved: cornersPreserved,
            points_smoothed: pointsSmoothed,
            smoothness: smoothness,
            corner_angle: cornerAngle
        }});
    }}
}})();
"""
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
