"""Draw light direction indicators on storyboard panels.

Renders key, fill, and rim light arrows/arcs on a dedicated "Lighting"
layer within each panel.  Lighting metadata is stored in the rig file
under `lighting` keyed by panel number.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiLightingNotationInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# Direction name → angle in degrees (0° = right, counter-clockwise)
DIRECTION_ANGLES = {
    "right": 0,
    "top_right": 45,
    "top": 90,
    "top_left": 135,
    "left": 180,
    "bottom_left": 225,
    "bottom": 270,
    "bottom_right": 315,
    "front": 90,
    "back": 270,
}

# Mood → background tint RGB
MOOD_TINTS = {
    "bright": (240, 240, 235),
    "moody": (60, 55, 70),
    "dramatic": (30, 25, 40),
    "silhouette": (20, 15, 25),
    "noir": (10, 10, 10),
}

# Default panel dimensions (must match storyboard_panel.py)
PANEL_WIDTH = 960
PANEL_HEIGHT = 540


def direction_to_angle(direction: str) -> float:
    """Convert a named direction to an angle in degrees.

    Returns 0 for unrecognised directions.
    """
    return DIRECTION_ANGLES.get(direction.lower().strip(), 0)


def _ensure_lighting(rig: dict) -> dict:
    """Ensure the rig has a lighting structure."""
    if "lighting" not in rig:
        rig["lighting"] = {}
    return rig


def register(mcp):
    """Register the adobe_ai_lighting_notation tool."""

    @mcp.tool(
        name="adobe_ai_lighting_notation",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_lighting_notation(params: AiLightingNotationInput) -> str:
        """Add key/fill/rim light direction indicators and mood tints to panels.

        Draws directional arrows for key and fill lights, an arc for rim
        light, and optionally tints the panel background to convey mood.
        """
        panel_num = params.panel_number
        action = params.action.lower().strip()

        # Use a fixed character name for lighting storage since
        # lighting data is panel-scoped, not character-scoped
        character_name = "character"
        rig = _load_rig(character_name)
        rig = _ensure_lighting(rig)

        panel_key = str(panel_num)

        # ── clear ───────────────────────────────────────────────────
        if action == "clear":
            removed = panel_key in rig["lighting"]
            if removed:
                del rig["lighting"][panel_key]
                _save_rig(character_name, rig)

            # Remove Lighting layer items in Illustrator
            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    try {{
        var layer = doc.layers.getByName("Lighting_{panel_num}");
        layer.remove();
        return JSON.stringify({{"cleared": true, "panel": {panel_num}}});
    }} catch(e) {{
        return JSON.stringify({{"cleared": false, "reason": "layer not found"}});
    }}
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "clear",
                "panel_number": panel_num,
                "removed_data": removed,
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── set ─────────────────────────────────────────────────────
        elif action == "set":
            # Store lighting data
            lighting_data = {}
            if params.key_direction:
                lighting_data["key"] = params.key_direction
            if params.fill_direction:
                lighting_data["fill"] = params.fill_direction
            lighting_data["rim"] = params.rim
            if params.mood:
                lighting_data["mood"] = params.mood

            rig["lighting"][panel_key] = lighting_data
            _save_rig(character_name, rig)

            # Build JSX to draw lighting indicators
            # Panel center (approximate — assumes panels are laid out horizontally)
            panel_gap = 40
            panel_idx = panel_num - 1
            ab_left = (PANEL_WIDTH + panel_gap) * panel_idx
            ab_top = 0
            cx = ab_left + PANEL_WIDTH / 2
            cy = ab_top - PANEL_HEIGHT / 2
            arrow_len = 60  # arrow length in points

            jsx_parts = [f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create Lighting layer for this panel
    var lightLayer;
    try {{
        lightLayer = doc.layers.getByName("Lighting_{panel_num}");
        // Clear existing items
        while (lightLayer.pageItems.length > 0) {{
            lightLayer.pageItems[0].remove();
        }}
    }} catch(e) {{
        lightLayer = doc.layers.add();
        lightLayer.name = "Lighting_{panel_num}";
    }}
"""]

            # Key light arrow
            if params.key_direction:
                angle_deg = direction_to_angle(params.key_direction)
                angle_rad = math.radians(angle_deg)
                # Arrow starts from edge, pointing toward center
                start_x = cx + arrow_len * math.cos(angle_rad)
                start_y = cy + arrow_len * math.sin(angle_rad)

                jsx_parts.append(f"""
    // Key light arrow
    var keyPath = lightLayer.pathItems.add();
    keyPath.name = "key_light_{panel_num}";
    keyPath.setEntirePath([[{start_x}, {start_y}], [{cx}, {cy}]]);
    keyPath.filled = false;
    keyPath.stroked = true;
    keyPath.strokeWidth = 3;
    var keyColor = new RGBColor();
    keyColor.red = 255; keyColor.green = 220; keyColor.blue = 50;
    keyPath.strokeColor = keyColor;

    // KEY label
    var keyLabel = lightLayer.textFrames.add();
    keyLabel.contents = "KEY";
    keyLabel.position = [{start_x - 15}, {start_y + 12}];
    keyLabel.textRange.characterAttributes.size = 8;
    keyLabel.textRange.characterAttributes.fillColor = keyColor;
""")

            # Fill light arrow (smaller)
            if params.fill_direction:
                fill_angle_deg = direction_to_angle(params.fill_direction)
                fill_angle_rad = math.radians(fill_angle_deg)
                fill_len = arrow_len * 0.6
                fill_start_x = cx + fill_len * math.cos(fill_angle_rad)
                fill_start_y = cy + fill_len * math.sin(fill_angle_rad)

                jsx_parts.append(f"""
    // Fill light arrow
    var fillPath = lightLayer.pathItems.add();
    fillPath.name = "fill_light_{panel_num}";
    fillPath.setEntirePath([[{fill_start_x}, {fill_start_y}], [{cx}, {cy}]]);
    fillPath.filled = false;
    fillPath.stroked = true;
    fillPath.strokeWidth = 1.5;
    var fillColor = new RGBColor();
    fillColor.red = 150; fillColor.green = 180; fillColor.blue = 255;
    fillPath.strokeColor = fillColor;

    // FILL label
    var fillLabel = lightLayer.textFrames.add();
    fillLabel.contents = "FILL";
    fillLabel.position = [{fill_start_x - 15}, {fill_start_y + 12}];
    fillLabel.textRange.characterAttributes.size = 7;
    fillLabel.textRange.characterAttributes.fillColor = fillColor;
""")

            # Rim light arc (opposite side of key)
            if params.rim:
                rim_angle = direction_to_angle(params.key_direction or "top_left") + 180
                rim_rad = math.radians(rim_angle)
                arc_radius = 30
                rim_cx = cx + (arrow_len * 0.7) * math.cos(rim_rad)
                rim_cy = cy + (arrow_len * 0.7) * math.sin(rim_rad)

                jsx_parts.append(f"""
    // Rim light arc
    var rimArc = lightLayer.pathItems.ellipse(
        {rim_cy + arc_radius}, {rim_cx - arc_radius},
        {arc_radius * 2}, {arc_radius * 2}
    );
    rimArc.name = "rim_light_{panel_num}";
    rimArc.filled = false;
    rimArc.stroked = true;
    rimArc.strokeWidth = 1;
    var rimColor = new RGBColor();
    rimColor.red = 255; rimColor.green = 150; rimColor.blue = 100;
    rimArc.strokeColor = rimColor;
    rimArc.strokeDashes = [3, 3];

    // RIM label
    var rimLabel = lightLayer.textFrames.add();
    rimLabel.contents = "RIM";
    rimLabel.position = [{rim_cx - 10}, {rim_cy + 10}];
    rimLabel.textRange.characterAttributes.size = 7;
    rimLabel.textRange.characterAttributes.fillColor = rimColor;
""")

            # Mood background tint
            if params.mood and params.mood in MOOD_TINTS:
                r, g, b = MOOD_TINTS[params.mood]
                jsx_parts.append(f"""
    // Mood background tint
    var moodRect = lightLayer.pathItems.rectangle(
        {ab_top}, {ab_left}, {PANEL_WIDTH}, {PANEL_HEIGHT}
    );
    moodRect.name = "mood_tint_{panel_num}";
    var moodColor = new RGBColor();
    moodColor.red = {r}; moodColor.green = {g}; moodColor.blue = {b};
    moodRect.fillColor = moodColor;
    moodRect.filled = true;
    moodRect.stroked = false;
    moodRect.opacity = 30;
    moodRect.move(lightLayer, ElementPlacement.PLACEATEND);
""")

            jsx_parts.append(f"""
    return JSON.stringify({{
        panel: {panel_num},
        lighting: {json.dumps(lighting_data)}
    }});
}})();
""")

            jsx = "\n".join(jsx_parts)
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "set",
                "panel_number": panel_num,
                "lighting": lighting_data,
                "jsx_success": result.get("success", False),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["set", "clear"],
            })
