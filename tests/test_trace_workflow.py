"""Tests for the GIR tracing workflow tool.

Verifies OpenCV-based contour detection, coordinate transforms, area filtering,
and shape sorting — all pure Python, no Adobe required.
"""

import json
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.trace_workflow import (
    _read_image_dimensions,
    _detect_black_contours,
    _detect_colored_regions,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic images for deterministic testing
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def black_shapes_png(tmp_path_factory):
    """200x150 image with two black shapes on white background.

    - Large rectangle (80x60 = 4800 px area) at top-left
    - Small square (20x20 = 400 px area) at bottom-right
    """
    path = str(tmp_path_factory.mktemp("trace") / "black_shapes.png")
    img = np.ones((150, 200, 3), dtype=np.uint8) * 255  # white background
    # Large black rectangle
    cv2.rectangle(img, (10, 10), (90, 70), (0, 0, 0), -1)
    # Small black square
    cv2.rectangle(img, (150, 110), (170, 130), (0, 0, 0), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def tiny_dots_png(tmp_path_factory):
    """100x100 image with several very small black dots (area < 50 each)."""
    path = str(tmp_path_factory.mktemp("trace") / "tiny_dots.png")
    img = np.ones((100, 100, 3), dtype=np.uint8) * 255
    # Draw 5 tiny circles (radius 3 → area ~28 pixels)
    for cx in [20, 40, 60, 80, 50]:
        cv2.circle(img, (cx, 50), 3, (0, 0, 0), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def single_rect_png(tmp_path_factory):
    """300x200 image with a single large black rectangle (area ~24000)."""
    path = str(tmp_path_factory.mktemp("trace") / "single_rect.png")
    img = np.ones((200, 300, 3), dtype=np.uint8) * 255
    cv2.rectangle(img, (50, 30), (250, 170), (0, 0, 0), -1)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# test_setup_dimensions: verify doc matches image size
# ---------------------------------------------------------------------------


def test_setup_dimensions(single_rect_png):
    """_read_image_dimensions returns correct width and height for the image."""
    dims = _read_image_dimensions(single_rect_png)
    assert "error" not in dims
    assert dims["width"] == 300
    assert dims["height"] == 200
    assert dims["channels"] == 3


def test_setup_dimensions_missing_file():
    """Missing image returns an error dict, not an exception."""
    dims = _read_image_dimensions("/nonexistent/path/missing.png")
    assert "error" in dims


# ---------------------------------------------------------------------------
# test_threshold_contour_count: synthetic image → correct shape count
# ---------------------------------------------------------------------------


def test_threshold_contour_count(black_shapes_png):
    """Two black shapes on white background produces exactly 2 contours at default threshold."""
    result = _detect_black_contours(black_shapes_png, threshold=30, min_area=200)
    assert "error" not in result
    # Should find the large rectangle and the small square
    assert result["shape_count"] == 2
    assert len(result["shapes"]) == 2
    # Verify each shape has required fields
    for shape in result["shapes"]:
        assert "name" in shape
        assert "area" in shape
        assert "point_count" in shape
        assert "points" in shape
        assert shape["area"] >= 200


# ---------------------------------------------------------------------------
# test_min_area_filter: small shapes filtered out
# ---------------------------------------------------------------------------


def test_min_area_filter(tiny_dots_png):
    """Tiny dots (area ~28 each) are filtered out when min_area=200."""
    result = _detect_black_contours(tiny_dots_png, threshold=30, min_area=200)
    assert "error" not in result
    # All dots are tiny (radius 3 → area ~28), all should be filtered
    assert result["shape_count"] == 0
    assert len(result["shapes"]) == 0


def test_min_area_filter_permissive(tiny_dots_png):
    """With a very low min_area, tiny dots are included."""
    result = _detect_black_contours(tiny_dots_png, threshold=30, min_area=10)
    assert "error" not in result
    # Should find at least some dots
    assert result["shape_count"] >= 1


# ---------------------------------------------------------------------------
# test_sort_by_area: shapes sorted largest first
# ---------------------------------------------------------------------------


def test_sort_by_area(black_shapes_png):
    """Shapes are returned sorted by area, largest first."""
    result = _detect_black_contours(black_shapes_png, threshold=30, min_area=200)
    assert "error" not in result
    assert result["shape_count"] >= 2

    areas = [s["area"] for s in result["shapes"]]
    # Verify descending order
    for i in range(len(areas) - 1):
        assert areas[i] >= areas[i + 1], (
            f"Shape {i} (area={areas[i]}) should be >= shape {i+1} (area={areas[i+1]})"
        )

    # The large rectangle (~4800) should be first, small square (~400) second
    assert areas[0] > areas[1]


# ---------------------------------------------------------------------------
# test_pixel_to_ai_coords: verify (x, -y) transform
# ---------------------------------------------------------------------------


def test_pixel_to_ai_coords(black_shapes_png):
    """Contour points are converted to AI coordinate space: (x, -y)."""
    result = _detect_black_contours(black_shapes_png, threshold=30, min_area=200)
    assert "error" not in result
    assert result["shape_count"] >= 1

    # Check that all Y coordinates are negative (or zero) since AI flips Y
    for shape in result["shapes"]:
        for point in shape["points"]:
            assert len(point) == 2, f"Point should be [x, y], got {point}"
            # X should be non-negative (pixel coords are non-negative)
            assert point[0] >= 0, f"X coordinate should be >= 0, got {point[0]}"
            # Y should be non-positive (AI flips: -y)
            assert point[1] <= 0, f"Y coordinate should be <= 0 in AI space, got {point[1]}"
