"""Contour labeler — classify and connect CV-extracted contours.

The multi-exposure edge voting system extracts form edge contours with
precise pixel coordinates. This module enables the LLM to LABEL and
CLASSIFY those contours rather than generating coordinates, then connect
contour segments into closed shapes via a constraint solver.

Tier 1 (top): Pure Python labeling, classification, and connection logic.
Tier 2 (bottom): MCP tool registration for label_contours and assemble_shape actions.
"""

import json
import math
from typing import Optional

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.drawing.contour_scanner import (
    _load_grayscale,
    multi_exposure_edge_vote,
    pixels_to_ai_coords,
    vote_map_to_contour_candidates,
)


# ── Tier 1: Pure Python Contour Labeling ────────────────────────────────


def extract_labeled_contours(
    image_path: str,
    min_votes: int = 7,
    min_length: int = 30,
) -> dict:
    """Extract contours from an image's vote map and compute metadata for each.

    Loads the image, computes a multi-exposure edge vote map, extracts contour
    candidates, then annotates each contour with spatial and tonal metadata
    the LLM can use for classification and connection decisions.

    Args:
        image_path: Path to the reference image.
        min_votes: Minimum vote count for contour extraction.
        min_length: Minimum contour perimeter in pixels.

    Returns:
        Dict with:
            contours: list of contour arrays (Nx1x2 int arrays)
            metadata: list of dicts, one per contour, with fields:
                id, bounding_box, centroid, orientation, perimeter,
                area, avg_brightness_left, avg_brightness_right,
                position_relative
            image_shape: (height, width) of the source image
            contour_count: number of contours found
        Or dict with 'error' key on failure.
    """
    gray = _load_grayscale(image_path)
    if gray is None:
        return {"error": f"Could not read image: {image_path}"}

    img_h, img_w = gray.shape[:2]

    # Compute vote map and extract contour candidates
    vote_map = multi_exposure_edge_vote(gray)
    contours = vote_map_to_contour_candidates(
        vote_map, min_votes=min_votes, min_contour_length=min_length
    )

    metadata_list = []
    for idx, contour in enumerate(contours):
        meta = _compute_contour_metadata(contour, gray, idx)
        metadata_list.append(meta)

    return {
        "contours": contours,
        "metadata": metadata_list,
        "image_shape": (img_h, img_w),
        "contour_count": len(contours),
    }


def _compute_contour_metadata(
    contour: np.ndarray,
    gray: np.ndarray,
    contour_id: int,
) -> dict:
    """Compute spatial and tonal metadata for a single contour.

    Args:
        contour: OpenCV contour array (Nx1x2).
        gray: Grayscale image for brightness sampling.
        contour_id: Integer identifier for this contour.

    Returns:
        Dict with id, bounding_box, centroid, orientation, perimeter,
        area, avg_brightness_left, avg_brightness_right, position_relative.
    """
    img_h, img_w = gray.shape[:2]

    # Bounding box
    x, y, w, h = cv2.boundingRect(contour)

    # Centroid via moments
    moments = cv2.moments(contour)
    if moments["m00"] != 0:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
    else:
        pts = contour.reshape(-1, 2).astype(np.float64)
        cx = float(np.mean(pts[:, 0]))
        cy = float(np.mean(pts[:, 1]))

    # Orientation based on aspect ratio of bounding box
    if h > 2 * w:
        orientation = "vertical"
    elif w > 2 * h:
        orientation = "horizontal"
    else:
        orientation = "diagonal"

    # Perimeter and area
    perimeter = cv2.arcLength(contour, closed=True)
    area = cv2.contourArea(contour)

    # Brightness sampling: average brightness 5px to left and right of contour
    avg_left, avg_right = _sample_brightness_sides(contour, gray, offset=5)

    # Position relative: based on centroid y-position in image
    third = img_h / 3.0
    if cy < third:
        position_relative = "top"
    elif cy < 2 * third:
        position_relative = "middle"
    else:
        position_relative = "bottom"

    return {
        "id": contour_id,
        "bounding_box": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
        "centroid": (round(cx, 2), round(cy, 2)),
        "orientation": orientation,
        "perimeter": round(perimeter, 2),
        "area": round(area, 2),
        "avg_brightness_left": round(avg_left, 2),
        "avg_brightness_right": round(avg_right, 2),
        "position_relative": position_relative,
    }


def _sample_brightness_sides(
    contour: np.ndarray,
    gray: np.ndarray,
    offset: int = 5,
) -> tuple[float, float]:
    """Sample average brightness on the left and right sides of a contour.

    For each contour point, compute the outward normal direction, then sample
    brightness at `offset` pixels on each side. Returns (avg_left, avg_right).

    Args:
        contour: OpenCV contour array (Nx1x2).
        gray: Grayscale image.
        offset: Pixel distance from contour to sample.

    Returns:
        Tuple of (avg_brightness_left, avg_brightness_right).
    """
    img_h, img_w = gray.shape[:2]
    pts = contour.reshape(-1, 2).astype(np.float64)
    n_pts = len(pts)

    if n_pts < 2:
        # Degenerate contour, return image mean for both sides
        mean_val = float(np.mean(gray))
        return mean_val, mean_val

    left_samples = []
    right_samples = []

    for i in range(n_pts):
        # Compute tangent direction from neighboring points
        prev_idx = (i - 1) % n_pts
        next_idx = (i + 1) % n_pts
        tangent = pts[next_idx] - pts[prev_idx]
        length = math.sqrt(tangent[0] ** 2 + tangent[1] ** 2)

        if length < 1e-6:
            continue

        # Normal direction (perpendicular to tangent)
        # Left normal: rotate tangent -90 degrees
        nx = -tangent[1] / length
        ny = tangent[0] / length

        # Sample left side (negative normal direction)
        lx = int(round(pts[i][0] - nx * offset))
        ly = int(round(pts[i][1] - ny * offset))
        if 0 <= lx < img_w and 0 <= ly < img_h:
            left_samples.append(float(gray[ly, lx]))

        # Sample right side (positive normal direction)
        rx = int(round(pts[i][0] + nx * offset))
        ry = int(round(pts[i][1] + ny * offset))
        if 0 <= rx < img_w and 0 <= ry < img_h:
            right_samples.append(float(gray[ry, rx]))

    avg_left = float(np.mean(left_samples)) if left_samples else 0.0
    avg_right = float(np.mean(right_samples)) if right_samples else 0.0

    return avg_left, avg_right


def classify_contour(contour_meta: dict, gray_image: np.ndarray) -> str:
    """Classify a contour based on brightness difference between its sides.

    Uses the avg_brightness_left and avg_brightness_right from contour
    metadata to determine the contour's role:

    - silhouette_edge: Large brightness difference (>80) with one side
      very bright (>200). This is a boundary between the form and the
      background.
    - face_boundary: Large difference (>40) but both sides are dark (<200).
      This separates two different 3D planes of the form.
    - panel_line: Small difference (<20). Surface detail lying on the
      same plane.
    - shadow_edge: Moderate difference (20-40). Gradual tonal transition
      caused by lighting, not geometry.

    Args:
        contour_meta: Metadata dict from extract_labeled_contours.
        gray_image: Grayscale image (used for additional context if needed).

    Returns:
        Classification string: one of 'silhouette_edge', 'face_boundary',
        'panel_line', or 'shadow_edge'.
    """
    left_b = contour_meta["avg_brightness_left"]
    right_b = contour_meta["avg_brightness_right"]
    diff = abs(left_b - right_b)
    brighter_side = max(left_b, right_b)

    if diff > 80 and brighter_side > 200:
        return "silhouette_edge"
    elif diff > 40:
        return "face_boundary"
    elif diff < 20:
        return "panel_line"
    else:
        # Moderate difference (20-40): gradual transition from lighting
        return "shadow_edge"


def connect_contours_to_shape(
    contour_ids: list[int],
    contours_data: list[np.ndarray],
    max_gap: float = 15.0,
) -> dict:
    """Connect a list of contour segments into a single shape.

    Given contour IDs and the full contour array list, extracts the
    specified contours and attempts to bridge gaps between consecutive
    pairs by finding closest endpoints.

    Args:
        contour_ids: List of integer contour IDs (indices into contours_data).
        contours_data: Full list of contour arrays from extraction.
        max_gap: Maximum pixel distance to bridge between segments.
            Gaps larger than this are flagged as disconnected.

    Returns:
        Dict with:
            points: Combined point sequence as list of [x, y] pixel coords.
            total_length: Total perimeter of the combined shape.
            gaps_bridged: Number of gaps that were successfully bridged.
            max_gap_size: Largest gap that was bridged (0 if none).
            disconnected: List of (id_a, id_b, gap_distance) tuples for
                gaps that exceeded max_gap.
    """
    if not contour_ids or not contours_data:
        return {
            "points": [],
            "total_length": 0.0,
            "gaps_bridged": 0,
            "max_gap_size": 0.0,
            "disconnected": [],
        }

    # Extract point lists for the requested contour IDs
    segments = []
    for cid in contour_ids:
        if 0 <= cid < len(contours_data):
            pts = contours_data[cid].reshape(-1, 2).astype(np.float64)
            segments.append((cid, pts))

    if not segments:
        return {
            "points": [],
            "total_length": 0.0,
            "gaps_bridged": 0,
            "max_gap_size": 0.0,
            "disconnected": [],
        }

    # Connect segments by finding closest endpoints between consecutive pairs
    combined_points = []
    gaps_bridged = 0
    max_gap_size = 0.0
    disconnected = []

    for i, (cid, pts) in enumerate(segments):
        if i == 0:
            # First segment: add all points
            combined_points.extend(pts.tolist())
            continue

        prev_cid, prev_pts = segments[i - 1]

        # Find the closest endpoint pair between the end of combined
        # and the start/end of the current segment
        tail = np.array(combined_points[-1])

        # Check both orientations of the current segment
        dist_to_start = float(np.linalg.norm(tail - pts[0]))
        dist_to_end = float(np.linalg.norm(tail - pts[-1]))

        if dist_to_end < dist_to_start:
            # Reverse the segment so the closer end connects
            pts = pts[::-1]
            gap_dist = dist_to_end
        else:
            gap_dist = dist_to_start

        if gap_dist <= max_gap:
            # Bridge the gap with a straight line (implicit via point sequence)
            gaps_bridged += 1
            max_gap_size = max(max_gap_size, gap_dist)
            combined_points.extend(pts.tolist())
        else:
            # Gap too large — flag as disconnected but still add points
            disconnected.append((prev_cid, cid, round(gap_dist, 2)))
            combined_points.extend(pts.tolist())

    # Compute total length of the combined polygon
    total_length = 0.0
    for i in range(1, len(combined_points)):
        dx = combined_points[i][0] - combined_points[i - 1][0]
        dy = combined_points[i][1] - combined_points[i - 1][1]
        total_length += math.sqrt(dx * dx + dy * dy)

    return {
        "points": combined_points,
        "total_length": round(total_length, 2),
        "gaps_bridged": gaps_bridged,
        "max_gap_size": round(max_gap_size, 2),
        "disconnected": disconnected,
    }


def assemble_shape(
    name: str,
    classified_contours: list[dict],
    connection_spec: list[int],
    contours_data: list[np.ndarray],
    max_gap: float = 15.0,
    transform: Optional[dict] = None,
) -> dict:
    """Assemble a named shape from classified contours using a connection spec.

    Takes a list of contour IDs in connection order, connects them into a
    closed polygon, converts pixel coordinates to AI coordinates, and returns
    a complete shape definition.

    Args:
        name: Human-readable name for the shape (e.g. 'head_silhouette').
        classified_contours: List of metadata dicts with classification info.
        connection_spec: List of contour IDs in the order they should be connected.
        contours_data: Full list of contour arrays from extraction.
        max_gap: Maximum pixel distance to bridge between segments.
        transform: Optional coordinate transform dict for pixel-to-AI conversion.

    Returns:
        Dict with:
            name: Shape name.
            points: Pixel coordinate points as list of [x, y].
            ai_points: AI coordinate points as list of [x, y].
            anchor_count: Number of points in the shape.
            source_contour_ids: List of contour IDs used.
            classification: Most common classification among source contours.
            connection_info: Dict with gaps_bridged, max_gap_size, disconnected.
    """
    # Connect the contours
    connection = connect_contours_to_shape(connection_spec, contours_data, max_gap)

    # Convert pixel coords to AI coords
    ai_points = pixels_to_ai_coords(connection["points"], transform)

    # Determine the dominant classification from the source contours
    classifications = []
    for cid in connection_spec:
        for meta in classified_contours:
            if meta.get("id") == cid and "classification" in meta:
                classifications.append(meta["classification"])
                break

    # Most common classification, or 'unknown' if none found
    if classifications:
        classification = max(set(classifications), key=classifications.count)
    else:
        classification = "unknown"

    return {
        "name": name,
        "points": connection["points"],
        "ai_points": ai_points,
        "anchor_count": len(connection["points"]),
        "source_contour_ids": connection_spec,
        "classification": classification,
        "connection_info": {
            "gaps_bridged": connection["gaps_bridged"],
            "max_gap_size": connection["max_gap_size"],
            "disconnected": connection["disconnected"],
        },
    }


# ── Tier 2: MCP Tool Registration ───────────────────────────────────────


def register(mcp):
    """Register the adobe_ai_contour_labeler tool."""

    @mcp.tool(
        name="adobe_ai_contour_labeler",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_contour_labeler(
        image_path: str,
        action: str = "extract",
        min_votes: int = 7,
        min_length: int = 30,
        contour_ids: Optional[str] = None,
        shape_name: str = "shape",
        max_gap: float = 15.0,
    ) -> str:
        """Label and classify CV-extracted contours from a reference image.

        Actions:
        - extract: Extract contours with metadata for LLM classification.
        - assemble: Connect specified contours into a named shape.
        """
        import os

        if action == "extract":
            if not os.path.exists(image_path):
                return json.dumps({"error": f"Image not found: {image_path}"})

            result = extract_labeled_contours(
                image_path, min_votes=min_votes, min_length=min_length
            )

            if "error" in result:
                return json.dumps(result)

            # Classify each contour
            gray = _load_grayscale(image_path)
            for meta in result["metadata"]:
                meta["classification"] = classify_contour(meta, gray)

            # Convert contour arrays to serializable format for JSON
            serializable_contours = []
            for contour in result["contours"]:
                serializable_contours.append(contour.reshape(-1, 2).tolist())

            return json.dumps({
                "action": "extract",
                "contour_count": result["contour_count"],
                "metadata": result["metadata"],
                "image_shape": list(result["image_shape"]),
            })

        elif action == "assemble":
            if not contour_ids:
                return json.dumps({"error": "assemble requires contour_ids"})

            try:
                ids = json.loads(contour_ids)
            except (json.JSONDecodeError, TypeError) as exc:
                return json.dumps({"error": f"Invalid contour_ids: {exc}"})

            # Re-extract contours to get the data
            result = extract_labeled_contours(
                image_path, min_votes=min_votes, min_length=min_length
            )
            if "error" in result:
                return json.dumps(result)

            gray = _load_grayscale(image_path)
            for meta in result["metadata"]:
                meta["classification"] = classify_contour(meta, gray)

            shape = assemble_shape(
                name=shape_name,
                classified_contours=result["metadata"],
                connection_spec=ids,
                contours_data=result["contours"],
                max_gap=max_gap,
            )

            return json.dumps({
                "action": "assemble",
                "shape": {
                    "name": shape["name"],
                    "anchor_count": shape["anchor_count"],
                    "ai_points": shape["ai_points"],
                    "source_contour_ids": shape["source_contour_ids"],
                    "classification": shape["classification"],
                    "connection_info": shape["connection_info"],
                },
            })

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
