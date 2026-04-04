"""Overlay landmarks, axes, pivots, and hierarchy on artwork.

Generates JSX code that draws debug visualization overlays in Adobe
Illustrator on a dedicated "Debug" layer. Supports mode filtering
for landmarks, axes, pivots, hierarchy lines, or all at once.

Pure Python generates JSX strings; MCP tool dispatches to Illustrator.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiVisualDebuggerInput(BaseModel):
    """Generate debug overlay visualizations for character rigs."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: generate_overlay, clear_debug",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    mode: str = Field(
        default="all",
        description="Overlay mode: landmarks, axes, pivots, hierarchy, all",
    )


# ---------------------------------------------------------------------------
# JSX generation constants
# ---------------------------------------------------------------------------

_COLORS = {
    "landmark": [255, 0, 0],       # Red circles
    "axis_primary": [0, 0, 255],    # Blue arrows
    "axis_cross": [0, 200, 0],      # Green arrows
    "pivot": [255, 165, 0],         # Orange diamonds
    "hierarchy": [128, 128, 128],   # Gray lines
    "label": [0, 0, 0],            # Black text
}

_LANDMARK_RADIUS = 5.0
_PIVOT_SIZE = 8.0
_ARROW_LENGTH = 30.0
_LABEL_FONT_SIZE = 8


# ---------------------------------------------------------------------------
# JSX generators for each mode
# ---------------------------------------------------------------------------


def _jsx_header() -> str:
    """JSX preamble: create or find the Debug layer."""
    return """
// --- Debug Overlay ---
var doc = app.activeDocument;
var debugLayer;
try {
    debugLayer = doc.layers.getByName("Debug");
} catch(e) {
    debugLayer = doc.layers.add();
    debugLayer.name = "Debug";
}
debugLayer.visible = true;

function makeColor(r, g, b) {
    var c = new RGBColor();
    c.red = r; c.green = g; c.blue = b;
    return c;
}
"""


def _jsx_landmark(name: str, x: float, y: float) -> str:
    """JSX to draw a circle at a landmark position with a label."""
    r, g, b = _COLORS["landmark"]
    return f"""
// Landmark: {name}
(function() {{
    var circle = debugLayer.pathItems.ellipse(
        {-y + _LANDMARK_RADIUS}, {x - _LANDMARK_RADIUS},
        {_LANDMARK_RADIUS * 2}, {_LANDMARK_RADIUS * 2}
    );
    circle.filled = true;
    circle.fillColor = makeColor({r}, {g}, {b});
    circle.stroked = false;
    circle.name = "debug_landmark_{name}";

    var label = debugLayer.textFrames.add();
    label.contents = "{name}";
    label.position = [{x + _LANDMARK_RADIUS + 2}, {-y}];
    label.textRange.characterAttributes.size = {_LABEL_FONT_SIZE};
    label.textRange.characterAttributes.fillColor = makeColor(0, 0, 0);
    label.name = "debug_label_{name}";
}})();
"""


def _jsx_axis(name: str, x: float, y: float, dx: float, dy: float, is_primary: bool) -> str:
    """JSX to draw an arrow showing an axis direction."""
    color_key = "axis_primary" if is_primary else "axis_cross"
    r, g, b = _COLORS[color_key]
    x2 = x + dx * _ARROW_LENGTH
    y2 = y + dy * _ARROW_LENGTH
    return f"""
// Axis: {name} ({'primary' if is_primary else 'cross'})
(function() {{
    var line = debugLayer.pathItems.add();
    line.setEntirePath([[{x}, {-y}], [{x2}, {-y2}]]);
    line.filled = false;
    line.stroked = true;
    line.strokeColor = makeColor({r}, {g}, {b});
    line.strokeWidth = 2;
    line.name = "debug_axis_{name}";
}})();
"""


def _jsx_pivot(name: str, x: float, y: float) -> str:
    """JSX to draw a diamond marker at a pivot point."""
    r, g, b = _COLORS["pivot"]
    s = _PIVOT_SIZE
    return f"""
// Pivot: {name}
(function() {{
    var diamond = debugLayer.pathItems.add();
    diamond.setEntirePath([
        [{x}, {-y + s}], [{x + s}, {-y}],
        [{x}, {-y - s}], [{x - s}, {-y}]
    ]);
    diamond.closed = true;
    diamond.filled = true;
    diamond.fillColor = makeColor({r}, {g}, {b});
    diamond.stroked = true;
    diamond.strokeColor = makeColor(0, 0, 0);
    diamond.strokeWidth = 1;
    diamond.name = "debug_pivot_{name}";
}})();
"""


def _jsx_hierarchy_line(parent_name: str, child_name: str, x1: float, y1: float, x2: float, y2: float) -> str:
    """JSX to draw a line from parent to child with an arrow indicator."""
    r, g, b = _COLORS["hierarchy"]
    return f"""
// Hierarchy: {parent_name} -> {child_name}
(function() {{
    var line = debugLayer.pathItems.add();
    line.setEntirePath([[{x1}, {-y1}], [{x2}, {-y2}]]);
    line.filled = false;
    line.stroked = true;
    line.strokeColor = makeColor({r}, {g}, {b});
    line.strokeWidth = 1;
    line.strokeDashes = [4, 2];
    line.name = "debug_hierarchy_{parent_name}_to_{child_name}";
}})();
"""


def _jsx_clear() -> str:
    """JSX to remove the Debug layer entirely."""
    return """
// Clear Debug Overlay
var doc = app.activeDocument;
try {
    var debugLayer = doc.layers.getByName("Debug");
    debugLayer.remove();
} catch(e) {
    // Debug layer doesn't exist, nothing to clear
}
"""


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def generate_debug_overlay(rig: dict, mode: str = "all") -> str:
    """Generate JSX code to draw debug visualization overlays.

    Modes:
        - landmarks: circles at each landmark position with labels
        - axes: arrows showing primary/cross axes
        - pivots: diamond markers at pivot points
        - hierarchy: lines connecting parent->child
        - all: everything

    Args:
        rig: character rig dict
        mode: visualization mode

    Returns:
        JSX code string ready for execution in Illustrator.
    """
    valid_modes = {"landmarks", "axes", "pivots", "hierarchy", "all"}
    if mode not in valid_modes:
        mode = "all"

    jsx_parts = [_jsx_header()]

    landmarks = rig.get("landmarks", {})
    joints = rig.get("joints", {})
    axes = rig.get("axes", {})
    bones = rig.get("bones", [])

    show_landmarks = mode in ("landmarks", "all")
    show_axes = mode in ("axes", "all")
    show_pivots = mode in ("pivots", "all")
    show_hierarchy = mode in ("hierarchy", "all")

    # Draw landmarks
    if show_landmarks:
        for name, data in landmarks.items():
            pos = data.get("position", data.get("pos", [0, 0]))
            if len(pos) >= 2:
                jsx_parts.append(_jsx_landmark(name, pos[0], pos[1]))
        # Also draw joints as landmarks
        for name, data in joints.items():
            pos = data.get("position", [0, 0])
            if len(pos) >= 2:
                jsx_parts.append(_jsx_landmark(name, pos[0], pos[1]))

    # Draw axes
    if show_axes:
        for name, data in axes.items():
            pos = data.get("origin", [0, 0])
            direction = data.get("direction", [1, 0])
            if len(pos) >= 2 and len(direction) >= 2:
                jsx_parts.append(_jsx_axis(name, pos[0], pos[1], direction[0], direction[1], True))
                # Cross axis (perpendicular)
                jsx_parts.append(_jsx_axis(
                    f"{name}_cross", pos[0], pos[1],
                    -direction[1], direction[0], False
                ))

    # Draw pivots
    if show_pivots:
        for name, data in landmarks.items():
            pivot = data.get("pivot")
            if pivot:
                pos = data.get("position", data.get("pos", [0, 0]))
                if len(pos) >= 2:
                    jsx_parts.append(_jsx_pivot(name, pos[0], pos[1]))

    # Draw hierarchy lines
    if show_hierarchy:
        # Build position lookup from joints and landmarks
        positions = {}
        for name, data in joints.items():
            pos = data.get("position", [0, 0])
            positions[name] = pos
        for name, data in landmarks.items():
            pos = data.get("position", data.get("pos", [0, 0]))
            positions[name] = pos

        # Draw lines from parent to child joints along bones
        for bone in bones:
            parent = bone.get("parent_joint", "")
            child = bone.get("child_joint", "")
            if parent in positions and child in positions:
                p1 = positions[parent]
                p2 = positions[child]
                if len(p1) >= 2 and len(p2) >= 2:
                    jsx_parts.append(_jsx_hierarchy_line(parent, child, p1[0], p1[1], p2[0], p2[1]))

    return "\n".join(jsx_parts)


def clear_debug(rig: dict) -> str:
    """Generate JSX to remove the debug overlay layer.

    Args:
        rig: character rig dict (unused but kept for API consistency)

    Returns:
        JSX code string to clear the Debug layer.
    """
    return _jsx_clear()


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_visual_debugger tool."""

    @mcp.tool(
        name="adobe_ai_visual_debugger",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_visual_debugger(params: AiVisualDebuggerInput) -> str:
        """Generate debug overlay visualizations for character rigs.

        Actions:
        - generate_overlay: create JSX for landmark/axis/pivot/hierarchy display
        - clear_debug: remove the Debug layer
        """
        action = params.action.lower().strip()
        rig = _load_rig(params.character_name)

        if action == "generate_overlay":
            jsx = generate_debug_overlay(rig, params.mode)
            return json.dumps({
                "jsx": jsx,
                "mode": params.mode,
                "character_name": params.character_name,
            })

        elif action == "clear_debug":
            jsx = clear_debug(rig)
            return json.dumps({
                "jsx": jsx,
                "character_name": params.character_name,
            })

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
