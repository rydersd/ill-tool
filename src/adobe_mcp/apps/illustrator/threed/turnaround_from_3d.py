"""Auto character sheet from 3D model.

Computes camera positions for turnaround views (front, side, back, 3/4)
and lays out the resulting renders on a page grid for a character sheet.

Pure Python — no JSX, no 3D engine required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiTurnaroundFrom3dInput(BaseModel):
    """Generate character turnaround sheet from 3D model data."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: generate_sheet, status",
    )
    n_views: int = Field(
        default=4,
        description="Number of turnaround views (e.g. 4 = front/right/back/left)",
    )
    camera_distance: float = Field(
        default=5.0,
        description="Camera orbit distance from model center",
    )
    camera_height: float = Field(
        default=1.0,
        description="Camera Y (height) offset",
    )
    page_width: float = Field(
        default=1920.0,
        description="Output page width in pixels",
    )
    page_height: float = Field(
        default=1080.0,
        description="Output page height in pixels",
    )
    margin: float = Field(
        default=40.0,
        description="Margin around each view cell in pixels",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for labeling",
    )


# ---------------------------------------------------------------------------
# Standard view labels by count
# ---------------------------------------------------------------------------

VIEW_LABELS = {
    1: ["front"],
    2: ["front", "side_right"],
    3: ["front", "three_quarter", "side_right"],
    4: ["front", "three_quarter", "side_right", "back"],
    5: ["front", "three_quarter_right", "side_right", "back", "side_left"],
    6: ["front", "three_quarter_right", "side_right", "back", "side_left", "three_quarter_left"],
    8: ["front", "front_3q_right", "side_right", "back_3q_right",
        "back", "back_3q_left", "side_left", "front_3q_left"],
}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def compute_turnaround_cameras(
    n_views: int = 4,
    distance: float = 5.0,
    height: float = 1.0,
) -> list[dict]:
    """Compute camera positions for turnaround views.

    Cameras are evenly distributed on a circle around the Y axis,
    starting at angle 0 (front) and proceeding clockwise when viewed
    from above.

    Args:
        n_views: number of evenly-spaced views (minimum 1, maximum 36).
        distance: radial distance from the model center.
        height: camera Y position (elevation).

    Returns:
        list of dicts, each with:
        - ``label``: human-readable view name
        - ``angle_deg``: rotation angle in degrees (0 = front)
        - ``position``: [x, y, z] camera world position
        - ``look_at``: [x, y, z] target point (always model center)
    """
    n_views = max(1, min(n_views, 36))
    distance = max(0.1, distance)

    labels = VIEW_LABELS.get(n_views)
    if labels is None:
        labels = [f"view_{i}" for i in range(n_views)]

    cameras = []
    for i in range(n_views):
        angle_deg = (360.0 / n_views) * i
        angle_rad = math.radians(angle_deg)

        # Camera on XZ plane, Y = height
        # Front (angle 0) → camera at +Z
        x = distance * math.sin(angle_rad)
        z = distance * math.cos(angle_rad)

        cameras.append({
            "label": labels[i] if i < len(labels) else f"view_{i}",
            "angle_deg": round(angle_deg, 2),
            "position": [round(x, 4), round(height, 4), round(z, 4)],
            "look_at": [0.0, 0.0, 0.0],
        })

    return cameras


def layout_turnaround_sheet(
    n_views: int,
    page_width: float,
    page_height: float,
    margin: float = 40.0,
) -> dict:
    """Compute grid layout for placing turnaround views on a page.

    Determines the optimal number of columns and rows, then computes
    cell positions for each view.

    Args:
        n_views: number of views to layout.
        page_width: total page width in pixels.
        page_height: total page height in pixels.
        margin: margin around each cell in pixels.

    Returns:
        dict with grid parameters and a list of cell rects.
    """
    n_views = max(1, n_views)
    page_width = max(100, page_width)
    page_height = max(100, page_height)
    margin = max(0, margin)

    # Determine grid dimensions: prefer wider layout (more columns)
    # Find the column count that gives cells closest to square aspect ratio
    best_cols = 1
    best_ratio_diff = float("inf")

    for cols in range(1, n_views + 1):
        rows = math.ceil(n_views / cols)
        cell_w = (page_width - margin * (cols + 1)) / cols
        cell_h = (page_height - margin * (rows + 1)) / rows
        if cell_w <= 0 or cell_h <= 0:
            continue
        ratio = cell_w / cell_h
        diff = abs(ratio - 1.0)  # How far from square
        if diff < best_ratio_diff:
            best_ratio_diff = diff
            best_cols = cols

    cols = best_cols
    rows = math.ceil(n_views / cols)

    cell_width = (page_width - margin * (cols + 1)) / cols
    cell_height = (page_height - margin * (rows + 1)) / rows

    cells = []
    for i in range(n_views):
        col = i % cols
        row = i // cols
        x = margin + col * (cell_width + margin)
        y = margin + row * (cell_height + margin)

        cells.append({
            "index": i,
            "column": col,
            "row": row,
            "x": round(x, 2),
            "y": round(y, 2),
            "width": round(cell_width, 2),
            "height": round(cell_height, 2),
        })

    return {
        "columns": cols,
        "rows": rows,
        "cell_width": round(cell_width, 2),
        "cell_height": round(cell_height, 2),
        "margin": margin,
        "page_width": page_width,
        "page_height": page_height,
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_turnaround_from_3d tool."""

    @mcp.tool(
        name="adobe_ai_turnaround_from_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_turnaround_from_3d(params: AiTurnaroundFrom3dInput) -> str:
        """Generate character turnaround sheet layout from 3D model.

        Actions:
        - generate_sheet: compute cameras and page layout for turnaround views
        - status: show configuration and readiness
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "turnaround_from_3d",
                "available_view_counts": sorted(VIEW_LABELS.keys()),
                "ready": True,
            }, indent=2)

        elif action == "generate_sheet":
            cameras = compute_turnaround_cameras(
                n_views=params.n_views,
                distance=params.camera_distance,
                height=params.camera_height,
            )
            layout = layout_turnaround_sheet(
                n_views=params.n_views,
                page_width=params.page_width,
                page_height=params.page_height,
                margin=params.margin,
            )

            return json.dumps({
                "action": "generate_sheet",
                "character_name": params.character_name,
                "cameras": cameras,
                "layout": layout,
                "view_count": len(cameras),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["generate_sheet", "status"],
            })
