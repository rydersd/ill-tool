"""Tonal analyzer — K-means tonal zone clustering and plane transition detection.

Segments a reference image into tonal zones (darkest to brightest) using
K-means clustering, then detects where zone transitions occur to identify
3D plane boundaries. Works with the contour labeler to provide the LLM
with tonal context for contour classification decisions.

Tier 1 (top): Pure Python zone analysis and transition detection.
Tier 2 (bottom): MCP tool registration for analyze_zones and find_transitions actions.
"""

import json
import math
from typing import Optional

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.contour_scanner import _load_grayscale


# ── Tier 1: Pure Python Tonal Analysis ──────────────────────────────────


def analyze_tonal_zones(
    image_path: str,
    n_zones: int = 4,
) -> dict:
    """Segment a grayscale image into tonal zones using K-means clustering.

    Clusters all pixel brightness values into n_zones groups, sorts them
    from darkest (zone 0) to brightest (zone n_zones-1), and computes
    statistics for each zone.

    Args:
        image_path: Path to the reference image.
        n_zones: Number of tonal zones to create.

    Returns:
        Dict with:
            zone_map: 2D numpy array (same size as image) where each pixel
                value is its zone index (0 = darkest, n_zones-1 = brightest).
            zone_stats: List of dicts, one per zone, sorted dark to bright:
                mean_brightness, pixel_count, percentage, bounding_box.
            light_direction: Estimated light direction as (dx, dy) unit vector,
                pointing FROM the light source TOWARD the form.
            n_zones: Number of zones.
            image_shape: (height, width).
        Or dict with 'error' key on failure.
    """
    gray = _load_grayscale(image_path)
    if gray is None:
        return {"error": f"Could not read image: {image_path}"}

    return _analyze_tonal_zones_from_gray(gray, n_zones)


def _analyze_tonal_zones_from_gray(
    gray: np.ndarray,
    n_zones: int = 4,
) -> dict:
    """Core tonal zone analysis on a grayscale array.

    Separated from the file-loading wrapper so tests can pass arrays directly.

    Args:
        gray: 2D uint8 grayscale image array.
        n_zones: Number of tonal zones.

    Returns:
        Same dict structure as analyze_tonal_zones.
    """
    img_h, img_w = gray.shape[:2]

    # Reshape pixels into a column vector for K-means
    pixels = gray.reshape(-1, 1).astype(np.float32)

    # K-means clustering
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, labels, centers = cv2.kmeans(
        pixels, n_zones, None, criteria, 10, cv2.KMEANS_PP_CENTERS
    )

    # Sort clusters by center brightness (darkest first)
    center_values = centers.flatten()
    sorted_indices = np.argsort(center_values)

    # Build a mapping from original cluster index to sorted zone index
    remap = np.zeros(n_zones, dtype=np.int32)
    for new_idx, old_idx in enumerate(sorted_indices):
        remap[old_idx] = new_idx

    # Create zone map: each pixel gets its sorted zone index
    zone_map = remap[labels.flatten()].reshape(img_h, img_w)

    # Compute per-zone statistics
    zone_stats = []
    total_pixels = img_h * img_w

    for zone_idx in range(n_zones):
        mask = (zone_map == zone_idx)
        pixel_count = int(np.sum(mask))

        if pixel_count > 0:
            mean_brightness = float(np.mean(gray[mask]))

            # Bounding box of the zone
            ys, xs = np.where(mask)
            bbox = {
                "x": int(xs.min()),
                "y": int(ys.min()),
                "w": int(xs.max() - xs.min() + 1),
                "h": int(ys.max() - ys.min() + 1),
            }
        else:
            mean_brightness = float(center_values[sorted_indices[zone_idx]])
            bbox = {"x": 0, "y": 0, "w": 0, "h": 0}

        zone_stats.append({
            "zone": zone_idx,
            "mean_brightness": round(mean_brightness, 2),
            "pixel_count": pixel_count,
            "percentage": round(100.0 * pixel_count / total_pixels, 2),
            "bounding_box": bbox,
        })

    # Estimate light direction from zone spatial distribution
    light_direction = _estimate_light_direction(zone_map, n_zones, img_h, img_w)

    return {
        "zone_map": zone_map,
        "zone_stats": zone_stats,
        "light_direction": light_direction,
        "n_zones": n_zones,
        "image_shape": (img_h, img_w),
    }


def _estimate_light_direction(
    zone_map: np.ndarray,
    n_zones: int,
    img_h: int,
    img_w: int,
) -> tuple[float, float]:
    """Estimate light direction from spatial distribution of tonal zones.

    Computes the centroid of each zone, then determines the light direction
    as the vector from the darkest zone's centroid toward the brightest
    zone's centroid. The returned vector points FROM the light source.

    Args:
        zone_map: 2D array of zone indices.
        n_zones: Number of zones.
        img_h: Image height.
        img_w: Image width.

    Returns:
        (dx, dy) unit vector indicating light direction.
        (0, 0) if direction cannot be determined.
    """
    centroids = []

    for zone_idx in range(n_zones):
        mask = (zone_map == zone_idx)
        if np.sum(mask) == 0:
            centroids.append(None)
            continue

        ys, xs = np.where(mask)
        cx = float(np.mean(xs))
        cy = float(np.mean(ys))
        centroids.append((cx, cy))

    # Light comes FROM the brightest zone toward the darkest zone
    # Find the brightest and darkest zones that have valid centroids
    brightest = None
    darkest = None

    for z in range(n_zones - 1, -1, -1):
        if centroids[z] is not None:
            brightest = centroids[z]
            break

    for z in range(n_zones):
        if centroids[z] is not None:
            darkest = centroids[z]
            break

    if brightest is None or darkest is None or brightest == darkest:
        return (0.0, 0.0)

    # Direction from brightest toward darkest (light comes FROM bright side)
    dx = darkest[0] - brightest[0]
    dy = darkest[1] - brightest[1]
    length = math.sqrt(dx * dx + dy * dy)

    if length < 1e-6:
        return (0.0, 0.0)

    return (round(dx / length, 4), round(dy / length, 4))


def find_plane_transitions(
    zone_map: np.ndarray,
    form_mask: Optional[np.ndarray] = None,
    scan_interval: int = 5,
    min_confidence: int = 3,
) -> list[dict]:
    """Find plane transition boundaries within the form by scanning for zone changes.

    Scans the zone map horizontally and vertically at regular intervals,
    looking for positions where the tonal zone changes significantly.
    Clusters consistent transition positions to find stable boundaries.

    Args:
        zone_map: 2D array of zone indices from analyze_tonal_zones.
        form_mask: Optional binary mask defining the form region.
            If None, everything except the brightest zone is treated as form.
        scan_interval: Row/column spacing between scan lines.
        min_confidence: Minimum number of scan line readings needed
            for a transition to be reported.

    Returns:
        List of transition dicts, each with:
            position: x or y position of the transition.
            orientation: 'vertical' (transition at x-position scanned
                horizontally) or 'horizontal' (transition at y-position
                scanned vertically).
            zones: (zone_a, zone_b) the two zones on each side.
            confidence: Number of scan lines that detected this transition.
    """
    img_h, img_w = zone_map.shape[:2]
    n_zones = int(zone_map.max()) + 1

    # Build form mask if not provided
    if form_mask is None:
        # Exclude the brightest zone (likely background)
        brightest_zone = n_zones - 1
        form_mask = (zone_map != brightest_zone).astype(np.uint8)

    # Scan horizontally (find vertical boundaries)
    h_transitions = _scan_transitions_horizontal(
        zone_map, form_mask, img_h, img_w, scan_interval
    )

    # Scan vertically (find horizontal boundaries)
    v_transitions = _scan_transitions_vertical(
        zone_map, form_mask, img_h, img_w, scan_interval
    )

    # Cluster and filter transitions by confidence
    results = []

    # Cluster horizontal scan results (vertical boundaries at x-positions)
    v_clusters = _cluster_transitions(h_transitions, min_confidence)
    for cluster in v_clusters:
        results.append({
            "position": cluster["position"],
            "orientation": "vertical",
            "zones": cluster["zones"],
            "confidence": cluster["confidence"],
        })

    # Cluster vertical scan results (horizontal boundaries at y-positions)
    h_clusters = _cluster_transitions(v_transitions, min_confidence)
    for cluster in h_clusters:
        results.append({
            "position": cluster["position"],
            "orientation": "horizontal",
            "zones": cluster["zones"],
            "confidence": cluster["confidence"],
        })

    return results


def _scan_transitions_horizontal(
    zone_map: np.ndarray,
    form_mask: np.ndarray,
    img_h: int,
    img_w: int,
    scan_interval: int,
) -> list[dict]:
    """Scan rows horizontally to find x-positions where zone changes.

    Returns list of raw transition readings: {position, zones}.
    """
    transitions = []

    for row in range(0, img_h, scan_interval):
        prev_zone = None
        for col in range(img_w):
            if form_mask[row, col] == 0:
                prev_zone = None
                continue

            current_zone = int(zone_map[row, col])
            if prev_zone is not None and current_zone != prev_zone:
                transitions.append({
                    "position": col,
                    "zones": (min(prev_zone, current_zone), max(prev_zone, current_zone)),
                })
            prev_zone = current_zone

    return transitions


def _scan_transitions_vertical(
    zone_map: np.ndarray,
    form_mask: np.ndarray,
    img_h: int,
    img_w: int,
    scan_interval: int,
) -> list[dict]:
    """Scan columns vertically to find y-positions where zone changes.

    Returns list of raw transition readings: {position, zones}.
    """
    transitions = []

    for col in range(0, img_w, scan_interval):
        prev_zone = None
        for row in range(img_h):
            if form_mask[row, col] == 0:
                prev_zone = None
                continue

            current_zone = int(zone_map[row, col])
            if prev_zone is not None and current_zone != prev_zone:
                transitions.append({
                    "position": row,
                    "zones": (min(prev_zone, current_zone), max(prev_zone, current_zone)),
                })
            prev_zone = current_zone

    return transitions


def _cluster_transitions(
    transitions: list[dict],
    min_confidence: int,
    cluster_radius: int = 5,
) -> list[dict]:
    """Cluster raw transition readings into stable boundaries.

    Groups transitions that are within cluster_radius pixels of each other
    and between the same zone pair, then reports clusters with at least
    min_confidence readings.

    Args:
        transitions: List of raw readings from horizontal or vertical scans.
        min_confidence: Minimum readings to include a cluster.
        cluster_radius: Maximum distance between readings in a cluster.

    Returns:
        List of cluster dicts: {position, zones, confidence}.
    """
    if not transitions:
        return []

    # Group by zone pair
    by_zones: dict[tuple, list[int]] = {}
    for t in transitions:
        key = t["zones"]
        by_zones.setdefault(key, []).append(t["position"])

    clusters = []

    for zones, positions in by_zones.items():
        positions.sort()

        # Simple greedy clustering
        current_cluster = [positions[0]]

        for i in range(1, len(positions)):
            if positions[i] - current_cluster[-1] <= cluster_radius:
                current_cluster.append(positions[i])
            else:
                # Finish current cluster
                if len(current_cluster) >= min_confidence:
                    median_pos = int(np.median(current_cluster))
                    clusters.append({
                        "position": median_pos,
                        "zones": zones,
                        "confidence": len(current_cluster),
                    })
                current_cluster = [positions[i]]

        # Don't forget the last cluster
        if len(current_cluster) >= min_confidence:
            median_pos = int(np.median(current_cluster))
            clusters.append({
                "position": median_pos,
                "zones": zones,
                "confidence": len(current_cluster),
            })

    return clusters


def get_zone_boundary_contours(
    zone_map: np.ndarray,
    zone_a: int,
    zone_b: int,
) -> list[np.ndarray]:
    """Extract contour arrays along the boundary between two tonal zones.

    Creates a binary mask where zone_a and zone_b meet, dilates slightly
    to ensure connectivity, then extracts contours in the same format as
    vote_map_to_contour_candidates.

    Args:
        zone_map: 2D array of zone indices.
        zone_a: First zone index.
        zone_b: Second zone index.

    Returns:
        List of contour arrays (Nx1x2 int arrays), representing the
        boundary between the two zones.
    """
    # Create masks for each zone
    mask_a = (zone_map == zone_a).astype(np.uint8)
    mask_b = (zone_map == zone_b).astype(np.uint8)

    # Dilate each mask slightly to find overlap region
    kernel = np.ones((3, 3), dtype=np.uint8)
    dilated_a = cv2.dilate(mask_a, kernel, iterations=1)
    dilated_b = cv2.dilate(mask_b, kernel, iterations=1)

    # The boundary is where dilated regions overlap
    boundary = (dilated_a & dilated_b) * 255

    # Extract contours from the boundary mask
    contours, _ = cv2.findContours(boundary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    return list(contours)


# ── Tier 2: MCP Tool Registration ───────────────────────────────────────


def register(mcp):
    """Register the adobe_ai_tonal_analyzer tool."""

    @mcp.tool(
        name="adobe_ai_tonal_analyzer",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_tonal_analyzer(
        image_path: str,
        action: str = "analyze_zones",
        n_zones: int = 4,
        zone_a: int = 0,
        zone_b: int = 1,
    ) -> str:
        """Analyze tonal zones and plane transitions in a reference image.

        Actions:
        - analyze_zones: Segment image into tonal zones and estimate light direction.
        - find_transitions: Find plane boundaries from zone transitions.
        - zone_boundary: Extract contours along the boundary between two zones.
        """
        import os

        if not os.path.exists(image_path):
            return json.dumps({"error": f"Image not found: {image_path}"})

        if action == "analyze_zones":
            result = analyze_tonal_zones(image_path, n_zones=n_zones)
            if "error" in result:
                return json.dumps(result)

            return json.dumps({
                "action": "analyze_zones",
                "n_zones": result["n_zones"],
                "zone_stats": result["zone_stats"],
                "light_direction": list(result["light_direction"]),
                "image_shape": list(result["image_shape"]),
            })

        elif action == "find_transitions":
            result = analyze_tonal_zones(image_path, n_zones=n_zones)
            if "error" in result:
                return json.dumps(result)

            transitions = find_plane_transitions(result["zone_map"])
            return json.dumps({
                "action": "find_transitions",
                "transitions": transitions,
                "transition_count": len(transitions),
            })

        elif action == "zone_boundary":
            result = analyze_tonal_zones(image_path, n_zones=n_zones)
            if "error" in result:
                return json.dumps(result)

            contours = get_zone_boundary_contours(result["zone_map"], zone_a, zone_b)
            serialized = []
            for c in contours:
                serialized.append(c.reshape(-1, 2).tolist())

            return json.dumps({
                "action": "zone_boundary",
                "zone_a": zone_a,
                "zone_b": zone_b,
                "contour_count": len(contours),
                "contours": serialized,
            })

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
