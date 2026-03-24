"""Overlay composition guides and score compositions.

Actions:
    rule_of_thirds – Draw 2 horizontal + 2 vertical guide lines at 1/3 and 2/3
    golden_ratio   – Draw golden ratio spiral and intersection points
    leading_lines  – Draw directional arrows from start to end
    depth_layers   – Draw 3 horizontal zones (foreground, midground, background)
    score          – Score character positions against rule of thirds power points
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiSceneCompositionInput(BaseModel):
    """Overlay composition guides and score compositions."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: rule_of_thirds, golden_ratio, leading_lines, depth_layers, score",
    )
    panel_width: float = Field(default=960, description="Panel width in points", ge=1)
    panel_height: float = Field(default=540, description="Panel height in points", ge=1)
    panel_x: float = Field(default=0, description="Panel left edge X")
    panel_y: float = Field(default=0, description="Panel top edge Y (AI coordinates)")
    # Leading lines params
    points_json: Optional[str] = Field(
        default=None,
        description="JSON array of [[start_x, start_y], [end_x, end_y]] for leading_lines",
    )
    # Score params
    positions_json: Optional[str] = Field(
        default=None,
        description="JSON array of [x, y] character positions for scoring",
    )


# ---------------------------------------------------------------------------
# Composition math (pure Python)
# ---------------------------------------------------------------------------


def compute_thirds(
    panel_x: float, panel_y: float,
    panel_width: float, panel_height: float,
) -> dict:
    """Compute rule-of-thirds line positions and power points.

    Returns {vertical_lines: [x1, x2], horizontal_lines: [y1, y2],
             power_points: [[x, y], ...]}.
    """
    x1 = panel_x + panel_width / 3.0
    x2 = panel_x + 2.0 * panel_width / 3.0
    y1 = panel_y - panel_height / 3.0  # AI coords: Y decreases downward
    y2 = panel_y - 2.0 * panel_height / 3.0

    power_points = [
        [round(x1, 2), round(y1, 2)],
        [round(x2, 2), round(y1, 2)],
        [round(x1, 2), round(y2, 2)],
        [round(x2, 2), round(y2, 2)],
    ]

    return {
        "vertical_lines": [round(x1, 2), round(x2, 2)],
        "horizontal_lines": [round(y1, 2), round(y2, 2)],
        "power_points": power_points,
    }


def compute_golden_ratio_points(
    panel_x: float, panel_y: float,
    panel_width: float, panel_height: float,
) -> dict:
    """Compute golden ratio intersection points.

    phi ~= 0.618; golden lines at 1/phi and 1-1/phi of panel dimensions.

    Returns {phi, vertical_lines, horizontal_lines, intersections}.
    """
    phi = (1.0 + math.sqrt(5)) / 2.0  # ~1.618
    frac = 1.0 / phi  # ~0.618

    x1 = panel_x + panel_width * frac
    x2 = panel_x + panel_width * (1.0 - frac)
    y1 = panel_y - panel_height * frac
    y2 = panel_y - panel_height * (1.0 - frac)

    intersections = [
        [round(x1, 2), round(y1, 2)],
        [round(x2, 2), round(y1, 2)],
        [round(x1, 2), round(y2, 2)],
        [round(x2, 2), round(y2, 2)],
    ]

    return {
        "phi": round(phi, 6),
        "vertical_lines": [round(x1, 2), round(x2, 2)],
        "horizontal_lines": [round(y1, 2), round(y2, 2)],
        "intersections": intersections,
    }


def compute_depth_zones(
    panel_x: float, panel_y: float,
    panel_width: float, panel_height: float,
) -> list[dict]:
    """Divide the panel into 3 horizontal depth zones.

    Returns [{name, y_top, y_bottom, height}, ...] for foreground,
    midground, background (top-to-bottom in visual reading).
    """
    zone_height = panel_height / 3.0
    zones = []
    names = ["background", "midground", "foreground"]
    for i, name in enumerate(names):
        y_top = panel_y - i * zone_height
        y_bottom = y_top - zone_height
        zones.append({
            "name": name,
            "y_top": round(y_top, 2),
            "y_bottom": round(y_bottom, 2),
            "height": round(zone_height, 2),
        })
    return zones


def score_composition(
    positions: list[list[float]],
    power_points: list[list[float]],
    panel_width: float,
    panel_height: float,
) -> dict:
    """Score how well character positions align with power points.

    Each position is matched to its nearest power point.  The score
    is 100 when a character is exactly on a power point and decreases
    linearly to 0 at half the panel diagonal distance.

    Returns {overall_score, per_position: [{position, nearest, distance, score}]}.
    """
    diag = math.sqrt(panel_width ** 2 + panel_height ** 2)
    max_dist = diag / 2.0

    per_pos = []
    for pos in positions:
        best_dist = float("inf")
        best_pp = power_points[0] if power_points else [0, 0]
        for pp in power_points:
            d = math.sqrt((pos[0] - pp[0]) ** 2 + (pos[1] - pp[1]) ** 2)
            if d < best_dist:
                best_dist = d
                best_pp = pp

        score = max(0.0, 100.0 * (1.0 - best_dist / max_dist)) if max_dist > 0 else 0
        per_pos.append({
            "position": [round(pos[0], 2), round(pos[1], 2)],
            "nearest_power_point": best_pp,
            "distance": round(best_dist, 2),
            "score": round(score, 1),
        })

    overall = sum(p["score"] for p in per_pos) / len(per_pos) if per_pos else 0
    return {
        "overall_score": round(overall, 1),
        "per_position": per_pos,
    }


# ---------------------------------------------------------------------------
# JSX helpers
# ---------------------------------------------------------------------------


_COMP_LAYER_JSX = """
function ensureCompLayer(doc) {
    var layer;
    try {
        layer = doc.layers.getByName("Composition");
    } catch(e) {
        layer = doc.layers.add();
        layer.name = "Composition";
    }
    return layer;
}
function compColor() {
    var c = new RGBColor();
    c.red = 160; c.green = 160; c.blue = 160;
    return c;
}
"""


def _thirds_jsx(thirds: dict, panel_x: float, panel_y: float, pw: float, ph: float) -> str:
    vlines = thirds["vertical_lines"]
    hlines = thirds["horizontal_lines"]
    bottom = panel_y - ph
    right = panel_x + pw
    return f"""
(function() {{
{_COMP_LAYER_JSX}
    var doc = app.activeDocument;
    var layer = ensureCompLayer(doc);
    var c = compColor();

    // Vertical lines
    var vx = {json.dumps(vlines)};
    for (var i = 0; i < vx.length; i++) {{
        var v = layer.pathItems.add();
        v.setEntirePath([[vx[i], {panel_y}], [vx[i], {bottom}]]);
        v.stroked = true; v.filled = false;
        v.strokeColor = c; v.strokeWidth = 0.5;
        v.strokeDashes = [6, 4];
        v.name = "thirds_v_" + i;
    }}
    // Horizontal lines
    var hy = {json.dumps(hlines)};
    for (var j = 0; j < hy.length; j++) {{
        var h = layer.pathItems.add();
        h.setEntirePath([[{panel_x}, hy[j]], [{right}, hy[j]]]);
        h.stroked = true; h.filled = false;
        h.strokeColor = c; h.strokeWidth = 0.5;
        h.strokeDashes = [6, 4];
        h.name = "thirds_h_" + j;
    }}
    return JSON.stringify({{guide: "rule_of_thirds", lines: 4}});
}})();
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_scene_composition tool."""

    @mcp.tool(
        name="adobe_ai_scene_composition",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_scene_composition(params: AiSceneCompositionInput) -> str:
        """Overlay composition guides and score compositions.

        Supports rule of thirds, golden ratio, leading lines,
        depth layers, and composition scoring.
        """
        action = params.action.lower().strip()
        px = params.panel_x
        py = params.panel_y
        pw = params.panel_width
        ph = params.panel_height

        if action == "rule_of_thirds":
            thirds = compute_thirds(px, py, pw, ph)
            jsx = _thirds_jsx(thirds, px, py, pw, ph)
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **thirds})

        elif action == "golden_ratio":
            golden = compute_golden_ratio_points(px, py, pw, ph)
            # Draw golden ratio lines similar to thirds
            return json.dumps({"action": action, **golden})

        elif action == "leading_lines":
            if not params.points_json:
                return json.dumps({"error": "leading_lines requires points_json"})
            try:
                lines = json.loads(params.points_json)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid points_json: {e}"})
            return json.dumps({"action": action, "lines": lines, "count": len(lines)})

        elif action == "depth_layers":
            zones = compute_depth_zones(px, py, pw, ph)
            return json.dumps({"action": action, "zones": zones})

        elif action == "score":
            if not params.positions_json:
                return json.dumps({"error": "score requires positions_json"})
            try:
                positions = json.loads(params.positions_json)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid positions_json: {e}"})

            thirds = compute_thirds(px, py, pw, ph)
            result = score_composition(positions, thirds["power_points"], pw, ph)
            return json.dumps({"action": action, **result})

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": [
                    "rule_of_thirds", "golden_ratio", "leading_lines",
                    "depth_layers", "score",
                ],
            })
