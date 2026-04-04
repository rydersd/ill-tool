"""Tests for normal_renderings — post-processing utilities for normal maps.

Uses synthetic normal maps (flat plane, sphere, cube) to verify each
rendering function produces correct output shapes, dtypes, and values
for known geometric inputs.  No ML dependencies required.
"""

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.normal_renderings import (
    curvature_map,
    depth_discontinuities,
    flat_planes,
    form_lines,
    relit_reference,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic normal maps
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def flat_normal_map():
    """100x100 constant-normal surface (all normals point straight up: +Z).

    Represents a perfectly flat plane facing the camera.
    """
    normals = np.zeros((100, 100, 3), dtype=np.float32)
    normals[:, :, 2] = 1.0  # all normals = (0, 0, 1)
    return normals


@pytest.fixture(scope="session")
def sphere_normal_map():
    """100x100 sphere normal map — normals vary smoothly from center to edge.

    Center pixel = (0, 0, 1), edges fan outward.  Outside the sphere radius
    gets a default (0, 0, 1) normal.
    """
    size = 100
    normals = np.zeros((size, size, 3), dtype=np.float32)
    cx, cy = size / 2, size / 2
    radius = size / 2 - 1

    for y in range(size):
        for x in range(size):
            dx = (x - cx) / radius
            dy = (y - cy) / radius
            r2 = dx * dx + dy * dy
            if r2 <= 1.0:
                dz = np.sqrt(1.0 - r2)
                normals[y, x] = (dx, dy, dz)
            else:
                normals[y, x] = (0.0, 0.0, 1.0)

    return normals


@pytest.fixture(scope="session")
def cube_normal_map():
    """120x120 image with 3 distinct normal clusters simulating cube faces.

    Top third: normals pointing up (+Y) = (0, 1, 0)
    Middle third: normals pointing right (+X) = (1, 0, 0)
    Bottom third: normals pointing toward camera (+Z) = (0, 0, 1)
    """
    normals = np.zeros((120, 120, 3), dtype=np.float32)
    normals[0:40, :] = (0.0, 1.0, 0.0)    # top face
    normals[40:80, :] = (1.0, 0.0, 0.0)    # right face
    normals[80:120, :] = (0.0, 0.0, 1.0)   # front face
    return normals


@pytest.fixture(scope="session")
def step_normal_map():
    """100x100 map with a sharp normal discontinuity down the middle.

    Left half: normals point left (-1, 0, 0)
    Right half: normals point right (1, 0, 0)
    Simulates an occlusion edge / depth step.
    """
    normals = np.zeros((100, 100, 3), dtype=np.float32)
    normals[:, :50] = (-1.0, 0.0, 0.0)
    normals[:, 50:] = (1.0, 0.0, 0.0)
    return normals


@pytest.fixture(scope="session")
def frontal_image():
    """100x100 solid mid-gray image for relighting tests."""
    return np.full((100, 100, 3), 128, dtype=np.uint8)


# ---------------------------------------------------------------------------
# flat_planes tests
# ---------------------------------------------------------------------------


class TestFlatPlanes:
    """Verify K-means plane clustering on normal maps."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        """Output should be HxWx3 uint8 BGR image."""
        result = flat_planes(flat_normal_map, k=3)
        assert result.shape == (100, 100, 3)
        assert result.dtype == np.uint8

    def test_constant_surface_produces_one_effective_color(self, flat_normal_map):
        """A flat plane (single normal) should produce essentially one color.

        K-means may create k labels but they should all converge to the same
        centroid, so the image should be nearly uniform.
        """
        result = flat_planes(flat_normal_map, k=3)
        # All pixels should be the same color (single cluster dominates)
        unique_colors = np.unique(result.reshape(-1, 3), axis=0)
        # With a perfectly constant input, k-means should converge to 1 color
        # (or very few due to floating point).  Allow up to k but check
        # that one color dominates >95% of pixels.
        dominant_count = 0
        for color in unique_colors:
            count = np.sum(np.all(result == color, axis=2))
            dominant_count = max(dominant_count, count)
        assert dominant_count >= 0.95 * 100 * 100

    def test_cube_produces_k_clusters(self, cube_normal_map):
        """Cube with 3 distinct normals and k=3 should yield exactly 3 colors."""
        result = flat_planes(cube_normal_map, k=3)
        unique_colors = np.unique(result.reshape(-1, 3), axis=0)
        assert len(unique_colors) == 3

    def test_cube_clusters_respect_regions(self, cube_normal_map):
        """Each third of the cube image should be uniformly one color."""
        result = flat_planes(cube_normal_map, k=3)
        # Top third should be uniform
        top = result[0:40, :]
        assert len(np.unique(top.reshape(-1, 3), axis=0)) == 1
        # Middle third should be uniform
        mid = result[40:80, :]
        assert len(np.unique(mid.reshape(-1, 3), axis=0)) == 1
        # Bottom third should be uniform
        bot = result[80:120, :]
        assert len(np.unique(bot.reshape(-1, 3), axis=0)) == 1

    def test_different_k_values(self, sphere_normal_map):
        """Requesting different k values should produce different cluster counts."""
        r2 = flat_planes(sphere_normal_map, k=2)
        r8 = flat_planes(sphere_normal_map, k=8)
        colors_2 = len(np.unique(r2.reshape(-1, 3), axis=0))
        colors_8 = len(np.unique(r8.reshape(-1, 3), axis=0))
        assert colors_2 <= colors_8


# ---------------------------------------------------------------------------
# form_lines tests
# ---------------------------------------------------------------------------


class TestFormLines:
    """Verify Sobel-based form edge detection on normal maps."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        """Output should be HxW uint8 edge mask."""
        result = form_lines(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.uint8

    def test_flat_surface_produces_no_edges(self, flat_normal_map):
        """A constant-normal surface has zero gradient — no edges."""
        result = form_lines(flat_normal_map, threshold=0.1)
        assert np.sum(result) == 0

    def test_step_discontinuity_produces_edges(self, step_normal_map):
        """A sharp normal change should produce strong edges at the boundary."""
        result = form_lines(step_normal_map, threshold=0.3)
        assert np.sum(result) > 0
        # Edges should be concentrated near column 50 (the discontinuity)
        edge_cols = np.where(result.any(axis=0))[0]
        assert len(edge_cols) > 0
        # All edge columns should be near the center
        assert all(40 <= c <= 60 for c in edge_cols)

    def test_sphere_has_edges_at_rim(self, sphere_normal_map):
        """Sphere normals change fastest at the rim — should produce edges there."""
        result = form_lines(sphere_normal_map, threshold=0.5)
        assert np.sum(result) > 0

    def test_threshold_sensitivity(self, sphere_normal_map):
        """Lower threshold should produce more edge pixels."""
        low = form_lines(sphere_normal_map, threshold=0.2)
        high = form_lines(sphere_normal_map, threshold=0.8)
        assert np.sum(low) >= np.sum(high)

    def test_output_is_binary(self, step_normal_map):
        """Edge mask should contain only 0 and 255."""
        result = form_lines(step_normal_map, threshold=0.3)
        unique_vals = np.unique(result)
        assert all(v in (0, 255) for v in unique_vals)


# ---------------------------------------------------------------------------
# curvature_map tests
# ---------------------------------------------------------------------------


class TestCurvatureMap:
    """Verify Gaussian curvature approximation from normal field."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        """Output should be HxW float32."""
        result = curvature_map(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.float32

    def test_flat_surface_has_zero_curvature(self, flat_normal_map):
        """A flat plane has zero Gaussian curvature everywhere."""
        result = curvature_map(flat_normal_map)
        assert np.allclose(result, 0.0, atol=1e-6)

    def test_sphere_has_nonzero_curvature(self, sphere_normal_map):
        """A sphere has positive Gaussian curvature — at least some pixels nonzero."""
        result = curvature_map(sphere_normal_map)
        # The interior of the sphere (away from edges) should show curvature
        center_region = result[30:70, 30:70]
        assert np.any(np.abs(center_region) > 1e-6)

    def test_cube_flat_faces_near_zero(self, cube_normal_map):
        """Interior of each cube face should have near-zero curvature."""
        result = curvature_map(cube_normal_map)
        # Sample well inside each face (away from boundaries)
        top_interior = result[5:35, 10:110]
        mid_interior = result[45:75, 10:110]
        bot_interior = result[85:115, 10:110]
        assert np.allclose(top_interior, 0.0, atol=1e-6)
        assert np.allclose(mid_interior, 0.0, atol=1e-6)
        assert np.allclose(bot_interior, 0.0, atol=1e-6)

    def test_crease_has_zero_gaussian_curvature(self, cube_normal_map):
        """A crease (normal step in one axis only) has zero Gaussian curvature.

        This is geometrically correct: Gaussian curvature = det(shape operator),
        which is zero for developable surfaces like a single fold/crease.
        """
        result = curvature_map(cube_normal_map)
        # Even at the boundary rows, Gaussian curvature is zero because
        # the normal variation is purely along the y-axis.
        assert np.allclose(result, 0.0, atol=1e-6)

    def test_corner_has_nonzero_gaussian_curvature(self):
        """A corner where normals change in both x and y has nonzero curvature.

        Four quadrants with distinct normals create a corner point where
        the shape operator determinant is nonzero.
        """
        normals = np.zeros((100, 100, 3), dtype=np.float32)
        normals[:50, :50] = (0.0, 0.0, 1.0)    # top-left: +Z
        normals[:50, 50:] = (1.0, 0.0, 0.0)    # top-right: +X
        normals[50:, :50] = (0.0, 1.0, 0.0)    # bottom-left: +Y
        normals[50:, 50:] = (0.0, 0.0, 1.0)    # bottom-right: +Z

        result = curvature_map(normals)
        # The corner region (around row 50, col 50) should have nonzero curvature
        corner_region = result[48:52, 48:52]
        assert np.any(np.abs(corner_region) > 1e-4)


# ---------------------------------------------------------------------------
# relit_reference tests
# ---------------------------------------------------------------------------


class TestRelitReference:
    """Verify synthetic relighting via normal dot product."""

    def test_output_shape_and_dtype(self, frontal_image, flat_normal_map):
        """Output should be HxWx3 uint8 BGR."""
        result = relit_reference(frontal_image, flat_normal_map)
        assert result.shape == (100, 100, 3)
        assert result.dtype == np.uint8

    def test_frontal_light_on_frontal_surface_preserves_brightness(
        self, frontal_image, flat_normal_map
    ):
        """Flat surface facing camera + frontal light = dot product 1.0.

        Result should match original image exactly (128 * 1.0 = 128).
        """
        result = relit_reference(
            frontal_image, flat_normal_map, light_dir=(0.0, 0.0, 1.0)
        )
        assert np.allclose(result, frontal_image, atol=1)

    def test_back_light_produces_dark_image(self, frontal_image, flat_normal_map):
        """Light from behind the surface (negative Z) should give zero brightness."""
        result = relit_reference(
            frontal_image, flat_normal_map, light_dir=(0.0, 0.0, -1.0)
        )
        assert np.all(result == 0)

    def test_side_light_on_flat_surface_produces_dark(
        self, frontal_image, flat_normal_map
    ):
        """Pure side light (1,0,0) on (0,0,1) normal: dot = 0 -> black."""
        result = relit_reference(
            frontal_image, flat_normal_map, light_dir=(1.0, 0.0, 0.0)
        )
        assert np.all(result == 0)

    def test_sphere_frontal_light_brighter_at_center(
        self, frontal_image, sphere_normal_map
    ):
        """Frontal light on a sphere: center (normal=(0,0,1)) should be brightest."""
        # Need a 100x100 image to match sphere
        img = np.full((100, 100, 3), 200, dtype=np.uint8)
        result = relit_reference(img, sphere_normal_map, light_dir=(0.0, 0.0, 1.0))
        center_brightness = int(result[50, 50].mean())
        edge_brightness = int(result[50, 5].mean())
        assert center_brightness > edge_brightness

    def test_zero_light_dir_defaults_to_frontal(
        self, frontal_image, flat_normal_map
    ):
        """A zero-length light direction should fall back to frontal (0,0,1)."""
        result = relit_reference(
            frontal_image, flat_normal_map, light_dir=(0.0, 0.0, 0.0)
        )
        # Should behave like frontal light
        assert np.allclose(result, frontal_image, atol=1)

    def test_unnormalized_light_is_normalized(
        self, frontal_image, flat_normal_map
    ):
        """Non-unit light vector should be normalized before use."""
        r1 = relit_reference(
            frontal_image, flat_normal_map, light_dir=(0.0, 0.0, 1.0)
        )
        r2 = relit_reference(
            frontal_image, flat_normal_map, light_dir=(0.0, 0.0, 5.0)
        )
        assert np.array_equal(r1, r2)


# ---------------------------------------------------------------------------
# depth_discontinuities tests
# ---------------------------------------------------------------------------


class TestDepthDiscontinuities:
    """Verify occlusion edge detection from normal discontinuities."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        """Output should be HxW uint8 edge mask."""
        result = depth_discontinuities(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.uint8

    def test_flat_surface_no_discontinuities(self, flat_normal_map):
        """Constant normals should produce zero edges."""
        result = depth_discontinuities(flat_normal_map, threshold=0.1)
        assert np.sum(result) == 0

    def test_step_produces_edge_at_boundary(self, step_normal_map):
        """Sharp left/right normal flip should produce strong edge at column 49-50."""
        result = depth_discontinuities(step_normal_map, threshold=0.3)
        assert np.sum(result) > 0
        # Edge should be at the discontinuity boundary
        edge_cols = np.where(result.any(axis=0))[0]
        assert len(edge_cols) > 0
        # Boundary is between columns 49 and 50
        assert any(48 <= c <= 51 for c in edge_cols)

    def test_sphere_rim_has_discontinuities(self, sphere_normal_map):
        """Sphere-to-background boundary should trigger discontinuity detection.

        The sphere fixture fills the outside with (0,0,1) which differs from
        the rim normals — creating discontinuities at the sphere edge.
        """
        # Use a low threshold to catch the sphere-to-flat transition
        result = depth_discontinuities(sphere_normal_map, threshold=0.05)
        assert np.sum(result) > 0

    def test_output_is_binary(self, step_normal_map):
        """Edge mask should contain only 0 and 255."""
        result = depth_discontinuities(step_normal_map, threshold=0.3)
        unique_vals = np.unique(result)
        assert all(v in (0, 255) for v in unique_vals)

    def test_threshold_sensitivity(self, step_normal_map):
        """Lower threshold should detect more edges (or equal)."""
        low = depth_discontinuities(step_normal_map, threshold=0.1)
        high = depth_discontinuities(step_normal_map, threshold=0.9)
        assert np.sum(low) >= np.sum(high)

    def test_cube_boundaries_detected(self, cube_normal_map):
        """Boundaries between cube faces should be detected as discontinuities."""
        result = depth_discontinuities(cube_normal_map, threshold=0.3)
        # Row 39/40 boundary and row 79/80 boundary should have edges
        boundary_1 = result[39:41, :]
        boundary_2 = result[79:81, :]
        assert np.sum(boundary_1) > 0
        assert np.sum(boundary_2) > 0
