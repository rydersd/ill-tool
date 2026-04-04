"""CharacterGen A-pose canonical normalization (optional dependency).

Takes a character image in any pose and produces an A-pose normalized
version where arms are at approximately 45 degrees from the body.
This canonical pose is useful for rigging and animation pipelines.

Falls back gracefully when ML dependencies are not installed.
"""

import json
import math
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Graceful ML dependency import
# ---------------------------------------------------------------------------

try:
    import torch
    from transformers import AutoModelForCausalLM
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class CharacterAPoseInput(BaseModel):
    """Control CharacterGen A-pose canonicalization."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, canonicalize",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to character image (any pose)"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory for output (defaults to temp)"
    )
    tolerance_degrees: float = Field(
        default=15.0,
        description="Tolerance in degrees for A-pose validation",
        ge=1.0,
        le=45.0,
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------

# A-pose target angles (degrees from vertical/body axis)
# Arms should be approximately 45 degrees from body sides
APOSE_TARGET_ANGLES = {
    "shoulder_to_elbow_l": 45.0,   # Left upper arm angle from body
    "shoulder_to_elbow_r": -45.0,  # Right upper arm angle from body (mirrored)
    "elbow_to_wrist_l": 45.0,     # Left forearm continues same angle
    "elbow_to_wrist_r": -45.0,    # Right forearm continues same angle
    "hip_to_knee_l": 0.0,         # Legs straight down
    "hip_to_knee_r": 0.0,         # Legs straight down
}


def is_apose(
    joint_angles: Dict[str, float],
    tolerance_degrees: float = 15.0,
) -> dict:
    """Check if the given joint angles are near canonical A-pose.

    A-pose has arms at approximately 45 degrees from the body axis,
    with legs straight down.

    Args:
        joint_angles: Dict mapping joint pair name to angle in degrees.
            Expected keys match APOSE_TARGET_ANGLES keys.
        tolerance_degrees: How many degrees off from target is acceptable.

    Returns:
        Dict with is_apose bool, per-joint deviations, and overall score.
    """
    if not joint_angles:
        return {
            "is_apose": False,
            "error": "No joint angles provided",
            "deviations": {},
            "score": 0.0,
        }

    deviations = {}
    within_tolerance = 0
    total_checked = 0

    for joint_name, target_angle in APOSE_TARGET_ANGLES.items():
        if joint_name not in joint_angles:
            continue

        actual_angle = joint_angles[joint_name]
        deviation = abs(actual_angle - target_angle)

        # Normalize to [-180, 180] range
        if deviation > 180:
            deviation = 360 - deviation

        deviations[joint_name] = {
            "actual": actual_angle,
            "target": target_angle,
            "deviation": round(deviation, 2),
            "within_tolerance": deviation <= tolerance_degrees,
        }

        total_checked += 1
        if deviation <= tolerance_degrees:
            within_tolerance += 1

    # Score: fraction of checked joints within tolerance
    score = within_tolerance / total_checked if total_checked > 0 else 0.0

    return {
        "is_apose": score >= 0.8,  # At least 80% of joints must pass
        "score": round(score, 3),
        "joints_checked": total_checked,
        "joints_passing": within_tolerance,
        "tolerance_degrees": tolerance_degrees,
        "deviations": deviations,
    }


def _ml_status() -> dict:
    """Return availability status for CharacterGen A-pose."""
    status = {
        "ml_available": ML_AVAILABLE,
        "tool": "CharacterGen A-pose canonicalization",
        "target_pose": "A-pose (arms at 45 degrees from body)",
        "apose_targets": APOSE_TARGET_ANGLES,
    }
    if ML_AVAILABLE:
        status["torch_version"] = torch.__version__
        if torch.cuda.is_available():
            status["device"] = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            status["device"] = "mps"
        else:
            status["device"] = "cpu"
    else:
        status["install_hint"] = 'Install ML dependencies with: uv pip install -e ".[ml]"'
        status["required_packages"] = ["torch", "transformers"]
        status["device"] = "unavailable"
    return status


def _canonicalize(
    image_path: str,
    output_dir: Optional[str],
    tolerance_degrees: float,
) -> dict:
    """Run CharacterGen A-pose canonicalization on an image.

    Requires ML dependencies (torch, transformers).
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot canonicalize.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        return {
            "error": "CharacterGen integration pending — model weights setup required.",
            "image_path": image_path,
            "note": "Use is_apose() to validate joint angles from any pose detector.",
        }
    except Exception as exc:
        return {"error": f"Canonicalization failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_apose tool."""

    @mcp.tool(
        name="adobe_ai_character_apose",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_apose(params: CharacterAPoseInput) -> str:
        """CharacterGen A-pose canonical normalization.

        Actions:
        - status: Check ML availability and A-pose targets
        - canonicalize: Normalize character to A-pose

        Requires optional ML dependencies (torch, transformers). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "canonicalize":
            result = _canonicalize(
                params.image_path, params.output_dir, params.tolerance_degrees
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "canonicalize"],
            })
