"""Place multiple characters in one storyboard panel.

Character placement data is stored in the rig file under
`character_placements` — a list of dicts recording which character is
in which panel, at what position, scale, and pose.

Actions: place, repose, remove, list.
"""

import json

from adobe_mcp.apps.illustrator.models import AiMultiCharacterInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _ensure_placements(rig: dict) -> dict:
    """Ensure the rig has a character_placements list."""
    if "character_placements" not in rig:
        rig["character_placements"] = []
    return rig


def _find_placement(
    placements: list, panel: int, character: str
) -> tuple[dict | None, int | None]:
    """Find a placement by panel + character name, returning (entry, index)."""
    for i, p in enumerate(placements):
        if p.get("panel") == panel and p.get("character") == character:
            return p, i
    return None, None


def register(mcp):
    """Register the adobe_ai_multi_character tool."""

    @mcp.tool(
        name="adobe_ai_multi_character",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_multi_character(params: AiMultiCharacterInput) -> str:
        """Place multiple characters in one panel with independent poses.

        Each character has its own position, scale, and pose assignment.
        Prevents duplicate placement of the same character in a panel.
        """
        # Store placements in a shared storyboard rig
        rig_name = "storyboard"
        rig = _load_rig(rig_name)
        rig = _ensure_placements(rig)

        action = params.action.lower().strip()
        placements = rig["character_placements"]

        # ── place ─────────────────────────────────────────────────────
        if action == "place":
            # Check for duplicate: same character in same panel
            existing, _ = _find_placement(placements, params.panel_number, params.character_name)
            if existing is not None:
                return json.dumps({
                    "error": (
                        f"Character '{params.character_name}' already placed in panel "
                        f"{params.panel_number}. Use repose to update or remove first."
                    ),
                })

            entry = {
                "panel": params.panel_number,
                "character": params.character_name,
                "pose": params.pose_name or "idle",
                "x": params.position_x if params.position_x is not None else 0.0,
                "y": params.position_y if params.position_y is not None else 0.0,
                "scale": params.scale,
            }
            placements.append(entry)
            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "place",
                "placement": entry,
                "total_placements": len(placements),
            }, indent=2)

        # ── repose ────────────────────────────────────────────────────
        elif action == "repose":
            existing, idx = _find_placement(placements, params.panel_number, params.character_name)
            if existing is None:
                return json.dumps({
                    "error": (
                        f"Character '{params.character_name}' not found in panel "
                        f"{params.panel_number}. Use place first."
                    ),
                })

            # Update pose and optionally position/scale
            if params.pose_name is not None:
                existing["pose"] = params.pose_name
            if params.position_x is not None:
                existing["x"] = params.position_x
            if params.position_y is not None:
                existing["y"] = params.position_y
            if params.scale != 100:  # non-default means user specified it
                existing["scale"] = params.scale

            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "repose",
                "placement": existing,
            }, indent=2)

        # ── remove ────────────────────────────────────────────────────
        elif action == "remove":
            existing, idx = _find_placement(placements, params.panel_number, params.character_name)
            if existing is None:
                return json.dumps({
                    "error": (
                        f"Character '{params.character_name}' not found in panel "
                        f"{params.panel_number}."
                    ),
                })

            placements.pop(idx)
            _save_rig(rig_name, rig)

            return json.dumps({
                "action": "remove",
                "removed": {
                    "panel": params.panel_number,
                    "character": params.character_name,
                },
                "total_placements": len(placements),
            }, indent=2)

        # ── list ──────────────────────────────────────────────────────
        elif action == "list":
            # Filter by panel if a panel_number is provided
            if params.panel_number is not None:
                filtered = [
                    p for p in placements if p.get("panel") == params.panel_number
                ]
            else:
                filtered = placements

            return json.dumps({
                "action": "list",
                "placements": filtered,
                "total": len(filtered),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["place", "repose", "remove", "list"],
            })
