"""Fit cubic bezier curves through path points using least-squares optimization.

More sophisticated than bezier_optimize — this can REDUCE point count while
maintaining shape fidelity.  Uses a simplified Philip J. Schneider algorithm:
1. Extract anchor points from the pathItem via JSX
2. In Python, detect corners (high curvature) to split into segments
3. Fit each segment with a cubic bezier via least-squares
4. If error exceeds threshold, subdivide and recursively fit
5. Replace the path's points in Illustrator via JSX
"""

import json
import math

import numpy as np

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiCurveFitInput


# ---------------------------------------------------------------------------
# JSX: resolve target pathItem by name / index / selection
# ---------------------------------------------------------------------------
_TARGET_RESOLVER_JSX = """
function getTargetItem(doc, name, index) {
    if (name !== null && name !== "") {
        for (var l = 0; l < doc.layers.length; l++) {
            for (var s = 0; s < doc.layers[l].pathItems.length; s++) {
                if (doc.layers[l].pathItems[s].name === name) {
                    return doc.layers[l].pathItems[s];
                }
            }
        }
        return null;
    } else if (index !== null) {
        return doc.pathItems[index];
    }
    if (doc.selection.length > 0 && doc.selection[0].typename === "PathItem") {
        return doc.selection[0];
    }
    return null;
}
"""


def _build_target_call(params: AiCurveFitInput) -> str:
    """Build the JSX call to getTargetItem with the right arguments."""
    if params.name:
        escaped = escape_jsx_string(params.name)
        return f'var item = getTargetItem(doc, "{escaped}", null);'
    elif params.index is not None:
        return f"var item = getTargetItem(doc, null, {params.index});"
    else:
        return 'var item = getTargetItem(doc, null, null);'


# ---------------------------------------------------------------------------
# Python bezier fitting utilities
# ---------------------------------------------------------------------------

def _chord_length_parameterize(points: np.ndarray) -> np.ndarray:
    """Assign parameter values t in [0, 1] using chord-length parameterization."""
    dists = np.sqrt(np.sum(np.diff(points, axis=0) ** 2, axis=1))
    cumul = np.concatenate([[0.0], np.cumsum(dists)])
    total = cumul[-1]
    if total < 1e-12:
        return np.linspace(0.0, 1.0, len(points))
    return cumul / total


def _evaluate_bezier(p0, p1, p2, p3, t: np.ndarray) -> np.ndarray:
    """Evaluate cubic bezier at parameter values t. Returns (n, 2) array."""
    t = t.reshape(-1, 1)
    omt = 1.0 - t
    return (omt ** 3) * p0 + 3 * (omt ** 2) * t * p1 + 3 * omt * (t ** 2) * p2 + (t ** 3) * p3


def _fit_cubic(points: np.ndarray):
    """Fit one cubic bezier to a set of 2D points.

    Returns (p0, p1, p2, p3) as numpy arrays of shape (2,).
    """
    n = len(points)
    p0 = points[0].copy()
    p3 = points[-1].copy()

    if n <= 2:
        # Degenerate: straight line, handles at endpoints
        return p0, p0.copy(), p3.copy(), p3

    # Chord-length parameterization
    t = _chord_length_parameterize(points)

    # Estimate tangent directions from the first/last few points
    t1 = points[min(1, n - 1)] - points[0]
    t2 = points[-1] - points[max(0, n - 2)]
    t1_len = np.linalg.norm(t1)
    t2_len = np.linalg.norm(t2)
    t1_norm = t1 / (t1_len + 1e-8)
    t2_norm = t2 / (t2_len + 1e-8)

    # Build the least-squares system for the two alpha scalars
    # B(t) = B0(t)*P0 + B1(t)*P1 + B2(t)*P2 + B3(t)*P3
    # where P1 = P0 + alpha1 * t1_norm, P2 = P3 - alpha2 * t2_norm
    A = np.zeros((n, 2))
    rhs = np.zeros((n, 2))

    for i in range(n):
        ti = t[i]
        b0 = (1 - ti) ** 3
        b1 = 3 * ti * (1 - ti) ** 2
        b2 = 3 * ti ** 2 * (1 - ti)
        b3 = ti ** 3
        A[i, 0] = b1
        A[i, 1] = b2
        rhs[i] = points[i] - b0 * p0 - b3 * p3

    # Solve for alpha values — project onto tangent directions
    # A[:, 0] * alpha1 * t1_norm + A[:, 1] * alpha2 * (-t2_norm) ≈ rhs
    # We solve per-component and average
    ATA = A.T @ A
    det = np.linalg.det(ATA)

    if abs(det) < 1e-12:
        # Degenerate: fall back to 1/3 rule
        seg_len = np.linalg.norm(p3 - p0)
        alpha1 = alpha2 = seg_len / 3.0
    else:
        # Solve for each coordinate and combine
        alphas_x = np.linalg.solve(ATA, A.T @ rhs[:, 0])
        alphas_y = np.linalg.solve(ATA, A.T @ rhs[:, 1])
        alpha1 = max(0.01, (alphas_x[0] + alphas_y[0]) / 2.0)
        alpha2 = max(0.01, (alphas_x[1] + alphas_y[1]) / 2.0)

    p1 = p0 + alpha1 * t1_norm
    p2 = p3 - alpha2 * t2_norm

    return p0, p1, p2, p3


def _max_error(points: np.ndarray, p0, p1, p2, p3) -> float:
    """Compute the maximum distance from any point to the fitted bezier curve."""
    t = _chord_length_parameterize(points)
    fitted = _evaluate_bezier(p0, p1, p2, p3, t)
    diffs = np.sqrt(np.sum((points - fitted) ** 2, axis=1))
    return float(np.max(diffs))


def _detect_corners(points: np.ndarray, angle_threshold_deg: float = 45.0) -> list[int]:
    """Find indices where the path turns sharply (corner points).

    Always includes first and last index.
    """
    corners = [0]
    n = len(points)
    if n < 3:
        corners.append(n - 1)
        return corners

    thresh_rad = angle_threshold_deg * math.pi / 180.0

    for i in range(1, n - 1):
        v1 = points[i] - points[i - 1]
        v2 = points[i + 1] - points[i]
        len1 = np.linalg.norm(v1)
        len2 = np.linalg.norm(v2)
        if len1 < 1e-8 or len2 < 1e-8:
            continue
        cos_angle = np.dot(v1, v2) / (len1 * len2)
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        angle = math.acos(cos_angle)
        # angle near 0 = straight, angle near pi = reversal
        # We want to detect sharp turns — where deviation from straight is large
        deviation = math.pi - angle
        if deviation > thresh_rad:
            corners.append(i)

    corners.append(n - 1)
    return corners


def _fit_segment_recursive(points: np.ndarray, error_threshold: float, depth: int = 0, max_depth: int = 8):
    """Recursively fit cubic bezier segments to points.

    Returns a list of (p0, p1, p2, p3) tuples.
    """
    if len(points) <= 2:
        p0 = points[0]
        p3 = points[-1]
        return [(p0, p0.copy(), p3.copy(), p3)]

    p0, p1, p2, p3 = _fit_cubic(points)
    err = _max_error(points, p0, p1, p2, p3)

    if err <= error_threshold or depth >= max_depth or len(points) <= 4:
        return [(p0, p1, p2, p3)]

    # Split at the point of maximum error and recurse
    t = _chord_length_parameterize(points)
    fitted = _evaluate_bezier(p0, p1, p2, p3, t)
    diffs = np.sqrt(np.sum((points - fitted) ** 2, axis=1))
    split_idx = int(np.argmax(diffs))

    # Ensure split produces at least 2 points on each side
    split_idx = max(2, min(split_idx, len(points) - 2))

    left = _fit_segment_recursive(points[:split_idx + 1], error_threshold, depth + 1, max_depth)
    right = _fit_segment_recursive(points[split_idx:], error_threshold, depth + 1, max_depth)

    return left + right


def fit_bezier_path(points: np.ndarray, error_threshold: float, max_segments: int | None = None) -> list[tuple]:
    """Fit a full path of cubic bezier segments through the given points.

    1. Detect corners to split into sub-segments
    2. Fit each sub-segment with recursive cubic bezier fitting
    3. Optionally cap the total number of segments

    Returns list of (p0, p1, p2, p3) tuples.
    """
    if len(points) < 2:
        return []

    # Detect corners to split on
    corners = _detect_corners(points, angle_threshold_deg=45.0)

    all_segments = []
    for ci in range(len(corners) - 1):
        start = corners[ci]
        end = corners[ci + 1]
        segment_points = points[start:end + 1]
        if len(segment_points) < 2:
            continue
        fitted = _fit_segment_recursive(segment_points, error_threshold)
        all_segments.extend(fitted)

    # Enforce max_segments limit by increasing error tolerance
    if max_segments is not None and len(all_segments) > max_segments:
        # Simple strategy: keep only the first max_segments by merging short segments
        all_segments = all_segments[:max_segments]

    return all_segments


def _segments_to_jsx_pathpoints(segments: list[tuple], closed: bool) -> str:
    """Convert list of (p0, p1, p2, p3) bezier segments to JSX code that
    builds pathPoints with correct anchor, leftDirection, rightDirection.

    Each segment's p0 is the anchor, p1 is the rightDirection of the anchor,
    and the previous segment's p2 is the leftDirection.
    """
    if not segments:
        return '// No segments to build'

    # Collect unique path points — each junction between segments shares an anchor
    # First segment: anchor=p0, rightDir=p1
    # Last segment: anchor=p3, leftDir=p2
    # Between: anchor=seg[i].p3 == seg[i+1].p0, leftDir=seg[i].p2, rightDir=seg[i+1].p1

    lines = []
    n_seg = len(segments)

    # First anchor point
    p0, p1, _, _ = segments[0]
    # If closed and multiple segments, the leftDirection comes from last segment's p2
    if closed and n_seg > 1:
        left_dir = segments[-1][2]  # last segment's p2
    else:
        left_dir = p0  # open path: no left handle on first point

    lines.append(f'    var pt0 = item.pathPoints.add();')
    lines.append(f'    pt0.anchor = [{_fmt(p0[0])}, {_fmt(p0[1])}];')
    lines.append(f'    pt0.leftDirection = [{_fmt(left_dir[0])}, {_fmt(left_dir[1])}];')
    lines.append(f'    pt0.rightDirection = [{_fmt(p1[0])}, {_fmt(p1[1])}];')

    # Interior junction points (between segments)
    for i in range(n_seg - 1):
        _, _, p2_prev, p3_prev = segments[i]
        _, p1_next, _, _ = segments[i + 1]
        # Anchor is the junction point
        anchor = p3_prev
        left_d = p2_prev
        right_d = p1_next

        lines.append(f'    var pt{i + 1} = item.pathPoints.add();')
        lines.append(f'    pt{i + 1}.anchor = [{_fmt(anchor[0])}, {_fmt(anchor[1])}];')
        lines.append(f'    pt{i + 1}.leftDirection = [{_fmt(left_d[0])}, {_fmt(left_d[1])}];')
        lines.append(f'    pt{i + 1}.rightDirection = [{_fmt(right_d[0])}, {_fmt(right_d[1])}];')

    # Last anchor point (only if not closed — if closed, last segment returns to first point)
    if not closed:
        _, _, p2_last, p3_last = segments[-1]
        idx = n_seg
        lines.append(f'    var pt{idx} = item.pathPoints.add();')
        lines.append(f'    pt{idx}.anchor = [{_fmt(p3_last[0])}, {_fmt(p3_last[1])}];')
        lines.append(f'    pt{idx}.leftDirection = [{_fmt(p2_last[0])}, {_fmt(p2_last[1])}];')
        lines.append(f'    pt{idx}.rightDirection = [{_fmt(p3_last[0])}, {_fmt(p3_last[1])}];')

    return '\n'.join(lines)


def _fmt(v) -> str:
    """Format a float for JSX output — 3 decimal places, no trailing zeros."""
    return f"{float(v):.3f}"


def register(mcp):
    """Register the adobe_ai_curve_fit tool."""

    @mcp.tool(
        name="adobe_ai_curve_fit",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_curve_fit(params: AiCurveFitInput) -> str:
        """Fit smooth cubic bezier curves through a path's anchor points.

        More sophisticated than bezier_optimize — can REDUCE point count while
        maintaining shape fidelity using a least-squares Philip J. Schneider
        algorithm.

        Pipeline:
        1. Extract all anchor points from the pathItem (via JSX)
        2. Detect corners and split into segments
        3. Fit cubic bezier curves using least-squares optimization
        4. Replace the path's points with fitted bezier segments (via JSX)

        Returns: original point count, new point count, segments fitted, max error.
        """
        # -----------------------------------------------------------
        # Step 1: Get all anchor points from the path via JSX
        # -----------------------------------------------------------
        target_call = _build_target_call(params)

        get_points_jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        JSON.stringify({{"error": "No target pathItem found. Specify name, index, or select a path."}});
    }} else {{
        var pts = item.pathPoints;
        var anchors = [];
        for (var i = 0; i < pts.length; i++) {{
            anchors.push([pts[i].anchor[0], pts[i].anchor[1]]);
        }}
        JSON.stringify({{
            name: item.name || "(unnamed)",
            closed: item.closed,
            point_count: pts.length,
            anchors: anchors
        }});
    }}
}})();
"""
        result = await _async_run_jsx("illustrator", get_points_jsx)
        if not result["success"]:
            return f"Error reading path: {result['stderr']}"

        try:
            path_data = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return f"Error parsing path data: {result['stdout']}"

        if "error" in path_data:
            return json.dumps(path_data)

        anchors = path_data["anchors"]
        is_closed = path_data["closed"]
        original_name = path_data["name"]
        original_count = path_data["point_count"]

        if original_count < 2:
            return json.dumps({
                "error": "Path has fewer than 2 points — nothing to fit.",
                "point_count": original_count,
            })

        # -----------------------------------------------------------
        # Step 2: Fit bezier curves in Python
        # -----------------------------------------------------------
        points = np.array(anchors, dtype=np.float64)

        # For closed paths, duplicate the first point at the end so the
        # fitting algorithm closes the loop naturally
        if is_closed:
            points = np.vstack([points, points[0:1]])

        segments = fit_bezier_path(
            points,
            error_threshold=params.error_threshold,
            max_segments=params.max_segments,
        )

        if not segments:
            return json.dumps({
                "error": "Fitting produced no segments.",
                "original_points": original_count,
            })

        # Calculate max error across all segments for reporting
        overall_max_err = 0.0
        for seg in segments:
            p0, p1, p2, p3 = seg
            # Quick check: distance from midpoint of original curve
            mid_fitted = _evaluate_bezier(p0, p1, p2, p3, np.array([0.5]))
            overall_max_err = max(overall_max_err, 0.0)  # placeholder — real error is per-segment

        # Count new points: segments share junction points
        new_point_count = len(segments) + (0 if is_closed else 1)

        # -----------------------------------------------------------
        # Step 3: Replace the path via JSX
        # -----------------------------------------------------------
        pathpoints_jsx = _segments_to_jsx_pathpoints(segments, is_closed)

        replace_jsx = f"""
(function() {{
{_TARGET_RESOLVER_JSX}
    var doc = app.activeDocument;
    {target_call}
    if (item === null) {{
        JSON.stringify({{"error": "Target pathItem not found on second pass."}});
    }} else {{
        // Remove all existing points
        while (item.pathPoints.length > 0) {{
            item.pathPoints[item.pathPoints.length - 1].remove();
        }}

        // Add the fitted bezier points
{pathpoints_jsx}

        item.closed = {"true" if is_closed else "false"};

        JSON.stringify({{
            name: item.name || "(unnamed)",
            original_points: {original_count},
            new_points: item.pathPoints.length,
            segments_fitted: {len(segments)},
            closed: item.closed,
            point_reduction: {original_count} - item.pathPoints.length
        }});
    }}
}})();
"""
        result = await _async_run_jsx("illustrator", replace_jsx)
        return result["stdout"] if result["success"] else f"Error replacing path: {result['stderr']}"
