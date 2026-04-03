"""Tests for form_edge_pipeline — pure Python form edge extraction.

Covers: heuristic_form_edges on synthetic images, dsine_form_edges
backend selection, edge_mask_to_contours on binary masks,
contours_to_ai_points coordinate transform, subtract_shadow_mask,
max_contours limiting, and min_length filtering.
"""

import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.form_edge_pipeline import (
    contours_to_ai_points,
    edge_mask_to_contours,
    extract_form_edges,
    heuristic_form_edges,
    subtract_shadow_mask,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rect_on_black():
    """100x100 image: white rectangle on black — clear form edges."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (80, 80), (255, 255, 255), -1)
    return img


@pytest.fixture(scope="session")
def circle_on_black():
    """100x100 image: white circle on black — curved form edges."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 30, (255, 255, 255), -1)
    return img


@pytest.fixture(scope="session")
def all_black():
    """100x100 all-black image — no edges expected."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture(scope="session")
def all_white():
    """100x100 all-white image — no edges expected."""
    return np.full((100, 100, 3), 255, dtype=np.uint8)


@pytest.fixture(scope="session")
def rect_edge_mask():
    """Binary edge mask with a rectangular contour for contour tests."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    cv2.rectangle(mask, (20, 20), (80, 80), 255, 2)  # 2px thick outline
    return mask


@pytest.fixture(scope="session")
def multi_contour_mask():
    """Binary mask with multiple contours of varying sizes."""
    mask = np.zeros((200, 200), dtype=np.uint8)
    # Large rectangle
    cv2.rectangle(mask, (10, 10), (90, 90), 255, 2)
    # Medium circle
    cv2.circle(mask, (150, 50), 25, 255, 2)
    # Small rectangle
    cv2.rectangle(mask, (120, 120), (140, 140), 255, 2)
    # Tiny dot (should be filtered by min_length)
    cv2.circle(mask, (180, 180), 3, 255, 1)
    return mask


@pytest.fixture
def rect_image_path(tmp_path, rect_on_black):
    """Save rect_on_black as a PNG and return the path."""
    path = str(tmp_path / "rect.png")
    cv2.imwrite(path, rect_on_black)
    return path


@pytest.fixture
def circle_image_path(tmp_path, circle_on_black):
    """Save circle_on_black as a PNG and return the path."""
    path = str(tmp_path / "circle.png")
    cv2.imwrite(path, circle_on_black)
    return path


# ---------------------------------------------------------------------------
# 1. Heuristic form edges — basic behavior
# ---------------------------------------------------------------------------


class TestHeuristicFormEdges:
    """Verify heuristic multi-exposure voting edge extraction."""

    def test_detects_edges_on_white_rect(self, rect_on_black):
        """White rectangle on black should produce non-zero edge mask."""
        result = heuristic_form_edges(rect_on_black)
        assert result["backend"] == "heuristic"
        assert result["form_edges"].shape == (100, 100)
        assert result["form_edges"].dtype == np.uint8
        assert result["metadata"]["edge_pixel_count"] > 0

    def test_detects_edges_on_circle(self, circle_on_black):
        """White circle on black should produce non-zero edge mask."""
        result = heuristic_form_edges(circle_on_black)
        assert result["metadata"]["edge_pixel_count"] > 0

    def test_all_black_produces_no_edges(self, all_black):
        """All-black image should produce zero edge pixels."""
        result = heuristic_form_edges(all_black)
        assert result["metadata"]["edge_pixel_count"] == 0

    def test_all_white_produces_no_edges(self, all_white):
        """All-white image should produce zero edge pixels."""
        result = heuristic_form_edges(all_white)
        assert result["metadata"]["edge_pixel_count"] == 0

    def test_grayscale_input_accepted(self, rect_on_black):
        """Grayscale (2D) input should be accepted."""
        gray = cv2.cvtColor(rect_on_black, cv2.COLOR_BGR2GRAY)
        result = heuristic_form_edges(gray)
        assert result["backend"] == "heuristic"
        assert result["metadata"]["edge_pixel_count"] > 0

    def test_metadata_contains_timing(self, rect_on_black):
        """Result metadata should include time_seconds."""
        result = heuristic_form_edges(rect_on_black)
        assert "time_seconds" in result["metadata"]
        assert result["metadata"]["time_seconds"] >= 0

    def test_metadata_records_parameters(self, rect_on_black):
        """Metadata should record num_exposures and vote_threshold."""
        result = heuristic_form_edges(rect_on_black, num_exposures=7, vote_threshold=4)
        assert result["metadata"]["num_exposures"] == 7
        assert result["metadata"]["vote_threshold"] == 4

    def test_more_exposures_produces_edges(self, rect_on_black):
        """Higher num_exposures should still detect edges."""
        result = heuristic_form_edges(rect_on_black, num_exposures=10, vote_threshold=5)
        assert result["metadata"]["edge_pixel_count"] > 0

    def test_vote_threshold_clamps_to_range(self, rect_on_black):
        """Vote threshold should be clamped to [1, num_exposures]."""
        result = heuristic_form_edges(rect_on_black, num_exposures=5, vote_threshold=100)
        assert result["metadata"]["vote_threshold"] == 5

        result2 = heuristic_form_edges(rect_on_black, num_exposures=5, vote_threshold=0)
        assert result2["metadata"]["vote_threshold"] == 1

    def test_edge_mask_is_binary(self, rect_on_black):
        """Edge mask should only contain 0 and 255 values."""
        result = heuristic_form_edges(rect_on_black)
        unique = set(np.unique(result["form_edges"]))
        assert unique.issubset({0, 255})


# ---------------------------------------------------------------------------
# 2. DSINE form edges (with mock)
# ---------------------------------------------------------------------------


class TestDsineFormEdges:
    """Verify DSINE-based form edge extraction."""

    def test_dsine_returns_form_edges_from_normal_map(self, rect_image_path, monkeypatch):
        """DSINE backend should return form edges when ML is available."""
        import adobe_mcp.apps.illustrator.form_edge_pipeline as fep

        # Create a synthetic normal map with a sharp boundary
        normals = np.zeros((100, 100, 3), dtype=np.float32)
        normals[:, :, 2] = 1.0  # All facing camera
        # Add a discontinuity to create a form edge
        normals[40:60, 40:60, 0] = 0.7
        normals[40:60, 40:60, 2] = 0.7

        def fake_estimate(image_path, model="auto"):
            return {
                "normal_map": normals,
                "device": "cpu",
                "model": "dsine",
                "time_seconds": 0.001,
                "height": 100,
                "width": 100,
            }

        monkeypatch.setattr(fep, "estimate_normals", fake_estimate)
        monkeypatch.setattr(fep, "DSINE_AVAILABLE", True)

        result = fep.dsine_form_edges(rect_image_path, threshold=0.3)
        assert "error" not in result, f"DSINE failed: {result.get('error')}"
        assert result["backend"] == "dsine"
        assert result["form_edges"].shape == (100, 100)
        assert "normal_map" in result
        assert result["metadata"]["edge_pixel_count"] > 0

    def test_dsine_returns_error_without_ml(self, rect_image_path, monkeypatch):
        """DSINE should return error when ML deps are not installed."""
        import adobe_mcp.apps.illustrator.form_edge_pipeline as fep

        monkeypatch.setattr(fep, "DSINE_AVAILABLE", False)

        result = fep.dsine_form_edges(rect_image_path)
        assert "error" in result
        assert "install_hint" in result


# ---------------------------------------------------------------------------
# 3. Dispatcher (extract_form_edges)
# ---------------------------------------------------------------------------


class TestExtractFormEdges:
    """Verify the main dispatcher selects the correct backend."""

    def test_auto_selects_heuristic_when_no_ml(self, rect_image_path, monkeypatch):
        """Auto mode should fall back to heuristic when DSINE unavailable."""
        import adobe_mcp.apps.illustrator.form_edge_pipeline as fep

        monkeypatch.setattr(fep, "DSINE_AVAILABLE", False)
        result = extract_form_edges(rect_image_path, backend="auto")
        assert "error" not in result
        assert result["backend"] == "heuristic"

    def test_heuristic_backend_explicit(self, rect_image_path):
        """Explicit heuristic backend should use heuristic."""
        result = extract_form_edges(rect_image_path, backend="heuristic")
        assert result["backend"] == "heuristic"
        assert "error" not in result

    def test_unknown_backend_returns_error(self, rect_image_path):
        """Unknown backend name should return error."""
        result = extract_form_edges(rect_image_path, backend="nonexistent")
        assert "error" in result
        assert "valid_backends" in result

    def test_nonexistent_image_returns_error(self):
        """Nonexistent image path should return error."""
        result = extract_form_edges("/nonexistent/image.png", backend="heuristic")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_none_image_returns_error(self):
        """None image path should return error."""
        result = extract_form_edges(None, backend="heuristic")
        assert "error" in result


# ---------------------------------------------------------------------------
# 4. Edge mask to contours
# ---------------------------------------------------------------------------


class TestEdgeMaskToContours:
    """Verify contour extraction from binary masks."""

    def test_rect_mask_produces_contour(self, rect_edge_mask):
        """Rectangular edge mask should produce at least one contour."""
        contours = edge_mask_to_contours(rect_edge_mask)
        assert len(contours) > 0
        # Each contour should have required keys
        for c in contours:
            assert "name" in c
            assert "points" in c
            assert "point_count" in c
            assert "area" in c
            assert c["point_count"] >= 3

    def test_contours_sorted_by_area_descending(self, multi_contour_mask):
        """Contours should be sorted by area descending."""
        contours = edge_mask_to_contours(multi_contour_mask, min_length=10)
        areas = [c["area"] for c in contours]
        for i in range(len(areas) - 1):
            assert areas[i] >= areas[i + 1], (
                f"Contours not sorted by area: {areas}"
            )

    def test_contour_names_are_sequential(self, multi_contour_mask):
        """Contour names should be form_edge_0, form_edge_1, etc."""
        contours = edge_mask_to_contours(multi_contour_mask, min_length=10)
        for i, c in enumerate(contours):
            assert c["name"] == f"form_edge_{i}"

    def test_max_contours_limiting(self, multi_contour_mask):
        """max_contours parameter should limit output count."""
        contours = edge_mask_to_contours(
            multi_contour_mask, min_length=10, max_contours=2
        )
        assert len(contours) <= 2

    def test_min_length_filtering(self, multi_contour_mask):
        """Contours shorter than min_length should be excluded."""
        # Use a high min_length to filter out small contours
        contours_all = edge_mask_to_contours(multi_contour_mask, min_length=1)
        contours_filtered = edge_mask_to_contours(multi_contour_mask, min_length=200)
        assert len(contours_filtered) <= len(contours_all)

    def test_empty_mask_returns_empty(self):
        """Empty mask should return no contours."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        contours = edge_mask_to_contours(mask)
        assert contours == []

    def test_none_mask_returns_empty(self):
        """None mask should return no contours."""
        contours = edge_mask_to_contours(None)
        assert contours == []

    def test_points_are_coordinate_pairs(self, rect_edge_mask):
        """Each point in a contour should be a [x, y] list."""
        contours = edge_mask_to_contours(rect_edge_mask)
        assert len(contours) > 0
        for pt in contours[0]["points"]:
            assert len(pt) == 2
            assert isinstance(pt[0], (int, float))
            assert isinstance(pt[1], (int, float))

    def test_simplification_reduces_points(self, rect_edge_mask):
        """Higher simplify_tolerance should produce fewer points."""
        fine = edge_mask_to_contours(rect_edge_mask, simplify_tolerance=0.5)
        coarse = edge_mask_to_contours(rect_edge_mask, simplify_tolerance=10.0)
        if fine and coarse:
            assert coarse[0]["point_count"] <= fine[0]["point_count"]


# ---------------------------------------------------------------------------
# 5. Contours to AI points (coordinate transform)
# ---------------------------------------------------------------------------


class TestContoursToAiPoints:
    """Verify pixel-to-Illustrator coordinate transformation."""

    def test_y_flip_applied(self):
        """Points higher in pixel space (larger Y) should be lower in AI space."""
        contours = [{
            "name": "test",
            "points": [[50, 0], [50, 100]],
            "point_count": 2,
            "area": 100.0,
        }]
        result = contours_to_ai_points(contours, (100, 100), (800, 600))
        # Pixel (50, 0) = top of image -> should have higher AI Y
        # Pixel (50, 100) = bottom of image -> should have lower AI Y
        assert result[0]["points"][0][1] > result[0]["points"][1][1]

    def test_scaling_fits_artboard(self):
        """Transformed points should fit within artboard dimensions."""
        contours = [{
            "name": "test",
            "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
            "point_count": 4,
            "area": 10000.0,
        }]
        ab_w, ab_h = 800, 600
        result = contours_to_ai_points(contours, (100, 100), (ab_w, ab_h))
        for pt in result[0]["points"]:
            assert 0 <= pt[0] <= ab_w, f"X out of artboard: {pt[0]}"
            assert 0 <= pt[1] <= ab_h, f"Y out of artboard: {pt[1]}"

    def test_centering(self):
        """Small contour on large artboard should be roughly centered."""
        contours = [{
            "name": "test",
            "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "point_count": 4,
            "area": 100.0,
        }]
        ab_w, ab_h = 800, 600
        result = contours_to_ai_points(contours, (10, 10), (ab_w, ab_h))
        xs = [pt[0] for pt in result[0]["points"]]
        ys = [pt[1] for pt in result[0]["points"]]
        center_x = (min(xs) + max(xs)) / 2
        center_y = (min(ys) + max(ys)) / 2
        # Center should be near artboard center (within 10% margin)
        assert abs(center_x - ab_w / 2) < ab_w * 0.1
        assert abs(center_y - ab_h / 2) < ab_h * 0.1

    def test_preserves_point_count(self):
        """Transformation should not add or remove points."""
        contours = [{
            "name": "test",
            "points": [[10, 20], [30, 40], [50, 60], [70, 80], [90, 10]],
            "point_count": 5,
            "area": 500.0,
        }]
        result = contours_to_ai_points(contours, (100, 100), (800, 600))
        assert result[0]["point_count"] == 5
        assert len(result[0]["points"]) == 5

    def test_preserves_contour_metadata(self):
        """Transformation should preserve name and area."""
        contours = [{
            "name": "my_edge",
            "points": [[0, 0], [10, 0], [10, 10]],
            "point_count": 3,
            "area": 50.0,
        }]
        result = contours_to_ai_points(contours, (100, 100), (800, 600))
        assert result[0]["name"] == "my_edge"
        assert result[0]["area"] == 50.0

    def test_empty_contours_returns_empty(self):
        """Empty contour list should return empty list."""
        result = contours_to_ai_points([], (100, 100), (800, 600))
        assert result == []

    def test_points_are_rounded(self):
        """Transformed points should be rounded to 2 decimal places."""
        contours = [{
            "name": "test",
            "points": [[33, 77]],
            "point_count": 1,
            "area": 10.0,
        }]
        result = contours_to_ai_points(contours, (100, 100), (800, 600))
        for pt in result[0]["points"]:
            # Check that values have at most 2 decimal places
            assert pt[0] == round(pt[0], 2)
            assert pt[1] == round(pt[1], 2)


# ---------------------------------------------------------------------------
# 6. Shadow mask subtraction
# ---------------------------------------------------------------------------


class TestSubtractShadowMask:
    """Verify shadow mask subtraction."""

    def test_removes_shadow_edges(self):
        """Pixels present in both form_edges and shadow_mask should be removed."""
        form = np.zeros((100, 100), dtype=np.uint8)
        form[20:30, :] = 255  # Horizontal form edge
        form[60:70, :] = 255  # Shadow edge (will be masked out)

        shadow = np.zeros((100, 100), dtype=np.uint8)
        shadow[60:70, :] = 255  # Shadow region matches bottom edge

        result = subtract_shadow_mask(form, shadow)

        # Top edge should remain
        assert np.any(result[20:30, :] > 0)
        # Bottom edge should be removed
        assert not np.any(result[60:70, :] > 0)

    def test_preserves_non_shadow_edges(self):
        """Edges not in shadow mask should be preserved."""
        form = np.full((50, 50), 255, dtype=np.uint8)
        shadow = np.zeros((50, 50), dtype=np.uint8)

        result = subtract_shadow_mask(form, shadow)
        # All form edges should remain since no shadow
        assert np.all(result == 255)

    def test_empty_shadow_preserves_all(self):
        """Empty shadow mask should preserve all form edges."""
        form = np.zeros((50, 50), dtype=np.uint8)
        form[10:20, 10:20] = 255
        shadow = np.zeros((50, 50), dtype=np.uint8)

        result = subtract_shadow_mask(form, shadow)
        assert np.array_equal(result, form)

    def test_full_shadow_removes_all(self):
        """Full shadow mask should remove all form edges."""
        form = np.full((50, 50), 255, dtype=np.uint8)
        shadow = np.full((50, 50), 255, dtype=np.uint8)

        result = subtract_shadow_mask(form, shadow)
        assert np.all(result == 0)

    def test_output_is_binary(self):
        """Output should only contain 0 and 255."""
        form = np.zeros((50, 50), dtype=np.uint8)
        form[10:20, :] = 255
        shadow = np.zeros((50, 50), dtype=np.uint8)
        shadow[15:25, :] = 255

        result = subtract_shadow_mask(form, shadow)
        unique = set(np.unique(result))
        assert unique.issubset({0, 255})
