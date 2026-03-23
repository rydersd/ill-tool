"""Tests for batch pose interpolation across panels.

Tests pure Python t-value computation and verifies interpolation behaviour.
"""

import pytest

from adobe_mcp.apps.illustrator.batch_pose import compute_panel_t_values


# ---------------------------------------------------------------------------
# t-value computation
# ---------------------------------------------------------------------------


def test_five_panels():
    """Five panels [3,4,5,6,7] should produce t = 0, 0.25, 0.5, 0.75, 1.0."""
    result = compute_panel_t_values([3, 4, 5, 6, 7])
    assert len(result) == 5
    assert result[0]["panel"] == 3
    assert result[0]["t"] == pytest.approx(0.0)
    assert result[1]["t"] == pytest.approx(0.25)
    assert result[2]["t"] == pytest.approx(0.5)
    assert result[3]["t"] == pytest.approx(0.75)
    assert result[4]["t"] == pytest.approx(1.0)


def test_two_panels():
    """Two panels should produce t = 0.0 and 1.0."""
    result = compute_panel_t_values([1, 2])
    assert len(result) == 2
    assert result[0]["t"] == pytest.approx(0.0)
    assert result[1]["t"] == pytest.approx(1.0)


def test_single_panel():
    """Single panel should produce t = 0.0."""
    result = compute_panel_t_values([5])
    assert len(result) == 1
    assert result[0]["t"] == pytest.approx(0.0)
    assert result[0]["panel"] == 5


def test_empty_range():
    """Empty panel range should return empty list."""
    result = compute_panel_t_values([])
    assert len(result) == 0


def test_three_panels_midpoint():
    """Three panels should have midpoint at t = 0.5."""
    result = compute_panel_t_values([10, 11, 12])
    assert len(result) == 3
    assert result[0]["t"] == pytest.approx(0.0)
    assert result[1]["t"] == pytest.approx(0.5)
    assert result[2]["t"] == pytest.approx(1.0)
