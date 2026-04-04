"""Organise scenes into acts for complete narrative structure.

Provides a three-tier hierarchy: Acts > Scenes > Panels.
Sequence data is stored in the rig file under `sequence`.
"""

import json

from adobe_mcp.apps.illustrator.models import AiSequenceAssemblerInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _ensure_sequence(rig: dict) -> dict:
    """Ensure the rig has a sequence structure."""
    if "sequence" not in rig:
        rig["sequence"] = {"acts": []}
    return rig


def _get_act(rig: dict, act_number: int) -> dict | None:
    """Find an act by number.  Returns None if not found."""
    for act in rig["sequence"]["acts"]:
        if act.get("number") == act_number:
            return act
    return None


def _get_scene_panels(rig: dict, scene_number: int) -> list:
    """Return panel numbers belonging to a scene from rig scene data.

    If a scene_manager entry exists, use its panels.  Otherwise
    fall back to storyboard panels that might be tagged.
    """
    scenes = rig.get("scenes", [])
    for s in scenes:
        if s.get("scene_number") == scene_number:
            return s.get("panel_numbers", [])
    # Fallback: use storyboard panels for this scene
    panels = rig.get("storyboard", {}).get("panels", [])
    return [
        p.get("number", 0) for p in panels
        if p.get("scene_number") == scene_number
    ]


def compute_summary(rig: dict) -> dict:
    """Compute total panels, scenes, acts, and estimated runtime.

    Returns a summary dict with counts and timing.
    """
    sequence = rig.get("sequence", {"acts": []})
    acts = sequence.get("acts", [])

    total_acts = len(acts)
    total_scenes = 0
    all_scene_numbers = set()

    for act in acts:
        scenes = act.get("scenes", [])
        total_scenes += len(scenes)
        all_scene_numbers.update(scenes)

    # Count panels from storyboard data
    storyboard_panels = rig.get("storyboard", {}).get("panels", [])
    total_panels = len(storyboard_panels)

    # Compute total duration from panel frame counts
    fps = rig.get("timeline", {}).get("fps", 24)
    total_frames = sum(
        p.get("duration_frames", 24) for p in storyboard_panels
    )
    total_seconds = round(total_frames / fps, 3) if fps > 0 else 0

    return {
        "total_acts": total_acts,
        "total_scenes": total_scenes,
        "total_panels": total_panels,
        "total_frames": total_frames,
        "fps": fps,
        "total_duration_seconds": total_seconds,
        "estimated_runtime": _format_runtime(total_seconds),
    }


def _format_runtime(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    total_secs = int(seconds)
    hours = total_secs // 3600
    mins = (total_secs % 3600) // 60
    secs = total_secs % 60
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def generate_outline(rig: dict) -> str:
    """Generate a formatted text outline of the sequence.

    Format:
        Act I: Setup
          Scene 1 — Panels 1-3
          Scene 2 — Panels 4-6
        Act II: Confrontation
          Scene 3 — Panels 7-10
    """
    sequence = rig.get("sequence", {"acts": []})
    acts = sequence.get("acts", [])
    storyboard_panels = rig.get("storyboard", {}).get("panels", [])

    # Build a mapping of scene_number → list of panel numbers
    scene_panels_map = {}
    scenes_data = rig.get("scenes", [])
    for s in scenes_data:
        sn = s.get("scene_number")
        scene_panels_map[sn] = sorted(s.get("panel_numbers", []))

    # Roman numeral conversion for acts
    roman = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
             6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}

    lines = []
    for act in sorted(acts, key=lambda a: a.get("number", 0)):
        act_num = act.get("number", 0)
        act_name = act.get("name", "")
        numeral = roman.get(act_num, str(act_num))
        lines.append(f"Act {numeral}: {act_name}")

        for scene_num in act.get("scenes", []):
            panels = scene_panels_map.get(scene_num, [])
            if panels:
                panel_min = min(panels)
                panel_max = max(panels)
                if panel_min == panel_max:
                    panel_range = f"Panel {panel_min}"
                else:
                    panel_range = f"Panels {panel_min}-{panel_max}"
            else:
                panel_range = "No panels"
            lines.append(f"  Scene {scene_num} — {panel_range}")

    return "\n".join(lines)


def register(mcp):
    """Register the adobe_ai_sequence_assembler tool."""

    @mcp.tool(
        name="adobe_ai_sequence_assembler",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_sequence_assembler(params: AiSequenceAssemblerInput) -> str:
        """Organise scenes into acts for complete narrative structure.

        Create acts, assign scenes to acts, reorder, list the full
        structure, get a summary of counts and timing, or export a
        formatted text outline.
        """
        character_name = "character"
        rig = _load_rig(character_name)
        rig = _ensure_sequence(rig)

        action = params.action.lower().strip()

        # ── create_act ──────────────────────────────────────────────
        if action == "create_act":
            if params.act_number is None:
                # Auto-assign next act number
                existing_nums = [a.get("number", 0) for a in rig["sequence"]["acts"]]
                act_num = max(existing_nums, default=0) + 1
            else:
                act_num = params.act_number

            # Check for duplicate
            if _get_act(rig, act_num) is not None:
                return json.dumps({
                    "error": f"Act {act_num} already exists.",
                    "hint": "Use a different number or reorder existing acts.",
                })

            act_name = params.act_name or f"Act {act_num}"
            new_act = {
                "number": act_num,
                "name": act_name,
                "scenes": [],
            }

            rig["sequence"]["acts"].append(new_act)
            rig["sequence"]["acts"].sort(key=lambda a: a.get("number", 0))
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "create_act",
                "act": new_act,
                "total_acts": len(rig["sequence"]["acts"]),
            }, indent=2)

        # ── add_scene ───────────────────────────────────────────────
        elif action == "add_scene":
            if params.act_number is None:
                return json.dumps({
                    "error": "act_number is required for add_scene.",
                })

            act = _get_act(rig, params.act_number)
            if act is None:
                return json.dumps({
                    "error": f"Act {params.act_number} not found.",
                    "available_acts": [
                        a.get("number") for a in rig["sequence"]["acts"]
                    ],
                })

            if not params.scene_numbers:
                return json.dumps({
                    "error": "scene_numbers is required (comma-separated).",
                })

            scene_nums = [
                int(s.strip()) for s in params.scene_numbers.split(",")
                if s.strip().isdigit()
            ]

            # Add scenes, avoiding duplicates
            existing = set(act.get("scenes", []))
            added = []
            for sn in scene_nums:
                if sn not in existing:
                    act["scenes"].append(sn)
                    existing.add(sn)
                    added.append(sn)

            act["scenes"].sort()
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "add_scene",
                "act_number": params.act_number,
                "added_scenes": added,
                "act_scenes": act["scenes"],
            }, indent=2)

        # ── reorder ─────────────────────────────────────────────────
        elif action == "reorder":
            if params.act_number is None:
                return json.dumps({
                    "error": "act_number is required (act to move).",
                })

            act = _get_act(rig, params.act_number)
            if act is None:
                return json.dumps({
                    "error": f"Act {params.act_number} not found.",
                })

            # Parse new position from scene_numbers (reuse field)
            # scene_numbers is a comma-separated string; first value is the
            # new position index (1-based)
            new_pos = 1
            if params.scene_numbers:
                try:
                    new_pos = int(params.scene_numbers.strip().split(",")[0])
                except ValueError:
                    new_pos = 1

            acts = rig["sequence"]["acts"]
            acts.remove(act)
            new_pos = max(1, min(new_pos, len(acts) + 1))
            acts.insert(new_pos - 1, act)

            # Renumber acts sequentially
            for i, a in enumerate(acts):
                a["number"] = i + 1

            _save_rig(character_name, rig)

            return json.dumps({
                "action": "reorder",
                "acts": [
                    {"number": a["number"], "name": a.get("name", "")}
                    for a in acts
                ],
            }, indent=2)

        # ── list ────────────────────────────────────────────────────
        elif action == "list":
            acts = rig["sequence"]["acts"]
            return json.dumps({
                "action": "list",
                "acts": acts,
                "total_acts": len(acts),
            }, indent=2)

        # ── summary ─────────────────────────────────────────────────
        elif action == "summary":
            summary = compute_summary(rig)
            return json.dumps({
                "action": "summary",
                **summary,
            }, indent=2)

        # ── export_outline ──────────────────────────────────────────
        elif action == "export_outline":
            outline = generate_outline(rig)
            return json.dumps({
                "action": "export_outline",
                "outline": outline,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": [
                    "create_act", "add_scene", "reorder",
                    "list", "summary", "export_outline",
                ],
            })
