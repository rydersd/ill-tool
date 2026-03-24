"""AE expressions for camera effects (shake, zoom, pan, dolly zoom).

Generates After Effects expression strings for common camera movements.

Pure Python — no JSX or Adobe required.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCameraExpressionsInput(BaseModel):
    """Generate AE camera effect expressions."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: shake, zoom, pan, dolly_zoom",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    amplitude: float = Field(
        default=5.0,
        description="Shake amplitude in pixels",
        ge=0,
    )
    frequency: float = Field(
        default=3.0,
        description="Shake frequency in Hz",
        ge=0,
    )
    decay: float = Field(
        default=0.95,
        description="Shake decay factor per second (0-1)",
        ge=0, le=1,
    )
    start_scale: float = Field(
        default=100.0,
        description="Start zoom scale (%)",
    )
    end_scale: float = Field(
        default=150.0,
        description="End zoom scale (%)",
    )
    start_pos: Optional[list[float]] = Field(
        default=None,
        description="[x, y] start position for pan",
    )
    end_pos: Optional[list[float]] = Field(
        default=None,
        description="[x, y] end position for pan",
    )
    duration_sec: float = Field(
        default=2.0,
        description="Duration of the effect in seconds",
        gt=0,
    )
    start_fov: float = Field(
        default=50.0,
        description="Start field of view for dolly zoom (degrees)",
        gt=0,
    )
    end_fov: float = Field(
        default=80.0,
        description="End field of view for dolly zoom (degrees)",
        gt=0,
    )


# ---------------------------------------------------------------------------
# Expression generators
# ---------------------------------------------------------------------------


def generate_shake_expression(
    amplitude: float = 5.0,
    frequency: float = 3.0,
    decay: float = 0.95,
) -> str:
    """Generate AE expression for camera shake with decay.

    Returns an After Effects expression string that produces a
    wiggle effect decaying over time.
    """
    return (
        f"// Camera shake with decay\n"
        f"var amp = {amplitude};\n"
        f"var freq = {frequency};\n"
        f"var decay = {decay};\n"
        f"var t = time - inPoint;\n"
        f"var decayFactor = Math.pow(decay, t);\n"
        f"var shake = wiggle(freq, amp);\n"
        f"var delta = shake - value;\n"
        f"value + delta * decayFactor;"
    )


def generate_zoom_expression(
    start_scale: float = 100.0,
    end_scale: float = 150.0,
    duration_sec: float = 2.0,
) -> str:
    """Generate AE expression for smooth zoom (scale interpolation).

    Returns an AE expression using linear() for scale interpolation.
    """
    return (
        f"// Smooth zoom\n"
        f"var startScale = {start_scale};\n"
        f"var endScale = {end_scale};\n"
        f"var dur = {duration_sec};\n"
        f"var s = linear(time, inPoint, inPoint + dur, startScale, endScale);\n"
        f"[s, s];"
    )


def generate_pan_expression(
    start_pos: list[float],
    end_pos: list[float],
    duration_sec: float = 2.0,
) -> str:
    """Generate AE position expression for a camera pan.

    Interpolates position from start to end over the given duration.
    """
    sx, sy = start_pos
    ex, ey = end_pos
    return (
        f"// Camera pan\n"
        f"var startPos = [{sx}, {sy}];\n"
        f"var endPos = [{ex}, {ey}];\n"
        f"var dur = {duration_sec};\n"
        f"var x = linear(time, inPoint, inPoint + dur, startPos[0], endPos[0]);\n"
        f"var y = linear(time, inPoint, inPoint + dur, startPos[1], endPos[1]);\n"
        f"[x, y];"
    )


def generate_dolly_zoom(
    start_fov: float = 50.0,
    end_fov: float = 80.0,
    duration_sec: float = 3.0,
) -> str:
    """Generate AE expression for the vertigo / dolly zoom effect.

    Zooms in while increasing FOV (or vice versa) to maintain subject
    size while dramatically changing perspective.
    """
    return (
        f"// Dolly zoom (vertigo effect)\n"
        f"var startFOV = {start_fov};\n"
        f"var endFOV = {end_fov};\n"
        f"var dur = {duration_sec};\n"
        f"var fov = linear(time, inPoint, inPoint + dur, startFOV, endFOV);\n"
        f"// Compensate position to maintain subject size\n"
        f"var subjectDist = 500;  // distance to subject in pixels\n"
        f"var startTan = Math.tan(degreesToRadians(startFOV / 2));\n"
        f"var curTan = Math.tan(degreesToRadians(fov / 2));\n"
        f"var zOffset = subjectDist * (startTan / curTan - 1);\n"
        f"value + [0, 0, zOffset];"
    )


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_camera_expressions tool."""

    @mcp.tool(
        name="adobe_ai_camera_expressions",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_camera_expressions(params: AiCameraExpressionsInput) -> str:
        """Generate AE expressions for camera effects.

        Actions:
        - shake: wiggle-based camera shake with temporal decay
        - zoom: linear scale interpolation
        - pan: linear position interpolation
        - dolly_zoom: vertigo effect (zoom + FOV change)
        """
        action = params.action.lower().strip()

        if action == "shake":
            expr = generate_shake_expression(
                amplitude=params.amplitude,
                frequency=params.frequency,
                decay=params.decay,
            )
            return json.dumps({
                "action": "shake",
                "expression": expr,
                "amplitude": params.amplitude,
                "frequency": params.frequency,
                "decay": params.decay,
            }, indent=2)

        elif action == "zoom":
            expr = generate_zoom_expression(
                start_scale=params.start_scale,
                end_scale=params.end_scale,
                duration_sec=params.duration_sec,
            )
            return json.dumps({
                "action": "zoom",
                "expression": expr,
                "start_scale": params.start_scale,
                "end_scale": params.end_scale,
                "duration_sec": params.duration_sec,
            }, indent=2)

        elif action == "pan":
            sp = params.start_pos or [0, 0]
            ep = params.end_pos or [960, 0]
            expr = generate_pan_expression(
                start_pos=sp,
                end_pos=ep,
                duration_sec=params.duration_sec,
            )
            return json.dumps({
                "action": "pan",
                "expression": expr,
                "start_pos": sp,
                "end_pos": ep,
                "duration_sec": params.duration_sec,
            }, indent=2)

        elif action == "dolly_zoom":
            expr = generate_dolly_zoom(
                start_fov=params.start_fov,
                end_fov=params.end_fov,
                duration_sec=params.duration_sec,
            )
            return json.dumps({
                "action": "dolly_zoom",
                "expression": expr,
                "start_fov": params.start_fov,
                "end_fov": params.end_fov,
                "duration_sec": params.duration_sec,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["shake", "zoom", "pan", "dolly_zoom"],
            })
