"""Pure Python form edge extraction pipeline.

Extracts form edges (ignoring shadow edges) from reference images using
either heuristic multi-exposure voting (always available) or DSINE
normal-based edge detection (requires ML backend).

This module has NO MCP registration and NO Illustrator interaction --
it is pure image processing logic consumed by form_edge_extract.py.

Key insight: shadow edges move when lighting changes; form edges don't.
Multi-exposure voting exploits this by detecting edges that persist
across multiple contrast levels.  Normal-based extraction avoids
shadows entirely by operating on surface orientation rather than
brightness.
"""

import time
from typing import Optional

import cv2
import numpy as np

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

    num_exposures = max(2, num_exposures)
    vote_threshold = max(1, min(vote_threshold, num_exposures))

    # Convert to grayscale if needed
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    h, w = gray.shape[:2]
    max_val = float(gray.max())
    if max_val < 1.0:
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

    # Sobel edge detection on each normal channel (same as form_lines in
    # normal_renderings.py but self-contained to avoid coupling)
    mag_sq = np.zeros(normal_map.shape[:2], dtype=np.float64)
    for ch in range(3):
        channel = normal_map[:, :, ch].astype(np.float64)
        gx = cv2.Sobel(channel, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(channel, cv2.CV_64F, 0, 1, ksize=3)
        mag_sq += gx * gx + gy * gy

    magnitude = np.sqrt(mag_sq)

    # Threshold to binary mask
    max_mag = magnitude.max()
    if max_mag > 0:
        form_mask = (magnitude >= threshold * max_mag).astype(np.uint8) * 255
    else:
        form_mask = np.zeros_like(magnitude, dtype=np.uint8)

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
# Dispatcher
# ---------------------------------------------------------------------------


def extract_form_edges(
    image_path: str,
    backend: str = "auto",
    threshold: float = 0.5,
) -> dict:
    """Main dispatcher for form edge extraction.

    Selects the best available backend: dsine > heuristic.

    Args:
        image_path: Absolute path to input image.
        backend: ``"auto"`` (best available), ``"dsine"``, or ``"heuristic"``.
        threshold: Edge detection threshold (used by dsine backend).

    Returns:
        Dict with ``form_edges`` mask, ``backend`` name, and ``metadata``.
        Contains ``"error"`` key on failure.
    """
    import os

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    if backend == "dsine":
        return dsine_form_edges(image_path, threshold=threshold)

    if backend == "heuristic":
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}
        return heuristic_form_edges(image)

    if backend == "auto":
        # Try dsine first, fall back to heuristic
        if DSINE_AVAILABLE:
            return dsine_form_edges(image_path, threshold=threshold)

        # Fall back to heuristic
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}
        return heuristic_form_edges(image)

    return {
        "error": f"Unknown backend: {backend}",
        "valid_backends": ["auto", "dsine", "heuristic"],
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
    artboard_dims: tuple,
) -> list[dict]:
    """Transform pixel contours to Illustrator coordinates.

    Applies Y-flip (Illustrator Y goes up), scales to fit the artboard
    (maintaining aspect ratio), and centers the result.

    Args:
        contours: List of contour dicts with ``"points"`` key (pixel coords).
        image_size: ``(width, height)`` of the source image in pixels.
        artboard_dims: ``(width, height)`` of the Illustrator artboard in points.

    Returns:
        New list of contour dicts with transformed ``"points"`` in AI coords.
        Original contours are not mutated.
    """
    if not contours:
        return []

    img_w, img_h = image_size
    ab_w, ab_h = artboard_dims

    if img_w <= 0 or img_h <= 0:
        return contours  # Can't transform, return as-is

    # Scale to fit artboard, maintaining aspect ratio (with 5% margin)
    margin = 0.95
    scale = min((ab_w * margin) / img_w, (ab_h * margin) / img_h)

    # Center offset
    offset_x = (ab_w - img_w * scale) / 2.0
    offset_y = (ab_h - img_h * scale) / 2.0

    transformed = []
    for contour in contours:
        new_points = []
        for pt in contour["points"]:
            # Scale and shift
            ai_x = pt[0] * scale + offset_x
            # Y-flip: pixel Y=0 is top, AI Y=0 is bottom
            ai_y = ab_h - (pt[1] * scale + offset_y)
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

    # form_edges AND NOT shadow_mask
    result = cv2.bitwise_and(fe, cv2.bitwise_not(sm))
    return result * 255
