"""Tests for SDPose landmark ML detection tool.

All tests work WITHOUT ML dependencies (torch, transformers) installed.
Validates graceful fallback, pure Python mapping, and input validation.
"""

import json
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.landmark_ml import (
    ML_AVAILABLE,
    LANDMARK_NAMES,
    SDPOSE_TO_LANDMARK,
    _ml_status,
    _detect_landmarks,
    map_sdpose_to_landmarks,
    LandmarkMLInput,
)


# ---------------------------------------------------------------------------
# test_status_check: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status_check():
    """_ml_status returns correct structure with ML availability info."""
    status = _ml_status()

    assert "ml_available" in status
    assert "model" in status
    assert "keypoint_count" in status
    assert status["keypoint_count"] == 133
    assert "mapped_landmarks" in status
    assert "landmark_names" in status
    assert isinstance(status["landmark_names"], list)

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert "uv pip install" in status["install_hint"]
        assert status["gpu_device"] == "unavailable"
    else:
        assert status["ml_available"] is True
        assert status["gpu_device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_map_sdpose_to_landmarks: pure Python mapping function
# ---------------------------------------------------------------------------


def test_map_sdpose_to_landmarks():
    """map_sdpose_to_landmarks correctly maps keypoint indices to landmark names.

    This is a pure Python test — no ML dependencies needed.
    """
    # Build a fake 133-keypoint array with known values
    keypoints = [[0.0, 0.0, 0.0]] * 133

    # Set specific keypoints with high confidence
    keypoints[0] = [100.0, 50.0, 0.95]    # nose
    keypoints[5] = [80.0, 120.0, 0.88]    # shoulder_l
    keypoints[6] = [120.0, 120.0, 0.85]   # shoulder_r
    keypoints[11] = [85.0, 200.0, 0.70]   # hip_l
    keypoints[12] = [115.0, 200.0, 0.10]  # hip_r — below threshold

    result = map_sdpose_to_landmarks(keypoints, confidence_threshold=0.3)

    # Nose should be mapped
    assert "nose" in result
    assert result["nose"]["x"] == 100.0
    assert result["nose"]["y"] == 50.0
    assert result["nose"]["confidence"] == 0.95

    # Shoulders should be mapped
    assert "shoulder_l" in result
    assert "shoulder_r" in result

    # hip_l passes threshold, hip_r does not
    assert "hip_l" in result
    assert "hip_r" not in result  # confidence 0.10 < 0.30

    # Zero-confidence keypoints should be filtered out
    assert "eye_l" not in result  # was set to [0, 0, 0]


# ---------------------------------------------------------------------------
# test_graceful_fallback: detect without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_detect_landmarks without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.landmark_ml.ML_AVAILABLE", False):
        result = _detect_landmarks("/tmp/test.png", 0.3)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result


# ---------------------------------------------------------------------------
# test_input_validation: bad image path returns error
# ---------------------------------------------------------------------------


def test_input_validation():
    """_detect_landmarks with nonexistent image returns error."""
    # Force ML_AVAILABLE=True so we hit the file-check path
    with patch("adobe_mcp.apps.illustrator.landmark_ml.ML_AVAILABLE", True):
        result = _detect_landmarks("/nonexistent/path/fake.png", 0.3)

    assert "error" in result
    assert "not found" in result["error"].lower() or "image" in result["error"].lower()


# ---------------------------------------------------------------------------
# test_keypoint_schema: SDPOSE_TO_LANDMARK and LANDMARK_NAMES are consistent
# ---------------------------------------------------------------------------


def test_keypoint_schema():
    """SDPOSE_TO_LANDMARK mapping and LANDMARK_NAMES are consistent and complete."""
    # All mapped names should be in LANDMARK_NAMES
    for idx, name in SDPOSE_TO_LANDMARK.items():
        assert name in LANDMARK_NAMES, f"Mapped name '{name}' not in LANDMARK_NAMES"

    # LANDMARK_NAMES should be sorted (for deterministic output)
    assert LANDMARK_NAMES == sorted(LANDMARK_NAMES)

    # All keypoint indices should be valid (0-132 for COCO-WholeBody)
    for idx in SDPOSE_TO_LANDMARK.keys():
        assert 0 <= idx <= 132, f"Invalid keypoint index: {idx}"

    # Input model has correct defaults
    model = LandmarkMLInput()
    assert model.action == "status"
    assert model.confidence_threshold == 0.3
