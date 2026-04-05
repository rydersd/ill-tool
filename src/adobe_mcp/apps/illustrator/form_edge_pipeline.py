"""Pure Python form edge extraction pipeline.

Extracts form edges (ignoring shadow edges) from reference images using
one of several backends:
- heuristic: multi-exposure Canny voting (always available)
- dsine: Sobel on DSINE normal map (requires torch)
- rindnet: RINDNet++ 4-class edge classification (requires rindnet research repo)
- informative: Informative Drawings artist-like line extraction (requires onnxruntime)

This module has NO MCP registration and NO Illustrator interaction --
it is pure image processing logic consumed by form_edge_extract.py.

Key insight: shadow edges move when lighting changes; form edges don't.
Multi-exposure voting exploits this by detecting edges that persist
across multiple contrast levels.  Normal-based extraction avoids
shadows entirely by operating on surface orientation rather than
brightness.  RINDNet++ directly classifies each edge pixel into one of
four types.  Informative Drawings produces artist-style line drawings.
"""

import time
from typing import Optional

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.path_validation import (
    validate_image_path_size,
    validate_image_size,
    validate_safe_path,
)

# ---------------------------------------------------------------------------
# Graceful ML dependency imports (module-level for monkeypatch testability)
# ---------------------------------------------------------------------------

try:
    from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
        estimate_normals,
        DSINE_AVAILABLE,
    )
except ImportError:
    DSINE_AVAILABLE = False

    def estimate_normals(image_path: str, model: str = "auto") -> dict:
        """Stub when ML backend is not importable."""
        return {
            "error": "ml_backends.normal_estimator not available.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }

try:
    from adobe_mcp.apps.illustrator.ml_backends.edge_classifier import (
        classify_edges_rindnet,
        RINDNET_AVAILABLE,
    )
except ImportError:
    RINDNET_AVAILABLE = False

    def classify_edges_rindnet(image_path: str) -> dict:
        """Stub when edge classifier backend is not importable."""
        return {
            "error": "ml_backends.edge_classifier not available.",
            "install_hint": (
                "RINDNet++ requires manual install from: "
                "https://github.com/MengyangPu/RINDNet-plusplus"
            ),
        }

try:
    from adobe_mcp.apps.illustrator.ml_backends.informative_draw import (
        informative_drawings,
        INFORMATIVE_AVAILABLE,
    )
except ImportError:
    INFORMATIVE_AVAILABLE = False

    def informative_drawings(image_path: str, threshold: float = 0.5) -> dict:
        """Stub when informative drawings backend is not importable."""
        return {
            "error": "ml_backends.informative_draw not available.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }


# ---------------------------------------------------------------------------
# Heuristic form edge extraction (always available)
# ---------------------------------------------------------------------------


def heuristic_form_edges(
    image: np.ndarray,
    num_exposures: int = 5,
    vote_threshold: int = 3,
) -> dict:
    """Heuristic form edge extraction using multi-exposure voting.

    Applies Canny edge detection at multiple threshold pairs spanning
    10% to 90% of the image intensity range.  Pixels detected as edges
    at ``vote_threshold`` or more exposure levels are classified as form
    edges (they persist across contrast changes, unlike shadows).

    Applies morphological cleanup to close small gaps and remove noise.

    Uses OpenCV only -- always available, no ML dependencies.

    Args:
        image: HxWx3 uint8 BGR image or HxW uint8 grayscale.
        num_exposures: Number of Canny threshold pairs to try (>= 2).
        vote_threshold: Minimum votes required to classify as form edge.
            Clamped to [1, num_exposures].

    Returns:
        Dict with keys:
        - ``form_edges``: HxW uint8 mask (255 = form edge, 0 = background).
        - ``backend``: ``"heuristic"``.
        - ``metadata``: Dict with num_exposures, vote_threshold, edge_pixel_count,
          time_seconds.
    """
    t0 = time.time()

    # Reject oversized images to prevent resource exhaustion
    try:
        validate_image_size(image)
    except ValueError as exc:
        return {"error": str(exc)}

    num_exposures = max(2, num_exposures)
    vote_threshold = max(1, min(vote_threshold, num_exposures))

    # Convert to grayscale if needed
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    h, w = gray.shape[:2]
    max_val = float(gray.max())
    if max_val == 0:
        # All-black image, no edges to detect
        # All-black image -- no edges to find
        return {
            "form_edges": np.zeros((h, w), dtype=np.uint8),
            "backend": "heuristic",
            "metadata": {
                "num_exposures": num_exposures,
                "vote_threshold": vote_threshold,
                "edge_pixel_count": 0,
                "time_seconds": round(time.time() - t0, 4),
            },
        }

    # Accumulate edge votes across multiple Canny threshold pairs
    vote_map = np.zeros((h, w), dtype=np.int32)

    for i in range(num_exposures):
        # Threshold pair spans from 10% to 90% of max value
        frac = 0.1 + 0.8 * i / max(1, num_exposures - 1)
        low = int(max_val * frac * 0.5)
        high = int(max_val * frac)
        low = max(1, low)
        high = max(low + 1, high)

        edges = cv2.Canny(gray, low, high)
        vote_map += (edges > 0).astype(np.int32)

    # Pixels that pass the vote threshold are form edges
    form_mask = (vote_map >= vote_threshold).astype(np.uint8) * 255

    # Morphological cleanup: close small gaps, then remove isolated noise
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    form_mask = cv2.morphologyEx(form_mask, cv2.MORPH_CLOSE, kernel_close)

    kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    form_mask = cv2.morphologyEx(form_mask, cv2.MORPH_OPEN, kernel_open)

    edge_count = int(np.count_nonzero(form_mask))
    t1 = time.time()

    return {
        "form_edges": form_mask,
        "backend": "heuristic",
        "metadata": {
            "num_exposures": num_exposures,
            "vote_threshold": vote_threshold,
            "edge_pixel_count": edge_count,
            "time_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# DSINE-based form edge extraction (requires ML backend)
# ---------------------------------------------------------------------------


def dsine_form_edges(
    image_path: str,
    threshold: float = 0.5,
) -> dict:
    """Form edges via DSINE normal prediction + Sobel on normal map.

    Predicts per-pixel surface normals using the DSINE model, then runs
    Sobel edge detection on the normal map channels.  Because normal maps
    encode surface orientation rather than brightness, shadow boundaries
    are invisible -- only true form edges appear.

    Requires ``ml_backends.normal_estimator`` (torch + torchvision).

    Args:
        image_path: Absolute path to input image (PNG/JPG).
        threshold: Fraction of max gradient magnitude below which edges
            are suppressed (0.0 = keep all, 1.0 = keep nothing).

    Returns:
        Dict with keys:
        - ``form_edges``: HxW uint8 mask (255 = form edge, 0 = background).
        - ``normal_map``: HxWx3 float32 normal map (unit vectors in [-1, 1]).
        - ``backend``: ``"dsine"``.
        - ``metadata``: Dict with model, device, height, width, threshold,
          edge_pixel_count, time_seconds.
    """
    t0 = time.time()

    if not DSINE_AVAILABLE:
        return {
            "error": "DSINE dependencies (torch, torchvision) not installed.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }

    # Predict normals
    result = estimate_normals(image_path, model="dsine")
    if "error" in result:
        return result

    normal_map = result["normal_map"]  # HxWx3 float32

    # Reuse the canonical Sobel-on-normals implementation from normal_renderings
    from adobe_mcp.apps.illustrator.normal_renderings import form_lines

    form_mask = form_lines(normal_map, threshold=threshold)

    edge_count = int(np.count_nonzero(form_mask))
    t1 = time.time()

    return {
        "form_edges": form_mask,
        "normal_map": normal_map,
        "backend": "dsine",
        "metadata": {
            "model": result.get("model", "dsine"),
            "device": result.get("device", "unknown"),
            "height": normal_map.shape[0],
            "width": normal_map.shape[1],
            "threshold": threshold,
            "edge_pixel_count": edge_count,
            "time_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# RINDNet++ form edge extraction
# ---------------------------------------------------------------------------


def rindnet_form_edges(
    image_path: str,
    threshold: float = 0.5,
) -> dict:
    """Form edges via RINDNet++ four-class edge classification.

    Calls ``classify_edges_rindnet`` to get per-pixel edge type
    classification, then returns the ``form_edges`` mask (normal | depth).

    Falls back to heuristic classification when RINDNet++ is not
    installed (the classifier handles this internally).

    Args:
        image_path: Absolute path to input image (PNG/JPG).
        threshold: Not used by RINDNet++ directly (reserved for
            consistency with other backends).

    Returns:
        Dict with keys:
        - ``form_edges``: HxW uint8 mask (255 = form edge, 0 = background).
        - ``shadow_edges``: HxW uint8 mask (255 = shadow edge).
        - ``backend``: ``"rindnet"`` or ``"heuristic"`` (if fallback).
        - ``metadata``: Dict with model, device, time_seconds, edge counts.
    """
    t0 = time.time()

    result = classify_edges_rindnet(image_path)
    if "error" in result:
        return result

    form_edges = result["form_edges"]
    shadow_edges = result["shadow_edges"]
    model_used = result.get("model", "rindnet")

    form_count = int(np.count_nonzero(form_edges))
    shadow_count = int(np.count_nonzero(shadow_edges))
    t1 = time.time()

    return {
        "form_edges": form_edges,
        "shadow_edges": shadow_edges,
        "backend": model_used,
        "metadata": {
            "model": model_used,
            "device": result.get("device", "cpu"),
            "threshold": threshold,
            "form_edge_pixel_count": form_count,
            "shadow_edge_pixel_count": shadow_count,
            "edge_pixel_count": form_count,
            "time_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# Informative Drawings form edge extraction
# ---------------------------------------------------------------------------


def informative_form_edges(
    image_path: str,
    threshold: float = 0.5,
) -> dict:
    """Form edges via Informative Drawings artist-like line extraction.

    Calls ``informative_drawings`` to extract a line drawing, then
    returns the thresholded result as a form edge mask.

    Requires onnxruntime and huggingface_hub.

    Args:
        image_path: Absolute path to input image (PNG/JPG).
        threshold: Binarization threshold for the line drawing output
            (0.0 = keep all lines, 1.0 = keep nothing).

    Returns:
        Dict with keys:
        - ``form_edges``: HxW uint8 mask (255 = form edge, 0 = background).
        - ``backend``: ``"informative"``.
        - ``metadata``: Dict with model, time_seconds, edge counts.
    """
    t0 = time.time()

    if not INFORMATIVE_AVAILABLE:
        return {
            "error": "onnxruntime not installed for Informative Drawings.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }

    result = informative_drawings(image_path, threshold=threshold)
    if "error" in result:
        return result

    form_edges = result["line_drawing"]
    edge_count = int(np.count_nonzero(form_edges))
    t1 = time.time()

    return {
        "form_edges": form_edges,
        "backend": "informative",
        "metadata": {
            "model": "informative_drawings",
            "threshold": threshold,
            "edge_pixel_count": edge_count,
            "height": result.get("height", form_edges.shape[0]),
            "width": result.get("width", form_edges.shape[1]),
            "time_seconds": round(t1 - t0, 4),
        },
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def extract_form_edges(
    image_path: str,
    backend: str = "auto",
    threshold: float = 0.5,
) -> dict:
    """Main dispatcher for form edge extraction.

    Selects the best available backend:
    rindnet > dsine > informative > heuristic.

    Args:
        image_path: Absolute path to input image.
        backend: ``"auto"`` (best available), ``"rindnet"``, ``"dsine"``,
            ``"informative"``, or ``"heuristic"``.
        threshold: Edge detection threshold (interpretation varies by backend).

    Returns:
        Dict with ``form_edges`` mask, ``backend`` name, and ``metadata``.
        Contains ``"error"`` key on failure.
    """
    import os

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Validate path against traversal attacks before any I/O
    try:
        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    # Check image dimensions from header before full decode
    try:
        validate_image_path_size(image_path)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception:
        pass  # PIL may not recognize all formats; let cv2 try

    if backend == "rindnet":
        return rindnet_form_edges(image_path, threshold=threshold)

    if backend == "dsine":
        return dsine_form_edges(image_path, threshold=threshold)

    if backend == "informative":
        return informative_form_edges(image_path, threshold=threshold)

    if backend == "heuristic":
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}
        return heuristic_form_edges(image)

    if backend == "auto":
        # Priority: rindnet > dsine > informative > heuristic
        if RINDNET_AVAILABLE:
            return rindnet_form_edges(image_path, threshold=threshold)

        if DSINE_AVAILABLE:
            return dsine_form_edges(image_path, threshold=threshold)

        if INFORMATIVE_AVAILABLE:
            return informative_form_edges(image_path, threshold=threshold)

        # Fall back to heuristic (always available)
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}
        return heuristic_form_edges(image)

    return {
        "error": f"Unknown backend: {backend}",
        "valid_backends": ["auto", "rindnet", "dsine", "informative", "heuristic"],
    }


# ---------------------------------------------------------------------------
# Edge mask to contours
# ---------------------------------------------------------------------------


def edge_mask_to_contours(
    mask: np.ndarray,
    simplify_tolerance: float = 2.0,
    min_length: int = 30,
    max_contours: int = 50,
) -> list[dict]:
    """Convert an edge mask to vectorizable contours.

    Uses ``cv2.findContours`` to extract contour polygons from the binary
    mask, then simplifies each with Douglas-Peucker.  Filters by arc length
    and limits the total count, sorted by area descending.

    Args:
        mask: HxW uint8 binary mask (255 = edge, 0 = background).
        simplify_tolerance: Douglas-Peucker epsilon for polygon simplification.
        min_length: Minimum contour arc length in pixels. Contours shorter
            than this are discarded.
        max_contours: Maximum number of contours to return.

    Returns:
        List of contour dicts, sorted by area descending::

            [
                {
                    "name": "form_edge_0",
                    "points": [[x, y], ...],
                    "point_count": int,
                    "area": float,
                },
                ...
            ]
    """
    if mask is None or mask.size == 0:
        return []

    # Ensure binary mask
    binary = (mask > 127).astype(np.uint8) * 255

    # Find contours (external + internal)
    contours, _ = cv2.findContours(
        binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )

    results = []
    for contour in contours:
        # Filter by arc length
        arc_len = cv2.arcLength(contour, closed=True)
        if arc_len < min_length:
            continue

        # Simplify with Douglas-Peucker
        simplified = cv2.approxPolyDP(contour, simplify_tolerance, closed=True)

        # Need at least 3 points for a meaningful contour
        if len(simplified) < 3:
            continue

        # Extract points as [[x, y], ...]
        points = simplified.reshape(-1, 2).tolist()
        area = abs(cv2.contourArea(simplified))

        results.append({
            "points": points,
            "point_count": len(points),
            "area": area,
        })

    # Sort by area descending
    results.sort(key=lambda c: c["area"], reverse=True)

    # Limit to max_contours
    results = results[:max_contours]

    # Assign names after sorting/limiting
    for i, contour in enumerate(results):
        contour["name"] = f"form_edge_{i}"

    return results


# ---------------------------------------------------------------------------
# Coordinate transform: pixel contours -> Illustrator coordinates
# ---------------------------------------------------------------------------


def contours_to_ai_points(
    contours: list[dict],
    image_size: tuple,
    artboard_dims,
    margin: float = 0.95,
) -> list[dict]:
    """Transform pixel contours to Illustrator coordinates.

    Applies Y-flip (Illustrator Y goes up), scales to fit the target
    bounds (maintaining aspect ratio), and centers the result.  Supports
    multi-artboard documents where the artboard is not at the origin.

    Args:
        contours: List of contour dicts with ``"points"`` key (pixel coords).
        image_size: ``(width, height)`` of the source image in pixels.
        artboard_dims: Either a dict with ``left``, ``top``, ``right``,
            ``bottom`` keys (for multi-artboard support, matching the
            pattern in ``contour_to_path.py``), or a ``(width, height)``
            tuple as a convenience fallback (assumes artboard at origin).
        margin: Scale factor applied to the target bounds before fitting.
            Use 0.95 (default) for artboard placement (5% inset).  Use
            1.0 for PlacedItem alignment where the image should fill the
            bounds exactly.

    Returns:
        New list of contour dicts with transformed ``"points"`` in AI coords.
        Original contours are not mutated.
    """
    if not contours:
        return []

    img_w, img_h = image_size

    # Accept either dict with artboard bounds or (width, height) tuple
    if isinstance(artboard_dims, dict):
        ab_left = artboard_dims.get("left", 0)
        ab_top = artboard_dims.get("top", artboard_dims.get("height", 0))
        ab_right = artboard_dims.get("right", artboard_dims.get("width", 0))
        ab_bottom = artboard_dims.get("bottom", 0)
        ab_w = ab_right - ab_left
        ab_h = ab_top - ab_bottom  # top > bottom in AI coordinate space
    else:
        ab_w, ab_h = artboard_dims
        ab_left = 0
        ab_top = ab_h  # artboard at origin: top = height

    if img_w <= 0 or img_h <= 0:
        return contours  # Can't transform, return as-is

    # Scale to fit target bounds, maintaining aspect ratio
    scale = min((ab_w * margin) / img_w, (ab_h * margin) / img_h)

    # Center offset — use target's actual position for the transform,
    # matching the pattern in contour_to_path.py which uses ab["top"].
    offset_x = ab_left + (ab_w - img_w * scale) / 2.0
    offset_y = ab_top - (ab_h - img_h * scale) / 2.0

    transformed = []
    for contour in contours:
        new_points = []
        for pt in contour["points"]:
            # Scale and shift
            ai_x = pt[0] * scale + offset_x
            # Y-flip: pixel Y=0 is top, AI Y increases upward
            ai_y = offset_y - pt[1] * scale
            new_points.append([round(ai_x, 2), round(ai_y, 2)])

        transformed.append({
            "name": contour["name"],
            "points": new_points,
            "point_count": contour["point_count"],
            "area": contour["area"],
        })

    return transformed


# ---------------------------------------------------------------------------
# Shadow mask subtraction
# ---------------------------------------------------------------------------


def subtract_shadow_mask(
    form_edges: np.ndarray,
    shadow_mask: np.ndarray,
) -> np.ndarray:
    """Remove shadow edges from form edge candidates.

    Computes ``form_edges AND NOT shadow_mask`` -- pixels that are in
    the form edge mask but also in the shadow mask are removed.

    Used when a shadow segmentation model (e.g. RINDNet++ in future
    Phase 3) provides a shadow boundary mask.

    Args:
        form_edges: HxW uint8 mask of form edge candidates.
        shadow_mask: HxW uint8 mask of shadow edges/regions.

    Returns:
        HxW uint8 mask with shadow edges removed.
    """
    # Ensure both are binary
    fe = (form_edges > 127).astype(np.uint8)
    sm = (shadow_mask > 127).astype(np.uint8)

    # form_edges AND NOT shadow_mask — using direct masking instead of
    # cv2.bitwise_not which depends on bit patterns of 0/1 values.
    result = fe.copy()
    result[sm > 0] = 0
    return result * 255
