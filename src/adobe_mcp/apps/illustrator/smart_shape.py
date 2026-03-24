"""High-level shape creation from descriptive parameters.

Computes vertex positions in Python (polygon/star/rectangle math), then
sends the resulting points to Illustrator via setEntirePath.  For ellipses,
uses the native pathItems.ellipse() API for proper bezier handles.

Supports: hexagon, pentagon, triangle, rectangle, ellipse, star, polygon
with arbitrary center, dimensions, rotation, and side count.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSmartShapeInput


# ── Vertex computation helpers ─────────────────────────────────────────────

# Map friendly names to side counts for common regular polygons
_NAMED_POLYGONS = {
    "triangle": 3,
    "pentagon": 5,
    "hexagon": 6,
}


def _regular_polygon_vertices(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    sides: int,
    rotation: float,
) -> list[list[float]]:
    """Compute vertices for a regular polygon inscribed in an ellipse.

    Points start at the top (12 o'clock) and go clockwise.  Rotation is
    applied in degrees (positive = counterclockwise in standard math,
    which maps to counterclockwise in AI's Y-down-from-top coordinate space).
    """
    points = []
    for i in range(sides):
        # Start at -pi/2 (top), add rotation offset
        angle = 2 * math.pi * i / sides - math.pi / 2 + math.radians(rotation)
        x = center_x + (width / 2) * math.cos(angle)
        y = center_y + (height / 2) * math.sin(angle)
        points.append([round(x, 2), round(y, 2)])
    return points


def _rectangle_vertices(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    rotation: float,
) -> list[list[float]]:
    """Compute 4 corners of a rotated rectangle."""
    hw, hh = width / 2, height / 2
    # Corners relative to center (before rotation)
    corners = [
        (-hw, -hh),  # top-left
        (hw, -hh),   # top-right
        (hw, hh),    # bottom-right
        (-hw, hh),   # bottom-left
    ]
    rad = math.radians(rotation)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    points = []
    for dx, dy in corners:
        rx = dx * cos_r - dy * sin_r + center_x
        ry = dx * sin_r + dy * cos_r + center_y
        points.append([round(rx, 2), round(ry, 2)])
    return points


def _star_vertices(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    sides: int,
    rotation: float,
) -> list[list[float]]:
    """Compute vertices for a star with alternating outer/inner radii.

    The inner radius is half the outer radius, producing a classic star shape.
    sides = number of points on the star (total vertices = sides * 2).
    """
    outer_rx, outer_ry = width / 2, height / 2
    inner_rx, inner_ry = outer_rx / 2, outer_ry / 2
    total = sides * 2
    points = []
    for i in range(total):
        angle = 2 * math.pi * i / total - math.pi / 2 + math.radians(rotation)
        if i % 2 == 0:
            # Outer vertex
            x = center_x + outer_rx * math.cos(angle)
            y = center_y + outer_ry * math.sin(angle)
        else:
            # Inner vertex
            x = center_x + inner_rx * math.cos(angle)
            y = center_y + inner_ry * math.sin(angle)
        points.append([round(x, 2), round(y, 2)])
    return points


def _ellipse_approximation_vertices(
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    rotation: float,
    num_points: int = 16,
) -> list[list[float]]:
    """Approximate an ellipse with evenly-spaced points (fallback only).

    Used when rotation != 0, since the native AI ellipse() cannot be rotated
    at creation time.  For unrotated ellipses, the native API is preferred.
    """
    points = []
    rad = math.radians(rotation)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        # Unrotated point on ellipse
        ex = (width / 2) * math.cos(angle)
        ey = (height / 2) * math.sin(angle)
        # Apply rotation around center
        x = ex * cos_r - ey * sin_r + center_x
        y = ex * sin_r + ey * cos_r + center_y
        points.append([round(x, 2), round(y, 2)])
    return points


# ── Tool registration ──────────────────────────────────────────────────────

def register(mcp):
    """Register the adobe_ai_smart_shape tool."""

    @mcp.tool(
        name="adobe_ai_smart_shape",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_smart_shape(params: AiSmartShapeInput) -> str:
        """Create a shape from high-level parameters: type, center, dimensions,
        rotation.  Supports hexagon, pentagon, triangle, rectangle, ellipse,
        star, and arbitrary N-sided polygon.

        Vertex positions are computed in Python for precision, then sent to
        Illustrator as a path.  Ellipses without rotation use the native AI
        ellipse API for proper bezier curves.
        """
        shape = params.shape_type.lower().strip()
        escaped_layer = escape_jsx_string(params.layer_name)
        escaped_name = escape_jsx_string(params.name)

        # ── Determine if we should use the native ellipse API ──────────
        use_native_ellipse = shape == "ellipse" and params.rotation == 0

        if use_native_ellipse:
            # Native AI ellipse: pathItems.ellipse(top, left, width, height)
            # AI coords: top-left corner, Y increases upward
            top = params.center_y + params.height / 2
            left = params.center_x - params.width / 2

            jsx = f"""
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

    var path = doc.pathItems.ellipse({top}, {left}, {params.width}, {params.height});
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = {params.stroke_width};

    var black = new RGBColor();
    black.red = 0;
    black.green = 0;
    black.blue = 0;
    path.strokeColor = black;
    path.name = "{escaped_name}";

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        pointCount: path.pathPoints.length,
        bounds: path.geometricBounds,
        shapeType: "ellipse",
        isNative: true
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": f"Native ellipse creation failed: {result['stderr']}"})

            try:
                placed = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                placed = {"raw": result["stdout"]}

            return json.dumps({
                "name": placed.get("name", params.name),
                "layer": placed.get("layer", params.layer_name),
                "point_count": placed.get("pointCount", 4),
                "bounds": placed.get("bounds", []),
                "shape_type": "ellipse",
                "native_api": True,
                "center": [params.center_x, params.center_y],
                "dimensions": [params.width, params.height],
            }, indent=2)

        # ── Compute vertices in Python ─────────────────────────────────
        vertices = []

        if shape in _NAMED_POLYGONS:
            sides = _NAMED_POLYGONS[shape]
            vertices = _regular_polygon_vertices(
                params.center_x, params.center_y,
                params.width, params.height,
                sides, params.rotation,
            )
        elif shape == "polygon":
            vertices = _regular_polygon_vertices(
                params.center_x, params.center_y,
                params.width, params.height,
                params.sides, params.rotation,
            )
        elif shape == "rectangle":
            vertices = _rectangle_vertices(
                params.center_x, params.center_y,
                params.width, params.height,
                params.rotation,
            )
        elif shape == "star":
            vertices = _star_vertices(
                params.center_x, params.center_y,
                params.width, params.height,
                params.sides, params.rotation,
            )
        elif shape == "ellipse":
            # Rotated ellipse — approximate with 16 points
            vertices = _ellipse_approximation_vertices(
                params.center_x, params.center_y,
                params.width, params.height,
                params.rotation, num_points=16,
            )
        else:
            return json.dumps({
                "error": f"Unknown shape_type: '{params.shape_type}'. "
                         f"Supported: hexagon, pentagon, triangle, rectangle, ellipse, star, polygon"
            })

        if not vertices:
            return json.dumps({"error": "No vertices computed — check parameters"})

        # ── Build JSX to create path from computed vertices ────────────
        points_json = json.dumps(vertices)

        jsx = f"""
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

    // Create the shape path from computed vertices
    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = true;
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = {params.stroke_width};

    var black = new RGBColor();
    black.red = 0;
    black.green = 0;
    black.blue = 0;
    path.strokeColor = black;
    path.name = "{escaped_name}";

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        pointCount: path.pathPoints.length,
        bounds: path.geometricBounds,
        shapeType: "{escape_jsx_string(shape)}",
        isNative: false
    }});
}})();
"""
        result = await _async_run_jsx("illustrator", jsx)

        if not result["success"]:
            # Return computed vertices even on placement failure
            return json.dumps({
                "error": f"Shape creation failed: {result['stderr']}",
                "computed_vertices": vertices,
                "vertex_count": len(vertices),
            }, indent=2)

        # ── Parse and return result ────────────────────────────────────
        try:
            placed = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            placed = {"raw": result["stdout"]}

        return json.dumps({
            "name": placed.get("name", params.name),
            "layer": placed.get("layer", params.layer_name),
            "point_count": placed.get("pointCount", len(vertices)),
            "bounds": placed.get("bounds", []),
            "shape_type": shape,
            "native_api": False,
            "center": [params.center_x, params.center_y],
            "dimensions": [params.width, params.height],
            "rotation": params.rotation,
            "computed_vertices": vertices,
        }, indent=2)
