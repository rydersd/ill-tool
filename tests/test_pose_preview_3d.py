"""Tests for the 3D pose preview tool.

Verifies identity transform, 90-degree rotation, and parent-child
composition — all pure Python, no 3D engine required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.pose_preview_3d import (
    joint_angles_to_bone_transforms,
    compose_transforms,
    _identity_4x4,
    _rotation_x,
    _rotation_y,
    _rotation_z,
    _mat_mul_4x4,
    compute_world_transforms,
)


# ---------------------------------------------------------------------------
# Helper to extract position from a 4x4 transform
# ---------------------------------------------------------------------------


def _get_translation(mat: list[float]) -> tuple[float, float, float]:
    """Extract translation (tx, ty, tz) from a 4x4 row-major matrix."""
    return (mat[3], mat[7], mat[11])


def _mat_entry(mat: list[float], row: int, col: int) -> float:
    """Get matrix entry at (row, col) from flat 16-element list."""
    return mat[row * 4 + col]


# ---------------------------------------------------------------------------
# test_identity_transform
# ---------------------------------------------------------------------------


class TestIdentityTransform:
    """Zero angles produce identity rotation."""

    def test_zero_angles_identity(self):
        """Joint with [0,0,0] angles at origin produces identity transform."""
        skeleton = {
            "joints": [
                {"name": "root", "parent": None, "rest_position": [0, 0, 0]},
            ],
        }
        angles = {"root": [0.0, 0.0, 0.0]}

        transforms = joint_angles_to_bone_transforms(angles, skeleton)

        assert "error" not in transforms
        root_t = transforms["root"]

        # Should be identity (within floating-point tolerance)
        identity = _identity_4x4()
        for i in range(16):
            assert root_t[i] == pytest.approx(identity[i], abs=1e-6)

    def test_missing_angles_default_identity(self):
        """Joints not listed in joint_angles default to identity rotation."""
        skeleton = {
            "joints": [
                {"name": "arm", "parent": None, "rest_position": [0, 0, 0]},
            ],
        }
        angles = {}  # No angles specified for 'arm'

        transforms = joint_angles_to_bone_transforms(angles, skeleton)
        arm_t = transforms["arm"]

        identity = _identity_4x4()
        for i in range(16):
            assert arm_t[i] == pytest.approx(identity[i], abs=1e-6)


# ---------------------------------------------------------------------------
# test_90_degree_rotation
# ---------------------------------------------------------------------------


class TestNinetyDegreeRotation:
    """90-degree rotation around each axis."""

    def test_90_deg_x(self):
        """90 degrees around X: Y-axis maps to Z-axis."""
        skeleton = {
            "joints": [
                {"name": "j", "parent": None, "rest_position": [0, 0, 0]},
            ],
        }
        transforms = joint_angles_to_bone_transforms(
            {"j": [90.0, 0.0, 0.0]}, skeleton
        )

        t = transforms["j"]

        # After 90-deg X rotation:
        # (0,1,0) -> (0,0,1)  i.e. m[1][1]=0, m[1][2]=-1, m[2][1]=1, m[2][2]=0
        assert _mat_entry(t, 1, 1) == pytest.approx(0.0, abs=1e-6)
        assert _mat_entry(t, 2, 1) == pytest.approx(1.0, abs=1e-6)

    def test_90_deg_y(self):
        """90 degrees around Y: Z-axis maps to X-axis."""
        skeleton = {
            "joints": [
                {"name": "j", "parent": None, "rest_position": [0, 0, 0]},
            ],
        }
        transforms = joint_angles_to_bone_transforms(
            {"j": [0.0, 90.0, 0.0]}, skeleton
        )

        t = transforms["j"]

        # After 90-deg Y rotation:
        # (0,0,1) -> (1,0,0)  i.e. m[0][0]=cos90=0, m[0][2]=sin90=1
        assert _mat_entry(t, 0, 0) == pytest.approx(0.0, abs=1e-6)
        assert _mat_entry(t, 0, 2) == pytest.approx(1.0, abs=1e-6)

    def test_90_deg_z(self):
        """90 degrees around Z: X-axis maps to Y-axis."""
        skeleton = {
            "joints": [
                {"name": "j", "parent": None, "rest_position": [0, 0, 0]},
            ],
        }
        transforms = joint_angles_to_bone_transforms(
            {"j": [0.0, 0.0, 90.0]}, skeleton
        )

        t = transforms["j"]

        # After 90-deg Z rotation:
        # (1,0,0) -> (0,1,0)  i.e. m[0][0]=0, m[1][0]=1
        assert _mat_entry(t, 0, 0) == pytest.approx(0.0, abs=1e-6)
        assert _mat_entry(t, 1, 0) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# test_parent_child_composition
# ---------------------------------------------------------------------------


class TestParentChildComposition:
    """Hierarchical transform composition."""

    def test_compose_with_identity(self):
        """Composing with identity leaves the transform unchanged."""
        identity = _identity_4x4()
        rot = _rotation_x(45.0)

        result = compose_transforms(identity, rot)
        for i in range(16):
            assert result[i] == pytest.approx(rot[i], abs=1e-5)

        result2 = compose_transforms(rot, identity)
        for i in range(16):
            assert result2[i] == pytest.approx(rot[i], abs=1e-5)

    def test_translations_add(self):
        """Parent translation + child translation = sum."""
        skeleton = {
            "joints": [
                {"name": "parent", "parent": None, "rest_position": [1.0, 2.0, 3.0]},
                {"name": "child", "parent": "parent", "rest_position": [0.5, 0.5, 0.5]},
            ],
        }
        angles = {
            "parent": [0.0, 0.0, 0.0],
            "child": [0.0, 0.0, 0.0],
        }

        local = joint_angles_to_bone_transforms(angles, skeleton)
        world = compute_world_transforms(local, skeleton)

        # Parent world = local (root)
        parent_pos = _get_translation(world["parent"])
        assert parent_pos == pytest.approx((1.0, 2.0, 3.0), abs=1e-5)

        # Child world = parent * child → translations add
        child_pos = _get_translation(world["child"])
        assert child_pos == pytest.approx((1.5, 2.5, 3.5), abs=1e-5)

    def test_three_joint_chain(self):
        """Three-joint chain: root -> spine -> head, translations accumulate."""
        skeleton = {
            "joints": [
                {"name": "root", "parent": None, "rest_position": [0, 0, 0]},
                {"name": "spine", "parent": "root", "rest_position": [0, 1, 0]},
                {"name": "head", "parent": "spine", "rest_position": [0, 0.5, 0]},
            ],
        }
        angles = {
            "root": [0, 0, 0],
            "spine": [0, 0, 0],
            "head": [0, 0, 0],
        }

        local = joint_angles_to_bone_transforms(angles, skeleton)
        world = compute_world_transforms(local, skeleton)

        head_pos = _get_translation(world["head"])
        assert head_pos == pytest.approx((0, 1.5, 0), abs=1e-5)
