"""Place simple construction forms (circles, boxes, cylinders) from landmarks.

Artists build up from simple shapes before adding detail.  This tool draws
lightweight construction geometry on a dedicated "Construction" layer using
dashed, light-blue strokes so the forms are clearly distinguishable from
final line art.

Actions:
    draw_head_circle  – circle from head_top → chin midpoint
    draw_body_box     – rectangle from shoulder_l→shoulder_r × shoulder_y→hip_y
    draw_limb_cylinder – ellipse between two joint landmarks
    draw_all          – draw all construction forms for a character
    clear             – remove the Construction layer
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiConstructionDrawInput(BaseModel):
    """Draw construction forms from character landmarks."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: draw_head_circle, draw_body_box, draw_limb_cylinder, draw_all, clear",
    )
    character_name: str = Field(default="character", description="Character identifier")
    landmark_a: str = Field(default="", description="First landmark name (for limb_cylinder)")
    landmark_b: str = Field(default="", description="Second landmark name (for limb_cylinder)")


# ---------------------------------------------------------------------------
# Pure-Python geometry helpers
# ---------------------------------------------------------------------------


def _midpoint(a: list, b: list) -> list:
    """Return the midpoint between two [x, y] positions."""
    return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]


def _distance(a: list, b: list) -> float:
    """Euclidean distance between two [x, y] positions."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def compute_head_circle(landmarks: dict) -> dict:
    """Compute circle centre and diameter from head_top and chin landmarks.

    Returns {center: [x, y], diameter: float} or {error: str}.
    """
    head = landmarks.get("head_top")
    chin = landmarks.get("chin")
    if not head or "ai" not in head:
        return {"error": "Missing head_top landmark"}
    if not chin or "ai" not in chin:
        return {"error": "Missing chin landmark"}
    center = _midpoint(head["ai"], chin["ai"])
    diameter = _distance(head["ai"], chin["ai"])
    return {"center": center, "diameter": round(diameter, 2)}


def compute_body_box(landmarks: dict) -> dict:
    """Compute body bounding rectangle from shoulders and hips.

    Returns {left, top, width, height} in AI coordinates.
    """
    sl = landmarks.get("shoulder_l")
    sr = landmarks.get("shoulder_r")
    hc = landmarks.get("hip_center")
    if not sl or "ai" not in sl:
        return {"error": "Missing shoulder_l landmark"}
    if not sr or "ai" not in sr:
        return {"error": "Missing shoulder_r landmark"}
    if not hc or "ai" not in hc:
        return {"error": "Missing hip_center landmark"}

    left_x = min(sl["ai"][0], sr["ai"][0])
    right_x = max(sl["ai"][0], sr["ai"][0])
    # In AI coords Y increases upward; shoulder is above hip
    shoulder_y = max(sl["ai"][1], sr["ai"][1])
    hip_y = hc["ai"][1]
    top = max(shoulder_y, hip_y)
    bottom = min(shoulder_y, hip_y)
    width = right_x - left_x
    height = abs(top - bottom)
    return {
        "left": round(left_x, 2),
        "top": round(top, 2),
        "width": round(width, 2),
        "height": round(height, 2),
    }


def compute_limb_cylinder(landmarks: dict, name_a: str, name_b: str) -> dict:
    """Compute an ellipse representing a limb cylinder between two landmarks.

    The ellipse is centred between the two joints with its major axis equal
    to the inter-joint distance and its minor axis at 30 % of the major.

    Returns {center, major, minor, angle_deg}.
    """
    la = landmarks.get(name_a)
    lb = landmarks.get(name_b)
    if not la or "ai" not in la:
        return {"error": f"Missing landmark: {name_a}"}
    if not lb or "ai" not in lb:
        return {"error": f"Missing landmark: {name_b}"}

    center = _midpoint(la["ai"], lb["ai"])
    major = _distance(la["ai"], lb["ai"])
    minor = major * 0.3
    dx = lb["ai"][0] - la["ai"][0]
    dy = lb["ai"][1] - la["ai"][1]
    angle_deg = math.degrees(math.atan2(dy, dx))
    return {
        "center": [round(center[0], 2), round(center[1], 2)],
        "major": round(major, 2),
        "minor": round(minor, 2),
        "angle_deg": round(angle_deg, 2),
    }


# ---------------------------------------------------------------------------
# Construction-layer JSX (dashed light-blue strokes)
# ---------------------------------------------------------------------------


_CONSTRUCTION_LAYER_JSX = """
function ensureConstructionLayer(doc) {
    var layer;
    try {
        layer = doc.layers.getByName("Construction");
    } catch(e) {
        layer = doc.layers.add();
        layer.name = "Construction";
    }
    return layer;
}
function constructionColor() {
    var c = new RGBColor();
    c.red = 135; c.green = 206; c.blue = 235;
    return c;
}
"""


def _circle_jsx(cx: float, cy: float, diameter: float) -> str:
    r = diameter / 2.0
    return f"""
(function() {{
{_CONSTRUCTION_LAYER_JSX}
    var doc = app.activeDocument;
    var layer = ensureConstructionLayer(doc);
    var ell = layer.pathItems.ellipse(
        {cy + r}, {cx - r}, {diameter}, {diameter}
    );
    ell.name = "construction_head_circle";
    ell.filled = false;
    ell.stroked = true;
    ell.strokeColor = constructionColor();
    ell.strokeWidth = 1;
    ell.strokeDashes = [6, 4];
    return JSON.stringify({{shape: "head_circle", cx: {cx}, cy: {cy}, diameter: {diameter}}});
}})();
"""


def _rect_jsx(left: float, top: float, width: float, height: float) -> str:
    return f"""
(function() {{
{_CONSTRUCTION_LAYER_JSX}
    var doc = app.activeDocument;
    var layer = ensureConstructionLayer(doc);
    var rect = layer.pathItems.rectangle({top}, {left}, {width}, {height});
    rect.name = "construction_body_box";
    rect.filled = false;
    rect.stroked = true;
    rect.strokeColor = constructionColor();
    rect.strokeWidth = 1;
    rect.strokeDashes = [6, 4];
    return JSON.stringify({{shape: "body_box", left: {left}, top: {top}, width: {width}, height: {height}}});
}})();
"""


def _ellipse_jsx(cx: float, cy: float, major: float, minor: float, angle_deg: float) -> str:
    # AI ellipse is axis-aligned; we approximate by drawing an ellipse then rotating
    return f"""
(function() {{
{_CONSTRUCTION_LAYER_JSX}
    var doc = app.activeDocument;
    var layer = ensureConstructionLayer(doc);
    var ell = layer.pathItems.ellipse(
        {cy + minor / 2.0}, {cx - major / 2.0}, {major}, {minor}
    );
    ell.name = "construction_limb_cylinder";
    ell.filled = false;
    ell.stroked = true;
    ell.strokeColor = constructionColor();
    ell.strokeWidth = 1;
    ell.strokeDashes = [6, 4];
    ell.rotate({angle_deg});
    return JSON.stringify({{shape: "limb_cylinder", cx: {cx}, cy: {cy}, major: {major}, minor: {minor}, angle: {angle_deg}}});
}})();
"""


_CLEAR_JSX = """
(function() {
    var doc = app.activeDocument;
    try {
        var layer = doc.layers.getByName("Construction");
        layer.remove();
        return JSON.stringify({cleared: true});
    } catch(e) {
        return JSON.stringify({cleared: false, note: "Construction layer not found"});
    }
})();
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_construction_draw tool."""

    @mcp.tool(
        name="adobe_ai_construction_draw",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_construction_draw(params: AiConstructionDrawInput) -> str:
        """Place construction forms (circles, boxes, cylinders) from character landmarks.

        Draws on a 'Construction' layer with dashed light-blue strokes so the
        forms are clearly distinguishable from final line art.
        """
        rig = _load_rig(params.character_name)
        landmarks = rig.get("landmarks", {})
        action = params.action.lower().strip()

        if action == "draw_head_circle":
            info = compute_head_circle(landmarks)
            if "error" in info:
                return json.dumps(info)
            jsx = _circle_jsx(info["center"][0], info["center"][1], info["diameter"])
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **info})

        elif action == "draw_body_box":
            info = compute_body_box(landmarks)
            if "error" in info:
                return json.dumps(info)
            jsx = _rect_jsx(info["left"], info["top"], info["width"], info["height"])
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **info})

        elif action == "draw_limb_cylinder":
            if not params.landmark_a or not params.landmark_b:
                return json.dumps({"error": "draw_limb_cylinder requires landmark_a and landmark_b"})
            info = compute_limb_cylinder(landmarks, params.landmark_a, params.landmark_b)
            if "error" in info:
                return json.dumps(info)
            jsx = _ellipse_jsx(
                info["center"][0], info["center"][1],
                info["major"], info["minor"], info["angle_deg"],
            )
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **info})

        elif action == "draw_all":
            results = []
            # Head circle
            hc = compute_head_circle(landmarks)
            if "error" not in hc:
                jsx = _circle_jsx(hc["center"][0], hc["center"][1], hc["diameter"])
                await _async_run_jsx("illustrator", jsx)
                results.append({"shape": "head_circle", **hc})

            # Body box
            bb = compute_body_box(landmarks)
            if "error" not in bb:
                jsx = _rect_jsx(bb["left"], bb["top"], bb["width"], bb["height"])
                await _async_run_jsx("illustrator", jsx)
                results.append({"shape": "body_box", **bb})

            # Limb cylinders for standard pairs
            limb_pairs = [
                ("shoulder_l", "elbow_l"),
                ("shoulder_r", "elbow_r"),
                ("elbow_l", "wrist_l"),
                ("elbow_r", "wrist_r"),
                ("hip_l", "knee_l"),
                ("hip_r", "knee_r"),
                ("knee_l", "ankle_l"),
                ("knee_r", "ankle_r"),
            ]
            for la, lb in limb_pairs:
                lc = compute_limb_cylinder(landmarks, la, lb)
                if "error" not in lc:
                    jsx = _ellipse_jsx(
                        lc["center"][0], lc["center"][1],
                        lc["major"], lc["minor"], lc["angle_deg"],
                    )
                    await _async_run_jsx("illustrator", jsx)
                    results.append({"shape": "limb_cylinder", "from": la, "to": lb, **lc})

            return json.dumps({"action": "draw_all", "forms": results, "count": len(results)})

        elif action == "clear":
            result = await _async_run_jsx("illustrator", _CLEAR_JSX)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return result["stdout"]

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["draw_head_circle", "draw_body_box", "draw_limb_cylinder", "draw_all", "clear"],
            })
