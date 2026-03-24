"""Group storyboard panels into scenes with location and time metadata.

Scene data is stored in the rig file under `scenes`.  Each scene has a
number, name, assigned panel numbers, location (INT/EXT) and time of
day.  Scenes provide high-level structure for the storyboard pipeline.
"""

import json

from adobe_mcp.apps.illustrator.models import AiSceneManagerInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def _ensure_scenes(rig: dict) -> dict:
    """Ensure the rig has a scenes list."""
    if "scenes" not in rig:
        rig["scenes"] = []
    return rig


def _next_scene_number(rig: dict) -> int:
    """Return the next available scene number."""
    scenes = rig.get("scenes", [])
    if not scenes:
        return 1
    return max(s.get("number", 0) for s in scenes) + 1


def _find_scene(rig: dict, scene_number: int) -> tuple[dict | None, int | None]:
    """Find a scene by number, returning (scene_dict, index) or (None, None)."""
    for i, s in enumerate(rig.get("scenes", [])):
        if s.get("number") == scene_number:
            return s, i
    return None, None


def register(mcp):
    """Register the adobe_ai_scene_manager tool."""

    @mcp.tool(
        name="adobe_ai_scene_manager",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_scene_manager(params: AiSceneManagerInput) -> str:
        """Group storyboard panels into numbered scenes with headers.

        Create scenes, assign panels to them, reorder scenes, list all
        scenes with their panels, or delete a scene.
        """
        # Use a default character name for scene-level data
        character_name = "storyboard"
        rig = _load_rig(character_name)
        rig = _ensure_scenes(rig)

        action = params.action.lower().strip()

        # ── create ────────────────────────────────────────────────────
        if action == "create":
            scene_num = params.scene_number if params.scene_number is not None else _next_scene_number(rig)

            # Check for duplicate scene number
            existing, _ = _find_scene(rig, scene_num)
            if existing is not None:
                return json.dumps({
                    "error": f"Scene {scene_num} already exists. Use delete first or pick another number.",
                })

            # Parse panel numbers if provided
            panels = []
            if params.panel_numbers:
                try:
                    panels = [int(p.strip()) for p in params.panel_numbers.split(",") if p.strip()]
                except ValueError:
                    return json.dumps({"error": "panel_numbers must be comma-separated integers."})

            scene = {
                "number": scene_num,
                "name": params.scene_name or f"Scene {scene_num}",
                "panels": panels,
                "location": (params.location or "").upper() or "INT",
                "time": (params.time_of_day or "").upper() or "DAY",
            }
            rig["scenes"].append(scene)
            rig["scenes"].sort(key=lambda s: s.get("number", 0))
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "create",
                "scene": scene,
                "total_scenes": len(rig["scenes"]),
            }, indent=2)

        # ── add_panel ─────────────────────────────────────────────────
        elif action == "add_panel":
            if params.scene_number is None:
                return json.dumps({"error": "scene_number is required for add_panel."})
            if not params.panel_numbers:
                return json.dumps({"error": "panel_numbers is required for add_panel."})

            scene, idx = _find_scene(rig, params.scene_number)
            if scene is None:
                return json.dumps({
                    "error": f"Scene {params.scene_number} not found.",
                    "available_scenes": [s.get("number") for s in rig["scenes"]],
                })

            try:
                new_panels = [int(p.strip()) for p in params.panel_numbers.split(",") if p.strip()]
            except ValueError:
                return json.dumps({"error": "panel_numbers must be comma-separated integers."})

            # Add panels without duplicates, preserving order
            existing_panels = set(scene["panels"])
            for pn in new_panels:
                if pn not in existing_panels:
                    scene["panels"].append(pn)
                    existing_panels.add(pn)

            _save_rig(character_name, rig)

            return json.dumps({
                "action": "add_panel",
                "scene_number": params.scene_number,
                "panels": scene["panels"],
            }, indent=2)

        # ── remove_panel ──────────────────────────────────────────────
        elif action == "remove_panel":
            if params.scene_number is None:
                return json.dumps({"error": "scene_number is required for remove_panel."})
            if not params.panel_numbers:
                return json.dumps({"error": "panel_numbers is required for remove_panel."})

            scene, idx = _find_scene(rig, params.scene_number)
            if scene is None:
                return json.dumps({
                    "error": f"Scene {params.scene_number} not found.",
                    "available_scenes": [s.get("number") for s in rig["scenes"]],
                })

            try:
                remove_panels = {int(p.strip()) for p in params.panel_numbers.split(",") if p.strip()}
            except ValueError:
                return json.dumps({"error": "panel_numbers must be comma-separated integers."})

            scene["panels"] = [p for p in scene["panels"] if p not in remove_panels]
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "remove_panel",
                "scene_number": params.scene_number,
                "panels": scene["panels"],
                "removed": list(remove_panels),
            }, indent=2)

        # ── reorder ───────────────────────────────────────────────────
        elif action == "reorder":
            if params.scene_number is None:
                return json.dumps({"error": "scene_number is required for reorder."})

            scene, idx = _find_scene(rig, params.scene_number)
            if scene is None:
                return json.dumps({
                    "error": f"Scene {params.scene_number} not found.",
                    "available_scenes": [s.get("number") for s in rig["scenes"]],
                })

            if not params.panel_numbers:
                return json.dumps({"error": "panel_numbers required — new panel ordering."})

            try:
                new_order = [int(p.strip()) for p in params.panel_numbers.split(",") if p.strip()]
            except ValueError:
                return json.dumps({"error": "panel_numbers must be comma-separated integers."})

            scene["panels"] = new_order
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "reorder",
                "scene_number": params.scene_number,
                "panels": scene["panels"],
            }, indent=2)

        # ── list ──────────────────────────────────────────────────────
        elif action == "list":
            scenes = rig.get("scenes", [])
            return json.dumps({
                "action": "list",
                "scenes": scenes,
                "total_scenes": len(scenes),
            }, indent=2)

        # ── delete ────────────────────────────────────────────────────
        elif action == "delete":
            if params.scene_number is None:
                return json.dumps({"error": "scene_number is required for delete."})

            scene, idx = _find_scene(rig, params.scene_number)
            if scene is None:
                return json.dumps({
                    "error": f"Scene {params.scene_number} not found.",
                    "available_scenes": [s.get("number") for s in rig["scenes"]],
                })

            rig["scenes"].pop(idx)
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "delete",
                "deleted_scene": params.scene_number,
                "total_scenes": len(rig["scenes"]),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "add_panel", "remove_panel", "reorder", "list", "delete"],
            })
