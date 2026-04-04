"""Automate the GIR tracing workflow: setup document, auto-trace contours, list shapes, export, and copy back.

Combines OpenCV contour detection with Illustrator document management to provide
a complete image-to-vector tracing pipeline.  Each action is a discrete step so the
user can inspect and adjust between stages.

Coordinate convention: pixel (x, y) maps to AI (x, -y) — origin at top-left,
Y axis flipped for Illustrator's bottom-up coordinate system.
"""

import json
import os
import tempfile

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class TraceWorkflowInput(BaseModel):
    """Control the GIR tracing workflow."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: setup, auto_trace, list_shapes, export_trace, copy_back",
    )
    image_path: Optional[str] = Field(
        default=None, description="Reference image path (for setup)"
    )
    target_doc: Optional[str] = Field(
        default=None, description="Target AI document path (for copy_back)"
    )
    threshold: int = Field(
        default=30,
        description="Black threshold for contour detection",
        ge=0,
        le=128,
    )
    min_area: int = Field(
        default=200,
        description="Minimum contour area in pixels to include",
        ge=10,
    )
    output_dir: Optional[str] = Field(
        default=None, description="Output directory for exports"
    )


# ---------------------------------------------------------------------------
# Pure Python helpers (testable without Illustrator)
# ---------------------------------------------------------------------------


def _read_image_dimensions(image_path: str) -> dict:
    """Read image and return dimensions, or error dict."""
    if not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}
    h, w = img.shape[:2]
    return {"width": w, "height": h, "channels": img.shape[2] if len(img.shape) > 2 else 1}


def _detect_black_contours(image_path: str, threshold: int, min_area: int) -> dict:
    """Detect black regions in the image via thresholding.

    Returns contours sorted by area (largest first), each with
    approxPolyDP points converted to a plain list and area measurement.
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Invert: we want black regions as white for findContours
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter by minimum area
    filtered = [c for c in contours if cv2.contourArea(c) >= min_area]

    # Sort by area, largest first
    filtered.sort(key=lambda c: cv2.contourArea(c), reverse=True)

    shapes = []
    for i, contour in enumerate(filtered):
        area = cv2.contourArea(contour)
        epsilon = 0.02 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        # Convert to AI coordinates: (x, -y) for each point
        ai_points = [[int(pt[0][0]), -int(pt[0][1])] for pt in approx]
        shapes.append({
            "name": f"shape_{i}",
            "area": float(area),
            "point_count": len(ai_points),
            "points": ai_points,
        })

    return {
        "shape_count": len(shapes),
        "shapes": shapes,
        "image_size": [img.shape[1], img.shape[0]],
    }


def _detect_colored_regions(image_path: str, min_area: int) -> dict:
    """Detect green (character body) and pink (tongue) regions via HSV ranges.

    Returns grouped contours for each detected color category.
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Color ranges in HSV
    color_ranges = {
        "green_body": {
            "lower": np.array([35, 50, 50]),
            "upper": np.array([85, 255, 255]),
        },
        "pink_tongue": {
            "lower": np.array([140, 50, 50]),
            "upper": np.array([170, 255, 255]),
        },
    }

    groups = {}
    for color_name, bounds in color_ranges.items():
        mask = cv2.inRange(hsv, bounds["lower"], bounds["upper"])
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filtered = [c for c in contours if cv2.contourArea(c) >= min_area]
        filtered.sort(key=lambda c: cv2.contourArea(c), reverse=True)

        region_shapes = []
        for i, contour in enumerate(filtered):
            area = cv2.contourArea(contour)
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            ai_points = [[int(pt[0][0]), -int(pt[0][1])] for pt in approx]
            region_shapes.append({
                "name": f"{color_name}_{i}",
                "area": float(area),
                "point_count": len(ai_points),
                "points": ai_points,
            })

        if region_shapes:
            groups[color_name] = region_shapes

    return {"colored_groups": groups, "group_count": len(groups)}


# ---------------------------------------------------------------------------
# JSX-backed actions (require Illustrator)
# ---------------------------------------------------------------------------


async def _action_setup(params: TraceWorkflowInput) -> str:
    """Create a new AI document matching the reference image size, set up layers, place image."""
    if not params.image_path:
        return json.dumps({"error": "image_path required for setup action"})

    dims = _read_image_dimensions(params.image_path)
    if "error" in dims:
        return json.dumps(dims)

    w, h = dims["width"], dims["height"]
    escaped_path = escape_jsx_string(params.image_path)

    # Determine output directory
    out_dir = params.output_dir or tempfile.mkdtemp(prefix="trace_workflow_")
    os.makedirs(out_dir, exist_ok=True)
    doc_path = os.path.join(out_dir, "trace_document.ai")
    escaped_doc = escape_jsx_string(doc_path)

    jsx = f"""
(function() {{
    // Create new document matching image dimensions
    var preset = new DocumentPreset();
    preset.width = {w};
    preset.height = {h};
    preset.colorMode = DocumentColorSpace.RGB;
    var doc = app.documents.addDocument("", preset);

    // Set up three layers: Trace (top), Axis (middle), Reference (bottom, locked)
    // Document starts with one layer — rename it as Reference
    var refLayer = doc.layers[0];
    refLayer.name = "Reference";

    var axisLayer = doc.layers.add();
    axisLayer.name = "Axis";

    var traceLayer = doc.layers.add();
    traceLayer.name = "Trace";

    // Place the reference image at (0, 0) — 1:1 pixel-to-AI mapping
    doc.activeLayer = refLayer;
    var placed = refLayer.placedItems.add();
    placed.file = new File("{escaped_path}");
    placed.position = [0, 0];

    // Lock the reference layer so it can't be accidentally edited
    refLayer.locked = true;

    // Set Trace as the active layer for drawing
    doc.activeLayer = traceLayer;

    // Save the document
    var saveFile = new File("{escaped_doc}");
    doc.saveAs(saveFile);

    return JSON.stringify({{
        doc_path: "{escaped_doc}",
        width: {w},
        height: {h},
        layers: ["Trace", "Axis", "Reference"],
        reference_locked: true
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return json.dumps({"error": f"Setup failed: {result['stderr']}"})

    try:
        data = json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        data = {"raw": result["stdout"]}

    data["image_dimensions"] = dims
    data["output_dir"] = out_dir
    return json.dumps(data, indent=2)


async def _action_auto_trace(params: TraceWorkflowInput) -> str:
    """Detect contours in the reference image and place them as paths on the Trace layer."""
    if not params.image_path:
        return json.dumps({"error": "image_path required for auto_trace action"})

    # Detect black contours
    detection = _detect_black_contours(params.image_path, params.threshold, params.min_area)
    if "error" in detection:
        return json.dumps(detection)

    shapes = detection["shapes"]
    if not shapes:
        return json.dumps({"shape_count": 0, "message": "No contours found above min_area threshold"})

    # Detect colored regions as well
    colored = _detect_colored_regions(params.image_path, params.min_area)

    # Build JSX to place all shapes on the Trace layer
    all_paths_jsx = ""
    for shape in shapes:
        pts_json = json.dumps(shape["points"])
        escaped_name = escape_jsx_string(shape["name"])
        all_paths_jsx += f"""
    var p = traceLayer.pathItems.add();
    p.setEntirePath({pts_json});
    p.closed = true;
    p.filled = false;
    p.stroked = true;
    p.strokeWidth = 1;
    var blk = new RGBColor();
    blk.red = 0; blk.green = 0; blk.blue = 0;
    p.strokeColor = blk;
    p.name = "{escaped_name}";
    placedCount++;
"""

    # Add colored region paths with their group colors
    color_map = {"green_body": [0, 180, 0], "pink_tongue": [255, 100, 150]}
    for group_name, group_shapes in colored.get("colored_groups", {}).items():
        rgb = color_map.get(group_name, [128, 128, 128])
        for shape in group_shapes:
            pts_json = json.dumps(shape["points"])
            escaped_name = escape_jsx_string(shape["name"])
            all_paths_jsx += f"""
    var cp = traceLayer.pathItems.add();
    cp.setEntirePath({pts_json});
    cp.closed = true;
    cp.filled = false;
    cp.stroked = true;
    cp.strokeWidth = 1;
    var clr = new RGBColor();
    clr.red = {rgb[0]}; clr.green = {rgb[1]}; clr.blue = {rgb[2]};
    cp.strokeColor = clr;
    cp.name = "{escaped_name}";
    placedCount++;
"""

    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var placedCount = 0;

    // Find or create Trace layer
    var traceLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Trace") {{
            traceLayer = doc.layers[i];
            break;
        }}
    }}
    if (!traceLayer) {{
        traceLayer = doc.layers.add();
        traceLayer.name = "Trace";
    }}
    doc.activeLayer = traceLayer;

    {all_paths_jsx}

    return JSON.stringify({{
        shapes_placed: placedCount
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return json.dumps({
            "error": f"Trace placement failed: {result['stderr']}",
            "detected_shapes": len(shapes),
        })

    response = {
        "shape_count": len(shapes),
        "shapes": [{"name": s["name"], "area": s["area"], "point_count": s["point_count"]} for s in shapes],
        "colored_groups": {
            k: [{"name": s["name"], "area": s["area"]} for s in v]
            for k, v in colored.get("colored_groups", {}).items()
        },
    }
    return json.dumps(response, indent=2)


async def _action_list_shapes(params: TraceWorkflowInput) -> str:
    """Return all shapes currently on the Trace layer with names, point counts, and bounds."""
    jsx = """
(function() {
    var doc = app.activeDocument;
    var traceLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Trace") {
            traceLayer = doc.layers[i];
            break;
        }
    }
    if (!traceLayer) {
        return JSON.stringify({error: "No Trace layer found"});
    }

    var shapes = [];
    for (var j = 0; j < traceLayer.pathItems.length; j++) {
        var p = traceLayer.pathItems[j];
        shapes.push({
            name: p.name,
            point_count: p.pathPoints.length,
            bounds: p.geometricBounds,
            closed: p.closed,
            stroked: p.stroked,
            filled: p.filled
        });
    }
    return JSON.stringify({shape_count: shapes.length, shapes: shapes});
})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return json.dumps({"error": f"List shapes failed: {result['stderr']}"})

    try:
        data = json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        data = {"raw": result["stdout"]}
    return json.dumps(data, indent=2)


async def _action_export_trace(params: TraceWorkflowInput) -> str:
    """Export the Trace layer contents as SVG."""
    out_dir = params.output_dir or tempfile.mkdtemp(prefix="trace_export_")
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "trace_export.svg")
    escaped_svg = escape_jsx_string(svg_path)

    jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Hide all layers except Trace for export
    var layerStates = [];
    for (var i = 0; i < doc.layers.length; i++) {{
        layerStates.push(doc.layers[i].visible);
        doc.layers[i].visible = (doc.layers[i].name === "Trace");
    }}

    // Export as SVG
    var svgFile = new File("{escaped_svg}");
    var opts = new ExportOptionsSVG();
    opts.embedRasterImages = false;
    opts.fontType = SVGFontType.OUTLINEFONT;
    doc.exportFile(svgFile, ExportType.SVG, opts);

    // Restore layer visibility
    for (var j = 0; j < doc.layers.length; j++) {{
        doc.layers[j].visible = layerStates[j];
    }}

    return JSON.stringify({{
        svg_path: "{escaped_svg}",
        exported: true
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return json.dumps({"error": f"Export failed: {result['stderr']}"})

    try:
        data = json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        data = {"raw": result["stdout"]}
    return json.dumps(data, indent=2)


async def _action_copy_back(params: TraceWorkflowInput) -> str:
    """Copy all paths from the Trace layer into the target document."""
    if not params.target_doc:
        return json.dumps({"error": "target_doc required for copy_back action"})

    escaped_target = escape_jsx_string(params.target_doc)

    jsx = f"""
(function() {{
    var sourceDoc = app.activeDocument;

    // Collect Trace layer paths
    var traceLayer = null;
    for (var i = 0; i < sourceDoc.layers.length; i++) {{
        if (sourceDoc.layers[i].name === "Trace") {{
            traceLayer = sourceDoc.layers[i];
            break;
        }}
    }}
    if (!traceLayer) {{
        return JSON.stringify({{error: "No Trace layer in source document"}});
    }}
    if (traceLayer.pathItems.length === 0) {{
        return JSON.stringify({{error: "No paths on Trace layer to copy"}});
    }}

    // Select all paths on the Trace layer
    sourceDoc.selection = null;
    for (var j = 0; j < traceLayer.pathItems.length; j++) {{
        traceLayer.pathItems[j].selected = true;
    }}

    // Copy selection
    app.copy();

    // Open target document
    var targetFile = new File("{escaped_target}");
    var targetDoc = app.open(targetFile);

    // Paste into target
    app.paste();

    // Align to artboard origin
    var ab = targetDoc.artboards[targetDoc.artboards.getActiveArtboardIndex()].artboardRect;
    if (targetDoc.selection && targetDoc.selection.length > 0) {{
        for (var k = 0; k < targetDoc.selection.length; k++) {{
            // Position relative to artboard left/top
            var item = targetDoc.selection[k];
            item.position = [
                ab[0] + (item.position[0] - ab[0]),
                ab[1] + (item.position[1] - ab[1])
            ];
        }}
    }}

    var copiedCount = targetDoc.selection ? targetDoc.selection.length : 0;

    return JSON.stringify({{
        target_doc: "{escaped_target}",
        paths_copied: copiedCount,
        aligned_to_artboard: true
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return json.dumps({"error": f"Copy back failed: {result['stderr']}"})

    try:
        data = json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        data = {"raw": result["stdout"]}
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_trace_workflow tool."""

    @mcp.tool(
        name="adobe_ai_trace_workflow",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_trace_workflow(params: TraceWorkflowInput) -> str:
        """Automate the GIR tracing workflow: setup document from reference image,
        auto-trace contours with OpenCV, list traced shapes, export as SVG,
        or copy traced paths back to a target document.

        Actions:
        - setup: Create AI doc matching image size, set up layers, place reference
        - auto_trace: Detect contours and place as paths on Trace layer
        - list_shapes: List all shapes on the Trace layer
        - export_trace: Export Trace layer as SVG
        - copy_back: Copy Trace paths to target document
        """
        action = params.action.lower().strip()

        if action == "setup":
            return await _action_setup(params)
        elif action == "auto_trace":
            return await _action_auto_trace(params)
        elif action == "list_shapes":
            return await _action_list_shapes(params)
        elif action == "export_trace":
            return await _action_export_trace(params)
        elif action == "copy_back":
            return await _action_copy_back(params)
        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["setup", "auto_trace", "list_shapes", "export_trace", "copy_back"],
            })
