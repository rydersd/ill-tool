"""Bridge from analyze_reference shape manifest to Illustrator path.

Takes a single shape entry from the analyze_reference manifest (with
approx_points in pixel coordinates), transforms those coordinates to
Illustrator artboard space (scale + Y-flip + centering), and creates
the path via setEntirePath.  Optionally smooths corners into curves.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiContourToPathInput


def _from_face_group_boundary(
    boundary_polygon: list[tuple[float, float]],
    group_label: str,
    artboard_dims: dict,
) -> dict:
    """Convert mesh_face_grouper boundary output to contour_to_path shape dict.

    Transforms a 2D boundary polygon (already projected from 3D) into the
    shape dict format expected by _create_path_jsx() and the contour_to_path
    tool -- specifically the "approx_points" key in pixel/AI coordinates.

    The boundary polygon comes from orthographic projection (raw world units),
    so we normalize it into the artboard coordinate space:
    1. Compute bounding box of all boundary points
    2. Scale points to fit within artboard dimensions (maintaining aspect ratio)
    3. Center on artboard
    4. Flip Y axis (AI coordinates: Y increases upward)

    Args:
        boundary_polygon: List of (x, y) tuples in projected 2D coordinates.
        group_label: Label string like "front_face", "top_face".
        artboard_dims: Dict with 'width' and 'height' keys (artboard size in points).

    Returns:
        Shape dict with "name", "approx_points" (list of [x, y] in AI
        coordinate space), and "point_count" -- compatible with the existing
        contour_to_path tool's shape_json format.
    """
    if not boundary_polygon:
        return {"name": group_label, "approx_points": [], "point_count": 0}

    ab_w = artboard_dims["width"]
    ab_h = artboard_dims["height"]

    # Convert tuples to lists and compute bounding box of projected polygon
    xs = [p[0] for p in boundary_polygon]
    ys = [p[1] for p in boundary_polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    poly_w = max_x - min_x if max_x > min_x else 1.0
    poly_h = max_y - min_y if max_y > min_y else 1.0

    # Scale to fit artboard (with 10% margin), maintain aspect ratio
    margin = 0.9
    scale = min((ab_w * margin) / poly_w, (ab_h * margin) / poly_h)

    # Center offset
    cx = (ab_w - poly_w * scale) / 2.0
    cy = (ab_h - poly_h * scale) / 2.0

    # Transform: scale, center, and flip Y for AI coordinates
    points_ai = []
    for px, py in boundary_polygon:
        ai_x = (px - min_x) * scale + cx
        ai_y = ab_h - ((py - min_y) * scale + cy)  # Y-flip for AI space
        points_ai.append([round(ai_x, 2), round(ai_y, 2)])

    return {
        "name": group_label,
        "approx_points": points_ai,
        "point_count": len(points_ai),
    }


def register(mcp):
    """Register the adobe_ai_contour_to_path tool."""

    @mcp.tool(
        name="adobe_ai_contour_to_path",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_contour_to_path(params: AiContourToPathInput) -> str:
        """Create an Illustrator path from an analyze_reference shape manifest entry.

        Parses the shape JSON for approx_points (pixel coordinates), queries the
        active artboard for dimensions, transforms pixel coords to AI coords
        (scale, Y-flip, centering), then creates a named path.  When smooth=True,
        sets bezier handles to 1/3 of the distance to adjacent anchors for curves.
        """
        # ── 1. Parse shape JSON ────────────────────────────────────────────
        try:
            shape = json.loads(params.shape_json)
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"Invalid shape_json: {exc}"})

        pixel_points = shape.get("approx_points")
        if not pixel_points or not isinstance(pixel_points, list):
            return json.dumps({"error": "shape_json must contain 'approx_points' array of [x,y] pixel coordinates"})

        # ── 2. Determine source image size ─────────────────────────────────
        # Prefer explicit image_size param; fall back to shape metadata
        img_w, img_h = None, None
        if params.image_size:
            try:
                img_size = json.loads(params.image_size)
                img_w, img_h = float(img_size[0]), float(img_size[1])
            except (json.JSONDecodeError, TypeError, IndexError, ValueError):
                return json.dumps({"error": f"Invalid image_size — expected JSON [width, height], got: {params.image_size}"})

        # If image_size was not provided, try to infer from shape bounding box
        if img_w is None or img_h is None:
            # Use the shape's own extents as a rough fallback (will not center
            # perfectly but still produces a usable path)
            xs = [pt[0] for pt in pixel_points]
            ys = [pt[1] for pt in pixel_points]
            img_w = max(xs) * 1.1  # add 10% margin
            img_h = max(ys) * 1.1

        # ── 3. Get artboard dimensions from Illustrator ────────────────────
        jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
        ab_result = await _async_run_jsx("illustrator", jsx_info)
        if not ab_result["success"]:
            return json.dumps({"error": f"Could not query artboard: {ab_result['stderr']}"})

        try:
            ab = json.loads(ab_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": f"Bad artboard response: {ab_result['stdout']}"})

        ab_w = ab["right"] - ab["left"]
        ab_h = ab["top"] - ab["bottom"]  # top > bottom in AI coordinate space

        # ── 4. Transform pixel coords to AI artboard coords ───────────────
        scale_x = ab_w / img_w
        scale_y = ab_h / img_h
        scale = min(scale_x, scale_y)  # maintain aspect ratio

        # Center the path on the artboard
        offset_x = ab["left"] + (ab_w - img_w * scale) / 2
        offset_y = ab["top"] - (ab_h - img_h * scale) / 2

        points_ai = []
        for pt in pixel_points:
            ai_x = pt[0] * scale + offset_x
            ai_y = offset_y - pt[1] * scale  # flip Y axis for AI coordinates
            points_ai.append([round(ai_x, 2), round(ai_y, 2)])

        # ── 5. Build JSX to create path ────────────────────────────────────
        escaped_layer = escape_jsx_string(params.layer_name)
        escaped_name = escape_jsx_string(params.path_name)
        points_json = json.dumps(points_ai)
        closed_js = "true" if params.closed else "false"
        smooth_js = "true" if params.smooth else "false"

        jsx_create = f"""
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

    // Create the path from transformed points
    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = {closed_js};
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = {params.stroke_width};

    // Default stroke: black
    var black = new RGBColor();
    black.red = 0;
    black.green = 0;
    black.blue = 0;
    path.strokeColor = black;
    path.name = "{escaped_name}";

    // Optional smoothing: set bezier handles to 1/3 distance to neighbors
    if ({smooth_js} && path.pathPoints.length >= 3) {{
        var n = path.pathPoints.length;
        for (var i = 0; i < n; i++) {{
            var pt = path.pathPoints[i];
            var prevIdx = (i - 1 + n) % n;
            var nextIdx = (i + 1) % n;
            var prev = path.pathPoints[prevIdx];
            var next = path.pathPoints[nextIdx];

            // Handle towards previous point (left direction)
            var dx_l = (pt.anchor[0] - prev.anchor[0]) / 3;
            var dy_l = (pt.anchor[1] - prev.anchor[1]) / 3;
            // Handle towards next point (right direction)
            var dx_r = (next.anchor[0] - pt.anchor[0]) / 3;
            var dy_r = (next.anchor[1] - pt.anchor[1]) / 3;

            pt.leftDirection = [pt.anchor[0] - dx_l, pt.anchor[1] - dy_l];
            pt.rightDirection = [pt.anchor[0] + dx_r, pt.anchor[1] + dy_r];
        }}
    }}

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        pointCount: path.pathPoints.length,
        bounds: path.geometricBounds,
        smoothed: {smooth_js}
    }});
}})();
"""
        create_result = await _async_run_jsx("illustrator", jsx_create)

        if not create_result["success"]:
            # Return transformed points even on failure so the work is not lost
            return json.dumps({
                "error": f"Path creation failed: {create_result['stderr']}",
                "transformed_points": points_ai,
                "point_count": len(points_ai),
                "coordinate_space": "illustrator_points",
            }, indent=2)

        # ── 6. Parse and return result ─────────────────────────────────────
        try:
            placed = json.loads(create_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            placed = {"raw": create_result["stdout"]}

        return json.dumps({
            "name": placed.get("name", params.path_name),
            "layer": placed.get("layer", params.layer_name),
            "point_count": placed.get("pointCount", len(points_ai)),
            "bounds": placed.get("bounds", []),
            "smoothed": placed.get("smoothed", params.smooth),
            "scale_used": round(scale, 4),
            "coordinate_transform": {
                "image_size": [img_w, img_h],
                "artboard_size": [ab_w, ab_h],
                "scale": round(scale, 4),
                "offset": [round(offset_x, 2), round(offset_y, 2)],
            },
        }, indent=2)
