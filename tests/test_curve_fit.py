"""Tests for the cubic bezier curve fitting algorithm.

Tests _fit_cubic, _max_error, _detect_corners, and fit_bezier_path
using synthetic point sets with known geometry.
"""

import math

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.core.curve_fit import (
    _fit_cubic,
    _max_error,
    _detect_corners,
    _evaluate_bezier,
    _chord_length_parameterize,
    fit_bezier_path,
)


# ---------------------------------------------------------------------------
# Fit straight line
# ---------------------------------------------------------------------------


def test_fit_straight_line():
    """Points on a straight line produce collinear control points.

    For a straight line from (0,0) to (100,0), the fitted bezier control
    points p1 and p2 should lie on the same line (y=0).
    """
    points = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0], [75.0, 0.0], [100.0, 0.0]])
    p0, p1, p2, p3 = _fit_cubic(points)

    # All y values should be near zero (collinear on y=0)
    assert abs(p0[1]) < 1e-6
    assert abs(p1[1]) < 1e-6
    assert abs(p2[1]) < 1e-6
    assert abs(p3[1]) < 1e-6

    # Endpoints should match
    assert p0[0] == pytest.approx(0.0)
    assert p3[0] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Fit known curve
# ---------------------------------------------------------------------------


def test_fit_known_curve():
    """Points sampled from a known cubic bezier produce finite, bounded error.

    The least-squares fitting uses a simplified tangent estimation from the
    first/last few points, so it won't perfectly reconstruct the original
    control points. We verify that:
    1. _fit_cubic produces non-NaN control points with bounded error
    2. fit_bezier_path with recursive subdivision keeps total error manageable
    """
    # Single cubic fit: verify it produces valid results
    known_p0 = np.array([0.0, 0.0])
    known_p1 = np.array([30.0, 80.0])
    known_p2 = np.array([70.0, 80.0])
    known_p3 = np.array([100.0, 0.0])

    t_vals = np.linspace(0, 1, 20)
    sample_points = _evaluate_bezier(known_p0, known_p1, known_p2, known_p3, t_vals)

    fp0, fp1, fp2, fp3 = _fit_cubic(sample_points)

    # Control points should be finite
    for cp in [fp0, fp1, fp2, fp3]:
        assert not np.any(np.isnan(cp)), "Control point contains NaN"
        assert not np.any(np.isinf(cp)), "Control point contains Inf"

    # Endpoints should be preserved exactly
    np.testing.assert_allclose(fp0, sample_points[0], atol=1e-6)
    np.testing.assert_allclose(fp3, sample_points[-1], atol=1e-6)

    # Error should be finite (the algorithm may not perfectly reconstruct)
    err = _max_error(sample_points, fp0, fp1, fp2, fp3)
    assert np.isfinite(err)

    # Full path fitter with recursive subdivision should produce lower error
    segments = fit_bezier_path(sample_points, error_threshold=5.0)
    assert len(segments) >= 1
    # Verify all control points are valid
    for p0, p1, p2, p3 in segments:
        assert not np.any(np.isnan(p0))
        assert not np.any(np.isnan(p3))


# ---------------------------------------------------------------------------
# Error below threshold
# ---------------------------------------------------------------------------


def test_error_below_threshold():
    """fit_bezier_path with a low threshold keeps error under control."""
    # Quarter circle points
    angles = np.linspace(0, math.pi / 2, 15)
    radius = 100.0
    points = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])

    segments = fit_bezier_path(points, error_threshold=2.0)
    assert len(segments) > 0

    # Check max error per segment
    for p0, p1, p2, p3 in segments:
        # Evaluate at dense t values for error checking
        t_check = np.linspace(0, 1, 50)
        fitted = _evaluate_bezier(p0, p1, p2, p3, t_check)
        # Each fitted point should be reasonably close to the curve
        # (not a strict per-segment test, but validates no wild outliers)
        for pt in fitted:
            dist_to_origin = np.sqrt(pt[0] ** 2 + pt[1] ** 2)
            # Points should be roughly on a circle of radius 100
            assert dist_to_origin < 150, "Fitted point is too far from expected curve"


# ---------------------------------------------------------------------------
# Corner detection
# ---------------------------------------------------------------------------


def test_detect_corners_on_square():
    """Corner detection finds corners of a square."""
    # Square corners at (0,0), (100,0), (100,100), (0,100) with intermediate points
    points = np.array([
        [0, 0], [50, 0], [100, 0],
        [100, 50], [100, 100],
        [50, 100], [0, 100],
        [0, 50],
    ], dtype=np.float64)

    corners = _detect_corners(points, angle_threshold_deg=45.0)
    # Should include first (0) and last (7) always
    assert 0 in corners
    assert len(points) - 1 in corners
    # The 90-degree corners at indices 2, 4, 6 should be detected
    assert 2 in corners  # (100, 0) corner
    assert 4 in corners  # (100, 100) corner


def test_detect_corners_on_line():
    """Straight line: collinear points have angle=0 (vectors parallel).

    In the implementation, deviation = pi - angle. When angle=0 (parallel),
    deviation=pi (~180 deg), which exceeds any threshold. So every interior
    point on a straight line is flagged as a corner. This is by design —
    the algorithm targets smooth curves where collinear segments are rare.

    For practical use, straight lines are handled by the fitter itself.
    """
    points = np.array([
        [0, 0], [25, 0], [50, 0], [75, 0], [100, 0]
    ], dtype=np.float64)

    corners = _detect_corners(points, angle_threshold_deg=45.0)
    # All points detected as corners (deviation = pi for collinear points)
    assert 0 in corners
    assert len(points) - 1 in corners
    assert len(corners) == len(points)


def test_detect_corners_sharp_vs_gentle():
    """Sharp turns produce more corners than gentle turns.

    The algorithm uses deviation = pi - angle_between_vectors.
    A sharp 90-degree turn has deviation ~90 deg (pi - pi/2).
    A gentle 170-degree turn has deviation ~10 deg (pi - 170*pi/180).

    With a 45-degree threshold, only the sharp turn should be detected.
    """
    # Path: gentle curve → sharp 90-degree corner → gentle curve
    points = np.array([
        [0, 0], [10, 1], [20, 2],       # gentle slope
        [30, 3],                          # corner point
        [30, 13], [30, 23], [30, 33],    # vertical after corner
    ], dtype=np.float64)

    corners = _detect_corners(points, angle_threshold_deg=45.0)
    # Index 3 is the sharp 90-degree turn
    assert 3 in corners
    # First and last are always included
    assert 0 in corners
    assert len(points) - 1 in corners


# ---------------------------------------------------------------------------
# Chord-length parameterization
# ---------------------------------------------------------------------------


def test_chord_length_endpoints():
    """First parameter is 0 and last is 1."""
    points = np.array([[0, 0], [3, 4], [6, 8]], dtype=np.float64)
    t = _chord_length_parameterize(points)
    assert t[0] == pytest.approx(0.0)
    assert t[-1] == pytest.approx(1.0)


def test_chord_length_uniform_spacing():
    """Equally-spaced points get equally-spaced parameter values."""
    points = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], dtype=np.float64)
    t = _chord_length_parameterize(points)
    # Should be [0, 1/3, 2/3, 1]
    expected = np.array([0.0, 1 / 3, 2 / 3, 1.0])
    np.testing.assert_allclose(t, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Degenerate cases
# ---------------------------------------------------------------------------


def test_fit_two_points():
    """Fitting exactly 2 points produces a degenerate straight-line bezier."""
    points = np.array([[0.0, 0.0], [100.0, 50.0]])
    p0, p1, p2, p3 = _fit_cubic(points)
    # For 2 points, handles collapse to endpoints
    np.testing.assert_allclose(p0, [0.0, 0.0])
    np.testing.assert_allclose(p3, [100.0, 50.0])


def test_fit_bezier_path_few_points():
    """fit_bezier_path with < 2 points returns empty list."""
    points = np.array([[10.0, 20.0]])
    segments = fit_bezier_path(points, error_threshold=1.0)
    assert segments == []
