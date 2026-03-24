"""Sketch2Anim bridge — parse storyboard panels for animation generation.

Extracts action descriptions and character positions from storyboard panel
data, then validates the animation output from the Sketch2Anim service.

Pure Python — no JSX or Adobe required.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiSketch2AnimBridgeInput(BaseModel):
    """Sketch2Anim bridge for animation generation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, generate_animation",
    )
    panels: Optional[list[dict]] = Field(
        default=None,
        description="Storyboard panels to parse for animation data",
    )
    animation_output: Optional[dict] = Field(
        default=None,
        description="Raw Sketch2Anim output to validate",
    )
    fps: int = Field(
        default=24,
        description="Target frames per second for animation",
    )


# ---------------------------------------------------------------------------
# Required fields for valid animation output
# ---------------------------------------------------------------------------

REQUIRED_ANIMATION_FIELDS = {
    "frames",       # list of frame data
    "duration",     # total duration in seconds or frames
    "resolution",   # output resolution (width, height)
}

REQUIRED_FRAME_FIELDS = {
    "index",        # frame number
    "timestamp",    # time in seconds
}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def parse_storyboard_for_animation(panels: list[dict]) -> dict:
    """Extract action descriptions and character positions from panel data.

    For each panel, extracts:
    - Action description (from description, action, or notes fields)
    - Character positions (from characters or positions fields)
    - Camera information (shot type, angle)
    - Timing information (duration)

    Args:
        panels: list of storyboard panel dicts.

    Returns:
        dict with parsed animation data: actions, characters, timing.
    """
    if not panels or not isinstance(panels, list):
        return {"error": "panels must be a non-empty list", "parsed": []}

    parsed_panels = []
    total_duration_frames = 0
    all_characters = set()

    for i, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue

        panel_num = panel.get("number", i + 1)

        # Extract action description from multiple possible fields
        action_desc = (
            panel.get("action")
            or panel.get("description")
            or panel.get("notes")
            or ""
        )

        # Extract character positions
        characters = panel.get("characters", [])
        if not isinstance(characters, list):
            characters = []

        char_positions = []
        for char in characters:
            if isinstance(char, dict):
                char_name = char.get("name", char.get("id", f"char_{len(char_positions)}"))
                all_characters.add(char_name)
                char_positions.append({
                    "name": char_name,
                    "position": char.get("position", [0, 0]),
                    "scale": char.get("scale", 1.0),
                    "facing": char.get("facing", "front"),
                    "action": char.get("action", ""),
                })
            elif isinstance(char, str):
                all_characters.add(char)
                char_positions.append({
                    "name": char,
                    "position": [0, 0],
                    "scale": 1.0,
                    "facing": "front",
                    "action": "",
                })

        # Extract camera info
        camera = panel.get("camera", panel.get("shot_type", "medium"))
        camera_angle = panel.get("camera_angle", panel.get("angle", "eye_level"))

        # Extract timing
        duration_frames = panel.get("duration_frames", 24)
        total_duration_frames += duration_frames

        parsed_panels.append({
            "panel_number": panel_num,
            "action_description": action_desc,
            "characters": char_positions,
            "camera": camera,
            "camera_angle": camera_angle,
            "duration_frames": duration_frames,
            "character_count": len(char_positions),
        })

    return {
        "panel_count": len(parsed_panels),
        "total_duration_frames": total_duration_frames,
        "unique_characters": sorted(all_characters),
        "panels": parsed_panels,
    }


def validate_animation_output(output: dict) -> dict:
    """Check that animation data has all required fields.

    Validates:
    1. Top-level required fields exist
    2. Frames list is non-empty
    3. Each frame has required per-frame fields
    4. Duration is positive

    Args:
        output: animation data dict to validate.

    Returns:
        dict with ``valid: True`` on success, or ``valid: False`` with
        ``errors`` list describing what's missing.
    """
    if not output or not isinstance(output, dict):
        return {"valid": False, "errors": ["Output is empty or not a dict"]}

    errors = []

    # Check top-level required fields
    missing_top = REQUIRED_ANIMATION_FIELDS - set(output.keys())
    if missing_top:
        errors.append(f"Missing top-level fields: {sorted(missing_top)}")

    # Validate frames
    frames = output.get("frames")
    if frames is None:
        errors.append("'frames' field is missing")
    elif not isinstance(frames, list):
        errors.append("'frames' must be a list")
    elif len(frames) == 0:
        errors.append("'frames' list is empty")
    else:
        # Check first frame for required fields
        for fi, frame in enumerate(frames[:5]):  # Check up to first 5 frames
            if not isinstance(frame, dict):
                errors.append(f"Frame {fi} is not a dict")
                continue
            missing_frame = REQUIRED_FRAME_FIELDS - set(frame.keys())
            if missing_frame:
                errors.append(f"Frame {fi} missing fields: {sorted(missing_frame)}")

    # Validate duration
    duration = output.get("duration")
    if duration is not None:
        if not isinstance(duration, (int, float)):
            errors.append("'duration' must be a number")
        elif duration <= 0:
            errors.append(f"'duration' must be positive, got {duration}")

    # Validate resolution
    resolution = output.get("resolution")
    if resolution is not None:
        if not isinstance(resolution, (list, tuple)) or len(resolution) < 2:
            errors.append("'resolution' must be [width, height]")

    if errors:
        return {"valid": False, "errors": errors, "error_count": len(errors)}

    return {
        "valid": True,
        "frame_count": len(frames),
        "duration": duration,
        "resolution": list(resolution) if resolution else None,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_sketch2anim_bridge tool."""

    @mcp.tool(
        name="adobe_ai_sketch2anim_bridge",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def adobe_ai_sketch2anim_bridge(params: AiSketch2AnimBridgeInput) -> str:
        """Bridge to Sketch2Anim for animation generation from storyboards.

        Actions:
        - status: check bridge readiness
        - generate_animation: parse panels and validate animation output
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "sketch2anim_bridge",
                "required_animation_fields": sorted(REQUIRED_ANIMATION_FIELDS),
                "default_fps": params.fps,
                "ready": True,
            }, indent=2)

        elif action == "generate_animation":
            result = {"action": "generate_animation", "fps": params.fps}

            # Parse panels if provided
            if params.panels:
                parsed = parse_storyboard_for_animation(params.panels)
                result["parsed_storyboard"] = parsed
            else:
                result["parsed_storyboard"] = None

            # Validate animation output if provided
            if params.animation_output:
                validation = validate_animation_output(params.animation_output)
                result["output_validation"] = validation

            if not params.panels and not params.animation_output:
                result["error"] = "Provide panels and/or animation_output"

            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "generate_animation"],
            })
