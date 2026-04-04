"""Landmark-and-axis-first drawing system for Illustrator.

Tier 1 (top): Pure Python geometry functions — detect landmarks, compute axes,
convert between pixel/AI/axis-relative coordinate systems, infer occluded
landmarks via symmetry.

Tier 2 (bottom): MCP tool registration that wires actions to JSX execution
and rig persistence.
"""

import json
import math
import os
from typing import Optional

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.models import AiLandmarkAxisInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig
from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ── Tier 1: Pure Python Geometry ─────────────────────────────────────────


def compute_transform(img_w, img_h, ab_left, ab_top, ab_right, ab_bottom):
    """Compute persistent pixel-to-AI transform.

    Returns dict: {scale, offset_x, offset_y, artboard_rect}

    AI coordinate system: Y increases upward. Pixel: Y increases downward.
    The transform maps pixel (0,0) [top-left] to AI (ab_left, ab_top).
    """
    ab_w = ab_right - ab_left
    ab_h = ab_top - ab_bottom  # top > bottom in AI
    scale_x = ab_w / img_w
    scale_y = ab_h / img_h
    scale = min(scale_x, scale_y)
    # Center the image on the artboard
    offset_x = ab_left + (ab_w - img_w * scale) / 2
    offset_y = ab_top - (ab_h - img_h * scale) / 2  # start from top
    return {
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "artboard_rect": [ab_left, ab_top, ab_right, ab_bottom],
    }


def pixel_to_ai(px_x, px_y, transform):
    """Convert pixel coords to AI coords."""
    s = transform["scale"]
    return (
        transform["offset_x"] + px_x * s,
        transform["offset_y"] - px_y * s,  # Y flip
    )


def ai_to_pixel(ai_x, ai_y, transform):
    """Convert AI coords to pixel coords."""
    s = transform["scale"]
    return (
        (ai_x - transform["offset_x"]) / s,
        (transform["offset_y"] - ai_y) / s,  # Y flip
    )


def compute_axis_from_landmarks(landmark_a_ai, landmark_b_ai):
    """Compute axis from two AI-coordinate positions.

    Returns: {angle_deg, angle_rad, length, origin, direction, normal}
    """
    dx = landmark_b_ai[0] - landmark_a_ai[0]
    dy = landmark_b_ai[1] - landmark_a_ai[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        return {
            "angle_deg": 0, "angle_rad": 0, "length": 0,
            "origin": list(landmark_a_ai), "direction": [1, 0], "normal": [0, 1],
        }
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    direction = [dx / length, dy / length]
    # Normal is 90 deg CCW from direction (right-hand rule, Y-up)
    normal = [-direction[1], direction[0]]
    return {
        "angle_deg": round(angle_deg, 2),
        "angle_rad": angle_rad,
        "length": round(length, 2),
        "origin": [round(landmark_a_ai[0], 2), round(landmark_a_ai[1], 2)],
        "direction": [round(direction[0], 4), round(direction[1], 4)],
        "normal": [round(normal[0], 4), round(normal[1], 4)],
    }


def compute_axis_from_pca(points):
    """Compute primary axis via PCA. Returns same format as compute_axis_from_landmarks."""
    pts = np.array(points, dtype=np.float64)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    cov = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Primary axis = eigenvector with largest eigenvalue
    primary = eigenvectors[:, np.argmax(eigenvalues)]
    # Orient: prefer Y-negative direction (downward in AI = toward feet)
    if primary[1] > 0:
        primary = -primary
    angle_rad = math.atan2(float(primary[1]), float(primary[0]))
    length = float(np.sqrt(eigenvalues.max())) * 2  # approximate span
    return {
        "angle_deg": round(math.degrees(angle_rad), 2),
        "angle_rad": angle_rad,
        "length": round(length, 2),
        "origin": [round(float(centroid[0]), 2), round(float(centroid[1]), 2)],
        "direction": [round(float(primary[0]), 4), round(float(primary[1]), 4)],
        "normal": [round(float(-primary[1]), 4), round(float(primary[0]), 4)],
    }


def axis_to_ai(origin, axis_angle_rad, along_pct, across_pct, axis_length, cross_width,
               near_cross_width=None, far_cross_width=None):
    """Convert axis-relative (along%, across%) to AI coordinates.

    along_pct: 0.0=origin, 1.0=endpoint. Can exceed [0,1].
    across_pct: 0.0=on axis. Positive=left of axis (CCW). Negative=right.
                Range: -1.0 to 1.0 where |1.0| = full cross_width from center.

    For perspective: positive across uses near_cross_width, negative uses far_cross_width.
    """
    along_dist = along_pct * axis_length

    # Determine effective cross width based on which side of the axis
    if across_pct >= 0:
        eff_width = near_cross_width if near_cross_width is not None else cross_width
    else:
        eff_width = far_cross_width if far_cross_width is not None else cross_width
    across_dist = across_pct * eff_width

    cos_a = math.cos(axis_angle_rad)
    sin_a = math.sin(axis_angle_rad)
    # Rotate [along, across] by axis angle
    # along is in the direction of the axis, across is perpendicular (normal direction)
    dx = along_dist * cos_a - across_dist * sin_a
    dy = along_dist * sin_a + across_dist * cos_a
    return (round(origin[0] + dx, 2), round(origin[1] + dy, 2))


def ai_to_axis(point, origin, axis_angle_rad, axis_length, cross_width):
    """Convert AI coordinates back to (along_pct, across_pct)."""
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    cos_a = math.cos(-axis_angle_rad)  # inverse rotation
    sin_a = math.sin(-axis_angle_rad)
    along_dist = dx * cos_a - dy * sin_a
    across_dist = dx * sin_a + dy * cos_a
    along_pct = along_dist / axis_length if axis_length > 0 else 0
    across_pct = across_dist / cross_width if cross_width > 0 else 0
    return (round(along_pct, 4), round(across_pct, 4))


def batch_axis_to_ai(axis_def, points, cross_width, near_cross_width=None, far_cross_width=None):
    """Convert list of [along_pct, across_pct] to AI coordinates."""
    result = []
    for along_pct, across_pct in points:
        ai = axis_to_ai(
            axis_def["origin"], axis_def["angle_rad"],
            along_pct, across_pct, axis_def["length"], cross_width,
            near_cross_width, far_cross_width,
        )
        result.append(list(ai))
    return result


def perspective_cross_width(base_width, view_angle_deg, side):
    """Compute foreshortened cross-axis width.

    Near side: base_width * cos(view_angle / 2)
    Far side: base_width * cos(view_angle)
    """
    view_rad = math.radians(view_angle_deg)
    if side == "near":
        return round(base_width * math.cos(view_rad / 2), 2)
    else:
        return round(base_width * math.cos(view_rad), 2)


# ── Occlusion Inference ──────────────────────────────────────────────────


SYMMETRY_PAIRS = {
    "shoulder_l": "shoulder_r", "shoulder_r": "shoulder_l",
    "elbow_l": "elbow_r", "elbow_r": "elbow_l",
    "wrist_l": "wrist_r", "wrist_r": "wrist_l",
    "hip_l": "hip_r", "hip_r": "hip_l",
    "knee_l": "knee_r", "knee_r": "knee_l",
    "ankle_l": "ankle_r", "ankle_r": "ankle_l",
    "eye_l": "eye_r", "eye_r": "eye_l",
    "ear_l": "ear_r", "ear_r": "ear_l",
}

MIDLINE_LANDMARKS = {
    "head_top", "chin", "neck", "spine_top", "spine_mid",
    "spine_base", "hip_center", "nose", "mouth_center",
}


def reflect_landmark_across_midline(landmark_ai, midline_x, view_angle_deg):
    """Reflect a landmark across the midline with perspective foreshortening."""
    dx = landmark_ai[0] - midline_x
    foreshorten = math.cos(math.radians(view_angle_deg))
    reflected_x = midline_x - dx * foreshorten
    return [round(reflected_x, 2), round(landmark_ai[1], 2)]


def infer_occluded_landmarks(visible_landmarks, view_angle_deg, symmetric=True):
    """Infer positions of occluded landmarks from visible ones + symmetry.

    visible_landmarks: {name: {"ai": [x,y], "type": str}, ...}
    Returns: {name: {"ai": [x,y], "type": str, "inferred": True}, ...}
    """
    if not symmetric:
        return {}

    # Find midline X from midline landmarks
    midline_xs = []
    for name in MIDLINE_LANDMARKS:
        if name in visible_landmarks and "ai" in visible_landmarks[name]:
            midline_xs.append(visible_landmarks[name]["ai"][0])
    midline_x = sum(midline_xs) / len(midline_xs) if midline_xs else None

    if midline_x is None:
        return {}

    inferred = {}
    for name, partner in SYMMETRY_PAIRS.items():
        if name not in visible_landmarks and partner in visible_landmarks:
            partner_ai = visible_landmarks[partner]["ai"]
            reflected = reflect_landmark_across_midline(partner_ai, midline_x, view_angle_deg)
            inferred[name] = {
                "ai": reflected,
                "type": visible_landmarks[partner].get("type", "structural"),
                "inferred": True,
            }

    return inferred


# ── Landmark Detection from Image ────────────────────────────────────────


def detect_landmarks_from_image(image_path):
    """Detect structural + feature landmarks from a reference image.

    Returns: {"landmarks": {name: {"px": [x,y], "type": str}}, "image_size": [w,h]}
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image: {image_path}"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return {"landmarks": {}, "image_size": [w, h]}

    # Use the largest contour as the character silhouette
    contour = max(contours, key=cv2.contourArea)
    pts = contour.reshape(-1, 2)

    # Structural landmarks from contour extremes
    top_idx = pts[:, 1].argmin()
    bottom_idx = pts[:, 1].argmax()
    left_idx = pts[:, 0].argmin()
    right_idx = pts[:, 0].argmax()

    head_top = pts[top_idx].tolist()
    feet_bottom = pts[bottom_idx].tolist()
    leftmost = pts[left_idx].tolist()
    rightmost = pts[right_idx].tolist()

    # Centroid
    M = cv2.moments(contour)
    if M["m00"] > 0:
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
    else:
        cx, cy = w / 2, h / 2

    # Interpolated structural landmarks
    total_h = feet_bottom[1] - head_top[1]
    center_x = (leftmost[0] + rightmost[0]) / 2

    landmarks = {
        "head_top": {"px": head_top, "type": "structural"},
        "chin": {"px": [center_x, head_top[1] + total_h * 0.35], "type": "structural"},
        "neck": {"px": [center_x, head_top[1] + total_h * 0.30], "type": "structural"},
        "spine_mid": {"px": [cx, cy], "type": "structural"},
        "hip_center": {"px": [center_x, head_top[1] + total_h * 0.55], "type": "structural"},
        "feet_bottom": {"px": feet_bottom, "type": "structural"},
        "leftmost": {"px": leftmost, "type": "structural"},
        "rightmost": {"px": rightmost, "type": "structural"},
    }

    # Widest points at different heights for shoulder/hip estimation
    for frac, name_l, name_r in [(0.25, "shoulder_l", "shoulder_r"), (0.55, "hip_l", "hip_r")]:
        y_target = head_top[1] + total_h * frac
        band = pts[np.abs(pts[:, 1] - y_target) < total_h * 0.05]
        if len(band) > 0:
            landmarks[name_l] = {"px": [float(band[:, 0].min()), float(y_target)], "type": "structural"}
            landmarks[name_r] = {"px": [float(band[:, 0].max()), float(y_target)], "type": "structural"}

    return {"landmarks": landmarks, "image_size": [w, h]}


# ── Tier 2: MCP Tool Registration ───────────────────────────────────────


def register(mcp):
    @mcp.tool(
        name="adobe_ai_landmark_axis",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_landmark_axis(params: AiLandmarkAxisInput) -> str:
        """Landmark-and-axis drawing system.

        Actions:
        - detect_landmarks: find structural landmarks from a reference image
        - add_landmark: manually place a named landmark in AI or pixel coords
        - compute_axis: compute axis between two landmarks
        - draw_on_axis: draw a shape using axis-relative [along%, across%] points
        - validate_placement: check placed path against intended positions
        - infer_occluded: infer hidden landmark positions via bilateral symmetry
        """

        if params.action == "detect_landmarks":
            # ── Detect landmarks from reference image ──
            if not params.image_path:
                return json.dumps({"error": "detect_landmarks requires image_path"})
            if not os.path.exists(params.image_path):
                return json.dumps({"error": f"Image not found: {params.image_path}"})

            detection = detect_landmarks_from_image(params.image_path)
            if "error" in detection:
                return json.dumps(detection)

            # Query artboard rect via JSX
            ab_jsx = """
var doc = app.activeDocument;
var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
JSON.stringify(ab.artboardRect);
"""
            ab_result = await _async_run_jsx("illustrator", ab_jsx)
            if not ab_result["success"]:
                return json.dumps({"error": f"JSX artboard query failed: {ab_result['stderr']}"})

            try:
                ab_rect = json.loads(ab_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": f"Invalid artboard rect: {ab_result['stdout']}"})

            # Compute pixel-to-AI transform
            img_w, img_h = detection["image_size"]
            transform = compute_transform(img_w, img_h, ab_rect[0], ab_rect[1], ab_rect[2], ab_rect[3])

            # Convert all pixel landmarks to AI coords
            rig = _load_rig(params.character_name)
            rig.setdefault("landmarks", {})
            rig.setdefault("axes", {})
            rig["transform"] = transform
            rig["image_source"] = params.image_path
            rig["image_size"] = detection["image_size"]

            for lm_name, lm_data in detection["landmarks"].items():
                px = lm_data["px"]
                ai_x, ai_y = pixel_to_ai(px[0], px[1], transform)
                rig["landmarks"][lm_name] = {
                    "px": px,
                    "ai": [round(ai_x, 2), round(ai_y, 2)],
                    "type": lm_data["type"],
                }

            _save_rig(params.character_name, rig)

            # Build summary
            landmark_summary = {}
            for name, data in rig["landmarks"].items():
                landmark_summary[name] = {"ai": data["ai"], "type": data["type"]}

            return json.dumps({
                "action": "detect_landmarks",
                "character": params.character_name,
                "landmark_count": len(rig["landmarks"]),
                "landmarks": landmark_summary,
                "image_size": detection["image_size"],
                "transform": transform,
            })

        elif params.action == "add_landmark":
            # ── Manually add/update a landmark ──
            if not params.landmark_name:
                return json.dumps({"error": "add_landmark requires landmark_name"})

            rig = _load_rig(params.character_name)
            rig.setdefault("landmarks", {})
            rig.setdefault("axes", {})

            lm_entry = {"type": params.landmark_type or "structural"}

            if params.x is not None and params.y is not None:
                # Direct AI coordinates
                lm_entry["ai"] = [round(params.x, 2), round(params.y, 2)]
                # If transform exists, also compute pixel coords
                if rig.get("transform"):
                    px = ai_to_pixel(params.x, params.y, rig["transform"])
                    lm_entry["px"] = [round(px[0], 2), round(px[1], 2)]
            elif params.px_x is not None and params.px_y is not None:
                # Pixel coordinates — convert via stored transform
                if not rig.get("transform"):
                    return json.dumps({"error": "No transform stored. Run detect_landmarks first or provide AI coords."})
                ai_x, ai_y = pixel_to_ai(params.px_x, params.px_y, rig["transform"])
                lm_entry["ai"] = [round(ai_x, 2), round(ai_y, 2)]
                lm_entry["px"] = [round(params.px_x, 2), round(params.px_y, 2)]
            else:
                return json.dumps({"error": "add_landmark requires (x, y) or (px_x, px_y)"})

            rig["landmarks"][params.landmark_name] = lm_entry
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "add_landmark",
                "landmark": params.landmark_name,
                "position": lm_entry,
            })

        elif params.action == "compute_axis":
            # ── Compute axis between two landmarks ──
            if not params.axis_name:
                return json.dumps({"error": "compute_axis requires axis_name"})
            if not params.from_landmark or not params.to_landmark:
                return json.dumps({"error": "compute_axis requires from_landmark and to_landmark"})

            rig = _load_rig(params.character_name)
            rig.setdefault("landmarks", {})
            rig.setdefault("axes", {})

            lm_a = rig["landmarks"].get(params.from_landmark)
            lm_b = rig["landmarks"].get(params.to_landmark)
            if not lm_a or "ai" not in lm_a:
                return json.dumps({"error": f"Landmark '{params.from_landmark}' not found or missing AI coords"})
            if not lm_b or "ai" not in lm_b:
                return json.dumps({"error": f"Landmark '{params.to_landmark}' not found or missing AI coords"})

            axis_def = compute_axis_from_landmarks(lm_a["ai"], lm_b["ai"])
            axis_def["from_landmark"] = params.from_landmark
            axis_def["to_landmark"] = params.to_landmark

            rig["axes"][params.axis_name] = axis_def
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "compute_axis",
                "axis_name": params.axis_name,
                "axis": axis_def,
            })

        elif params.action == "draw_on_axis":
            # ── Draw shape using axis-relative coordinates ──
            if not params.points_json:
                return json.dumps({"error": "draw_on_axis requires points_json"})

            try:
                points = json.loads(params.points_json)
            except json.JSONDecodeError as exc:
                return json.dumps({"error": f"Invalid points_json: {exc}"})

            if not points or not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in points):
                return json.dumps({"error": "points_json must be array of [along_pct, across_pct]"})

            rig = _load_rig(params.character_name)
            rig.setdefault("landmarks", {})
            rig.setdefault("axes", {})

            # Resolve axis: from stored axis name, or compute ad-hoc from landmarks
            axis_def = None
            if params.axis_name and params.axis_name in rig.get("axes", {}):
                axis_def = rig["axes"][params.axis_name]
            elif params.from_landmark and params.to_landmark:
                lm_a = rig["landmarks"].get(params.from_landmark)
                lm_b = rig["landmarks"].get(params.to_landmark)
                if not lm_a or "ai" not in lm_a:
                    return json.dumps({"error": f"Landmark '{params.from_landmark}' not found"})
                if not lm_b or "ai" not in lm_b:
                    return json.dumps({"error": f"Landmark '{params.to_landmark}' not found"})
                axis_def = compute_axis_from_landmarks(lm_a["ai"], lm_b["ai"])
            else:
                return json.dumps({"error": "draw_on_axis requires axis_name (stored) or from_landmark + to_landmark"})

            cross_w = params.cross_width if params.cross_width is not None else axis_def["length"] * 0.3
            ai_points = batch_axis_to_ai(
                axis_def, points, cross_w,
                near_cross_width=params.near_cross_width,
                far_cross_width=params.far_cross_width,
            )

            # Build JSX to create the path on the target layer
            escaped_layer = escape_jsx_string(params.layer_name)
            escaped_name = escape_jsx_string(params.path_name)
            points_js = json.dumps(ai_points)
            closed_js = "true" if params.closed else "false"

            jsx = f"""
var doc = app.activeDocument;
var layer;
try {{
    layer = doc.layers.getByName("{escaped_layer}");
}} catch(e) {{
    layer = doc.layers.add();
    layer.name = "{escaped_layer}";
}}
var pts = {points_js};
var path = layer.pathItems.add();
path.name = "{escaped_name}";
path.setEntirePath(pts);
path.closed = {closed_js};
path.stroked = true;
path.strokeWidth = {params.stroke_width};
path.filled = false;
var result = [];
for (var i = 0; i < path.pathPoints.length; i++) {{
    var a = path.pathPoints[i].anchor;
    result.push([Math.round(a[0] * 100) / 100, Math.round(a[1] * 100) / 100]);
}}
JSON.stringify({{
    name: path.name,
    point_count: path.pathPoints.length,
    closed: path.closed,
    placed_points: result
}});
"""
            jsx_result = await _async_run_jsx("illustrator", jsx)
            if not jsx_result["success"]:
                return json.dumps({"error": f"JSX failed: {jsx_result['stderr']}"})

            # Store placement for validation
            rig["_last_placement"] = {
                "path_name": params.path_name,
                "intended_points": ai_points,
                "axis_name": params.axis_name,
                "axis_relative": points,
            }
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "draw_on_axis",
                "path_name": params.path_name,
                "ai_points": ai_points,
                "jsx_result": jsx_result["stdout"],
            })

        elif params.action == "validate_placement":
            # ── Validate placed path against intended positions ──
            rig = _load_rig(params.character_name)
            placement = rig.get("_last_placement")

            # Determine which path to validate
            target_name = params.placed_name or (placement["path_name"] if placement else None)
            if not target_name:
                return json.dumps({"error": "No placed_name specified and no recent placement found"})

            escaped_name = escape_jsx_string(target_name)
            jsx = f"""
var doc = app.activeDocument;
var item = null;
for (var l = 0; l < doc.layers.length; l++) {{
    var lyr = doc.layers[l];
    for (var s = 0; s < lyr.pathItems.length; s++) {{
        if (lyr.pathItems[s].name === "{escaped_name}") {{
            item = lyr.pathItems[s];
            break;
        }}
    }}
    if (item) break;
}}
if (!item) {{
    JSON.stringify({{"error": "Path not found: {escaped_name}"}});
}} else {{
    var pts = [];
    for (var i = 0; i < item.pathPoints.length; i++) {{
        var a = item.pathPoints[i].anchor;
        pts.push([Math.round(a[0] * 100) / 100, Math.round(a[1] * 100) / 100]);
    }}
    JSON.stringify({{name: item.name, points: pts}});
}}
"""
            jsx_result = await _async_run_jsx("illustrator", jsx)
            if not jsx_result["success"]:
                return json.dumps({"error": f"JSX failed: {jsx_result['stderr']}"})

            try:
                placed_data = json.loads(jsx_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": f"Invalid JSX response: {jsx_result['stdout']}"})

            if "error" in placed_data:
                return json.dumps(placed_data)

            # Compare with intended positions
            intended = placement["intended_points"] if placement else None
            if not intended:
                return json.dumps({
                    "action": "validate_placement",
                    "path_name": target_name,
                    "placed_points": placed_data["points"],
                    "note": "No intended positions stored for comparison",
                })

            actual = placed_data["points"]
            tol = params.tolerance
            errors = []
            all_pass = True
            for i, (intended_pt, actual_pt) in enumerate(zip(intended, actual)):
                dx = actual_pt[0] - intended_pt[0]
                dy = actual_pt[1] - intended_pt[1]
                dist = math.sqrt(dx * dx + dy * dy)
                passed = dist <= tol
                if not passed:
                    all_pass = False
                errors.append({
                    "index": i,
                    "intended": intended_pt,
                    "actual": actual_pt,
                    "delta": [round(dx, 2), round(dy, 2)],
                    "distance": round(dist, 2),
                    "pass": passed,
                })

            return json.dumps({
                "action": "validate_placement",
                "path_name": target_name,
                "tolerance": tol,
                "all_pass": all_pass,
                "point_count": len(errors),
                "per_point": errors,
            })

        elif params.action == "infer_occluded":
            # ── Infer hidden landmarks via bilateral symmetry ──
            rig = _load_rig(params.character_name)
            rig.setdefault("landmarks", {})
            rig.setdefault("axes", {})

            # Determine visible set: explicit list or all non-inferred landmarks
            if params.visible_landmarks:
                try:
                    visible_names = json.loads(params.visible_landmarks)
                except json.JSONDecodeError:
                    visible_names = [n.strip() for n in params.visible_landmarks.split(",")]
                visible = {n: rig["landmarks"][n] for n in visible_names if n in rig["landmarks"]}
            else:
                visible = {n: d for n, d in rig["landmarks"].items() if not d.get("inferred")}

            view_angle = params.view_angle if params.view_angle is not None else rig.get("view_angle", 0)

            inferred = infer_occluded_landmarks(visible, view_angle, symmetric=params.symmetric)

            # Merge inferred landmarks into rig
            for name, data in inferred.items():
                rig["landmarks"][name] = data

            if params.view_angle is not None:
                rig["view_angle"] = params.view_angle

            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "infer_occluded",
                "view_angle": view_angle,
                "inferred_count": len(inferred),
                "inferred": inferred,
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {params.action}. "
                "Valid: detect_landmarks, add_landmark, compute_axis, draw_on_axis, validate_placement, infer_occluded"
            })
