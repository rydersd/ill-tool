"""Normal map rendering utilities for illustration reference.

Post-processing functions that extract structural information from predicted
normal maps.  Each function takes a float32 HxWx3 normal map (unit vectors
in [-1, 1]) and returns a visualization useful for constructive drawing.

Pure Python implementation using OpenCV and numpy — no ML dependencies.
"""

from typing import List, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Module-level cache for principal curvature results
# ---------------------------------------------------------------------------

_curvature_cache: dict = {}


def _cache_key(normal_map: np.ndarray) -> tuple:
    """Content-based cache key — immune to GC address reuse.

    Samples corner, center, and quarter-point values across all three
    channels for a reliable fingerprint.  Quarter-points avoid the
    failure mode where corners and center share the same normal (e.g.
    sphere fixture where out-of-radius corners default to (0,0,1) —
    same as the flat fixture).
    """
    h, w = normal_map.shape[:2]
    qh, qw = max(h // 4, 0), max(w // 4, 0)
    samples = (
        normal_map[0, 0, 0], normal_map[0, 0, 1], normal_map[0, 0, 2],
        normal_map[h - 1, w - 1, 0], normal_map[h - 1, w - 1, 2],
        normal_map[h // 2, w // 2, 0], normal_map[h // 2, w // 2, 1],
        normal_map[qh, qw, 0], normal_map[qh, qw, 1], normal_map[qh, qw, 2],
        normal_map[h - 1 - qh, w - 1 - qw, 0],
        normal_map[h - 1 - qh, w - 1 - qw, 1],
    )
    return (normal_map.shape, normal_map.dtype.str, samples)


def _get_principal_curvatures(normal_map: np.ndarray) -> np.ndarray:
    """Return cached principal curvatures, computing if needed.

    Only one normal map is cached at a time — calling with a different
    map clears the previous entry.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxWx3 float32: channel 0 = H (mean), 1 = kappa1 (max), 2 = kappa2 (min).
    """
    key = _cache_key(normal_map)
    if key not in _curvature_cache:
        _curvature_cache.clear()
        _curvature_cache[key] = principal_curvatures(normal_map)
    return _curvature_cache[key]


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

    Delegates to :func:`principal_curvatures` (cached) and returns K = kappa1 * kappa2.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxW float32 array of curvature values (signed).
    """
    pc = _get_principal_curvatures(normal_map)
    k1 = pc[:, :, 1]
    k2 = pc[:, :, 2]
    return (k1 * k2).astype(np.float32)


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


# ---------------------------------------------------------------------------
# principal_curvatures — eigendecomposition of the shape operator
# ---------------------------------------------------------------------------


def principal_curvatures(normal_map: np.ndarray) -> np.ndarray:
    """Compute principal curvatures from the 2x2 shape operator per pixel.

    The shape operator S = [[dnx/dx, dnx/dy], [dny/dx, dny/dy]] is
    eigendecomposed via the closed-form 2x2 solution:

        trace = dnx_dx + dny_dy
        det   = dnx_dx * dny_dy - dnx_dy * dny_dx
        kappa1 = trace/2 + sqrt(trace^2/4 - det)
        kappa2 = trace/2 - sqrt(trace^2/4 - det)
        H      = (kappa1 + kappa2) / 2 = trace / 2

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxWx3 float32 array: channel 0 = H (mean curvature),
        channel 1 = kappa1 (max principal curvature),
        channel 2 = kappa2 (min principal curvature).
    """
    nx = normal_map[:, :, 0].astype(np.float64)
    ny = normal_map[:, :, 1].astype(np.float64)

    # np.gradient returns (dy, dx) for a 2D array
    dnx_dy, dnx_dx = np.gradient(nx)
    dny_dy, dny_dx = np.gradient(ny)

    trace = dnx_dx + dny_dy
    det = dnx_dx * dny_dy - dnx_dy * dny_dx

    # Discriminant clamped to zero to avoid sqrt of negative due to numerics
    disc = np.maximum(trace * trace / 4.0 - det, 0.0)
    sqrt_disc = np.sqrt(disc)

    k1 = (trace / 2.0 + sqrt_disc)  # max principal curvature
    k2 = (trace / 2.0 - sqrt_disc)  # min principal curvature
    H = trace / 2.0                 # mean curvature

    result = np.empty((*normal_map.shape[:2], 3), dtype=np.float32)
    result[:, :, 0] = H
    result[:, :, 1] = k1
    result[:, :, 2] = k2
    return result


# ---------------------------------------------------------------------------
# surface_type_map — classify each pixel by local surface type
# ---------------------------------------------------------------------------


def surface_type_map(normal_map: np.ndarray, epsilon: float = 0.01) -> np.ndarray:
    """Classify each pixel into flat / convex / concave / saddle / cylindrical.

    Uses principal curvatures kappa1, kappa2 from the shape operator.

    Classification:
        0 = flat        (|kappa1| < eps AND |kappa2| < eps)
        1 = convex      (kappa1 > eps AND kappa2 > eps)
        2 = concave     (kappa1 < -eps AND kappa2 < -eps)
        3 = saddle       (kappa1 * kappa2 < -eps^2)
        4 = cylindrical (one |kappa| < eps, other |kappa| > eps)

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        epsilon: Threshold below which a curvature is considered zero.

    Returns:
        HxW uint8 array with values in {0, 1, 2, 3, 4}.
    """
    pc = _get_principal_curvatures(normal_map)
    k1 = pc[:, :, 1].astype(np.float64)
    k2 = pc[:, :, 2].astype(np.float64)

    abs_k1 = np.abs(k1)
    abs_k2 = np.abs(k2)
    eps2 = epsilon * epsilon

    result = np.zeros(normal_map.shape[:2], dtype=np.uint8)

    # Evaluate conditions in priority order
    # 0 = flat (default from zeros)
    flat = (abs_k1 < epsilon) & (abs_k2 < epsilon)

    convex = (k1 > epsilon) & (k2 > epsilon)
    concave = (k1 < -epsilon) & (k2 < -epsilon)
    saddle = (k1 * k2 < -eps2)
    cylindrical = ((abs_k1 < epsilon) & (abs_k2 > epsilon)) | (
        (abs_k1 > epsilon) & (abs_k2 < epsilon)
    )

    # Assign in reverse priority so higher-priority wins
    result[cylindrical] = 4
    result[saddle] = 3
    result[concave] = 2
    result[convex] = 1
    result[flat] = 0

    return result


# ---------------------------------------------------------------------------
# ridge_valley_map — ridges and valleys from mean curvature
# ---------------------------------------------------------------------------


def ridge_valley_map(
    normal_map: np.ndarray,
    ridge_threshold: float = 0.02,
    valley_threshold: float = 0.02,
) -> np.ndarray:
    """Detect ridge and valley pixels from mean curvature.

    Ridges are pixels with positive mean curvature H (convex ridges);
    valleys have negative H (concave valleys).  Strength is |H| normalized
    to 0-255.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        ridge_threshold: Minimum H for a ridge pixel.
        valley_threshold: Minimum |H| for a valley pixel.

    Returns:
        HxWx2 uint8 array: channel 0 = ridge strength, channel 1 = valley strength.
    """
    pc = _get_principal_curvatures(normal_map)
    H = pc[:, :, 0].astype(np.float64)

    h, w = H.shape
    result = np.zeros((h, w, 2), dtype=np.uint8)

    # Ridge channel
    ridge_mask = H > ridge_threshold
    if np.any(ridge_mask):
        ridge_vals = np.abs(H) * ridge_mask
        max_r = ridge_vals.max()
        if max_r > 0:
            result[:, :, 0] = (np.clip(ridge_vals / max_r, 0, 1) * 255).astype(
                np.uint8
            )

    # Valley channel
    valley_mask = H < -valley_threshold
    if np.any(valley_mask):
        valley_vals = np.abs(H) * valley_mask
        max_v = valley_vals.max()
        if max_v > 0:
            result[:, :, 1] = (np.clip(valley_vals / max_v, 0, 1) * 255).astype(
                np.uint8
            )

    return result


# ---------------------------------------------------------------------------
# silhouette_contours — near-perpendicular normals indicate silhouette
# ---------------------------------------------------------------------------


def silhouette_contours(
    normal_map: np.ndarray, threshold: float = 0.15
) -> np.ndarray:
    """Extract silhouette contours where the surface is nearly perpendicular to the view.

    Pixels whose nz component (z-normal) is close to zero are facing
    sideways — these form the visible silhouette of the object.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        threshold: Maximum |nz| to count as silhouette.

    Returns:
        HxW uint8 binary mask (255 = silhouette, 0 = not).
    """
    nz = normal_map[:, :, 2].astype(np.float64)
    mask = (np.abs(nz) < threshold).astype(np.uint8) * 255
    return mask


# ---------------------------------------------------------------------------
# depth_facing_map — how much each pixel faces the camera
# ---------------------------------------------------------------------------


def depth_facing_map(normal_map: np.ndarray) -> np.ndarray:
    """Compute a front-facing intensity map from the z-component of normals.

    Pixels with nz close to 1.0 face the camera directly; pixels with
    nz <= 0 are back-facing and clamped to 0.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxW float32 array in [0, 1].
    """
    nz = normal_map[:, :, 2].astype(np.float64)
    facing = np.clip(nz, 0.0, 1.0)
    return facing.astype(np.float32)


# ---------------------------------------------------------------------------
# surface_flow_field — principal direction eigenvectors of shape operator
# ---------------------------------------------------------------------------


def surface_flow_field(normal_map: np.ndarray) -> np.ndarray:
    """Compute principal curvature direction vectors at each pixel.

    For the 2x2 shape operator S = [[a, b], [c, d]], the eigenvector
    for eigenvalue lambda is proportional to [b, lambda - a].  Where
    curvature is negligible (flat), directions are set to zero.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].

    Returns:
        HxWx4 float32 array: (dir1_x, dir1_y, dir2_x, dir2_y) — two
        orthogonal principal directions per pixel.
    """
    nx = normal_map[:, :, 0].astype(np.float64)
    ny = normal_map[:, :, 1].astype(np.float64)

    dnx_dy, dnx_dx = np.gradient(nx)
    dny_dy, dny_dx = np.gradient(ny)

    pc = _get_principal_curvatures(normal_map)
    k1 = pc[:, :, 1].astype(np.float64)
    k2 = pc[:, :, 2].astype(np.float64)

    h, w = normal_map.shape[:2]
    result = np.zeros((h, w, 4), dtype=np.float32)

    # Flat-region threshold
    eps = 1e-6
    curvature_magnitude = np.abs(k1) + np.abs(k2)
    curved = curvature_magnitude > eps

    # For S = [[dnx_dx, dnx_dy], [dny_dx, dny_dy]]:
    #   eigvec for lambda = [dnx_dy, lambda - dnx_dx]
    # Direction 1 (for kappa1)
    ev1_x = dnx_dy
    ev1_y = k1 - dnx_dx
    len1 = np.sqrt(ev1_x ** 2 + ev1_y ** 2)
    len1 = np.maximum(len1, 1e-12)
    ev1_x = ev1_x / len1
    ev1_y = ev1_y / len1

    # Direction 2 (for kappa2)
    ev2_x = dnx_dy
    ev2_y = k2 - dnx_dx
    len2 = np.sqrt(ev2_x ** 2 + ev2_y ** 2)
    len2 = np.maximum(len2, 1e-12)
    ev2_x = ev2_x / len2
    ev2_y = ev2_y / len2

    result[:, :, 0] = np.where(curved, ev1_x, 0.0).astype(np.float32)
    result[:, :, 1] = np.where(curved, ev1_y, 0.0).astype(np.float32)
    result[:, :, 2] = np.where(curved, ev2_x, 0.0).astype(np.float32)
    result[:, :, 3] = np.where(curved, ev2_y, 0.0).astype(np.float32)

    return result


# ---------------------------------------------------------------------------
# ambient_occlusion_approx — normal variance as AO proxy
# ---------------------------------------------------------------------------


def ambient_occlusion_approx(
    normal_map: np.ndarray, kernel_size: int = 11
) -> np.ndarray:
    """Approximate ambient occlusion from local normal variance.

    High variance of normals in a neighborhood indicates complex geometry
    (crevices, inner corners) that would trap ambient light.

    Uses the identity: Var(n) = E[|n|^2] - |E[n]|^2, computed efficiently
    with cv2.blur.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        kernel_size: Side length of the averaging kernel.

    Returns:
        HxW float32 array in [0, 1] (1 = high occlusion).
    """
    normals = normal_map.astype(np.float64)
    ksize = (kernel_size, kernel_size)

    # E[|n|^2] — mean of squared magnitude per channel
    n_sq = normals ** 2
    mean_sq = np.zeros(normal_map.shape[:2], dtype=np.float64)
    for ch in range(3):
        mean_sq += cv2.blur(n_sq[:, :, ch], ksize)

    # |E[n]|^2 — squared magnitude of mean normal
    mean_norm_sq = np.zeros(normal_map.shape[:2], dtype=np.float64)
    for ch in range(3):
        mean_ch = cv2.blur(normals[:, :, ch], ksize)
        mean_norm_sq += mean_ch ** 2

    variance = np.maximum(mean_sq - mean_norm_sq, 0.0)

    # Normalize to [0, 1]
    max_var = variance.max()
    if max_var > 0:
        variance = variance / max_var

    return variance.astype(np.float32)


# ---------------------------------------------------------------------------
# form_vs_material_boundaries — classify discontinuities by surface context
# ---------------------------------------------------------------------------


def form_vs_material_boundaries(
    normal_map: np.ndarray, threshold: float = 0.3
) -> np.ndarray:
    """Separate normal discontinuities into form boundaries and material boundaries.

    A form boundary has different surface types on each side (geometry edge).
    A material boundary has the same surface type on both sides (paint/decal edge).

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        threshold: Minimum angular difference for a pixel to be a discontinuity.

    Returns:
        HxWx2 uint8 array: channel 0 = form boundaries (255/0),
        channel 1 = material boundaries (255/0).
    """
    # Get discontinuity mask using same logic as depth_discontinuities
    disc_mask = depth_discontinuities(normal_map, threshold=threshold)

    # Get surface types
    stype = surface_type_map(normal_map)

    h, w = normal_map.shape[:2]
    result = np.zeros((h, w, 2), dtype=np.uint8)

    # Check surface type on left/right and above/below neighbors
    # A discontinuity pixel is a form boundary if surface type differs
    # across the discontinuity; material boundary otherwise.
    disc_pixels = disc_mask > 0

    # Compare with right neighbor
    same_right = np.ones((h, w), dtype=bool)
    same_right[:, :-1] = stype[:, :-1] == stype[:, 1:]

    # Compare with bottom neighbor
    same_down = np.ones((h, w), dtype=bool)
    same_down[:-1, :] = stype[:-1, :] == stype[1:, :]

    # If either neighbor pair differs, it's a form boundary
    diff_neighbor = ~same_right | ~same_down

    form_boundary = disc_pixels & diff_neighbor
    material_boundary = disc_pixels & ~diff_neighbor

    result[:, :, 0] = form_boundary.astype(np.uint8) * 255
    result[:, :, 1] = material_boundary.astype(np.uint8) * 255

    return result


# ---------------------------------------------------------------------------
# cross_contour_field — streamlines along cross-contour direction
# ---------------------------------------------------------------------------


def cross_contour_field(
    normal_map: np.ndarray,
    spacing: int = 20,
    max_length: int = 200,
    min_curvature: float = 0.01,
    max_contours: int = 100,
) -> List[List[List[float]]]:
    """Trace cross-contour streamlines perpendicular to maximum curvature.

    Seeds are placed on a regular grid; at each seed the second principal
    direction (perpendicular to max curvature) is integrated using 4th-order
    Runge-Kutta to produce polylines.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        spacing: Pixel distance between seed points.
        max_length: Maximum streamline length in pixels.
        min_curvature: Minimum curvature magnitude to seed / continue tracing.
        max_contours: Maximum number of streamlines to return.  When exceeded,
            the longest polylines are kept and shorter ones are discarded.

    Returns:
        List of polylines; each polyline is a list of [x, y] pixel coordinates.
    """
    pc = _get_principal_curvatures(normal_map)
    curvature_mag = np.abs(pc[:, :, 1]) + np.abs(pc[:, :, 2])

    flow = surface_flow_field(normal_map)
    # Second principal direction = channels 2, 3
    dir_x = flow[:, :, 2].astype(np.float64)
    dir_y = flow[:, :, 3].astype(np.float64)

    h, w = normal_map.shape[:2]
    step_size = 1.0

    def _sample_dir(x: float, y: float) -> Tuple[float, float]:
        """Bilinear sample of the direction field."""
        ix = int(x)
        iy = int(y)
        if ix < 0 or ix >= w - 1 or iy < 0 or iy >= h - 1:
            return 0.0, 0.0
        fx = x - ix
        fy = y - iy
        dx_val = (
            dir_x[iy, ix] * (1 - fx) * (1 - fy)
            + dir_x[iy, ix + 1] * fx * (1 - fy)
            + dir_x[iy + 1, ix] * (1 - fx) * fy
            + dir_x[iy + 1, ix + 1] * fx * fy
        )
        dy_val = (
            dir_y[iy, ix] * (1 - fx) * (1 - fy)
            + dir_y[iy, ix + 1] * fx * (1 - fy)
            + dir_y[iy + 1, ix] * (1 - fx) * fy
            + dir_y[iy + 1, ix + 1] * fx * fy
        )
        length = np.sqrt(dx_val ** 2 + dy_val ** 2)
        if length < 1e-12:
            return 0.0, 0.0
        return dx_val / length, dy_val / length

    def _sample_curvature(x: float, y: float) -> float:
        ix = int(round(x))
        iy = int(round(y))
        if 0 <= ix < w and 0 <= iy < h:
            return float(curvature_mag[iy, ix])
        return 0.0

    def _rk4_step(
        x: float, y: float, sign: float
    ) -> Tuple[float, float]:
        """Single RK4 step along the direction field."""
        k1x, k1y = _sample_dir(x, y)
        k1x *= sign
        k1y *= sign

        k2x, k2y = _sample_dir(x + 0.5 * step_size * k1x, y + 0.5 * step_size * k1y)
        k2x *= sign
        k2y *= sign

        k3x, k3y = _sample_dir(x + 0.5 * step_size * k2x, y + 0.5 * step_size * k2y)
        k3x *= sign
        k3y *= sign

        k4x, k4y = _sample_dir(x + step_size * k3x, y + step_size * k3y)
        k4x *= sign
        k4y *= sign

        nx_ = x + (step_size / 6.0) * (k1x + 2 * k2x + 2 * k3x + k4x)
        ny_ = y + (step_size / 6.0) * (k1y + 2 * k2y + 2 * k3y + k4y)
        return nx_, ny_

    def _trace_half(sx: float, sy: float, sign: float) -> List[List[float]]:
        """Trace in one direction from seed."""
        points: List[List[float]] = []
        cx, cy = sx, sy
        length = 0.0
        for _ in range(max_length):
            nx_, ny_ = _rk4_step(cx, cy, sign)
            if nx_ < 0 or nx_ >= w - 1 or ny_ < 0 or ny_ >= h - 1:
                break
            if _sample_curvature(nx_, ny_) < min_curvature:
                break
            seg_len = np.sqrt((nx_ - cx) ** 2 + (ny_ - cy) ** 2)
            length += seg_len
            if length > max_length:
                break
            points.append([nx_, ny_])
            cx, cy = nx_, ny_
        return points

    polylines: List[List[List[float]]] = []
    for gy in range(spacing // 2, h, spacing):
        for gx in range(spacing // 2, w, spacing):
            if _sample_curvature(float(gx), float(gy)) < min_curvature:
                continue

            # Trace both directions, concatenate
            forward = _trace_half(float(gx), float(gy), 1.0)
            backward = _trace_half(float(gx), float(gy), -1.0)

            line = list(reversed(backward)) + [[float(gx), float(gy)]] + forward
            if len(line) >= 2:
                polylines.append(line)

    # Limit to max_contours — keep the longest polylines
    if max_contours and len(polylines) > max_contours:
        polylines.sort(key=len, reverse=True)
        polylines = polylines[:max_contours]

    return polylines


# ---------------------------------------------------------------------------
# curvature_line_weight — adaptive stroke weight from curvature + silhouette
# ---------------------------------------------------------------------------


def curvature_line_weight(
    normal_map: np.ndarray, silhouette_threshold: float = 0.15
) -> np.ndarray:
    """Compute per-pixel line weight from curvature and silhouette information.

    Weight assignment uses smooth sigmoid blending:
        - Silhouettes (|nz| < threshold): weight = 1.0
        - Valleys (H < -0.02): 0.5 + 0.2 * sigmoid(-H * 50) -> up to 0.7
        - Ridges (H > 0.02): 0.5 - 0.2 * sigmoid(H * 50) -> down to 0.3
        - Flat (|H| < 0.02): weight = 0.5
    Final weight = max(silhouette_weight, curvature_weight) so silhouettes win.

    Args:
        normal_map: HxWx3 float32 array of unit normal vectors in [-1, 1].
        silhouette_threshold: Maximum |nz| for silhouette classification.

    Returns:
        HxW float32 array in [0, 1].
    """
    pc = _get_principal_curvatures(normal_map)
    H = pc[:, :, 0].astype(np.float64)
    nz = normal_map[:, :, 2].astype(np.float64)

    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))

    # Silhouette weight
    sil_weight = np.where(np.abs(nz) < silhouette_threshold, 1.0, 0.0)

    # Curvature weight
    curv_weight = np.full_like(H, 0.5)
    valley_mask = H < -0.02
    ridge_mask = H > 0.02
    curv_weight = np.where(
        valley_mask, 0.5 + 0.2 * _sigmoid(-H * 50), curv_weight
    )
    curv_weight = np.where(
        ridge_mask, 0.5 - 0.2 * _sigmoid(H * 50), curv_weight
    )

    # Silhouettes always win
    final = np.maximum(sil_weight, curv_weight)
    return np.clip(final, 0.0, 1.0).astype(np.float32)
