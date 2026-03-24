"""Speed/motion lines and impact lines based on movement direction.

Generates line geometry for conveying motion and impact in panels.

Pure Python — no JSX or Adobe required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiActionLinesInput(BaseModel):
    """Generate speed/motion or impact lines."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="motion",
        description="Action: 'motion' for speed lines, 'impact' for radial lines",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    direction_angle: float = Field(
        default=0.0,
        description="Movement direction in degrees (0=right, 90=up)",
    )
    origin: list[float] = Field(
        default=[0.0, 0.0],
        description="[x, y] origin point of the motion or impact",
    )
    length: float = Field(
        default=100.0,
        description="Length of each line",
        gt=0,
    )
    count: int = Field(
        default=8,
        description="Number of lines to generate",
        ge=1, le=100,
    )
    spread: float = Field(
        default=15.0,
        description="Angle spread in degrees (wider = more dramatic)",
        ge=0, le=180,
    )
    radius: float = Field(
        default=50.0,
        description="Radius for impact lines (distance from center)",
        gt=0,
    )


# ---------------------------------------------------------------------------
# Line generation
# ---------------------------------------------------------------------------


def generate_action_lines(
    direction_angle: float,
    origin: list[float],
    length: float,
    count: int = 8,
    spread: float = 15.0,
) -> list[dict]:
    """Generate parallel speed/motion lines emanating from behind a moving object.

    Lines fan out behind the object in the opposite direction of travel.

    Args:
        direction_angle: Degrees (0=right, 90=up).
        origin: [x, y] origin point.
        length: Length of each line.
        count: Number of lines.
        spread: Angular spread in degrees.

    Returns:
        List of dicts with 'start' and 'end' coordinate pairs.
    """
    # Lines go in the OPPOSITE direction of travel (trailing behind)
    base_angle_rad = math.radians(direction_angle + 180)

    lines = []
    if count == 1:
        offsets = [0.0]
    else:
        # Distribute lines evenly across the spread
        half_spread_rad = math.radians(spread / 2)
        offsets = [
            -half_spread_rad + i * (2 * half_spread_rad) / (count - 1)
            for i in range(count)
        ]

    ox, oy = origin

    for offset in offsets:
        angle = base_angle_rad + offset
        dx = math.cos(angle) * length
        dy = math.sin(angle) * length

        # Start at origin, end at computed distance
        lines.append({
            "start": [ox, oy],
            "end": [ox + dx, oy + dy],
        })

    return lines


def generate_impact_lines(
    center: list[float],
    radius: float,
    count: int = 12,
) -> list[dict]:
    """Generate radial lines from a center point (for impacts, explosions).

    Lines emanate outward from the center in all directions.

    Args:
        center: [x, y] center of the impact.
        radius: Length of each radial line.
        count: Number of lines (evenly distributed around 360 degrees).

    Returns:
        List of dicts with 'start' and 'end' coordinate pairs.
    """
    cx, cy = center
    lines = []

    for i in range(count):
        angle = (2 * math.pi * i) / count
        dx = math.cos(angle) * radius
        dy = math.sin(angle) * radius
        lines.append({
            "start": [cx, cy],
            "end": [cx + dx, cy + dy],
        })

    return lines


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_action_lines tool."""

    @mcp.tool(
        name="adobe_ai_action_lines",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_action_lines(params: AiActionLinesInput) -> str:
        """Generate speed/motion lines or impact lines.

        Actions:
        - motion: parallel trailing lines behind a moving object
        - impact: radial burst lines from a center point
        """
        action = params.action.lower().strip()

        if action == "motion":
            lines = generate_action_lines(
                direction_angle=params.direction_angle,
                origin=params.origin,
                length=params.length,
                count=params.count,
                spread=params.spread,
            )
            return json.dumps({
                "action": "motion",
                "direction_angle": params.direction_angle,
                "line_count": len(lines),
                "lines": lines,
            }, indent=2)

        elif action == "impact":
            lines = generate_impact_lines(
                center=params.origin,
                radius=params.radius,
                count=params.count,
            )
            return json.dumps({
                "action": "impact",
                "center": params.origin,
                "line_count": len(lines),
                "lines": lines,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["motion", "impact"],
            })
