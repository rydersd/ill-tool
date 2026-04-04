"""Tests for proportion checking against artistic canons.

Tests pure Python proportion math — ratio computation, canon comparison,
and limb proportion validation.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.drawing.proportion_check import (
    compute_head_height,
    compute_body_height,
    compute_proportion_ratio,
    check_limb_proportions,
    CANONS,
)


# ---------------------------------------------------------------------------
# Helper: build a set of landmarks at controlled positions
# ---------------------------------------------------------------------------


def _make_landmarks(head_y=500, chin_y=450, feet_y=125):
    """Create a standard landmark set with controllable heights.

    Default proportions: head=50, body=375, ratio=7.5 (realistic).
    """
    return {
        "head_top": {"ai": [100, head_y]},
        "chin": {"ai": [100, chin_y]},
        "feet_bottom": {"ai": [100, feet_y]},
        "shoulder_l": {"ai": [80, 430]},
        "shoulder_r": {"ai": [120, 430]},
        "hip_center": {"ai": [100, 300]},
        "hip_l": {"ai": [90, 300]},
        "elbow_l": {"ai": [70, 360]},
        "wrist_l": {"ai": [60, 300]},
        "knee_l": {"ai": [90, 210]},
        "ankle_l": {"ai": [90, 130]},
    }


# ---------------------------------------------------------------------------
# Head height
# ---------------------------------------------------------------------------


def test_head_height_calculation():
    """Head height is the distance from head_top to chin."""
    lm = _make_landmarks()
    h = compute_head_height(lm)
    assert h == pytest.approx(50.0)


def test_head_height_missing():
    """Returns None when head_top or chin is missing."""
    assert compute_head_height({}) is None
    assert compute_head_height({"head_top": {"ai": [0, 0]}}) is None


# ---------------------------------------------------------------------------
# Body height
# ---------------------------------------------------------------------------


def test_body_height_calculation():
    """Body height is the distance from head_top to feet_bottom."""
    lm = _make_landmarks()
    h = compute_body_height(lm)
    assert h == pytest.approx(375.0)


# ---------------------------------------------------------------------------
# Ratio matches each canon
# ---------------------------------------------------------------------------


def test_realistic_canon():
    """7.5-head figure should match realistic canon closely."""
    # head=50, body=375 → ratio=7.5
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=125)
    result = compute_proportion_ratio(lm)
    assert result["ratio"] == pytest.approx(7.5)


def test_heroic_canon():
    """8-head figure should match heroic canon."""
    # head=50, body=400 → ratio=8.0
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=100)
    result = compute_proportion_ratio(lm)
    assert result["ratio"] == pytest.approx(8.0)


def test_anime_canon():
    """5-head figure should match anime canon."""
    # head=50, body=250 → ratio=5.0
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=250)
    result = compute_proportion_ratio(lm)
    assert result["ratio"] == pytest.approx(5.0)


def test_chibi_canon():
    """2-head figure should match chibi canon."""
    # head=50, body=100 → ratio=2.0
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=400)
    result = compute_proportion_ratio(lm)
    assert result["ratio"] == pytest.approx(2.0)


def test_cartoon_canon():
    """3.5-head figure should match cartoon canon."""
    # head=50, body=175 → ratio=3.5
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=325)
    result = compute_proportion_ratio(lm)
    assert result["ratio"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Deviation computation
# ---------------------------------------------------------------------------


def test_deviation_percentage():
    """Deviation percentage is correct when actual differs from expected."""
    # ratio=7.5, expected for heroic=8.0 → deviation = |7.5-8|/8 * 100 = 6.25 %
    lm = _make_landmarks(head_y=500, chin_y=450, feet_y=125)
    result = compute_proportion_ratio(lm)
    ratio = result["ratio"]
    expected = CANONS["heroic"]
    dev = abs(ratio - expected) / expected * 100
    assert dev == pytest.approx(6.25)


def test_limb_violation_detection():
    """A limb that is 30 % off from expected triggers a violation."""
    # Create landmarks where upper_arm is way too long
    lm = _make_landmarks()
    # Override elbow to make upper_arm very long
    lm["elbow_l"] = {"ai": [70, 200]}  # shoulder_l at 430, elbow at 200 → 230 units
    body_h = 375.0  # from _make_landmarks
    violations = check_limb_proportions(lm, "realistic", body_h)
    # upper_arm actual = 230/375 * 100 ≈ 61.3 %, expected ~14 % → big violation
    limb_names = [v["limb"] for v in violations]
    assert "upper_arm" in limb_names
