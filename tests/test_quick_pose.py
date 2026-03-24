"""Tests for the quick pose tool.

Verifies pose parsing, combination, application to rigs, and
error handling for unknown poses.
All tests are pure Python -- no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.quick_pose import (
    parse_pose_description,
    apply_quick_pose,
    combine_poses,
    list_poses,
    POSE_VOCABULARY,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_known_poses():
    """Each known pose should return the correct joint angles."""
    angles = parse_pose_description("arms_raised")
    assert angles["shoulder_l"] == 150.0
    assert angles["shoulder_r"] == 150.0

    angles = parse_pose_description("sitting")
    assert angles["hip_l"] == 90.0
    assert angles["knee_l"] == 90.0
    assert angles["hip_r"] == 90.0
    assert angles["knee_r"] == 90.0

    angles = parse_pose_description("looking_left")
    assert angles["neck"] == -30.0


def test_combine_two_poses_later_overrides():
    """Combining poses should merge angles, later overriding earlier."""
    # arms_raised sets shoulder_r=150, waving also sets shoulder_r=150 + elbow_r=-45
    merged = combine_poses(["standing", "waving"])

    # standing sets hip_l=0, hip_r=0, knee_l=0, knee_r=0
    assert merged["hip_l"] == 0.0
    assert merged["hip_r"] == 0.0
    # waving adds shoulder_r=150, elbow_r=-45
    assert merged["shoulder_r"] == 150.0
    assert merged["elbow_r"] == -45.0

    # Test override: sitting then standing should result in standing values
    merged2 = combine_poses(["sitting", "standing"])
    assert merged2["hip_l"] == 0.0  # standing overrides sitting
    assert merged2["knee_l"] == 0.0


def test_unknown_pose_raises_error():
    """Requesting an unknown pose should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown pose"):
        parse_pose_description("breakdancing_on_ceiling")


def test_apply_quick_pose_sets_joint_values():
    """apply_quick_pose should set rotation values on rig joints."""
    rig = {"joints": {}, "character_name": "test"}
    result = apply_quick_pose(rig, "crouching")

    assert result["pose"] == "crouching"
    assert result["joints_updated"] > 0
    # Verify joint rotations were set
    assert rig["joints"]["hip_l"]["rotation"] == 60.0
    assert rig["joints"]["knee_l"]["rotation"] == 120.0
    assert rig["joints"]["hip_r"]["rotation"] == 60.0
    assert rig["joints"]["knee_r"]["rotation"] == 120.0


def test_compound_pose_description():
    """Compound poses with + separator should merge angles."""
    angles = parse_pose_description("arms_raised+looking_left")
    assert angles["shoulder_l"] == 150.0
    assert angles["shoulder_r"] == 150.0
    assert angles["neck"] == -30.0
