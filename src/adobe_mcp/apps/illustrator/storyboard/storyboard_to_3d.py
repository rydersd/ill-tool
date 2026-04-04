"""Storyboard panels to 3D scene description.

Converts storyboard panel camera framing and character positions
into a 3D scene description with camera positions, focal lengths,
and object placements in world space.

Pure Python — no JSX, no 3D engine required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiStoryboardTo3dInput(BaseModel):
    """Convert storyboard panels to 3D scene descriptions."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: convert, status",
    )
    panel_data: Optional[dict] = Field(
        default=None,
        description=(
            "Panel data with camera type, characters, and positions. "
            "Keys: camera, characters (list), description."
        ),
    )
    characters: Optional[list[dict]] = Field(
        default=None,
        description="Character data: [{name, position_x, position_y, scale}, ...]",
    )
    reference_height: float = Field(
        default=1.8,
        description="Reference character height in 3D units (default 1.8m)",
    )
    panel_width: float = Field(
        default=1920.0,
        description="Panel width in pixels (for position mapping)",
    )
    panel_height: float = Field(
        default=1080.0,
        description="Panel height in pixels (for position mapping)",
    )


# ---------------------------------------------------------------------------
# Camera presets — maps shot type to 3D camera parameters
# ---------------------------------------------------------------------------

CAMERA_PRESETS = {
    "extreme_wide": {"distance": 30.0, "focal_length": 16.0, "height": 3.0},
    "wide": {"distance": 15.0, "focal_length": 24.0, "height": 2.0},
    "medium_wide": {"distance": 10.0, "focal_length": 35.0, "height": 1.6},
    "medium": {"distance": 6.0, "focal_length": 50.0, "height": 1.5},
    "medium_close": {"distance": 4.0, "focal_length": 65.0, "height": 1.5},
    "close": {"distance": 2.5, "focal_length": 85.0, "height": 1.5},
    "extreme_close": {"distance": 1.5, "focal_length": 105.0, "height": 1.5},
    "overhead": {"distance": 12.0, "focal_length": 35.0, "height": 12.0},
    "low_angle": {"distance": 6.0, "focal_length": 35.0, "height": 0.3},
    "high_angle": {"distance": 8.0, "focal_length": 50.0, "height": 4.0},
}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def estimate_depth_from_scale(
    character_scale: float,
    reference_height: float = 1.8,
) -> float:
    """Estimate depth (distance from camera) based on character scale.

    Larger scale means the character appears bigger in frame, so they
    are closer to the camera. Uses an inverse relationship:
    depth proportional to 1/scale.

    Args:
        character_scale: relative scale in the panel (1.0 = normal).
        reference_height: character height in 3D units.

    Returns:
        Estimated depth distance from camera in 3D units.
    """
    # Clamp scale to avoid division by zero
    scale = max(0.01, character_scale)

    # Base depth: at scale 1.0, character is at a "medium shot" distance
    base_depth = 6.0

    # Depth is inversely proportional to scale
    depth = base_depth / scale

    return round(depth, 3)


def panel_to_3d_scene(
    panel_data: dict,
    characters: Optional[list[dict]] = None,
    reference_height: float = 1.8,
    panel_width: float = 1920.0,
    panel_height: float = 1080.0,
) -> dict:
    """Convert panel camera + character positions to a 3D scene description.

    Maps:
    - Camera shot type to 3D camera position, focal length, and look-at
    - Character panel positions (pixel coords) to 3D world positions
    - Panel description to scene metadata

    Args:
        panel_data: dict with 'camera' (shot type), 'description', etc.
        characters: list of character dicts with position and scale info.
        reference_height: character height in 3D units.
        panel_width: panel pixel width for coordinate mapping.
        panel_height: panel pixel height for coordinate mapping.

    Returns:
        Scene dict with cameras, objects, and environment sections.
    """
    if not panel_data or not isinstance(panel_data, dict):
        return {"error": "panel_data is required and must be a dict"}

    # ── Camera setup ──────────────────────────────────────────────
    camera_type = panel_data.get("camera", "medium").lower().replace(" ", "_")
    preset = CAMERA_PRESETS.get(camera_type, CAMERA_PRESETS["medium"])

    camera_distance = preset["distance"]
    focal_length = preset["focal_length"]
    camera_height = preset["height"]

    # Camera angle adjustments
    camera_angle = panel_data.get("camera_angle", "eye_level").lower()
    if camera_angle == "low_angle":
        camera_height = 0.3
    elif camera_angle == "high_angle":
        camera_height = camera_distance * 0.5
    elif camera_angle == "overhead":
        camera_height = camera_distance

    # Camera position: looking down -Z axis, positioned along +Z
    camera_3d = {
        "position": [0.0, round(camera_height, 3), round(camera_distance, 3)],
        "look_at": [0.0, round(reference_height * 0.5, 3), 0.0],
        "focal_length_mm": focal_length,
        "shot_type": camera_type,
    }

    # ── Character placement ───────────────────────────────────────
    objects_3d = []
    chars = characters or panel_data.get("characters", [])

    for i, char in enumerate(chars):
        if not isinstance(char, dict):
            continue

        char_name = char.get("name", f"character_{i}")

        # Panel position (pixels) → normalized → 3D world
        px = char.get("position_x", char.get("x", panel_width / 2))
        py = char.get("position_y", char.get("y", panel_height / 2))
        scale = char.get("scale", 1.0)

        # Normalize pixel coordinates to [-1, 1] range
        norm_x = (px / panel_width) * 2.0 - 1.0
        norm_y = (py / panel_height) * 2.0 - 1.0

        # Map to 3D: X spreads characters left-right, Z is depth from scale
        depth = estimate_depth_from_scale(scale, reference_height)
        world_x = norm_x * camera_distance * 0.5  # Spread proportional to camera distance
        world_y = 0.0  # Characters stand on ground plane
        world_z = -depth + camera_distance  # Relative to camera

        objects_3d.append({
            "name": char_name,
            "type": "character",
            "position": [round(world_x, 3), round(world_y, 3), round(world_z, 3)],
            "height": round(reference_height * scale, 3),
            "scale": scale,
            "estimated_depth": round(depth, 3),
            "facing": char.get("facing", "camera"),
        })

    # ── Environment ───────────────────────────────────────────────
    environment = {
        "ground_plane": True,
        "ground_y": 0.0,
        "description": panel_data.get("description", ""),
        "lighting": panel_data.get("lighting", "default"),
    }

    return {
        "camera": camera_3d,
        "objects": objects_3d,
        "environment": environment,
        "object_count": len(objects_3d),
        "source_panel": {
            "camera_type": camera_type,
            "description": panel_data.get("description", ""),
        },
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_storyboard_to_3d tool."""

    @mcp.tool(
        name="adobe_ai_storyboard_to_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_storyboard_to_3d(params: AiStoryboardTo3dInput) -> str:
        """Convert storyboard panels to 3D scene descriptions.

        Actions:
        - convert: transform panel data to 3D scene
        - status: show available camera presets and configuration
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "storyboard_to_3d",
                "camera_presets": sorted(CAMERA_PRESETS.keys()),
                "reference_height": params.reference_height,
                "ready": True,
            }, indent=2)

        elif action == "convert":
            if not params.panel_data:
                return json.dumps({"error": "panel_data is required for convert"})

            scene = panel_to_3d_scene(
                panel_data=params.panel_data,
                characters=params.characters,
                reference_height=params.reference_height,
                panel_width=params.panel_width,
                panel_height=params.panel_height,
            )
            scene["action"] = "convert"
            return json.dumps(scene, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["convert", "status"],
            })
