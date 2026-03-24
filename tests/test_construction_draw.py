"""Tests for construction drawing geometry.

Tests pure Python geometry helpers (compute_head_circle, compute_body_box,
compute_limb_cylinder) directly — no Adobe app required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.construction_draw import (
    compute_head_circle,
    compute_body_box,
    compute_limb_cylinder,
    _midpoint,
    _distance,
)


# ---------------------------------------------------------------------------
# Head circle dimensions
# ---------------------------------------------------------------------------


def test_head_circle_centre_at_midpoint():
    """Circle centre should be the midpoint between head_top and chin."""
    landmarks = {
        "head_top": {"ai": [100, 500]},
        "chin": {"ai": [100, 450]},
    }
    result = compute_head_circle(landmarks)
    assert "error" not in result
    assert result["center"][0] == pytest.approx(100.0)
    assert result["center"][1] == pytest.approx(475.0)


def test_head_circle_diameter():
    """Diameter should equal the distance from head_top to chin."""
    landmarks = {
        "head_top": {"ai": [100, 500]},
        "chin": {"ai": [100, 450]},
    }
    result = compute_head_circle(landmarks)
    assert result["diameter"] == pytest.approx(50.0)


def test_head_circle_diagonal():
    """Head circle with diagonal head_top→chin still computes correctly."""
    landmarks = {
        "head_top": {"ai": [100, 500]},
        "chin": {"ai": [130, 460]},
    }
    result = compute_head_circle(landmarks)
    expected_d = math.sqrt(30**2 + 40**2)  # 50.0
    assert result["diameter"] == pytest.approx(expected_d)
    assert result["center"][0] == pytest.approx(115.0)
    assert result["center"][1] == pytest.approx(480.0)


# ---------------------------------------------------------------------------
# Body box dimensions
# ---------------------------------------------------------------------------


def test_body_box_dimensions():
    """Body box width = shoulder span, height = shoulder→hip distance."""
    landmarks = {
        "shoulder_l": {"ai": [80, 400]},
        "shoulder_r": {"ai": [120, 400]},
        "hip_center": {"ai": [100, 300]},
    }
    result = compute_body_box(landmarks)
    assert "error" not in result
    assert result["width"] == pytest.approx(40.0)
    assert result["height"] == pytest.approx(100.0)
    assert result["left"] == pytest.approx(80.0)
    assert result["top"] == pytest.approx(400.0)


def test_body_box_missing_landmark():
    """Body box returns error when a required landmark is missing."""
    landmarks = {
        "shoulder_l": {"ai": [80, 400]},
        # Missing shoulder_r and hip_center
    }
    result = compute_body_box(landmarks)
    assert "error" in result


# ---------------------------------------------------------------------------
# Limb cylinder
# ---------------------------------------------------------------------------


def test_limb_cylinder_dimensions():
    """Cylinder major axis = inter-joint distance, minor = 30% of major."""
    landmarks = {
        "shoulder_l": {"ai": [80, 400]},
        "elbow_l": {"ai": [80, 300]},
    }
    result = compute_limb_cylinder(landmarks, "shoulder_l", "elbow_l")
    assert "error" not in result
    assert result["major"] == pytest.approx(100.0)
    assert result["minor"] == pytest.approx(30.0)
    assert result["center"][0] == pytest.approx(80.0)
    assert result["center"][1] == pytest.approx(350.0)


def test_limb_cylinder_angle():
    """Cylinder angle matches the angle between the two landmarks."""
    landmarks = {
        "a": {"ai": [0, 0]},
        "b": {"ai": [100, 100]},
    }
    result = compute_limb_cylinder(landmarks, "a", "b")
    assert result["angle_deg"] == pytest.approx(45.0)


def test_limb_cylinder_missing_landmark():
    """Cylinder returns error when a landmark doesn't exist."""
    landmarks = {"shoulder_l": {"ai": [80, 400]}}
    result = compute_limb_cylinder(landmarks, "shoulder_l", "nonexistent")
    assert "error" in result
