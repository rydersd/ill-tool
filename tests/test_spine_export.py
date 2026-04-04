"""Tests for the Spine skeleton export tool.

Verifies skeleton structure, bone hierarchy, and animation mapping.
All tests are pure Python — no Spine runtime required.
"""

import pytest

from adobe_mcp.apps.illustrator.export_formats.spine_export import (
    rig_to_spine_skeleton,
    spine_bone,
)


# ---------------------------------------------------------------------------
# Bone creation
# ---------------------------------------------------------------------------


def test_spine_bone_structure():
    """Spine bone dict should have all required fields."""
    bone = spine_bone("femur", parent="hip", x=10.0, y=-50.0, rotation=45.0, length=80.0)

    assert bone["name"] == "femur"
    assert bone["parent"] == "hip"
    assert bone["x"] == 10.0
    assert bone["y"] == -50.0
    assert bone["rotation"] == 45.0
    assert bone["length"] == 80.0


def test_spine_bone_root_no_parent():
    """Root bone should not have a parent key."""
    bone = spine_bone("root")

    assert bone["name"] == "root"
    assert "parent" not in bone


# ---------------------------------------------------------------------------
# Full skeleton conversion
# ---------------------------------------------------------------------------


def test_skeleton_bone_hierarchy():
    """Skeleton should maintain parent-child bone relationships."""
    rig = {
        "character_name": "test_char",
        "joints": {
            "hip": {
                "position": [200, 300],
                "parent": "root",
            },
            "knee": {
                "position": [200, 450],
                "parent": "hip",
            },
            "ankle": {
                "position": [200, 580],
                "parent": "knee",
            },
        },
        "bindings": {},
        "poses": {},
    }

    skeleton = rig_to_spine_skeleton(rig)

    bones = skeleton["bones"]
    bone_names = [b["name"] for b in bones]

    # Root should be first
    assert bone_names[0] == "root"
    # All joints should be present as bones
    assert "hip" in bone_names
    assert "knee" in bone_names
    assert "ankle" in bone_names

    # Check parent relationships are preserved
    bone_map = {b["name"]: b for b in bones}
    assert bone_map["hip"]["parent"] == "root"
    assert bone_map["knee"]["parent"] == "hip"
    assert bone_map["ankle"]["parent"] == "knee"


def test_skeleton_animation_mapping():
    """Poses should map to Spine animations with bone rotate timelines."""
    rig = {
        "character_name": "test_char",
        "joints": {
            "shoulder": {
                "position": [100, 200],
                "parent": "root",
            },
            "elbow": {
                "position": [150, 300],
                "parent": "shoulder",
            },
        },
        "bindings": {},
        "poses": {
            "wave": {
                "joint_rotations": {
                    "shoulder": 30.0,
                    "elbow": -45.0,
                },
            },
        },
    }

    skeleton = rig_to_spine_skeleton(rig)

    # Check animations
    animations = skeleton["animations"]
    assert "wave" in animations

    wave_anim = animations["wave"]
    assert "bones" in wave_anim

    # Shoulder should have rotate keyframes
    shoulder_timeline = wave_anim["bones"]["shoulder"]
    assert "rotate" in shoulder_timeline
    rotates = shoulder_timeline["rotate"]
    assert len(rotates) == 2
    assert rotates[0]["time"] == 0
    assert rotates[1]["angle"] == 30.0

    # Elbow should have rotate keyframes
    elbow_timeline = wave_anim["bones"]["elbow"]
    assert elbow_timeline["rotate"][1]["angle"] == -45.0


def test_skeleton_slots_from_bindings():
    """Bindings should map to Spine slots with attachments."""
    rig = {
        "character_name": "test_char",
        "joints": {
            "hip": {"position": [200, 300], "parent": "root"},
        },
        "bindings": {
            "torso_art": "hip",
            "leg_art": {"joint": "hip"},
        },
        "poses": {},
    }

    skeleton = rig_to_spine_skeleton(rig)

    slots = skeleton["slots"]
    slot_names = [s["name"] for s in slots]
    assert "torso_art" in slot_names
    assert "leg_art" in slot_names

    # Check that skin attachments were created
    skins = skeleton["skins"]
    assert "default" in skins
    assert "torso_art" in skins["default"]
    assert "leg_art" in skins["default"]
