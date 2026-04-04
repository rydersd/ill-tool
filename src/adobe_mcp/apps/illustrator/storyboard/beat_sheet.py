"""Map story beats to storyboard panels for narrative structure.

Beat sheet data is stored in the rig under `beat_sheet` as a list of
beat entries.  Each beat has a name, assigned panel number, and
description.

Standard beats: opening, inciting_incident, rising_action, midpoint,
climax, falling_action, resolution.

The auto_assign action distributes beats evenly across the total panel
count so there is always a reasonable starting structure.
"""

import json
import math

from adobe_mcp.apps.illustrator.models import AiBeatSheetInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig

# Standard story beat names in narrative order
STANDARD_BEATS = [
    "opening",
    "inciting_incident",
    "rising_action",
    "midpoint",
    "climax",
    "falling_action",
    "resolution",
]


def _ensure_beat_sheet(rig: dict) -> dict:
    """Ensure the rig has a beat_sheet structure."""
    if "beat_sheet" not in rig:
        rig["beat_sheet"] = {"beats": []}
    if "beats" not in rig["beat_sheet"]:
        rig["beat_sheet"]["beats"] = []
    return rig


def _find_beat(beats: list, beat_name: str) -> tuple[dict | None, int | None]:
    """Find a beat by name, returning (beat_dict, index) or (None, None)."""
    for i, b in enumerate(beats):
        if b.get("name") == beat_name:
            return b, i
    return None, None


def _auto_distribute(total_panels: int) -> list[dict]:
    """Distribute standard beats evenly across panel numbers.

    For 10 panels the distribution is:
        opening=1, inciting_incident=2, rising_action=4, midpoint=5,
        climax=7, falling_action=9, resolution=10

    General formula: each beat gets an evenly spaced position, clamped
    to 1..total_panels.
    """
    num_beats = len(STANDARD_BEATS)
    if total_panels <= 0:
        return []

    beats = []
    for i, name in enumerate(STANDARD_BEATS):
        if num_beats == 1:
            panel = 1
        else:
            # Spread beats across the panel range, first at 1, last at total_panels
            raw = 1 + (i * (total_panels - 1)) / (num_beats - 1)
            panel = max(1, min(total_panels, round(raw)))
        beats.append({
            "name": name,
            "panel": panel,
            "description": "",
        })
    return beats


def register(mcp):
    """Register the adobe_ai_beat_sheet tool."""

    @mcp.tool(
        name="adobe_ai_beat_sheet",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_beat_sheet(params: AiBeatSheetInput) -> str:
        """Map story beats to panel timing for narrative structure.

        Add, remove, list beats, or auto-assign standard story beats
        evenly across the panel count.
        """
        rig_name = "storyboard"
        rig = _load_rig(rig_name)
        rig = _ensure_beat_sheet(rig)

        action = params.action.lower().strip()
        beats = rig["beat_sheet"]["beats"]

        # ── add ───────────────────────────────────────────────────────
        if action == "add":
            if not params.beat_name:
                return json.dumps({"error": "beat_name is required for add."})
            if params.panel_number is None:
                return json.dumps({"error": "panel_number is required for add."})

            # Replace existing beat with same name
            beats = [b for b in beats if b.get("name") != params.beat_name]

            beat = {
                "name": params.beat_name,
                "panel": params.panel_number,
                "description": params.description or "",
            }
            beats.append(beat)
            # Sort beats by panel number for readability
            beats.sort(key=lambda b: b.get("panel", 0))
            rig["beat_sheet"]["beats"] = beats
            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "add",
                "beat": beat,
                "total_beats": len(beats),
            }, indent=2)

        # ── remove ────────────────────────────────────────────────────
        elif action == "remove":
            if not params.beat_name:
                return json.dumps({"error": "beat_name is required for remove."})

            existing, idx = _find_beat(beats, params.beat_name)
            if existing is None:
                return json.dumps({
                    "error": f"Beat '{params.beat_name}' not found.",
                    "available_beats": [b.get("name") for b in beats],
                })

            beats.pop(idx)
            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "remove",
                "removed": params.beat_name,
                "total_beats": len(beats),
            }, indent=2)

        # ── list ──────────────────────────────────────────────────────
        elif action == "list":
            return json.dumps({
                "action": "list",
                "beats": beats,
                "total_beats": len(beats),
                "standard_beats": STANDARD_BEATS,
            }, indent=2)

        # ── auto_assign ───────────────────────────────────────────────
        elif action == "auto_assign":
            # Determine total panel count from storyboard data
            storyboard = rig.get("storyboard", {})
            panels = storyboard.get("panels", [])
            total_panels = len(panels)

            if total_panels == 0:
                # Fall back to panel_number param as total count hint
                if params.panel_number is not None and params.panel_number > 0:
                    total_panels = params.panel_number
                else:
                    return json.dumps({
                        "error": "No panels found in storyboard. Create panels first or provide panel_number as total count.",
                    })

            auto_beats = _auto_distribute(total_panels)
            rig["beat_sheet"]["beats"] = auto_beats
            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "auto_assign",
                "beats": auto_beats,
                "total_panels": total_panels,
                "total_beats": len(auto_beats),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["add", "remove", "list", "auto_assign"],
            })
