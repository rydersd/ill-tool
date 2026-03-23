"""Auto-generate model sheet spec from rigged character.

Computes layout for multiple turnaround views, proportion guide lines,
color swatches, and annotation text suitable for rendering via JSX.

Pure Python — no JSX or Adobe required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCharacterSheetGenInput(BaseModel):
    """Generate model/character sheet spec from rig data."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="generate",
        description="Action: generate (full sheet spec) or layout (grid only)",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    views: Optional[list[int]] = Field(
        default=None,
        description="List of rotation angles in degrees (default: [0, 30, 90, 180])",
    )
    page_width: float = Field(
        default=2400.0,
        description="Page width in points",
        gt=0,
    )
    page_height: float = Field(
        default=1800.0,
        description="Page height in points",
        gt=0,
    )
    character_height: float = Field(
        default=600.0,
        description="Character height in the sheet",
        gt=0,
    )
    character_palette: Optional[list[str]] = Field(
        default=None,
        description="Hex color strings for character color swatches",
    )
    landmark_heights: Optional[dict[str, float]] = Field(
        default=None,
        description="Named landmarks as fractions of height (0=top, 1=bottom)",
    )
    annotations: Optional[dict[str, str]] = Field(
        default=None,
        description="Key-value annotation text (e.g. name, height, notes)",
    )


# ---------------------------------------------------------------------------
# Default landmarks (fraction from top of character)
# ---------------------------------------------------------------------------


DEFAULT_LANDMARKS = {
    "head_top": 0.0,
    "chin": 0.12,
    "shoulder": 0.18,
    "chest": 0.30,
    "waist": 0.42,
    "hip": 0.50,
    "knee": 0.72,
    "ankle": 0.90,
    "foot": 1.0,
}

# Default turnaround angles
DEFAULT_VIEWS = [0, 30, 90, 180]

# Layout margins and spacing
_MARGIN_X = 60.0
_MARGIN_Y = 120.0
_SWATCH_SIZE = 30.0
_SWATCH_GAP = 8.0
_ANNOTATION_HEIGHT = 160.0


# ---------------------------------------------------------------------------
# Layout computation
# ---------------------------------------------------------------------------


def sheet_layout(
    view_count: int,
    page_size: tuple[float, float],
    character_height: float = 600.0,
) -> dict:
    """Compute layout grid for views and annotation areas.

    Distributes views horizontally with equal spacing, leaving room
    for annotations and color swatches below.

    Args:
        view_count: Number of turnaround views.
        page_size: (width, height) of the sheet page.
        character_height: Height allocated to each character view.

    Returns:
        Dict with view_rects, annotation_area, and swatch_area.
    """
    pw, ph = page_size

    # Usable area after margins
    usable_w = pw - 2 * _MARGIN_X
    usable_h = ph - 2 * _MARGIN_Y - _ANNOTATION_HEIGHT

    # Character views are arranged horizontally
    view_width = usable_w / max(view_count, 1)
    view_height = min(character_height, usable_h)

    # Center views vertically in the usable area
    views_top = _MARGIN_Y + (usable_h - view_height) / 2

    view_rects = []
    for i in range(view_count):
        vx = _MARGIN_X + i * view_width
        view_rects.append({
            "index": i,
            "x": round(vx, 2),
            "y": round(views_top, 2),
            "width": round(view_width, 2),
            "height": round(view_height, 2),
        })

    # Annotation area below views
    annotation_y = _MARGIN_Y + usable_h
    annotation_area = {
        "x": _MARGIN_X,
        "y": round(annotation_y, 2),
        "width": round(usable_w, 2),
        "height": _ANNOTATION_HEIGHT,
    }

    # Swatch area: right portion of annotation area
    swatch_area = {
        "x": round(pw - _MARGIN_X - 300, 2),
        "y": round(annotation_y + 10, 2),
        "width": 280.0,
        "height": 60.0,
    }

    return {
        "page_size": [pw, ph],
        "view_count": view_count,
        "view_rects": view_rects,
        "annotation_area": annotation_area,
        "swatch_area": swatch_area,
    }


# ---------------------------------------------------------------------------
# Full sheet spec
# ---------------------------------------------------------------------------


def generate_sheet_spec(
    rig: dict,
    views: Optional[list[int]] = None,
    page_size: tuple[float, float] = (2400.0, 1800.0),
    character_height: float = 600.0,
    character_palette: Optional[list[str]] = None,
    landmark_heights: Optional[dict[str, float]] = None,
    annotations: Optional[dict[str, str]] = None,
) -> dict:
    """Generate a complete model sheet specification from rig data.

    Produces a data structure describing:
    - View layout positions for each turnaround angle
    - Proportion guide lines at landmark heights
    - Color swatches
    - Annotation text blocks

    Args:
        rig: Character rig dict.
        views: Turnaround angles (degrees). Default: [0, 30, 90, 180].
        page_size: (width, height) page dimensions.
        character_height: Height of each character view.
        character_palette: Hex color list for swatches.
        landmark_heights: Named landmark fractions (0=top, 1=bottom).
        annotations: Key-value annotation strings.

    Returns:
        Dict with layout, views, guides, swatches, and annotations.
    """
    if views is None:
        views = list(DEFAULT_VIEWS)

    layout = sheet_layout(len(views), page_size, character_height)

    # View specs with turnaround transforms
    view_specs = []
    for i, angle in enumerate(views):
        rect = layout["view_rects"][i] if i < len(layout["view_rects"]) else None
        label = _angle_label(angle)
        view_specs.append({
            "angle": angle,
            "label": label,
            "rect": rect,
            "transform": {
                "rotation_y": angle,
                "flip_x": angle > 90,
            },
        })

    # Proportion guide lines
    landmarks = landmark_heights if landmark_heights else dict(DEFAULT_LANDMARKS)
    guides = []
    for name, frac in sorted(landmarks.items(), key=lambda kv: kv[1]):
        # Guide line spans the full width of all views
        line_y = layout["view_rects"][0]["y"] + frac * character_height if layout["view_rects"] else 0
        guides.append({
            "name": name,
            "fraction": frac,
            "y": round(line_y, 2),
            "x_start": layout["view_rects"][0]["x"] if layout["view_rects"] else 0,
            "x_end": (
                layout["view_rects"][-1]["x"] + layout["view_rects"][-1]["width"]
                if layout["view_rects"] else page_size[0]
            ),
        })

    # Color swatches
    palette = character_palette or rig.get("palette", [])
    swatches = []
    swatch_area = layout["swatch_area"]
    for i, color in enumerate(palette):
        sx = swatch_area["x"] + i * (_SWATCH_SIZE + _SWATCH_GAP)
        swatches.append({
            "color": color,
            "x": round(sx, 2),
            "y": swatch_area["y"],
            "size": _SWATCH_SIZE,
        })

    # Annotation text
    anno = annotations or {}
    char_name = anno.get("name", rig.get("character_name", "Character"))
    anno_area = layout["annotation_area"]
    annotation_blocks = [
        {"key": "name", "value": char_name, "x": anno_area["x"], "y": anno_area["y"] + 20, "size": 24},
    ]
    y_offset = 50
    for key, value in anno.items():
        if key == "name":
            continue
        annotation_blocks.append({
            "key": key,
            "value": value,
            "x": anno_area["x"],
            "y": anno_area["y"] + y_offset,
            "size": 14,
        })
        y_offset += 22

    return {
        "layout": layout,
        "views": view_specs,
        "guides": guides,
        "swatches": swatches,
        "annotations": annotation_blocks,
        "view_count": len(views),
        "page_size": list(page_size),
    }


def _angle_label(angle: int) -> str:
    """Generate a human-readable label for a turnaround angle."""
    labels = {
        0: "Front",
        30: "3/4 Front",
        45: "3/4",
        90: "Side",
        135: "3/4 Back",
        180: "Back",
        270: "Side (mirror)",
        360: "Front",
    }
    return labels.get(angle, f"{angle}°")


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_sheet_gen tool."""

    @mcp.tool(
        name="adobe_ai_character_sheet_gen",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_sheet_gen(params: AiCharacterSheetGenInput) -> str:
        """Generate model/character sheet specifications.

        Actions:
        - generate: full sheet spec with views, guides, swatches, annotations
        - layout: compute the layout grid only
        """
        action = params.action.lower().strip()

        if action == "generate":
            # Build a minimal rig dict from params
            rig = {"character_name": params.character_name}
            if params.character_palette:
                rig["palette"] = params.character_palette

            spec = generate_sheet_spec(
                rig=rig,
                views=params.views,
                page_size=(params.page_width, params.page_height),
                character_height=params.character_height,
                character_palette=params.character_palette,
                landmark_heights=params.landmark_heights,
                annotations=params.annotations,
            )
            return json.dumps({
                "action": "generate",
                **spec,
            }, indent=2)

        elif action == "layout":
            view_count = len(params.views) if params.views else 4
            layout = sheet_layout(
                view_count,
                (params.page_width, params.page_height),
                params.character_height,
            )
            return json.dumps({
                "action": "layout",
                **layout,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["generate", "layout"],
            })
