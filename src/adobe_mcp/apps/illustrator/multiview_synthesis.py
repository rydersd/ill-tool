"""Multi-view synthesis — render 3D model from multiple camera angles.

Computes camera positions evenly distributed around a sphere for
rendering a 3D model from multiple viewpoints.  Pure Python math;
3D rendering is delegated to external tools.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiMultiviewSynthesisInput(BaseModel):
    """Render 3D model from multiple camera angles."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: render_views, status"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    n_views: int = Field(
        default=4,
        description="Number of views to render (4 or 8 are standard)",
        ge=1, le=36,
    )
    radius: float = Field(
        default=5.0, description="Camera distance from origin", gt=0
    )
    elevation_deg: float = Field(
        default=15.0,
        description="Camera elevation above equator in degrees",
        ge=-90.0, le=90.0,
    )
    look_at: Optional[list[float]] = Field(
        default=None,
        description="Target point [x, y, z] the cameras look at (default: origin)",
    )


# ---------------------------------------------------------------------------
# Camera position math
# ---------------------------------------------------------------------------


def compute_camera_positions(
    n_views: int,
    radius: float = 5.0,
    elevation_deg: float = 15.0,
    look_at: Optional[list[float]] = None,
) -> list[dict]:
    """Compute camera positions evenly spaced around a sphere.

    Cameras are placed on a circle at the given elevation above the
    equatorial plane, looking inward at the target point.

    Standard layouts:
        4 views: front (0deg), right (90deg), back (180deg), left (270deg)
        8 views: adds 45deg increments between the 4 cardinal views

    Args:
        n_views: number of cameras to place
        radius: distance from the look_at point
        elevation_deg: degrees above the equator (0=equator, 90=top-down)
        look_at: [x, y, z] target point (default: [0, 0, 0])

    Returns:
        List of dicts with position, azimuth_deg, elevation_deg, look_at,
        and a human-readable label.
    """
    if n_views < 1:
        raise ValueError("n_views must be >= 1")

    target = look_at if look_at else [0.0, 0.0, 0.0]
    elev_rad = math.radians(elevation_deg)

    # Horizontal radius at the given elevation
    r_horiz = radius * math.cos(elev_rad)
    # Vertical offset at the given elevation
    z_offset = radius * math.sin(elev_rad)

    # Standard labels for common view counts
    cardinal_labels = {
        0.0: "front",
        90.0: "right",
        180.0: "back",
        270.0: "left",
        45.0: "front_right",
        135.0: "back_right",
        225.0: "back_left",
        315.0: "front_left",
    }

    cameras = []
    for i in range(n_views):
        azimuth_deg = (360.0 / n_views) * i
        azimuth_rad = math.radians(azimuth_deg)

        # Camera position on the sphere
        cam_x = target[0] + r_horiz * math.sin(azimuth_rad)
        cam_y = target[1] + r_horiz * math.cos(azimuth_rad)
        cam_z = target[2] + z_offset

        # Find label
        label = cardinal_labels.get(round(azimuth_deg, 1), f"view_{i}")

        cameras.append({
            "index": i,
            "label": label,
            "azimuth_deg": round(azimuth_deg, 4),
            "elevation_deg": round(elevation_deg, 4),
            "position": [round(cam_x, 6), round(cam_y, 6), round(cam_z, 6)],
            "look_at": [round(t, 6) for t in target],
        })

    return cameras


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_multiview_synthesis tool."""

    @mcp.tool(
        name="adobe_ai_multiview_synthesis",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_multiview_synthesis(params: AiMultiviewSynthesisInput) -> str:
        """Compute camera positions for multi-view rendering of a 3D model.

        Actions:
        - render_views: compute camera positions evenly around the target
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "supported_view_counts": [4, 8],
                "max_views": 36,
                "supported_actions": ["render_views", "status"],
            }, indent=2)

        # ── render_views ────────────────────────────────────────────
        if action == "render_views":
            cameras = compute_camera_positions(
                n_views=params.n_views,
                radius=params.radius,
                elevation_deg=params.elevation_deg,
                look_at=params.look_at,
            )

            return json.dumps({
                "action": "render_views",
                "character_name": params.character_name,
                "n_views": params.n_views,
                "radius": params.radius,
                "elevation_deg": params.elevation_deg,
                "cameras": cameras,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["render_views", "status"],
        })
