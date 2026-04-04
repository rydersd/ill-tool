"""Boundary signature computation for cross-layer edge clustering.

Each extracted path sits at a boundary between two surface regions.
By sampling the normal map perpendicular to each path on both sides,
we determine WHAT kind of 3D boundary the path represents.

This creates a boundary signature: (surface_left, surface_right, boundary_curvature)
that enables clustering by structural meaning rather than proximity.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from adobe_mcp.apps.illustrator.surface_classifier import SURFACE_TYPE_NAMES


@dataclass
class BoundarySignature:
    """What 3D boundary a path represents.

    Attributes:
        surface_left: Surface type name on the left side of the path.
        surface_right: Surface type name on the right side of the path.
        boundary_curvature: Rate of normal change across the path (0-1).
        confidence: Sampling consistency score (0-1). High when left != right
            at most sample points (a real boundary). Low when the path sits
            in the middle of a uniform surface region.
    """

    surface_left: str
    surface_right: str
    boundary_curvature: float
    confidence: float

    def identity_key(self) -> str:
        """Canonical key for this edge identity. Order-invariant.

        Surfaces are sorted alphabetically so (A, B) == (B, A).
        Curvature is bucketed to the nearest 0.1 to allow fuzzy grouping.
        """
        surfaces = sorted([self.surface_left, self.surface_right])
        # Use half-up rounding instead of Python's banker's rounding to
        # ensure symmetric bucket widths (e.g. 0.05 always rounds to 0.1).
        curv_bucket = int(self.boundary_curvature * 10 + 0.5) / 10
        return f"{surfaces[0]}|{surfaces[1]}|{curv_bucket}"

    def similarity(self, other: "BoundarySignature") -> float:
        """Compute 0-1 similarity between two boundary signatures.

        Scoring tiers:
          - Same identity key: 1.0
          - Same surface pair, different curvature: 0.8 minus curvature penalty
          - One surface in common: 0.3
          - No surfaces in common: 0.0
        """
        if self.identity_key() == other.identity_key():
            return 1.0

        s1 = sorted([self.surface_left, self.surface_right])
        s2 = sorted([other.surface_left, other.surface_right])

        if s1 == s2:
            curv_diff = abs(self.boundary_curvature - other.boundary_curvature)
            return max(0.0, 0.8 - curv_diff * 2)

        # Check if any single surface matches across the two pairs
        if s1[0] in s2 or s1[1] in s2:
            return 0.3

        return 0.0


def _default_signature() -> BoundarySignature:
    """Return a zero-confidence default for degenerate inputs."""
    return BoundarySignature(
        surface_left="flat",
        surface_right="flat",
        boundary_curvature=0.0,
        confidence=0.0,
    )


def _sample_indices(n_points: int, sample_count: int) -> np.ndarray:
    """Return evenly-spaced indices along a path of *n_points* vertices.

    When sample_count >= n_points, every point is used.
    """
    if n_points <= sample_count:
        return np.arange(n_points)
    return np.linspace(0, n_points - 1, sample_count).astype(int)


def _tangents_at(points: np.ndarray) -> np.ndarray:
    """Compute unit tangent vectors at each sampled point.

    Uses central differences internally, with forward/backward at endpoints.

    Args:
        points: (N, 2) array of (x, y) pixel coordinates.

    Returns:
        (N, 2) array of unit tangent vectors.
    """
    n = len(points)
    tangents = np.empty_like(points, dtype=np.float64)

    if n == 1:
        # Single point -- arbitrary tangent
        tangents[0] = [1.0, 0.0]
        return tangents

    # Forward difference at first point
    tangents[0] = points[1] - points[0]
    # Backward difference at last point
    tangents[-1] = points[-1] - points[-2]
    # Central differences for interior points
    if n > 2:
        tangents[1:-1] = points[2:] - points[:-2]

    # Normalise; detect zero-length tangents from duplicate consecutive points
    lengths = np.linalg.norm(tangents, axis=1, keepdims=True)

    # Replace zero-length tangents with nearest non-zero tangent
    zero_mask = (lengths.ravel() < 1e-12)
    if np.any(zero_mask):
        non_zero_indices = np.where(~zero_mask)[0]
        if len(non_zero_indices) == 0:
            # All tangents are zero — degenerate path, return arbitrary tangents
            tangents[:] = [1.0, 0.0]
            return tangents
        for i in np.where(zero_mask)[0]:
            # Find nearest non-zero tangent
            nearest = non_zero_indices[np.argmin(np.abs(non_zero_indices - i))]
            tangents[i] = tangents[nearest]
        # Recompute lengths after replacement
        lengths = np.linalg.norm(tangents, axis=1, keepdims=True)

    lengths = np.maximum(lengths, 1e-12)
    tangents /= lengths
    return tangents


def _perpendiculars(tangents: np.ndarray) -> np.ndarray:
    """Rotate tangent vectors 90 degrees to get left-pointing perpendiculars.

    In pixel coordinates (Y increases downward), the CCW rotation
    ``(-ty, tx)`` actually points rightward. We use ``(ty, -tx)``
    instead so that "left" consistently means the left side of the
    path when walking along it in screen space.
    """
    perps = np.empty_like(tangents)
    perps[:, 0] = tangents[:, 1]
    perps[:, 1] = -tangents[:, 0]
    return perps


def _clamp_coords(
    coords: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Clamp (x, y) pixel coordinates to valid image bounds.

    Args:
        coords: (N, 2) float array of (x, y).
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        (N, 2) int array, clamped and rounded.
    """
    clamped = np.round(coords).astype(int)
    clamped[:, 0] = np.clip(clamped[:, 0], 0, width - 1)
    clamped[:, 1] = np.clip(clamped[:, 1], 0, height - 1)
    return clamped


def _majority_surface(type_values: np.ndarray) -> str:
    """Return the surface type name that appears most often.

    Uses numpy.bincount for fast majority vote over integer type codes (0-4).
    Clamps values to valid range to prevent crashes on negative inputs.
    """
    if len(type_values) == 0:
        return "flat"
    max_type = max(SURFACE_TYPE_NAMES.keys())
    type_values = np.clip(type_values, 0, max_type)
    counts = np.bincount(type_values, minlength=max_type + 1)
    winner = int(np.argmax(counts))
    return SURFACE_TYPE_NAMES.get(winner, "flat")


def _mean_angular_difference(
    normals_left: np.ndarray, normals_right: np.ndarray
) -> float:
    """Compute the mean angular difference between paired normal vectors.

    Result is normalised to [0, 1] where 0 = identical normals and
    1 = opposite normals (180 degrees apart).

    Args:
        normals_left: (N, 3) normals sampled on the left side.
        normals_right: (N, 3) normals sampled on the right side.

    Returns:
        Scalar in [0, 1].
    """
    # dot product per row, clamped to valid arccos range
    dots = np.sum(normals_left * normals_right, axis=1)
    dots = np.clip(dots, -1.0, 1.0)
    angles = np.arccos(dots) / np.pi  # normalise to [0, 1]
    return float(np.mean(angles))


def compute_boundary_signature(
    contour_points: list,
    normal_map: np.ndarray,
    surface_type_map: np.ndarray,
    sample_count: int = 15,
    perpendicular_offset: int = 4,
) -> BoundarySignature:
    """Sample the surface type on both sides of a path to determine
    what 3D boundary this path represents.

    Algorithm:
      1. Evenly sample ``sample_count`` points along the path.
      2. At each point, compute the path tangent and perpendicular direction.
      3. Step ``perpendicular_offset`` pixels left and right.
      4. Look up ``surface_type_map`` at each offset position.
      5. Majority vote for surface_left and surface_right.
      6. Compute ``boundary_curvature`` as mean angular difference of normals
         across the path.
      7. Confidence = fraction of samples where left != right (a real boundary).

    Args:
        contour_points: List of (x, y) tuples in pixel coordinates.
        normal_map: H x W x 3 array, normals in [-1, 1].
        surface_type_map: H x W array, integer values 0-4.
        sample_count: Number of evenly-spaced sample points along the path.
        perpendicular_offset: Pixels to step left/right from the path.

    Returns:
        BoundarySignature describing the 3D boundary at this path.
    """
    # --- Edge cases: degenerate contours ---
    if not contour_points:
        return _default_signature()

    pts = np.asarray(contour_points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] < 2:
        return _default_signature()

    # Collapse to unique points for tangent computation
    n_pts = len(pts)
    if n_pts == 0:
        return _default_signature()

    # Check for all-same-point degenerate case
    if n_pts > 1 and np.allclose(pts[0], pts, atol=1e-6):
        return _default_signature()

    h, w = surface_type_map.shape[:2]

    # Zero-dimension image guard
    if h == 0 or w == 0:
        return _default_signature()

    # 1. Sample indices along the path
    indices = _sample_indices(n_pts, sample_count)
    sampled_pts = pts[indices]  # (K, 2)

    # 2. Tangents and perpendiculars at each sample
    tangents = _tangents_at(sampled_pts)
    perps = _perpendiculars(tangents)

    # 3. Left and right sample positions
    left_pos = sampled_pts + perps * perpendicular_offset
    right_pos = sampled_pts - perps * perpendicular_offset

    # 4. Clamp to image bounds and look up surface types
    left_px = _clamp_coords(left_pos, w, h)
    right_px = _clamp_coords(right_pos, w, h)

    left_types = surface_type_map[left_px[:, 1], left_px[:, 0]]
    right_types = surface_type_map[right_px[:, 1], right_px[:, 0]]

    # 5. Majority vote for each side
    surface_left = _majority_surface(left_types.astype(int))
    surface_right = _majority_surface(right_types.astype(int))

    # 6. Boundary curvature from normal map angular difference
    left_normals = normal_map[left_px[:, 1], left_px[:, 0]]   # (K, 3)
    right_normals = normal_map[right_px[:, 1], right_px[:, 0]]  # (K, 3)
    boundary_curvature = _mean_angular_difference(left_normals, right_normals)

    # 7. Confidence = fraction where left type != right type
    n_different = int(np.sum(left_types != right_types))
    confidence = n_different / len(indices) if len(indices) > 0 else 0.0

    return BoundarySignature(
        surface_left=surface_left,
        surface_right=surface_right,
        boundary_curvature=round(boundary_curvature, 6),
        confidence=round(confidence, 4),
    )


def compute_signatures_batch(
    contours: list,
    normal_map: np.ndarray,
    surface_type_map: np.ndarray,
    sample_count: int = 15,
    perpendicular_offset: int = 4,
) -> list[BoundarySignature]:
    """Compute boundary signatures for multiple contours.

    Each contour dict must have a ``'points'`` key containing a list of
    (x, y) tuples in pixel coordinates.

    Args:
        contours: List of dicts with ``'points'`` key.
        normal_map: H x W x 3 normal map.
        surface_type_map: H x W integer surface type map.
        sample_count: Samples per contour.
        perpendicular_offset: Pixels to step left/right.

    Returns:
        List of BoundarySignature, one per contour, in the same order.
    """
    results: list[BoundarySignature] = []
    for contour in contours:
        points = contour.get("points", [])
        sig = compute_boundary_signature(
            contour_points=points,
            normal_map=normal_map,
            surface_type_map=surface_type_map,
            sample_count=sample_count,
            perpendicular_offset=perpendicular_offset,
        )
        results.append(sig)
    return results
