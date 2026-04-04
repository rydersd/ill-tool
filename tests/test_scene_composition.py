"""Tests for scene composition rules.

Tests pure Python composition math: thirds positions, golden ratio,
depth zones, and scoring.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.storyboard.scene_composition import (
    compute_thirds,
    compute_golden_ratio_points,
    compute_depth_zones,
    score_composition,
)


# ---------------------------------------------------------------------------
# Rule of thirds positions
# ---------------------------------------------------------------------------


def test_thirds_vertical_lines():
    """Vertical lines at 1/3 and 2/3 of panel width."""
    thirds = compute_thirds(0, 0, 900, 600)
    assert thirds["vertical_lines"][0] == pytest.approx(300.0)
    assert thirds["vertical_lines"][1] == pytest.approx(600.0)


def test_thirds_horizontal_lines():
    """Horizontal lines at 1/3 and 2/3 of panel height (AI coords: Y decreases)."""
    thirds = compute_thirds(0, 0, 900, 600)
    # panel_y=0, height=600 → y1 = 0 - 200 = -200, y2 = 0 - 400 = -400
    assert thirds["horizontal_lines"][0] == pytest.approx(-200.0)
    assert thirds["horizontal_lines"][1] == pytest.approx(-400.0)


def test_thirds_power_points_count():
    """Should produce exactly 4 power points (intersections of thirds lines)."""
    thirds = compute_thirds(0, 0, 900, 600)
    assert len(thirds["power_points"]) == 4


# ---------------------------------------------------------------------------
# Golden ratio
# ---------------------------------------------------------------------------


def test_golden_ratio_phi():
    """Phi should be approximately 1.618."""
    golden = compute_golden_ratio_points(0, 0, 900, 600)
    assert golden["phi"] == pytest.approx(1.618034, abs=0.001)


def test_golden_ratio_lines_within_panel():
    """Golden ratio lines should fall within panel bounds."""
    golden = compute_golden_ratio_points(0, 0, 900, 600)
    for x in golden["vertical_lines"]:
        assert 0 < x < 900
    for y in golden["horizontal_lines"]:
        assert -600 < y < 0  # AI coords


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_on_power_point():
    """Character exactly on a power point should score 100."""
    power_points = [[300, -200], [600, -200], [300, -400], [600, -400]]
    positions = [[300, -200]]
    result = score_composition(positions, power_points, 900, 600)
    assert result["per_position"][0]["score"] == pytest.approx(100.0)


def test_score_far_from_power_points():
    """Character far from all power points should score low."""
    power_points = [[300, -200], [600, -200], [300, -400], [600, -400]]
    # Place character at corner — far from all power points
    positions = [[0, 0]]
    result = score_composition(positions, power_points, 900, 600)
    assert result["per_position"][0]["score"] < 50
