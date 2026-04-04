"""Auto-place speech bubbles relative to characters.

Computes bubble positions, tail geometry, and multi-speaker layout
using reading-order rules (left-to-right, top-to-bottom).

Pure Python — no JSX or Adobe required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiDialogueLayoutInput(BaseModel):
    """Auto-place speech bubbles relative to characters."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="layout",
        description="Action: layout (multiple speakers) or single (one bubble)",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    character_bounds: Optional[list[float]] = Field(
        default=None,
        description="[x, y, w, h] bounding box of the character",
    )
    speaker_side: str = Field(
        default="right",
        description="Side to place bubble: 'left' or 'right'",
    )
    panel_bounds: Optional[list[float]] = Field(
        default=None,
        description="[x, y, w, h] panel bounding box (for clamping)",
    )
    speakers: Optional[list[dict]] = Field(
        default=None,
        description="List of speaker dicts with 'bounds' and 'lines'",
    )
    lines: Optional[list[str]] = Field(
        default=None,
        description="Dialogue lines for a single speaker",
    )
    bubble_padding: float = Field(
        default=12.0,
        description="Padding inside the bubble around text",
        ge=0, le=50,
    )
    line_height: float = Field(
        default=18.0,
        description="Estimated height per line of dialogue text",
        ge=8, le=60,
    )
    bubble_width: float = Field(
        default=140.0,
        description="Default bubble width",
        ge=40, le=500,
    )


# ---------------------------------------------------------------------------
# Bubble geometry
# ---------------------------------------------------------------------------

# Default padding from character head to bubble bottom
_HEAD_OFFSET_Y = 15.0

# Default horizontal offset from character edge to bubble center
_SIDE_OFFSET_X = 20.0

# Tail base width as fraction of bubble width
_TAIL_BASE_FRACTION = 0.15


def compute_bubble_position(
    character_bounds: list[float],
    speaker_side: str = "right",
    panel_bounds: Optional[list[float]] = None,
    line_count: int = 1,
    bubble_padding: float = 12.0,
    line_height: float = 18.0,
    bubble_width: float = 140.0,
) -> dict:
    """Compute a single speech bubble position relative to a character.

    Args:
        character_bounds: [x, y, w, h] character bounding box.
        speaker_side: 'left' or 'right' — which side of the character.
        panel_bounds: Optional [x, y, w, h] panel bounds for clamping.
        line_count: Number of dialogue lines (determines bubble height).
        bubble_padding: Interior padding.
        line_height: Height per text line.
        bubble_width: Width of the bubble.

    Returns:
        Dict with bubble_rect, tail_point, and tail_base.
    """
    cx, cy, cw, ch = character_bounds

    # Bubble dimensions
    text_height = line_count * line_height
    bw = bubble_width
    bh = text_height + 2 * bubble_padding

    # Character head area: top 25% of the character bounding box
    head_y = cy  # top of character
    head_center_x = cx + cw / 2

    # Position bubble above and to the side of the character
    by = head_y - bh - _HEAD_OFFSET_Y  # above the head

    if speaker_side == "left":
        bx = cx - bw - _SIDE_OFFSET_X
    else:
        bx = cx + cw + _SIDE_OFFSET_X

    # Tail points toward the character's head area (top-center)
    tail_point = [head_center_x, head_y]

    # Clamp bubble to panel bounds if provided
    if panel_bounds is not None:
        px, py, pw, ph = panel_bounds
        panel_right = px + pw
        panel_bottom = py + ph

        # Clamp horizontally
        if bx < px:
            bx = px
        if bx + bw > panel_right:
            bx = panel_right - bw

        # Clamp vertically (push down if above panel top)
        if by < py:
            by = py
        if by + bh > panel_bottom:
            by = panel_bottom - bh

    # Tail base: centered on the bottom edge of the bubble, closest to character
    tail_base_half = bw * _TAIL_BASE_FRACTION / 2
    if speaker_side == "left":
        # Tail on right side of bubble (closer to character)
        tail_base_cx = bx + bw
    else:
        # Tail on left side of bubble (closer to character)
        tail_base_cx = bx

    # Clamp tail base center to be within the bubble bottom edge
    tail_base_cx = max(bx + tail_base_half, min(bx + bw - tail_base_half, tail_base_cx))

    tail_base = [
        tail_base_cx - tail_base_half,
        by + bh,
        tail_base_cx + tail_base_half,
        by + bh,
    ]

    return {
        "bubble_rect": [bx, by, bw, bh],
        "tail_point": tail_point,
        "tail_base": tail_base,
    }


def layout_dialogue(
    speakers: list[dict],
    lines: list[list[str]],
    panel_bounds: list[float],
    bubble_padding: float = 12.0,
    line_height: float = 18.0,
    bubble_width: float = 140.0,
) -> list[dict]:
    """Layout multiple speech bubbles for a dialogue sequence.

    Reading order: left-to-right, top-to-bottom.
    Multiple speakers alternate sides.
    Multiple lines from the same speaker stack vertically.

    Args:
        speakers: List of dicts with 'bounds' key ([x,y,w,h]).
        lines: List of line-lists, one per speaker (parallel to speakers).
        panel_bounds: [x, y, w, h] panel bounding box.
        bubble_padding: Padding inside bubbles.
        line_height: Height per text line.
        bubble_width: Width of each bubble.

    Returns:
        List of bubble dicts, one per speaker.
    """
    if not speakers or not lines:
        return []

    # Sort speakers by horizontal position (left-to-right reading order)
    indexed = list(enumerate(speakers))
    indexed.sort(key=lambda pair: pair[1].get("bounds", [0, 0, 0, 0])[0])

    results = []
    prev_bottom = None

    for order_idx, (orig_idx, speaker) in enumerate(indexed):
        bounds = speaker.get("bounds", [0, 0, 0, 0])
        speaker_lines = lines[orig_idx] if orig_idx < len(lines) else ["..."]
        line_count = len(speaker_lines)

        # Alternate sides: even index → right, odd index → left
        side = "right" if order_idx % 2 == 0 else "left"

        bubble = compute_bubble_position(
            character_bounds=bounds,
            speaker_side=side,
            panel_bounds=panel_bounds,
            line_count=line_count,
            bubble_padding=bubble_padding,
            line_height=line_height,
            bubble_width=bubble_width,
        )

        # If same speaker has multiple lines stacking, push down
        if prev_bottom is not None:
            bx, by, bw, bh = bubble["bubble_rect"]
            if by < prev_bottom + 5:
                by = prev_bottom + 5
                bubble["bubble_rect"] = [bx, by, bw, bh]
                # Update tail base y
                bubble["tail_base"][1] = by + bh
                bubble["tail_base"][3] = by + bh

        bubble["speaker_index"] = orig_idx
        bubble["side"] = side
        bubble["lines"] = speaker_lines

        bx, by, bw, bh = bubble["bubble_rect"]
        prev_bottom = by + bh

        results.append(bubble)

    return results


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_dialogue_layout tool."""

    @mcp.tool(
        name="adobe_ai_dialogue_layout",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_dialogue_layout(params: AiDialogueLayoutInput) -> str:
        """Auto-place speech bubbles relative to characters.

        Actions:
        - single: compute one bubble position for one character
        - layout: compute bubble positions for multiple speakers
        """
        action = params.action.lower().strip()

        if action == "single":
            if params.character_bounds is None:
                return json.dumps({"error": "character_bounds required for single bubble"})

            line_count = len(params.lines) if params.lines else 1
            result = compute_bubble_position(
                character_bounds=params.character_bounds,
                speaker_side=params.speaker_side,
                panel_bounds=params.panel_bounds,
                line_count=line_count,
                bubble_padding=params.bubble_padding,
                line_height=params.line_height,
                bubble_width=params.bubble_width,
            )
            return json.dumps(result, indent=2)

        elif action == "layout":
            if not params.speakers:
                return json.dumps({"error": "speakers list required for layout"})
            if params.panel_bounds is None:
                return json.dumps({"error": "panel_bounds required for layout"})

            speaker_lines = [s.get("lines", ["..."]) for s in params.speakers]
            bubbles = layout_dialogue(
                speakers=params.speakers,
                lines=speaker_lines,
                panel_bounds=params.panel_bounds,
                bubble_padding=params.bubble_padding,
                line_height=params.line_height,
                bubble_width=params.bubble_width,
            )
            return json.dumps({
                "action": "layout",
                "bubble_count": len(bubbles),
                "bubbles": bubbles,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["single", "layout"],
            })
