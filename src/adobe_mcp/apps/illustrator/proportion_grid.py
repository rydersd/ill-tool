"""Place a measurement grid on the Illustrator artboard based on reference analysis.

Supports three modes:
  - from_manifest: auto-generates crosshair guides and bounding boxes from
    the shape manifest produced by analyze_reference.
  - manual: places horizontal/vertical guide lines at user-specified percentage
    positions on the artboard.
  - clear: removes all grid items (and optionally the Grid layer itself).

Grid layer color is GRAY per project convention (feedback_layer_colors.md).
All guide lines are clipped to artboard bounds (feedback_clip_to_artboard.md).
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiProportionGridInput


def register(mcp):
    """Register the adobe_ai_proportion_grid tool."""

    @mcp.tool(
        name="adobe_ai_proportion_grid",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_proportion_grid(params: AiProportionGridInput) -> str:
        """Place a measurement grid on the artboard from a shape manifest or manual positions.

        Idempotent: re-running replaces the existing grid. Grid lines are dashed,
        thin (0.5pt), gray, and clipped to artboard bounds. The Grid layer is
        locked after placement.

        Actions:
          from_manifest - parse shape_manifest JSON, draw crosshairs at each
                          shape center and optional dashed bounding rectangles.
          manual        - draw horizontal guides at h_positions (Y%) and vertical
                          guides at v_positions (X%).
          clear         - remove all items from the Grid layer.
        """
        action = params.action

        if action == "from_manifest":
            return await _from_manifest(params)
        elif action == "manual":
            return await _manual(params)
        elif action == "clear":
            return await _clear()
        else:
            return f"Error: unknown action '{action}'. Use from_manifest, manual, or clear."


async def _from_manifest(params: AiProportionGridInput) -> str:
    """Generate grid from an analyze_reference shape manifest."""
    if not params.shape_manifest:
        return "Error: from_manifest action requires shape_manifest JSON"

    # Validate the manifest JSON before sending to JSX
    try:
        manifest = json.loads(params.shape_manifest)
    except json.JSONDecodeError as exc:
        return f"Error: invalid shape_manifest JSON: {exc}"

    if "shapes" not in manifest or "image_size" not in manifest:
        return "Error: shape_manifest must contain 'shapes' and 'image_size' keys"

    # Escape the manifest for embedding in JSX string literal
    escaped_manifest = escape_jsx_string(params.shape_manifest)
    show_bboxes = "true" if params.show_bounding_boxes else "false"
    opacity = params.grid_opacity

    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var manifest = JSON.parse("{escaped_manifest}");
    var shapes = manifest.shapes;
    var imgW = manifest.image_size[0];
    var imgH = manifest.image_size[1];

    // --- Artboard metrics ---
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abLeft   = ab[0];
    var abTop    = ab[1];
    var abRight  = ab[2];
    var abBottom = ab[3];
    var abW = abRight - abLeft;
    var abH = abTop - abBottom; // positive because top > bottom in AI coords

    // Coordinate transform: image pixel space -> artboard space
    var scaleX = abW / imgW;
    var scaleY = abH / imgH;

    function toAiX(px) {{ return px * scaleX + abLeft; }}
    function toAiY(py) {{ return abTop - py * scaleY; }} // y is flipped

    // Clamp to artboard bounds
    function clampX(x) {{ return Math.max(abLeft, Math.min(abRight, x)); }}
    function clampY(y) {{ return Math.min(abTop, Math.max(abBottom, y)); }} // top > bottom

    // --- Find or create Grid layer ---
    var gridLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Grid") {{
            gridLayer = doc.layers[i];
            break;
        }}
    }}
    if (!gridLayer) {{
        gridLayer = doc.layers.add();
        gridLayer.name = "Grid";
    }}

    // Unlock so we can modify
    gridLayer.locked = false;
    gridLayer.visible = true;

    // Clear existing grid items (idempotent)
    while (gridLayer.pageItems.length > 0) {{
        gridLayer.pageItems[0].remove();
    }}

    // --- Position Grid layer just above Reference layer (or at bottom) ---
    var refLayer = null;
    for (var r = 0; r < doc.layers.length; r++) {{
        if (doc.layers[r].name === "Reference") {{
            refLayer = doc.layers[r];
            break;
        }}
    }}
    if (refLayer) {{
        // Place Grid just before (above) Reference
        try {{
            gridLayer.move(refLayer, ElementPlacement.PLACEBEFORE);
        }} catch (e) {{ /* already in position */ }}
    }} else if (doc.layers.length > 1) {{
        // No Reference layer — move Grid to bottom
        gridLayer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
    }}

    // --- Set layer color to gray ---
    var layerColor = new RGBColor();
    layerColor.red = 128;
    layerColor.green = 128;
    layerColor.blue = 128;
    gridLayer.color = layerColor;

    // --- Gray stroke color for all grid items ---
    var grayStroke = new GrayColor();
    grayStroke.gray = 60;

    var guidesDrawn = 0;
    var bboxesDrawn = 0;
    var showBBoxes = {show_bboxes};

    // --- Draw guides for each shape ---
    for (var s = 0; s < shapes.length; s++) {{
        var shape = shapes[s];
        var cx = toAiX(shape.center[0]);
        var cy = toAiY(shape.center[1]);

        // Clamp center to artboard
        cx = clampX(cx);
        cy = clampY(cy);

        // Horizontal crosshair line through center (clipped to artboard width)
        var hLine = gridLayer.pathItems.add();
        hLine.setEntirePath([
            [abLeft, cy],
            [abRight, cy]
        ]);
        hLine.filled = false;
        hLine.stroked = true;
        hLine.strokeColor = grayStroke;
        hLine.strokeWidth = 0.5;
        hLine.strokeDashes = [4, 4];
        hLine.name = "guide-h-" + s;
        guidesDrawn++;

        // Vertical crosshair line through center (clipped to artboard height)
        var vLine = gridLayer.pathItems.add();
        vLine.setEntirePath([
            [cx, abTop],
            [cx, abBottom]
        ]);
        vLine.filled = false;
        vLine.stroked = true;
        vLine.strokeColor = grayStroke;
        vLine.strokeWidth = 0.5;
        vLine.strokeDashes = [4, 4];
        vLine.name = "guide-v-" + s;
        guidesDrawn++;

        // Bounding box rectangle if requested
        if (showBBoxes && shape.bounding_rect) {{
            var br = shape.bounding_rect; // [x, y, w, h] in pixel space
            var rectLeft   = clampX(toAiX(br[0]));
            var rectTop    = clampY(toAiY(br[1]));
            var rectRight  = clampX(toAiX(br[0] + br[2]));
            var rectBottom = clampY(toAiY(br[1] + br[3]));

            // AI rectangle() takes (top, left, width, height) where top is the
            // upper-left Y in AI coordinate space (larger value).
            var rTop   = Math.max(rectTop, rectBottom); // whichever is higher in AI coords
            var rBot   = Math.min(rectTop, rectBottom);
            var rLeft  = Math.min(rectLeft, rectRight);
            var rRight = Math.max(rectLeft, rectRight);
            var rW = rRight - rLeft;
            var rH = rTop - rBot;

            if (rW > 0 && rH > 0) {{
                var rect = gridLayer.pathItems.rectangle(rTop, rLeft, rW, rH);
                rect.filled = false;
                rect.stroked = true;
                rect.strokeColor = grayStroke;
                rect.strokeWidth = 0.5;
                rect.strokeDashes = [2, 2];
                var shapeName = shape.type || ("shape-" + s);
                rect.name = "bbox-" + shapeName + "-" + s;
                bboxesDrawn++;
            }}
        }}
    }}

    // --- Set opacity and lock ---
    gridLayer.opacity = {opacity};
    gridLayer.locked = true;

    return JSON.stringify({{
        action: "from_manifest",
        layer: "Grid",
        guides_drawn: guidesDrawn,
        bounding_boxes_drawn: bboxesDrawn,
        shapes_processed: shapes.length,
        opacity: {opacity},
        locked: true
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return f"Error: {result['stderr']}"

    stdout = result["stdout"]
    try:
        data = json.loads(stdout)
        if "error" in data:
            return f"Grid placement failed: {data['error']}"
        parts = [
            f"Grid placed on '{data.get('layer', 'Grid')}' layer",
            f"guides: {data.get('guides_drawn', 0)}",
            f"bounding boxes: {data.get('bounding_boxes_drawn', 0)}",
            f"shapes processed: {data.get('shapes_processed', 0)}",
            f"opacity: {data.get('opacity', 30)}%",
            f"locked: {data.get('locked', True)}",
        ]
        return " | ".join(parts)
    except (json.JSONDecodeError, TypeError):
        return stdout


async def _manual(params: AiProportionGridInput) -> str:
    """Place horizontal/vertical guides at percentage positions."""
    h_positions = []
    v_positions = []

    if params.h_positions:
        try:
            h_positions = json.loads(params.h_positions)
        except json.JSONDecodeError as exc:
            return f"Error: invalid h_positions JSON: {exc}"
        if not isinstance(h_positions, list):
            return "Error: h_positions must be a JSON array of numbers"

    if params.v_positions:
        try:
            v_positions = json.loads(params.v_positions)
        except json.JSONDecodeError as exc:
            return f"Error: invalid v_positions JSON: {exc}"
        if not isinstance(v_positions, list):
            return "Error: v_positions must be a JSON array of numbers"

    if not h_positions and not v_positions:
        return "Error: manual action requires at least one of h_positions or v_positions"

    escaped_h = escape_jsx_string(json.dumps(h_positions))
    escaped_v = escape_jsx_string(json.dumps(v_positions))
    opacity = params.grid_opacity

    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var hPositions = JSON.parse("{escaped_h}");
    var vPositions = JSON.parse("{escaped_v}");

    // --- Artboard metrics ---
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abLeft   = ab[0];
    var abTop    = ab[1];
    var abRight  = ab[2];
    var abBottom = ab[3];
    var abW = abRight - abLeft;
    var abH = abTop - abBottom; // positive

    // --- Find or create Grid layer ---
    var gridLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Grid") {{
            gridLayer = doc.layers[i];
            break;
        }}
    }}
    if (!gridLayer) {{
        gridLayer = doc.layers.add();
        gridLayer.name = "Grid";
    }}

    gridLayer.locked = false;
    gridLayer.visible = true;

    // Clear existing grid items (idempotent)
    while (gridLayer.pageItems.length > 0) {{
        gridLayer.pageItems[0].remove();
    }}

    // --- Position Grid layer just above Reference layer (or at bottom) ---
    var refLayer = null;
    for (var r = 0; r < doc.layers.length; r++) {{
        if (doc.layers[r].name === "Reference") {{
            refLayer = doc.layers[r];
            break;
        }}
    }}
    if (refLayer) {{
        try {{
            gridLayer.move(refLayer, ElementPlacement.PLACEBEFORE);
        }} catch (e) {{ /* already in position */ }}
    }} else if (doc.layers.length > 1) {{
        gridLayer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
    }}

    // --- Set layer color to gray ---
    var layerColor = new RGBColor();
    layerColor.red = 128;
    layerColor.green = 128;
    layerColor.blue = 128;
    gridLayer.color = layerColor;

    // --- Gray stroke color ---
    var grayStroke = new GrayColor();
    grayStroke.gray = 60;

    var guidesDrawn = 0;

    // --- Horizontal guides (Y% positions) ---
    for (var h = 0; h < hPositions.length; h++) {{
        var pct = hPositions[h];
        // Clamp percentage to 0-100
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        // Convert Y% to AI coordinate: 0% = top, 100% = bottom
        var yPos = abTop - (pct / 100.0) * abH;

        var hLine = gridLayer.pathItems.add();
        hLine.setEntirePath([
            [abLeft, yPos],
            [abRight, yPos]
        ]);
        hLine.filled = false;
        hLine.stroked = true;
        hLine.strokeColor = grayStroke;
        hLine.strokeWidth = 0.5;
        hLine.strokeDashes = [4, 4];
        hLine.name = "guide-h-" + h + "-" + Math.round(pct) + "pct";
        guidesDrawn++;
    }}

    // --- Vertical guides (X% positions) ---
    for (var v = 0; v < vPositions.length; v++) {{
        var pct = vPositions[v];
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        // Convert X% to AI coordinate: 0% = left, 100% = right
        var xPos = abLeft + (pct / 100.0) * abW;

        var vLine = gridLayer.pathItems.add();
        vLine.setEntirePath([
            [xPos, abTop],
            [xPos, abBottom]
        ]);
        vLine.filled = false;
        vLine.stroked = true;
        vLine.strokeColor = grayStroke;
        vLine.strokeWidth = 0.5;
        vLine.strokeDashes = [4, 4];
        vLine.name = "guide-v-" + v + "-" + Math.round(pct) + "pct";
        guidesDrawn++;
    }}

    // --- Set opacity and lock ---
    gridLayer.opacity = {opacity};
    gridLayer.locked = true;

    return JSON.stringify({{
        action: "manual",
        layer: "Grid",
        guides_drawn: guidesDrawn,
        h_guides: hPositions.length,
        v_guides: vPositions.length,
        opacity: {opacity},
        locked: true
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return f"Error: {result['stderr']}"

    stdout = result["stdout"]
    try:
        data = json.loads(stdout)
        if "error" in data:
            return f"Grid placement failed: {data['error']}"
        parts = [
            f"Grid placed on '{data.get('layer', 'Grid')}' layer",
            f"guides: {data.get('guides_drawn', 0)} ({data.get('h_guides', 0)}H + {data.get('v_guides', 0)}V)",
            f"opacity: {data.get('opacity', 30)}%",
            f"locked: {data.get('locked', True)}",
        ]
        return " | ".join(parts)
    except (json.JSONDecodeError, TypeError):
        return stdout


async def _clear() -> str:
    """Remove all items from the Grid layer."""
    jsx = """
(function() {
    var doc = app.activeDocument;

    // Find the Grid layer
    var gridLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Grid") {
            gridLayer = doc.layers[i];
            break;
        }
    }
    if (!gridLayer) {
        return JSON.stringify({ action: "clear", removed: 0, message: "No Grid layer found" });
    }

    // Unlock so we can remove items
    gridLayer.locked = false;

    var count = gridLayer.pageItems.length;
    while (gridLayer.pageItems.length > 0) {
        gridLayer.pageItems[0].remove();
    }

    // Remove the empty layer itself
    gridLayer.remove();

    return JSON.stringify({
        action: "clear",
        removed: count,
        layer_removed: true
    });
})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return f"Error: {result['stderr']}"

    stdout = result["stdout"]
    try:
        data = json.loads(stdout)
        if "error" in data:
            return f"Grid clear failed: {data['error']}"
        removed = data.get("removed", 0)
        if data.get("layer_removed"):
            return f"Grid cleared: {removed} items removed, Grid layer removed"
        return data.get("message", f"Grid cleared: {removed} items removed")
    except (json.JSONDecodeError, TypeError):
        return stdout
