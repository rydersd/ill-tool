"""Extract the overall silhouette from a reference image as a single clean closed path.

Uses OpenCV to threshold the image, find the largest external contour, simplify it
with approxPolyDP, then optionally place the result as a closed stroked path in
Illustrator — mapped to the active artboard with correct aspect ratio.
"""

import json
import os

import cv2
import numpy as np

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSilhouetteInput


def _extract_silhouette(params: AiSilhouetteInput) -> dict:
    """Run OpenCV pipeline: threshold, find largest contour, simplify.

    Returns a dict with contour points in pixel coordinates plus metadata.
    Does NOT interact with Illustrator.
    """
    # Step 1: Load and preprocess image
    img = cv2.imread(params.image_path)
    if img is None:
        return {"error": f"Could not read image at {params.image_path}"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold via Otsu for clean silhouette extraction
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Step 2: Find the outermost contour only
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"error": "No contours found in image"}

    # Take the largest contour by area — this is the silhouette
    largest = max(contours, key=cv2.contourArea)
    original_point_count = len(largest)

    # Step 3: Simplify with approxPolyDP
    arc_length = cv2.arcLength(largest, True)
    epsilon = params.simplification * arc_length
    approx = cv2.approxPolyDP(largest, epsilon, True)

    # Convert to plain list of [x, y] pixel coords
    pixel_points = approx.reshape(-1, 2).tolist()

    img_h, img_w = img.shape[:2]

    return {
        "pixel_points": pixel_points,
        "point_count": len(pixel_points),
        "original_contour_points": original_point_count,
        "image_size": [img_w, img_h],
    }


def register(mcp):
    """Register the adobe_ai_silhouette tool."""

    @mcp.tool(
        name="adobe_ai_silhouette",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_silhouette(params: AiSilhouetteInput) -> str:
        """Extract the overall silhouette from a reference image as a single clean
        closed path and optionally place it in Illustrator.

        Uses Otsu thresholding to isolate the subject, finds the largest external
        contour, simplifies it with approxPolyDP, then maps the result to the
        active artboard maintaining aspect ratio.
        """
        # Validate image path before processing
        if not os.path.isfile(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        # Run the OpenCV extraction pipeline
        extraction = _extract_silhouette(params)
        if "error" in extraction:
            return json.dumps(extraction)

        pixel_points = extraction["pixel_points"]
        img_w, img_h = extraction["image_size"]

        # If not placing in AI, return the raw silhouette data in pixel coords
        if not params.place_in_ai:
            return json.dumps({
                "point_count": extraction["point_count"],
                "points": pixel_points,
                "simplification_used": params.simplification,
                "original_contour_points": extraction["original_contour_points"],
                "placed_in_ai": False,
                "coordinate_space": "pixels",
                "image_size": [img_w, img_h],
            }, indent=2)

        # Step 4: Get artboard dimensions from Illustrator
        jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
        ab_result = await _async_run_jsx("illustrator", jsx_info)
        if not ab_result["success"]:
            # Artboard query failed — return silhouette data without placement
            return json.dumps({
                "point_count": extraction["point_count"],
                "points": pixel_points,
                "simplification_used": params.simplification,
                "original_contour_points": extraction["original_contour_points"],
                "placed_in_ai": False,
                "coordinate_space": "pixels",
                "image_size": [img_w, img_h],
                "placement_error": f"Could not query artboard: {ab_result['stderr']}",
            }, indent=2)

        try:
            ab = json.loads(ab_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "point_count": extraction["point_count"],
                "points": pixel_points,
                "simplification_used": params.simplification,
                "original_contour_points": extraction["original_contour_points"],
                "placed_in_ai": False,
                "coordinate_space": "pixels",
                "image_size": [img_w, img_h],
                "placement_error": f"Bad artboard response: {ab_result['stdout']}",
            }, indent=2)

        # Transform pixel coords to AI artboard coords
        ab_w = ab["right"] - ab["left"]
        ab_h = ab["top"] - ab["bottom"]  # top > bottom in AI coordinate space

        scale_x = ab_w / img_w
        scale_y = ab_h / img_h
        scale = min(scale_x, scale_y)  # maintain aspect ratio

        # Center the silhouette on the artboard
        offset_x = ab["left"] + (ab_w - img_w * scale) / 2
        offset_y = ab["top"] - (ab_h - img_h * scale) / 2

        points_ai = []
        for pt in pixel_points:
            ai_x = pt[0] * scale + offset_x
            ai_y = offset_y - pt[1] * scale  # flip Y axis for AI coordinates
            points_ai.append([round(ai_x, 1), round(ai_y, 1)])

        # Step 5: Place the silhouette as a closed stroked path in Illustrator
        escaped_layer = escape_jsx_string(params.layer_name)
        points_json = json.dumps(points_ai)

        jsx_place = f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create the target layer
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i];
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}

    doc.activeLayer = layer;

    // Create the closed silhouette path
    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = true;
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = {params.stroke_width};

    // Default stroke color: black
    var black = new RGBColor();
    black.red = 0;
    black.green = 0;
    black.blue = 0;
    path.strokeColor = black;
    path.name = "silhouette";

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        pointCount: path.pathPoints.length,
        bounds: path.geometricBounds
    }});
}})();
"""
        place_result = await _async_run_jsx("illustrator", jsx_place)

        if not place_result["success"]:
            # Placement failed — still return silhouette data so the work is not lost
            return json.dumps({
                "point_count": len(points_ai),
                "points": points_ai,
                "simplification_used": params.simplification,
                "original_contour_points": extraction["original_contour_points"],
                "placed_in_ai": False,
                "coordinate_space": "illustrator_points",
                "placement_error": place_result["stderr"],
            }, indent=2)

        # Parse placement result
        try:
            placed_info = json.loads(place_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            placed_info = {"raw": place_result["stdout"]}

        return json.dumps({
            "point_count": len(points_ai),
            "points": points_ai,
            "simplification_used": params.simplification,
            "original_contour_points": extraction["original_contour_points"],
            "placed_in_ai": True,
            "layer": placed_info.get("layer", params.layer_name),
            "bounds": placed_info.get("bounds", []),
        }, indent=2)
