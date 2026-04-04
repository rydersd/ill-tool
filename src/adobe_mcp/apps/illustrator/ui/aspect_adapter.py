"""Re-compose panels for different output formats (aspect ratios).

Computes crop rects, scaling, and letterbox/pillarbox parameters
for adapting storyboard panels to various screen formats.

Pure Python — no JSX or Adobe required.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiAspectAdapterInput(BaseModel):
    """Re-compose panels for different aspect ratios."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="adapt",
        description="Action: adapt (single panel) or batch (all panels)",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    panel_bounds: Optional[list[float]] = Field(
        default=None,
        description="[x, y, w, h] source panel bounds",
    )
    panels: Optional[list[list[float]]] = Field(
        default=None,
        description="List of [x, y, w, h] panel bounds for batch",
    )
    source_ratio: str = Field(
        default="16:9",
        description="Source aspect ratio (e.g. '16:9', '4:3')",
    )
    target_ratio: str = Field(
        default="4:3",
        description="Target aspect ratio (e.g. '4:3', '1:1', '9:16')",
    )


# ---------------------------------------------------------------------------
# Common aspect ratios
# ---------------------------------------------------------------------------


COMMON_RATIOS = {
    "16:9": (16, 9),
    "4:3": (4, 3),
    "2.39:1": (2.39, 1),
    "1:1": (1, 1),
    "9:16": (9, 16),
    "21:9": (21, 9),
    "3:2": (3, 2),
}


def _parse_ratio(ratio_str: str) -> tuple[float, float]:
    """Parse an aspect ratio string like '16:9' into (width, height) floats."""
    # Check lookup table first
    if ratio_str in COMMON_RATIOS:
        return COMMON_RATIOS[ratio_str]

    parts = ratio_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid ratio format: {ratio_str}. Use 'W:H'.")

    w = float(parts[0])
    h = float(parts[1])
    if w <= 0 or h <= 0:
        raise ValueError(f"Ratio components must be positive: {ratio_str}")

    return (w, h)


# ---------------------------------------------------------------------------
# Core adaptation
# ---------------------------------------------------------------------------


def adapt_panel(
    panel_bounds: list[float],
    source_ratio: str,
    target_ratio: str,
) -> dict:
    """Compute the crop/pad transformation to adapt a panel to a new aspect ratio.

    Center-weighted: the crop preserves the center of the panel.

    Args:
        panel_bounds: [x, y, w, h] of the source panel.
        source_ratio: Source aspect ratio string.
        target_ratio: Target aspect ratio string.

    Returns:
        Dict with crop_rect, scale, letterbox, and pillarbox info.
    """
    px, py, pw, ph = panel_bounds

    src_w, src_h = _parse_ratio(source_ratio)
    tgt_w, tgt_h = _parse_ratio(target_ratio)

    src_aspect = src_w / src_h
    tgt_aspect = tgt_w / tgt_h

    # Tolerance for "same" aspect ratio
    if abs(src_aspect - tgt_aspect) < 0.01:
        return {
            "crop_rect": [px, py, pw, ph],
            "scale": 1.0,
            "letterbox": False,
            "pillarbox": False,
            "pad_top": 0.0,
            "pad_bottom": 0.0,
            "pad_left": 0.0,
            "pad_right": 0.0,
        }

    letterbox = False
    pillarbox = False
    pad_top = 0.0
    pad_bottom = 0.0
    pad_left = 0.0
    pad_right = 0.0

    if tgt_aspect < src_aspect:
        # Target is taller (relative to width) than source:
        # We need to crop horizontally (remove sides) or add vertical padding (letterbox).
        # Strategy: crop the source to fit target aspect, center-weighted.
        new_w = ph * tgt_aspect
        if new_w <= pw:
            # Crop horizontally
            crop_x = px + (pw - new_w) / 2
            crop_rect = [crop_x, py, new_w, ph]
            scale = 1.0
        else:
            # Can't crop enough horizontally; add vertical padding (letterbox)
            new_h = pw / tgt_aspect
            pad = new_h - ph
            pad_top = pad / 2
            pad_bottom = pad / 2
            crop_rect = [px, py - pad_top, pw, new_h]
            scale = 1.0
            letterbox = True

    else:
        # Target is wider (relative to height) than source:
        # Crop vertically (remove top/bottom) or add horizontal padding (pillarbox).
        new_h = pw / tgt_aspect
        if new_h <= ph:
            # Crop vertically
            crop_y = py + (ph - new_h) / 2
            crop_rect = [px, crop_y, pw, new_h]
            scale = 1.0
        else:
            # Can't crop enough vertically; add horizontal padding (pillarbox)
            new_w = ph * tgt_aspect
            pad = new_w - pw
            pad_left = pad / 2
            pad_right = pad / 2
            crop_rect = [px - pad_left, py, new_w, ph]
            scale = 1.0
            pillarbox = True

    return {
        "crop_rect": [round(v, 2) for v in crop_rect],
        "scale": round(scale, 4),
        "letterbox": letterbox,
        "pillarbox": pillarbox,
        "pad_top": round(pad_top, 2),
        "pad_bottom": round(pad_bottom, 2),
        "pad_left": round(pad_left, 2),
        "pad_right": round(pad_right, 2),
    }


def batch_adapt(
    panels: list[list[float]],
    target_ratio: str,
    source_ratio: str = "16:9",
) -> list[dict]:
    """Adapt all panels in a storyboard to a target aspect ratio.

    Args:
        panels: List of [x, y, w, h] panel bounds.
        target_ratio: Target aspect ratio.
        source_ratio: Source aspect ratio (common for all panels).

    Returns:
        List of adaptation dicts, one per panel.
    """
    return [
        adapt_panel(panel, source_ratio, target_ratio)
        for panel in panels
    ]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_aspect_adapter tool."""

    @mcp.tool(
        name="adobe_ai_aspect_adapter",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_aspect_adapter(params: AiAspectAdapterInput) -> str:
        """Re-compose panels for different output aspect ratios.

        Actions:
        - adapt: adapt a single panel
        - batch: adapt all panels in a storyboard
        """
        action = params.action.lower().strip()

        try:
            if action == "adapt":
                if params.panel_bounds is None:
                    return json.dumps({"error": "panel_bounds required for adapt"})
                result = adapt_panel(
                    params.panel_bounds,
                    params.source_ratio,
                    params.target_ratio,
                )
                return json.dumps({
                    "action": "adapt",
                    "source_ratio": params.source_ratio,
                    "target_ratio": params.target_ratio,
                    **result,
                }, indent=2)

            elif action == "batch":
                if not params.panels:
                    return json.dumps({"error": "panels list required for batch"})
                results = batch_adapt(
                    params.panels,
                    params.target_ratio,
                    params.source_ratio,
                )
                return json.dumps({
                    "action": "batch",
                    "source_ratio": params.source_ratio,
                    "target_ratio": params.target_ratio,
                    "panel_count": len(results),
                    "adaptations": results,
                }, indent=2)

            else:
                return json.dumps({
                    "error": f"Unknown action: {action}",
                    "valid_actions": ["adapt", "batch"],
                })

        except ValueError as e:
            return json.dumps({"error": str(e)})
