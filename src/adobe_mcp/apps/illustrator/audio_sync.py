"""Audio timing markers per storyboard panel.

Stores dialogue, music, SFX, and ambience cues with frame-level timing
in the rig file under `audio_cues`.  The `export_markers` action computes
absolute frame positions by summing panel durations.
"""

import json

from adobe_mcp.apps.illustrator.models import AiAudioSyncInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# Valid cue types
VALID_CUE_TYPES = {"dialogue", "music", "sfx", "ambience"}


def _ensure_audio_cues(rig: dict) -> dict:
    """Ensure the rig has an audio_cues list."""
    if "audio_cues" not in rig:
        rig["audio_cues"] = []
    return rig


def _get_panel_duration(rig: dict, panel_number: int) -> int:
    """Get the duration in frames for a specific panel from storyboard data.

    Falls back to 24 frames (1 second at 24fps) if not found.
    """
    panels = rig.get("storyboard", {}).get("panels", [])
    for p in panels:
        if p.get("number") == panel_number:
            return p.get("duration_frames", 24)
    return 24


def _compute_panel_start_frames(rig: dict) -> dict:
    """Compute absolute start frame for each panel by summing durations.

    Returns a dict mapping panel_number → absolute_start_frame.
    """
    panels = rig.get("storyboard", {}).get("panels", [])
    # Sort by panel number
    sorted_panels = sorted(panels, key=lambda p: p.get("number", 0))

    start_frames = {}
    cumulative = 0
    for p in sorted_panels:
        panel_num = p.get("number", 0)
        start_frames[panel_num] = cumulative
        cumulative += p.get("duration_frames", 24)

    return start_frames


def export_markers(rig: dict) -> list:
    """Generate a timeline of all audio cues with absolute frame positions.

    Each cue's absolute start frame = panel start frame + cue's local start_frame.
    Returns a list of marker dicts sorted by absolute frame.
    """
    panel_starts = _compute_panel_start_frames(rig)
    cues = rig.get("audio_cues", [])

    markers = []
    for cue in cues:
        panel_num = cue.get("panel", 0)
        # Use computed panel start, or estimate from panel number if
        # panel isn't in storyboard data
        panel_start = panel_starts.get(panel_num, (panel_num - 1) * 24)
        local_start = cue.get("start_frame", 0)
        absolute_frame = panel_start + local_start

        markers.append({
            "panel": panel_num,
            "type": cue.get("type", ""),
            "name": cue.get("name", ""),
            "start_frame": local_start,
            "duration": cue.get("duration", 0),
            "absolute_frame": absolute_frame,
            "absolute_end_frame": absolute_frame + cue.get("duration", 0),
        })

    # Sort by absolute frame, then by panel for stable ordering
    markers.sort(key=lambda m: (m["absolute_frame"], m["panel"]))
    return markers


def register(mcp):
    """Register the adobe_ai_audio_sync tool."""

    @mcp.tool(
        name="adobe_ai_audio_sync",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_audio_sync(params: AiAudioSyncInput) -> str:
        """Add, remove, list, or export audio timing markers for panels.

        Supports dialogue, music, SFX, and ambience cues with frame-level
        precision.  export_markers computes absolute frame positions across
        the entire storyboard timeline.
        """
        character_name = "character"
        rig = _load_rig(character_name)
        rig = _ensure_audio_cues(rig)

        action = params.action.lower().strip()
        panel_num = params.panel_number

        # ── add ─────────────────────────────────────────────────────
        if action == "add":
            cue_type = params.cue_type.lower().strip()
            if cue_type not in VALID_CUE_TYPES:
                return json.dumps({
                    "error": f"Unknown cue type: {cue_type}",
                    "valid_types": sorted(VALID_CUE_TYPES),
                })

            cue = {
                "panel": panel_num,
                "type": cue_type,
                "name": params.cue_name or "",
                "start_frame": params.start_frame,
                "duration": params.duration_frames or 0,
            }

            rig["audio_cues"].append(cue)
            # Sort cues by panel then start_frame
            rig["audio_cues"].sort(
                key=lambda c: (c.get("panel", 0), c.get("start_frame", 0))
            )
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "add",
                "cue": cue,
                "total_cues": len(rig["audio_cues"]),
            }, indent=2)

        # ── remove ──────────────────────────────────────────────────
        elif action == "remove":
            cue_name = params.cue_name
            before_count = len(rig["audio_cues"])

            if cue_name:
                # Remove by name within the specified panel
                rig["audio_cues"] = [
                    c for c in rig["audio_cues"]
                    if not (c.get("panel") == panel_num and c.get("name") == cue_name)
                ]
            else:
                # Remove all cues for this panel
                rig["audio_cues"] = [
                    c for c in rig["audio_cues"]
                    if c.get("panel") != panel_num
                ]

            removed = before_count - len(rig["audio_cues"])
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "remove",
                "panel_number": panel_num,
                "cue_name": cue_name,
                "removed_count": removed,
                "remaining_cues": len(rig["audio_cues"]),
            }, indent=2)

        # ── list ────────────────────────────────────────────────────
        elif action == "list":
            panel_cues = [
                c for c in rig["audio_cues"]
                if c.get("panel") == panel_num
            ]

            return json.dumps({
                "action": "list",
                "panel_number": panel_num,
                "cues": panel_cues,
                "total_cues_in_panel": len(panel_cues),
                "total_cues_all": len(rig["audio_cues"]),
            }, indent=2)

        # ── export_markers ──────────────────────────────────────────
        elif action == "export_markers":
            markers = export_markers(rig)

            # Compute total duration from storyboard
            panels = rig.get("storyboard", {}).get("panels", [])
            total_frames = sum(p.get("duration_frames", 24) for p in panels)
            fps = rig.get("timeline", {}).get("fps", 24)

            return json.dumps({
                "action": "export_markers",
                "markers": markers,
                "total_markers": len(markers),
                "total_frames": total_frames,
                "fps": fps,
                "total_duration_seconds": round(total_frames / fps, 3) if fps > 0 else 0,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["add", "remove", "list", "export_markers"],
            })
