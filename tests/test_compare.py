"""Tests for the compare-drawing geometry helpers.

Covers contour resampling, centroid computation, contour extraction/matching,
correction vectors, and severity classification using synthetic fixtures.
"""

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.common.compare import (
    _resample_contour,
    _contour_centroid,
    _extract_contours,
    _match_contours,
    _compute_corrections,
    _severity,
)


# ---------------------------------------------------------------------------
# Helper: build OpenCV-format contour from a list of (x, y) tuples
# ---------------------------------------------------------------------------


def _make_contour(points: list[list[int]]) -> np.ndarray:
    """Return an OpenCV-shaped contour array (N, 1, 2) from flat point list."""
    return np.array(points, dtype=np.int32).reshape(-1, 1, 2)


# ---------------------------------------------------------------------------
# _resample_contour
# ---------------------------------------------------------------------------


def test_resample_contour_count():
    square = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    resampled = _resample_contour(square, 32)
    assert resampled.shape == (32, 2)


def test_resample_preserves_bounds():
    square = _make_contour([[10, 20], [90, 20], [90, 80], [10, 80]])
    resampled = _resample_contour(square, 64)
    assert resampled[:, 0].min() >= 10 - 1  # allow tiny floating-point drift
    assert resampled[:, 0].max() <= 90 + 1
    assert resampled[:, 1].min() >= 20 - 1
    assert resampled[:, 1].max() <= 80 + 1


# ---------------------------------------------------------------------------
# _contour_centroid
# ---------------------------------------------------------------------------


def test_centroid_square():
    square = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    cx, cy = _contour_centroid(square)
    assert abs(cx - 50) < 1
    assert abs(cy - 50) < 1


def test_centroid_triangle():
    triangle = _make_contour([[0, 0], [100, 0], [50, 100]])
    cx, cy = _contour_centroid(triangle)
    assert abs(cx - 50) < 1
    assert abs(cy - 33.3) < 1


# ---------------------------------------------------------------------------
# _extract_contours (uses real images via fixtures)
# ---------------------------------------------------------------------------


def test_extract_contours_from_rect(white_rect_png):
    img = cv2.imread(white_rect_png)
    contours = _extract_contours(img, min_area=0)
    assert len(contours) >= 1
    # At least one contour should have meaningful area
    areas = [cv2.contourArea(c) for c in contours]
    assert max(areas) > 0


def test_extract_contours_min_area(white_rect_png):
    img = cv2.imread(white_rect_png)
    # The rect is 60x40 = 2400 px area. Setting min_area above that → 0 contours.
    contours_low = _extract_contours(img, min_area=0)
    contours_high = _extract_contours(img, min_area=50000)
    assert len(contours_high) <= len(contours_low)
    assert len(contours_high) == 0


# ---------------------------------------------------------------------------
# _match_contours
# ---------------------------------------------------------------------------


def test_match_identical():
    square = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    matches = _match_contours([square], [square])
    assert len(matches) == 1
    assert matches[0] == (0, 0)


def test_match_offset():
    ref = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    # Offset by 10px — should still match (centroids close, areas identical)
    draw = _make_contour([[10, 10], [110, 10], [110, 110], [10, 110]])
    matches = _match_contours([ref], [draw])
    assert len(matches) == 1
    assert matches[0] == (0, 0)


def test_match_area_rejection():
    small = _make_contour([[0, 0], [10, 0], [10, 10], [0, 10]])
    # 10x larger in each dimension → 100x area — ratio check rejects (>3x)
    large = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    matches = _match_contours([small], [large])
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# _compute_corrections
# ---------------------------------------------------------------------------


def test_corrections_zero_for_identical():
    square = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    corrections, hausdorff = _compute_corrections(square, square)
    assert len(corrections) == 32  # default num_sample_points
    for c in corrections:
        assert abs(c["dx"]) < 1
        assert abs(c["dy"]) < 1
    assert hausdorff < 1


def test_corrections_direction():
    ref = _make_contour([[0, 0], [100, 0], [100, 100], [0, 100]])
    # Drawing is shifted 20px to the right → corrections should point left (negative dx)
    draw = _make_contour([[20, 0], [120, 0], [120, 100], [20, 100]])
    corrections, hausdorff = _compute_corrections(ref, draw)
    # Average dx should be negative (ref is to the left of draw)
    avg_dx = sum(c["dx"] for c in corrections) / len(corrections)
    assert avg_dx < 0


# ---------------------------------------------------------------------------
# _severity
# ---------------------------------------------------------------------------


def test_severity_thresholds():
    assert _severity(25) == "critical"
    assert _severity(15) == "high"
    assert _severity(7) == "medium"
    assert _severity(2) == "low"
