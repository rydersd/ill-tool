"""Apply variable-width stroke profiles to Illustrator paths for expressive line art.

JSX approach: Illustrator's scripting model does not expose variable-width profiles
directly. This tool splits the source path into per-segment sub-paths and applies
graduated strokeWidth values to simulate taper, swell, and pressure profiles.

For the "uniform" profile, the path is left intact with a single strokeWidth.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiStrokeProfileInput


# ---------------------------------------------------------------------------
# JSX target resolver (reused across several tools)
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


def _build_target_call(params: AiStrokeProfileInput) -> str:
    """Build the JSX call to getTargetItem with the right arguments."""
    if params.name:
        escaped = escape_jsx_string(params.name)
        return f'var item = getTargetItem(doc, "{escaped}", null);'
    elif params.index is not None:
        return f"var item = getTargetItem(doc, null, {params.index});"
    else:
        return 'var item = getTargetItem(doc, null, null);'


def _compute_profile_widths(
    profile: str,
    segment_count: int,
    min_width: float,
    max_width: float,
) -> list[float]:
    """Compute per-segment stroke widths for the given profile type.

    Returns a list of widths, one per segment.
    """
    if segment_count < 1:
        return []

    widths = []
    for i in range(segment_count):
        t = i / max(segment_count - 1, 1)  # normalized 0..1

        if profile == "taper":
            # Thick at start, thin at end (linear decrease)
            w = max_width - t * (max_width - min_width)
        elif profile == "swell":
            # Thin at both ends, thick in the middle (parabolic)
            w = min_width + (max_width - min_width) * (1 - (2 * t - 1) ** 2)
        elif profile == "pressure":
            # Sine wave variation simulating pen pressure
            w = min_width + (max_width - min_width) * (0.5 + 0.5 * math.sin(t * math.pi * 2))
        else:
            # "uniform" or unknown — constant width
            w = max_width

        widths.append(round(w, 2))

    return widths


def register(mcp):
    """Register the adobe_ai_stroke_profiles tool."""

    @mcp.tool(
        name="adobe_ai_stroke_profiles",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_stroke_profiles(params: AiStrokeProfileInput) -> str:
        """Apply a variable-width stroke profile to a path by splitting it into segments.

        Profiles:
        - taper: thick at start, thin at end (linear decrease)
        - swell: thin at ends, thick in the middle (parabolic)
        - pressure: sine wave variation simulating pen pressure
        - uniform: constant width (no splitting needed)

        The original path is replaced by per-segment sub-paths with graduated
        strokeWidth values. For "uniform", only the strokeWidth is updated.
        """
        target_call = _build_target_call(params)
        profile = params.profile
        min_w = params.min_width
        max_w = params.max_width

        # For uniform profile, just set the stroke width directly
        if profile == "uniform":
            jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "No target pathItem found. Specify name, index, or select a path."}});
    }}
    item.strokeWidth = {max_w};
    return JSON.stringify({{
        name: item.name || "(unnamed)",
        profile: "uniform",
        stroke_width: {max_w},
        segments: 0,
        note: "Single uniform width applied"
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)
            return result["stdout"] if result["success"] else f"Error: {result['stderr']}"

        # For variable profiles, read the path points, create sub-paths per segment
        # First, read the source path data
        read_jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "No target pathItem found."}});
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
    var sc = null;
    if (item.stroked && item.strokeColor) {{
        try {{
            sc = [item.strokeColor.red, item.strokeColor.green, item.strokeColor.blue];
        }} catch(e) {{ sc = [0, 0, 0]; }}
    }}
    return JSON.stringify({{
        name: item.name || "(unnamed)",
        layerName: item.layer.name,
        closed: item.closed,
        points: pts,
        strokeColor: sc || [0, 0, 0]
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
        segment_count = len(points) - 1 if not path_data["closed"] else len(points)

        if segment_count < 1:
            return json.dumps({"error": "Path has fewer than 2 points, cannot create segments."})

        # Compute widths for each segment
        widths = _compute_profile_widths(profile, segment_count, min_w, max_w)
        widths_json = json.dumps(widths)
        points_json = json.dumps(points)
        stroke_color = path_data["strokeColor"]
        escaped_layer = escape_jsx_string(path_data["layerName"])
        escaped_name = escape_jsx_string(path_data["name"])

        # Build JSX that removes original, creates per-segment sub-paths
        apply_jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "Target path not found for replacement."}});
    }}

    var origName = item.name || "profiled";
    var layer = item.layer;
    var points = {points_json};
    var widths = {widths_json};
    var closed = {str(path_data["closed"]).lower()};
    var segCount = closed ? points.length : points.length - 1;

    // Create stroke color
    var sc = new RGBColor();
    sc.red = {stroke_color[0]};
    sc.green = {stroke_color[1]};
    sc.blue = {stroke_color[2]};

    // Remove original path
    item.remove();

    // Create per-segment sub-paths
    var created = 0;
    for (var s = 0; s < segCount; s++) {{
        var i0 = s;
        var i1 = (s + 1) % points.length;
        var p0 = points[i0];
        var p1 = points[i1];

        var seg = layer.pathItems.add();
        seg.setEntirePath([p0.anchor, p1.anchor]);
        seg.pathPoints[0].leftDirection = p0.left;
        seg.pathPoints[0].rightDirection = p0.right;
        seg.pathPoints[1].leftDirection = p1.left;
        seg.pathPoints[1].rightDirection = p1.right;
        seg.closed = false;
        seg.filled = false;
        seg.stroked = true;
        seg.strokeColor = sc;
        seg.strokeWidth = widths[s];
        seg.name = origName + "_seg" + s;
        created++;
    }}

    return JSON.stringify({{
        name: origName,
        profile: "{profile}",
        segments_created: created,
        min_width: {min_w},
        max_width: {max_w}
    }});
}})();
"""
        apply_result = await _async_run_jsx("illustrator", apply_jsx)
        return apply_result["stdout"] if apply_result["success"] else f"Error: {apply_result['stderr']}"
