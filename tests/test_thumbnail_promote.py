"""Tests for the thumbnail promote tool.

Verifies scale factor calculation and landmark position scaling.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.ui.thumbnail_promote import (
    calculate_scale_factor,
    scale_landmarks,
)


# ---------------------------------------------------------------------------
# Scale factor calculation
# ---------------------------------------------------------------------------


def test_scale_4x_uniform():
    """240x135 -> 960x540 gives exactly 4x uniform scale."""
    result = calculate_scale_factor(240, 135, 960, 540)
    assert result["uniform_scale"] == pytest.approx(4.0)
    assert result["scale_x"] == pytest.approx(4.0)
    assert result["scale_y"] == pytest.approx(4.0)


def test_scale_non_uniform_picks_smaller():
    """Non-matching aspect ratios use the smaller scale to fit without cropping."""
    # 100x100 -> 400x200: scale_x=4, scale_y=2, uniform=2
    result = calculate_scale_factor(100, 100, 400, 200)
    assert result["scale_x"] == pytest.approx(4.0)
    assert result["scale_y"] == pytest.approx(2.0)
    assert result["uniform_scale"] == pytest.approx(2.0)


def test_scale_zero_source_returns_identity():
    """Zero source dimensions return 1.0 scale factor."""
    result = calculate_scale_factor(0, 0, 960, 540)
    assert result["uniform_scale"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Landmark position scaling
# ---------------------------------------------------------------------------


def test_landmark_scaling_doubles():
    """Landmarks scale by 2x when scale factor is 2."""
    landmarks = {
        "head_top": {"ai": [100.0, -50.0], "type": "structural"},
        "chin": {"ai": [100.0, -80.0], "type": "structural"},
    }
    result = scale_landmarks(landmarks, 2.0)
    assert result["head_top"]["ai"] == [200.0, -100.0]
    assert result["chin"]["ai"] == [200.0, -160.0]
    assert result["head_top"].get("promoted") is True


def test_landmark_scaling_with_offset():
    """Landmarks can be offset after scaling."""
    landmarks = {
        "point": {"ai": [10.0, -20.0], "type": "feature"},
    }
    result = scale_landmarks(landmarks, 3.0, offset_x=100.0, offset_y=-50.0)
    # 10*3 + 100 = 130,  -20*3 + (-50) = -110
    assert result["point"]["ai"] == [130.0, -110.0]
