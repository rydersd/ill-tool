"""Set backgrounds for storyboard panels via JSX.

Each panel's background lives on a "Background" sublayer within its
artboard area.  Supports solid color fills, gradient fills, placed
images, and clearing the background entirely.

Background metadata is stored in the rig under `backgrounds` keyed by
panel number so the pipeline can track what each panel uses.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiBackgroundLayerInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# Default panel dimensions (must match storyboard_panel.py)
PANEL_WIDTH = 960
PANEL_HEIGHT = 540


def _ensure_backgrounds(rig: dict) -> dict:
    """Ensure the rig has a backgrounds dict."""
    if "backgrounds" not in rig:
        rig["backgrounds"] = {}
    return rig


def _validate_color(r: int, g: int, b: int) -> str | None:
    """Return an error string if any RGB value is out of range, else None."""
    for name, val in [("red", r), ("green", g), ("blue", b)]:
        if not (0 <= val <= 255):
            return f"Color {name} value {val} out of range 0-255."
    return None


def register(mcp):
    """Register the adobe_ai_background_layer tool."""

    @mcp.tool(
        name="adobe_ai_background_layer",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_background_layer(params: AiBackgroundLayerInput) -> str:
        """Set up a background for a storyboard panel.

        Supports solid color, gradient, placed image, or clearing the
        background.  The background is placed on a locked "Background"
        sublayer beneath the panel content.
        """
        character_name = "storyboard"
        rig = _load_rig(character_name)
        rig = _ensure_backgrounds(rig)

        bg_type = params.bg_type.lower().strip()
        panel_num = params.panel_number

        # ── none: remove background ──────────────────────────────────
        if bg_type == "none":
            panel_key = str(panel_num) if panel_num is not None else "active"

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var removed = 0;
    for (var i = doc.layers.length - 1; i >= 0; i--) {{
        if (doc.layers[i].name === "Background_{panel_key}") {{
            doc.layers[i].locked = false;
            doc.layers[i].remove();
            removed++;
        }}
    }}
    return JSON.stringify({{removed: removed}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            # Remove from rig data
            rig["backgrounds"].pop(panel_key, None)
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "remove_background",
                "panel": panel_key,
                "success": result.get("success", False),
            }, indent=2)

        # ── Validate color for solid and gradient ────────────────────
        color_err = _validate_color(params.color_r, params.color_g, params.color_b)
        if color_err:
            return json.dumps({"error": color_err})

        panel_key = str(panel_num) if panel_num is not None else "active"

        # ── solid ────────────────────────────────────────────────────
        if bg_type == "solid":
            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Create or find Background layer
    var bgLayer;
    try {{
        bgLayer = doc.layers.getByName("Background_{panel_key}");
        bgLayer.locked = false;
        // Clear existing items
        while (bgLayer.pageItems.length > 0) {{
            bgLayer.pageItems[0].remove();
        }}
    }} catch(e) {{
        bgLayer = doc.layers.add();
        bgLayer.name = "Background_{panel_key}";
    }}

    // Move to bottom
    bgLayer.zOrder(ZOrderMethod.SENDTOBACK);

    // Get artboard bounds for the panel
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var rect = ab.artboardRect;
    var w = rect[2] - rect[0];
    var h = rect[1] - rect[3];

    // Create filled rectangle
    var bg = bgLayer.pathItems.rectangle(rect[1], rect[0], w, h);
    bg.name = "bg_solid_{panel_key}";
    bg.stroked = false;
    bg.filled = true;
    var c = new RGBColor();
    c.red = {params.color_r}; c.green = {params.color_g}; c.blue = {params.color_b};
    bg.fillColor = c;
    bg.opacity = {params.opacity};

    bgLayer.locked = true;

    return JSON.stringify({{
        type: "solid",
        panel: "{panel_key}",
        color: [{params.color_r}, {params.color_g}, {params.color_b}]
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            bg_data = {
                "type": "solid",
                "color": [params.color_r, params.color_g, params.color_b],
                "opacity": params.opacity,
            }
            rig["backgrounds"][panel_key] = bg_data
            _save_rig(character_name, rig)

            if not result.get("success", False):
                return json.dumps({
                    "error": f"Failed to create solid background: {result.get('stderr', 'Unknown error')}",
                    "data_saved": True,
                })

            return json.dumps({
                "action": "set_background",
                "background": bg_data,
                "panel": panel_key,
            }, indent=2)

        # ── gradient ─────────────────────────────────────────────────
        elif bg_type == "gradient":
            end_r = params.gradient_end_r if params.gradient_end_r is not None else 255
            end_g = params.gradient_end_g if params.gradient_end_g is not None else 255
            end_b = params.gradient_end_b if params.gradient_end_b is not None else 255

            end_err = _validate_color(end_r, end_g, end_b)
            if end_err:
                return json.dumps({"error": f"Gradient end color: {end_err}"})

            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    var bgLayer;
    try {{
        bgLayer = doc.layers.getByName("Background_{panel_key}");
        bgLayer.locked = false;
        while (bgLayer.pageItems.length > 0) {{
            bgLayer.pageItems[0].remove();
        }}
    }} catch(e) {{
        bgLayer = doc.layers.add();
        bgLayer.name = "Background_{panel_key}";
    }}

    bgLayer.zOrder(ZOrderMethod.SENDTOBACK);

    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var rect = ab.artboardRect;
    var w = rect[2] - rect[0];
    var h = rect[1] - rect[3];

    var bg = bgLayer.pathItems.rectangle(rect[1], rect[0], w, h);
    bg.name = "bg_gradient_{panel_key}";
    bg.stroked = false;

    // Create gradient
    var grad = doc.gradients.add();
    grad.name = "bg_grad_{panel_key}";
    grad.type = GradientType.LINEAR;

    var stop1 = grad.gradientStops[0];
    var c1 = new RGBColor();
    c1.red = {params.color_r}; c1.green = {params.color_g}; c1.blue = {params.color_b};
    stop1.color = c1;
    stop1.rampPoint = 0;

    var stop2 = grad.gradientStops[1];
    var c2 = new RGBColor();
    c2.red = {end_r}; c2.green = {end_g}; c2.blue = {end_b};
    stop2.color = c2;
    stop2.rampPoint = 100;

    var gc = new GradientColor();
    gc.gradient = grad;
    bg.fillColor = gc;
    bg.filled = true;
    bg.opacity = {params.opacity};

    bgLayer.locked = true;

    return JSON.stringify({{
        type: "gradient",
        panel: "{panel_key}",
        start_color: [{params.color_r}, {params.color_g}, {params.color_b}],
        end_color: [{end_r}, {end_g}, {end_b}]
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            bg_data = {
                "type": "gradient",
                "color": [params.color_r, params.color_g, params.color_b],
                "gradient_end": [end_r, end_g, end_b],
                "opacity": params.opacity,
            }
            rig["backgrounds"][panel_key] = bg_data
            _save_rig(character_name, rig)

            if not result.get("success", False):
                return json.dumps({
                    "error": f"Failed to create gradient background: {result.get('stderr', 'Unknown error')}",
                    "data_saved": True,
                })

            return json.dumps({
                "action": "set_background",
                "background": bg_data,
                "panel": panel_key,
            }, indent=2)

        # ── image ────────────────────────────────────────────────────
        elif bg_type == "image":
            if not params.image_path:
                return json.dumps({"error": "image_path is required for image background type."})

            escaped_path = params.image_path.replace("\\", "\\\\")

            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    var bgLayer;
    try {{
        bgLayer = doc.layers.getByName("Background_{panel_key}");
        bgLayer.locked = false;
        while (bgLayer.pageItems.length > 0) {{
            bgLayer.pageItems[0].remove();
        }}
    }} catch(e) {{
        bgLayer = doc.layers.add();
        bgLayer.name = "Background_{panel_key}";
    }}

    bgLayer.zOrder(ZOrderMethod.SENDTOBACK);

    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var rect = ab.artboardRect;

    var imgFile = new File("{escaped_path}");
    if (!imgFile.exists) {{
        return JSON.stringify({{error: "Image file not found: {escaped_path}"}});
    }}

    var placed = bgLayer.placedItems.add();
    placed.file = imgFile;
    placed.name = "bg_image_{panel_key}";

    // Scale to fit artboard
    var abW = rect[2] - rect[0];
    var abH = rect[1] - rect[3];
    var imgW = placed.width;
    var imgH = placed.height;
    var scaleX = (abW / imgW) * 100;
    var scaleY = (abH / imgH) * 100;
    var scale = Math.max(scaleX, scaleY);
    placed.resize(scale, scale);
    placed.position = [rect[0], rect[1]];
    placed.opacity = {params.opacity};

    bgLayer.locked = true;

    return JSON.stringify({{
        type: "image",
        panel: "{panel_key}",
        image: "{escaped_path}"
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            bg_data = {
                "type": "image",
                "image_path": params.image_path,
                "opacity": params.opacity,
            }
            rig["backgrounds"][panel_key] = bg_data
            _save_rig(character_name, rig)

            if not result.get("success", False):
                return json.dumps({
                    "error": f"Failed to place image background: {result.get('stderr', 'Unknown error')}",
                    "data_saved": True,
                })

            return json.dumps({
                "action": "set_background",
                "background": bg_data,
                "panel": panel_key,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown bg_type: {bg_type}",
                "valid_types": ["solid", "gradient", "image", "none"],
            })
