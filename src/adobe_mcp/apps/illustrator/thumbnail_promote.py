"""Promote rough thumbnails to full-size storyboard panels.

Scales a rough thumbnail to full-size panel, duplicating all paths
and scaling landmark positions proportionally.  The new landmarks
are stored in the rig.

Uses JSX for duplication and scaling in Illustrator.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiThumbnailPromoteInput(BaseModel):
    """Scale a rough thumbnail to a full-size panel."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="promote", description="Action: promote"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    panel_number: int = Field(
        ..., description="Source thumbnail panel number", ge=1
    )
    target_width: float = Field(
        default=960.0, description="Target artboard width in points", gt=0
    )
    target_height: float = Field(
        default=540.0, description="Target artboard height in points", gt=0
    )
    source_width: float = Field(
        default=240.0, description="Source thumbnail width in points", gt=0
    )
    source_height: float = Field(
        default=135.0, description="Source thumbnail height in points", gt=0
    )


# ---------------------------------------------------------------------------
# Scale calculation helpers
# ---------------------------------------------------------------------------


def calculate_scale_factor(
    source_w: float, source_h: float, target_w: float, target_h: float
) -> dict:
    """Calculate uniform scale factor to fit source into target.

    Uses the smaller of width/height ratios so the content fits
    without cropping.  Returns dict with scale_x, scale_y, and
    uniform scale factor.
    """
    if source_w <= 0 or source_h <= 0:
        return {"scale_x": 1.0, "scale_y": 1.0, "uniform_scale": 1.0}

    sx = target_w / source_w
    sy = target_h / source_h
    uniform = min(sx, sy)

    return {
        "scale_x": round(sx, 4),
        "scale_y": round(sy, 4),
        "uniform_scale": round(uniform, 4),
    }


def scale_landmarks(
    landmarks: dict, scale: float, offset_x: float = 0.0, offset_y: float = 0.0
) -> dict:
    """Scale landmark positions proportionally.

    Each landmark has an ``ai`` key with [x, y] in AI coordinates.
    Returns a new dict with scaled positions.
    """
    scaled = {}
    for name, data in landmarks.items():
        if "ai" not in data:
            scaled[name] = dict(data)
            continue
        old = data["ai"]
        new_pos = [
            round(old[0] * scale + offset_x, 2),
            round(old[1] * scale + offset_y, 2),
        ]
        entry = dict(data)
        entry["ai"] = new_pos
        entry["promoted"] = True
        scaled[name] = entry
    return scaled


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_thumbnail_promote tool."""

    @mcp.tool(
        name="adobe_ai_thumbnail_promote",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_thumbnail_promote(params: AiThumbnailPromoteInput) -> str:
        """Scale a rough thumbnail to a full-size panel, preserving landmarks.

        Calculates scale factor, duplicates all paths from the source
        artboard, scales and positions them onto a new artboard, and
        scales landmark positions proportionally.
        """
        action = params.action.lower().strip()
        if action != "promote":
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["promote"],
            })

        rig = _load_rig(params.character_name)

        # Calculate scale
        scale_info = calculate_scale_factor(
            params.source_width, params.source_height,
            params.target_width, params.target_height,
        )
        uniform_scale = scale_info["uniform_scale"]
        scale_pct = round(uniform_scale * 100, 2)

        # Scale landmarks if present
        old_landmarks = rig.get("landmarks", {})
        new_landmarks = {}
        if old_landmarks:
            new_landmarks = scale_landmarks(old_landmarks, uniform_scale)

        # Build JSX to duplicate and scale panel contents
        panel_gap = 40
        # Source artboard position
        src_idx = params.panel_number - 1
        src_left = (params.source_width + panel_gap) * src_idx

        # New artboard placed after existing artboards
        panels = rig.get("storyboard", {}).get("panels", [])
        existing_count = len(panels)
        new_left = (params.target_width + panel_gap) * existing_count
        new_top = 0
        new_right = new_left + params.target_width
        new_bottom = new_top - params.target_height

        new_panel_num = max((p.get("number", 0) for p in panels), default=0) + 1

        jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Create new artboard
    var abRect = [{new_left}, {new_top}, {new_right}, {new_bottom}];
    var abIdx = doc.artboards.add(abRect);
    var ab = doc.artboards[abIdx];
    ab.name = "Panel_{new_panel_num}_promoted";

    // Find source panel layer
    var sourceLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Panel_{params.panel_number}") {{
            sourceLayer = doc.layers[i];
            break;
        }}
    }}

    var copied = 0;
    if (sourceLayer) {{
        var newLayer = doc.layers.add();
        newLayer.name = "Panel_{new_panel_num}_promoted";

        // Duplicate and scale each item
        for (var j = sourceLayer.pageItems.length - 1; j >= 0; j--) {{
            var item = sourceLayer.pageItems[j];
            var dup = item.duplicate(newLayer, ElementPlacement.PLACEATBEGINNING);
            // Move to new artboard position first
            var dx = {new_left} - {src_left};
            dup.translate(dx, 0);
            // Scale from top-left of new artboard
            dup.resize({scale_pct}, {scale_pct});
            copied++;
        }}
    }}

    return JSON.stringify({{
        artboard_index: abIdx,
        panel_number: {new_panel_num},
        copied_items: copied,
        scale_percent: {scale_pct}
    }});
}})();
"""
        result = await _async_run_jsx("illustrator", jsx)

        # Store promoted panel in rig storyboard
        if "storyboard" not in rig:
            rig["storyboard"] = {"panels": []}

        promoted_panel = {
            "number": new_panel_num,
            "description": f"Promoted from thumbnail panel {params.panel_number}",
            "camera": "wide",
            "duration_frames": 24,
            "promoted_from": params.panel_number,
            "scale_factor": uniform_scale,
        }
        rig["storyboard"]["panels"].append(promoted_panel)

        # Store scaled landmarks
        if new_landmarks:
            rig.setdefault("promoted_landmarks", {})
            rig["promoted_landmarks"][str(new_panel_num)] = new_landmarks

        _save_rig(params.character_name, rig)

        return json.dumps({
            "action": "promote",
            "source_panel": params.panel_number,
            "new_panel_number": new_panel_num,
            "scale_info": scale_info,
            "landmarks_scaled": len(new_landmarks),
            "jsx_success": result.get("success", False),
        }, indent=2)
