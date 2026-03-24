"""Estimate character pose from a reference image.

Uses OpenCV contour analysis to identify a character silhouette and estimate
joint positions from contour geometry.  Saves the extracted pose to the rig
file and optionally applies it via joint rotations.

Alternatively, returns a manual annotation guide listing each joint needed
so the user can mark them with skeleton_annotate.
"""

import json
import math
import os

import cv2
import numpy as np

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPoseFromImageInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _contour_extremes(contour: np.ndarray) -> dict:
    """Find extreme points of a contour (top, bottom, left, right)."""
    pts = contour.reshape(-1, 2)
    top_idx = int(np.argmin(pts[:, 1]))  # smallest Y = top in image coords
    bottom_idx = int(np.argmax(pts[:, 1]))
    left_idx = int(np.argmin(pts[:, 0]))
    right_idx = int(np.argmax(pts[:, 0]))
    return {
        "top": pts[top_idx].tolist(),
        "bottom": pts[bottom_idx].tolist(),
        "left": pts[left_idx].tolist(),
        "right": pts[right_idx].tolist(),
    }


def _widest_at_fraction(contour: np.ndarray, y_frac: float, height_range: float = 0.05) -> tuple:
    """Find the widest horizontal span at a vertical fraction of the bounding box.

    y_frac: 0.0 = top, 1.0 = bottom of the bounding box.
    height_range: fraction of bbox height to sample within.
    Returns (left_x, right_x, y_center) in pixel coordinates.
    """
    pts = contour.reshape(-1, 2)
    y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())
    bbox_h = y_max - y_min
    if bbox_h == 0:
        cx = float(pts[:, 0].mean())
        cy = float(pts[:, 1].mean())
        return (cx, cx, cy)

    target_y = y_min + bbox_h * y_frac
    half_band = bbox_h * height_range

    mask = (pts[:, 1] >= target_y - half_band) & (pts[:, 1] <= target_y + half_band)
    band_pts = pts[mask]
    if len(band_pts) == 0:
        # Widen band until we get points
        for mult in [2, 4, 8]:
            mask = (pts[:, 1] >= target_y - half_band * mult) & (pts[:, 1] <= target_y + half_band * mult)
            band_pts = pts[mask]
            if len(band_pts) > 0:
                break
    if len(band_pts) == 0:
        cx = float(pts[:, 0].mean())
        return (cx, cx, target_y)

    left_x = float(band_pts[:, 0].min())
    right_x = float(band_pts[:, 0].max())
    y_center = float(band_pts[:, 1].mean())
    return (left_x, right_x, y_center)


def _bottommost_local_minima(contour: np.ndarray, n: int = 2) -> list:
    """Find the N bottommost local minima along the contour — typically the feet.

    We walk the contour boundary and find points where x reverses direction
    at the bottom portion.  Falls back to the two bottommost points if no
    clear minima are found.
    """
    pts = contour.reshape(-1, 2)
    y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())
    bbox_h = y_max - y_min
    if bbox_h == 0:
        return [pts[0].tolist()] * n

    # Only look at the bottom 30% of the contour
    threshold_y = y_min + bbox_h * 0.7
    bottom_mask = pts[:, 1] >= threshold_y
    bottom_pts = pts[bottom_mask]
    if len(bottom_pts) < n:
        # Fall back: take the N points with highest Y
        sorted_by_y = pts[np.argsort(-pts[:, 1])]
        return [sorted_by_y[i].tolist() for i in range(min(n, len(sorted_by_y)))]

    # Sort bottom points by X to find clusters (left foot, right foot)
    sorted_by_x = bottom_pts[np.argsort(bottom_pts[:, 0])]
    if len(sorted_by_x) < n:
        return [sorted_by_x[i].tolist() for i in range(len(sorted_by_x))]

    # Split into N clusters via equal X partitioning
    cluster_size = len(sorted_by_x) // n
    results = []
    for i in range(n):
        start = i * cluster_size
        end = start + cluster_size if i < n - 1 else len(sorted_by_x)
        cluster = sorted_by_x[start:end]
        # Take the point with the highest Y in each cluster (most bottom)
        best = cluster[np.argmax(cluster[:, 1])]
        results.append(best.tolist())
    return results


def _midpoint(a: list, b: list) -> list:
    """Return the midpoint between two [x, y] points."""
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]


def _angle_between(a: list, b: list, c: list) -> float:
    """Compute the angle in degrees at point b, formed by segments a-b and b-c."""
    ba = [a[0] - b[0], a[1] - b[1]]
    bc = [c[0] - b[0], c[1] - b[1]]
    dot = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.sqrt(ba[0] ** 2 + ba[1] ** 2)
    mag_bc = math.sqrt(bc[0] ** 2 + bc[1] ** 2)
    if mag_ba == 0 or mag_bc == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ba * mag_bc)))
    return math.degrees(math.acos(cos_angle))


def _estimate_joints_from_contour(contour: np.ndarray) -> dict:
    """Estimate joint positions from contour geometry.

    Returns a dict mapping joint names to {x, y} pixel coordinates.
    """
    extremes = _contour_extremes(contour)
    pts = contour.reshape(-1, 2)
    y_min = float(pts[:, 1].min())
    y_max = float(pts[:, 1].max())
    x_center = float(pts[:, 0].mean())
    bbox_h = y_max - y_min

    # Head: topmost point
    head = extremes["top"]

    # Feet: two bottommost local minima
    feet = _bottommost_local_minima(contour, n=2)
    foot_l = feet[0]
    foot_r = feet[1] if len(feet) > 1 else feet[0]
    # Ensure left foot is actually on the left
    if foot_l[0] > foot_r[0]:
        foot_l, foot_r = foot_r, foot_l

    # Shoulders: widest points in upper third
    sh_left, sh_right, sh_y = _widest_at_fraction(contour, 0.25, 0.06)
    shoulder_l = [sh_left, sh_y]
    shoulder_r = [sh_right, sh_y]

    # Hips: widest points in lower third
    hip_left, hip_right, hip_y = _widest_at_fraction(contour, 0.55, 0.06)
    hip_l = [hip_left, hip_y]
    hip_r = [hip_right, hip_y]

    # Spine: vertical center line
    neck_y = y_min + bbox_h * 0.18
    neck = [x_center, neck_y]
    spine_top = [(shoulder_l[0] + shoulder_r[0]) / 2, sh_y]
    spine_mid = [x_center, y_min + bbox_h * 0.42]
    spine_base = [(hip_l[0] + hip_r[0]) / 2, hip_y]

    # Hands: leftmost and rightmost extremities at mid-height
    hand_left, hand_right, hand_y = _widest_at_fraction(contour, 0.42, 0.10)
    wrist_l = [hand_left, hand_y]
    wrist_r = [hand_right, hand_y]

    # Elbows: midpoints between shoulder and wrist
    elbow_l = _midpoint(shoulder_l, wrist_l)
    elbow_r = _midpoint(shoulder_r, wrist_r)

    # Knees: midpoints between hip and ankle/foot
    knee_l = _midpoint(hip_l, foot_l)
    knee_r = _midpoint(hip_r, foot_r)

    # Ankles: slightly above feet
    ankle_l = [foot_l[0], foot_l[1] - bbox_h * 0.04]
    ankle_r = [foot_r[0], foot_r[1] - bbox_h * 0.04]

    joints = {
        "head": {"x": round(head[0], 1), "y": round(head[1], 1)},
        "neck": {"x": round(neck[0], 1), "y": round(neck[1], 1)},
        "spine_top": {"x": round(spine_top[0], 1), "y": round(spine_top[1], 1)},
        "spine_mid": {"x": round(spine_mid[0], 1), "y": round(spine_mid[1], 1)},
        "spine_base": {"x": round(spine_base[0], 1), "y": round(spine_base[1], 1)},
        "shoulder_l": {"x": round(shoulder_l[0], 1), "y": round(shoulder_l[1], 1)},
        "shoulder_r": {"x": round(shoulder_r[0], 1), "y": round(shoulder_r[1], 1)},
        "elbow_l": {"x": round(elbow_l[0], 1), "y": round(elbow_l[1], 1)},
        "elbow_r": {"x": round(elbow_r[0], 1), "y": round(elbow_r[1], 1)},
        "wrist_l": {"x": round(wrist_l[0], 1), "y": round(wrist_l[1], 1)},
        "wrist_r": {"x": round(wrist_r[0], 1), "y": round(wrist_r[1], 1)},
        "hip_l": {"x": round(hip_l[0], 1), "y": round(hip_l[1], 1)},
        "hip_r": {"x": round(hip_r[0], 1), "y": round(hip_r[1], 1)},
        "knee_l": {"x": round(knee_l[0], 1), "y": round(knee_l[1], 1)},
        "knee_r": {"x": round(knee_r[0], 1), "y": round(knee_r[1], 1)},
        "ankle_l": {"x": round(ankle_l[0], 1), "y": round(ankle_l[1], 1)},
        "ankle_r": {"x": round(ankle_r[0], 1), "y": round(ankle_r[1], 1)},
    }
    return joints


def _compute_joint_angles(joints: dict) -> dict:
    """Compute angles at each joint from the estimated positions.

    Returns a dict mapping joint name to angle in degrees.
    """
    def _jpt(name: str) -> list:
        j = joints.get(name, {"x": 0, "y": 0})
        return [j["x"], j["y"]]

    angles = {}

    # Left arm chain: shoulder -> elbow -> wrist
    angles["elbow_l"] = round(_angle_between(_jpt("shoulder_l"), _jpt("elbow_l"), _jpt("wrist_l")), 1)
    angles["elbow_r"] = round(_angle_between(_jpt("shoulder_r"), _jpt("elbow_r"), _jpt("wrist_r")), 1)

    # Shoulder angles: neck -> shoulder -> elbow
    angles["shoulder_l"] = round(_angle_between(_jpt("neck"), _jpt("shoulder_l"), _jpt("elbow_l")), 1)
    angles["shoulder_r"] = round(_angle_between(_jpt("neck"), _jpt("shoulder_r"), _jpt("elbow_r")), 1)

    # Leg chain: hip -> knee -> ankle
    angles["knee_l"] = round(_angle_between(_jpt("hip_l"), _jpt("knee_l"), _jpt("ankle_l")), 1)
    angles["knee_r"] = round(_angle_between(_jpt("hip_r"), _jpt("knee_r"), _jpt("ankle_r")), 1)

    # Hip angles: spine_base -> hip -> knee
    angles["hip_l"] = round(_angle_between(_jpt("spine_base"), _jpt("hip_l"), _jpt("knee_l")), 1)
    angles["hip_r"] = round(_angle_between(_jpt("spine_base"), _jpt("hip_r"), _jpt("knee_r")), 1)

    return angles


def register(mcp):
    """Register the adobe_ai_pose_from_image tool."""

    @mcp.tool(
        name="adobe_ai_pose_from_image",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_pose_from_image(params: AiPoseFromImageInput) -> str:
        """Estimate character pose from a reference image using contour analysis.

        Contour method: loads the image, thresholds to find the character
        silhouette, then estimates joint positions from the contour geometry.
        Saves the result as a named pose in the rig file.

        Manual method: returns a guide listing the joints needed, with
        instructions to use skeleton_annotate to mark them.
        """
        # ── Manual method: return annotation guide ──────────────────────
        if params.method == "manual":
            joint_list = [
                "head", "neck",
                "shoulder_l", "shoulder_r",
                "elbow_l", "elbow_r",
                "wrist_l", "wrist_r",
                "spine_top", "spine_mid", "spine_base",
                "hip_l", "hip_r",
                "knee_l", "knee_r",
                "ankle_l", "ankle_r",
            ]
            guide = {
                "method": "manual",
                "message": (
                    "Mark each joint position on the character using the "
                    "skeleton_annotate tool with action='add'. The joints "
                    "needed are listed below. After marking all joints, "
                    "use pose_snapshot with action='capture' to save the pose."
                ),
                "joints_needed": joint_list,
                "instructions": {
                    "head": "Top of the head / crown",
                    "neck": "Base of the skull / top of spine",
                    "shoulder_l": "Left shoulder joint (character's left)",
                    "shoulder_r": "Right shoulder joint",
                    "elbow_l": "Left elbow bend point",
                    "elbow_r": "Right elbow bend point",
                    "wrist_l": "Left wrist / hand base",
                    "wrist_r": "Right wrist / hand base",
                    "spine_top": "Top of spine between shoulders",
                    "spine_mid": "Mid-spine / waist level",
                    "spine_base": "Base of spine / pelvis center",
                    "hip_l": "Left hip joint",
                    "hip_r": "Right hip joint",
                    "knee_l": "Left knee bend point",
                    "knee_r": "Right knee bend point",
                    "ankle_l": "Left ankle",
                    "ankle_r": "Right ankle",
                },
                "character_name": params.character_name,
                "reference_image": params.image_path,
            }
            return json.dumps(guide, indent=2)

        # ── Contour method: automated estimation ────────────────────────
        if not os.path.isfile(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        img = cv2.imread(params.image_path)
        if img is None:
            return json.dumps({"error": f"Could not decode image: {params.image_path}"})

        # Step 1: Threshold and find contours
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return json.dumps({"error": "No contours found in image — cannot extract pose."})

        # Step 2: Find the largest contour (character silhouette)
        largest = max(contours, key=cv2.contourArea)
        contour_area = cv2.contourArea(largest)
        img_h, img_w = img.shape[:2]
        area_pct = (contour_area / (img_w * img_h)) * 100

        if area_pct < 1.0:
            return json.dumps({
                "error": (
                    f"Largest contour is only {area_pct:.1f}% of image area — "
                    "too small to be a character. Check the image or try the manual method."
                ),
            })

        # Step 3: Estimate joint positions
        joints = _estimate_joints_from_contour(largest)

        # Step 4: Compute joint angles
        angles = _compute_joint_angles(joints)

        # Step 5: Save as a pose in the rig file
        rig = _load_rig(params.character_name)

        # Store the joints in the rig so skeleton_annotate can see them
        for jname, jdata in joints.items():
            rig["joints"][jname] = jdata

        # Build the pose data: angles + positions
        pose_name = "from_image"
        pose_data = {
            "joints": joints,
            "angles": angles,
            "source_image": params.image_path,
            "image_size": [img_w, img_h],
            "contour_area_pct": round(area_pct, 1),
        }

        if "poses" not in rig:
            rig["poses"] = {}
        rig["poses"][pose_name] = pose_data

        _save_rig(params.character_name, rig)

        # Step 6: Optionally apply the pose via JSX
        applied = False
        if params.apply:
            # Apply by placing visual joint markers in Illustrator
            # so the user can see and adjust the pose
            marker_points = []
            for jname, jdata in joints.items():
                marker_points.append({
                    "name": jname,
                    "x": jdata["x"],
                    "y": jdata["y"],
                })

            markers_json = json.dumps(marker_points)
            jsx_apply = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Pose") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "Pose";
    }}
    doc.activeLayer = layer;

    var markers = {markers_json};
    var placed = 0;
    for (var m = 0; m < markers.length; m++) {{
        var mk = markers[m];
        // Create a small circle at each joint position
        var r = 4;
        var ell = layer.pathItems.ellipse(
            mk.y + r, mk.x - r, r * 2, r * 2
        );
        ell.name = "joint_" + mk.name;
        ell.filled = true;
        ell.stroked = true;
        ell.strokeWidth = 1;
        var fillColor = new RGBColor();
        fillColor.red = 0; fillColor.green = 200; fillColor.blue = 100;
        ell.fillColor = fillColor;
        var strokeColor = new RGBColor();
        strokeColor.red = 0; strokeColor.green = 0; strokeColor.blue = 0;
        ell.strokeColor = strokeColor;
        placed++;
    }}

    // Draw bone lines between connected joints
    var bones = [
        ["head", "neck"], ["neck", "spine_top"],
        ["spine_top", "spine_mid"], ["spine_mid", "spine_base"],
        ["spine_top", "shoulder_l"], ["spine_top", "shoulder_r"],
        ["shoulder_l", "elbow_l"], ["elbow_l", "wrist_l"],
        ["shoulder_r", "elbow_r"], ["elbow_r", "wrist_r"],
        ["spine_base", "hip_l"], ["spine_base", "hip_r"],
        ["hip_l", "knee_l"], ["knee_l", "ankle_l"],
        ["hip_r", "knee_r"], ["knee_r", "ankle_r"]
    ];
    var markerMap = {{}};
    for (var i = 0; i < markers.length; i++) {{
        markerMap[markers[i].name] = markers[i];
    }}
    for (var b = 0; b < bones.length; b++) {{
        var a = markerMap[bones[b][0]];
        var c = markerMap[bones[b][1]];
        if (a && c) {{
            var line = layer.pathItems.add();
            line.setEntirePath([[a.x, a.y], [c.x, c.y]]);
            line.closed = false;
            line.filled = false;
            line.stroked = true;
            line.strokeWidth = 1.5;
            var boneColor = new RGBColor();
            boneColor.red = 0; boneColor.green = 200; boneColor.blue = 100;
            line.strokeColor = boneColor;
            line.name = "bone_" + bones[b][0] + "_" + bones[b][1];
        }}
    }}

    return JSON.stringify({{placed: placed}});
}})();
"""
            apply_result = await _async_run_jsx("illustrator", jsx_apply)
            applied = apply_result.get("success", False)

        result = {
            "method": "contour",
            "character_name": params.character_name,
            "pose_name": pose_name,
            "joints": joints,
            "angles": angles,
            "contour_area_pct": round(area_pct, 1),
            "image_size": [img_w, img_h],
            "saved_to_rig": True,
            "applied": applied,
        }
        return json.dumps(result, indent=2)
