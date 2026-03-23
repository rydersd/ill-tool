"""Tests for the rig controllers system.

Tests rig data manipulation (controller list storage, position mapping)
and helper functions without requiring Adobe Illustrator.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.rig_controllers import (
    _controller_name,
    _build_controller_list,
    _map_controllers_to_joints,
)
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _controller_name
# ---------------------------------------------------------------------------


def test_controller_name_format():
    """Controller names follow the ctrl_{joint_name} convention."""
    assert _controller_name("shoulder_l") == "ctrl_shoulder_l"
    assert _controller_name("head") == "ctrl_head"
    assert _controller_name("hip") == "ctrl_hip"


# ---------------------------------------------------------------------------
# _build_controller_list
# ---------------------------------------------------------------------------


def test_build_controller_list_basic():
    """Build controller list from joints dict."""
    joints = {
        "head": {"x": 0, "y": -50},
        "shoulder_l": {"x": -60, "y": -120},
    }
    controllers = _build_controller_list(joints, "circle", 12)

    assert len(controllers) == 2
    names = {c["name"] for c in controllers}
    assert "ctrl_head" in names
    assert "ctrl_shoulder_l" in names

    for c in controllers:
        assert c["style"] == "circle"
        assert c["size"] == 12
        assert "x" in c
        assert "y" in c
        assert "joint_name" in c


def test_build_controller_list_positions_match_joints():
    """Controller positions match their corresponding joint positions."""
    joints = {
        "elbow_r": {"x": 150, "y": -200},
    }
    controllers = _build_controller_list(joints, "diamond", 8)

    ctrl = controllers[0]
    assert ctrl["x"] == 150
    assert ctrl["y"] == -200
    assert ctrl["joint_name"] == "elbow_r"


def test_build_controller_list_empty_joints():
    """Empty joints dict produces empty controller list."""
    assert _build_controller_list({}, "square", 10) == []


def test_build_controller_list_styles():
    """Different styles are passed through to controller descriptors."""
    joints = {"test": {"x": 0, "y": 0}}
    for style in ("circle", "diamond", "square", "arrow"):
        controllers = _build_controller_list(joints, style, 10)
        assert controllers[0]["style"] == style


# ---------------------------------------------------------------------------
# _map_controllers_to_joints
# ---------------------------------------------------------------------------


def test_map_controllers_basic():
    """Update action maps controller positions back to joint positions."""
    rig = {
        "joints": {
            "head": {"x": 0, "y": -50},
            "shoulder_l": {"x": -60, "y": -120},
        },
    }

    # Simulate user dragging controllers to new positions
    controller_positions = {
        "ctrl_head": {"x": 10, "y": -55},
        "ctrl_shoulder_l": {"x": -65, "y": -130},
    }

    updated = _map_controllers_to_joints(controller_positions, rig)

    # Verify joints were updated
    assert rig["joints"]["head"] == {"x": 10, "y": -55}
    assert rig["joints"]["shoulder_l"] == {"x": -65, "y": -130}

    # Verify return value lists updated joints
    assert "head" in updated
    assert "shoulder_l" in updated
    assert updated["head"] == {"x": 10, "y": -55}


def test_map_controllers_unknown_joint_ignored():
    """Controllers for unknown joints are silently ignored."""
    rig = {
        "joints": {
            "head": {"x": 0, "y": 0},
        },
    }
    controller_positions = {
        "ctrl_head": {"x": 5, "y": 5},
        "ctrl_nonexistent": {"x": 99, "y": 99},
    }

    updated = _map_controllers_to_joints(controller_positions, rig)

    assert "head" in updated
    assert "nonexistent" not in updated
    assert "nonexistent" not in rig["joints"]


def test_map_controllers_preserves_other_joints():
    """Mapping controllers only updates joints that have controllers."""
    rig = {
        "joints": {
            "head": {"x": 0, "y": 0},
            "hip": {"x": 0, "y": -300},
        },
    }

    # Only update head
    controller_positions = {
        "ctrl_head": {"x": 10, "y": -10},
    }

    _map_controllers_to_joints(controller_positions, rig)

    assert rig["joints"]["head"] == {"x": 10, "y": -10}
    assert rig["joints"]["hip"] == {"x": 0, "y": -300}  # unchanged


# ---------------------------------------------------------------------------
# Rig persistence of controllers
# ---------------------------------------------------------------------------


def test_save_controllers_in_rig(tmp_rig_dir):
    """Controllers list is persisted in the rig file."""
    rig = _load_rig("hero")
    rig["joints"] = {
        "head": {"x": 0, "y": -50},
        "hip": {"x": 0, "y": -200},
    }

    controllers = _build_controller_list(rig["joints"], "circle", 12)
    rig["controllers"] = [c["name"] for c in controllers]
    _save_rig("hero", rig)

    loaded = _load_rig("hero")
    assert "controllers" in loaded
    assert "ctrl_head" in loaded["controllers"]
    assert "ctrl_hip" in loaded["controllers"]
    assert len(loaded["controllers"]) == 2


def test_clear_controllers_from_rig(tmp_rig_dir):
    """Clearing controllers removes the key from the rig."""
    rig = _load_rig("hero")
    rig["controllers"] = ["ctrl_head", "ctrl_hip"]
    _save_rig("hero", rig)

    loaded = _load_rig("hero")
    loaded.pop("controllers", None)
    _save_rig("hero", loaded)

    final = _load_rig("hero")
    assert "controllers" not in final


def test_update_roundtrip(tmp_rig_dir):
    """Full roundtrip: create controllers, update positions, verify joints."""
    rig = _load_rig("test_char")
    rig["joints"] = {
        "shoulder_l": {"x": -60, "y": -120},
        "elbow_l": {"x": -90, "y": -200},
    }
    controllers = _build_controller_list(rig["joints"], "diamond", 10)
    rig["controllers"] = [c["name"] for c in controllers]
    _save_rig("test_char", rig)

    # Simulate position update (user dragged elbow)
    loaded = _load_rig("test_char")
    new_positions = {
        "ctrl_shoulder_l": {"x": -60, "y": -120},  # unchanged
        "ctrl_elbow_l": {"x": -100, "y": -210},     # moved
    }
    updated = _map_controllers_to_joints(new_positions, loaded)
    _save_rig("test_char", loaded)

    # Verify
    final = _load_rig("test_char")
    assert final["joints"]["shoulder_l"] == {"x": -60, "y": -120}
    assert final["joints"]["elbow_l"] == {"x": -100, "y": -210}
    assert "elbow_l" in updated
