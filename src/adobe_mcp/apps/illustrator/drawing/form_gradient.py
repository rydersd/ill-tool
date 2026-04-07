"""MCP tool for surface-aware form gradients in Illustrator.

Computes gradient blend steps between two paths that follow surface
curvature rather than linear interpolation. Uses the normal map's
cross-contour flow field to make blends wrap around 3D form.

Actions:
- preview: Compute blend paths and colors without placing in Illustrator.
- place: Compute and place the gradient as colored stroke paths.
"""

import json
import math
import os
import time
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class FormGradientInput(BaseModel):
    """Control form gradient computation and placement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="preview",
        description=(
            "Action: preview | place. "
            "preview = compute blend paths + colors, return as JSON. "
            "place = compute and place as colored paths in Illustrator."
        ),
    )
    image_path: str = Field(
        default="",
        description=(
            "Absolute path to reference image (PNG/JPG) for normal map "
            "estimation. Required for surface-aware flow. If empty, falls "
            "back to linear interpolation."
        ),
    )
    path_a_points: list[list[float]] = Field(
        default_factory=list,
        description="Start path points as [[x, y], ...] in Illustrator coordinates.",
    )
    path_b_points: list[list[float]] = Field(
        default_factory=list,
        description="End path points as [[x, y], ...] in Illustrator coordinates.",
    )
    num_steps: int = Field(
        default=10,
        description="Number of blend steps between the two paths.",
        ge=2,
        le=100,
    )
    color_start: list[float] = Field(
        default=[0.0, 0.0, 0.0],
        description="Start color as [R, G, B] where each is 0-255.",
    )
    color_end: list[float] = Field(
        default=[255.0, 255.0, 255.0],
        description="End color as [R, G, B] where each is 0-255.",
    )
    layer_name: str = Field(
        default="Form Gradient",
        description="Illustrator layer name for placed gradient paths.",
    )
    stroke_width: float = Field(
        default=1.0,
        description="Stroke width for gradient paths in points.",
        ge=0.1,
        le=20.0,
    )


# ---------------------------------------------------------------------------
# Path resampling
# ---------------------------------------------------------------------------


def _resample_path(points, num_samples):
    """Resample a polyline to have exactly num_samples evenly spaced points.

    Uses linear interpolation along the path's arc length.

    Args:
        points: List of [x, y] points.
        num_samples: Target number of output points.

    Returns:
        List of [x, y] points, evenly spaced along the arc.
    """
    if len(points) < 2 or num_samples < 2:
        return [list(p) for p in points]

    # Compute cumulative arc lengths
    arc_lengths = [0.0]
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        arc_lengths.append(arc_lengths[-1] + math.sqrt(dx * dx + dy * dy))

    total_length = arc_lengths[-1]
    if total_length < 1e-12:
        return [list(points[0])] * num_samples

    result = []
    for s in range(num_samples):
        target = (s / (num_samples - 1)) * total_length

        # Find the segment containing this arc length
        seg = 0
        for j in range(1, len(arc_lengths)):
            if arc_lengths[j] >= target:
                seg = j - 1
                break
        else:
            seg = len(arc_lengths) - 2

        seg_start = arc_lengths[seg]
        seg_end = arc_lengths[seg + 1]
        seg_len = seg_end - seg_start

        if seg_len < 1e-12:
            t = 0.0
        else:
            t = (target - seg_start) / seg_len

        x = points[seg][0] + t * (points[seg + 1][0] - points[seg][0])
        y = points[seg][1] + t * (points[seg + 1][1] - points[seg][1])
        result.append([x, y])

    return result


# ---------------------------------------------------------------------------
# Surface flow field loading
# ---------------------------------------------------------------------------


def _load_or_compute_flow(image_path):
    """Load normal map and compute surface flow field.

    Returns (flow_field, normal_map) or (None, None) on failure.
    flow_field is HxWx4: (dir1_x, dir1_y, dir2_x, dir2_y).
    """
    if not image_path or not os.path.isfile(image_path):
        return None, None

    try:
        from adobe_mcp.apps.illustrator.normal_renderings import (
            surface_flow_field,
        )
    except ImportError:
        return None, None

    # Check for cached normal map next to the image
    import tempfile
    cache_dir = os.path.join(
        tempfile.gettempdir(), f"ai_form_edges_{os.getuid()}"
    )
    nmap_cache = os.path.join(cache_dir, "normal_map.npy")

    normal_map = None

    # Try cached normal map first
    if os.path.isfile(nmap_cache):
        try:
            normal_map = np.load(nmap_cache)
        except Exception:
            normal_map = None

    # Estimate normals if no cache
    if normal_map is None:
        try:
            from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
                estimate_normals,
                DSINE_AVAILABLE,
            )
            if not DSINE_AVAILABLE:
                return None, None
            result = estimate_normals(image_path, model="dsine")
            if "error" in result:
                return None, None
            normal_map = result["normal_map"]
        except ImportError:
            return None, None

    if normal_map is None:
        return None, None

    try:
        flow = surface_flow_field(normal_map)
        return flow, normal_map
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Curvature computation for non-uniform color spacing
# ---------------------------------------------------------------------------


def _compute_curvature_weights(normal_map, path_a, path_b, num_steps):
    """Compute per-step curvature weights for non-uniform color spacing.

    Samples mean curvature along the interpolation direction. High-curvature
    regions get tighter color steps (gradient compresses), flat regions get
    wider steps (gradient stretches).

    Args:
        normal_map: HxWx3 float32 normal map.
        path_a: Resampled start path points.
        path_b: Resampled end path points.
        num_steps: Number of blend steps.

    Returns:
        List of float weights (sum = 1.0), one per step transition.
    """
    try:
        from adobe_mcp.apps.illustrator.normal_renderings import principal_curvatures
        pc = principal_curvatures(normal_map)
    except Exception:
        # Uniform weights as fallback
        n = max(1, num_steps - 1)
        return [1.0 / n] * n

    h, w = normal_map.shape[:2]
    mean_curv = np.abs(pc[:, :, 0])  # Mean curvature channel

    weights = []
    for step in range(num_steps - 1):
        t = (step + 0.5) / (num_steps - 1)  # Sample at midpoint of transition
        total_curv = 0.0
        sample_count = 0

        for i in range(len(path_a)):
            # Interpolated sample position
            x = path_a[i][0] * (1 - t) + path_b[i][0] * t
            y = path_a[i][1] * (1 - t) + path_b[i][1] * t
            px, py = int(round(x)), int(round(y))

            if 0 <= px < w and 0 <= py < h:
                total_curv += float(mean_curv[py, px])
                sample_count += 1

        avg_curv = total_curv / max(1, sample_count)
        # Higher curvature = tighter step (larger weight)
        weights.append(max(0.01, avg_curv + 0.1))

    # Normalize to sum to 1
    total = sum(weights)
    if total > 1e-12:
        weights = [w / total for w in weights]
    else:
        n = len(weights)
        weights = [1.0 / n] * n

    return weights


# ---------------------------------------------------------------------------
# Flow-following interpolation
# ---------------------------------------------------------------------------


def interpolate_flow_path(path_a, path_b, t, surface_flow):
    """Interpolate between two paths following the surface flow field.

    Starts with linear interpolation, then adjusts each point along the
    cross-contour direction from the flow field. This makes the blend
    follow surface curvature rather than cutting through the form.

    Args:
        path_a: Start path points (resampled).
        path_b: End path points (resampled, same count as path_a).
        t: Interpolation parameter 0-1.
        surface_flow: HxWx4 flow field (dir1_x, dir1_y, dir2_x, dir2_y)
            or None for pure linear interpolation.

    Returns:
        List of [x, y] interpolated points.
    """
    interp = []
    for i in range(len(path_a)):
        x = (1 - t) * path_a[i][0] + t * path_b[i][0]
        y = (1 - t) * path_a[i][1] + t * path_b[i][1]
        interp.append([x, y])

    if surface_flow is None:
        return interp

    h, w = surface_flow.shape[:2]

    for i, pt in enumerate(interp):
        px, py = int(round(pt[0])), int(round(pt[1]))
        if 0 <= px < w and 0 <= py < h:
            # Use the second principal direction (cross-contour)
            flow_x = float(surface_flow[py, px, 2])
            flow_y = float(surface_flow[py, px, 3])

            # Scale adjustment by distance from center (t=0.5)
            # and by flow magnitude, creating a subtle curvature-following effect
            flow_mag = math.sqrt(flow_x * flow_x + flow_y * flow_y)
            if flow_mag > 1e-6:
                adjustment = flow_mag * 2.0 * (t - 0.5)
                interp[i][0] += flow_x * adjustment
                interp[i][1] += flow_y * adjustment

    return interp


# ---------------------------------------------------------------------------
# Blend computation
# ---------------------------------------------------------------------------


def compute_blend(
    path_a_points,
    path_b_points,
    num_steps,
    color_start,
    color_end,
    surface_flow=None,
    normal_map=None,
):
    """Compute the full set of blend paths and colors.

    Args:
        path_a_points: Start path [[x, y], ...].
        path_b_points: End path [[x, y], ...].
        num_steps: Number of blend steps.
        color_start: [R, G, B] 0-255.
        color_end: [R, G, B] 0-255.
        surface_flow: Optional HxWx4 flow field.
        normal_map: Optional HxWx3 normal map for curvature weighting.

    Returns:
        Dict with blend_paths list and metadata.
    """
    # Resample both paths to the same number of sample points
    num_samples = max(len(path_a_points), len(path_b_points), 20)
    path_a = _resample_path(path_a_points, num_samples)
    path_b = _resample_path(path_b_points, num_samples)

    # Compute curvature weights for non-uniform color spacing
    if normal_map is not None:
        curv_weights = _compute_curvature_weights(normal_map, path_a, path_b, num_steps)
    else:
        n = max(1, num_steps - 1)
        curv_weights = [1.0 / n] * n

    # Accumulate weights to get color t values
    color_t_values = [0.0]
    running = 0.0
    for w in curv_weights:
        running += w
        color_t_values.append(running)
    # Normalize to [0, 1]
    if color_t_values[-1] > 1e-12:
        color_t_values = [v / color_t_values[-1] for v in color_t_values]

    blend_paths = []
    for step in range(num_steps):
        # Geometric interpolation parameter (uniform)
        t = step / max(1, num_steps - 1)

        # Color interpolation parameter (curvature-weighted)
        ct = color_t_values[step]

        # Interpolate path with flow following
        points = interpolate_flow_path(path_a, path_b, t, surface_flow)

        # Interpolate color
        r = color_start[0] + ct * (color_end[0] - color_start[0])
        g = color_start[1] + ct * (color_end[1] - color_start[1])
        b = color_start[2] + ct * (color_end[2] - color_start[2])

        blend_paths.append({
            "step": step,
            "t": round(t, 4),
            "color_t": round(ct, 4),
            "points": [[round(p[0], 2), round(p[1], 2)] for p in points],
            "point_count": len(points),
            "color": [round(r, 1), round(g, 1), round(b, 1)],
        })

    return {
        "blend_paths": blend_paths,
        "num_steps": num_steps,
        "num_samples_per_path": num_samples,
        "flow_available": surface_flow is not None,
        "curvature_weighted": normal_map is not None,
    }


# ---------------------------------------------------------------------------
# JSX generation for Illustrator placement
# ---------------------------------------------------------------------------


def _build_gradient_jsx(blend_paths, layer_name, stroke_width=1.0):
    """Build JSX to place gradient blend paths in Illustrator.

    Each blend step becomes a stroked path with the interpolated color.

    Args:
        blend_paths: List of blend path dicts from compute_blend.
        layer_name: Illustrator layer name.
        stroke_width: Stroke width in points.

    Returns:
        JSX string for execution.
    """
    from adobe_mcp.jsx.templates import escape_jsx_string

    escaped_layer = escape_jsx_string(layer_name)

    path_blocks = []
    for bp in blend_paths:
        points = bp["points"]
        if len(points) < 2:
            continue

        color = bp["color"]
        name = escape_jsx_string(f"grad_step_{bp['step']:03d}")
        points_json = json.dumps(points)

        path_blocks.append(f"""
        (function() {{
            var path = layer.pathItems.add();
            path.setEntirePath({points_json});
            path.closed = false;
            path.filled = false;
            path.stroked = true;
            path.strokeWidth = {stroke_width};
            var color = new RGBColor();
            color.red = {round(color[0])}; color.green = {round(color[1])}; color.blue = {round(color[2])};
            path.strokeColor = color;
            path.name = "{name}";
            paths.push({{name: "{name}", points: {len(points)}}});
        }})();""")

    if not path_blocks:
        return None

    jsx = f"""(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("{escaped_layer}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}

    var paths = [];
    {"".join(path_blocks)}

    return JSON.stringify({{
        layer: "{escaped_layer}",
        paths_placed: paths.length,
        paths: paths
    }});
}})();"""

    return jsx


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_form_gradient tool."""

    @mcp.tool(
        name="adobe_ai_form_gradient",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_form_gradient(
        params: FormGradientInput,
    ) -> str:
        """Compute and place surface-aware form gradients.

        Creates gradient blends between two paths that follow the 3D
        surface curvature instead of interpolating linearly. Uses the
        normal map's cross-contour flow field to make blend steps wrap
        around form, and curvature-weighted color spacing to compress
        gradients on high-curvature areas and stretch them on flat areas.

        Actions:
        - preview: Compute blend paths and colors, return as JSON
        - place: Compute and place as colored stroke paths in Illustrator

        When image_path is provided: computes normal map and uses surface
        flow for path interpolation + curvature-weighted color spacing.
        Without image_path: falls back to linear interpolation with
        uniform color spacing.
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        if not params.path_a_points or len(params.path_a_points) < 2:
            return json.dumps(
                {"error": "path_a_points requires at least 2 points."},
                indent=2,
            )
        if not params.path_b_points or len(params.path_b_points) < 2:
            return json.dumps(
                {"error": "path_b_points requires at least 2 points."},
                indent=2,
            )

        t0 = time.time()

        # Load surface flow if image provided
        surface_flow = None
        normal_map = None
        if params.image_path:
            surface_flow, normal_map = _load_or_compute_flow(params.image_path)

        # Compute blend
        blend_result = compute_blend(
            path_a_points=params.path_a_points,
            path_b_points=params.path_b_points,
            num_steps=params.num_steps,
            color_start=params.color_start,
            color_end=params.color_end,
            surface_flow=surface_flow,
            normal_map=normal_map,
        )

        t1 = time.time()
        blend_result["timings"] = {"compute_seconds": round(t1 - t0, 4)}

        if action == "preview":
            return json.dumps(blend_result, indent=2)

        elif action == "place":
            # Build and execute JSX
            jsx = _build_gradient_jsx(
                blend_result["blend_paths"],
                params.layer_name,
                stroke_width=params.stroke_width,
            )

            if jsx is None:
                return json.dumps({
                    "error": "No valid blend paths to place.",
                    "blend_result": blend_result,
                })

            place_result = await _async_run_jsx("illustrator", jsx)

            if not place_result["success"]:
                return json.dumps({
                    "error": f"JSX execution failed: {place_result.get('stderr', 'unknown')}",
                    "blend_paths_count": len(blend_result["blend_paths"]),
                })

            try:
                place_data = json.loads(place_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                place_data = {"paths_placed": 0}

            t2 = time.time()

            response = {
                "paths_placed": place_data.get("paths_placed", 0),
                "layer_name": place_data.get("layer", params.layer_name),
                "num_steps": params.num_steps,
                "flow_available": blend_result["flow_available"],
                "curvature_weighted": blend_result["curvature_weighted"],
                "timings": {
                    "compute_seconds": blend_result["timings"]["compute_seconds"],
                    "place_seconds": round(t2 - t1, 4),
                    "total_seconds": round(t2 - t0, 4),
                },
            }
            return json.dumps(response, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["preview", "place"],
            })
