"""MCP tool for shape classification, simplification, and LOD precomputation.

Provides a Python-side equivalent of the ExtendScript shapes.jsx and
geometry.jsx modules, callable from the C++ plugin SDK or any MCP client.

Actions:
- classify: Given a list of [x, y] points, classify the shape and return the
  best fit (line, arc, lshape, rectangle, scurve, ellipse, freeform).
- simplify: Given points + shape type + level (0-100), return simplified points
  using a 3-phase strategy: Douglas-Peucker -> inflection-preserving -> primitive fit.
- lod: Given points, precompute all LOD levels and return them.
"""

import json
import math
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class ShapeClassifyInput(BaseModel):
    """Control shape classification and simplification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="classify",
        description=(
            "Action: classify | simplify | lod. "
            "classify = identify shape type from points. "
            "simplify = reduce points using shape-aware strategy. "
            "lod = precompute all LOD levels."
        ),
    )
    points: list[list[float]] = Field(
        default_factory=list,
        description="Point array as [[x, y], ...] in any coordinate space.",
    )
    shape_type: str = Field(
        default="",
        description=(
            "For simplify action: force fit to this shape type "
            "(line, arc, lshape, rectangle, scurve, ellipse, freeform). "
            "Empty string = auto-detect."
        ),
    )
    surface_hint: str = Field(
        default="",
        description=(
            "Surface type hint for classification boost: "
            "flat, cylindrical, convex, concave, saddle, angular, rectangular."
        ),
    )
    simplify_level: int = Field(
        default=50,
        description="Simplification level 0-100 (0 = no simplification, 100 = maximum).",
        ge=0,
        le=100,
    )
    num_lod_levels: int = Field(
        default=20,
        description="Number of LOD levels to precompute for lod action.",
        ge=2,
        le=100,
    )


# ---------------------------------------------------------------------------
# 2D vector helpers (matching math2d.jsx)
# ---------------------------------------------------------------------------


def _dist2d(a, b):
    """Euclidean distance between two 2D points."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


def _sub2d(a, b):
    """Subtract b from a."""
    return [a[0] - b[0], a[1] - b[1]]


def _dot2d(a, b):
    """Dot product."""
    return a[0] * b[0] + a[1] * b[1]


def _cross2d(a, b):
    """2D cross product (z-component)."""
    return a[0] * b[1] - a[1] * b[0]


def _normalize2d(v):
    """Normalize a 2D vector."""
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length < 1e-12:
        return [0.0, 0.0]
    return [v[0] / length, v[1] / length]


def _centroid2d(pts):
    """Compute centroid of points."""
    n = len(pts)
    if n == 0:
        return [0.0, 0.0]
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    return [cx, cy]


def _point_to_segment_dist(p, a, b):
    """Perpendicular distance from point p to line segment a-b."""
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq < 1e-12:
        return _dist2d(p, a)
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / ab_len_sq
    t = max(0.0, min(1.0, t))
    proj = [a[0] + t * abx, a[1] + t * aby]
    return _dist2d(p, proj)


# ---------------------------------------------------------------------------
# Circumcircle (3-point circle)
# ---------------------------------------------------------------------------


def _circumcircle(p1, p2, p3):
    """Compute circumscribed circle through three points.

    Returns dict with 'center' and 'radius', or None if collinear.
    """
    ax, ay = p1[0], p1[1]
    bx, by = p2[0], p2[1]
    cx, cy = p3[0], p3[1]

    D = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(D) < 1e-10:
        return None

    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / D
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / D
    r = _dist2d([ux, uy], p1)

    return {"center": [ux, uy], "radius": r}


# ---------------------------------------------------------------------------
# Convex hull (Graham scan) — needed for minAreaRect
# ---------------------------------------------------------------------------


def _convex_hull_2d(pts):
    """Convex hull via Graham scan, CCW order."""
    if len(pts) < 3:
        return [list(p) for p in pts]

    # Find lowest-leftmost pivot
    pivot = 0
    for i in range(1, len(pts)):
        if pts[i][1] < pts[pivot][1] or (
            pts[i][1] == pts[pivot][1] and pts[i][0] < pts[pivot][0]
        ):
            pivot = i

    p0 = pts[pivot]
    indices = [j for j in range(len(pts)) if j != pivot]
    indices.sort(
        key=lambda idx: (
            math.atan2(pts[idx][1] - p0[1], pts[idx][0] - p0[0]),
            _dist2d(p0, pts[idx]),
        )
    )

    stack = [list(p0)]
    for k in indices:
        pt = list(pts[k])
        while len(stack) > 1:
            top = stack[-1]
            below = stack[-2]
            cross_val = _cross2d(_sub2d(top, below), _sub2d(pt, below))
            if cross_val <= 0:
                stack.pop()
            else:
                break
        stack.append(pt)

    return stack


# ---------------------------------------------------------------------------
# Minimum-area bounding rectangle (rotating calipers)
# ---------------------------------------------------------------------------


def _min_area_rect(pts):
    """Minimum-area bounding rectangle using rotating calipers.

    Returns dict with center, width, height, angle (degrees).
    """
    if len(pts) < 2:
        return {"center": pts[0] if pts else [0, 0], "width": 0, "height": 0, "angle": 0}
    if len(pts) == 2:
        mx = (pts[0][0] + pts[1][0]) / 2
        my = (pts[0][1] + pts[1][1]) / 2
        d = _dist2d(pts[0], pts[1])
        ang = math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
        return {"center": [mx, my], "width": d, "height": 0, "angle": ang}

    hull = _convex_hull_2d(pts)
    best_area = float("inf")
    best_rect = None

    for i in range(len(hull)):
        i2 = (i + 1) % len(hull)
        edge_dir = _normalize2d(_sub2d(hull[i2], hull[i]))
        edge_perp = [-edge_dir[1], edge_dir[0]]

        min_proj = float("inf")
        max_proj = float("-inf")
        min_perp = float("inf")
        max_perp = float("-inf")

        for j in range(len(hull)):
            v = _sub2d(hull[j], hull[i])
            proj = _dot2d(v, edge_dir)
            perp = _dot2d(v, edge_perp)
            min_proj = min(min_proj, proj)
            max_proj = max(max_proj, proj)
            min_perp = min(min_perp, perp)
            max_perp = max(max_perp, perp)

        w = max_proj - min_proj
        h = max_perp - min_perp
        area = w * h

        if area < best_area:
            best_area = area
            mid_proj = (min_proj + max_proj) / 2
            mid_perp = (min_perp + max_perp) / 2
            rcx = hull[i][0] + edge_dir[0] * mid_proj + edge_perp[0] * mid_perp
            rcy = hull[i][1] + edge_dir[1] * mid_proj + edge_perp[1] * mid_perp
            angle = math.degrees(math.atan2(edge_dir[1], edge_dir[0]))
            best_rect = {"center": [rcx, rcy], "width": w, "height": h, "angle": angle}

    if best_rect is None:
        c = _centroid2d(pts)
        return {"center": c, "width": 0, "height": 0, "angle": 0}
    return best_rect


def _rect_corners(cx, cy, hw, hh, rad):
    """Compute 4 corners of a rotated rectangle."""
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    offsets = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]]
    return [
        [cx + o[0] * cos_a - o[1] * sin_a, cy + o[0] * sin_a + o[1] * cos_a]
        for o in offsets
    ]


# ---------------------------------------------------------------------------
# Shape tests (classification)
# ---------------------------------------------------------------------------


def _test_line(pts):
    """Test if points are collinear (line shape)."""
    first = pts[0]
    last = pts[-1]
    total_dev = 0.0

    for i in range(1, len(pts) - 1):
        total_dev += _point_to_segment_dist(pts[i], first, last)

    span = _dist2d(first, last)
    if span < 1e-6:
        return {"shape": "line", "points": [first, last], "closed": False, "confidence": 0}

    avg_dev = total_dev / (len(pts) - 2) if len(pts) > 2 else 0
    rel_dev = avg_dev / span
    confidence = max(0, 1 - rel_dev * 20)
    return _fit_line(pts, confidence)


def _test_arc(pts):
    """Test if points form a circular arc."""
    n = len(pts)
    if n < 3:
        return {"shape": "arc", "points": [list(p) for p in pts], "closed": False, "confidence": 0}

    p1 = pts[0]
    p2 = pts[n // 2]
    p3 = pts[-1]
    circle = _circumcircle(p1, p2, p3)

    if not circle:
        return {"shape": "arc", "points": [list(p) for p in pts], "closed": False, "confidence": 0}

    total_dev = 0.0
    for i in range(n):
        r = _dist2d(pts[i], circle["center"])
        total_dev += abs(r - circle["radius"])
    avg_dev = total_dev / n
    rel_dev = avg_dev / circle["radius"] if circle["radius"] > 1e-6 else float("inf")

    ang1 = math.atan2(p1[1] - circle["center"][1], p1[0] - circle["center"][0])
    ang3 = math.atan2(p3[1] - circle["center"][1], p3[0] - circle["center"][0])
    sweep = abs(ang3 - ang1)
    if sweep > math.pi:
        sweep = 2 * math.pi - sweep

    confidence = max(0, (1 - rel_dev * 10) * (1 if sweep < 5.5 else 0.3))
    return _fit_arc(pts, confidence)


def _test_lshape(pts):
    """Test if points form an L-shape (sharp corner)."""
    n = len(pts)
    if n < 3:
        return {"shape": "lshape", "points": [list(p) for p in pts], "closed": False, "confidence": 0}

    first = pts[0]
    last = pts[-1]
    max_dist = 0.0
    corner_idx = 0

    for i in range(1, n - 1):
        d = _point_to_segment_dist(pts[i], first, last)
        if d > max_dist:
            max_dist = d
            corner_idx = i

    span = _dist2d(first, last)
    if span < 1e-6:
        return {"shape": "lshape", "points": [list(p) for p in pts], "closed": False, "confidence": 0}

    corner = pts[corner_idx]
    dev1 = sum(_point_to_segment_dist(pts[a], first, corner) for a in range(1, corner_idx))
    dev2 = sum(_point_to_segment_dist(pts[b], corner, last) for b in range(corner_idx + 1, n - 1))

    total_dev = (dev1 + dev2) / max(1, n - 3)
    rel_dev = total_dev / span

    v1 = _normalize2d(_sub2d(first, corner))
    v2 = _normalize2d(_sub2d(last, corner))
    dot_val = _dot2d(v1, v2)
    angle_factor = max(0, 1 - abs(dot_val))

    confidence = max(0, (1 - rel_dev * 15) * angle_factor)
    return _fit_lshape(pts, confidence)


def _test_rectangle(pts):
    """Test if points form a rectangle."""
    n = len(pts)
    if n < 4:
        return {"shape": "rectangle", "points": [], "closed": True, "confidence": 0}

    rect = _min_area_rect(pts)
    hw = rect["width"] / 2
    hh = rect["height"] / 2
    rad = math.radians(rect["angle"])
    corners = _rect_corners(rect["center"][0], rect["center"][1], hw, hh, rad)

    total_dist = 0.0
    for i in range(n):
        min_dist = float("inf")
        for e in range(4):
            e2 = (e + 1) % 4
            d = _point_to_segment_dist(pts[i], corners[e], corners[e2])
            min_dist = min(min_dist, d)
        total_dist += min_dist

    avg_dist = total_dist / n
    diag_len = math.sqrt(rect["width"] ** 2 + rect["height"] ** 2)
    if diag_len < 1:
        diag_len = 1
    rel_dist = avg_dist / diag_len

    aspect_penalty = 1.0
    if rect["width"] > 0 and rect["height"] > 0:
        aspect = min(rect["width"], rect["height"]) / max(rect["width"], rect["height"])
        if aspect < 0.05:
            aspect_penalty = 0.2

    closure_dist = _dist2d(pts[0], pts[-1])
    closure_factor = 1.0 if closure_dist < diag_len * 0.3 else 0.3

    confidence = max(0, (1 - rel_dist * 10) * aspect_penalty * closure_factor)
    return _fit_rectangle(pts, confidence)


def _test_scurve(pts):
    """Test if points form an S-curve (curvature sign change)."""
    n = len(pts)
    if n < 4:
        return {"shape": "scurve", "points": [list(p) for p in pts], "closed": False, "confidence": 0}

    sign_changes = 0
    prev_sign = 0
    for i in range(1, n - 1):
        v1 = _sub2d(pts[i], pts[i - 1])
        v2 = _sub2d(pts[i + 1], pts[i])
        cp = _cross2d(v1, v2)
        sign = 1 if cp > 0 else (-1 if cp < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            sign_changes += 1
        if sign != 0:
            prev_sign = sign

    inflection_score = 1 if 1 <= sign_changes <= 3 else 0.3
    line_test = _test_line(pts)
    not_line_penalty = 1 if line_test["confidence"] < 0.7 else 0.3

    confidence = 0.6 * inflection_score * not_line_penalty
    return _fit_scurve(pts, confidence)


def _test_ellipse(pts):
    """Test if points form an ellipse."""
    n = len(pts)
    if n < 5:
        return {"shape": "ellipse", "points": [], "closed": True, "confidence": 0}

    closure_dist = _dist2d(pts[0], pts[-1])
    c = _centroid2d(pts)
    avg_radius = sum(_dist2d(p, c) for p in pts) / n
    if avg_radius < 1:
        avg_radius = 1

    closure_factor = 1.0 if closure_dist < avg_radius * 0.5 else 0.3

    total_dev = sum(abs(_dist2d(p, c) - avg_radius) for p in pts)
    rel_dev = (total_dev / n) / avg_radius

    confidence = max(0, (1 - rel_dev * 5) * closure_factor)
    return _fit_ellipse(pts, confidence)


# ---------------------------------------------------------------------------
# Shape fitters
# ---------------------------------------------------------------------------


def _fit_line(pts, confidence=0.5):
    """Fit points to a line: return 2 endpoints."""
    return {
        "shape": "line",
        "points": [list(pts[0]), list(pts[-1])],
        "closed": False,
        "confidence": confidence,
    }


def _fit_arc(pts, confidence=0.5):
    """Fit points to a circular arc: return 3 points on the arc with handles."""
    n = len(pts)
    p1 = pts[0]
    p2 = pts[n // 2]
    p3 = pts[-1]
    circle = _circumcircle(p1, p2, p3)

    if not circle:
        return {"shape": "arc", "points": [list(p) for p in pts], "closed": False, "confidence": confidence}

    cx, cy, r = circle["center"][0], circle["center"][1], circle["radius"]

    ang1 = math.atan2(p1[1] - cy, p1[0] - cx)
    ang3 = math.atan2(p3[1] - cy, p3[0] - cx)
    sweep = ang3 - ang1
    while sweep > math.pi:
        sweep -= 2 * math.pi
    while sweep < -math.pi:
        sweep += 2 * math.pi

    ang_mid = ang1 + sweep * 0.5

    arc_points = [
        [cx + r * math.cos(ang1), cy + r * math.sin(ang1)],
        [cx + r * math.cos(ang_mid), cy + r * math.sin(ang_mid)],
        [cx + r * math.cos(ang1 + sweep), cy + r * math.sin(ang1 + sweep)],
    ]

    # Cubic bezier handle length for arc segments
    seg_angle = abs(sweep / 2)
    h_len = (4.0 / 3.0) * math.tan(seg_angle / 4.0) * r
    sweep_sign = 1 if sweep >= 0 else -1

    handles = []
    angles = [ang1, ang_mid, ang1 + sweep]
    for i, theta in enumerate(angles):
        tx = -math.sin(theta) * sweep_sign
        ty = math.cos(theta) * sweep_sign
        pt = arc_points[i]

        if i == 0:
            handles.append({
                "left": [pt[0], pt[1]],
                "right": [pt[0] + tx * h_len, pt[1] + ty * h_len],
            })
        elif i == 2:
            handles.append({
                "left": [pt[0] - tx * h_len, pt[1] - ty * h_len],
                "right": [pt[0], pt[1]],
            })
        else:
            handles.append({
                "left": [pt[0] - tx * h_len, pt[1] - ty * h_len],
                "right": [pt[0] + tx * h_len, pt[1] + ty * h_len],
            })

    return {
        "shape": "arc",
        "points": arc_points,
        "handles": handles,
        "closed": False,
        "confidence": confidence,
    }


def _fit_lshape(pts, confidence=0.5):
    """Fit points to an L-shape: return 3 points (start, corner, end)."""
    n = len(pts)
    first = pts[0]
    last = pts[-1]
    max_dist = 0.0
    corner_idx = 0
    for i in range(1, n - 1):
        d = _point_to_segment_dist(pts[i], first, last)
        if d > max_dist:
            max_dist = d
            corner_idx = i
    return {
        "shape": "lshape",
        "points": [list(first), list(pts[corner_idx]), list(last)],
        "closed": False,
        "confidence": confidence,
    }


def _fit_rectangle(pts, confidence=0.5):
    """Fit points to a rectangle: return 4 corner points."""
    rect = _min_area_rect(pts)
    hw = rect["width"] / 2
    hh = rect["height"] / 2
    rad = math.radians(rect["angle"])
    corners = _rect_corners(rect["center"][0], rect["center"][1], hw, hh, rad)
    return {
        "shape": "rectangle",
        "points": corners,
        "closed": True,
        "confidence": confidence,
    }


def _fit_scurve(pts, confidence=0.5):
    """Fit points to an S-curve: return 3 points (start, inflection, end) with handles."""
    n = len(pts)

    # Find inflection point
    infl_idx = n // 2
    prev_sign = 0
    for i in range(1, n - 1):
        v1 = _sub2d(pts[i], pts[i - 1])
        v2 = _sub2d(pts[i + 1], pts[i])
        cp = _cross2d(v1, v2)
        sign = 1 if cp > 0 else (-1 if cp < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            infl_idx = i
            break
        if sign != 0:
            prev_sign = sign

    first = pts[0]
    infl_pt = pts[infl_idx]
    last = pts[-1]
    scurve_points = [list(first), list(infl_pt), list(last)]

    # Catmull-Rom tangent handles
    tension = 1.0 / 6.0
    t0x = (infl_pt[0] - first[0]) * tension
    t0y = (infl_pt[1] - first[1]) * tension
    t1x = (last[0] - first[0]) * tension
    t1y = (last[1] - first[1]) * tension
    t2x = (last[0] - infl_pt[0]) * tension
    t2y = (last[1] - infl_pt[1]) * tension

    handles = [
        {"left": [first[0] - t0x, first[1] - t0y], "right": [first[0] + t0x, first[1] + t0y]},
        {"left": [infl_pt[0] - t1x, infl_pt[1] - t1y], "right": [infl_pt[0] + t1x, infl_pt[1] + t1y]},
        {"left": [last[0] - t2x, last[1] - t2y], "right": [last[0] + t2x, last[1] + t2y]},
    ]

    return {
        "shape": "scurve",
        "points": scurve_points,
        "handles": handles,
        "closed": False,
        "confidence": confidence,
    }


def _fit_ellipse(pts, confidence=0.5):
    """Fit points to an ellipse: return 4 cardinal points with handles.

    Uses PCA-based fitting (matching shapes.jsx). Falls back to cv2.fitEllipse
    when there are enough points and it is available.
    """
    c = _centroid2d(pts)
    n = len(pts)

    # Try cv2.fitEllipse for 5+ points (more accurate)
    if n >= 5:
        try:
            import cv2
            pts_arr = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
            (ecx, ecy), (ew, eh), eang = cv2.fitEllipse(pts_arr)
            # cv2 returns full axes, we need semi-axes
            a_axis = max(ew, eh) / 2
            b_axis = min(ew, eh) / 2
            angle = math.radians(eang)
            c = [ecx, ecy]
            return _ellipse_from_params(c, a_axis, b_axis, angle, confidence)
        except Exception:
            pass  # Fall through to PCA method

    # PCA-based ellipse fitting (matches shapes.jsx)
    cxx = sum((p[0] - c[0]) ** 2 for p in pts) / n
    cxy = sum((p[0] - c[0]) * (p[1] - c[1]) for p in pts) / n
    cyy = sum((p[1] - c[1]) ** 2 for p in pts) / n

    trace = cxx + cyy
    det = cxx * cyy - cxy * cxy
    discrim = max(0, trace * trace / 4 - det)
    ev1 = trace / 2 + math.sqrt(discrim)
    ev2 = trace / 2 - math.sqrt(discrim)

    a_axis = math.sqrt(max(0, 2 * ev1))
    b_axis = math.sqrt(max(0, 2 * ev2))

    if abs(cxy) > 1e-10:
        angle = math.atan2(ev1 - cxx, cxy)
    else:
        angle = 0 if cxx >= cyy else math.pi / 2

    return _ellipse_from_params(c, a_axis, b_axis, angle, confidence)


def _ellipse_from_params(center, a, b, angle, confidence):
    """Build ellipse result dict from parameters."""
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    k = (4.0 / 3.0) * (math.sqrt(2) - 1)  # ~0.5523

    cardinal_angles = [0, math.pi / 2, math.pi, 3 * math.pi / 2]
    ellipse_points = []
    handles = []

    for j, t in enumerate(cardinal_angles):
        ex = a * math.cos(t)
        ey = b * math.sin(t)
        px = ex * cos_a - ey * sin_a + center[0]
        py = ex * sin_a + ey * cos_a + center[1]
        ellipse_points.append([px, py])

        ltx = -a * math.sin(t)
        lty = b * math.cos(t)
        wtx = ltx * cos_a - lty * sin_a
        wty = ltx * sin_a + lty * cos_a
        t_len = math.sqrt(wtx * wtx + wty * wty)
        if t_len > 1e-10:
            wtx /= t_len
            wty /= t_len

        h_len = k * b if j % 2 == 0 else k * a

        handles.append({
            "left": [px - wtx * h_len, py - wty * h_len],
            "right": [px + wtx * h_len, py + wty * h_len],
        })

    return {
        "shape": "ellipse",
        "points": ellipse_points,
        "handles": handles,
        "closed": True,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Main classification function
# ---------------------------------------------------------------------------


SURFACE_HINT_MAPPING = {
    "flat": "line",
    "cylindrical": "arc",
    "convex": "arc",
    "concave": "arc",
    "saddle": "scurve",
    "angular": "lshape",
    "rectangular": "rectangle",
}


def classify_shape(points, surface_hint=None):
    """Classify a set of 2D points into a shape type.

    Port of classifyShape() from shapes.jsx. Tests each shape type and
    picks the highest-confidence match. Optionally boosts confidence when
    a surface hint matches the detected shape.

    Args:
        points: List of [x, y] points (must be sorted, e.g. by PCA).
        surface_hint: Optional surface type for confidence boosting.

    Returns:
        Dict with shape, points, closed, confidence, and optionally handles.
    """
    pts = [list(p) for p in points]

    if len(pts) < 2:
        return {"shape": "freeform", "points": pts, "closed": False, "confidence": 0}

    candidates = [
        _test_line(pts),
        _test_arc(pts),
        _test_lshape(pts),
        _test_rectangle(pts),
        _test_scurve(pts),
        _test_ellipse(pts),
    ]

    best = {"shape": "freeform", "points": pts, "closed": False, "confidence": 0.1}
    for c in candidates:
        if c["confidence"] > best["confidence"]:
            best = c

    # Apply surface hint bonus
    if surface_hint and best["shape"] != "freeform":
        suggested = SURFACE_HINT_MAPPING.get(surface_hint)
        if suggested and best["shape"] == suggested:
            best["confidence"] = min(1.0, best["confidence"] + 0.15)
        # Also check if a lower-confidence candidate matches the hint better
        for c in candidates:
            if c["shape"] == suggested and c["confidence"] > best["confidence"]:
                best = c
                best["confidence"] = min(1.0, best["confidence"] + 0.15)
                break

    return best


def fit_to_shape(pts, shape_type):
    """Force-fit points to a specified shape type.

    Port of fitToShape() from shapes.jsx.

    Args:
        pts: List of [x, y] points.
        shape_type: One of: line, arc, lshape, rectangle, scurve, ellipse, freeform.

    Returns:
        Dict with shape, points, closed, confidence, and optionally handles.
    """
    pts = [list(p) for p in pts]
    if len(pts) < 2:
        return {"shape": shape_type, "points": pts, "closed": False, "confidence": 0}

    fitters = {
        "line": _fit_line,
        "arc": _fit_arc,
        "lshape": _fit_lshape,
        "rectangle": _fit_rectangle,
        "scurve": _fit_scurve,
        "ellipse": _fit_ellipse,
    }
    fitter = fitters.get(shape_type)
    if fitter:
        return fitter(pts)
    return {"shape": "freeform", "points": pts, "closed": False, "confidence": 0.5}


# ---------------------------------------------------------------------------
# Douglas-Peucker simplification (matches geometry.jsx)
# ---------------------------------------------------------------------------


def douglas_peucker(pts, epsilon):
    """Douglas-Peucker polyline simplification.

    Args:
        pts: List of [x, y] points.
        epsilon: Max perpendicular distance tolerance.

    Returns:
        Simplified list of [x, y] points.
    """
    if len(pts) < 3:
        return [list(p) for p in pts]

    first = pts[0]
    last = pts[-1]
    max_dist = 0.0
    max_idx = 0

    for i in range(1, len(pts) - 1):
        d = _point_to_segment_dist(pts[i], first, last)
        if d > max_dist:
            max_dist = d
            max_idx = i

    if max_dist > epsilon:
        left = douglas_peucker(pts[: max_idx + 1], epsilon)
        right = douglas_peucker(pts[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [list(first), list(last)]


# ---------------------------------------------------------------------------
# Inflection point preservation (matches geometry.jsx)
# ---------------------------------------------------------------------------


def _find_inflection_indices(pts):
    """Find inflection points where curvature sign changes.

    Returns list of indices, always including first and last.
    """
    result = [0]
    if len(pts) < 3:
        if len(pts) > 1:
            result.append(len(pts) - 1)
        return result

    prev_sign = 0
    for i in range(1, len(pts) - 1):
        v1 = _sub2d(pts[i], pts[i - 1])
        v2 = _sub2d(pts[i + 1], pts[i])
        cp = _cross2d(v1, v2)
        sign = 1 if cp > 0 else (-1 if cp < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            result.append(i)
        if sign != 0:
            prev_sign = sign

    result.append(len(pts) - 1)
    return result


def _merge_inflection_points(simplified, all_pts, inflection_indices):
    """Merge inflection points into a simplified point set.

    Any inflection point not already in simplified is inserted at the
    position closest to its location along the simplified path.
    """
    if not inflection_indices:
        return simplified

    merged = [list(p) for p in simplified]
    eps = 1e-6

    for idx in inflection_indices:
        ip = all_pts[idx]
        found = False
        for m in merged:
            dx = m[0] - ip[0]
            dy = m[1] - ip[1]
            if dx * dx + dy * dy < eps:
                found = True
                break

        if not found:
            best_insert = len(merged)
            best_dist = float("inf")
            for s in range(len(merged) - 1):
                d = _point_to_segment_dist(ip, merged[s], merged[s + 1])
                if d < best_dist:
                    best_dist = d
                    best_insert = s + 1
            merged.insert(best_insert, list(ip))

    return merged


# ---------------------------------------------------------------------------
# Simplify (3-phase strategy)
# ---------------------------------------------------------------------------


def simplify_points(points, level, shape_type="", surface_hint=""):
    """Simplify points using a 3-phase surface-aware strategy.

    Phase 1 (level 0-30): Pure Douglas-Peucker
    Phase 2 (level 30-70): Douglas-Peucker with inflection preservation
    Phase 3 (level 70-100): Blend toward primitive shape fit

    Args:
        points: List of [x, y] points.
        level: Simplification level 0-100.
        shape_type: Optional forced shape type for Phase 3.
        surface_hint: Optional surface type for Phase 3 primitive selection.

    Returns:
        Dict with simplified points, point_count, level, and shape info.
    """
    pts = [list(p) for p in points]
    if len(pts) < 3:
        return {"points": pts, "point_count": len(pts), "level": level}

    # Compute bounding diagonal for epsilon scaling
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2)
    if diag < 1:
        diag = 1

    t = level / 100.0

    # Determine primitive fit for high-level simplification
    primitive_fit = None
    if shape_type:
        primitive_fit = fit_to_shape(pts, shape_type)
    elif surface_hint:
        hint_shape_map = {
            "flat": "line",
            "cylindrical": "arc",
            "convex": "arc",
            "concave": "arc",
            "saddle": "scurve",
            "angular": "lshape",
            "rectangular": "rectangle",
        }
        target_shape = hint_shape_map.get(surface_hint)
        if target_shape:
            primitive_fit = fit_to_shape(pts, target_shape)

    if t < 0.3 or not primitive_fit:
        # Phase 1: Pure Douglas-Peucker
        epsilon = diag * 0.001 * (100 ** t)
        simplified = douglas_peucker(pts, epsilon)
        return {"points": simplified, "point_count": len(simplified), "level": level}

    elif t < 0.7:
        # Phase 2: Douglas-Peucker with inflection preservation
        epsilon = diag * 0.001 * (100 ** t)
        dp_result = douglas_peucker(pts, epsilon)
        inflection_indices = _find_inflection_indices(pts)
        with_inflections = _merge_inflection_points(dp_result, pts, inflection_indices)
        return {"points": with_inflections, "point_count": len(with_inflections), "level": level}

    else:
        # Phase 3: Blend toward primitive fit
        blend_t = (t - 0.7) / 0.3

        if blend_t >= 0.95:
            # Pure primitive
            result = {
                "points": primitive_fit["points"],
                "point_count": len(primitive_fit["points"]),
                "level": level,
                "shape": primitive_fit["shape"],
                "closed": primitive_fit.get("closed", False),
            }
            if "handles" in primitive_fit:
                result["handles"] = primitive_fit["handles"]
            return result
        else:
            # Transitional: aggressive DP
            epsilon = diag * 0.001 * (100 ** t)
            dp_high = douglas_peucker(pts, epsilon)
            return {"points": dp_high, "point_count": len(dp_high), "level": level}


# ---------------------------------------------------------------------------
# LOD precomputation (matches geometry.jsx precomputeLOD)
# ---------------------------------------------------------------------------


def precompute_lod(points, num_levels=20, surface_hint=""):
    """Precompute LOD levels for a point array.

    Surface-aware simplification across exponentially spaced epsilon values,
    matching the 3-phase strategy from geometry.jsx precomputeLOD.

    Args:
        points: List of [x, y] points.
        num_levels: Number of LOD levels (2-100).
        surface_hint: Optional surface type for high-level primitive fitting.

    Returns:
        List of dicts with level (0-100), points, and point_count.
    """
    pts = [list(p) for p in points]
    if len(pts) < 2:
        return [{"level": 0, "points": pts, "point_count": len(pts)}]

    levels = [{"level": 0, "points": pts, "point_count": len(pts)}]

    for lv in range(1, num_levels + 1):
        slider_value = round(lv / num_levels * 100)
        result = simplify_points(pts, slider_value, surface_hint=surface_hint)
        entry = {
            "level": slider_value,
            "points": result["points"],
            "point_count": result["point_count"],
        }
        if "shape" in result:
            entry["shape"] = result["shape"]
        if "handles" in result:
            entry["handles"] = result["handles"]
        if "closed" in result:
            entry["closed"] = result["closed"]
        levels.append(entry)

    return levels


# ---------------------------------------------------------------------------
# JSON serializer for numpy types
# ---------------------------------------------------------------------------


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_classify_shape tool."""

    @mcp.tool(
        name="adobe_ai_classify_shape",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_classify_shape(
        params: ShapeClassifyInput,
    ) -> str:
        """Classify, simplify, or precompute LOD for 2D point arrays.

        Identifies geometric primitives (line, arc, L-shape, rectangle,
        S-curve, ellipse) from point data, with optional surface-aware
        simplification. Used by the C++ plugin SDK for shape editing
        and by the drawing pipeline for contour analysis.

        Actions:
        - classify: Identify the best-fit shape type and return fitted points
        - simplify: Reduce point count using 3-phase surface-aware strategy
        - lod: Precompute all LOD levels from raw points to minimal primitive

        Surface hints (flat, cylindrical, convex, concave, saddle, angular,
        rectangular) boost classification confidence and guide high-level
        simplification toward the correct primitive.
        """
        action = params.action.lower().strip()

        if action == "classify":
            if len(params.points) < 2:
                return json.dumps(
                    {"error": "At least 2 points required for classification."},
                    indent=2,
                )

            result = classify_shape(
                params.points,
                surface_hint=params.surface_hint or None,
            )
            return json.dumps(result, indent=2, default=_json_default)

        elif action == "simplify":
            if len(params.points) < 2:
                return json.dumps(
                    {"error": "At least 2 points required for simplification."},
                    indent=2,
                )

            result = simplify_points(
                params.points,
                level=params.simplify_level,
                shape_type=params.shape_type,
                surface_hint=params.surface_hint,
            )
            return json.dumps(result, indent=2, default=_json_default)

        elif action == "lod":
            if len(params.points) < 2:
                return json.dumps(
                    {"error": "At least 2 points required for LOD computation."},
                    indent=2,
                )

            result = precompute_lod(
                params.points,
                num_levels=params.num_lod_levels,
                surface_hint=params.surface_hint,
            )
            return json.dumps(result, indent=2, default=_json_default)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["classify", "simplify", "lod"],
            })
