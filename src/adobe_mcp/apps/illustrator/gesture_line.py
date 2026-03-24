"""Capture the energy/flow of a pose as single sweeping curves.

Given a chain of landmark names the tool draws one smooth flowing bezier
curve through all the landmark positions.  Handle directions at each point
aim toward the NEXT landmark in the chain so the curve carries visual
momentum in the reading direction.

Drawn on a "Gesture" layer with thick red strokes and no fill.
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiGestureLineInput(BaseModel):
    """Draw gesture lines through landmark chains."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: draw_gesture, clear",
    )
    character_name: str = Field(default="character", description="Character identifier")
    chain: str = Field(
        default="",
        description="Comma-separated landmark names for the gesture curve (e.g. 'head_top,spine_mid,hip_center,knee_r,ankle_r')",
    )
    stroke_width: float = Field(default=3.0, description="Stroke width for gesture line", ge=0.5)
    handle_strength: float = Field(
        default=0.33,
        description="Handle length as fraction of distance to next point (0..1)",
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Pure-Python handle computation
# ---------------------------------------------------------------------------


def compute_gesture_handles(
    points: list[list[float]],
    strength: float = 0.33,
) -> list[dict]:
    """Compute bezier handle positions for a flowing gesture curve.

    Each handle pair aims toward the NEXT point in the chain so the
    curve carries visual momentum.  The first and last points get
    slightly shortened handles.

    Parameters
    ----------
    points : list of [x, y]
        Ordered anchor positions along the gesture curve.
    strength : float
        How far handles extend as a fraction of the inter-point distance.

    Returns
    -------
    list of {anchor, handle_in, handle_out}
        One entry per point.  handle_in and handle_out are [x, y].
    """
    n = len(points)
    if n == 0:
        return []
    if n == 1:
        return [{"anchor": points[0], "handle_in": list(points[0]), "handle_out": list(points[0])}]

    result = []

    for i in range(n):
        anchor = points[i]

        if i == 0:
            # First point — out-handle points toward next
            dx = points[i + 1][0] - anchor[0]
            dy = points[i + 1][1] - anchor[1]
            d = math.sqrt(dx * dx + dy * dy) or 1.0
            out_len = d * strength
            out_x = anchor[0] + (dx / d) * out_len
            out_y = anchor[1] + (dy / d) * out_len
            result.append({
                "anchor": list(anchor),
                "handle_in": list(anchor),  # no in-handle on first point
                "handle_out": [round(out_x, 3), round(out_y, 3)],
            })

        elif i == n - 1:
            # Last point — in-handle points back from previous
            dx = points[i - 1][0] - anchor[0]
            dy = points[i - 1][1] - anchor[1]
            d = math.sqrt(dx * dx + dy * dy) or 1.0
            in_len = d * strength
            in_x = anchor[0] + (dx / d) * in_len
            in_y = anchor[1] + (dy / d) * in_len
            result.append({
                "anchor": list(anchor),
                "handle_in": [round(in_x, 3), round(in_y, 3)],
                "handle_out": list(anchor),  # no out-handle on last point
            })

        else:
            # Middle points — handles aligned along prev→next direction
            prev = points[i - 1]
            nxt = points[i + 1]
            dx = nxt[0] - prev[0]
            dy = nxt[1] - prev[1]
            d = math.sqrt(dx * dx + dy * dy) or 1.0
            ux, uy = dx / d, dy / d

            # Distance to neighbours determines handle length
            d_prev = math.sqrt(
                (anchor[0] - prev[0]) ** 2 + (anchor[1] - prev[1]) ** 2
            )
            d_next = math.sqrt(
                (anchor[0] - nxt[0]) ** 2 + (anchor[1] - nxt[1]) ** 2
            )

            in_len = d_prev * strength
            out_len = d_next * strength

            in_x = anchor[0] - ux * in_len
            in_y = anchor[1] - uy * in_len
            out_x = anchor[0] + ux * out_len
            out_y = anchor[1] + uy * out_len

            result.append({
                "anchor": list(anchor),
                "handle_in": [round(in_x, 3), round(in_y, 3)],
                "handle_out": [round(out_x, 3), round(out_y, 3)],
            })

    return result


# ---------------------------------------------------------------------------
# JSX helpers
# ---------------------------------------------------------------------------


_GESTURE_LAYER_JSX = """
function ensureGestureLayer(doc) {
    var layer;
    try {
        layer = doc.layers.getByName("Gesture");
    } catch(e) {
        layer = doc.layers.add();
        layer.name = "Gesture";
    }
    return layer;
}
"""

_CLEAR_JSX = """
(function() {
    var doc = app.activeDocument;
    try {
        var layer = doc.layers.getByName("Gesture");
        layer.remove();
        return JSON.stringify({cleared: true});
    } catch(e) {
        return JSON.stringify({cleared: false, note: "Gesture layer not found"});
    }
})();
"""


def _draw_gesture_jsx(handles: list[dict], stroke_width: float) -> str:
    """Build JSX to draw a flowing gesture curve with bezier handles."""
    anchors_js = json.dumps([h["anchor"] for h in handles])
    handles_js = json.dumps(handles)
    return f"""
(function() {{
{_GESTURE_LAYER_JSX}
    var doc = app.activeDocument;
    var layer = ensureGestureLayer(doc);
    var handles = {handles_js};
    var path = layer.pathItems.add();
    path.name = "gesture_line";
    path.setEntirePath({anchors_js});
    path.closed = false;
    path.filled = false;
    path.stroked = true;
    var sc = new RGBColor();
    sc.red = 220; sc.green = 50; sc.blue = 50;
    path.strokeColor = sc;
    path.strokeWidth = {stroke_width};
    // Apply bezier handles
    for (var i = 0; i < path.pathPoints.length && i < handles.length; i++) {{
        path.pathPoints[i].leftDirection = handles[i].handle_in;
        path.pathPoints[i].rightDirection = handles[i].handle_out;
    }}
    return JSON.stringify({{
        name: path.name,
        point_count: path.pathPoints.length,
        stroke_width: {stroke_width}
    }});
}})();
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_gesture_line tool."""

    @mcp.tool(
        name="adobe_ai_gesture_line",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_gesture_line(params: AiGestureLineInput) -> str:
        """Draw gesture lines through character landmark chains.

        Creates smooth flowing bezier curves through landmark positions
        to capture the energy and flow of a pose.
        """
        action = params.action.lower().strip()

        if action == "draw_gesture":
            if not params.chain:
                return json.dumps({"error": "draw_gesture requires a 'chain' of comma-separated landmark names"})

            rig = _load_rig(params.character_name)
            landmarks = rig.get("landmarks", {})

            names = [n.strip() for n in params.chain.split(",") if n.strip()]
            if len(names) < 2:
                return json.dumps({"error": "Gesture chain must contain at least 2 landmark names"})

            # Resolve landmarks to AI coordinates
            points = []
            missing = []
            for name in names:
                lm = landmarks.get(name)
                if not lm or "ai" not in lm:
                    missing.append(name)
                else:
                    points.append(lm["ai"])

            if missing:
                return json.dumps({
                    "error": f"Missing landmarks: {missing}",
                    "available": list(landmarks.keys()),
                })

            handles = compute_gesture_handles(points, params.handle_strength)
            jsx = _draw_gesture_jsx(handles, params.stroke_width)
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})

            return json.dumps({
                "action": "draw_gesture",
                "chain": names,
                "point_count": len(points),
                "handles": handles,
            })

        elif action == "clear":
            result = await _async_run_jsx("illustrator", _CLEAR_JSX)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return result["stdout"]

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["draw_gesture", "clear"],
            })
