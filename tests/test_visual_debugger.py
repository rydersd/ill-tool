"""Tests for the visual debugger JSX generator.

Verifies JSX generation for known landmarks, mode filtering, and
clear logic. All tests are pure Python -- no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.visual_debugger import (
    generate_debug_overlay,
    clear_debug,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_rig():
    """A minimal rig with joints, landmarks, axes, and bones."""
    return {
        "character_name": "test_debug",
        "joints": {
            "hip": {"position": [100, 200]},
            "knee": {"position": [100, 300]},
            "head": {"position": [100, 50]},
        },
        "landmarks": {
            "shoulder_l": {
                "position": [60, 100],
                "pivot": {"type": "ball", "rotation_range": [-180, 180]},
            },
            "shoulder_r": {
                "position": [140, 100],
                "pivot": {"type": "ball", "rotation_range": [-180, 180]},
            },
        },
        "axes": {
            "spine": {"origin": [100, 100], "direction": [0, -1]},
        },
        "bones": [
            {"parent_joint": "hip", "child_joint": "knee", "name": "thigh"},
            {"parent_joint": "head", "child_joint": "hip", "name": "torso_bone"},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_overlay_all_mode(sample_rig):
    """mode='all' should include landmarks, axes, pivots, and hierarchy."""
    jsx = generate_debug_overlay(sample_rig, mode="all")

    # Should have the Debug layer header
    assert 'debugLayer' in jsx
    assert '"Debug"' in jsx

    # Should include landmarks (joints and landmark entries)
    assert "debug_landmark_hip" in jsx
    assert "debug_landmark_shoulder_l" in jsx

    # Should include axes
    assert "debug_axis_spine" in jsx

    # Should include pivots
    assert "debug_pivot_shoulder_l" in jsx

    # Should include hierarchy lines
    assert "debug_hierarchy_hip_to_knee" in jsx


def test_generate_overlay_landmarks_only(sample_rig):
    """mode='landmarks' should only include landmark markers."""
    jsx = generate_debug_overlay(sample_rig, mode="landmarks")

    assert "debug_landmark_hip" in jsx
    assert "debug_landmark_shoulder_l" in jsx
    # Should NOT include axis, pivot diamond, or hierarchy lines
    assert "debug_axis_spine" not in jsx
    assert "debug_pivot_" not in jsx
    assert "debug_hierarchy_" not in jsx


def test_generate_overlay_hierarchy_only(sample_rig):
    """mode='hierarchy' should only include parent-child lines."""
    jsx = generate_debug_overlay(sample_rig, mode="hierarchy")

    assert "debug_hierarchy_hip_to_knee" in jsx
    assert "debug_hierarchy_head_to_hip" in jsx
    # Should NOT include landmarks or pivots
    assert "debug_landmark_" not in jsx
    assert "debug_pivot_" not in jsx
    assert "debug_axis_spine" not in jsx


def test_clear_debug_generates_remove_jsx(sample_rig):
    """clear_debug should generate JSX to remove the Debug layer."""
    jsx = clear_debug(sample_rig)

    assert "Debug" in jsx
    assert "remove()" in jsx


def test_generate_overlay_empty_rig():
    """Empty rig should produce valid JSX with just the header."""
    empty_rig = {
        "character_name": "empty",
        "joints": {},
        "landmarks": {},
        "axes": {},
        "bones": [],
    }
    jsx = generate_debug_overlay(empty_rig, mode="all")

    # Should still have the Debug layer setup
    assert 'debugLayer' in jsx
    assert '"Debug"' in jsx
