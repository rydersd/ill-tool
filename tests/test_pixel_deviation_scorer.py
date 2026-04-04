"""Tests for the pixel deviation scorer — Hausdorff-based contour comparison.

Tests verify distance computation, scoring normalization, contour matching,
calibration round-trip, and edge cases (empty contours, single points).
No Adobe app required.
"""

import json
import math
import os
import tempfile

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.pixel_deviation_scorer import (
    hausdorff_distance,
    mean_contour_distance,
    score_pixel_deviation,
    save_calibration,
    load_calibration,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic contour generators
# ---------------------------------------------------------------------------


def _make_circle_contour(
    cx: float = 100.0, cy: float = 100.0, radius: float = 40.0, n_pts: int = 64,
) -> np.ndarray:
    """Generate a circular contour as Nx2 array of (x, y) points."""
    angles = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
    xs = cx + radius * np.cos(angles)
    ys = cy + radius * np.sin(angles)
    return np.column_stack([xs, ys])


def _make_square_contour(
    x0: float = 50.0, y0: float = 50.0, size: float = 100.0, n_pts_per_side: int = 10,
) -> np.ndarray:
    """Generate a square contour as Nx2 array with points distributed along edges."""
    pts: list[list[float]] = []
    for i in range(n_pts_per_side):
        t = i / n_pts_per_side
        pts.append([x0 + t * size, y0])  # top
    for i in range(n_pts_per_side):
        t = i / n_pts_per_side
        pts.append([x0 + size, y0 + t * size])  # right
    for i in range(n_pts_per_side):
        t = i / n_pts_per_side
        pts.append([x0 + size - t * size, y0 + size])  # bottom
    for i in range(n_pts_per_side):
        t = i / n_pts_per_side
        pts.append([x0, y0 + size - t * size])  # left
    return np.array(pts, dtype=np.float64)


# ---------------------------------------------------------------------------
# Tests: identical contours produce score 1.0
# ---------------------------------------------------------------------------


class TestIdenticalContours:
    """Identical contour sets should score 1.0 (zero deviation)."""

    def test_identical_circles_score_one(self):
        """Two identical circle contours produce a score of 1.0."""
        circle = _make_circle_contour()
        result = score_pixel_deviation([circle], [circle])
        assert result["score"] == pytest.approx(1.0, abs=1e-6)
        assert result["mean_deviation"] == pytest.approx(0.0, abs=1e-6)
        assert result["max_deviation"] == pytest.approx(0.0, abs=1e-6)
        assert result["matched_pairs"] == 1
        assert result["unmatched_ref"] == 0
        assert result["unmatched_test"] == 0

    def test_identical_squares_score_one(self):
        """Two identical square contours produce a score of 1.0."""
        sq = _make_square_contour()
        result = score_pixel_deviation([sq], [sq])
        assert result["score"] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Tests: shifted contour produces proportional score
# ---------------------------------------------------------------------------


class TestShiftedContours:
    """A contour shifted by a known amount produces a score proportional to the shift."""

    def test_small_shift_high_score(self):
        """A 5px shift on a ~113px diagonal contour gives a high score."""
        circle = _make_circle_contour(cx=100, cy=100, radius=40)
        shifted = circle + np.array([5.0, 0.0])

        result = score_pixel_deviation([circle], [shifted])

        # Mean deviation is less than the shift amount because the nearest
        # point on the opposing contour is found for each point — points on
        # the near side of the circle are closer to each other than the
        # shift magnitude. The deviation should be positive and bounded by
        # the shift amount.
        assert 0.0 < result["mean_deviation"] <= 5.0
        # Score should be high (deviation is small relative to scale)
        assert result["score"] > 0.9

    def test_large_shift_low_score(self):
        """A large shift produces a proportionally lower score."""
        circle = _make_circle_contour(cx=100, cy=100, radius=40)
        shifted = circle + np.array([60.0, 60.0])

        result = score_pixel_deviation([circle], [shifted])

        # Mean deviation is bounded by the shift magnitude: for circles
        # with radius 40 shifted by ~85px, nearest-point distances are
        # reduced on the near side. The deviation should be substantial
        # but less than the full centroid-to-centroid distance.
        shift_mag = math.hypot(60, 60)
        assert result["mean_deviation"] > 0.0
        assert result["mean_deviation"] <= shift_mag
        # Score should be meaningfully lower than identical
        assert result["score"] < 0.6

    def test_larger_shift_means_lower_score(self):
        """Monotonicity: larger shift always produces lower score."""
        circle = _make_circle_contour()
        shift_small = circle + np.array([5.0, 0.0])
        shift_large = circle + np.array([30.0, 0.0])

        result_small = score_pixel_deviation([circle], [shift_small])
        result_large = score_pixel_deviation([circle], [shift_large])

        assert result_small["score"] > result_large["score"]


# ---------------------------------------------------------------------------
# Tests: totally disjoint contours produce score near 0.0
# ---------------------------------------------------------------------------


class TestDisjointContours:
    """Contours in completely different locations score near 0.0."""

    def test_distant_contours_near_zero(self):
        """Two circles 1000px apart should score near 0.0."""
        c1 = _make_circle_contour(cx=50, cy=50, radius=20)
        c2 = _make_circle_contour(cx=1050, cy=1050, radius=20)

        result = score_pixel_deviation([c1], [c2])

        # The deviation is huge relative to the reference scale (~40px diagonal)
        assert result["score"] < 0.1


# ---------------------------------------------------------------------------
# Tests: score is invariant to contour point count
# ---------------------------------------------------------------------------


class TestPointCountInvariance:
    """Resampling a contour to more/fewer points should not change the score."""

    def test_resample_does_not_change_score(self):
        """Same circle with 32 vs 128 points produces similar score against a reference."""
        ref = _make_circle_contour(n_pts=64)
        test_sparse = _make_circle_contour(n_pts=32)
        test_dense = _make_circle_contour(n_pts=128)

        result_sparse = score_pixel_deviation([ref], [test_sparse])
        result_dense = score_pixel_deviation([ref], [test_dense])

        # Both should be very close to 1.0 (same geometric shape)
        assert result_sparse["score"] > 0.99
        assert result_dense["score"] > 0.99
        # And close to each other
        assert abs(result_sparse["score"] - result_dense["score"]) < 0.01


# ---------------------------------------------------------------------------
# Tests: Hausdorff distance symmetry
# ---------------------------------------------------------------------------


class TestHausdorffSymmetry:
    """Symmetric Hausdorff: max(d(A,B), d(B,A)) is symmetric by definition,
    but directed Hausdorff d(A,B) should also equal d(B,A) for identical
    point sets that simply differ in ordering."""

    def test_hausdorff_symmetric_for_shifted_contours(self):
        """Directed Hausdorff d(A,B) == d(B,A) when contours have same density."""
        a = _make_circle_contour(cx=100, cy=100, n_pts=64)
        b = _make_circle_contour(cx=110, cy=100, n_pts=64)

        d_ab = hausdorff_distance(a, b)
        d_ba = hausdorff_distance(b, a)

        # For uniform-density contours, directed Hausdorff is symmetric
        assert d_ab == pytest.approx(d_ba, abs=0.5)


# ---------------------------------------------------------------------------
# Tests: mean distance is always <= Hausdorff distance
# ---------------------------------------------------------------------------


class TestMeanVsHausdorff:
    """Mean contour distance must always be <= Hausdorff distance,
    since Hausdorff is the max of nearest-point distances while
    mean is the average."""

    def test_mean_leq_hausdorff(self):
        """Mean distance <= Hausdorff distance for non-trivial contours."""
        a = _make_circle_contour(cx=100, cy=100, radius=40)
        b = _make_square_contour(x0=80, y0=80, size=60)

        mean_d = mean_contour_distance(a, b)
        haus_d = hausdorff_distance(a, b)

        assert mean_d <= haus_d + 1e-9  # small tolerance for floating point


# ---------------------------------------------------------------------------
# Tests: calibration data round-trip
# ---------------------------------------------------------------------------


class TestCalibrationRoundTrip:
    """Calibration save/load should produce identical data."""

    def test_save_load_round_trip(self, tmp_path):
        """Data written by save_calibration is read back identically."""
        cal_data = {
            "reference_scale": 283.5,
            "baseline_score": 0.42,
            "session_id": "test-session-001",
            "notes": "initial calibration from tower reference",
        }

        cal_path = str(tmp_path / "test_calibration.json")
        save_calibration(cal_data, path=cal_path)

        loaded = load_calibration(path=cal_path)
        assert loaded is not None
        assert loaded["reference_scale"] == pytest.approx(283.5)
        assert loaded["baseline_score"] == pytest.approx(0.42)
        assert loaded["session_id"] == "test-session-001"
        assert loaded["notes"] == "initial calibration from tower reference"

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading from a non-existent path returns None."""
        result = load_calibration(path=str(tmp_path / "does_not_exist.json"))
        assert result is None


# ---------------------------------------------------------------------------
# Tests: empty contour list handled gracefully
# ---------------------------------------------------------------------------


class TestEmptyContours:
    """Empty contour lists should not crash and should return meaningful scores."""

    def test_both_empty_score_one(self):
        """Two empty contour lists score 1.0 (nothing to compare = identical)."""
        result = score_pixel_deviation([], [])
        assert result["score"] == pytest.approx(1.0)
        assert result["matched_pairs"] == 0

    def test_ref_empty_test_has_contours(self):
        """Empty reference + non-empty test = score 0.0."""
        circle = _make_circle_contour()
        result = score_pixel_deviation([], [circle])
        assert result["score"] == pytest.approx(0.0)
        assert result["unmatched_test"] == 1

    def test_test_empty_ref_has_contours(self):
        """Non-empty reference + empty test = score 0.0."""
        circle = _make_circle_contour()
        result = score_pixel_deviation([circle], [])
        assert result["score"] == pytest.approx(0.0)
        assert result["unmatched_ref"] == 1


# ---------------------------------------------------------------------------
# Tests: single-point contours handled
# ---------------------------------------------------------------------------


class TestSinglePointContours:
    """Single-point contours are degenerate but should not crash."""

    def test_single_point_identical(self):
        """Two identical single-point contours score 1.0."""
        pt = np.array([[50.0, 50.0]])
        result = score_pixel_deviation([pt], [pt])
        assert result["score"] == pytest.approx(1.0, abs=1e-6)

    def test_single_point_distant(self):
        """Two distant single-point contours score near 0.0."""
        pt_a = np.array([[0.0, 0.0]])
        pt_b = np.array([[1000.0, 1000.0]])
        result = score_pixel_deviation([pt_a], [pt_b])
        # The deviation (~1414px) relative to scale (~0 from bbox) is huge
        assert result["score"] < 0.1


# ---------------------------------------------------------------------------
# Tests: explicit reference_scale produces expected value
# ---------------------------------------------------------------------------


class TestExplicitReferenceScale:
    """When reference_scale is set explicitly, score normalizes accordingly."""

    def test_known_deviation_with_known_scale(self):
        """Shift of 10px with reference_scale=100 gives score ~0.9."""
        circle = _make_circle_contour(cx=100, cy=100, radius=40)
        shifted = circle + np.array([10.0, 0.0])

        result = score_pixel_deviation([circle], [shifted], reference_scale=100.0)

        # mean_deviation ~ 10.0, scale = 100 -> score = 1 - 10/100 = 0.9
        assert result["score"] == pytest.approx(0.9, abs=0.05)

    def test_same_deviation_different_scales(self):
        """Same deviation with larger scale gives higher score."""
        circle = _make_circle_contour()
        shifted = circle + np.array([20.0, 0.0])

        result_small_scale = score_pixel_deviation([circle], [shifted], reference_scale=50.0)
        result_large_scale = score_pixel_deviation([circle], [shifted], reference_scale=500.0)

        assert result_large_scale["score"] > result_small_scale["score"]
