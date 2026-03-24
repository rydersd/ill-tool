"""Draw camera movement arrows and indicators on storyboard panels.

Provides visual notation for pan, tilt, zoom, truck, dolly, crane, static,
and handheld camera movements. Movement intensity (subtle, medium, dramatic)
controls the size of the drawn indicators. Notation data is persisted in the
rig file under "camera_notations".
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiCameraNotationInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Intensity scale factors
# ---------------------------------------------------------------------------

INTENSITY_SCALE = {
    "subtle":   0.5,
    "medium":   1.0,
    "dramatic": 2.0,
}


def _get_intensity_scale(intensity: str) -> float:
    """Return the scale multiplier for a given intensity level.

    Defaults to 1.0 (medium) for unknown values.
    """
    return INTENSITY_SCALE.get(intensity.lower().strip(), 1.0)


# ---------------------------------------------------------------------------
# Movement categories for JSX generation
# ---------------------------------------------------------------------------

# Horizontal arrows
HORIZONTAL_MOVEMENTS = {"pan_left", "pan_right", "truck_left", "truck_right"}
# Vertical arrows
VERTICAL_MOVEMENTS = {"tilt_up", "tilt_down", "crane_up", "crane_down"}
# Zoom brackets
ZOOM_MOVEMENTS = {"zoom_in", "zoom_out"}
# Depth arrows
DEPTH_MOVEMENTS = {"dolly_in", "dolly_out"}
# Static/handheld
SPECIAL_MOVEMENTS = {"static", "handheld"}


def _ensure_camera_notations(rig: dict) -> dict:
    """Ensure the rig has a camera_notations structure."""
    if "camera_notations" not in rig:
        rig["camera_notations"] = {}
    return rig


def _movement_label(movement: str) -> str:
    """Return a short label for annotated movements (truck/dolly)."""
    if movement.startswith("truck"):
        return "T"
    elif movement.startswith("dolly"):
        return "D"
    elif movement.startswith("crane"):
        return "C"
    return ""


def _arrow_direction(movement: str) -> tuple[float, float]:
    """Return (dx, dy) direction unit for the movement.

    Positive dx = right, positive dy = up (AI coordinate space).
    Returns unnormalized direction — caller scales by intensity.
    """
    directions = {
        "pan_left":    (-1, 0),
        "pan_right":   (1, 0),
        "tilt_up":     (0, 1),
        "tilt_down":   (0, -1),
        "truck_left":  (-1, 0),
        "truck_right": (1, 0),
        "dolly_in":    (0, 1),
        "dolly_out":   (0, -1),
        "crane_up":    (0, 1),
        "crane_down":  (0, -1),
    }
    return directions.get(movement, (0, 0))


def _build_jsx_notation(
    movement: str,
    panel_number: int,
    scale: float,
) -> str:
    """Build JSX code to draw camera notation on a panel.

    Assumes variables `panelBounds`, `ctrlLayer` are in scope
    (set by the calling JSX wrapper).
    """
    base_len = 60 * scale
    arrow_size = 8 * scale

    if movement in HORIZONTAL_MOVEMENTS or movement in VERTICAL_MOVEMENTS or movement in DEPTH_MOVEMENTS:
        dx, dy = _arrow_direction(movement)
        label = _movement_label(movement)

        # Arrow is drawn at center of panel
        return f"""
        var cx = (panelBounds[0] + panelBounds[2]) / 2;
        var cy = (panelBounds[1] + panelBounds[3]) / 2;
        var dx = {dx};
        var dy = {dy};
        var len = {base_len};
        var arrSz = {arrow_size};

        // Arrow line
        var arrow = notationLayer.pathItems.add();
        arrow.setEntirePath([
            [cx - dx * len / 2, cy - dy * len / 2],
            [cx + dx * len / 2, cy + dy * len / 2]
        ]);
        arrow.name = "cam_{panel_number}_arrow";
        arrow.filled = false;
        arrow.stroked = true;
        arrow.strokeWidth = 2 * {scale};
        var arrowClr = new RGBColor();
        arrowClr.red = 50; arrowClr.green = 150; arrowClr.blue = 255;
        arrow.strokeColor = arrowClr;

        // Arrowhead
        var tipX = cx + dx * len / 2;
        var tipY = cy + dy * len / 2;
        var head = notationLayer.pathItems.add();
        if (Math.abs(dx) > 0) {{
            head.setEntirePath([
                [tipX - dx * arrSz, tipY - arrSz],
                [tipX, tipY],
                [tipX - dx * arrSz, tipY + arrSz]
            ]);
        }} else {{
            head.setEntirePath([
                [tipX - arrSz, tipY - dy * arrSz],
                [tipX, tipY],
                [tipX + arrSz, tipY - dy * arrSz]
            ]);
        }}
        head.name = "cam_{panel_number}_head";
        head.filled = false;
        head.stroked = true;
        head.strokeWidth = 2 * {scale};
        head.strokeColor = arrowClr;

        // Movement label (T for truck, D for dolly, C for crane)
        var labelStr = "{label}";
        if (labelStr.length > 0) {{
            var lbl = notationLayer.textFrames.add();
            lbl.contents = labelStr;
            lbl.name = "cam_{panel_number}_label";
            lbl.position = [tipX + 4, tipY + 4];
            lbl.textRange.characterAttributes.size = 10 * {scale};
            lbl.textRange.characterAttributes.fillColor = arrowClr;
        }}
        """

    elif movement == "zoom_in":
        return f"""
        var cx = (panelBounds[0] + panelBounds[2]) / 2;
        var cy = (panelBounds[1] + panelBounds[3]) / 2;
        var sz = {base_len / 2};

        // Converging corner brackets (4 L-shapes pointing inward)
        var corners = [
            [[cx - sz, cy + sz - 15 * {scale}], [cx - sz, cy + sz], [cx - sz + 15 * {scale}, cy + sz]],
            [[cx + sz - 15 * {scale}, cy + sz], [cx + sz, cy + sz], [cx + sz, cy + sz - 15 * {scale}]],
            [[cx + sz, cy - sz + 15 * {scale}], [cx + sz, cy - sz], [cx + sz - 15 * {scale}, cy - sz]],
            [[cx - sz + 15 * {scale}, cy - sz], [cx - sz, cy - sz], [cx - sz, cy - sz + 15 * {scale}]]
        ];
        var bracketClr = new RGBColor();
        bracketClr.red = 50; bracketClr.green = 150; bracketClr.blue = 255;
        for (var b = 0; b < corners.length; b++) {{
            var bracket = notationLayer.pathItems.add();
            bracket.setEntirePath(corners[b]);
            bracket.name = "cam_{panel_number}_zoom_" + b;
            bracket.filled = false;
            bracket.stroked = true;
            bracket.strokeWidth = 2 * {scale};
            bracket.strokeColor = bracketClr;
        }}
        """

    elif movement == "zoom_out":
        return f"""
        var cx = (panelBounds[0] + panelBounds[2]) / 2;
        var cy = (panelBounds[1] + panelBounds[3]) / 2;
        var sz = {base_len / 4};
        var outerSz = {base_len / 2};

        // Diverging corner brackets (4 L-shapes pointing outward)
        var corners = [
            [[cx - sz, cy + sz + 15 * {scale}], [cx - sz, cy + sz], [cx - sz - 15 * {scale}, cy + sz]],
            [[cx + sz + 15 * {scale}, cy + sz], [cx + sz, cy + sz], [cx + sz, cy + sz + 15 * {scale}]],
            [[cx + sz, cy - sz - 15 * {scale}], [cx + sz, cy - sz], [cx + sz + 15 * {scale}, cy - sz]],
            [[cx - sz - 15 * {scale}, cy - sz], [cx - sz, cy - sz], [cx - sz, cy - sz - 15 * {scale}]]
        ];
        var bracketClr = new RGBColor();
        bracketClr.red = 50; bracketClr.green = 150; bracketClr.blue = 255;
        for (var b = 0; b < corners.length; b++) {{
            var bracket = notationLayer.pathItems.add();
            bracket.setEntirePath(corners[b]);
            bracket.name = "cam_{panel_number}_zoom_" + b;
            bracket.filled = false;
            bracket.stroked = true;
            bracket.strokeWidth = 2 * {scale};
            bracket.strokeColor = bracketClr;
        }}
        """

    elif movement == "static":
        return f"""
        var cx = (panelBounds[0] + panelBounds[2]) / 2;
        var cy = panelBounds[1] - 12;
        var lbl = notationLayer.textFrames.add();
        lbl.contents = "STATIC";
        lbl.name = "cam_{panel_number}_static";
        lbl.position = [cx - 15, cy];
        lbl.textRange.characterAttributes.size = 8 * {scale};
        var staticClr = new RGBColor();
        staticClr.red = 100; staticClr.green = 100; staticClr.blue = 100;
        lbl.textRange.characterAttributes.fillColor = staticClr;
        """

    elif movement == "handheld":
        # Wavy line to indicate handheld camera
        return f"""
        var cx = (panelBounds[0] + panelBounds[2]) / 2;
        var cy = (panelBounds[1] + panelBounds[3]) / 2;
        var amplitude = 6 * {scale};
        var waveLen = {base_len};
        var segments = 12;
        var pts = [];
        for (var s = 0; s <= segments; s++) {{
            var t = s / segments;
            var wx = cx - waveLen / 2 + t * waveLen;
            var wy = cy + Math.sin(t * Math.PI * 4) * amplitude;
            pts.push([wx, wy]);
        }}
        var wave = notationLayer.pathItems.add();
        wave.setEntirePath(pts);
        wave.name = "cam_{panel_number}_handheld";
        wave.filled = false;
        wave.stroked = true;
        wave.strokeWidth = 1.5 * {scale};
        var waveClr = new RGBColor();
        waveClr.red = 50; waveClr.green = 150; waveClr.blue = 255;
        wave.strokeColor = waveClr;
        """

    # Fallback — just a label
    return f"""
    var cx = (panelBounds[0] + panelBounds[2]) / 2;
    var cy = panelBounds[1] - 12;
    var lbl = notationLayer.textFrames.add();
    lbl.contents = "{movement.upper().replace('_', ' ')}";
    lbl.name = "cam_{panel_number}_label";
    lbl.position = [cx - 20, cy];
    lbl.textRange.characterAttributes.size = 8 * {scale};
    var lblClr = new RGBColor();
    lblClr.red = 50; lblClr.green = 150; lblClr.blue = 255;
    lbl.textRange.characterAttributes.fillColor = lblClr;
    """


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_camera_notation tool."""

    @mcp.tool(
        name="adobe_ai_camera_notation",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_camera_notation(params: AiCameraNotationInput) -> str:
        """Draw camera movement arrows and indicators on a storyboard panel.

        Supports: pan, tilt, zoom, truck, dolly, crane, static, handheld.
        Intensity (subtle/medium/dramatic) controls arrow size.
        """
        rig = _load_rig("storyboard")
        rig = _ensure_camera_notations(rig)

        panel_key = str(params.panel_number)
        movement = params.movement.lower().strip()
        intensity = params.intensity.lower().strip()
        scale = _get_intensity_scale(intensity)

        # Generate the notation JSX
        notation_jsx = _build_jsx_notation(movement, params.panel_number, scale)

        jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Find panel bounds from the panel frame
    var panelBounds = null;
    for (var l = 0; l < doc.layers.length; l++) {{
        try {{
            var frame = doc.layers[l].pathItems.getByName("panel_{params.panel_number}_frame");
            if (frame) {{
                panelBounds = frame.geometricBounds;
                break;
            }}
        }} catch(e) {{}}
    }}

    if (!panelBounds) {{
        // Fallback to active artboard
        var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
        panelBounds = ab.artboardRect;
    }}

    // Remove existing notation for this panel
    var notationLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Camera_Notation") {{
            notationLayer = doc.layers[i];
            break;
        }}
    }}
    if (!notationLayer) {{
        notationLayer = doc.layers.add();
        notationLayer.name = "Camera_Notation";
    }}

    // Remove old notation items for this panel
    var removePrefix = "cam_{params.panel_number}_";
    for (var j = notationLayer.pageItems.length - 1; j >= 0; j--) {{
        if (notationLayer.pageItems[j].name.indexOf(removePrefix) === 0) {{
            notationLayer.pageItems[j].remove();
        }}
    }}

    // Draw the notation
    {notation_jsx}

    return JSON.stringify({{
        panel: {params.panel_number},
        movement: "{movement}",
        intensity: "{intensity}",
        scale: {scale}
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result.get("success", False):
            return json.dumps({"error": result.get("stderr", "Unknown error")})

        # Store in rig
        rig["camera_notations"][panel_key] = {
            "movement": movement,
            "intensity": intensity,
            "scale": scale,
        }
        _save_rig("storyboard", rig)

        return json.dumps({
            "panel_number": params.panel_number,
            "movement": movement,
            "intensity": intensity,
            "scale": scale,
        }, indent=2)
