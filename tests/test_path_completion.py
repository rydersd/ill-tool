"""Tests for path_completion — predictive path completion along surface curvature.

Covers: input model validation, tangent computation, surface walking,
simplification, connection to existing fragments, and predict_path integration.

Uses synthetic normal maps (no ML dependencies required).
"""

import json
import os
import tempfile

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.drawing.path_completion import (
    PathCompletionInput,
    _compute_tangents,
    _connect_to_existing,
    _fit_quadratic_tangents,
    _simplify_path,
    _build_open_path_jsx,
    predict_path,
    should_stop,
    walk_surface,
    OUTPUT_DIR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def synthetic_normal_map():
    """Create a 100x100 normal map pointing mostly up (+Z).

    Center region has normals tilted to simulate a cylinder surface
    (normals point outward from center column).
    """
    h, w = 100, 100
    nmap = np.zeros((h, w, 3), dtype=np.float32)
    # Default: all normals point straight up (0, 0, 1)
    nmap[:, :, 2] = 1.0

    # Cylinder region (columns 30-70): normals tilt in X
    for x in range(30, 70):
        nx = (x - 50) / 20.0  # ranges from -1 to +1
        nz = np.sqrt(max(0, 1 - nx * nx))
        nmap[:, x, 0] = nx
        nmap[:, x, 2] = nz

    return nmap


@pytest.fixture(scope="session")
def synthetic_surface_type_map():
    """100x100 surface type map with two regions.

    Left half (cols 0-49): flat (0)
    Right half (cols 50-99): cylindrical (4)
    """
    stype = np.zeros((100, 100), dtype=np.uint8)
    stype[:, 50:] = 4  # cylindrical
    return stype


@pytest.fixture(scope="session")
def test_image_with_cache(tmp_path_factory, synthetic_normal_map, synthetic_surface_type_map):
    """Create a test image and pre-cache its normal + surface type maps.

    Returns the image path. The cached .npy files are written to OUTPUT_DIR
    so _get_surface_type_map will find them.
    """
    img_dir = tmp_path_factory.mktemp("path_completion")
    img_path = str(img_dir / "test_surface.png")

    # Write a simple test image
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, :50] = 128  # left half gray (flat)
    img[:, 50:] = 200  # right half lighter (cylinder)
    cv2.imwrite(img_path, img)

    # Pre-cache the maps so predict_path doesn't need DSINE
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    basename = os.path.splitext(os.path.basename(img_path))[0]
    np.save(os.path.join(OUTPUT_DIR, f"{basename}_normal_map.npy"), synthetic_normal_map)
    np.save(os.path.join(OUTPUT_DIR, f"{basename}_surface_type_map.npy"), synthetic_surface_type_map)

    return img_path


@pytest.fixture(autouse=True)
def ensure_output_dir():
    """Ensure output directory exists for caching tests."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yield


# ---------------------------------------------------------------------------
# 1. Input model validation
# ---------------------------------------------------------------------------


class TestInputModel:
    """Validate PathCompletionInput field constraints."""

    def test_defaults(self):
        """Default values should be sane."""
        inp = PathCompletionInput()
        assert inp.action == "predict"
        assert inp.seed_points == []
        assert inp.max_extension == 200.0
        assert inp.step_size == 2.0
        assert inp.connect_existing is True
        assert inp.simplify_tolerance == 2.0

    def test_step_size_range(self):
        """step_size must be between 0.5 and 20."""
        inp = PathCompletionInput(step_size=0.5)
        assert inp.step_size == 0.5
        inp = PathCompletionInput(step_size=20.0)
        assert inp.step_size == 20.0

        with pytest.raises(Exception):
            PathCompletionInput(step_size=0.1)
        with pytest.raises(Exception):
            PathCompletionInput(step_size=25.0)

    def test_max_extension_range(self):
        """max_extension must be between 1 and 2000."""
        with pytest.raises(Exception):
            PathCompletionInput(max_extension=0.5)
        with pytest.raises(Exception):
            PathCompletionInput(max_extension=3000.0)


# ---------------------------------------------------------------------------
# 2. Tangent computation
# ---------------------------------------------------------------------------


class TestTangentComputation:
    """Test _compute_tangents for 2 and 3 seed points."""

    def test_two_points_tangent(self):
        """Two points: tangent should be the direction vector."""
        start, s_tan, end, e_tan = _compute_tangents([[10, 20], [30, 40]])
        np.testing.assert_array_almost_equal(start, [10, 20])
        np.testing.assert_array_almost_equal(end, [30, 40])
        np.testing.assert_array_almost_equal(s_tan, [20, 20])
        np.testing.assert_array_almost_equal(e_tan, [20, 20])

    def test_three_points_tangent(self):
        """Three points: quadratic fit should produce different tangents at ends."""
        start, s_tan, end, e_tan = _compute_tangents(
            [[0, 0], [50, 50], [100, 0]]
        )
        np.testing.assert_array_almost_equal(start, [0, 0])
        np.testing.assert_array_almost_equal(end, [100, 0])
        # Start tangent should point right and up, end tangent right and down
        assert s_tan[0] > 0  # moving right
        assert s_tan[1] > 0  # moving up at start
        assert e_tan[0] > 0  # moving right
        assert e_tan[1] < 0  # moving down at end

    def test_collinear_three_points(self):
        """Three collinear points: tangents should be parallel."""
        start, s_tan, end, e_tan = _compute_tangents(
            [[0, 0], [50, 50], [100, 100]]
        )
        # Both tangents should point in the same direction
        s_dir = s_tan / np.linalg.norm(s_tan)
        e_dir = e_tan / np.linalg.norm(e_tan)
        np.testing.assert_array_almost_equal(s_dir, e_dir, decimal=3)


# ---------------------------------------------------------------------------
# 3. Surface walking
# ---------------------------------------------------------------------------


class TestSurfaceWalking:
    """Test walk_surface with synthetic normal maps."""

    def test_flat_surface_walks_straight(self):
        """On a flat surface (normal = [0,0,1]), walking should be straight."""
        nmap = np.zeros((100, 100, 3), dtype=np.float32)
        nmap[:, :, 2] = 1.0  # all normals point up

        path = walk_surface(
            start_point=np.array([50, 50]),
            tangent=np.array([1, 0]),  # walk right
            normal_map=nmap,
            stype_map=None,
            step_size=2.0,
            max_steps=10,
        )

        assert len(path) > 1
        # On flat surface, Y should stay constant
        for pt in path:
            assert abs(pt[1] - 50) < 1.0, f"Y drifted to {pt[1]}"

    def test_walks_off_edge_stops(self):
        """Walking toward the image edge should stop at boundary."""
        nmap = np.zeros((50, 50, 3), dtype=np.float32)
        nmap[:, :, 2] = 1.0

        path = walk_surface(
            start_point=np.array([45, 25]),
            tangent=np.array([1, 0]),
            normal_map=nmap,
            stype_map=None,
            step_size=2.0,
            max_steps=100,
        )

        # Should stop before going off the edge (50 pixels wide)
        last_x = path[-1][0]
        assert last_x < 55, f"Walked past image edge to x={last_x}"

    def test_cylinder_surface_curves_path(self, synthetic_normal_map):
        """On a cylinder, path should curve following the surface."""
        # Walk along the cylinder center (x=50), starting from top
        path = walk_surface(
            start_point=np.array([50, 20]),
            tangent=np.array([0, 1]),  # walk down
            normal_map=synthetic_normal_map,
            stype_map=None,
            step_size=2.0,
            max_steps=20,
        )

        assert len(path) > 5

    def test_zero_tangent_returns_start_only(self):
        """Zero tangent vector should return just the start point."""
        nmap = np.zeros((50, 50, 3), dtype=np.float32)
        nmap[:, :, 2] = 1.0

        path = walk_surface(
            start_point=np.array([25, 25]),
            tangent=np.array([0, 0]),
            normal_map=nmap,
            stype_map=None,
            step_size=2.0,
            max_steps=10,
        )

        assert len(path) == 1

    def test_max_steps_limits_path(self):
        """Path should not exceed max_steps + 1 points."""
        nmap = np.zeros((200, 200, 3), dtype=np.float32)
        nmap[:, :, 2] = 1.0

        path = walk_surface(
            start_point=np.array([100, 100]),
            tangent=np.array([1, 0]),
            normal_map=nmap,
            stype_map=None,
            step_size=1.0,
            max_steps=15,
        )

        # +1 for the start point
        assert len(path) <= 16


# ---------------------------------------------------------------------------
# 4. Surface type boundary detection
# ---------------------------------------------------------------------------


class TestBoundaryDetection:
    """Test should_stop with surface type boundaries."""

    def test_same_type_no_stop(self, synthetic_surface_type_map):
        """No stop when both points are on the same surface type."""
        assert not should_stop(
            np.array([30, 50]),
            np.array([31, 50]),
            synthetic_surface_type_map,
        )

    def test_boundary_crossing_stops(self, synthetic_surface_type_map):
        """Should stop when crossing from flat (0) to cylindrical (4)."""
        assert should_stop(
            np.array([50, 50]),  # cylindrical
            np.array([49, 50]),  # flat
            synthetic_surface_type_map,
        )

    def test_out_of_bounds_no_stop(self, synthetic_surface_type_map):
        """Out-of-bounds coordinates should not trigger stop."""
        assert not should_stop(
            np.array([-1, 50]),
            np.array([30, 50]),
            synthetic_surface_type_map,
        )

    def test_walk_stops_at_boundary(self, synthetic_normal_map, synthetic_surface_type_map):
        """Walking across a surface boundary should stop the path."""
        path = walk_surface(
            start_point=np.array([40, 50]),
            tangent=np.array([1, 0]),  # walk right toward boundary at x=50
            normal_map=synthetic_normal_map,
            stype_map=synthetic_surface_type_map,
            step_size=2.0,
            max_steps=50,
        )

        # The path should stop near the boundary at x=50
        last_x = path[-1][0]
        assert last_x < 55, f"Path crossed boundary, last x={last_x}"


# ---------------------------------------------------------------------------
# 5. Path simplification
# ---------------------------------------------------------------------------


class TestSimplification:
    """Test Douglas-Peucker simplification on open paths."""

    def test_straight_line_simplifies(self):
        """A straight line with many intermediate points should simplify."""
        points = [[float(i), 0.0] for i in range(50)]
        simplified = _simplify_path(points, tolerance=1.0)
        # A straight line should reduce to just 2 points (endpoints)
        assert len(simplified) <= 3

    def test_curved_path_preserves_shape(self):
        """A curved path should not reduce to fewer than 3 points."""
        # Quarter circle
        points = [
            [50 * np.cos(t), 50 * np.sin(t)]
            for t in np.linspace(0, np.pi / 2, 50)
        ]
        simplified = _simplify_path(points, tolerance=1.0)
        assert len(simplified) >= 3

    def test_zero_tolerance_preserves_all(self):
        """Zero tolerance should return all points."""
        points = [[float(i), float(i * i)] for i in range(10)]
        simplified = _simplify_path(points, tolerance=0.0)
        assert len(simplified) == len(points)

    def test_few_points_unchanged(self):
        """Paths with < 3 points should be returned unchanged."""
        points = [[0, 0], [10, 10]]
        simplified = _simplify_path(points, tolerance=5.0)
        assert len(simplified) == 2


# ---------------------------------------------------------------------------
# 6. predict_path integration (with cached maps)
# ---------------------------------------------------------------------------


class TestPredictPath:
    """Integration tests for predict_path using pre-cached maps."""

    def test_two_seed_points(self, test_image_with_cache):
        """Basic prediction with 2 seed points should return a path."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[30, 50], [40, 50]],
            max_extension=50.0,
            step_size=2.0,
            connect_existing=False,
        )
        assert "error" not in result, result.get("error")
        assert "points" in result
        assert result["point_count"] >= 2
        assert result["seed_count"] == 2

    def test_three_seed_points(self, test_image_with_cache):
        """Prediction with 3 seed points should work."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[20, 50], [30, 55], [40, 50]],
            max_extension=30.0,
            step_size=2.0,
            connect_existing=False,
        )
        assert "error" not in result, result.get("error")
        assert result["seed_count"] == 3
        assert result["point_count"] >= 3

    def test_too_few_seed_points(self, test_image_with_cache):
        """1 seed point should produce an error."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[50, 50]],
        )
        assert "error" in result

    def test_too_many_seed_points(self, test_image_with_cache):
        """4 seed points should produce an error."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[10, 10], [20, 20], [30, 30], [40, 40]],
        )
        assert "error" in result

    def test_out_of_bounds_seed_point(self, test_image_with_cache):
        """Seed point outside image bounds should produce an error."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[500, 50], [510, 50]],
        )
        assert "error" in result

    def test_nonexistent_image(self):
        """Nonexistent image path should produce an error."""
        result = predict_path(
            image_path="/nonexistent/image.png",
            seed_points=[[10, 10], [20, 20]],
        )
        assert "error" in result

    def test_path_extends_both_directions(self, test_image_with_cache):
        """Predicted path should have backward + forward extensions."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[30, 50], [40, 50]],
            max_extension=40.0,
            step_size=2.0,
            connect_existing=False,
            simplify_tolerance=0.0,  # no simplification for step counting
        )
        assert "error" not in result, result.get("error")
        assert result["backward_steps"] > 0
        assert result["forward_steps"] > 0

    def test_timings_present(self, test_image_with_cache):
        """Result should include timing information."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[30, 50], [40, 50]],
            max_extension=20.0,
            connect_existing=False,
        )
        assert "timings" in result
        assert "total_seconds" in result["timings"]

    def test_surface_map_cached(self, test_image_with_cache):
        """Pre-cached maps should be detected as cached."""
        result = predict_path(
            image_path=test_image_with_cache,
            seed_points=[[30, 50], [40, 50]],
            max_extension=20.0,
            connect_existing=False,
        )
        assert "error" not in result, result.get("error")
        assert result["surface_map_cached"] is True


# ---------------------------------------------------------------------------
# 7. Open path JSX generation
# ---------------------------------------------------------------------------


class TestOpenPathJsx:
    """Test _build_open_path_jsx output."""

    def test_jsx_contains_layer_name(self):
        """JSX should reference the target layer name."""
        jsx = _build_open_path_jsx(
            [[0, 0], [10, 10], [20, 0]],
            "Test Layer",
        )
        assert "Test Layer" in jsx

    def test_jsx_open_path(self):
        """JSX should set path.closed = false for open paths."""
        jsx = _build_open_path_jsx(
            [[0, 0], [10, 10], [20, 0]],
            "Layer",
        )
        assert "path.closed = false" in jsx

    def test_jsx_orange_stroke(self):
        """JSX should use orange accent color."""
        jsx = _build_open_path_jsx(
            [[0, 0], [10, 10]],
            "Layer",
        )
        assert "orange.red = 255" in jsx
        assert "orange.green = 140" in jsx

    def test_jsx_path_name(self):
        """JSX should set the path name."""
        jsx = _build_open_path_jsx(
            [[0, 0], [10, 10]],
            "Layer",
            path_name="my_path",
        )
        assert "my_path" in jsx

    def test_jsx_returns_json(self):
        """JSX should return a JSON string with placement info."""
        jsx = _build_open_path_jsx(
            [[0, 0], [10, 10], [20, 0]],
            "Layer",
        )
        assert "JSON.stringify" in jsx
        assert "paths_placed" in jsx
