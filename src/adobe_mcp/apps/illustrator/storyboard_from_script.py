"""Parse a beat sheet / scene list and auto-generate panel layout.

Converts a simple script format into structured scene and panel data,
with timing estimates for animatic production. Supports camera tags,
dialogue detection, and automatic frame duration assignment.

Pure Python implementation.
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiStoryboardFromScriptInput(BaseModel):
    """Parse a script into storyboard panel layout."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: parse_script, generate_specs, count_panels",
    )
    text: Optional[str] = Field(
        default=None,
        description="Script text to parse",
    )
    parsed_script: Optional[list[dict]] = Field(
        default=None,
        description="Previously parsed script data (for generate_specs)",
    )
    fps: int = Field(
        default=24,
        description="Frames per second for timing calculations",
        ge=1,
    )


# ---------------------------------------------------------------------------
# Frame duration constants
# ---------------------------------------------------------------------------

# Duration assignments (in frames at 24fps)
DURATION_ACTION = 24       # 1 second for action panels
DURATION_DIALOGUE = 48     # 2 seconds per dialogue line
DURATION_ESTABLISHING = 72  # 3 seconds for establishing shots


# ---------------------------------------------------------------------------
# Script parser
# ---------------------------------------------------------------------------

# Regex patterns for script parsing
_SCENE_HEADER = re.compile(
    r"^SCENE\s+(\d+)\s*:\s*(.*?)$",
    re.IGNORECASE,
)
_PANEL_LINE = re.compile(
    r"^\s*-\s*(.*?)(?:\[(\w+)\])?\s*$",
)
_DIALOGUE = re.compile(
    r'([A-Z][A-Z\s]*?):\s*["\u201c](.*?)["\u201d]',
)


def parse_script(text: str) -> list[dict]:
    """Parse a simple script format into structured scene/panel data.

    Expected format:
        SCENE 1: INT. KITCHEN - DAY
        - GIR stands on table [wide]
        - GIR: "I'm gonna sing the doom song!" [medium]
        - Close on GIR's face, eyes glowing [close_up]

        SCENE 2: EXT. YARD - NIGHT
        - Wide establishing shot [wide]

    Camera tags in square brackets are optional; defaults to "wide".

    Args:
        text: raw script text

    Returns:
        List of scene dicts, each with scene number, location, and panels.
    """
    if not text or not text.strip():
        return []

    scenes = []
    current_scene = None

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for scene header
        scene_match = _SCENE_HEADER.match(line)
        if scene_match:
            if current_scene:
                scenes.append(current_scene)
            current_scene = {
                "scene": int(scene_match.group(1)),
                "location": scene_match.group(2).strip(),
                "panels": [],
            }
            continue

        # Check for panel line (starts with -)
        panel_match = _PANEL_LINE.match(line)
        if panel_match and current_scene is not None:
            description = panel_match.group(1).strip()
            camera = panel_match.group(2)

            # Clean up camera tag from description if it was captured inline
            if camera:
                camera = camera.strip().lower()
                # Remove the camera tag from description text
                description = re.sub(r'\s*\[' + re.escape(camera) + r'\]\s*', '', description, flags=re.IGNORECASE).strip()
            else:
                camera = "wide"  # default

            # Detect dialogue
            dialogue_match = _DIALOGUE.search(description)
            character = None
            dialogue = None
            if dialogue_match:
                character = dialogue_match.group(1).strip()
                dialogue = dialogue_match.group(2).strip()

            panel = {
                "description": description,
                "camera": camera,
                "dialogue": dialogue,
                "character": character,
            }
            current_scene["panels"].append(panel)

    # Don't forget the last scene
    if current_scene:
        scenes.append(current_scene)

    return scenes


# ---------------------------------------------------------------------------
# Panel spec generator
# ---------------------------------------------------------------------------


def _is_establishing(panel: dict) -> bool:
    """Check if a panel is an establishing shot."""
    desc = panel.get("description", "").lower()
    camera = panel.get("camera", "").lower()
    return (
        "establishing" in desc
        or "wide establishing" in desc
        or (camera == "wide" and ("ext." in desc.lower() or "exterior" in desc.lower()))
    )


def generate_panel_specs(parsed_script: list[dict], fps: int = 24) -> list[dict]:
    """Convert parsed script to panel specs with timing estimates.

    Duration rules:
        - Establishing shots: 72 frames (3 seconds at 24fps)
        - Dialogue panels: 48 frames per line (2 seconds)
        - Action panels: 24 frames (1 second)

    Args:
        parsed_script: output from parse_script()
        fps: frames per second for timing

    Returns:
        List of panel spec dicts with timing, scene info, and sequence number.
    """
    specs = []
    panel_seq = 0

    for scene in parsed_script:
        scene_num = scene.get("scene", 0)
        location = scene.get("location", "")

        for panel in scene.get("panels", []):
            panel_seq += 1

            # Determine duration
            if _is_establishing(panel):
                duration_frames = DURATION_ESTABLISHING
                panel_type = "establishing"
            elif panel.get("dialogue"):
                duration_frames = DURATION_DIALOGUE
                panel_type = "dialogue"
            else:
                duration_frames = DURATION_ACTION
                panel_type = "action"

            # Scale duration if fps differs from 24
            scale = fps / 24.0
            scaled_frames = round(duration_frames * scale)

            spec = {
                "panel_number": panel_seq,
                "scene": scene_num,
                "location": location,
                "description": panel.get("description", ""),
                "camera": panel.get("camera", "wide"),
                "dialogue": panel.get("dialogue"),
                "character": panel.get("character"),
                "panel_type": panel_type,
                "duration_frames": scaled_frames,
                "duration_seconds": round(scaled_frames / fps, 2),
            }
            specs.append(spec)

    return specs


def count_panels(script: str) -> dict:
    """Count total panels across all scenes in a script.

    Useful for selecting the right storyboard template size.

    Args:
        script: raw script text

    Returns:
        Dict with total panel count and per-scene breakdown.
    """
    parsed = parse_script(script)
    per_scene = []
    total = 0

    for scene in parsed:
        count = len(scene.get("panels", []))
        per_scene.append({
            "scene": scene.get("scene", 0),
            "location": scene.get("location", ""),
            "panels": count,
        })
        total += count

    return {
        "total_panels": total,
        "scenes": len(parsed),
        "per_scene": per_scene,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_storyboard_from_script tool."""

    @mcp.tool(
        name="adobe_ai_storyboard_from_script",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_storyboard_from_script(params: AiStoryboardFromScriptInput) -> str:
        """Parse a script into storyboard panel layout with timing.

        Actions:
        - parse_script: parse raw script text into scenes and panels
        - generate_specs: convert parsed script to panel specs with timing
        - count_panels: count total panels for template selection
        """
        action = params.action.lower().strip()

        if action == "parse_script":
            if not params.text:
                return json.dumps({"error": "parse_script requires text"})
            result = parse_script(params.text)
            return json.dumps({"scenes": result, "total_panels": sum(len(s["panels"]) for s in result)})

        elif action == "generate_specs":
            if not params.parsed_script:
                if params.text:
                    parsed = parse_script(params.text)
                else:
                    return json.dumps({"error": "generate_specs requires parsed_script or text"})
            else:
                parsed = params.parsed_script
            specs = generate_panel_specs(parsed, fps=params.fps)
            total_frames = sum(s["duration_frames"] for s in specs)
            return json.dumps({
                "panels": specs,
                "total_panels": len(specs),
                "total_frames": total_frames,
                "total_seconds": round(total_frames / params.fps, 2),
            })

        elif action == "count_panels":
            if not params.text:
                return json.dumps({"error": "count_panels requires text"})
            result = count_panels(params.text)
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
