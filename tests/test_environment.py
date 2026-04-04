"""Tests for the environment/set design tool.

Verifies vanishing point calculation and grid line geometry.
All tests are pure Python — no JSX or Adobe required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.production.environment import (
    compute_vanishing_points,
    compute_grid_lines,
    _ensure_environment,
)


# ---------------------------------------------------------------------------
# Vanishing point computation
# ---------------------------------------------------------------------------


def test_1_point_default_center():
    """1-point grid places VP at center of panel on horizon."""
    vps = compute_vanishing_points("1_point", 960, 540, 0.5)
    assert len(vps) == 1
    assert vps[0]["x"] == pytest.approx(480.0)
    assert vps[0]["y"] == pytest.approx(270.0)
    assert vps[0]["label"] == "VP"


def test_2_point_two_vps_on_horizon():
    """2-point grid places two VPs on the horizon line."""
    vps = compute_vanishing_points("2_point", 960, 540, 0.5)
    assert len(vps) == 2
    # Both VPs should be at the same Y (horizon)
    assert vps[0]["y"] == pytest.approx(270.0)
    assert vps[1]["y"] == pytest.approx(270.0)
    # Left VP should be left of right VP
    assert vps[0]["x"] < vps[1]["x"]


def test_3_point_has_vertical_vp():
    """3-point grid has a third VP above or below the horizon."""
    vps = compute_vanishing_points("3_point", 960, 540, 0.6)
    assert len(vps) == 3
    # First two on horizon
    horizon_y = 540 * 0.6
    assert vps[0]["y"] == pytest.approx(horizon_y)
    assert vps[1]["y"] == pytest.approx(horizon_y)
    # Third VP off-horizon (above since horizon_y_pct > 0.5)
    assert vps[2]["label"] == "VP_V"
    assert vps[2]["y"] == pytest.approx(0.0)  # above the horizon


# ---------------------------------------------------------------------------
# Grid line computation
# ---------------------------------------------------------------------------


def test_grid_lines_radiate_from_vp():
    """Grid lines all start from the vanishing point."""
    vps = [{"x": 480.0, "y": 270.0, "label": "VP"}]
    lines = compute_grid_lines(vps, 960, 540, 8)

    for line in lines:
        assert line["start"] == [480.0, 270.0]
        assert line["vp_label"] == "VP"


def test_grid_line_count_matches():
    """Number of grid lines equals num_lines per VP."""
    vps = [{"x": 480.0, "y": 270.0, "label": "VP"}]
    lines = compute_grid_lines(vps, 960, 540, 12)
    assert len(lines) == 12

    # With 2 VPs, should get 2 * num_lines
    vps_2 = [
        {"x": 96.0, "y": 270.0, "label": "VP_L"},
        {"x": 864.0, "y": 270.0, "label": "VP_R"},
    ]
    lines_2 = compute_grid_lines(vps_2, 960, 540, 8)
    assert len(lines_2) == 16
