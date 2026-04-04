"""3D camera simulation for illustration framing.

Provides pure-Python camera math:
- Focal length ↔ field of view conversion
- Visible frame width at a given distance
- Camera suggestion for desired framing

Useful for setting up perspective-correct illustration compositions
that match real camera behavior.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCamera3dInput(BaseModel):
    """Camera simulation for 3D-informed illustration framing."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: compute_fov, compute_framing, suggest_camera, status"
    )
    focal_mm: Optional[float] = Field(
        default=None, description="Focal length in mm", gt=0
    )
    sensor_mm: float = Field(
        default=36.0, description="Sensor width in mm (36mm = full frame)", gt=0
    )
    fov_deg: Optional[float] = Field(
        default=None, description="Field of view in degrees", gt=0, lt=180
    )
    distance: Optional[float] = Field(
        default=None, description="Distance from camera to subject", gt=0
    )
    scene_width: Optional[float] = Field(
        default=None, description="Desired visible scene width for camera suggestion", gt=0
    )
    target: str = Field(
        default="medium",
        description="Framing target: 'close' (head), 'medium' (torso), 'wide' (full body), 'extreme_wide' (environment)",
    )


# ---------------------------------------------------------------------------
# Camera math functions
# ---------------------------------------------------------------------------


def focal_length_to_fov(focal_mm: float, sensor_mm: float = 36.0) -> float:
    """Convert focal length to horizontal field of view angle in degrees.

    Uses the standard photography formula:
        FOV = 2 * atan(sensor_width / (2 * focal_length))

    Args:
        focal_mm: lens focal length in millimeters
        sensor_mm: sensor width in mm (default 36mm for full-frame)

    Returns:
        Field of view in degrees.

    Raises:
        ValueError: if focal_mm or sensor_mm is non-positive.
    """
    if focal_mm <= 0:
        raise ValueError("focal_mm must be positive")
    if sensor_mm <= 0:
        raise ValueError("sensor_mm must be positive")

    fov_rad = 2.0 * math.atan(sensor_mm / (2.0 * focal_mm))
    return round(math.degrees(fov_rad), 4)


def fov_to_frame_width(fov_deg: float, distance: float) -> float:
    """Compute the visible width at a given distance for a field of view.

    Args:
        fov_deg: horizontal field of view in degrees
        distance: distance from camera to subject plane

    Returns:
        Visible width at that distance (same units as distance).

    Raises:
        ValueError: if fov_deg is out of (0, 180) or distance is non-positive.
    """
    if fov_deg <= 0 or fov_deg >= 180:
        raise ValueError("fov_deg must be between 0 and 180 (exclusive)")
    if distance <= 0:
        raise ValueError("distance must be positive")

    fov_rad = math.radians(fov_deg)
    width = 2.0 * distance * math.tan(fov_rad / 2.0)
    return round(width, 4)


def suggest_camera(
    scene_width: float,
    distance: float,
    target: str = "medium",
    sensor_mm: float = 36.0,
) -> dict:
    """Suggest a focal length to achieve desired framing.

    Framing targets control how much of the scene width is visible:
        - close: 30% of scene_width visible (tight on subject)
        - medium: 60% of scene_width visible
        - wide: 100% of scene_width visible
        - extreme_wide: 150% of scene_width visible

    Args:
        scene_width: total width of the scene
        distance: camera-to-subject distance
        target: framing target name
        sensor_mm: sensor width in mm

    Returns:
        Dict with focal_mm, fov_deg, visible_width, and framing info.

    Raises:
        ValueError: if parameters are invalid.
    """
    if scene_width <= 0:
        raise ValueError("scene_width must be positive")
    if distance <= 0:
        raise ValueError("distance must be positive")

    # Framing multipliers: what fraction of scene_width to show
    framing_map = {
        "close": 0.3,
        "medium": 0.6,
        "wide": 1.0,
        "extreme_wide": 1.5,
    }

    if target not in framing_map:
        raise ValueError(
            f"Unknown target '{target}'. "
            f"Valid: {list(framing_map.keys())}"
        )

    multiplier = framing_map[target]
    visible_width = scene_width * multiplier

    # Reverse the FOV formula to find focal length:
    # visible_width = 2 * distance * tan(FOV/2)
    # FOV/2 = atan(visible_width / (2 * distance))
    # FOV = 2 * atan(sensor / (2 * focal))
    # → focal = sensor / (2 * tan(atan(visible_width / (2 * distance))))
    half_angle = math.atan(visible_width / (2.0 * distance))
    focal_mm = sensor_mm / (2.0 * math.tan(half_angle))

    fov_deg = focal_length_to_fov(focal_mm, sensor_mm)

    # Classify the lens type
    if focal_mm < 24:
        lens_type = "ultra-wide"
    elif focal_mm < 35:
        lens_type = "wide"
    elif focal_mm < 60:
        lens_type = "normal"
    elif focal_mm < 105:
        lens_type = "short telephoto"
    else:
        lens_type = "telephoto"

    return {
        "focal_mm": round(focal_mm, 2),
        "fov_deg": fov_deg,
        "visible_width": round(visible_width, 4),
        "lens_type": lens_type,
        "target": target,
        "framing_multiplier": multiplier,
        "distance": distance,
        "sensor_mm": sensor_mm,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_camera_3d tool."""

    @mcp.tool(
        name="adobe_ai_camera_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_camera_3d(params: AiCamera3dInput) -> str:
        """Camera simulation for 3D-informed illustration framing.

        Actions:
        - compute_fov: convert focal length to field of view
        - compute_framing: compute visible width at distance
        - suggest_camera: suggest focal length for desired framing
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "supported_actions": ["compute_fov", "compute_framing", "suggest_camera", "status"],
                "default_sensor_mm": 36.0,
                "framing_targets": ["close", "medium", "wide", "extreme_wide"],
            }, indent=2)

        # ── compute_fov ────────────────────────────────────────────
        if action == "compute_fov":
            if not params.focal_mm:
                return json.dumps({"error": "focal_mm is required for compute_fov"})
            try:
                fov = focal_length_to_fov(params.focal_mm, params.sensor_mm)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            return json.dumps({
                "action": "compute_fov",
                "focal_mm": params.focal_mm,
                "sensor_mm": params.sensor_mm,
                "fov_deg": fov,
            }, indent=2)

        # ── compute_framing ─────────────────────────────────────────
        if action == "compute_framing":
            if not params.fov_deg:
                return json.dumps({"error": "fov_deg is required for compute_framing"})
            if not params.distance:
                return json.dumps({"error": "distance is required for compute_framing"})
            try:
                width = fov_to_frame_width(params.fov_deg, params.distance)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            return json.dumps({
                "action": "compute_framing",
                "fov_deg": params.fov_deg,
                "distance": params.distance,
                "visible_width": width,
            }, indent=2)

        # ── suggest_camera ──────────────────────────────────────────
        if action == "suggest_camera":
            if not params.scene_width:
                return json.dumps({"error": "scene_width is required for suggest_camera"})
            if not params.distance:
                return json.dumps({"error": "distance is required for suggest_camera"})
            try:
                result = suggest_camera(
                    params.scene_width,
                    params.distance,
                    params.target,
                    params.sensor_mm,
                )
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            return json.dumps({
                "action": "suggest_camera",
                **result,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["compute_fov", "compute_framing", "suggest_camera", "status"],
        })
