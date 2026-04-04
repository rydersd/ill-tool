"""Tests for expanded normal_renderings — principal curvatures, surface analysis,
flow fields, AO, boundary classification, cross-contours, and line weight.

Uses synthetic normal maps (flat plane, sphere, cube, step) to verify each
rendering function produces correct output shapes, dtypes, and values
for known geometric inputs.  No ML dependencies required.
"""

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.normal_renderings import (
    ambient_occlusion_approx,
    cross_contour_field,
    curvature_line_weight,
    curvature_map,
    depth_facing_map,
    form_vs_material_boundaries,
    principal_curvatures,
    ridge_valley_map,
    silhouette_contours,
    surface_flow_field,
    surface_type_map,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic normal maps (duplicated from test_normal_renderings.py)
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


# ---------------------------------------------------------------------------
# principal_curvatures tests
# ---------------------------------------------------------------------------


class TestPrincipalCurvatures:
    """Verify eigendecomposition of the shape operator."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        """Output should be HxWx3 float32."""
        result = principal_curvatures(flat_normal_map)
        assert result.shape == (100, 100, 3)
        assert result.dtype == np.float32

    def test_flat_surface_zero_curvature(self, flat_normal_map):
        """A flat plane has H ~ 0, kappa1 ~ 0, kappa2 ~ 0 everywhere."""
        result = principal_curvatures(flat_normal_map)
        assert np.allclose(result[:, :, 0], 0.0, atol=1e-6), "Mean curvature H != 0"
        assert np.allclose(result[:, :, 1], 0.0, atol=1e-6), "kappa1 != 0"
        assert np.allclose(result[:, :, 2], 0.0, atol=1e-6), "kappa2 != 0"

    def test_sphere_positive_curvature(self, sphere_normal_map):
        """Sphere interior should have H > 0 and both kappas > 0 (convex)."""
        result = principal_curvatures(sphere_normal_map)
        # Sample center region away from boundary
        center = result[35:65, 35:65]
        H = center[:, :, 0]
        k1 = center[:, :, 1]
        k2 = center[:, :, 2]
        # Mean curvature should be positive in the convex region
        assert np.mean(H) > 0, "Sphere center should have positive mean curvature"
        # Both principal curvatures should be positive (convex)
        assert np.mean(k1) > 0, "kappa1 should be positive for sphere"
        assert np.mean(k2) > 0, "kappa2 should be positive for sphere"

    def test_kappa1_geq_kappa2(self, sphere_normal_map):
        """kappa1 should always be >= kappa2 (max >= min)."""
        result = principal_curvatures(sphere_normal_map)
        k1 = result[:, :, 1]
        k2 = result[:, :, 2]
        assert np.all(k1 >= k2 - 1e-7), "kappa1 must be >= kappa2"


# ---------------------------------------------------------------------------
# curvature_map backward compatibility tests
# ---------------------------------------------------------------------------


class TestCurvatureMapBackcompat:
    """Verify curvature_map still returns K = kappa1 * kappa2 after refactor."""

    def test_flat_zero(self, flat_normal_map):
        result = curvature_map(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.float32
        assert np.allclose(result, 0.0, atol=1e-6)

    def test_sphere_nonzero(self, sphere_normal_map):
        result = curvature_map(sphere_normal_map)
        center = result[30:70, 30:70]
        assert np.any(np.abs(center) > 1e-6)


# ---------------------------------------------------------------------------
# surface_type_map tests
# ---------------------------------------------------------------------------


class TestSurfaceTypeMap:
    """Verify per-pixel surface classification."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = surface_type_map(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.uint8

    def test_flat_surface_all_flat(self, flat_normal_map):
        """A flat plane should classify all pixels as 0 (flat)."""
        result = surface_type_map(flat_normal_map)
        assert np.all(result == 0)

    def test_sphere_has_convex(self, sphere_normal_map):
        """Sphere interior should have convex (1) pixels, not all flat."""
        result = surface_type_map(sphere_normal_map)
        assert np.any(result == 1), "Sphere should have convex pixels"

    def test_cube_mostly_flat(self, cube_normal_map):
        """Interior of cube faces should be flat (0)."""
        result = surface_type_map(cube_normal_map)
        # Interior of each face well away from boundaries
        top_interior = result[5:35, 10:110]
        mid_interior = result[45:75, 10:110]
        bot_interior = result[85:115, 10:110]
        assert np.all(top_interior == 0)
        assert np.all(mid_interior == 0)
        assert np.all(bot_interior == 0)

    def test_values_in_range(self, sphere_normal_map):
        """All pixel values should be in {0, 1, 2, 3, 4}."""
        result = surface_type_map(sphere_normal_map)
        unique = np.unique(result)
        assert all(v in {0, 1, 2, 3, 4} for v in unique)


# ---------------------------------------------------------------------------
# ridge_valley_map tests
# ---------------------------------------------------------------------------


class TestRidgeValleyMap:
    """Verify ridge and valley detection from mean curvature."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = ridge_valley_map(flat_normal_map)
        assert result.shape == (100, 100, 2)
        assert result.dtype == np.uint8

    def test_flat_no_ridges_or_valleys(self, flat_normal_map):
        """A flat plane should have zero in both channels."""
        result = ridge_valley_map(flat_normal_map)
        assert np.all(result[:, :, 0] == 0), "Flat should have no ridges"
        assert np.all(result[:, :, 1] == 0), "Flat should have no valleys"

    def test_sphere_has_ridges(self, sphere_normal_map):
        """A convex sphere should produce nonzero ridge channel pixels."""
        result = ridge_valley_map(sphere_normal_map)
        assert np.any(result[:, :, 0] > 0), "Sphere should have ridge pixels"


# ---------------------------------------------------------------------------
# silhouette_contours tests
# ---------------------------------------------------------------------------


class TestSilhouetteContours:
    """Verify silhouette detection from nz magnitude."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = silhouette_contours(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.uint8

    def test_flat_no_silhouettes(self, flat_normal_map):
        """All nz = 1.0 -> no silhouettes."""
        result = silhouette_contours(flat_normal_map)
        assert np.all(result == 0)

    def test_sphere_silhouettes_at_rim(self, sphere_normal_map):
        """Sphere edges have nz -> 0, should produce silhouette pixels."""
        result = silhouette_contours(sphere_normal_map)
        assert np.any(result == 255), "Sphere rim should have silhouettes"

    def test_step_all_silhouette(self, step_normal_map):
        """Step map has nz = 0 everywhere -> all pixels are silhouettes."""
        result = silhouette_contours(step_normal_map)
        assert np.all(result == 255)

    def test_output_is_binary(self, sphere_normal_map):
        result = silhouette_contours(sphere_normal_map)
        unique = np.unique(result)
        assert all(v in (0, 255) for v in unique)


# ---------------------------------------------------------------------------
# depth_facing_map tests
# ---------------------------------------------------------------------------


class TestDepthFacingMap:
    """Verify front-facing intensity map."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = depth_facing_map(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.float32

    def test_flat_all_one(self, flat_normal_map):
        """All nz = 1.0 -> all facing values = 1.0."""
        result = depth_facing_map(flat_normal_map)
        assert np.allclose(result, 1.0)

    def test_step_all_zero(self, step_normal_map):
        """Step map has nz = 0 everywhere -> all facing values = 0.0."""
        result = depth_facing_map(step_normal_map)
        assert np.allclose(result, 0.0)

    def test_values_in_range(self, sphere_normal_map):
        result = depth_facing_map(sphere_normal_map)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)


# ---------------------------------------------------------------------------
# surface_flow_field tests
# ---------------------------------------------------------------------------


class TestSurfaceFlowField:
    """Verify principal direction eigenvectors."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = surface_flow_field(flat_normal_map)
        assert result.shape == (100, 100, 4)
        assert result.dtype == np.float32

    def test_flat_zero_directions(self, flat_normal_map):
        """Flat surface has no curvature -> all directions = 0."""
        result = surface_flow_field(flat_normal_map)
        assert np.allclose(result, 0.0, atol=1e-6)

    def test_sphere_nonzero_directions(self, sphere_normal_map):
        """Sphere has curvature -> directions should be nonzero in curved regions."""
        result = surface_flow_field(sphere_normal_map)
        center = result[35:65, 35:65]
        assert np.any(np.abs(center) > 1e-6), "Sphere should have nonzero flow"


# ---------------------------------------------------------------------------
# ambient_occlusion_approx tests
# ---------------------------------------------------------------------------


class TestAmbientOcclusionApprox:
    """Verify normal-variance ambient occlusion approximation."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = ambient_occlusion_approx(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.float32

    def test_flat_near_zero(self, flat_normal_map):
        """Constant normals -> zero variance -> zero AO."""
        result = ambient_occlusion_approx(flat_normal_map)
        assert np.allclose(result, 0.0, atol=1e-6)

    def test_step_high_near_discontinuity(self, step_normal_map):
        """Sharp normal change should produce high AO near the boundary."""
        result = ambient_occlusion_approx(step_normal_map)
        # The center column region should have higher values
        center_col = result[:, 45:55]
        edge_col = result[:, 0:10]
        assert np.mean(center_col) > np.mean(edge_col)

    def test_values_non_negative(self, sphere_normal_map):
        result = ambient_occlusion_approx(sphere_normal_map)
        assert np.all(result >= 0.0)


# ---------------------------------------------------------------------------
# form_vs_material_boundaries tests
# ---------------------------------------------------------------------------


class TestFormVsMaterialBoundaries:
    """Verify form/material boundary classification."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = form_vs_material_boundaries(flat_normal_map)
        assert result.shape == (100, 100, 2)
        assert result.dtype == np.uint8

    def test_flat_no_boundaries(self, flat_normal_map):
        """Constant normals -> no discontinuities -> no boundaries."""
        result = form_vs_material_boundaries(flat_normal_map)
        assert np.all(result[:, :, 0] == 0)
        assert np.all(result[:, :, 1] == 0)

    def test_step_has_boundaries(self, step_normal_map):
        """A sharp normal step should produce boundary pixels."""
        result = form_vs_material_boundaries(step_normal_map)
        total_boundaries = np.sum(result[:, :, 0]) + np.sum(result[:, :, 1])
        assert total_boundaries > 0, "Step should have boundary pixels"

    def test_output_is_binary(self, step_normal_map):
        result = form_vs_material_boundaries(step_normal_map)
        for ch in range(2):
            unique = np.unique(result[:, :, ch])
            assert all(v in (0, 255) for v in unique)


# ---------------------------------------------------------------------------
# cross_contour_field tests
# ---------------------------------------------------------------------------


class TestCrossContourField:
    """Verify streamline tracing along cross-contour directions."""

    def test_flat_empty(self, flat_normal_map):
        """Flat surface has no curvature -> no cross contours."""
        result = cross_contour_field(flat_normal_map)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_sphere_non_empty(self, sphere_normal_map):
        """Sphere has curvature -> should produce polylines."""
        result = cross_contour_field(sphere_normal_map, spacing=15)
        assert isinstance(result, list)
        assert len(result) > 0, "Sphere should produce cross-contour lines"

    def test_polyline_structure(self, sphere_normal_map):
        """Each polyline should be a list of [x, y] pairs."""
        result = cross_contour_field(sphere_normal_map, spacing=20)
        if len(result) > 0:
            line = result[0]
            assert isinstance(line, list)
            assert len(line) >= 2
            point = line[0]
            assert isinstance(point, list)
            assert len(point) == 2
            assert isinstance(point[0], float)
            assert isinstance(point[1], float)


# ---------------------------------------------------------------------------
# curvature_line_weight tests
# ---------------------------------------------------------------------------


class TestCurvatureLineWeight:
    """Verify adaptive stroke weight from curvature + silhouette."""

    def test_output_shape_and_dtype(self, flat_normal_map):
        result = curvature_line_weight(flat_normal_map)
        assert result.shape == (100, 100)
        assert result.dtype == np.float32

    def test_flat_medium_weight(self, flat_normal_map):
        """Flat surface (H ~ 0, nz = 1) should get weight ~ 0.5."""
        result = curvature_line_weight(flat_normal_map)
        assert np.allclose(result, 0.5, atol=0.05)

    def test_step_silhouette_weight(self, step_normal_map):
        """Step map has nz = 0 everywhere -> silhouette -> weight ~ 1.0."""
        result = curvature_line_weight(step_normal_map)
        assert np.allclose(result, 1.0, atol=0.05)

    def test_values_in_range(self, sphere_normal_map):
        result = curvature_line_weight(sphere_normal_map)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)
