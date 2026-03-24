"""EDL / FCP XML export for storyboard timelines.

Generates CMX3600 Edit Decision List or Final Cut Pro XML from
the keyframe timeline and storyboard panel data.  Each panel maps
to one event with source IN/OUT and record IN/OUT timecodes.

Pure Python -- generates text files, no JSX.
"""

import json
import math
import os
import xml.etree.ElementTree as ET
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiEdlExportInput(BaseModel):
    """Export storyboard timing as EDL or FCP XML."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: export_edl, export_fcpxml"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path (auto-generated if None)"
    )
    title: str = Field(
        default="Storyboard", description="Project / sequence title"
    )
    fps: Optional[int] = Field(
        default=None, description="Frames per second (overrides timeline setting)"
    )


# ---------------------------------------------------------------------------
# Timecode helpers
# ---------------------------------------------------------------------------


def frames_to_timecode(total_frames: int, fps: int) -> str:
    """Convert a frame count to HH:MM:SS:FF timecode string.

    Uses non-drop-frame format (colon separator throughout).
    """
    if fps <= 0:
        return "00:00:00:00"
    h = total_frames // (fps * 3600)
    remainder = total_frames % (fps * 3600)
    m = remainder // (fps * 60)
    remainder = remainder % (fps * 60)
    s = remainder // fps
    f = remainder % fps
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _get_panels(rig: dict) -> list:
    """Extract sorted panels from the rig's storyboard data."""
    panels = rig.get("storyboard", {}).get("panels", [])
    return sorted(panels, key=lambda p: p.get("number", 0))


# ---------------------------------------------------------------------------
# EDL generation (CMX3600 format)
# ---------------------------------------------------------------------------


def generate_edl(panels: list, title: str, fps: int) -> str:
    """Generate a CMX3600-format EDL from a list of panels.

    Each panel becomes one edit event with:
    - Source IN/OUT = 00:00:00:00 to panel duration
    - Record IN/OUT = cumulative timeline position

    Returns the EDL as a string.
    """
    lines = [
        f"TITLE: {title}",
        f"FCM: NON-DROP FRAME",
        "",
    ]

    record_frame = 0
    for i, panel in enumerate(panels):
        event_num = i + 1
        duration = panel.get("duration_frames", 24)
        reel = f"PANEL_{panel.get('number', event_num):03d}"
        description = panel.get("description", "")

        src_in = frames_to_timecode(0, fps)
        src_out = frames_to_timecode(duration, fps)
        rec_in = frames_to_timecode(record_frame, fps)
        rec_out = frames_to_timecode(record_frame + duration, fps)

        # CMX3600 format: event# reel track transition src_in src_out rec_in rec_out
        lines.append(
            f"{event_num:03d}  {reel:<8s} V     C        "
            f"{src_in} {src_out} {rec_in} {rec_out}"
        )
        # Optional comment line with description
        if description:
            lines.append(f"* FROM CLIP NAME: {description}")
        lines.append("")

        record_frame += duration

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FCP XML generation
# ---------------------------------------------------------------------------


def generate_fcpxml(panels: list, title: str, fps: int) -> str:
    """Generate a Final Cut Pro XML from a list of panels.

    Creates a sequence with clips corresponding to each panel.
    Returns the XML as a string.
    """
    # Calculate total duration
    total_frames = sum(p.get("duration_frames", 24) for p in panels)

    # Build XML tree
    xmeml = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(xmeml, "sequence")
    ET.SubElement(sequence, "name").text = title
    ET.SubElement(sequence, "duration").text = str(total_frames)

    rate_elem = ET.SubElement(sequence, "rate")
    ET.SubElement(rate_elem, "timebase").text = str(fps)
    ET.SubElement(rate_elem, "ntsc").text = "FALSE"

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    track = ET.SubElement(video, "track")

    record_frame = 0
    for i, panel in enumerate(panels):
        duration = panel.get("duration_frames", 24)
        panel_num = panel.get("number", i + 1)
        description = panel.get("description", f"Panel {panel_num}")

        clip = ET.SubElement(track, "clipitem", id=f"clipitem-{i + 1}")
        ET.SubElement(clip, "name").text = description
        ET.SubElement(clip, "duration").text = str(duration)

        clip_rate = ET.SubElement(clip, "rate")
        ET.SubElement(clip_rate, "timebase").text = str(fps)
        ET.SubElement(clip_rate, "ntsc").text = "FALSE"

        ET.SubElement(clip, "start").text = str(record_frame)
        ET.SubElement(clip, "end").text = str(record_frame + duration)

        ET.SubElement(clip, "in").text = "0"
        ET.SubElement(clip, "out").text = str(duration)

        # File reference
        file_elem = ET.SubElement(clip, "file", id=f"file-{panel_num}")
        ET.SubElement(file_elem, "name").text = f"panel_{panel_num:03d}.png"
        ET.SubElement(file_elem, "pathurl").text = f"file:///panels/panel_{panel_num:03d}.png"

        file_rate = ET.SubElement(file_elem, "rate")
        ET.SubElement(file_rate, "timebase").text = str(fps)

        ET.SubElement(file_elem, "duration").text = str(duration)

        record_frame += duration

    # Serialize to string
    tree = ET.ElementTree(xmeml)
    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue().decode("utf-8")


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_edl_export tool."""

    @mcp.tool(
        name="adobe_ai_edl_export",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_edl_export(params: AiEdlExportInput) -> str:
        """Export storyboard timing as EDL or FCP XML for editorial.

        Actions:
        - export_edl: generate CMX3600 EDL format
        - export_fcpxml: generate Final Cut Pro XML with clips and timeline
        """
        rig = _load_rig(params.character_name)
        panels = _get_panels(rig)

        if not panels:
            return json.dumps({
                "error": "No storyboard panels found.",
                "hint": "Create panels first using the storyboard_panel tool.",
            })

        fps = params.fps or rig.get("timeline", {}).get("fps", 24)
        action = params.action.lower().strip()

        # ── export_edl ───────────────────────────────────────────────
        if action == "export_edl":
            edl_content = generate_edl(panels, params.title, fps)

            out_path = params.output_path or "/tmp/ai_storyboard_export/storyboard.edl"
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                f.write(edl_content)

            total_frames = sum(p.get("duration_frames", 24) for p in panels)
            return json.dumps({
                "action": "export_edl",
                "output_path": out_path,
                "event_count": len(panels),
                "total_frames": total_frames,
                "total_duration_tc": frames_to_timecode(total_frames, fps),
                "fps": fps,
            }, indent=2)

        # ── export_fcpxml ────────────────────────────────────────────
        elif action == "export_fcpxml":
            xml_content = generate_fcpxml(panels, params.title, fps)

            out_path = params.output_path or "/tmp/ai_storyboard_export/storyboard.fcpxml"
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                f.write(xml_content)

            total_frames = sum(p.get("duration_frames", 24) for p in panels)
            return json.dumps({
                "action": "export_fcpxml",
                "output_path": out_path,
                "clip_count": len(panels),
                "total_frames": total_frames,
                "total_duration_tc": frames_to_timecode(total_frames, fps),
                "fps": fps,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["export_edl", "export_fcpxml"],
            })
