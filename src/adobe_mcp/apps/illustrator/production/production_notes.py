"""Per-panel production notes for storyboard panels.

Stores director's notes, VFX flags, audio cues, and technical requirements
per panel.  Data lives in the rig file under `production_notes` keyed by
panel number (as string).

Each note is a dict: {"type": ..., "note": ..., "priority": ...}
"""

import json

from adobe_mcp.apps.illustrator.models import AiProductionNotesInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# Valid note types and priorities for validation
VALID_NOTE_TYPES = {"direction", "vfx", "audio", "technical", "continuity"}
VALID_PRIORITIES = {"low", "normal", "high", "critical"}

# Priority ordering for sorting/filtering
PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def _ensure_production_notes(rig: dict) -> dict:
    """Ensure the rig has a production_notes dict."""
    if "production_notes" not in rig:
        rig["production_notes"] = {}
    return rig


def _get_panel_notes(rig: dict, panel_number: int) -> list[dict]:
    """Return notes for a specific panel, or an empty list."""
    key = str(panel_number)
    return rig.get("production_notes", {}).get(key, [])


def _filter_by_priority(notes: list[dict], priority: str | None) -> list[dict]:
    """Filter a list of notes by priority level.

    If priority is None, return all notes.
    """
    if priority is None:
        return notes
    return [n for n in notes if n.get("priority") == priority]


def _export_notes(rig: dict) -> str:
    """Format all production notes as human-readable text.

    Groups by panel, sorted by priority within each panel.
    """
    prod_notes = rig.get("production_notes", {})
    if not prod_notes:
        return "No production notes."

    lines: list[str] = []
    lines.append("=" * 50)
    lines.append("PRODUCTION NOTES")
    lines.append("=" * 50)

    # Sort panel numbers numerically
    panel_keys = sorted(prod_notes.keys(), key=lambda k: int(k))

    for panel_key in panel_keys:
        notes = prod_notes[panel_key]
        if not notes:
            continue

        lines.append("")
        lines.append(f"--- Panel {panel_key} ---")

        # Sort by priority (critical first)
        sorted_notes = sorted(
            notes,
            key=lambda n: PRIORITY_ORDER.get(n.get("priority", "normal"), 2),
        )

        for note in sorted_notes:
            priority_tag = note.get("priority", "normal").upper()
            note_type = note.get("type", "direction").upper()
            content = note.get("note", "")
            lines.append(f"  [{priority_tag}] ({note_type}) {content}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def register(mcp):
    """Register the adobe_ai_production_notes tool."""

    @mcp.tool(
        name="adobe_ai_production_notes",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_production_notes(params: AiProductionNotesInput) -> str:
        """Manage per-panel production notes: direction, VFX, audio, technical.

        Actions:
        - set: add a note to a panel
        - clear: remove all notes from a panel
        - list: show all notes (optionally filtered by panel/priority)
        - export: formatted text export of all notes
        """
        # Use a default character name for storyboard-level data
        character_name = "storyboard"
        rig = _load_rig(character_name)
        rig = _ensure_production_notes(rig)

        action = params.action.lower().strip()

        # ── set (add a note) ─────────────────────────────────────
        if action == "set":
            if not params.note:
                return json.dumps({"error": "note text is required for set action."})

            note_type = params.note_type.lower().strip()
            if note_type not in VALID_NOTE_TYPES:
                return json.dumps({
                    "error": f"Invalid note_type: {note_type}",
                    "valid_types": sorted(VALID_NOTE_TYPES),
                })

            priority = params.priority.lower().strip()
            if priority not in VALID_PRIORITIES:
                return json.dumps({
                    "error": f"Invalid priority: {priority}",
                    "valid_priorities": sorted(VALID_PRIORITIES),
                })

            panel_key = str(params.panel_number)
            if panel_key not in rig["production_notes"]:
                rig["production_notes"][panel_key] = []

            note_entry = {
                "type": note_type,
                "note": params.note,
                "priority": priority,
            }
            rig["production_notes"][panel_key].append(note_entry)
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "set",
                "panel": params.panel_number,
                "note": note_entry,
                "total_notes_on_panel": len(rig["production_notes"][panel_key]),
            }, indent=2)

        # ── clear ────────────────────────────────────────────────
        elif action == "clear":
            panel_key = str(params.panel_number)
            removed_count = len(rig["production_notes"].get(panel_key, []))
            rig["production_notes"].pop(panel_key, None)
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "clear",
                "panel": params.panel_number,
                "removed_count": removed_count,
            }, indent=2)

        # ── list ─────────────────────────────────────────────────
        elif action == "list":
            all_notes: dict[str, list[dict]] = {}
            prod_notes = rig.get("production_notes", {})

            # Collect all panels or just one
            panel_keys = sorted(prod_notes.keys(), key=lambda k: int(k))

            for pk in panel_keys:
                notes = prod_notes[pk]
                all_notes[pk] = sorted(
                    notes,
                    key=lambda n: PRIORITY_ORDER.get(n.get("priority", "normal"), 2),
                )

            total = sum(len(v) for v in all_notes.values())
            return json.dumps({
                "action": "list",
                "production_notes": all_notes,
                "total_notes": total,
                "panels_with_notes": len(all_notes),
            }, indent=2)

        # ── export ───────────────────────────────────────────────
        elif action == "export":
            text = _export_notes(rig)
            return json.dumps({
                "action": "export",
                "format": "text",
                "content": text,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["set", "clear", "list", "export"],
            })
