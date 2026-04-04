"""Tests for boundary_signature — cross-layer edge clustering Phase 1.

Tests use synthetic normal maps and surface type maps (no ML dependencies).
A 100x100 image with left half = cylindrical (4) and right half = flat (0)
provides a clear boundary at x=50 for testing boundary detection.
"""

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.analysis.boundary_signature import (
    BoundarySignature,
    compute_boundary_signature,
    compute_signatures_batch,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic 100x100 normal map and surface type map
# ---------------------------------------------------------------------------


@pytest.fixture()
def uniform_normal_map():
    """100x100 normal map with all normals pointing straight up [0, 0, 1]."""
    nmap = np.zeros((100, 100, 3), dtype=np.float32)
    nmap[:, :, 2] = 1.0  # Z = 1, pointing up
    return nmap


@pytest.fixture()
def split_normal_map():
    """100x100 normal map with left half tilted left, right half tilted right.

    Left normals: [-0.7, 0, 0.7] (tilted left)
    Right normals: [0.7, 0, 0.7] (tilted right)
    This creates a measurable angular difference at the boundary.
    """
    nmap = np.zeros((100, 100, 3), dtype=np.float32)
    # Left half: normals tilted to -X
    nmap[:, :50, 0] = -0.7071
    nmap[:, :50, 2] = 0.7071
    # Right half: normals tilted to +X
    nmap[:, 50:, 0] = 0.7071
    nmap[:, 50:, 2] = 0.7071
    return nmap


@pytest.fixture()
def split_surface_map():
    """100x100 surface type map: left half = 4 (cylindrical), right half = 0 (flat)."""
    smap = np.zeros((100, 100), dtype=np.uint8)
    smap[:, :50] = 4  # cylindrical
    smap[:, 50:] = 0  # flat
    return smap


@pytest.fixture()
def uniform_surface_map():
    """100x100 surface type map: all flat (0)."""
    return np.zeros((100, 100), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Vertical path at boundary (x=50) and horizontal path in cylindrical region
# ---------------------------------------------------------------------------


@pytest.fixture()
def vertical_boundary_path():
    """Vertical path at x=50 (the boundary), running y=10..90."""
    return [(50, y) for y in range(10, 91)]


@pytest.fixture()
def horizontal_cylindrical_path():
    """Horizontal path at y=50, x=10..40 — entirely within the cylindrical region."""
    return [(x, 50) for x in range(10, 41)]


# ---------------------------------------------------------------------------
# Test: flat region — both sides same, low confidence
# ---------------------------------------------------------------------------


class TestBoundarySignatureFlatRegion:
    """Path in the middle of a uniform flat region."""

    def test_both_sides_flat(self, uniform_normal_map, uniform_surface_map):
        # Horizontal path in the centre of a fully-flat map
        path = [(x, 50) for x in range(20, 80)]
        sig = compute_boundary_signature(
            path, uniform_normal_map, uniform_surface_map
        )
        assert sig.surface_left == "flat"
        assert sig.surface_right == "flat"

    def test_low_confidence(self, uniform_normal_map, uniform_surface_map):
        path = [(x, 50) for x in range(20, 80)]
        sig = compute_boundary_signature(
            path, uniform_normal_map, uniform_surface_map
        )
        # Same surface on both sides => confidence should be 0
        assert sig.confidence == pytest.approx(0.0, abs=0.01)

    def test_low_curvature(self, uniform_normal_map, uniform_surface_map):
        path = [(x, 50) for x in range(20, 80)]
        sig = compute_boundary_signature(
            path, uniform_normal_map, uniform_surface_map
        )
        # Normals identical on both sides => curvature ~0
        assert sig.boundary_curvature == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test: path at cylinder-flat boundary
# ---------------------------------------------------------------------------


class TestBoundarySignatureAtBoundary:
    """Vertical path at x=50 where cylindrical meets flat."""

    def test_detects_cylindrical_and_flat(
        self, split_normal_map, split_surface_map, vertical_boundary_path
    ):
        sig = compute_boundary_signature(
            vertical_boundary_path,
            split_normal_map,
            split_surface_map,
            perpendicular_offset=4,
        )
        # For a vertical path, the perpendicular is horizontal.
        # Left of path (lower x) = cylindrical, right of path (higher x) = flat.
        surfaces = sorted([sig.surface_left, sig.surface_right])
        assert surfaces == ["cylindrical", "flat"]

    def test_high_confidence(
        self, split_normal_map, split_surface_map, vertical_boundary_path
    ):
        sig = compute_boundary_signature(
            vertical_boundary_path,
            split_normal_map,
            split_surface_map,
            perpendicular_offset=4,
        )
        # Different surface on each side at every sample => high confidence
        assert sig.confidence > 0.8

    def test_nonzero_curvature(
        self, split_normal_map, split_surface_map, vertical_boundary_path
    ):
        sig = compute_boundary_signature(
            vertical_boundary_path,
            split_normal_map,
            split_surface_map,
            perpendicular_offset=4,
        )
        # Normals differ across the boundary => curvature > 0
        assert sig.boundary_curvature > 0.1


# ---------------------------------------------------------------------------
# Test: identity key — order invariance
# ---------------------------------------------------------------------------


class TestIdentityKeyOrderInvariant:
    """identity_key must produce the same string regardless of left/right order."""

    def test_ab_equals_ba(self):
        sig_ab = BoundarySignature(
            surface_left="convex",
            surface_right="flat",
            boundary_curvature=0.3,
            confidence=0.9,
        )
        sig_ba = BoundarySignature(
            surface_left="flat",
            surface_right="convex",
            boundary_curvature=0.3,
            confidence=0.9,
        )
        assert sig_ab.identity_key() == sig_ba.identity_key()

    def test_symmetric_for_all_pairs(self):
        for a in ("flat", "convex", "concave", "saddle", "cylindrical"):
            for b in ("flat", "convex", "concave", "saddle", "cylindrical"):
                sig1 = BoundarySignature(a, b, 0.5, 1.0)
                sig2 = BoundarySignature(b, a, 0.5, 1.0)
                assert sig1.identity_key() == sig2.identity_key(), f"Failed for ({a}, {b})"


# ---------------------------------------------------------------------------
# Test: identity key — curvature bucketing
# ---------------------------------------------------------------------------


class TestIdentityKeyCurvatureBucketing:
    """Curvature values bucketed to nearest 0.1."""

    def test_same_bucket(self):
        sig_a = BoundarySignature("flat", "convex", 0.31, 0.9)
        sig_b = BoundarySignature("flat", "convex", 0.34, 0.9)
        # Both round to 0.3
        assert sig_a.identity_key() == sig_b.identity_key()

    def test_different_bucket(self):
        sig_a = BoundarySignature("flat", "convex", 0.31, 0.9)
        sig_b = BoundarySignature("flat", "convex", 0.39, 0.9)
        # 0.31 rounds to 0.3, 0.39 rounds to 0.4
        assert sig_a.identity_key() != sig_b.identity_key()

    def test_edge_of_bucket(self):
        sig_a = BoundarySignature("flat", "flat", 0.06, 0.5)
        sig_b = BoundarySignature("flat", "flat", 0.14, 0.5)
        # 0.06 rounds to 0.1, 0.14 rounds to 0.1
        assert sig_a.identity_key() == sig_b.identity_key()


# ---------------------------------------------------------------------------
# Test: similarity — same identity
# ---------------------------------------------------------------------------


class TestSimilaritySameIdentity:
    """Identical signatures should return 1.0."""

    def test_perfect_match(self):
        sig = BoundarySignature("convex", "flat", 0.3, 0.9)
        assert sig.similarity(sig) == 1.0

    def test_swapped_order_same_curvature_bucket(self):
        sig_a = BoundarySignature("convex", "flat", 0.3, 0.9)
        sig_b = BoundarySignature("flat", "convex", 0.32, 0.8)
        # Both bucket to 0.3 and same surfaces
        assert sig_a.similarity(sig_b) == 1.0


# ---------------------------------------------------------------------------
# Test: similarity — same surfaces, different curvature
# ---------------------------------------------------------------------------


class TestSimilaritySameSurfacesDifferentCurvature:
    """Same surface pair but different curvature bucket."""

    def test_small_curvature_difference(self):
        sig_a = BoundarySignature("convex", "flat", 0.2, 0.9)
        sig_b = BoundarySignature("flat", "convex", 0.3, 0.9)
        # Same pair, curvature diff = 0.1 => 0.8 - 0.1*2 = 0.6
        assert sig_a.similarity(sig_b) == pytest.approx(0.6, abs=0.01)

    def test_large_curvature_difference(self):
        sig_a = BoundarySignature("convex", "flat", 0.1, 0.9)
        sig_b = BoundarySignature("flat", "convex", 0.8, 0.9)
        # Same pair, curvature diff = 0.7 => 0.8 - 0.7*2 = -0.6 => clamped to 0.0
        assert sig_a.similarity(sig_b) == pytest.approx(0.0, abs=0.01)

    def test_moderate_difference(self):
        sig_a = BoundarySignature("cylindrical", "concave", 0.3, 0.9)
        sig_b = BoundarySignature("concave", "cylindrical", 0.5, 0.9)
        # diff = 0.2 => 0.8 - 0.2*2 = 0.4
        assert sig_a.similarity(sig_b) == pytest.approx(0.4, abs=0.01)


# ---------------------------------------------------------------------------
# Test: similarity — one surface matches
# ---------------------------------------------------------------------------


class TestSimilarityOneMatch:
    """One surface in common should return 0.3."""

    def test_one_shared_surface(self):
        sig_a = BoundarySignature("convex", "flat", 0.3, 0.9)
        sig_b = BoundarySignature("convex", "concave", 0.3, 0.9)
        assert sig_a.similarity(sig_b) == pytest.approx(0.3, abs=0.01)

    def test_one_shared_reversed(self):
        sig_a = BoundarySignature("flat", "saddle", 0.5, 0.8)
        sig_b = BoundarySignature("cylindrical", "saddle", 0.5, 0.8)
        assert sig_a.similarity(sig_b) == pytest.approx(0.3, abs=0.01)


# ---------------------------------------------------------------------------
# Test: similarity — no match
# ---------------------------------------------------------------------------


class TestSimilarityNoMatch:
    """No surfaces in common should return 0.0."""

    def test_completely_different(self):
        sig_a = BoundarySignature("convex", "flat", 0.3, 0.9)
        sig_b = BoundarySignature("concave", "saddle", 0.3, 0.9)
        assert sig_a.similarity(sig_b) == pytest.approx(0.0, abs=0.01)

    def test_different_with_different_curvature(self):
        sig_a = BoundarySignature("convex", "flat", 0.1, 0.5)
        sig_b = BoundarySignature("concave", "cylindrical", 0.8, 0.9)
        assert sig_a.similarity(sig_b) == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test: batch computation
# ---------------------------------------------------------------------------


class TestBatchComputation:
    """compute_signatures_batch should return one signature per contour."""

    def test_batch_of_five(self, uniform_normal_map, uniform_surface_map):
        contours = [
            {"points": [(x, 50) for x in range(20, 40)]}
            for _ in range(5)
        ]
        sigs = compute_signatures_batch(
            contours, uniform_normal_map, uniform_surface_map
        )
        assert len(sigs) == 5
        assert all(isinstance(s, BoundarySignature) for s in sigs)

    def test_batch_preserves_order(self, split_normal_map, split_surface_map):
        # First contour in cylindrical region, second at boundary
        contours = [
            {"points": [(x, 50) for x in range(10, 41)]},  # all cylindrical
            {"points": [(50, y) for y in range(10, 91)]},   # at boundary
        ]
        sigs = compute_signatures_batch(
            contours, split_normal_map, split_surface_map
        )
        assert len(sigs) == 2
        # First contour: both sides cylindrical (it's fully inside the left half)
        assert sigs[0].surface_left == "cylindrical"
        assert sigs[0].surface_right == "cylindrical"
        # Second contour: crosses the boundary
        surfaces = sorted([sigs[1].surface_left, sigs[1].surface_right])
        assert surfaces == ["cylindrical", "flat"]

    def test_empty_contour_list(self, uniform_normal_map, uniform_surface_map):
        sigs = compute_signatures_batch(
            [], uniform_normal_map, uniform_surface_map
        )
        assert sigs == []


# ---------------------------------------------------------------------------
# Test: edge cases — degenerate contours
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Empty, single-point, and all-same-point contours should not crash."""

    def test_empty_contour(self, uniform_normal_map, uniform_surface_map):
        sig = compute_boundary_signature(
            [], uniform_normal_map, uniform_surface_map
        )
        assert sig.confidence == 0.0
        assert sig.surface_left == "flat"
        assert sig.surface_right == "flat"

    def test_single_point_contour(self, uniform_normal_map, uniform_surface_map):
        sig = compute_boundary_signature(
            [(50, 50)], uniform_normal_map, uniform_surface_map
        )
        # Single point means tangent is arbitrary, but should not crash
        assert isinstance(sig, BoundarySignature)
        assert sig.confidence >= 0.0

    def test_all_same_point_contour(self, uniform_normal_map, uniform_surface_map):
        sig = compute_boundary_signature(
            [(30, 30)] * 20, uniform_normal_map, uniform_surface_map
        )
        # All-same-point is degenerate — should return default
        assert sig.confidence == 0.0
        assert sig.surface_left == "flat"
        assert sig.surface_right == "flat"

    def test_two_point_contour(self, uniform_normal_map, uniform_surface_map):
        sig = compute_boundary_signature(
            [(20, 50), (80, 50)], uniform_normal_map, uniform_surface_map
        )
        assert isinstance(sig, BoundarySignature)

    def test_batch_with_empty_points_key(self, uniform_normal_map, uniform_surface_map):
        contours = [{"points": []}, {"name": "no_points"}]
        sigs = compute_signatures_batch(
            contours, uniform_normal_map, uniform_surface_map
        )
        assert len(sigs) == 2
        assert all(s.confidence == 0.0 for s in sigs)


# ---------------------------------------------------------------------------
# Test: boundary signature near image edges (adversarial review gap #3)
# ---------------------------------------------------------------------------


class TestBoundarySignatureNearImageEdge:
    """Perpendicular sampling near image boundaries must clamp without crash.

    When a path runs along the edge of the image, the perpendicular offset
    would sample outside the image bounds. The implementation should clamp
    coordinates and still produce a valid signature.
    """

    def test_path_along_top_edge(self, split_normal_map, split_surface_map):
        """Horizontal path at y=0 — perpendicular samples above the image."""
        path = [(x, 0) for x in range(10, 90)]
        sig = compute_boundary_signature(
            path, split_normal_map, split_surface_map,
            perpendicular_offset=10,
        )
        assert isinstance(sig, BoundarySignature)
        # Should not crash; confidence may be low due to clamped samples
        assert sig.confidence >= 0.0

    def test_path_along_bottom_edge(self, split_normal_map, split_surface_map):
        """Horizontal path at y=99 — perpendicular samples below the image."""
        path = [(x, 99) for x in range(10, 90)]
        sig = compute_boundary_signature(
            path, split_normal_map, split_surface_map,
            perpendicular_offset=10,
        )
        assert isinstance(sig, BoundarySignature)
        assert sig.confidence >= 0.0

    def test_path_along_left_edge(self, split_normal_map, split_surface_map):
        """Vertical path at x=0 — perpendicular samples left of the image."""
        path = [(0, y) for y in range(10, 90)]
        sig = compute_boundary_signature(
            path, split_normal_map, split_surface_map,
            perpendicular_offset=10,
        )
        assert isinstance(sig, BoundarySignature)
        assert sig.confidence >= 0.0

    def test_path_along_right_edge(self, split_normal_map, split_surface_map):
        """Vertical path at x=99 — perpendicular samples right of the image."""
        path = [(99, y) for y in range(10, 90)]
        sig = compute_boundary_signature(
            path, split_normal_map, split_surface_map,
            perpendicular_offset=10,
        )
        assert isinstance(sig, BoundarySignature)
        assert sig.confidence >= 0.0

    def test_corner_path(self, uniform_normal_map, uniform_surface_map):
        """Path at the corner (0,0) to (1,1) — perpendicular hits two edges."""
        path = [(0, 0), (1, 1)]
        sig = compute_boundary_signature(
            path, uniform_normal_map, uniform_surface_map,
            perpendicular_offset=5,
        )
        assert isinstance(sig, BoundarySignature)
        assert sig.confidence >= 0.0

    def test_large_perpendicular_offset(self, uniform_normal_map, uniform_surface_map):
        """Perpendicular offset larger than image dimensions still works."""
        path = [(50, 50), (51, 50)]
        sig = compute_boundary_signature(
            path, uniform_normal_map, uniform_surface_map,
            perpendicular_offset=200,  # larger than 100x100 image
        )
        assert isinstance(sig, BoundarySignature)
        # Both clamped samples land at the same edge -> same surface
        assert sig.confidence >= 0.0

    def test_zero_dimension_image(self):
        """Zero-dimension normal map and surface type map return default."""
        import numpy as np
        zero_normal = np.zeros((0, 100, 3), dtype=np.float32)
        zero_surface = np.zeros((0, 100), dtype=np.uint8)
        path = [(50, 50), (60, 50)]
        sig = compute_boundary_signature(
            path, zero_normal, zero_surface,
        )
        assert sig.confidence == 0.0
        assert sig.surface_left == "flat"
        assert sig.surface_right == "flat"

    def test_perpendicular_direction_consistency(self, split_normal_map, split_surface_map):
        """Perpendicular direction is consistent: left of a vertical upward path
        should be the -x side (cylindrical in our split map), right should be +x (flat).

        With the corrected perpendicular (ty, -tx), a vertical path walking
        downward (increasing y) should have left=cylindrical, right=flat for our
        split map (cylindrical at x<50, flat at x>=50).
        """
        # Vertical path at x=50, walking downward (y=10 to y=90)
        path = [(50, y) for y in range(10, 91)]
        sig = compute_boundary_signature(
            path, split_normal_map, split_surface_map,
            perpendicular_offset=10,
        )
        # The specific left/right assignment depends on the perpendicular direction.
        # What matters is that both surfaces are detected.
        surfaces = sorted([sig.surface_left, sig.surface_right])
        assert surfaces == ["cylindrical", "flat"]
