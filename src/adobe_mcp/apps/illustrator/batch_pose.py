"""Pose a character across multiple panels with interpolated variations.

Given two named poses and a range of panels, compute an interpolated
pose for each panel and apply it.  The result is a smooth progression
from pose_a to pose_b across the panel range.

Uses pose_interpolate math under the hood.
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.pose_interpolate import (
    _interpolate_joints,
    _interpolate_path_states,
)


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiBatchPoseInput(BaseModel):
    """Pose a character across multiple panels with interpolation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="batch_pose", description="Action: batch_pose")
    character_name: str = Field(default="character", description="Character identifier")
    pose_a: str = Field(..., description="Starting pose name")
    pose_b: str = Field(..., description="Ending pose name")
    panel_range: str = Field(
        ...,
        description="JSON array of panel numbers e.g. [3,4,5,6,7]",
    )


# ---------------------------------------------------------------------------
# Interpolation t-value computation (pure Python)
# ---------------------------------------------------------------------------


def compute_panel_t_values(panel_range: list[int]) -> list[dict]:
    """Compute the interpolation t-value for each panel.

    t = 0.0 for the first panel, 1.0 for the last.
    Single-panel ranges get t = 0.0.

    Parameters
    ----------
    panel_range : list of int
        Sequential panel numbers.

    Returns
    -------
    list of {panel, t}
    """
    n = len(panel_range)
    if n == 0:
        return []
    if n == 1:
        return [{"panel": panel_range[0], "t": 0.0}]

    result = []
    for i, panel in enumerate(panel_range):
        t = i / (n - 1)
        result.append({"panel": panel, "t": round(t, 6)})
    return result


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_batch_pose tool."""

    @mcp.tool(
        name="adobe_ai_batch_pose",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_batch_pose(params: AiBatchPoseInput) -> str:
        """Pose a character across multiple panels with interpolated variations.

        Computes interpolated poses between pose_a and pose_b for each
        panel in the range, creating smooth progression across panels.
        """
        if params.action.lower().strip() != "batch_pose":
            return json.dumps({
                "error": f"Unknown action: {params.action}",
                "valid_actions": ["batch_pose"],
            })

        # Parse panel range
        try:
            panel_range = json.loads(params.panel_range)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid panel_range JSON: {e}"})

        if not isinstance(panel_range, list) or not all(isinstance(p, int) for p in panel_range):
            return json.dumps({"error": "panel_range must be a JSON array of integers"})

        if len(panel_range) == 0:
            return json.dumps({"error": "panel_range must contain at least one panel"})

        rig = _load_rig(params.character_name)
        poses = rig.get("poses", {})

        # Validate both poses exist
        missing = []
        if params.pose_a not in poses:
            missing.append(params.pose_a)
        if params.pose_b not in poses:
            missing.append(params.pose_b)
        if missing:
            return json.dumps({
                "error": f"Pose(s) not found: {missing}",
                "available_poses": list(poses.keys()),
            })

        pose_a = poses[params.pose_a]
        pose_b = poses[params.pose_b]

        # Compute t-values for each panel
        panel_ts = compute_panel_t_values(panel_range)

        # Compute interpolated poses for each panel
        panel_poses = []
        for pt in panel_ts:
            t = pt["t"]
            panel_num = pt["panel"]

            joints_a = pose_a.get("joints", {})
            joints_b = pose_b.get("joints", {})
            interp_joints = _interpolate_joints(joints_a, joints_b, t)

            states_a = pose_a.get("path_states", {})
            states_b = pose_b.get("path_states", {})
            interp_states = _interpolate_path_states(states_a, states_b, t)

            panel_poses.append({
                "panel": panel_num,
                "t": pt["t"],
                "joint_count": len(interp_joints),
                "path_count": len(interp_states),
            })

            # Store panel-pose association in rig
            rig.setdefault("panel_poses", {})
            rig["panel_poses"][str(panel_num)] = {
                "pose_a": params.pose_a,
                "pose_b": params.pose_b,
                "t": pt["t"],
                "joints": interp_joints,
                "path_states": interp_states,
            }

        _save_rig(params.character_name, rig)

        return json.dumps({
            "action": "batch_pose",
            "character_name": params.character_name,
            "pose_a": params.pose_a,
            "pose_b": params.pose_b,
            "panel_count": len(panel_poses),
            "panels": panel_poses,
        })
