"""CartoonSegmentation ML backend (optional dependency).

Provides cartoon character instance segmentation using AnimeInstanceSegmentation.
Returns instance masks mapped to a parts schema (body, head, arms, legs, etc.).

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
# Parts schema — canonical part names for cartoon characters
# ---------------------------------------------------------------------------

PART_LABELS = [
    "background",
    "body",
    "head",
    "hair",
    "face",
    "arm_l",
    "arm_r",
    "hand_l",
    "hand_r",
    "leg_l",
    "leg_r",
    "foot_l",
    "foot_r",
    "clothing_upper",
    "clothing_lower",
    "accessory",
]


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class SegmentMLInput(BaseModel):
    """Control CartoonSegmentation."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, segment",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to character image for segmentation"
    )
    min_score: float = Field(
        default=0.5,
        description="Minimum instance score to include",
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def masks_to_parts(
    masks: List[List[List[int]]],
    scores: List[float],
    labels: List[int],
    min_score: float = 0.5,
) -> List[Dict]:
    """Convert model output (masks, scores, labels) to our parts format.

    Args:
        masks: List of 2D binary masks (H x W), one per instance.
        scores: Confidence score for each instance.
        labels: Integer label index for each instance (indexes into PART_LABELS).

    Returns:
        List of part dicts with keys: label, score, bbox, pixel_count.
    """
    parts = []
    for i, (mask, score, label_idx) in enumerate(zip(masks, scores, labels)):
        if score < min_score:
            continue

        # Determine label name
        if 0 <= label_idx < len(PART_LABELS):
            label_name = PART_LABELS[label_idx]
        else:
            label_name = f"unknown_{label_idx}"

        # Compute bounding box and pixel count from mask
        pixel_count = 0
        min_r, min_c = len(mask), len(mask[0]) if mask else 0
        max_r, max_c = 0, 0

        for r, row in enumerate(mask):
            for c, val in enumerate(row):
                if val > 0:
                    pixel_count += 1
                    min_r = min(min_r, r)
                    max_r = max(max_r, r)
                    min_c = min(min_c, c)
                    max_c = max(max_c, c)

        bbox = None
        if pixel_count > 0:
            bbox = {
                "x": min_c,
                "y": min_r,
                "width": max_c - min_c + 1,
                "height": max_r - min_r + 1,
            }

        parts.append({
            "label": label_name,
            "score": round(score, 4),
            "pixel_count": pixel_count,
            "bbox": bbox,
            "instance_index": i,
        })

    return parts


def _ml_status() -> dict:
    """Return availability status of ML segmentation."""
    status = {
        "ml_available": ML_AVAILABLE,
        "model": "AnimeInstanceSegmentation",
        "supported_parts": PART_LABELS,
        "part_count": len(PART_LABELS),
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


def _segment_image(image_path: str, min_score: float) -> dict:
    """Run AnimeInstanceSegmentation on an image.

    Requires ML dependencies.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot run segmentation.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        width, height = image.size

        return {
            "error": "AnimeInstanceSegmentation model integration pending.",
            "image_path": image_path,
            "image_size": {"width": width, "height": height},
            "note": "Use masks_to_parts() with output from any instance segmentation model.",
        }
    except Exception as exc:
        return {"error": f"Segmentation failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_segment_ml tool."""

    @mcp.tool(
        name="adobe_ai_segment_ml",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_segment_ml(params: SegmentMLInput) -> str:
        """CartoonSegmentation instance segmentation.

        Actions:
        - status: Check ML availability and supported parts
        - segment: Run segmentation on an image, return part masks

        Requires optional ML dependencies (torch, transformers). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "segment":
            result = _segment_image(params.image_path, params.min_score)
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "segment"],
            })
