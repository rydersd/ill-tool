"""Normal map rendering utilities for illustration reference.

Post-processing functions that extract structural information from predicted
normal maps.  Each function takes a float32 HxWx3 normal map (unit vectors
in [-1, 1]) and returns a visualization useful for constructive drawing.

Pure Python implementation using OpenCV and numpy — no ML dependencies.
"""

from typing import Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# flat_planes — K-means clustering of normal directions
# ---------------------------------------------------------------------------


def flat_planes(normal_map: np.ndarray, k: int = 6) -> np.ndarray:
    """K-means cluster normal vectors, assign a flat color per cluster.

    Reveals the major structural planes in a surface.  Each pixel is
    assigned to the nearest cluster centroid in normal-vector space,
    then colored with a unique hue so the plane boundaries are visible.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        k: Number of clusters (planes) to detect.

    Returns:
        HxWx3 uint8 BGR image where each cluster has a distinct flat color.
    """
    h, w = normal_map.shape[:2]

    # Reshape to (N, 3) float32 for cv2.kmeans
    pixels = normal_map.reshape(-1, 3).astype(np.float32)

    # Guard against k > unique pixels or empty input — cv2.kmeans crashes
    if len(pixels) == 0:
        return np.zeros((h, w, 3), dtype=np.uint8)
    n_unique = len(np.unique(pixels, axis=0))
    k = min(k, n_unique, len(pixels))
    if k < 1:
        return np.zeros((h, w, 3), dtype=np.uint8)

    # cv2.kmeans criteria: stop after 20 iterations or 0.5 epsilon
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, _ = cv2.kmeans(
        pixels, k, None, criteria, attempts=5, flags=cv2.KMEANS_PP_CENTERS
    )

    # Generate k evenly-spaced hues in HSV, convert to BGR
    palette = np.zeros((k, 1, 3), dtype=np.uint8)
    for i in range(k):
        palette[i, 0] = (int(180 * i / k), 200, 220)  # H, S, V
    palette_bgr = cv2.cvtColor(palette, cv2.COLOR_HSV2BGR).reshape(k, 3)

    # Map each pixel to its cluster color
    result = palette_bgr[labels.flatten()].reshape(h, w, 3)
    return result


# ---------------------------------------------------------------------------
# form_lines — Sobel edge detection on normal channels
# ---------------------------------------------------------------------------


def form_lines(normal_map: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    """Sobel edge detection on each normal-map channel, combined magnitude.

    Produces *only* form edges — because normal maps encode surface
    orientation rather than brightness, shadow boundaries are invisible.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        threshold: Fraction of the maximum gradient magnitude below which
                   edges are suppressed (0.0 keeps everything, 1.0 keeps nothing).

    Returns:
        HxW uint8 binary edge mask (255 = edge, 0 = no edge).
    """
    # Accumulate squared gradient magnitude across all 3 normal channels
    mag_sq = np.zeros(normal_map.shape[:2], dtype=np.float64)

    for ch in range(3):
        channel = normal_map[:, :, ch].astype(np.float64)
        gx = cv2.Sobel(channel, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(channel, cv2.CV_64F, 0, 1, ksize=3)
        mag_sq += gx * gx + gy * gy

    magnitude = np.sqrt(mag_sq)

    # Threshold: suppress below fraction of max
    max_mag = magnitude.max()
    if max_mag > 0:
        binary = (magnitude >= threshold * max_mag).astype(np.uint8) * 255
    else:
        binary = np.zeros_like(magnitude, dtype=np.uint8)

    return binary


# ---------------------------------------------------------------------------
# curvature_map — Gaussian curvature approximation
# ---------------------------------------------------------------------------


def curvature_map(normal_map: np.ndarray) -> np.ndarray:
    """Approximate Gaussian curvature from spatial derivatives of the normal field.

    Computes the shape operator (Weingarten map) from the partial derivatives
    of the normal vector field, then takes the determinant of the 2x2 matrix
    as the Gaussian curvature estimate.  Positive = convex, negative = saddle,
    zero = flat or cylinder.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxW float32 array of curvature values (signed).
    """
    # Partial derivatives of each normal component w.r.t. x and y
    # np.gradient returns (dy, dx) for a 2D array
    nx = normal_map[:, :, 0].astype(np.float64)
    ny = normal_map[:, :, 1].astype(np.float64)

    # dnx/dy, dnx/dx
    dnx_dy, dnx_dx = np.gradient(nx)
    dny_dy, dny_dx = np.gradient(ny)

    # Shape operator (Weingarten map) approximation from the predicted
    # normal field.  The 2x2 shape operator for a surface parameterized
    # by image (x, y) is:
    #   S = [[dnx/dx, dnx/dy],
    #        [dny/dx, dny/dy]]
    # Gaussian curvature K = det(S) = (dnx/dx)(dny/dy) - (dnx/dy)(dny/dx)
    #
    # Only the xy pair is used — this is the actual determinant from
    # differential geometry.  The nz channel is redundant for unit normals
    # on a surface embedded in 3D (nz is determined by nx, ny via the
    # unit-length constraint).
    curvature = dnx_dx * dny_dy - dnx_dy * dny_dx
    return curvature.astype(np.float32)


# ---------------------------------------------------------------------------
# relit_reference — synthetic relighting via dot(normal, light)
# ---------------------------------------------------------------------------


def relit_reference(
    image: np.ndarray,
    normal_map: np.ndarray,
    light_dir: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> np.ndarray:
    """Multiply original image albedo by dot(normal, light_dir) for relighting.

    Approximates the image as a Lambertian surface with ``albedo = image``.
    The result is a shadow-free 'clean' version under the specified light.

    Args:
        image: HxWx3 uint8 BGR image (the original photograph/render).
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        light_dir: (x, y, z) light direction vector (will be normalized).

    Returns:
        HxWx3 uint8 BGR relighted image.
    """
    # Normalize the light direction
    light = np.array(light_dir, dtype=np.float64)
    norm = np.linalg.norm(light)
    if norm > 0:
        light = light / norm
    else:
        light = np.array([0.0, 0.0, 1.0])

    # Dot product: (H, W, 3) · (3,) -> (H, W)
    normals_f64 = normal_map.astype(np.float64)
    dot = np.einsum("ijk,k->ij", normals_f64, light)

    # Clamp to [0, 1] — back-facing surfaces get zero light
    dot = np.clip(dot, 0.0, 1.0)

    # Multiply albedo (image) by shading factor
    albedo = image.astype(np.float64)
    shaded = albedo * dot[:, :, np.newaxis]

    return np.clip(shaded, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# depth_discontinuities — occlusion edge detection from normal jumps
# ---------------------------------------------------------------------------


def depth_discontinuities(
    normal_map: np.ndarray, threshold: float = 0.3
) -> np.ndarray:
    """Detect depth/occlusion boundaries from normal map discontinuities.

    Large changes in the normal vector between adjacent pixels indicate
    occlusion edges (depth discontinuities) rather than smooth curvature.
    Uses the angular difference (1 - dot product) between neighboring
    normals as the discontinuity measure.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        threshold: Minimum angular difference (0-2 scale) to count as an
                   occlusion edge.  Lower = more sensitive.

    Returns:
        HxW uint8 binary edge mask (255 = discontinuity, 0 = smooth).
    """
    normals = normal_map.astype(np.float64)

    # Normalize normal vectors before computing dot products so that
    # non-unit inputs (e.g. from noisy predictions) don't skew results.
    norm = np.linalg.norm(normals, axis=2, keepdims=True)
    norm = np.maximum(norm, 1e-8)  # avoid division by zero
    normals = normals / norm

    h, w = normals.shape[:2]

    # Compute dot product with right and bottom neighbors
    # Pad by repeating edge values so output is same size
    dot_right = np.ones((h, w), dtype=np.float64)
    dot_down = np.ones((h, w), dtype=np.float64)

    # Right neighbor: dot product of pixel (y, x) with (y, x+1)
    dot_right[:, :-1] = np.einsum(
        "ijk,ijk->ij", normals[:, :-1, :], normals[:, 1:, :]
    )
    # Bottom neighbor: dot product of pixel (y, x) with (y+1, x)
    dot_down[:-1, :] = np.einsum(
        "ijk,ijk->ij", normals[:-1, :, :], normals[1:, :, :]
    )

    # Angular difference: 1 - dot gives 0 for parallel, 2 for opposite
    diff_right = 1.0 - dot_right
    diff_down = 1.0 - dot_down

    # Take the maximum discontinuity in either direction
    max_diff = np.maximum(diff_right, diff_down)

    # Threshold to binary mask
    mask = (max_diff >= threshold).astype(np.uint8) * 255
    return mask
