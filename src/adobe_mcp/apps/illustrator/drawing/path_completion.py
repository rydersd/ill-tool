"""MCP tool for predictive path completion along surface curvature.

Given 2-3 seed points on a reference image, predicts the completed path
by walking along the surface following the normal map curvature.  Can
optionally connect to existing edge fragments from extraction layers.

Actions:
- predict: Given seed points + image_path, predict the completed path.
- place: Predict + place as vector path in Illustrator.

Depends on:
- surface_extract._get_surface_type_map for cached normal/surface maps
- form_edge_pipeline.contours_to_ai_points for coordinate transforms
- form_edge_extract._build_place_jsx for Illustrator placement
- surface_classifier.find_sidecar / load_sidecar for edge fragment connection
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.form_edge_pipeline import contours_to_ai_points
from adobe_mcp.apps.illustrator.drawing.form_edge_extract import (
    _build_place_jsx,
    OUTPUT_DIR,
)
from adobe_mcp.apps.illustrator.drawing.surface_extract import (
    _get_surface_type_map,
)
from adobe_mcp.apps.illustrator.surface_classifier import (
    find_sidecar,
    load_sidecar,
)


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class PathCompletionInput(BaseModel):
    """Control predictive path completion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="predict",
        description="Action: predict | place.",
    )
    image_path: str = Field(
        default="",
        description="Absolute path to reference image (PNG/JPG).",
    )
    seed_points: list[list[float]] = Field(
        default_factory=list,
        description="2-3 user-placed points in pixel coords [[x,y], ...].",
    )
    max_extension: float = Field(
        default=200.0,
        description="Max pixels to extend in each direction.",
        ge=1.0,
        le=2000.0,
    )
    step_size: float = Field(
        default=2.0,
        description="Pixels per step along the surface.",
        ge=0.5,
        le=20.0,
    )
    layer_name: str = Field(
        default="Predicted Path",
        description="Illustrator layer name for placed paths.",
    )
    connect_existing: bool = Field(
        default=True,
        description="Try to connect to existing edge fragments.",
    )
    simplify_tolerance: float = Field(
        default=2.0,
        description="Douglas-Peucker simplification tolerance in pixels.",
        ge=0.0,
    )
    match_placed_item: bool = Field(
        default=True,
        description=(
            "When True, query for a PlacedItem on a 'ref' or 'Reference' layer "
            "and use its bounds for coordinate scaling."
        ),
    )


# ---------------------------------------------------------------------------
# Surface walking
# ---------------------------------------------------------------------------

# Curvature blending factor — controls how strongly curvature changes
# deflect the walking direction.  Higher = more responsive to surface
# shape, but can overshoot.  0.5 is a balanced default.
_CURVATURE_BLEND = 0.5

# Connection threshold in pixels — if a predicted path endpoint is
# within this distance of an existing edge fragment endpoint, extend
# the predicted path to connect.
_CONNECT_THRESHOLD_PX = 10.0


def _fit_quadratic_tangents(
    seed_points: list[list[float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit a quadratic curve through 3 seed points and return endpoint tangents.

    Returns:
        (start_point, start_tangent, end_point, end_tangent) as numpy arrays.
    """
    pts = np.array(seed_points, dtype=float)

    # Parameterize: t=0 at first point, t=1 at last point.
    # For 3 points use t = [0, 0.5, 1].
    t = np.array([0.0, 0.5, 1.0])

    # Fit quadratic: p(t) = a*t^2 + b*t + c
    # Solve for x and y independently
    T = np.column_stack([t**2, t, np.ones_like(t)])
    coeffs_x = np.linalg.lstsq(T, pts[:, 0], rcond=None)[0]
    coeffs_y = np.linalg.lstsq(T, pts[:, 1], rcond=None)[0]

    # Derivative: p'(t) = 2*a*t + b
    # At t=0: tangent = b
    start_tangent = np.array([coeffs_x[1], coeffs_y[1]])
    # At t=1: tangent = 2*a + b
    end_tangent = np.array([2 * coeffs_x[0] + coeffs_x[1],
                            2 * coeffs_y[0] + coeffs_y[1]])

    return pts[0], start_tangent, pts[-1], end_tangent


def _compute_tangents(
    seed_points: list[list[float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute start/end tangents from seed points.

    For 2 points: tangent = direction from p0 to p1.
    For 3 points: fit a quadratic through them.

    Returns:
        (start_point, start_tangent, end_point, end_tangent)
    """
    pts = np.array(seed_points, dtype=float)

    if len(pts) == 2:
        direction = pts[1] - pts[0]
        return pts[0], direction, pts[1], direction

    # 3 points: quadratic fit
    return _fit_quadratic_tangents(seed_points)


def should_stop(
    current: np.ndarray,
    prev: np.ndarray,
    surface_type_map: np.ndarray,
) -> bool:
    """Stop walking if we cross a surface type boundary."""
    cx, cy = int(current[0]), int(current[1])
    px, py = int(prev[0]), int(prev[1])
    h, w = surface_type_map.shape[:2]
    if (0 <= cx < w and 0 <= cy < h and
            0 <= px < w and 0 <= py < h):
        if surface_type_map[cy, cx] != surface_type_map[py, px]:
            return True
    return False


def walk_surface(
    start_point: np.ndarray,
    tangent: np.ndarray,
    normal_map: np.ndarray,
    stype_map: Optional[np.ndarray],
    step_size: float,
    max_steps: int,
) -> list[list[float]]:
    """Walk along the surface following the cross-contour perpendicular.

    At each step, projects the walking direction onto the surface tangent
    plane (perpendicular to the normal at that pixel) and advances.
    The direction is updated based on the curvature (change in normal)
    to smoothly follow the surface.

    Args:
        start_point: Starting position [x, y] in pixel coords.
        tangent: Initial walking direction [dx, dy].
        normal_map: HxWx3 float32 normal map.
        stype_map: Optional HxW uint8 surface type map for boundary detection.
        step_size: Pixels per step.
        max_steps: Maximum number of steps.

    Returns:
        List of [x, y] points along the walked path.
    """
    path: list[list[float]] = [start_point.tolist()]
    current = np.array(start_point, dtype=float)
    direction = np.array(tangent, dtype=float)
    norm = np.linalg.norm(direction)
    if norm < 1e-6:
        return path
    direction = direction / norm

    h, w = normal_map.shape[:2]

    for _step in range(max_steps):
        # Sample the normal at current position
        px, py = int(round(current[0])), int(round(current[1]))
        if px < 0 or px >= w or py < 0 or py >= h:
            break  # walked off the image

        normal = normal_map[py, px]  # [nx, ny, nz]

        # Project direction onto the surface tangent plane.
        # The tangent plane is perpendicular to the normal.
        # We only use the xy components of the normal for 2D projection.
        normal_xy = normal[:2]
        dot = np.dot(direction, normal_xy)
        projected = direction - dot * normal_xy
        proj_norm = np.linalg.norm(projected)
        if proj_norm < 1e-6:
            break  # direction is perpendicular to surface (edge)
        projected = projected / proj_norm

        # Advance along the projected direction
        prev = current.copy()
        current = current + projected * step_size
        path.append(current.tolist())

        # Check surface type boundary
        if stype_map is not None and should_stop(current, prev, stype_map):
            break

        # Update direction based on surface curvature.
        # Sample normal slightly ahead to detect curvature change.
        ahead = current + projected * step_size
        apx, apy = int(round(ahead[0])), int(round(ahead[1]))
        if 0 <= apx < w and 0 <= apy < h:
            normal_ahead = normal_map[apy, apx]
            # Adjust direction based on normal change (follow curvature)
            curvature = normal_ahead[:2] - normal[:2]
            direction = projected - curvature * _CURVATURE_BLEND
            dir_norm = np.linalg.norm(direction)
            if dir_norm < 1e-6:
                direction = projected
            else:
                direction = direction / dir_norm
        else:
            direction = projected

    return path


def _simplify_path(
    points: list[list[float]],
    tolerance: float,
) -> list[list[float]]:
    """Simplify an open polyline using Douglas-Peucker.

    Unlike edge_mask_to_contours which works on closed contours,
    this operates on an open path.

    Args:
        points: List of [x, y] coordinate pairs.
        tolerance: Douglas-Peucker epsilon.

    Returns:
        Simplified point list.
    """
    if len(points) < 3 or tolerance <= 0:
        return points

    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(pts, tolerance, closed=False)
    return simplified.reshape(-1, 2).tolist()


def _connect_to_existing(
    path_points: list[list[float]],
    sidecar_path: Optional[Path],
    image_path: str,
    threshold: float = _CONNECT_THRESHOLD_PX,
) -> tuple[list[list[float]], Optional[str]]:
    """Try to connect the path to existing edge fragment endpoints.

    Loads the sidecar JSON from previous extraction and checks if
    any path endpoints are near the predicted path's endpoints.

    Args:
        path_points: Predicted path as [[x, y], ...].
        sidecar_path: Path to the sidecar JSON.
        image_path: Original image path (used to find sidecar if not given).
        threshold: Maximum pixel distance for connection.

    Returns:
        (possibly_extended_path, connected_fragment_name_or_None)
    """
    if not sidecar_path:
        # Try to find sidecar from the image name
        basename = os.path.splitext(os.path.basename(image_path))[0]
        sidecar_path = find_sidecar(basename, cache_dir=OUTPUT_DIR)

    if not sidecar_path:
        return path_points, None

    sidecar = load_sidecar(str(sidecar_path))
    if not sidecar or not sidecar.paths:
        return path_points, None

    # We don't have the pixel-space points of existing paths in the sidecar
    # (it only has metadata). To connect, we would need the actual contour
    # points from a cached extraction. Check for cached contours JSON.
    contours_path = sidecar_path.parent / sidecar_path.name.replace(
        "_normals.json", "_contours.json"
    )
    if not contours_path.exists():
        return path_points, None

    try:
        contours_data = json.loads(contours_path.read_text())
    except (json.JSONDecodeError, OSError):
        return path_points, None

    if not isinstance(contours_data, list):
        return path_points, None

    # Check endpoints of our predicted path against all fragment endpoints
    path_start = np.array(path_points[0])
    path_end = np.array(path_points[-1])
    best_dist = threshold
    best_point = None
    best_name = None
    connect_end = "end"  # which end of our path to extend

    for fragment in contours_data:
        frag_points = fragment.get("points", [])
        if len(frag_points) < 2:
            continue

        frag_name = fragment.get("name", "unknown")
        frag_start = np.array(frag_points[0])
        frag_end = np.array(frag_points[-1])

        # Check all four combinations: our start/end vs fragment start/end
        for our_end, our_pt, label in [
            ("start", path_start, "start"),
            ("end", path_end, "end"),
        ]:
            for frag_pt in [frag_start, frag_end]:
                dist = float(np.linalg.norm(our_pt - frag_pt))
                if dist < best_dist:
                    best_dist = dist
                    best_point = frag_pt.tolist()
                    best_name = frag_name
                    connect_end = label

    if best_point is not None:
        if connect_end == "start":
            path_points = [best_point] + path_points
        else:
            path_points = path_points + [best_point]

    return path_points, best_name


def predict_path(
    image_path: str,
    seed_points: list[list[float]],
    max_extension: float = 200.0,
    step_size: float = 2.0,
    connect_existing: bool = True,
    simplify_tolerance: float = 2.0,
) -> dict:
    """Predict a completed path from seed points using normal map curvature.

    Args:
        image_path: Path to the reference image.
        seed_points: 2-3 seed points in pixel coords.
        max_extension: Max pixels to extend in each direction.
        step_size: Pixels per step.
        connect_existing: Whether to connect to existing edge fragments.
        simplify_tolerance: Douglas-Peucker simplification tolerance.

    Returns:
        Dict with predicted path, metadata, and optional connection info.
        Contains "error" key on failure.
    """
    t0 = time.time()

    # Validate seed points
    if len(seed_points) < 2:
        return {"error": "At least 2 seed points required."}
    if len(seed_points) > 3:
        return {"error": "At most 3 seed points supported."}

    # Validate image
    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Load or compute normal map + surface type map
    stype_result = _get_surface_type_map(image_path)
    if "error" in stype_result:
        return stype_result

    normal_map = stype_result["normal_map"]
    stype_map = stype_result["surface_type_map"]
    image_size = stype_result["image_size"]  # (w, h)
    was_cached = stype_result["cached"]
    map_time = stype_result["time_seconds"]

    w, h = image_size

    # Validate seed points are within image bounds
    for i, pt in enumerate(seed_points):
        if len(pt) != 2:
            return {"error": f"Seed point {i} must have exactly 2 coordinates."}
        if pt[0] < 0 or pt[0] >= w or pt[1] < 0 or pt[1] >= h:
            return {
                "error": (
                    f"Seed point {i} ({pt[0]}, {pt[1]}) is outside image bounds "
                    f"(0-{w - 1}, 0-{h - 1})."
                ),
            }

    max_steps = int(max_extension / step_size)

    # Compute tangent directions from seed points
    start_pt, start_tangent, end_pt, end_tangent = _compute_tangents(seed_points)

    # Walk backward from the start point (reverse tangent)
    backward_path = walk_surface(
        start_pt, -start_tangent, normal_map, stype_map, step_size, max_steps,
    )
    # Reverse so it goes from far end toward start
    backward_path.reverse()

    # Walk forward from the end point
    forward_path = walk_surface(
        end_pt, end_tangent, normal_map, stype_map, step_size, max_steps,
    )

    # Assemble full path: backward extension + seed points + forward extension
    # Remove duplicates at junctions (backward ends at start_pt, forward starts at end_pt)
    seed_list = [pt for pt in seed_points]
    full_path = backward_path[:-1] + seed_list + forward_path[1:]

    # Try to connect to existing edge fragments
    connected_fragment = None
    if connect_existing:
        full_path, connected_fragment = _connect_to_existing(
            full_path, None, image_path,
        )

    # Simplify the full path
    if simplify_tolerance > 0:
        full_path = _simplify_path(full_path, simplify_tolerance)

    t1 = time.time()

    result = {
        "points": full_path,
        "point_count": len(full_path),
        "seed_count": len(seed_points),
        "backward_steps": len(backward_path),
        "forward_steps": len(forward_path),
        "image_size": list(image_size),
        "surface_map_cached": was_cached,
        "timings": {
            "surface_map_seconds": map_time,
            "prediction_seconds": round(t1 - t0 - map_time, 4),
            "total_seconds": round(t1 - t0, 4),
        },
    }

    if connected_fragment:
        result["connected_to"] = connected_fragment

    return result


# ---------------------------------------------------------------------------
# JSX for open path placement (not closed like form edges)
# ---------------------------------------------------------------------------


def _build_open_path_jsx(
    path_points: list[list[float]],
    layer_name: str,
    path_name: str = "predicted_path",
) -> str:
    """Build JSX to place an open path with orange accent stroke.

    Unlike _build_place_jsx which creates closed paths with dark stroke,
    this creates an open path with orange stroke (accent color) at 1pt.

    Args:
        path_points: List of [x, y] in Illustrator coordinates.
        layer_name: Target layer name.
        path_name: Name for the placed path item.

    Returns:
        JSX string for execution in Illustrator.
    """
    from adobe_mcp.jsx.templates import escape_jsx_string

    escaped_layer = escape_jsx_string(layer_name)
    escaped_name = escape_jsx_string(path_name)
    points_json = json.dumps(path_points)

    return f"""
(function() {{
    var doc = app.activeDocument;
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

    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = false;
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = 1;

    // Accent color: orange
    var orange = new RGBColor();
    orange.red = 255; orange.green = 140; orange.blue = 0;
    path.strokeColor = orange;
    path.name = "{escaped_name}";

    // Smooth handles for curved appearance
    if (path.pathPoints.length >= 3) {{
        var n = path.pathPoints.length;
        for (var i = 0; i < n; i++) {{
            var pt = path.pathPoints[i];
            // First and last points: one-sided handles
            var prevIdx = Math.max(0, i - 1);
            var nextIdx = Math.min(n - 1, i + 1);
            var prev = path.pathPoints[prevIdx];
            var next = path.pathPoints[nextIdx];

            var tx = next.anchor[0] - prev.anchor[0];
            var ty = next.anchor[1] - prev.anchor[1];

            pt.leftDirection = [pt.anchor[0] - tx / 6.0, pt.anchor[1] - ty / 6.0];
            pt.rightDirection = [pt.anchor[0] + tx / 6.0, pt.anchor[1] + ty / 6.0];
        }}
    }}

    return JSON.stringify({{
        paths_placed: 1,
        path_name: path.name,
        point_count: path.pathPoints.length,
        layer: layer.name
    }});
}})();
"""


# ---------------------------------------------------------------------------
# JSON serializer for numpy types
# ---------------------------------------------------------------------------


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_predict_path tool."""

    @mcp.tool(
        name="adobe_ai_predict_path",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_predict_path(
        params: PathCompletionInput,
    ) -> str:
        """Predict and optionally place a completed path along surface curvature.

        Given 2-3 seed points on a reference image, walks along the
        surface following the normal map curvature, connecting to
        existing edge fragments when possible.

        Actions:
        - predict: Return predicted path as JSON (no Illustrator interaction)
        - place: Predict + place as vector path in Illustrator
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        # --- Predict the path ---
        prediction = predict_path(
            image_path=params.image_path,
            seed_points=params.seed_points,
            max_extension=params.max_extension,
            step_size=params.step_size,
            connect_existing=params.connect_existing,
            simplify_tolerance=params.simplify_tolerance,
        )

        if "error" in prediction:
            return json.dumps(prediction, indent=2)

        if action == "predict":
            return json.dumps(prediction, indent=2, default=_json_default)

        if action != "place":
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["predict", "place"],
            })

        # --- Place action: transform coords and place in Illustrator ---
        path_points = prediction["points"]
        image_size = tuple(prediction["image_size"])

        # Query artboard bounds
        jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
        ab_result = await _async_run_jsx("illustrator", jsx_info)
        if not ab_result["success"]:
            return json.dumps({
                "error": f"Could not query artboard: {ab_result.get('stderr', '')}",
                "prediction": prediction,
            })

        try:
            artboard = json.loads(ab_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "error": f"Bad artboard response: {ab_result.get('stdout', '')}",
                "prediction": prediction,
            })

        # PlacedItem bounds query (same pattern as surface_extract)
        target_bounds = artboard
        placed_item_matched = False

        if params.match_placed_item:
            jsx_placed = """
(function() {
    var doc = app.activeDocument;
    var refNames = ["ref", "Ref", "reference", "Reference"];
    for (var n = 0; n < refNames.length; n++) {
        try {
            var layer = doc.layers.getByName(refNames[n]);
        } catch(e) { continue; }
        for (var i = 0; i < layer.placedItems.length; i++) {
            var pi = layer.placedItems[i];
            var gb = pi.geometricBounds;
            return JSON.stringify({
                found: true,
                left: gb[0], top: gb[1], right: gb[2], bottom: gb[3],
                layer: layer.name, name: pi.name || ""
            });
        }
        for (var j = 0; j < layer.rasterItems.length; j++) {
            var ri = layer.rasterItems[j];
            var rb = ri.geometricBounds;
            return JSON.stringify({
                found: true,
                left: rb[0], top: rb[1], right: rb[2], bottom: rb[3],
                layer: layer.name, name: ri.name || ""
            });
        }
    }
    return JSON.stringify({found: false});
})();
"""
            pi_result = await _async_run_jsx("illustrator", jsx_placed)
            if pi_result["success"]:
                try:
                    pi_data = json.loads(pi_result["stdout"])
                    if pi_data.get("found"):
                        target_bounds = {
                            "left": pi_data["left"],
                            "top": pi_data["top"],
                            "right": pi_data["right"],
                            "bottom": pi_data["bottom"],
                        }
                        placed_item_matched = True
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

        # Transform path from pixel coords to AI coords
        # Wrap in contour format expected by contours_to_ai_points
        coord_margin = 1.0 if placed_item_matched else 0.95
        contour_wrapper = [{
            "name": "predicted_path",
            "points": path_points,
            "point_count": len(path_points),
            "area": 0.0,
        }]
        ai_contours = contours_to_ai_points(
            contour_wrapper, image_size, target_bounds, margin=coord_margin,
        )

        if not ai_contours:
            return json.dumps({
                "error": "Coordinate transform produced no points.",
                "prediction": prediction,
            })

        ai_points = ai_contours[0]["points"]

        # Build and execute JSX for open path placement
        jsx = _build_open_path_jsx(ai_points, params.layer_name)
        place_result = await _async_run_jsx("illustrator", jsx)

        if not place_result["success"]:
            return json.dumps({
                "error": f"Path placement failed: {place_result.get('stderr', '')}",
                "prediction": prediction,
            })

        try:
            place_data = json.loads(place_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            place_data = {"paths_placed": 1}

        # Build response
        response = {
            "action": "place",
            "paths_placed": place_data.get("paths_placed", 1),
            "path_name": place_data.get("path_name", "predicted_path"),
            "point_count": place_data.get("point_count", len(ai_points)),
            "layer_name": place_data.get("layer", params.layer_name),
            "seed_count": prediction["seed_count"],
            "backward_steps": prediction["backward_steps"],
            "forward_steps": prediction["forward_steps"],
            "image_size": prediction["image_size"],
            "surface_map_cached": prediction["surface_map_cached"],
            "timings": prediction["timings"],
        }

        if prediction.get("connected_to"):
            response["connected_to"] = prediction["connected_to"]
        if placed_item_matched:
            response["coordinate_source"] = "placed_item"

        return json.dumps(response, indent=2, default=_json_default)
