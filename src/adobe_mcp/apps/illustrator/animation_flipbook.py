"""Preview pose sequence by creating artboards per frame.

Creates a flipbook-style preview where each artboard shows the character
in a different pose. Artboards are laid out horizontally with configurable
spacing, allowing manual flipping in Illustrator for animation review.

Pure Python implementation -- generates artboard specs and pose data.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.quick_pose import apply_quick_pose, POSE_VOCABULARY


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiAnimationFlipbookInput(BaseModel):
    """Create a flipbook of artboards showing pose sequence."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: create_flipbook, flipbook_info",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    pose_names: Optional[list[str]] = Field(
        default=None,
        description="List of pose names for each frame",
    )
    spacing: float = Field(
        default=50.0,
        description="Horizontal spacing between artboards in points",
        ge=0.0,
    )
    artboard_width: float = Field(
        default=300.0,
        description="Width of each artboard in points",
        gt=0.0,
    )
    artboard_height: float = Field(
        default=400.0,
        description="Height of each artboard in points",
        gt=0.0,
    )


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def create_flipbook(
    rig: dict,
    pose_names: list[str],
    spacing: float = 50.0,
    artboard_width: float = 300.0,
    artboard_height: float = 400.0,
) -> dict:
    """Create a flipbook with one artboard per pose.

    For each pose in the list:
        1. Creates an artboard at the next horizontal position
        2. Records the pose angles for that frame
        3. Tracks artboard bounds for navigation

    The flipbook data is stored in the rig under "flipbook" key.

    Args:
        rig: character rig dict
        pose_names: ordered list of pose names from POSE_VOCABULARY
        spacing: horizontal gap between artboards in points
        artboard_width: width of each artboard
        artboard_height: height of each artboard

    Returns:
        Dict with artboard list, total width, and frame count.
    """
    if not pose_names:
        return {"error": "pose_names list is required and must not be empty"}

    artboards = []
    x_offset = 0.0

    for i, pose_name in enumerate(pose_names):
        # Compute artboard bounds
        artboard_rect = [
            round(x_offset, 2),
            0.0,
            round(x_offset + artboard_width, 2),
            artboard_height,
        ]

        # Resolve pose angles
        try:
            from adobe_mcp.apps.illustrator.quick_pose import parse_pose_description
            angles = parse_pose_description(pose_name)
        except ValueError:
            angles = {}

        artboard = {
            "index": i,
            "pose_name": pose_name,
            "artboard_rect": artboard_rect,
            "angles": angles,
            "x_offset": round(x_offset, 2),
        }
        artboards.append(artboard)

        # Advance to next artboard position
        x_offset += artboard_width + spacing

    # Store flipbook data in rig
    rig["flipbook"] = {
        "artboards": artboards,
        "frame_count": len(artboards),
        "total_width": round(x_offset - spacing, 2),
        "artboard_size": [artboard_width, artboard_height],
        "spacing": spacing,
    }

    return {
        "frame_count": len(artboards),
        "artboards": artboards,
        "total_width": round(x_offset - spacing, 2),
        "artboard_size": [artboard_width, artboard_height],
        "spacing": spacing,
    }


def flipbook_info(rig: dict) -> dict:
    """List current flipbook artboards for a rig.

    Args:
        rig: character rig dict

    Returns:
        Dict with flipbook artboard data, or empty if no flipbook exists.
    """
    flipbook = rig.get("flipbook")
    if not flipbook:
        return {
            "has_flipbook": False,
            "frame_count": 0,
            "artboards": [],
        }

    return {
        "has_flipbook": True,
        "frame_count": flipbook.get("frame_count", 0),
        "artboards": flipbook.get("artboards", []),
        "total_width": flipbook.get("total_width", 0),
        "artboard_size": flipbook.get("artboard_size", [300, 400]),
        "spacing": flipbook.get("spacing", 50),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_animation_flipbook tool."""

    @mcp.tool(
        name="adobe_ai_animation_flipbook",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_animation_flipbook(params: AiAnimationFlipbookInput) -> str:
        """Create a flipbook preview of pose sequences.

        Actions:
        - create_flipbook: create artboards for each pose frame
        - flipbook_info: list current flipbook artboards
        """
        action = params.action.lower().strip()
        rig = _load_rig(params.character_name)

        if action == "create_flipbook":
            if not params.pose_names:
                return json.dumps({"error": "create_flipbook requires pose_names"})
            result = create_flipbook(
                rig,
                params.pose_names,
                spacing=params.spacing,
                artboard_width=params.artboard_width,
                artboard_height=params.artboard_height,
            )
            _save_rig(params.character_name, rig)
            return json.dumps(result)

        elif action == "flipbook_info":
            result = flipbook_info(rig)
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
