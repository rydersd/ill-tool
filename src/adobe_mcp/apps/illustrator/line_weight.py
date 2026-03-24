"""Auto-assign stroke widths based on light direction and form orientation.

For each segment of a path, compute the segment's normal direction.
Segments facing AWAY from light get THICK strokes (shadow side).
Segments facing TOWARD light get THIN strokes (light side).
Joint/corner segments get THICK strokes for emphasis at connections.

Implementation splits the path into per-segment sub-paths with graduated
widths (same approach as stroke_profiles.py).
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiLineWeightInput(BaseModel):
    """Apply light-direction-based line weight to paths."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: apply_weights, set_light_direction",
    )
    character_name: str = Field(default="character", description="Character identifier")
    name: Optional[str] = Field(default=None, description="Target pathItem name")
    index: Optional[int] = Field(default=None, description="Target pathItem index (0-based)")
    light_direction: str = Field(
        default="top_left",
        description="Light direction: top_left, top, top_right, left, right, bottom_left, bottom, bottom_right",
    )
    min_width: float = Field(default=0.5, description="Minimum stroke width (light side)", ge=0.1)
    max_width: float = Field(default=4.0, description="Maximum stroke width (shadow side)", ge=0.1)
    corner_threshold: float = Field(
        default=45.0,
        description="Angle change (degrees) above which a segment is treated as a corner/joint",
        ge=0,
        le=180,
    )


# ---------------------------------------------------------------------------
# Light direction vectors
# ---------------------------------------------------------------------------


LIGHT_VECTORS: dict[str, tuple[float, float]] = {
    "top_left": (-1.0, 1.0),
    "top": (0.0, 1.0),
    "top_right": (1.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "bottom_left": (-1.0, -1.0),
    "bottom": (0.0, -1.0),
    "bottom_right": (1.0, -1.0),
}


def _normalize(v: tuple[float, float]) -> tuple[float, float]:
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2)
    if mag == 0:
        return (0.0, 0.0)
    return (v[0] / mag, v[1] / mag)


# ---------------------------------------------------------------------------
# Line weight computation (pure Python)
# ---------------------------------------------------------------------------


def compute_segment_normal(p0: list[float], p1: list[float]) -> tuple[float, float]:
    """Compute the outward normal for a line segment from p0 to p1.

    Normal is 90 degrees CCW from the segment direction (right-hand rule,
    Y-up coordinate system used by Illustrator).
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        return (0.0, 0.0)
    # Perpendicular CCW: (-dy, dx) normalized
    return (-dy / length, dx / length)


def compute_segment_angle(p0: list[float], p1: list[float]) -> float:
    """Angle of a segment in degrees."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    return math.degrees(math.atan2(dy, dx))


def compute_line_weights(
    points: list[list[float]],
    light_direction: str,
    min_width: float = 0.5,
    max_width: float = 4.0,
    corner_threshold: float = 45.0,
) -> list[dict]:
    """Compute per-segment stroke widths based on light direction.

    Parameters
    ----------
    points : list of [x, y]
        Sequential path anchor points.
    light_direction : str
        Named direction of the light source.
    min_width, max_width : float
        Width range for the strokes.
    corner_threshold : float
        Angle change between consecutive segments above which
        the segment is treated as a corner/joint.

    Returns
    -------
    list of {segment_index, normal, dot, is_corner, width}
    """
    if len(points) < 2:
        return []

    light_vec = _normalize(LIGHT_VECTORS.get(light_direction, (0, 1)))
    segments = []

    for i in range(len(points) - 1):
        p0 = points[i]
        p1 = points[i + 1]
        normal = compute_segment_normal(p0, p1)

        # dot product with light direction: 1 = facing light, -1 = facing away
        dot = normal[0] * light_vec[0] + normal[1] * light_vec[1]

        # Detect corners by angle change with previous segment
        is_corner = False
        if i > 0:
            prev_angle = compute_segment_angle(points[i - 1], points[i])
            curr_angle = compute_segment_angle(points[i], points[i + 1])
            angle_change = abs(curr_angle - prev_angle)
            # Normalize to [0, 180]
            if angle_change > 180:
                angle_change = 360 - angle_change
            if angle_change > corner_threshold:
                is_corner = True

        # Weight: facing light → thin, facing away → thick
        # dot ranges from -1..1; map to 0..1 where 0 = facing light
        t = (1.0 - dot) / 2.0  # 0 when facing light, 1 when facing away
        if is_corner:
            width = max_width  # corners always thick
        else:
            width = min_width + t * (max_width - min_width)

        segments.append({
            "segment_index": i,
            "normal": [round(normal[0], 4), round(normal[1], 4)],
            "dot": round(dot, 4),
            "is_corner": is_corner,
            "width": round(width, 2),
        })

    return segments


# ---------------------------------------------------------------------------
# JSX builder
# ---------------------------------------------------------------------------


def _build_target_call(name: Optional[str], index: Optional[int]) -> str:
    """Build JSX target resolution."""
    if name:
        escaped = escape_jsx_string(name)
        return f"""
var item = null;
for (var l = 0; l < doc.layers.length; l++) {{
    for (var s = 0; s < doc.layers[l].pathItems.length; s++) {{
        if (doc.layers[l].pathItems[s].name === "{escaped}") {{
            item = doc.layers[l].pathItems[s]; break;
        }}
    }}
    if (item) break;
}}
"""
    elif index is not None:
        return f"var item = doc.pathItems[{index}];"
    else:
        return """
var item = null;
if (doc.selection.length > 0 && doc.selection[0].typename === "PathItem") {
    item = doc.selection[0];
}
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_line_weight tool."""

    @mcp.tool(
        name="adobe_ai_line_weight",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_line_weight(params: AiLineWeightInput) -> str:
        """Auto-assign stroke widths based on light direction and form orientation.

        Segments facing the light get thin strokes; segments in shadow
        get thick strokes.  Corners/joints always get thick emphasis.
        """
        action = params.action.lower().strip()

        if action == "set_light_direction":
            ld = params.light_direction.lower().strip()
            if ld not in LIGHT_VECTORS:
                return json.dumps({
                    "error": f"Unknown light direction: {ld}",
                    "valid_directions": list(LIGHT_VECTORS.keys()),
                })
            rig = _load_rig(params.character_name)
            rig["light_direction"] = ld
            _save_rig(params.character_name, rig)
            return json.dumps({
                "action": "set_light_direction",
                "light_direction": ld,
                "vector": list(LIGHT_VECTORS[ld]),
            })

        elif action == "apply_weights":
            ld = params.light_direction.lower().strip()
            if ld not in LIGHT_VECTORS:
                return json.dumps({
                    "error": f"Unknown light direction: {ld}",
                    "valid_directions": list(LIGHT_VECTORS.keys()),
                })

            # Read the target path points via JSX
            target_call = _build_target_call(params.name, params.index)
            read_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "No target pathItem found."}});
    }}
    var pts = [];
    for (var i = 0; i < item.pathPoints.length; i++) {{
        var pp = item.pathPoints[i];
        pts.push([pp.anchor[0], pp.anchor[1]]);
    }}
    var sc = null;
    try {{
        sc = [item.strokeColor.red, item.strokeColor.green, item.strokeColor.blue];
    }} catch(e) {{ sc = [0, 0, 0]; }}
    return JSON.stringify({{
        name: item.name || "(unnamed)",
        layerName: item.layer.name,
        closed: item.closed,
        points: pts,
        strokeColor: sc
    }});
}})();
"""
            read_result = await _async_run_jsx("illustrator", read_jsx)
            if not read_result["success"]:
                return json.dumps({"error": f"JSX read failed: {read_result['stderr']}"})

            try:
                path_data = json.loads(read_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": f"Invalid path data: {read_result['stdout']}"})

            if "error" in path_data:
                return json.dumps(path_data)

            points = path_data["points"]
            if len(points) < 2:
                return json.dumps({"error": "Path has fewer than 2 points"})

            segments = compute_line_weights(
                points, ld,
                min_width=params.min_width,
                max_width=params.max_width,
                corner_threshold=params.corner_threshold,
            )

            # Build JSX that removes original and creates per-segment sub-paths
            widths = [s["width"] for s in segments]
            widths_js = json.dumps(widths)
            points_js = json.dumps(points)
            sc = path_data.get("strokeColor", [0, 0, 0])
            escaped_name = escape_jsx_string(path_data["name"])

            apply_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        return JSON.stringify({{"error": "Target path not found for replacement."}});
    }}
    var origName = item.name || "weighted";
    var layer = item.layer;
    var points = {points_js};
    var widths = {widths_js};

    var sc = new RGBColor();
    sc.red = {sc[0]}; sc.green = {sc[1]}; sc.blue = {sc[2]};

    item.remove();

    var created = 0;
    for (var s = 0; s < widths.length; s++) {{
        var p0 = points[s];
        var p1 = points[s + 1];
        var seg = layer.pathItems.add();
        seg.setEntirePath([p0, p1]);
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
        segments_created: created,
        light_direction: "{ld}"
    }});
}})();
"""
            apply_result = await _async_run_jsx("illustrator", apply_jsx)
            if not apply_result["success"]:
                return json.dumps({"error": f"JSX apply failed: {apply_result['stderr']}"})

            return json.dumps({
                "action": "apply_weights",
                "light_direction": ld,
                "segment_count": len(segments),
                "segments": segments,
                "jsx_result": apply_result["stdout"],
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["apply_weights", "set_light_direction"],
            })
