"""SDPose cartoon pose detection via ML (optional dependency).

Provides cartoon character pose detection using SDPose (COCO-WholeBody 133
keypoints).  Maps the detected keypoints to our internal landmark schema
(head_top, chin, shoulder_l, etc.) via a pure-Python mapping function.

Falls back gracefully when ML dependencies are not installed.
"""

import json
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
# Landmark schema — our canonical landmark names
# ---------------------------------------------------------------------------

# COCO-WholeBody 133 keypoint index -> our landmark name
# Body: 0-16, Feet: 17-22, Face: 23-90, Left hand: 91-111, Right hand: 112-132
SDPOSE_TO_LANDMARK: Dict[int, str] = {
    # Core body landmarks
    0: "nose",
    1: "eye_l",
    2: "eye_r",
    3: "ear_l",
    4: "ear_r",
    5: "shoulder_l",
    6: "shoulder_r",
    7: "elbow_l",
    8: "elbow_r",
    9: "wrist_l",
    10: "wrist_r",
    11: "hip_l",
    12: "hip_r",
    13: "knee_l",
    14: "knee_r",
    15: "ankle_l",
    16: "ankle_r",
    # Feet
    17: "big_toe_l",
    18: "small_toe_l",
    19: "heel_l",
    20: "big_toe_r",
    21: "small_toe_r",
    22: "heel_r",
    # Face — selected subset for character illustration
    30: "head_top",
    32: "chin",
    # Hands — wrist roots
    91: "hand_root_l",
    112: "hand_root_r",
}

# Full list of our supported landmark names (for schema validation)
LANDMARK_NAMES = sorted(set(SDPOSE_TO_LANDMARK.values()))


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class LandmarkMLInput(BaseModel):
    """Control SDPose landmark detection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, detect",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to character image for detection"
    )
    confidence_threshold: float = Field(
        default=0.3,
        description="Minimum keypoint confidence to include",
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def map_sdpose_to_landmarks(
    keypoints: List[List[float]],
    confidence_threshold: float = 0.3,
) -> Dict[str, Dict[str, float]]:
    """Map COCO-WholeBody keypoint array to our landmark schema.

    Args:
        keypoints: List of [x, y, confidence] for each of the 133 keypoints.
        confidence_threshold: Minimum confidence to include a landmark.

    Returns:
        Dict mapping landmark name -> {"x": float, "y": float, "confidence": float}
    """
    landmarks: Dict[str, Dict[str, float]] = {}

    for idx, name in SDPOSE_TO_LANDMARK.items():
        if idx >= len(keypoints):
            continue
        kp = keypoints[idx]
        if len(kp) < 3:
            continue
        x, y, conf = kp[0], kp[1], kp[2]
        if conf >= confidence_threshold:
            landmarks[name] = {"x": x, "y": y, "confidence": conf}

    return landmarks


def _ml_status() -> dict:
    """Return status of ML dependencies and model info."""
    status = {
        "ml_available": ML_AVAILABLE,
        "model": "SDPose (COCO-WholeBody 133 keypoints)",
        "keypoint_count": 133,
        "mapped_landmarks": len(SDPOSE_TO_LANDMARK),
        "landmark_names": LANDMARK_NAMES,
    }
    if ML_AVAILABLE:
        status["torch_version"] = torch.__version__
        status["cuda_available"] = torch.cuda.is_available()
        status["mps_available"] = (
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )
        if status["cuda_available"]:
            status["gpu_device"] = "cuda"
        elif status["mps_available"]:
            status["gpu_device"] = "mps"
        else:
            status["gpu_device"] = "cpu"
        status["model_loaded"] = False  # Would be True after first detect call
    else:
        status["install_hint"] = 'Install ML dependencies with: uv pip install -e ".[ml]"'
        status["required_packages"] = ["torch", "transformers"]
        status["gpu_device"] = "unavailable"

    return status


def _detect_landmarks(image_path: str, confidence_threshold: float) -> dict:
    """Run SDPose detection on an image and return mapped landmarks.

    Requires ML dependencies (torch, transformers).
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot run pose detection.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        from PIL import Image

        # Load and preprocess image
        image = Image.open(image_path).convert("RGB")
        width, height = image.size

        # Determine device
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

        # In a real implementation, load SDPose model and run inference
        # For now, this is the integration point where the model would be loaded
        # model = AutoModelForCausalLM.from_pretrained("sdpose/sdpose-coco-wholebody")
        # keypoints = model.detect(image)

        return {
            "error": "SDPose model integration pending — model weights not yet available via HuggingFace.",
            "image_path": image_path,
            "image_size": {"width": width, "height": height},
            "device": device,
            "note": "Use map_sdpose_to_landmarks() with keypoints from any COCO-WholeBody detector.",
        }
    except Exception as exc:
        return {"error": f"Detection failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_landmark_ml tool."""

    @mcp.tool(
        name="adobe_ai_landmark_ml",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_landmark_ml(params: LandmarkMLInput) -> str:
        """SDPose cartoon pose detection with landmark mapping.

        Actions:
        - status: Check ML availability, GPU info, supported landmarks
        - detect: Run SDPose on an image, return mapped landmarks

        Requires optional ML dependencies (torch, transformers). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "detect":
            result = _detect_landmarks(params.image_path, params.confidence_threshold)
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "detect"],
            })
