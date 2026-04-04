"""Quick pose application from structured descriptions.

Maps human-readable pose names (like "arms_raised", "sitting") to
joint angle sets, then applies them to character rigs. Multiple poses
can be combined, with later overrides taking precedence.

Pure Python implementation.
"""

import copy
import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiQuickPoseInput(BaseModel):
    """Apply a named pose to a character rig."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: apply_pose, parse_pose, combine_poses, list_poses",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    pose_name: Optional[str] = Field(
        default=None,
        description="Name of the pose to apply (from vocabulary)",
    )
    pose_names: Optional[list[str]] = Field(
        default=None,
        description="List of pose names to combine",
    )


# ---------------------------------------------------------------------------
# Pose vocabulary: maps pose names to joint angle sets
# ---------------------------------------------------------------------------

POSE_VOCABULARY: dict[str, dict[str, float]] = {
    "arms_raised": {"shoulder_l": 150.0, "shoulder_r": 150.0},
    "arms_down": {"shoulder_l": 0.0, "shoulder_r": 0.0},
    "looking_left": {"neck": -30.0},
    "looking_right": {"neck": 30.0},
    "sitting": {"hip_l": 90.0, "hip_r": 90.0, "knee_l": 90.0, "knee_r": 90.0},
    "standing": {"hip_l": 0.0, "hip_r": 0.0, "knee_l": 0.0, "knee_r": 0.0},
    "walking": {"hip_l": 30.0, "hip_r": -15.0, "knee_l": -15.0, "knee_r": 30.0},
    "running": {"hip_l": 45.0, "hip_r": -30.0, "knee_l": -30.0, "knee_r": 60.0},
    "jumping": {"hip_l": -30.0, "hip_r": -30.0, "knee_l": -60.0, "knee_r": -60.0},
    "crouching": {"hip_l": 60.0, "knee_l": 120.0, "hip_r": 60.0, "knee_r": 120.0},
    "waving": {"shoulder_r": 150.0, "elbow_r": -45.0},
    "pointing": {"shoulder_r": 90.0, "elbow_r": 0.0, "wrist_r": 0.0},
}


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def parse_pose_description(description: str) -> dict:
    """Parse a structured pose description into joint angles.

    Looks up the description in the POSE_VOCABULARY and returns the
    corresponding joint angle set. Supports compound descriptions
    separated by '+' (e.g. "arms_raised+looking_left").

    Args:
        description: pose name or compound pose description

    Returns:
        Dict mapping joint names to angle values (degrees).

    Raises:
        ValueError: if pose name not found in vocabulary.
    """
    # Handle compound descriptions
    parts = [p.strip() for p in description.split("+")]
    result: dict[str, float] = {}

    for part in parts:
        if part not in POSE_VOCABULARY:
            raise ValueError(
                f"Unknown pose: '{part}'. Available: {sorted(POSE_VOCABULARY.keys())}"
            )
        result.update(POSE_VOCABULARY[part])

    return result


def apply_quick_pose(rig: dict, pose_name: str) -> dict:
    """Look up a pose and apply its angles to rig joints.

    Sets the joint rotation values in the rig to match the pose.
    Creates joints if they don't exist yet.

    Args:
        rig: character rig dict
        pose_name: name from POSE_VOCABULARY

    Returns:
        Dict with applied angles and joints updated.

    Raises:
        ValueError: if pose_name not in vocabulary.
    """
    angles = parse_pose_description(pose_name)

    if "joints" not in rig:
        rig["joints"] = {}

    applied = {}
    for joint_name, angle in angles.items():
        if joint_name not in rig["joints"]:
            rig["joints"][joint_name] = {"position": [0, 0]}
        rig["joints"][joint_name]["rotation"] = angle
        applied[joint_name] = angle

    # Store the pose name as current
    rig["current_pose"] = pose_name

    return {
        "pose": pose_name,
        "joints_updated": len(applied),
        "angles": applied,
    }


def combine_poses(pose_names: list[str]) -> dict:
    """Merge multiple pose descriptions, later overrides earlier.

    When two poses set the same joint, the later pose's value wins.

    Args:
        pose_names: ordered list of pose names to combine

    Returns:
        Merged joint angle dict.

    Raises:
        ValueError: if any pose name not found in vocabulary.
    """
    if not pose_names:
        return {}

    merged: dict[str, float] = {}
    for name in pose_names:
        angles = parse_pose_description(name)
        merged.update(angles)

    return merged


def list_poses() -> dict:
    """Return all available poses and their joint angle definitions.

    Returns:
        Dict mapping pose names to their joint angle sets.
    """
    return {
        "poses": {name: dict(angles) for name, angles in POSE_VOCABULARY.items()},
        "count": len(POSE_VOCABULARY),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_quick_pose tool."""

    @mcp.tool(
        name="adobe_ai_quick_pose",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_quick_pose(params: AiQuickPoseInput) -> str:
        """Apply named poses to character rigs.

        Actions:
        - apply_pose: look up and apply a pose to a rig
        - parse_pose: parse a pose name into joint angles
        - combine_poses: merge multiple poses (later overrides earlier)
        - list_poses: show available poses
        """
        action = params.action.lower().strip()

        if action == "apply_pose":
            if not params.pose_name:
                return json.dumps({"error": "apply_pose requires pose_name"})
            rig = _load_rig(params.character_name)
            try:
                result = apply_quick_pose(rig, params.pose_name)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            _save_rig(params.character_name, rig)
            return json.dumps(result)

        elif action == "parse_pose":
            if not params.pose_name:
                return json.dumps({"error": "parse_pose requires pose_name"})
            try:
                angles = parse_pose_description(params.pose_name)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps({"pose": params.pose_name, "angles": angles})

        elif action == "combine_poses":
            if not params.pose_names:
                return json.dumps({"error": "combine_poses requires pose_names list"})
            try:
                merged = combine_poses(params.pose_names)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps({"combined": merged, "source_poses": params.pose_names})

        elif action == "list_poses":
            return json.dumps(list_poses())

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
