"""Visual transition indicators between storyboard panels.

Draws small indicators in the gutter between adjacent panels to show
how one panel flows into the next.  Transition metadata is stored in
the rig file under `transitions` keyed by source panel number.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiTransitionPlannerInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# Valid transition types
VALID_TRANSITIONS = {
    "cut", "dissolve", "wipe_left", "wipe_right", "wipe_up", "wipe_down",
    "match_cut", "smash_cut", "fade_in", "fade_out", "iris",
}

# Default panel dimensions (match storyboard_panel.py)
PANEL_WIDTH = 960
PANEL_HEIGHT = 540
PANEL_GAP = 40


def _ensure_transitions(rig: dict) -> dict:
    """Ensure the rig has a transitions structure."""
    if "transitions" not in rig:
        rig["transitions"] = {}
    return rig


def register(mcp):
    """Register the adobe_ai_transition_planner tool."""

    @mcp.tool(
        name="adobe_ai_transition_planner",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_transition_planner(params: AiTransitionPlannerInput) -> str:
        """Draw transition indicators between storyboard panels.

        Supported transitions: cut, dissolve, wipe (directional),
        match_cut, smash_cut, fade_in, fade_out, iris.
        """
        panel_num = params.panel_number
        transition = params.transition.lower().strip()
        duration_frames = params.duration_frames

        if transition not in VALID_TRANSITIONS:
            return json.dumps({
                "error": f"Unknown transition: {transition}",
                "valid_transitions": sorted(VALID_TRANSITIONS),
            })

        # Store in rig data
        character_name = "character"
        rig = _load_rig(character_name)
        rig = _ensure_transitions(rig)

        panel_key = str(panel_num)
        rig["transitions"][panel_key] = {
            "type": transition,
            "duration_frames": duration_frames,
        }
        _save_rig(character_name, rig)

        # Calculate gutter position between panel N and panel N+1
        panel_idx = panel_num - 1
        gutter_left = (PANEL_WIDTH + PANEL_GAP) * panel_idx + PANEL_WIDTH
        gutter_center_x = gutter_left + PANEL_GAP / 2
        gutter_center_y = -(PANEL_HEIGHT / 2)  # vertical center of panels
        indicator_size = 24

        # Build JSX based on transition type
        jsx_parts = [f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create Transitions layer
    var transLayer;
    try {{
        transLayer = doc.layers.getByName("Transitions");
    }} catch(e) {{
        transLayer = doc.layers.add();
        transLayer.name = "Transitions";
    }}

    // Remove any existing indicator for this panel transition
    for (var i = transLayer.pageItems.length - 1; i >= 0; i--) {{
        if (transLayer.pageItems[i].name.indexOf("trans_{panel_num}_") === 0) {{
            transLayer.pageItems[i].remove();
        }}
    }}
"""]

        escaped_transition = escape_jsx_string(transition)

        if transition == "cut":
            # Simple "CUT" text
            jsx_parts.append(f"""
    var cutText = transLayer.textFrames.add();
    cutText.contents = "CUT";
    cutText.name = "trans_{panel_num}_cut";
    cutText.position = [{gutter_center_x - 12}, {gutter_center_y + 6}];
    cutText.textRange.characterAttributes.size = 9;
    var cutColor = new RGBColor();
    cutColor.red = 200; cutColor.green = 200; cutColor.blue = 200;
    cutText.textRange.characterAttributes.fillColor = cutColor;
""")

        elif transition == "dissolve":
            # Two overlapping circles
            jsx_parts.append(f"""
    var c1 = transLayer.pathItems.ellipse(
        {gutter_center_y + indicator_size/2}, {gutter_center_x - indicator_size/2 - 4},
        {indicator_size}, {indicator_size}
    );
    c1.name = "trans_{panel_num}_dissolve_1";
    c1.filled = true;
    var c1Color = new RGBColor();
    c1Color.red = 100; c1Color.green = 150; c1Color.blue = 255;
    c1.fillColor = c1Color;
    c1.opacity = 50;
    c1.stroked = false;

    var c2 = transLayer.pathItems.ellipse(
        {gutter_center_y + indicator_size/2}, {gutter_center_x - indicator_size/2 + 4},
        {indicator_size}, {indicator_size}
    );
    c2.name = "trans_{panel_num}_dissolve_2";
    c2.filled = true;
    var c2Color = new RGBColor();
    c2Color.red = 255; c2Color.green = 150; c2Color.blue = 100;
    c2.fillColor = c2Color;
    c2.opacity = 50;
    c2.stroked = false;
""")

        elif transition.startswith("wipe"):
            # Arrow showing wipe direction
            direction_map = {
                "wipe_left": (1, 0),
                "wipe_right": (-1, 0),
                "wipe_up": (0, -1),
                "wipe_down": (0, 1),
            }
            dx, dy = direction_map.get(transition, (1, 0))
            arrow_start_x = gutter_center_x - dx * 12
            arrow_start_y = gutter_center_y - dy * 12
            arrow_end_x = gutter_center_x + dx * 12
            arrow_end_y = gutter_center_y + dy * 12

            jsx_parts.append(f"""
    var wipePath = transLayer.pathItems.add();
    wipePath.name = "trans_{panel_num}_wipe";
    wipePath.setEntirePath([
        [{arrow_start_x}, {arrow_start_y}],
        [{arrow_end_x}, {arrow_end_y}]
    ]);
    wipePath.filled = false;
    wipePath.stroked = true;
    wipePath.strokeWidth = 2;
    var wipeColor = new RGBColor();
    wipeColor.red = 100; wipeColor.green = 200; wipeColor.blue = 100;
    wipePath.strokeColor = wipeColor;
""")

        elif transition == "match_cut":
            # "MATCH" text with a link icon (two small connected squares)
            jsx_parts.append(f"""
    var matchText = transLayer.textFrames.add();
    matchText.contents = "MATCH";
    matchText.name = "trans_{panel_num}_match";
    matchText.position = [{gutter_center_x - 16}, {gutter_center_y + 6}];
    matchText.textRange.characterAttributes.size = 8;
    var matchColor = new RGBColor();
    matchColor.red = 255; matchColor.green = 200; matchColor.blue = 50;
    matchText.textRange.characterAttributes.fillColor = matchColor;

    // Link icon: two small squares connected by a line
    var sq1 = transLayer.pathItems.rectangle(
        {gutter_center_y - 8}, {gutter_center_x - 8}, 6, 6
    );
    sq1.name = "trans_{panel_num}_match_link1";
    sq1.fillColor = matchColor;
    sq1.filled = true;
    sq1.stroked = false;

    var sq2 = transLayer.pathItems.rectangle(
        {gutter_center_y - 8}, {gutter_center_x + 2}, 6, 6
    );
    sq2.name = "trans_{panel_num}_match_link2";
    sq2.fillColor = matchColor;
    sq2.filled = true;
    sq2.stroked = false;

    var linkLine = transLayer.pathItems.add();
    linkLine.name = "trans_{panel_num}_match_line";
    linkLine.setEntirePath([
        [{gutter_center_x - 2}, {gutter_center_y - 5}],
        [{gutter_center_x + 2}, {gutter_center_y - 5}]
    ]);
    linkLine.stroked = true;
    linkLine.strokeWidth = 1;
    linkLine.strokeColor = matchColor;
    linkLine.filled = false;
""")

        elif transition in ("fade_in", "fade_out"):
            # Gradient rectangle
            jsx_parts.append(f"""
    var fadeRect = transLayer.pathItems.rectangle(
        {gutter_center_y + indicator_size/2}, {gutter_center_x - indicator_size/2},
        {indicator_size}, {indicator_size}
    );
    fadeRect.name = "trans_{panel_num}_fade";
    fadeRect.filled = true;
    var fadeColor = new RGBColor();
    fadeColor.red = 80; fadeColor.green = 80; fadeColor.blue = 80;
    fadeRect.fillColor = fadeColor;
    fadeRect.opacity = {"70" if transition == "fade_out" else "30"};
    fadeRect.stroked = true;
    fadeRect.strokeWidth = 0.5;

    var fadeLabel = transLayer.textFrames.add();
    fadeLabel.contents = "{"FADE OUT" if transition == "fade_out" else "FADE IN"}";
    fadeLabel.name = "trans_{panel_num}_fade_label";
    fadeLabel.position = [{gutter_center_x - 18}, {gutter_center_y - indicator_size/2 - 4}];
    fadeLabel.textRange.characterAttributes.size = 6;
""")

        elif transition == "smash_cut":
            jsx_parts.append(f"""
    var smashText = transLayer.textFrames.add();
    smashText.contents = "SMASH CUT";
    smashText.name = "trans_{panel_num}_smash";
    smashText.position = [{gutter_center_x - 22}, {gutter_center_y + 6}];
    smashText.textRange.characterAttributes.size = 8;
    var smashColor = new RGBColor();
    smashColor.red = 255; smashColor.green = 50; smashColor.blue = 50;
    smashText.textRange.characterAttributes.fillColor = smashColor;
""")

        elif transition == "iris":
            jsx_parts.append(f"""
    var irisCircle = transLayer.pathItems.ellipse(
        {gutter_center_y + indicator_size/2}, {gutter_center_x - indicator_size/2},
        {indicator_size}, {indicator_size}
    );
    irisCircle.name = "trans_{panel_num}_iris";
    irisCircle.filled = false;
    irisCircle.stroked = true;
    irisCircle.strokeWidth = 2;
    var irisColor = new RGBColor();
    irisColor.red = 200; irisColor.green = 100; irisColor.blue = 255;
    irisCircle.strokeColor = irisColor;
""")

        # Duration label for all transitions
        jsx_parts.append(f"""
    // Duration label
    var durLabel = transLayer.textFrames.add();
    durLabel.contents = "{duration_frames}f";
    durLabel.name = "trans_{panel_num}_duration";
    durLabel.position = [{gutter_center_x - 8}, {gutter_center_y - indicator_size/2 - 14}];
    durLabel.textRange.characterAttributes.size = 7;
    var durColor = new RGBColor();
    durColor.red = 160; durColor.green = 160; durColor.blue = 160;
    durLabel.textRange.characterAttributes.fillColor = durColor;

    return JSON.stringify({{
        panel: {panel_num},
        transition: "{escaped_transition}",
        duration_frames: {duration_frames}
    }});
}})();
""")

        jsx = "\n".join(jsx_parts)
        result = await _async_run_jsx("illustrator", jsx)

        return json.dumps({
            "action": "set",
            "panel_number": panel_num,
            "transition": transition,
            "duration_frames": duration_frames,
            "jsx_success": result.get("success", False),
        }, indent=2)
