"""Compose a storyboard panel with character + pose + camera in one call.

Orchestrates rig loading, pose application, and camera framing to produce
a complete panel composition specification. Supports wide, medium, close-up,
and extreme close-up camera types.

Pure Python orchestrator.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.quick_pose import apply_quick_pose, POSE_VOCABULARY


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiPanelComposerInput(BaseModel):
    """Compose a storyboard panel with character + pose + camera."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="compose",
        description="Action: compose, camera_frame",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    pose_name: Optional[str] = Field(
        default=None,
        description="Pose name to apply (from quick_pose vocabulary)",
    )
    camera_type: str = Field(
        default="wide",
        description="Camera type: wide, medium, close_up, extreme_close",
    )
    panel_number: int = Field(
        default=1,
        description="Panel number in the storyboard sequence",
        ge=1,
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional text description for the panel",
    )
    # For standalone camera_frame action
    character_bounds: Optional[list[float]] = Field(
        default=None,
        description="Character bounding box [x, y, width, height] for camera_frame action",
    )


# ---------------------------------------------------------------------------
# Camera framing helpers
# ---------------------------------------------------------------------------

# Camera types and their visible region specs
_CAMERA_SPECS = {
    "wide": {"top_pct": 0.0, "height_pct": 1.0, "margin": 0.20},
    "medium": {"top_pct": 0.0, "height_pct": 0.60, "margin": 0.10},
    "close_up": {"top_pct": 0.0, "height_pct": 0.30, "margin": 0.05},
    "extreme_close": {"top_pct": 0.0, "height_pct": 0.15, "margin": 0.02},
}


def camera_frame(character_bounds: list[float], camera_type: str) -> dict:
    """Compute the visible camera rectangle for a given framing.

    Camera types:
        - wide: full character bounds + 20% margin
        - medium: top 60% of bounds (waist up)
        - close_up: top 30% of bounds (head + shoulders)
        - extreme_close: top 15% of bounds (face only)

    Args:
        character_bounds: [x, y, width, height] of the character
        camera_type: one of wide, medium, close_up, extreme_close

    Returns:
        Dict with camera_rect [x, y, w, h] and camera_type.
    """
    if len(character_bounds) < 4:
        return {"error": "character_bounds must have [x, y, width, height]"}

    x, y, w, h = character_bounds[:4]

    spec = _CAMERA_SPECS.get(camera_type, _CAMERA_SPECS["wide"])
    margin = spec["margin"]
    height_pct = spec["height_pct"]

    # Compute the visible region (always from the top of the character)
    visible_h = h * height_pct
    visible_y = y  # Start from top

    # Add margin around the visible region
    margin_x = w * margin
    margin_y = visible_h * margin

    camera_rect = [
        round(x - margin_x, 2),
        round(visible_y - margin_y, 2),
        round(w + 2 * margin_x, 2),
        round(visible_h + 2 * margin_y, 2),
    ]

    return {
        "camera_type": camera_type,
        "camera_rect": camera_rect,
        "character_bounds": character_bounds,
        "visible_height_pct": height_pct,
    }


# ---------------------------------------------------------------------------
# Composition orchestrator
# ---------------------------------------------------------------------------


def _estimate_character_bounds(rig: dict) -> list[float]:
    """Estimate character bounding box from rig joint positions.

    Falls back to a default 200x400 bounds if no joint data exists.
    """
    joints = rig.get("joints", {})
    if not joints:
        return [0.0, 0.0, 200.0, 400.0]

    xs = []
    ys = []
    for joint_data in joints.values():
        pos = joint_data.get("position", [0, 0])
        if len(pos) >= 2:
            xs.append(pos[0])
            ys.append(pos[1])

    if not xs or not ys:
        return [0.0, 0.0, 200.0, 400.0]

    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)

    # Ensure minimum size
    w = max(max_x - min_x, 50.0)
    h = max(max_y - min_y, 100.0)

    return [min_x, min_y, w, h]


def compose_panel(
    character_name: str,
    pose_name: Optional[str] = None,
    camera_type: str = "wide",
    panel_number: int = 1,
    description: Optional[str] = None,
) -> dict:
    """Compose a full storyboard panel specification.

    Steps:
        1. Load the character rig
        2. Apply the specified pose (if given)
        3. Estimate character bounds from rig data
        4. Compute camera framing based on camera_type
        5. Return the complete composition spec

    Args:
        character_name: character rig identifier
        pose_name: optional pose from quick_pose vocabulary
        camera_type: wide, medium, close_up, or extreme_close
        panel_number: panel sequence number
        description: optional text annotation

    Returns:
        Composition spec with character_bounds, camera_rect, pose info.
    """
    rig = _load_rig(character_name)

    # Apply pose if specified
    pose_result = None
    if pose_name:
        try:
            pose_result = apply_quick_pose(rig, pose_name)
            _save_rig(character_name, rig)
        except ValueError as exc:
            return {"error": str(exc)}

    # Estimate character bounds from rig data
    char_bounds = _estimate_character_bounds(rig)

    # Compute camera framing
    cam = camera_frame(char_bounds, camera_type)

    return {
        "panel_number": panel_number,
        "character_name": character_name,
        "character_bounds": char_bounds,
        "camera_rect": cam.get("camera_rect", []),
        "camera_type": camera_type,
        "pose_applied": pose_result,
        "description": description,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_panel_composer tool."""

    @mcp.tool(
        name="adobe_ai_panel_composer",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_panel_composer(params: AiPanelComposerInput) -> str:
        """Compose a storyboard panel with character + pose + camera.

        Actions:
        - compose: full panel composition (rig + pose + camera)
        - camera_frame: compute camera framing from bounds
        """
        action = params.action.lower().strip()

        if action == "compose":
            result = compose_panel(
                character_name=params.character_name,
                pose_name=params.pose_name,
                camera_type=params.camera_type,
                panel_number=params.panel_number,
                description=params.description,
            )
            return json.dumps(result)

        elif action == "camera_frame":
            if not params.character_bounds:
                return json.dumps({"error": "camera_frame requires character_bounds"})
            result = camera_frame(params.character_bounds, params.camera_type)
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
