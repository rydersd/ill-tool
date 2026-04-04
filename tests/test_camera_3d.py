"""Tests for the 3D camera simulation tool.

Verifies focal length ↔ FOV conversion, FOV framing calculation,
and camera suggestion for desired framing.
All tests are pure Python — no 3D deps required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.threed.camera_3d import (
    focal_length_to_fov,
    fov_to_frame_width,
    suggest_camera,
)


# ---------------------------------------------------------------------------
# Focal length to FOV conversion
# ---------------------------------------------------------------------------


def test_focal_length_to_fov_50mm():
    """50mm lens on full-frame sensor should give approximately 39.6° FOV."""
    fov = focal_length_to_fov(50.0, sensor_mm=36.0)

    # Known value: 2 * atan(36 / (2 * 50)) = 2 * atan(0.36) ≈ 39.5978°
    expected = 2.0 * math.degrees(math.atan(36.0 / 100.0))
    assert abs(fov - expected) < 0.01, f"Expected ≈{expected}°, got {fov}°"


def test_focal_length_to_fov_wide_vs_tele():
    """Wider focal length should produce larger FOV than telephoto."""
    fov_wide = focal_length_to_fov(24.0)   # wide angle
    fov_normal = focal_length_to_fov(50.0)  # normal
    fov_tele = focal_length_to_fov(200.0)   # telephoto

    assert fov_wide > fov_normal > fov_tele
    # Wide should be > 70°, tele should be < 15°
    assert fov_wide > 70
    assert fov_tele < 15


def test_focal_length_to_fov_invalid():
    """Non-positive values raise ValueError."""
    with pytest.raises(ValueError, match="focal_mm"):
        focal_length_to_fov(0)
    with pytest.raises(ValueError, match="focal_mm"):
        focal_length_to_fov(-10)


# ---------------------------------------------------------------------------
# FOV to frame width
# ---------------------------------------------------------------------------


def test_fov_to_frame_width_90deg():
    """90° FOV at distance 1 should give width = 2 (2*tan(45°) = 2)."""
    width = fov_to_frame_width(90.0, 1.0)
    assert abs(width - 2.0) < 0.01, f"Expected 2.0, got {width}"


def test_fov_to_frame_width_scales_with_distance():
    """Frame width should scale linearly with distance."""
    w1 = fov_to_frame_width(60.0, 5.0)
    w2 = fov_to_frame_width(60.0, 10.0)
    # Width at double distance should be double
    assert abs(w2 / w1 - 2.0) < 0.01


# ---------------------------------------------------------------------------
# Camera suggestion
# ---------------------------------------------------------------------------


def test_suggest_camera_medium_framing():
    """Medium framing should show 60% of scene width."""
    result = suggest_camera(
        scene_width=100.0,
        distance=50.0,
        target="medium",
        sensor_mm=36.0,
    )

    assert result["target"] == "medium"
    assert result["framing_multiplier"] == 0.6
    assert abs(result["visible_width"] - 60.0) < 0.01

    # The suggested focal length should produce the correct FOV
    fov = focal_length_to_fov(result["focal_mm"], 36.0)
    width = fov_to_frame_width(fov, 50.0)
    assert abs(width - 60.0) < 0.1, f"Roundtrip check: expected 60.0, got {width}"


def test_suggest_camera_close_vs_wide():
    """Close framing should suggest longer focal length than wide."""
    close = suggest_camera(scene_width=100.0, distance=50.0, target="close")
    wide = suggest_camera(scene_width=100.0, distance=50.0, target="wide")

    # Close = less visible width = longer focal length (more telephoto)
    assert close["focal_mm"] > wide["focal_mm"]
    assert close["fov_deg"] < wide["fov_deg"]


def test_suggest_camera_invalid_target():
    """Invalid framing target raises ValueError."""
    with pytest.raises(ValueError, match="Unknown target"):
        suggest_camera(100.0, 50.0, target="extreme_closeup")
