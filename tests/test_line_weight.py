"""Tests for light-direction-based line weight computation.

Tests pure Python compute_segment_normal and compute_line_weights functions.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.drawing.line_weight import (
    compute_segment_normal,
    compute_line_weights,
    LIGHT_VECTORS,
)


# ---------------------------------------------------------------------------
# Segment normal computation
# ---------------------------------------------------------------------------


def test_horizontal_segment_normal():
    """Horizontal segment (left→right) has upward normal in AI coords."""
    normal = compute_segment_normal([0, 0], [100, 0])
    # Perpendicular CCW of [1, 0] is [0, 1] (upward)
    assert normal[0] == pytest.approx(0.0, abs=0.01)
    assert normal[1] == pytest.approx(1.0, abs=0.01)


def test_vertical_segment_normal():
    """Vertical segment (bottom→top) has leftward normal."""
    normal = compute_segment_normal([0, 0], [0, 100])
    # Perpendicular CCW of [0, 1] is [-1, 0] (leftward)
    assert normal[0] == pytest.approx(-1.0, abs=0.01)
    assert normal[1] == pytest.approx(0.0, abs=0.01)


def test_diagonal_segment_normal():
    """45-degree segment has a normal at 135 degrees (CCW rotation)."""
    normal = compute_segment_normal([0, 0], [100, 100])
    # Direction = [1/sqrt2, 1/sqrt2], Normal CCW = [-1/sqrt2, 1/sqrt2]
    expected_x = -1 / math.sqrt(2)
    expected_y = 1 / math.sqrt(2)
    assert normal[0] == pytest.approx(expected_x, abs=0.01)
    assert normal[1] == pytest.approx(expected_y, abs=0.01)


# ---------------------------------------------------------------------------
# Weight assignment vs light direction
# ---------------------------------------------------------------------------


def test_segment_facing_light_gets_thin():
    """Segment normal pointing toward light source gets thin width."""
    # Light from top → light_vec = (0, 1). Horizontal segment normal = (0, 1).
    # dot = 1.0 → facing light → should be thin.
    points = [[0, 0], [100, 0]]
    segments = compute_line_weights(points, "top", min_width=0.5, max_width=4.0)
    assert len(segments) == 1
    # dot ≈ 1.0 → t ≈ 0 → width ≈ min_width
    assert segments[0]["width"] == pytest.approx(0.5, abs=0.1)


def test_segment_facing_away_gets_thick():
    """Segment normal pointing away from light gets thick width."""
    # Light from top → (0, 1). Segment going right→left: [100,0]→[0,0].
    # Normal of right→left = perpendicular CCW of [-1, 0] = [0, -1].
    # dot = (0)*(0) + (-1)*(1) = -1 → facing away → thick.
    points = [[100, 0], [0, 0]]
    segments = compute_line_weights(points, "top", min_width=0.5, max_width=4.0)
    assert len(segments) == 1
    # dot ≈ -1.0 → t ≈ 1.0 → width ≈ max_width
    assert segments[0]["width"] == pytest.approx(4.0, abs=0.1)


def test_corner_always_gets_max_width():
    """Sharp corners should always get maximum width regardless of normal."""
    # Three points forming a right angle: straight then sharp turn
    points = [[0, 0], [100, 0], [100, 100]]
    segments = compute_line_weights(
        points, "top", min_width=0.5, max_width=4.0, corner_threshold=45,
    )
    assert len(segments) == 2
    # Second segment changes direction by 90 degrees → is_corner = True
    assert segments[1]["is_corner"] is True
    assert segments[1]["width"] == pytest.approx(4.0)
