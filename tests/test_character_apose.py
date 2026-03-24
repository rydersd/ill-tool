"""Tests for CharacterGen A-pose canonicalization tool.

All tests work WITHOUT ML dependencies (torch, transformers) installed.
Validates graceful fallback, A-pose checking, and status.
"""

import json
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.character_apose import (
    ML_AVAILABLE,
    APOSE_TARGET_ANGLES,
    _ml_status,
    _canonicalize,
    is_apose,
    CharacterAPoseInput,
)


# ---------------------------------------------------------------------------
# test_is_apose: pure Python A-pose angle checking
# ---------------------------------------------------------------------------


def test_is_apose():
    """is_apose correctly validates joint angles against A-pose targets.

    Pure Python test — no ML dependencies needed.
    """
    # Perfect A-pose: all angles match targets exactly
    perfect_angles = dict(APOSE_TARGET_ANGLES)
    result = is_apose(perfect_angles, tolerance_degrees=15.0)
    assert result["is_apose"] is True
    assert result["score"] == 1.0
    assert result["joints_passing"] == result["joints_checked"]

    # Near A-pose: angles within tolerance
    near_angles = {k: v + 5.0 for k, v in APOSE_TARGET_ANGLES.items()}
    result = is_apose(near_angles, tolerance_degrees=15.0)
    assert result["is_apose"] is True
    assert result["score"] >= 0.8

    # Not A-pose: arms straight down (0 degrees instead of 45)
    bad_angles = {
        "shoulder_to_elbow_l": 0.0,  # Should be 45
        "shoulder_to_elbow_r": 0.0,  # Should be -45
        "elbow_to_wrist_l": 0.0,    # Should be 45
        "elbow_to_wrist_r": 0.0,    # Should be -45
        "hip_to_knee_l": 0.0,       # Correct
        "hip_to_knee_r": 0.0,       # Correct
    }
    result = is_apose(bad_angles, tolerance_degrees=15.0)
    assert result["is_apose"] is False
    assert result["score"] < 0.8

    # Check deviations are reported correctly
    assert "deviations" in result
    shoulder_dev = result["deviations"]["shoulder_to_elbow_l"]
    assert shoulder_dev["actual"] == 0.0
    assert shoulder_dev["target"] == 45.0
    assert shoulder_dev["deviation"] == 45.0
    assert shoulder_dev["within_tolerance"] is False

    # Empty angles
    result = is_apose({}, tolerance_degrees=15.0)
    assert result["is_apose"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with A-pose target info."""
    status = _ml_status()

    assert "ml_available" in status
    assert "tool" in status
    assert "target_pose" in status
    assert "apose_targets" in status
    assert "45" in status["target_pose"]  # Mentions 45 degrees

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_graceful_fallback: canonicalize without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_canonicalize without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.character_apose.ML_AVAILABLE", False):
        result = _canonicalize("/tmp/test.png", None, 15.0)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
