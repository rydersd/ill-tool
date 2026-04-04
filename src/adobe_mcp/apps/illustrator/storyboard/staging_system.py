"""Scene staging system for storyboard panels.

Suggests camera placement and character positions based on scene type
(dialogue, action, establishing, chase, confrontation).  Staging presets
are stored in the rig file under ``staging``.

Pure Python logic with optional JSX for placing guides.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiStagingSystemInput(BaseModel):
    """Suggest and apply scene staging for storyboard panels."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: suggest_staging, apply_staging"
    )
    scene_type: str = Field(
        default="dialogue",
        description="Scene type: dialogue, action, establishing, chase, confrontation",
    )
    panel_number: int = Field(default=1, description="Target panel number", ge=1)
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    num_characters: int = Field(
        default=2, description="Number of characters in scene", ge=1, le=10
    )


# ---------------------------------------------------------------------------
# Staging presets
# ---------------------------------------------------------------------------

# Default panel dimensions (must match storyboard_panel.py)
PANEL_WIDTH = 960
PANEL_HEIGHT = 540


def _dialogue_staging(num_characters: int, panel_w: int, panel_h: int) -> dict:
    """Over-shoulder alternating, medium shots for dialogue scenes."""
    cameras = [
        {"type": "medium", "y_frac": (0.0, 0.55), "description": "Waist-up medium shot"},
        {"type": "over_shoulder", "y_frac": (0.05, 0.45), "description": "Over-shoulder reverse"},
        {"type": "close_up", "y_frac": (0.0, 0.30), "description": "Close-up for emphasis"},
    ]
    # Place characters at 1/3 and 2/3 of frame width, facing each other
    positions = []
    for i in range(num_characters):
        x_frac = (i + 1) / (num_characters + 1)
        facing = "right" if x_frac < 0.5 else "left"
        positions.append({
            "character_index": i,
            "x": round(panel_w * x_frac, 1),
            "y": round(panel_h * 0.55, 1),
            "facing": facing,
            "scale": 1.0,
        })
    return {
        "scene_type": "dialogue",
        "suggested_cameras": cameras,
        "character_positions": positions,
        "notes": "Alternate between over-shoulder and medium shots for dialogue rhythm.",
    }


def _action_staging(num_characters: int, panel_w: int, panel_h: int) -> dict:
    """Wide establishing then close-up reaction shots for action scenes."""
    cameras = [
        {"type": "wide", "y_frac": (0.0, 1.0), "description": "Wide establishing shot"},
        {"type": "close_up", "y_frac": (0.0, 0.30), "description": "Close-up reaction"},
        {"type": "medium", "y_frac": (0.0, 0.55), "description": "Medium action shot"},
        {"type": "extreme_close_up", "y_frac": (0.0, 0.18), "description": "Impact close-up"},
    ]
    # Characters spread across frame with dynamic spacing
    positions = []
    for i in range(num_characters):
        x_frac = (i + 1) / (num_characters + 1)
        # Action scenes have varied vertical positions for dynamism
        y_offset = 0.6 + (i % 2) * 0.1
        positions.append({
            "character_index": i,
            "x": round(panel_w * x_frac, 1),
            "y": round(panel_h * y_offset, 1),
            "facing": "right",
            "scale": 0.9 + (i % 2) * 0.2,
        })
    return {
        "scene_type": "action",
        "suggested_cameras": cameras,
        "character_positions": positions,
        "notes": "Start wide to establish geography, then cut to close-ups for reactions.",
    }


def _establishing_staging(num_characters: int, panel_w: int, panel_h: int) -> dict:
    """Wide shots with characters small in frame for establishing scenes."""
    cameras = [
        {"type": "wide", "y_frac": (0.0, 1.0), "description": "Wide establishing shot"},
        {"type": "extreme_wide", "y_frac": (0.0, 1.0), "description": "Extreme wide for scale"},
    ]
    # Characters are small and grouped toward the lower third
    positions = []
    group_center = panel_w * 0.5
    spread = panel_w * 0.15
    for i in range(num_characters):
        offset = (i - (num_characters - 1) / 2) * (spread / max(num_characters - 1, 1))
        positions.append({
            "character_index": i,
            "x": round(group_center + offset, 1),
            "y": round(panel_h * 0.75, 1),
            "facing": "right",
            "scale": 0.4,
        })
    return {
        "scene_type": "establishing",
        "suggested_cameras": cameras,
        "character_positions": positions,
        "notes": "Keep characters small to emphasize environment. Use lower third placement.",
    }


def _chase_staging(num_characters: int, panel_w: int, panel_h: int) -> dict:
    """Dynamic diagonal compositions for chase scenes."""
    cameras = [
        {"type": "wide", "y_frac": (0.0, 1.0), "description": "Wide chase tracking shot"},
        {"type": "medium", "y_frac": (0.0, 0.55), "description": "Medium running shot"},
        {"type": "low_angle", "y_frac": (0.3, 1.0), "description": "Low angle for speed"},
    ]
    # Characters along a diagonal for motion feeling
    positions = []
    for i in range(num_characters):
        t = (i + 1) / (num_characters + 1)
        positions.append({
            "character_index": i,
            "x": round(panel_w * t, 1),
            "y": round(panel_h * (0.4 + t * 0.3), 1),
            "facing": "right",
            "scale": 0.7 + t * 0.3,
        })
    return {
        "scene_type": "chase",
        "suggested_cameras": cameras,
        "character_positions": positions,
        "notes": "Use diagonal composition. Leading character larger (closer to camera).",
    }


def _confrontation_staging(num_characters: int, panel_w: int, panel_h: int) -> dict:
    """Symmetric framing with characters facing each other for confrontations."""
    cameras = [
        {"type": "medium", "y_frac": (0.0, 0.55), "description": "Medium two-shot"},
        {"type": "close_up", "y_frac": (0.0, 0.30), "description": "Close-up tension"},
        {"type": "wide", "y_frac": (0.0, 1.0), "description": "Wide standoff"},
    ]
    # Characters at screen edges, facing inward
    positions = []
    for i in range(num_characters):
        if i % 2 == 0:
            x_frac = 0.25
            facing = "right"
        else:
            x_frac = 0.75
            facing = "left"
        # If more than 2, stack them behind their sides
        row = i // 2
        y_offset = 0.5 + row * 0.08
        positions.append({
            "character_index": i,
            "x": round(panel_w * x_frac, 1),
            "y": round(panel_h * y_offset, 1),
            "facing": facing,
            "scale": 1.0 - row * 0.1,
        })
    return {
        "scene_type": "confrontation",
        "suggested_cameras": cameras,
        "character_positions": positions,
        "notes": "Symmetric framing builds tension. Characters face each other across frame center.",
    }


# Scene type -> staging function
STAGING_FUNCTIONS = {
    "dialogue": _dialogue_staging,
    "action": _action_staging,
    "establishing": _establishing_staging,
    "chase": _chase_staging,
    "confrontation": _confrontation_staging,
}

VALID_SCENE_TYPES = set(STAGING_FUNCTIONS.keys())


def suggest_staging(scene_type: str, num_characters: int,
                    panel_w: int = PANEL_WIDTH, panel_h: int = PANEL_HEIGHT) -> dict:
    """Return staging suggestion for the given scene type.

    Returns a dict with suggested_cameras, character_positions, and notes.
    """
    scene_type = scene_type.lower().strip()
    if scene_type not in STAGING_FUNCTIONS:
        return {
            "error": f"Unknown scene type: {scene_type}",
            "valid_types": sorted(VALID_SCENE_TYPES),
        }
    return STAGING_FUNCTIONS[scene_type](num_characters, panel_w, panel_h)


def _ensure_staging(rig: dict) -> dict:
    """Ensure the rig has a staging structure."""
    if "staging" not in rig:
        rig["staging"] = {}
    return rig


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_staging_system tool."""

    @mcp.tool(
        name="adobe_ai_staging_system",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_staging_system(params: AiStagingSystemInput) -> str:
        """Suggest camera placement and character positions for a scene.

        Actions:
        - suggest_staging: return camera and character placement suggestions
        - apply_staging: store the staging preset and optionally draw guides
        """
        action = params.action.lower().strip()
        scene_type = params.scene_type.lower().strip()

        # ── suggest_staging ──────────────────────────────────────────
        if action == "suggest_staging":
            staging = suggest_staging(scene_type, params.num_characters)
            if "error" in staging:
                return json.dumps(staging)

            return json.dumps({
                "action": "suggest_staging",
                "panel_number": params.panel_number,
                **staging,
            }, indent=2)

        # ── apply_staging ────────────────────────────────────────────
        elif action == "apply_staging":
            staging = suggest_staging(scene_type, params.num_characters)
            if "error" in staging:
                return json.dumps(staging)

            # Store in rig
            rig = _load_rig(params.character_name)
            rig = _ensure_staging(rig)

            panel_key = str(params.panel_number)
            rig["staging"][panel_key] = staging
            _save_rig(params.character_name, rig)

            # Draw character position guides via JSX
            panel_gap = 40
            panel_idx = params.panel_number - 1
            ab_left = (PANEL_WIDTH + panel_gap) * panel_idx

            guide_lines = []
            for pos in staging["character_positions"]:
                cx = ab_left + pos["x"]
                cy = -pos["y"]  # AI Y-up
                # Draw a small cross marker at character position
                arm = 15
                guide_lines.append(
                    f"var m{pos['character_index']} = layer.pathItems.add();"
                    f"m{pos['character_index']}.setEntirePath("
                    f"[[{cx - arm}, {cy}], [{cx + arm}, {cy}]]);"
                    f"m{pos['character_index']}.stroked = true;"
                    f"m{pos['character_index']}.strokeWidth = 1;"
                    f"m{pos['character_index']}.filled = false;"
                    f"var mv{pos['character_index']} = layer.pathItems.add();"
                    f"mv{pos['character_index']}.setEntirePath("
                    f"[[{cx}, {cy - arm}], [{cx}, {cy + arm}]]);"
                    f"mv{pos['character_index']}.stroked = true;"
                    f"mv{pos['character_index']}.strokeWidth = 1;"
                    f"mv{pos['character_index']}.filled = false;"
                )

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Staging_{params.panel_number}");
        while (layer.pageItems.length > 0) {{
            layer.pageItems[0].remove();
        }}
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Staging_{params.panel_number}";
    }}
    var stageColor = new RGBColor();
    stageColor.red = 100; stageColor.green = 200; stageColor.blue = 100;
    {"".join(guide_lines)}
    return JSON.stringify({{panel: {params.panel_number}, guides_placed: {len(staging["character_positions"])}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "apply_staging",
                "panel_number": params.panel_number,
                "stored": True,
                "jsx_success": result.get("success", False),
                **staging,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["suggest_staging", "apply_staging"],
            })
