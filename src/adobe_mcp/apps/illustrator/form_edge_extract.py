"""MCP tool for form edge extraction and placement in Illustrator.

Wraps the pure-Python form_edge_pipeline module with MCP tool
registration, Illustrator JSX generation, and action dispatching.

Actions:
- status: Report available backends (heuristic, dsine) and their readiness.
- extract: Run pipeline, return contours as JSON (no Illustrator interaction).
- place: Extract + place as vector paths on a new Illustrator layer.
- compare: Extract form edges from two images, compute IoU similarity.
"""

import json
import os
import time
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.form_edge_pipeline import (
    contours_to_ai_points,
    dsine_form_edges,
    edge_mask_to_contours,
    extract_form_edges,
    heuristic_form_edges,
)


# ---------------------------------------------------------------------------
# Check backend availability at import time
# ---------------------------------------------------------------------------

try:
    from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
        DSINE_AVAILABLE,
    )
except ImportError:
    DSINE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Output directory for cached edge masks
# ---------------------------------------------------------------------------

OUTPUT_DIR = "/tmp/ai_form_edges"


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class FormEdgeExtractInput(BaseModel):
    """Control form edge extraction and placement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="status",
        description=(
            "Action: status | extract | place | compare. "
            "status = report available backends. "
            "extract = run pipeline, return contours as JSON (no Illustrator). "
            "place = extract + place as vector paths in Illustrator. "
            "compare = extract from two images, compute IoU similarity."
        ),
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Absolute path to reference image (PNG/JPG). Required for extract/place.",
    )
    image_path_b: Optional[str] = Field(
        default=None,
        description="Second image path for compare action.",
    )
    backend: str = Field(
        default="auto",
        description="Backend: auto (best available) | heuristic | dsine.",
    )
    edge_threshold: float = Field(
        default=0.5,
        description="Edge detection threshold for dsine backend (0.0-1.0).",
        ge=0.0,
        le=1.0,
    )
    simplify_tolerance: float = Field(
        default=2.0,
        description="Douglas-Peucker simplification tolerance in pixels.",
        ge=0.0,
    )
    layer_name: str = Field(
        default="Form Edges",
        description="Illustrator layer name for placed paths.",
    )
    smooth: bool = Field(
        default=True,
        description="Set path points to smooth (curved) when placing.",
    )
    max_contours: int = Field(
        default=50,
        description="Maximum number of contours to extract.",
        ge=1,
        le=500,
    )
    min_contour_length: int = Field(
        default=30,
        description="Minimum contour arc length in pixels.",
        ge=1,
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _status() -> dict:
    """Report which form edge extraction backends are available."""
    return {
        "pipeline": "form_edge_extract",
        "description": (
            "Extract form edges (ignoring shadows) from reference images. "
            "Heuristic backend uses multi-exposure Canny voting. "
            "DSINE backend uses surface normals for shadow-free edge detection."
        ),
        "backends": {
            "heuristic": {
                "available": True,
                "description": "Multi-exposure Canny voting (always available, no ML).",
            },
            "dsine": {
                "available": DSINE_AVAILABLE,
                "description": "Sobel on DSINE normal map (shadow-free, requires ML).",
                "install_hint": (
                    None if DSINE_AVAILABLE
                    else 'Install with: uv pip install -e ".[ml-form-edge]"'
                ),
            },
        },
        "available_actions": ["status", "extract", "place", "compare"],
        "output_dir": OUTPUT_DIR,
    }


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


def _extract(
    image_path: str,
    backend: str = "auto",
    edge_threshold: float = 0.5,
    simplify_tolerance: float = 2.0,
    min_contour_length: int = 30,
    max_contours: int = 50,
) -> dict:
    """Run form edge extraction pipeline, return contours as JSON-serializable dict.

    Args:
        image_path: Absolute path to input image.
        backend: Backend selection (auto, heuristic, dsine).
        edge_threshold: Threshold for dsine backend.
        simplify_tolerance: Douglas-Peucker epsilon.
        min_contour_length: Minimum arc length filter.
        max_contours: Maximum contour count.

    Returns:
        Dict with contours, metadata, and timing. Contains "error" on failure.
    """
    t0 = time.time()

    if not image_path:
        return {"error": "image_path is required for extract action."}

    if not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Run extraction
    result = extract_form_edges(
        image_path, backend=backend, threshold=edge_threshold
    )

    if "error" in result:
        return result

    form_mask = result["form_edges"]

    # Save edge mask to disk for debugging
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    mask_path = os.path.join(OUTPUT_DIR, "form_edges.png")
    cv2.imwrite(mask_path, form_mask)

    # Convert mask to contours
    contours = edge_mask_to_contours(
        form_mask,
        simplify_tolerance=simplify_tolerance,
        min_length=min_contour_length,
        max_contours=max_contours,
    )

    # Read image dimensions for coordinate transforms
    img = cv2.imread(image_path)
    img_h, img_w = img.shape[:2] if img is not None else (0, 0)

    t1 = time.time()

    return {
        "contours": contours,
        "contour_count": len(contours),
        "backend": result["backend"],
        "mask_path": mask_path,
        "image_size": [img_w, img_h],
        "metadata": result.get("metadata", {}),
        "timings": {
            "extraction_seconds": result.get("metadata", {}).get("time_seconds", 0),
            "total_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# Compare (IoU between two images' form edges)
# ---------------------------------------------------------------------------


def _compare(
    image_path_a: str,
    image_path_b: str,
    backend: str = "auto",
    edge_threshold: float = 0.5,
) -> dict:
    """Extract form edges from two images and compute IoU similarity.

    Args:
        image_path_a: First image path.
        image_path_b: Second image path.
        backend: Backend selection.
        edge_threshold: Threshold for dsine backend.

    Returns:
        Dict with IoU score, per-image edge counts, and metadata.
        Contains "error" on failure.
    """
    t0 = time.time()

    if not image_path_a or not os.path.isfile(image_path_a):
        return {"error": f"Image A not found: {image_path_a}"}
    if not image_path_b or not os.path.isfile(image_path_b):
        return {"error": f"Image B not found: {image_path_b}"}

    result_a = extract_form_edges(
        image_path_a, backend=backend, threshold=edge_threshold
    )
    if "error" in result_a:
        return {"error": f"Image A extraction failed: {result_a['error']}"}

    result_b = extract_form_edges(
        image_path_b, backend=backend, threshold=edge_threshold
    )
    if "error" in result_b:
        return {"error": f"Image B extraction failed: {result_b['error']}"}

    mask_a = result_a["form_edges"]
    mask_b = result_b["form_edges"]

    # Resize masks to same dimensions if needed (use the smaller)
    h_a, w_a = mask_a.shape[:2]
    h_b, w_b = mask_b.shape[:2]
    if (h_a, w_a) != (h_b, w_b):
        target_h = min(h_a, h_b)
        target_w = min(w_a, w_b)
        mask_a = cv2.resize(mask_a, (target_w, target_h))
        mask_b = cv2.resize(mask_b, (target_w, target_h))

    # Compute IoU
    binary_a = (mask_a > 127).astype(np.uint8)
    binary_b = (mask_b > 127).astype(np.uint8)

    intersection = np.count_nonzero(binary_a & binary_b)
    union = np.count_nonzero(binary_a | binary_b)

    iou = intersection / union if union > 0 else 0.0

    t1 = time.time()

    return {
        "iou": round(iou, 4),
        "intersection_pixels": int(intersection),
        "union_pixels": int(union),
        "image_a": {
            "path": image_path_a,
            "edge_pixels": int(np.count_nonzero(binary_a)),
            "backend": result_a["backend"],
        },
        "image_b": {
            "path": image_path_b,
            "edge_pixels": int(np.count_nonzero(binary_b)),
            "backend": result_b["backend"],
        },
        "timings": {
            "total_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# JSX builder for path placement
# ---------------------------------------------------------------------------


def _build_place_jsx(
    contours: list[dict],
    layer_name: str,
    smooth: bool = True,
) -> str:
    """Build JSX to place form edge contours as vector paths in Illustrator.

    Creates a layer named ``layer_name``, then for each contour creates a
    path using ``pathItems.add()`` + ``setEntirePath()``.  When ``smooth``
    is True, sets all path points to smooth (curved via 1/3 handle distance).

    Args:
        contours: List of contour dicts with ``"name"`` and ``"points"`` keys.
            Points must already be in Illustrator coordinates.
        layer_name: Name for the target Illustrator layer.
        smooth: Whether to set bezier handles for smooth curves.

    Returns:
        JSX string for execution in Illustrator.
    """
    from adobe_mcp.jsx.templates import escape_jsx_string

    escaped_layer = escape_jsx_string(layer_name)
    smooth_js = "true" if smooth else "false"

    # Build per-contour placement blocks
    path_blocks = []
    for contour in contours:
        points = contour.get("points", [])
        if not points or len(points) < 3:
            continue

        name = escape_jsx_string(contour.get("name", "form_edge"))
        points_json = json.dumps(points)

        path_blocks.append(f"""
        (function() {{
            var path = layer.pathItems.add();
            path.setEntirePath({points_json});
            path.closed = true;
            path.filled = false;
            path.stroked = true;
            path.strokeWidth = 1.0;
            var black = new RGBColor();
            black.red = 40; black.green = 40; black.blue = 40;
            path.strokeColor = black;
            path.name = "{name}";

            if ({smooth_js} && path.pathPoints.length >= 3) {{
                var n = path.pathPoints.length;
                for (var i = 0; i < n; i++) {{
                    var pt = path.pathPoints[i];
                    var prevIdx = (i - 1 + n) % n;
                    var nextIdx = (i + 1) % n;
                    var prev = path.pathPoints[prevIdx];
                    var next = path.pathPoints[nextIdx];

                    var dx_l = (pt.anchor[0] - prev.anchor[0]) / 3;
                    var dy_l = (pt.anchor[1] - prev.anchor[1]) / 3;
                    var dx_r = (next.anchor[0] - pt.anchor[0]) / 3;
                    var dy_r = (next.anchor[1] - pt.anchor[1]) / 3;

                    pt.leftDirection = [pt.anchor[0] - dx_l, pt.anchor[1] - dy_l];
                    pt.rightDirection = [pt.anchor[0] + dx_r, pt.anchor[1] + dy_r];
                }}
            }}

            placed.push({{ name: path.name, points: path.pathPoints.length }});
        }})();
""")

    jsx = f"""
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

    var placed = [];
    {"".join(path_blocks)}
    return JSON.stringify({{ paths_placed: placed.length, paths: placed, layer: layer.name }});
}})();
"""
    return jsx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_form_edge_extract tool."""

    @mcp.tool(
        name="adobe_ai_form_edge_extract",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_form_edge_extract(
        params: FormEdgeExtractInput,
    ) -> str:
        """Extract form edges (ignoring shadows) from reference images.

        Uses either heuristic multi-exposure voting (always available) or
        DSINE normal-based edge detection (requires ML) to find edges
        that represent real surface boundaries, not lighting artifacts.

        Actions:
        - status: Report available backends and readiness
        - extract: Run pipeline, return contours as JSON (no Illustrator)
        - place: Extract + place as vector paths in Illustrator
        - compare: Extract from two images, compute IoU similarity

        The heuristic backend detects edges that persist across multiple
        contrast levels (form edges) vs those that appear only at certain
        thresholds (shadow edges).  The DSINE backend operates on surface
        normals where shadows are invisible.
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        # --- status ---
        if action == "status":
            return json.dumps(_status(), indent=2)

        # --- extract ---
        elif action == "extract":
            result = _extract(
                image_path=params.image_path,
                backend=params.backend,
                edge_threshold=params.edge_threshold,
                simplify_tolerance=params.simplify_tolerance,
                min_contour_length=params.min_contour_length,
                max_contours=params.max_contours,
            )
            return json.dumps(result, indent=2, default=_json_default)

        # --- place ---
        elif action == "place":
            # Run extraction first
            extract_result = _extract(
                image_path=params.image_path,
                backend=params.backend,
                edge_threshold=params.edge_threshold,
                simplify_tolerance=params.simplify_tolerance,
                min_contour_length=params.min_contour_length,
                max_contours=params.max_contours,
            )

            if "error" in extract_result:
                return json.dumps(extract_result, indent=2)

            contours = extract_result["contours"]
            if not contours:
                return json.dumps({
                    "error": "No contours found in image.",
                    "backend": extract_result.get("backend"),
                    "metadata": extract_result.get("metadata"),
                })

            # Query artboard dimensions from Illustrator
            jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({width: ab[2] - ab[0], height: ab[1] - ab[3]});
})();
"""
            ab_result = await _async_run_jsx("illustrator", jsx_info)
            if not ab_result["success"]:
                return json.dumps({
                    "error": f"Could not query artboard: {ab_result['stderr']}",
                    "contours": contours,
                })

            try:
                artboard = json.loads(ab_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({
                    "error": f"Bad artboard response: {ab_result['stdout']}",
                    "contours": contours,
                })

            # Transform contours to AI coordinates
            img_size = tuple(extract_result["image_size"])
            ab_dims = (artboard["width"], artboard["height"])
            ai_contours = contours_to_ai_points(contours, img_size, ab_dims)

            # Build and execute JSX
            jsx = _build_place_jsx(ai_contours, params.layer_name, params.smooth)
            place_result = await _async_run_jsx("illustrator", jsx)

            if not place_result["success"]:
                return json.dumps({
                    "error": f"Path placement failed: {place_result['stderr']}",
                    "contour_count": len(ai_contours),
                })

            try:
                placed = json.loads(place_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                placed = {"raw": place_result["stdout"]}

            return json.dumps({
                "paths_placed": placed.get("paths_placed", 0),
                "paths": placed.get("paths", []),
                "layer_name": placed.get("layer", params.layer_name),
                "contour_count": len(ai_contours),
                "backend": extract_result["backend"],
                "mask_path": extract_result.get("mask_path"),
                "image_size": extract_result["image_size"],
                "timings": extract_result.get("timings"),
            }, indent=2)

        # --- compare ---
        elif action == "compare":
            if not params.image_path:
                return json.dumps({"error": "image_path is required for compare action."})
            if not params.image_path_b:
                return json.dumps({"error": "image_path_b is required for compare action."})

            result = _compare(
                image_path_a=params.image_path,
                image_path_b=params.image_path_b,
                backend=params.backend,
                edge_threshold=params.edge_threshold,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "extract", "place", "compare"],
            })


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
