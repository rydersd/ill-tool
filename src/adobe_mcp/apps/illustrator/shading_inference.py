"""Shading-to-form inference from reference images.

Analyzes light/shadow boundaries in a reference image to infer 3D form.
Detects highlight, midtone, and shadow regions, finds boundary contours,
and estimates light direction from highlight positions.

Pure Python implementation using OpenCV and numpy.
"""

import json
import math
import os
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiShadingInferenceInput(BaseModel):
    """Infer 3D form from light/shadow boundaries in a reference image."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: detect_shading, infer_light_direction"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to reference image"
    )
    highlight_threshold: float = Field(
        default=0.75,
        description="Brightness threshold for highlights (0-1, top percentile)",
        ge=0.0, le=1.0,
    )
    shadow_threshold: float = Field(
        default=0.25,
        description="Brightness threshold for shadows (0-1, bottom percentile)",
        ge=0.0, le=1.0,
    )


# ---------------------------------------------------------------------------
# Shading analysis functions
# ---------------------------------------------------------------------------


def detect_shading_regions(
    image_path: str,
    highlight_threshold: float = 0.75,
    shadow_threshold: float = 0.25,
) -> dict:
    """Load reference image and segment into highlight, midtone, shadow regions.

    Args:
        image_path: path to the image file
        highlight_threshold: fraction of max brightness (above = highlight)
        shadow_threshold: fraction of max brightness (below = shadow)

    Returns dict with:
        - regions: {highlight, midtone, shadow} each with pixel_count, centroid
        - boundaries: list of boundary contour point counts
        - image_size: [w, h]
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_norm = gray.astype(np.float64) / 255.0

    # Threshold into three regions
    highlight_val = highlight_threshold
    shadow_val = shadow_threshold

    highlight_mask = (gray_norm >= highlight_val).astype(np.uint8) * 255
    shadow_mask = (gray_norm <= shadow_val).astype(np.uint8) * 255
    midtone_mask = ((gray_norm > shadow_val) & (gray_norm < highlight_val)).astype(np.uint8) * 255

    # Compute centroids for each region
    def region_centroid(mask):
        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            return None
        return [round(float(xs.mean()), 2), round(float(ys.mean()), 2)]

    highlight_centroid = region_centroid(highlight_mask)
    shadow_centroid = region_centroid(shadow_mask)
    midtone_centroid = region_centroid(midtone_mask)

    # Find boundary contours between highlight and shadow regions
    # Use the boundary between highlight and non-highlight
    contours_hl, _ = cv2.findContours(
        highlight_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours_sh, _ = cv2.findContours(
        shadow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    boundaries = []
    for c in contours_hl:
        if cv2.contourArea(c) > 10:  # filter noise
            boundaries.append({
                "type": "highlight_boundary",
                "point_count": len(c),
                "area": round(float(cv2.contourArea(c)), 1),
            })
    for c in contours_sh:
        if cv2.contourArea(c) > 10:
            boundaries.append({
                "type": "shadow_boundary",
                "point_count": len(c),
                "area": round(float(cv2.contourArea(c)), 1),
            })

    return {
        "image_size": [w, h],
        "regions": {
            "highlight": {
                "pixel_count": int(np.sum(highlight_mask > 0)),
                "centroid": highlight_centroid,
                "threshold": highlight_val,
            },
            "midtone": {
                "pixel_count": int(np.sum(midtone_mask > 0)),
                "centroid": midtone_centroid,
            },
            "shadow": {
                "pixel_count": int(np.sum(shadow_mask > 0)),
                "centroid": shadow_centroid,
                "threshold": shadow_val,
            },
        },
        "boundaries": boundaries,
        "total_boundaries": len(boundaries),
    }


def infer_light_direction(
    highlight_centroid: Optional[list[float]],
    image_center: list[float],
) -> dict:
    """Infer light direction from highlight position relative to image center.

    Highlights closer to top-left suggest light from top-left, etc.

    Returns:
        direction: [dx, dy] normalized direction vector pointing toward light
        angle_deg: angle in degrees (0=right, 90=up, 180=left, 270=down)
        confidence: 0-1 based on distance from center
        description: human-readable direction
    """
    if highlight_centroid is None:
        return {
            "direction": [0.0, 0.0],
            "angle_deg": 0.0,
            "confidence": 0.0,
            "description": "unknown (no highlight detected)",
        }

    # Vector from center to highlight
    dx = highlight_centroid[0] - image_center[0]
    dy = highlight_centroid[1] - image_center[1]

    # In image coords, Y increases downward; in light direction, we want
    # "up" to mean top of image, so negate dy
    dy = -dy

    dist = math.sqrt(dx * dx + dy * dy)
    max_dist = math.sqrt(image_center[0] ** 2 + image_center[1] ** 2)

    if dist < 1.0:
        return {
            "direction": [0.0, 0.0],
            "angle_deg": 0.0,
            "confidence": 0.0,
            "description": "centered (diffuse light)",
        }

    # Normalize
    ndx = dx / dist
    ndy = dy / dist

    # Angle (0=right, counter-clockwise)
    angle_rad = math.atan2(ndy, ndx)
    angle_deg = math.degrees(angle_rad) % 360

    # Confidence based on how far highlight is from center
    confidence = min(dist / max_dist, 1.0) if max_dist > 0 else 0.0

    # Human-readable direction
    if angle_deg < 22.5 or angle_deg >= 337.5:
        description = "right"
    elif angle_deg < 67.5:
        description = "top-right"
    elif angle_deg < 112.5:
        description = "top"
    elif angle_deg < 157.5:
        description = "top-left"
    elif angle_deg < 202.5:
        description = "left"
    elif angle_deg < 247.5:
        description = "bottom-left"
    elif angle_deg < 292.5:
        description = "bottom"
    else:
        description = "bottom-right"

    return {
        "direction": [round(ndx, 4), round(ndy, 4)],
        "angle_deg": round(angle_deg, 2),
        "confidence": round(confidence, 3),
        "description": description,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_shading_inference tool."""

    @mcp.tool(
        name="adobe_ai_shading_inference",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_shading_inference(params: AiShadingInferenceInput) -> str:
        """Infer 3D form from light/shadow boundaries in a reference image.

        Actions:
        - detect_shading: segment image into highlight/midtone/shadow regions
        - infer_light_direction: estimate light direction from highlights
        """
        action = params.action.lower().strip()

        if not params.image_path:
            return json.dumps({"error": f"{action} requires image_path"})

        if not os.path.exists(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        # ── detect_shading ───────────────────────────────────────────
        if action == "detect_shading":
            result = detect_shading_regions(
                params.image_path,
                params.highlight_threshold,
                params.shadow_threshold,
            )

            if "error" in result:
                return json.dumps(result)

            # Store in rig
            rig = _load_rig(params.character_name)
            rig["shading_analysis"] = result
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "detect_shading",
                "image_path": params.image_path,
                **result,
            }, indent=2)

        # ── infer_light_direction ────────────────────────────────────
        elif action == "infer_light_direction":
            shading = detect_shading_regions(
                params.image_path,
                params.highlight_threshold,
                params.shadow_threshold,
            )

            if "error" in shading:
                return json.dumps(shading)

            highlight_centroid = shading["regions"]["highlight"]["centroid"]
            w, h = shading["image_size"]
            center = [w / 2, h / 2]

            light_dir = infer_light_direction(highlight_centroid, center)

            # Store in rig
            rig = _load_rig(params.character_name)
            rig["light_direction"] = light_dir
            rig["shading_analysis"] = shading
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "infer_light_direction",
                "image_path": params.image_path,
                "image_size": shading["image_size"],
                "highlight_centroid": highlight_centroid,
                "image_center": center,
                **light_dir,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["detect_shading", "infer_light_direction"],
            })
