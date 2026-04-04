"""Real-time 3D pose testing — joint angle to bone transform math.

Converts joint angles to bone rotation matrices and composes them
hierarchically (parent * child) for skeletal animation preview.

Pure Python — no JSX, no 3D engine required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiPosePreview3dInput(BaseModel):
    """Real-time 3D pose preview from joint angles."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: preview_pose, status",
    )
    joint_angles: Optional[dict[str, list[float]]] = Field(
        default=None,
        description=(
            "Joint angles in degrees: {'joint_name': [rx, ry, rz], ...}. "
            "Rotation order is X-Y-Z (Euler angles)."
        ),
    )
    skeleton: Optional[dict] = Field(
        default=None,
        description=(
            "Skeleton definition: {'joints': [{'name': str, 'parent': str|None, "
            "'rest_position': [x,y,z]}, ...]}"
        ),
    )
    character_name: str = Field(
        default="character",
        description="Character identifier",
    )


# ---------------------------------------------------------------------------
# 4x4 matrix helpers (row-major, stored as flat list of 16 floats)
# ---------------------------------------------------------------------------

# A transform is a 4x4 matrix stored as a list of 16 floats in row-major order.
# [ m00, m01, m02, m03,
#   m10, m11, m12, m13,
#   m20, m21, m22, m23,
#   m30, m31, m32, m33 ]


def _identity_4x4() -> list[float]:
    """Return a 4x4 identity matrix as a flat 16-element list."""
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _rotation_x(angle_deg: float) -> list[float]:
    """4x4 rotation matrix around the X axis."""
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0,   c,  -s, 0.0,
        0.0,   s,   c, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _rotation_y(angle_deg: float) -> list[float]:
    """4x4 rotation matrix around the Y axis."""
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return [
          c, 0.0,   s, 0.0,
        0.0, 1.0, 0.0, 0.0,
         -s, 0.0,   c, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _rotation_z(angle_deg: float) -> list[float]:
    """4x4 rotation matrix around the Z axis."""
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return [
          c,  -s, 0.0, 0.0,
          s,   c, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _mat_mul_4x4(a: list[float], b: list[float]) -> list[float]:
    """Multiply two 4x4 matrices (row-major flat lists)."""
    result = [0.0] * 16
    for row in range(4):
        for col in range(4):
            s = 0.0
            for k in range(4):
                s += a[row * 4 + k] * b[k * 4 + col]
            result[row * 4 + col] = s
    return result


def _mat_round(m: list[float], decimals: int = 6) -> list[float]:
    """Round all elements of a matrix."""
    return [round(v, decimals) for v in m]


def _translation_4x4(tx: float, ty: float, tz: float) -> list[float]:
    """4x4 translation matrix."""
    return [
        1.0, 0.0, 0.0, tx,
        0.0, 1.0, 0.0, ty,
        0.0, 0.0, 1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def joint_angles_to_bone_transforms(
    joint_angles: dict[str, list[float]],
    skeleton: dict,
) -> dict:
    """Convert joint angles (Euler XYZ degrees) to bone rotation matrices.

    For each joint in the skeleton, looks up its angles in joint_angles
    and computes the local rotation matrix (Rx * Ry * Rz). If no angles
    are specified for a joint, it gets the identity transform.

    Args:
        joint_angles: mapping of joint name to [rx, ry, rz] degrees.
        skeleton: skeleton definition with 'joints' list.

    Returns:
        dict mapping joint names to their local 4x4 transform matrices.
    """
    if not skeleton or "joints" not in skeleton:
        return {"error": "Skeleton must have a 'joints' list"}

    transforms = {}

    for joint in skeleton["joints"]:
        name = joint.get("name", "")
        if not name:
            continue

        angles = joint_angles.get(name, [0.0, 0.0, 0.0])
        rx = angles[0] if len(angles) > 0 else 0.0
        ry = angles[1] if len(angles) > 1 else 0.0
        rz = angles[2] if len(angles) > 2 else 0.0

        # Build rotation: Rx * Ry * Rz
        rot = _mat_mul_4x4(_rotation_x(rx), _rotation_y(ry))
        rot = _mat_mul_4x4(rot, _rotation_z(rz))

        # Add rest position as translation
        rest_pos = joint.get("rest_position", [0.0, 0.0, 0.0])
        tx, ty, tz = (
            rest_pos[0] if len(rest_pos) > 0 else 0.0,
            rest_pos[1] if len(rest_pos) > 1 else 0.0,
            rest_pos[2] if len(rest_pos) > 2 else 0.0,
        )
        trans = _translation_4x4(tx, ty, tz)

        # Local transform = Translation * Rotation
        local_transform = _mat_mul_4x4(trans, rot)
        transforms[name] = _mat_round(local_transform)

    return transforms


def compose_transforms(
    parent_transform: list[float],
    local_transform: list[float],
) -> list[float]:
    """Compose parent and local transforms via matrix multiplication.

    In skeletal animation, the world transform of a bone is:
        world = parent_world * local

    Args:
        parent_transform: 4x4 parent world transform (flat list of 16).
        local_transform: 4x4 local bone transform (flat list of 16).

    Returns:
        4x4 composed world transform (flat list of 16).
    """
    if len(parent_transform) != 16 or len(local_transform) != 16:
        return _identity_4x4()

    return _mat_round(_mat_mul_4x4(parent_transform, local_transform))


def compute_world_transforms(
    local_transforms: dict[str, list[float]],
    skeleton: dict,
) -> dict[str, list[float]]:
    """Compute world transforms for all joints by walking the hierarchy.

    Args:
        local_transforms: joint name → local 4x4 transform.
        skeleton: skeleton with 'joints' list (each has 'name' and 'parent').

    Returns:
        dict mapping joint names to world 4x4 transforms.
    """
    # Build parent lookup
    parent_map = {}
    for joint in skeleton.get("joints", []):
        name = joint.get("name", "")
        parent = joint.get("parent", None)
        parent_map[name] = parent

    world_transforms = {}

    # Process joints in dependency order (roots first)
    processed = set()

    def _process(name: str) -> list[float]:
        if name in world_transforms:
            return world_transforms[name]

        parent = parent_map.get(name)
        local = local_transforms.get(name, _identity_4x4())

        if parent and parent in local_transforms:
            parent_world = _process(parent)
            world = compose_transforms(parent_world, local)
        else:
            world = local

        world_transforms[name] = world
        processed.add(name)
        return world

    for joint in skeleton.get("joints", []):
        name = joint.get("name", "")
        if name and name not in processed:
            _process(name)

    return world_transforms


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_pose_preview_3d tool."""

    @mcp.tool(
        name="adobe_ai_pose_preview_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_pose_preview_3d(params: AiPosePreview3dInput) -> str:
        """Real-time 3D pose preview from joint angles.

        Actions:
        - preview_pose: compute bone transforms from joint angles
        - status: show configuration and readiness
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "pose_preview_3d",
                "rotation_order": "XYZ (Euler)",
                "matrix_format": "4x4 row-major (16 floats)",
                "ready": True,
            }, indent=2)

        elif action == "preview_pose":
            if not params.joint_angles or not params.skeleton:
                return json.dumps({
                    "error": "Both joint_angles and skeleton are required",
                })

            local_transforms = joint_angles_to_bone_transforms(
                params.joint_angles,
                params.skeleton,
            )

            if "error" in local_transforms:
                return json.dumps(local_transforms)

            world_transforms = compute_world_transforms(
                local_transforms,
                params.skeleton,
            )

            return json.dumps({
                "action": "preview_pose",
                "character_name": params.character_name,
                "joint_count": len(local_transforms),
                "local_transforms": local_transforms,
                "world_transforms": world_transforms,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["preview_pose", "status"],
            })
