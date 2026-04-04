"""Crop and re-analyze a specific region of a reference image at higher detail.

Pure Python implementation using OpenCV. Crops the image to the specified rectangle,
runs the same contour analysis pipeline as analyze_reference on the cropped region,
and optionally saves the cropped image for visual reference.
"""

import json
import os
import tempfile

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.models import AiReferenceCropInput
from adobe_mcp.apps.illustrator.ml_vision.analyze_reference import (
    _classify_shape,
    _edge_lengths,
    _edge_ratios,
)


def _analyze_cropped_region(
    img: np.ndarray,
    min_area_pct: float,
    max_contours: int = 30,
) -> dict:
    """Run contour analysis on a cropped image region.

    Uses the same shape classification pipeline as analyze_reference but
    at a finer granularity appropriate for detail regions.
    """
    img_h, img_w = img.shape[:2]
    total_area = img_h * img_w
    min_area = (min_area_pct / 100.0) * total_area

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Run Canny at two scales for better detail capture on crops
    shapes_all = []
    thresholds = [(30, 90, "bold"), (50, 150, "fine")]

    for canny_low, canny_high, scale_tag in thresholds:
        edges = cv2.Canny(blurred, canny_low, canny_high)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            arc_len = cv2.arcLength(contour, True)
            epsilon = 0.02 * arc_len
            approx = cv2.approxPolyDP(contour, epsilon, True)
            vertex_count = len(approx)

            rect = cv2.minAreaRect(contour)
            center, (w, h), rotation = rect
            shape_type = _classify_shape(vertex_count, w, h)

            moments = cv2.moments(contour)
            if moments["m00"] != 0:
                cx = moments["m10"] / moments["m00"]
                cy = moments["m01"] / moments["m00"]
            else:
                cx, cy = float(center[0]), float(center[1])

            edges_list = _edge_lengths(approx)
            ratios = _edge_ratios(edges_list)
            bx, by, bw, bh = cv2.boundingRect(contour)
            approx_pts = approx.reshape(-1, 2).tolist()

            # Check for duplicates by centroid proximity
            is_duplicate = False
            for existing in shapes_all:
                dx = existing["center"][0] - cx
                dy = existing["center"][1] - cy
                if (dx * dx + dy * dy) < 400:  # 20px merge radius
                    is_duplicate = True
                    break

            if not is_duplicate:
                shapes_all.append({
                    "type": shape_type,
                    "vertices": vertex_count,
                    "center": [round(cx, 1), round(cy, 1)],
                    "width": round(float(w), 1),
                    "height": round(float(h), 1),
                    "rotation_deg": round(float(rotation), 1),
                    "area": int(area),
                    "perimeter": round(arc_len, 1),
                    "edge_lengths": edges_list,
                    "edge_ratios": ratios,
                    "bounding_rect": [bx, by, bw, bh],
                    "approx_points": approx_pts,
                    "scale": scale_tag,
                })

    # Sort by area descending and cap
    shapes_all.sort(key=lambda s: s["area"], reverse=True)
    shapes_all = shapes_all[:max_contours]

    # Re-index
    for idx, shape in enumerate(shapes_all):
        shape["index"] = idx

    return {
        "crop_size": [img_w, img_h],
        "shapes_returned": len(shapes_all),
        "shapes": shapes_all,
    }


def register(mcp):
    """Register the adobe_ai_reference_crop tool."""

    @mcp.tool(
        name="adobe_ai_reference_crop",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_reference_crop(params: AiReferenceCropInput) -> str:
        """Crop a region from the reference image and analyze it at higher detail.

        Extracts the specified rectangle [x, y, width, height] from the reference
        image, runs contour analysis on the cropped region with a lower min_area_pct
        for finer detail capture, and optionally saves the crop for visual reference.

        Returns a shape manifest for the cropped region with coordinates relative
        to the crop origin, plus the crop image path if save_crop is True.
        """
        # Validate image exists
        if not os.path.isfile(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        img = cv2.imread(params.image_path)
        if img is None:
            return json.dumps({"error": f"Could not decode image: {params.image_path}"})

        img_h, img_w = img.shape[:2]

        # Validate crop bounds
        x, y, w, h = params.x, params.y, params.width, params.height

        if x < 0 or y < 0:
            return json.dumps({"error": f"Crop origin cannot be negative: ({x}, {y})"})
        if x + w > img_w:
            w = img_w - x
        if y + h > img_h:
            h = img_h - y

        if w < 10 or h < 10:
            return json.dumps({"error": f"Crop region too small after clipping: {w}x{h}"})

        # Perform the crop
        cropped = img[y:y + h, x:x + w]

        # Run analysis on the cropped region
        analysis = _analyze_cropped_region(cropped, params.min_area_pct)

        # Translate coordinates: add crop offset so shapes reference the full image
        for shape in analysis["shapes"]:
            shape["center_in_full_image"] = [
                round(shape["center"][0] + x, 1),
                round(shape["center"][1] + y, 1),
            ]
            shape["bounding_rect_in_full_image"] = [
                shape["bounding_rect"][0] + x,
                shape["bounding_rect"][1] + y,
                shape["bounding_rect"][2],
                shape["bounding_rect"][3],
            ]

        result = {
            "source_image": params.image_path,
            "source_size": [img_w, img_h],
            "crop_region": {"x": x, "y": y, "width": w, "height": h},
            **analysis,
        }

        # Optionally save the cropped image
        if params.save_crop:
            crop_path = tempfile.mktemp(
                suffix="_crop.png",
                prefix="ai_ref_crop_",
            )
            cv2.imwrite(crop_path, cropped)
            result["crop_image_path"] = crop_path

        return json.dumps(result, indent=2)
