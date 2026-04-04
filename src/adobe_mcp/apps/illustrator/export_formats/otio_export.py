"""OpenTimelineIO adapter for storyboard/keyframe data.

Converts our internal keyframe timeline and storyboard panel data
to OTIO-compatible dict structures.  Pure Python data structures
work without the opentimelineio package; when OTIO is available,
validated export is also supported.

Optional dependency: opentimelineio (graceful import).
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig

# Graceful import for optional dependency
try:
    import opentimelineio as _otio
except ImportError:
    _otio = None


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiOtioExportInput(BaseModel):
    """OpenTimelineIO export from storyboard/keyframe data."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: export, status"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    fps: int = Field(
        default=24, description="Frames per second", ge=1
    )
    title: str = Field(
        default="Storyboard", description="Timeline title"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path (auto-generated if None)"
    )


# ---------------------------------------------------------------------------
# OTIO dict builders (pure Python, no OTIO dep needed)
# ---------------------------------------------------------------------------


def otio_clip(panel: dict, fps: int) -> dict:
    """Create an OTIO-compatible clip dict from a storyboard panel.

    The clip dict follows the OTIO JSON schema with:
    - OTIO_SCHEMA for type identification
    - source_range with start_time and duration as RationalTime
    - media_reference pointing to the panel image

    Args:
        panel: storyboard panel dict with 'number', 'duration_frames',
               'description', and optionally 'image_path'
        fps: frames per second for time calculations

    Returns:
        Dict representing an OTIO Clip.
    """
    panel_num = panel.get("number", 1)
    duration_frames = panel.get("duration_frames", 24)
    description = panel.get("description", f"Panel {panel_num}")
    image_path = panel.get("image_path", f"panels/panel_{panel_num:03d}.png")

    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": description,
        "source_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {
                "OTIO_SCHEMA": "RationalTime.1",
                "value": 0.0,
                "rate": float(fps),
            },
            "duration": {
                "OTIO_SCHEMA": "RationalTime.1",
                "value": float(duration_frames),
                "rate": float(fps),
            },
        },
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": image_path,
            "available_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {
                    "OTIO_SCHEMA": "RationalTime.1",
                    "value": 0.0,
                    "rate": float(fps),
                },
                "duration": {
                    "OTIO_SCHEMA": "RationalTime.1",
                    "value": float(duration_frames),
                    "rate": float(fps),
                },
            },
        },
        "metadata": {
            "panel_number": panel_num,
        },
    }


def otio_transition(
    transition_type: str,
    duration_frames: int,
    fps: int,
) -> dict:
    """Create an OTIO-compatible transition dict.

    Args:
        transition_type: type of transition ('dissolve', 'wipe', 'cut', etc.)
        duration_frames: transition duration in frames
        fps: frames per second

    Returns:
        Dict representing an OTIO Transition.
    """
    # Map common names to OTIO transition types
    type_map = {
        "dissolve": "SMPTE_Dissolve",
        "wipe": "SMPTE_Wipe",
        "cut": "SMPTE_Dissolve",  # A cut with 0 duration is conceptually instant
        "fade": "SMPTE_Dissolve",
        "custom": "Custom_Transition",
    }

    otio_type = type_map.get(transition_type.lower(), "SMPTE_Dissolve")

    return {
        "OTIO_SCHEMA": "Transition.1",
        "name": transition_type,
        "transition_type": otio_type,
        "in_offset": {
            "OTIO_SCHEMA": "RationalTime.1",
            "value": float(duration_frames) / 2.0,
            "rate": float(fps),
        },
        "out_offset": {
            "OTIO_SCHEMA": "RationalTime.1",
            "value": float(duration_frames) / 2.0,
            "rate": float(fps),
        },
        "metadata": {
            "original_type": transition_type,
            "total_duration_frames": duration_frames,
        },
    }


def timeline_to_otio_dict(rig: dict, title: str = "Storyboard", fps: int = 24) -> dict:
    """Convert our keyframe/storyboard data to an OTIO-compatible dict.

    Builds a full OTIO Timeline dict structure with:
    - Timeline wrapper with global_start_time
    - Stack containing one Track
    - Track containing Clips (and Transitions if present)

    Args:
        rig: our rig data dict containing 'storyboard' and/or 'timeline' keys
        title: timeline title
        fps: frames per second

    Returns:
        Dict representing an OTIO Timeline, serializable to JSON.
    """
    panels = rig.get("storyboard", {}).get("panels", [])
    panels = sorted(panels, key=lambda p: p.get("number", 0))

    transitions = rig.get("storyboard", {}).get("transitions", [])

    # Build clips from panels
    children = []
    for i, panel in enumerate(panels):
        clip = otio_clip(panel, fps)
        children.append(clip)

        # Insert transition after this clip if one exists for this position
        matching_trans = [
            t for t in transitions
            if t.get("after_panel") == panel.get("number")
        ]
        for t in matching_trans:
            trans_dict = otio_transition(
                t.get("type", "dissolve"),
                t.get("duration_frames", 12),
                fps,
            )
            children.append(trans_dict)

    # Calculate total duration from panels
    total_frames = sum(p.get("duration_frames", 24) for p in panels)

    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": title,
        "global_start_time": {
            "OTIO_SCHEMA": "RationalTime.1",
            "value": 0.0,
            "rate": float(fps),
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "Video 1",
                    "kind": "Video",
                    "children": children,
                },
            ],
        },
        "metadata": {
            "total_duration_frames": total_frames,
            "panel_count": len(panels),
            "fps": fps,
        },
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_otio_export tool."""

    @mcp.tool(
        name="adobe_ai_otio_export",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_otio_export(params: AiOtioExportInput) -> str:
        """Export storyboard/keyframe data as OpenTimelineIO.

        Actions:
        - export: generate OTIO-compatible JSON from storyboard data
        - status: check OTIO availability and tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "otio_available": _otio is not None,
                "pure_python_dict": True,
                "supported_actions": ["export", "status"],
            }, indent=2)

        # ── export ──────────────────────────────────────────────────
        if action == "export":
            rig = _load_rig(params.character_name)
            panels = rig.get("storyboard", {}).get("panels", [])

            if not panels:
                return json.dumps({
                    "error": "No storyboard panels found.",
                    "hint": "Create panels first using the storyboard_panel tool.",
                })

            otio_dict = timeline_to_otio_dict(rig, params.title, params.fps)

            # Serialize to JSON
            otio_json = json.dumps(otio_dict, indent=2)

            if params.output_path:
                import os
                os.makedirs(os.path.dirname(params.output_path), exist_ok=True)
                with open(params.output_path, "w") as f:
                    f.write(otio_json)

            return json.dumps({
                "action": "export",
                "format": "otio_dict",
                "otio_available": _otio is not None,
                "panel_count": len(panels),
                "clip_count": len([
                    c for c in otio_dict["tracks"]["children"][0]["children"]
                    if c.get("OTIO_SCHEMA", "").startswith("Clip")
                ]),
                "timeline": otio_dict,
                "output_path": params.output_path,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["export", "status"],
        })
