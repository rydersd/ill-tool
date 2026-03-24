"""Tests for Meta Animated Drawings bridge tool.

All tests work WITHOUT Docker service running.
Validates mapping function, status check, and connection error handling.
"""

import json
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.animated_drawings_bridge import (
    AD_TO_RIG_MAP,
    RIG_JOINT_NAMES,
    _check_service,
    _process_image,
    map_ad_to_rig,
    AnimatedDrawingsBridgeInput,
)


# ---------------------------------------------------------------------------
# test_map_ad_to_rig: pure Python mapping function
# ---------------------------------------------------------------------------


def test_map_ad_to_rig():
    """map_ad_to_rig correctly maps Animated Drawings joints to our rig schema.

    Pure Python test — no Docker service needed.
    """
    ad_response = {
        "joints": [
            {"name": "root", "x": 100.0, "y": 200.0},
            {"name": "head", "x": 100.0, "y": 50.0},
            {"name": "left_shoulder", "x": 70.0, "y": 100.0},
            {"name": "right_shoulder", "x": 130.0, "y": 100.0},
            {"name": "left_hand", "x": 40.0, "y": 180.0},
            {"name": "unknown_joint", "x": 0.0, "y": 0.0},  # Unmapped
        ],
    }

    result = map_ad_to_rig(ad_response)

    assert "joints" in result
    assert "joint_count" in result
    assert "unmapped" in result
    assert result["schema"] == "rig_v1"

    # Check mapped joints
    assert result["joint_count"] == 5  # root, head, 2 shoulders, left_hand
    joint_names = [j["name"] for j in result["joints"]]
    assert "root" in joint_names
    assert "head" in joint_names
    assert "shoulder_l" in joint_names
    assert "shoulder_r" in joint_names
    assert "hand_l" in joint_names

    # Check unmapped
    assert "unknown_joint" in result["unmapped"]

    # Verify coordinates preserved
    head = next(j for j in result["joints"] if j["name"] == "head")
    assert head["x"] == 100.0
    assert head["y"] == 50.0
    assert head["original_name"] == "head"

    # Test with invalid input
    result_bad = map_ad_to_rig("not a dict")
    assert "error" in result_bad

    result_empty = map_ad_to_rig({"joints": []})
    assert result_empty["joint_count"] == 0


# ---------------------------------------------------------------------------
# test_status_check: service unreachable returns helpful error
# ---------------------------------------------------------------------------


def test_status_check():
    """_check_service when Docker is not running returns reachable=False with hint."""
    # Use a port that definitely won't be running the AD service
    result = _check_service("http://localhost:19999")

    assert "service_url" in result
    assert result["reachable"] is False
    assert "error" in result
    assert "hint" in result
    assert "docker" in result["hint"].lower()
    assert "rig_joint_names" in result
    assert isinstance(result["rig_joint_names"], list)


# ---------------------------------------------------------------------------
# test_connection_error_handling: process with unreachable service
# ---------------------------------------------------------------------------


def test_connection_error_handling():
    """_process_image with nonexistent image returns error."""
    result = _process_image("/nonexistent/path/image.png", "http://localhost:19999")

    assert "error" in result
    assert "not found" in result["error"].lower() or "image" in result["error"].lower()
