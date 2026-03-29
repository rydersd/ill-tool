"""Constraint solver: resolves semantic edge constraints to exact coordinates.

The LLM cannot reliably output pixel coordinates. Instead, it outputs semantic
constraints like {"type": "silhouette", "side": "left"} and this solver
resolves them to exact coordinates derived from CV data (contours, tonal maps,
silhouette masks).

All coordinates originate from computer vision — the LLM never generates
pixel values directly.

Tier 1 (top): Pure Python constraint resolution and geometry helpers.
Tier 2 (bottom): No MCP registration — this is a library module consumed
by other tools (e.g. contour_scanner, drawing_orchestrator).
"""

import math
from typing import Optional

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.landmark_axis import compute_transform, pixel_to_ai


# ── Silhouette Extraction ────────────────────────────────────────────────


def extract_silhouette_edges(
    gray_image: np.ndarray,
    threshold: int = 200,
) -> dict:
    """Extract left and right silhouette edges from a grayscale image.

    Thresholds the image to find the largest dark region, then for each
    scanline (y row), finds the minimum-x (left edge) and maximum-x
    (right edge) of the silhouette contour.

    Args:
        gray_image: 2D numpy array (uint8) grayscale image.
        threshold: Pixels below this value are considered part of the
                   silhouette (dark form on light background).

    Returns:
        Dict with:
            left_edge: list of [x, y] points tracing the left boundary
            right_edge: list of [x, y] points tracing the right boundary
            contour: the largest contour found (Nx1x2 int array)
            y_range: (min_y, max_y) of the silhouette
    """
    # Invert so the dark form becomes white (foreground) for findContours
    _, binary = cv2.threshold(gray_image, threshold, 255, cv2.THRESH_BINARY_INV)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    if not contours:
        return {
            "left_edge": [],
            "right_edge": [],
            "contour": None,
            "y_range": (0, 0),
        }

    # Pick the largest contour by area
    largest = max(contours, key=cv2.contourArea)

    # Flatten to Nx2 array of points
    pts = largest.reshape(-1, 2)

    # For each y row in the contour, find min-x and max-x
    y_min = int(pts[:, 1].min())
    y_max = int(pts[:, 1].max())

    left_edge = []
    right_edge = []

    for y in range(y_min, y_max + 1):
        row_mask = pts[:, 1] == y
        if not np.any(row_mask):
            continue
        row_xs = pts[row_mask, 0]
        left_edge.append([int(row_xs.min()), y])
        right_edge.append([int(row_xs.max()), y])

    return {
        "left_edge": left_edge,
        "right_edge": right_edge,
        "contour": largest,
        "y_range": (y_min, y_max),
    }


# ── Single Edge Constraint Resolution ────────────────────────────────────


def resolve_edge_constraint(
    constraint: dict,
    contours: Optional[list[np.ndarray]] = None,
    tonal_data: Optional[np.ndarray] = None,
    silhouette: Optional[dict] = None,
) -> list[list[float]]:
    """Resolve a single semantic edge constraint to pixel coordinates.

    All coordinates come from CV data — never from the LLM.

    Constraint types:
        {"type": "silhouette", "side": "left"}
            Extract left silhouette edge from the silhouette dict.
        {"type": "silhouette", "side": "right"}
            Extract right silhouette edge.
        {"type": "tonal_boundary", "from_zone": N, "to_zone": M}
            Find the boundary between two brightness zones in tonal_data.
        {"type": "contour_id", "id": N}
            Return the points from contour index N.
        {"type": "y_level", "y": Y}
            Return a horizontal line at the given y coordinate, spanning
            the silhouette width (or a default width if no silhouette).
        {"type": "y_range", "start": Y1, "end": Y2, "x": "silhouette_left"}
            Vertical slice of the silhouette between Y1 and Y2.

    Args:
        constraint: Dict describing the edge constraint (must have "type").
        contours: Optional list of cv2 contour arrays.
        tonal_data: Optional 2D grayscale image used for tonal zone detection.
        silhouette: Optional dict from extract_silhouette_edges().

    Returns:
        List of [x, y] points along the resolved edge.

    Raises:
        ValueError: If constraint type is unknown or required data is missing.
    """
    ctype = constraint.get("type")

    if ctype == "silhouette":
        if silhouette is None:
            raise ValueError("silhouette data required for silhouette constraint")
        side = constraint.get("side", "left")
        if side == "left":
            return [[float(p[0]), float(p[1])] for p in silhouette["left_edge"]]
        elif side == "right":
            return [[float(p[0]), float(p[1])] for p in silhouette["right_edge"]]
        else:
            raise ValueError(f"Unknown silhouette side: {side}")

    elif ctype == "tonal_boundary":
        if tonal_data is None:
            raise ValueError("tonal_data required for tonal_boundary constraint")
        from_zone = constraint.get("from_zone", 2)
        to_zone = constraint.get("to_zone", 1)
        return _find_tonal_boundary(tonal_data, from_zone, to_zone)

    elif ctype == "contour_id":
        if contours is None:
            raise ValueError("contours required for contour_id constraint")
        idx = constraint.get("id", 0)
        if idx < 0 or idx >= len(contours):
            raise ValueError(
                f"Contour index {idx} out of range (have {len(contours)} contours)"
            )
        pts = contours[idx].reshape(-1, 2)
        return [[float(p[0]), float(p[1])] for p in pts]

    elif ctype == "y_level":
        y = constraint.get("y", 0)
        # Determine x range from silhouette or default
        if silhouette and silhouette["left_edge"] and silhouette["right_edge"]:
            all_left_x = [p[0] for p in silhouette["left_edge"]]
            all_right_x = [p[0] for p in silhouette["right_edge"]]
            x_min = min(all_left_x)
            x_max = max(all_right_x)
        else:
            # Default span if no silhouette available
            x_min = 0.0
            x_max = 200.0
        return [[float(x_min), float(y)], [float(x_max), float(y)]]

    elif ctype == "y_range":
        if silhouette is None:
            raise ValueError("silhouette data required for y_range constraint")
        y_start = constraint.get("start", 0)
        y_end = constraint.get("end", 100)
        x_source = constraint.get("x", "silhouette_left")

        if x_source == "silhouette_left":
            source_edge = silhouette["left_edge"]
        elif x_source == "silhouette_right":
            source_edge = silhouette["right_edge"]
        else:
            raise ValueError(f"Unknown x source for y_range: {x_source}")

        # Filter edge points within the y range
        return [
            [float(p[0]), float(p[1])]
            for p in source_edge
            if y_start <= p[1] <= y_end
        ]

    else:
        raise ValueError(f"Unknown constraint type: {ctype}")


# ── Tonal Boundary Detection ─────────────────────────────────────────────


def _find_tonal_boundary(
    gray: np.ndarray,
    from_zone: int,
    to_zone: int,
    n_zones: int = 4,
) -> list[list[float]]:
    """Find the boundary between two brightness zones in a grayscale image.

    Divides the brightness range [0, 255] into n_zones equal bands. The
    boundary between from_zone and to_zone is detected by scanning each
    row for the transition point between the two zones.

    Zone numbering: 0 = darkest, n_zones-1 = brightest.

    Args:
        gray: 2D grayscale image array.
        from_zone: Zone index on one side of the boundary.
        to_zone: Zone index on the other side.
        n_zones: Total number of brightness zones.

    Returns:
        List of [x, y] points along the detected boundary.
    """
    h, w = gray.shape[:2]
    zone_width = 256 / n_zones

    # Compute zone map: which zone each pixel belongs to
    zone_map = np.clip((gray.astype(np.float64) / zone_width).astype(int), 0, n_zones - 1)

    boundary_points = []

    for y in range(h):
        row = zone_map[y, :]
        # Scan for transitions between from_zone and to_zone
        for x in range(1, w):
            prev_z = row[x - 1]
            curr_z = row[x]
            if (prev_z == from_zone and curr_z == to_zone) or (
                prev_z == to_zone and curr_z == from_zone
            ):
                boundary_points.append([float(x), float(y)])
                break  # Take first transition per row

    return boundary_points


# ── Full Shape Constraint Resolution ─────────────────────────────────────


def resolve_shape_constraint(
    shape_constraint: dict,
    contours: Optional[list[np.ndarray]] = None,
    tonal_data: Optional[np.ndarray] = None,
    silhouette: Optional[dict] = None,
    transform: Optional[dict] = None,
) -> dict:
    """Resolve a full shape constraint (4 edges) into a closed polygon.

    A shape constraint defines a region by its four edges:
        {"name": "front_face", "edges": {
            "left": {"type": "silhouette", "side": "left"},
            "right": {"type": "tonal_boundary", "from_zone": 2, "to_zone": 1},
            "top": {"type": "y_level", "y": 75},
            "bottom": {"type": "y_level", "y": 440}
        }}

    Each edge is resolved independently via resolve_edge_constraint, then
    the four edges are connected into a closed polygon by walking:
    left (top→bottom) → bottom (left→right) → right (bottom→top) →
    top (right→left).

    Args:
        shape_constraint: Dict with "name" and "edges" containing
                          left/right/top/bottom edge constraints.
        contours: Optional contour list for contour_id constraints.
        tonal_data: Optional grayscale image for tonal constraints.
        silhouette: Optional silhouette dict for silhouette constraints.
        transform: Optional pixel→AI transform dict.

    Returns:
        Dict with:
            name: Shape name from the constraint.
            points: Closed polygon in pixel coordinates.
            ai_points: Closed polygon in AI coordinates (if transform given).
            edge_sources: Dict mapping edge name to its resolved points.
    """
    name = shape_constraint.get("name", "unnamed")
    edges_def = shape_constraint.get("edges", {})

    edge_sources = {}
    for edge_name in ("left", "right", "top", "bottom"):
        if edge_name in edges_def:
            edge_sources[edge_name] = resolve_edge_constraint(
                edges_def[edge_name],
                contours=contours,
                tonal_data=tonal_data,
                silhouette=silhouette,
            )
        else:
            edge_sources[edge_name] = []

    # Build closed polygon by connecting edges in order:
    # left top→bottom, bottom left→right, right bottom→top, top right→left
    polygon = []

    # Left edge: sorted top to bottom (ascending y)
    left_pts = sorted(edge_sources.get("left", []), key=lambda p: p[1])
    polygon.extend(left_pts)

    # Bottom edge: sorted left to right (ascending x)
    bottom_pts = sorted(edge_sources.get("bottom", []), key=lambda p: p[0])
    polygon.extend(bottom_pts)

    # Right edge: sorted bottom to top (descending y)
    right_pts = sorted(edge_sources.get("right", []), key=lambda p: p[1], reverse=True)
    polygon.extend(right_pts)

    # Top edge: sorted right to left (descending x)
    top_pts = sorted(edge_sources.get("top", []), key=lambda p: p[0], reverse=True)
    polygon.extend(top_pts)

    # Convert to AI coordinates if transform available
    ai_points = []
    if transform and polygon:
        for pt in polygon:
            ai_x, ai_y = pixel_to_ai(pt[0], pt[1], transform)
            ai_points.append([round(ai_x, 2), round(ai_y, 2)])

    return {
        "name": name,
        "points": polygon,
        "ai_points": ai_points,
        "edge_sources": edge_sources,
    }


# ── Vanishing Point Snap ─────────────────────────────────────────────────


def snap_to_vanishing_point(
    edge_points: list[list[float]],
    vp: tuple[float, float],
    tolerance: float = 5.0,
) -> list[list[float]]:
    """Adjust edge points so the edge line converges toward a vanishing point.

    For each consecutive pair of edge points, computes the line direction
    and compares it to the direction toward the VP from their midpoint.
    If the angular difference exceeds the tolerance, the second point is
    rotated slightly toward VP convergence.

    Points already converging within tolerance are left unchanged.

    Args:
        edge_points: List of [x, y] points defining the edge.
        vp: (x, y) position of the vanishing point.
        tolerance: Maximum angular difference (degrees) before adjustment.

    Returns:
        Adjusted list of [x, y] points.
    """
    if len(edge_points) < 2:
        return [list(p) for p in edge_points]

    result = [list(edge_points[0])]

    for i in range(1, len(edge_points)):
        p0 = result[i - 1]
        p1 = list(edge_points[i])

        # Direction of the edge segment
        dx_edge = p1[0] - p0[0]
        dy_edge = p1[1] - p0[1]
        seg_len = math.sqrt(dx_edge ** 2 + dy_edge ** 2)

        if seg_len < 1e-6:
            result.append(p1)
            continue

        edge_angle = math.atan2(dy_edge, dx_edge)

        # Direction from midpoint to VP
        mid_x = (p0[0] + p1[0]) / 2
        mid_y = (p0[1] + p1[1]) / 2
        dx_vp = vp[0] - mid_x
        dy_vp = vp[1] - mid_y
        vp_dist = math.sqrt(dx_vp ** 2 + dy_vp ** 2)

        if vp_dist < 1e-6:
            result.append(p1)
            continue

        vp_angle = math.atan2(dy_vp, dx_vp)

        # Angular difference (handle wrap-around)
        angle_diff = vp_angle - edge_angle
        # Normalize to [-pi, pi]
        angle_diff = math.atan2(math.sin(angle_diff), math.cos(angle_diff))
        angle_diff_deg = math.degrees(abs(angle_diff))

        if angle_diff_deg <= tolerance:
            # Already converging within tolerance — no adjustment
            result.append(p1)
        else:
            # Rotate the segment direction toward the VP direction.
            # Blend the edge angle toward the VP angle by the minimum
            # amount to get within tolerance.
            adjustment = math.radians(tolerance)
            if angle_diff > 0:
                new_angle = edge_angle + (abs(angle_diff) - adjustment)
            else:
                new_angle = edge_angle - (abs(angle_diff) - adjustment)

            # Reconstruct p1 at the original distance from p0 but with
            # the adjusted angle
            new_x = p0[0] + seg_len * math.cos(new_angle)
            new_y = p0[1] + seg_len * math.sin(new_angle)
            result.append([round(new_x, 4), round(new_y, 4)])

    return result
