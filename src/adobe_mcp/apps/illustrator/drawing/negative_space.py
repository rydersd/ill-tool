"""Analyze the shapes BETWEEN character limbs/features (negative space).

Pure Python implementation using OpenCV.  Loads a reference image,
thresholds to get a character silhouette, inverts to capture the empty
regions, then analyses each negative-space contour for area, aspect ratio,
centroid, bounding box, and flags unusually shaped regions.
"""

import json
import math
import os

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiNegativeSpaceInput(BaseModel):
    """Analyze negative space in a character reference image."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(default="analyze", description="Action: analyze")
    image_path: str = Field(..., description="Path to reference image")
    threshold: int = Field(
        default=128,
        description="Binary threshold for silhouette extraction (0-255)",
        ge=0,
        le=255,
    )
    min_area: int = Field(
        default=100,
        description="Minimum contour area (pixels) to include in analysis",
        ge=1,
    )
    thin_ratio: float = Field(
        default=4.0,
        description="Aspect ratio above which a region is flagged as 'thin' (limbs too close)",
        ge=1.0,
    )
    large_fraction: float = Field(
        default=0.25,
        description="Area fraction of image above which a region is flagged as 'large' (limbs too spread)",
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Negative-space analysis
# ---------------------------------------------------------------------------


def analyze_negative_space(
    image_path: str,
    threshold: int = 128,
    min_area: int = 100,
    thin_ratio: float = 4.0,
    large_fraction: float = 0.25,
) -> dict:
    """Analyze negative space in a character image.

    Parameters
    ----------
    image_path : str
        Filesystem path to the reference image.
    threshold : int
        Binary threshold value for silhouette extraction.
    min_area : int
        Minimum contour area to include.
    thin_ratio : float
        Aspect ratio threshold for flagging thin regions.
    large_fraction : float
        Fraction of total image area for flagging large regions.

    Returns
    -------
    dict
        {regions: [...], flags: [...], total_negative_area, ...}
    """
    if not os.path.exists(image_path):
        return {"error": f"Image not found: {image_path}"}

    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}

    h, w = img.shape[:2]
    total_area = h * w

    # Convert to greyscale and threshold to get character silhouette
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    # Invert: white areas (negative space) become the subject
    inverted = cv2.bitwise_not(binary)

    # Find contours of negative space regions
    contours, _ = cv2.findContours(inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    flags = []

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < min_area:
            continue

        # Bounding box
        bx, by, bw, bh = cv2.boundingRect(contour)
        aspect_ratio = max(bw, bh) / max(min(bw, bh), 1)

        # Centroid
        M = cv2.moments(contour)
        if M["m00"] > 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
        else:
            cx = bx + bw / 2.0
            cy = by + bh / 2.0

        region = {
            "index": len(regions),
            "area": int(area),
            "area_fraction": round(area / total_area, 4),
            "aspect_ratio": round(aspect_ratio, 2),
            "centroid": [round(cx, 1), round(cy, 1)],
            "bounding_box": {"x": bx, "y": by, "width": bw, "height": bh},
        }
        regions.append(region)

        # Flag unusually shaped regions
        if aspect_ratio > thin_ratio:
            flags.append({
                "region_index": region["index"],
                "type": "thin",
                "message": f"Region {region['index']} is very thin (aspect {aspect_ratio:.1f}) — limbs may be too close",
                "aspect_ratio": round(aspect_ratio, 2),
            })

        if area / total_area > large_fraction:
            flags.append({
                "region_index": region["index"],
                "type": "large",
                "message": f"Region {region['index']} is very large ({area / total_area:.1%} of image) — limbs may be too spread",
                "area_fraction": round(area / total_area, 4),
            })

    total_neg = sum(r["area"] for r in regions)

    return {
        "image_size": [w, h],
        "threshold": threshold,
        "total_negative_area": total_neg,
        "negative_fraction": round(total_neg / total_area, 4) if total_area > 0 else 0,
        "region_count": len(regions),
        "regions": regions,
        "flag_count": len(flags),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_negative_space tool."""

    @mcp.tool(
        name="adobe_ai_negative_space",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_negative_space(params: AiNegativeSpaceInput) -> str:
        """Analyze the shapes between character limbs/features.

        Loads a reference image, extracts the character silhouette,
        inverts it to find negative-space regions, and reports area,
        aspect ratio, centroid, bounding box, and flags for each region.
        """
        if params.action != "analyze":
            return json.dumps({
                "error": f"Unknown action: {params.action}",
                "valid_actions": ["analyze"],
            })

        result = analyze_negative_space(
            image_path=params.image_path,
            threshold=params.threshold,
            min_area=params.min_area,
            thin_ratio=params.thin_ratio,
            large_fraction=params.large_fraction,
        )
        return json.dumps(result)
