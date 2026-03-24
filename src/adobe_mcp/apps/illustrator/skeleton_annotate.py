"""Mark joint positions on a character for skeleton-based posing.

Joints are stored in the rig file at /tmp/ai_rigs/{character_name}.json.
The add action optionally draws a small circle marker on a "Skeleton"
layer in Illustrator so the artist can see joint placement.

auto_detect uses OpenCV contour analysis on a reference image to estimate
a starting set of joint positions from the character's silhouette.
"""

import json
import os
import math

import cv2
import numpy as np

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSkeletonAnnotateInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def _auto_detect_joints(image_path: str) -> dict:
    """Estimate biped joint positions from the largest contour in a reference image.

    Strategy:
    - Find the largest external contour (the character silhouette).
    - Identify anchor landmarks: topmost (head), bottommost left/right (ankles),
      leftmost/rightmost at mid-height (wrists), centroid (spine_mid).
    - Interpolate intermediate joints (shoulders, elbows, hips, knees, spine)
      from these anchors.

    Returns a dict of joint_name -> {"x": float, "y": float} in pixel coords,
    plus image_size for downstream coordinate transforms.
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"error": f"Could not read image at {image_path}"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"error": "No contours found in image"}

    largest = max(contours, key=cv2.contourArea)
    pts = largest.reshape(-1, 2)
    img_h, img_w = img.shape[:2]

    # Centroid via moments
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return {"error": "Degenerate contour (zero area)"}
    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]

    # Topmost point -> head
    top_idx = np.argmin(pts[:, 1])
    head = pts[top_idx].tolist()

    # Bottommost points split left/right of centroid for ankles
    bottom_pts = pts[pts[:, 1] > cy + (np.max(pts[:, 1]) - cy) * 0.7]
    if len(bottom_pts) < 2:
        bottom_pts = pts[np.argsort(-pts[:, 1])[:4]]
    left_bottom = bottom_pts[bottom_pts[:, 0] < cx]
    right_bottom = bottom_pts[bottom_pts[:, 0] >= cx]

    if len(left_bottom) > 0:
        ankle_l_idx = np.argmax(left_bottom[:, 1])
        ankle_l = left_bottom[ankle_l_idx].tolist()
    else:
        ankle_l = [cx - img_w * 0.1, np.max(pts[:, 1])]

    if len(right_bottom) > 0:
        ankle_r_idx = np.argmax(right_bottom[:, 1])
        ankle_r = right_bottom[ankle_r_idx].tolist()
    else:
        ankle_r = [cx + img_w * 0.1, np.max(pts[:, 1])]

    # Leftmost/rightmost at roughly mid-height band for wrists
    mid_band_y_min = cy - img_h * 0.15
    mid_band_y_max = cy + img_h * 0.15
    mid_band = pts[(pts[:, 1] > mid_band_y_min) & (pts[:, 1] < mid_band_y_max)]
    if len(mid_band) >= 2:
        wrist_l = mid_band[np.argmin(mid_band[:, 0])].tolist()
        wrist_r = mid_band[np.argmax(mid_band[:, 0])].tolist()
    else:
        wrist_l = [np.min(pts[:, 0]), cy]
        wrist_r = [np.max(pts[:, 0]), cy]

    # Anchor points established: head, centroid (spine_mid), ankle_l, ankle_r, wrist_l, wrist_r
    # Now interpolate intermediate joints

    # Neck: between head and centroid, closer to head (20% from head)
    neck = [head[0] * 0.8 + cx * 0.2, head[1] * 0.8 + cy * 0.2]

    # Spine top: between neck and centroid (40% from head toward centroid)
    spine_top = [head[0] * 0.6 + cx * 0.4, head[1] * 0.6 + cy * 0.4]

    # Spine mid: centroid
    spine_mid = [cx, cy]

    # Spine base: between centroid and average ankle Y (60% from centroid toward ankles)
    avg_ankle_y = (ankle_l[1] + ankle_r[1]) / 2
    spine_base = [cx, cy * 0.4 + avg_ankle_y * 0.6]

    # Shoulders: at spine_top Y height, offset left/right
    shoulder_offset_x = abs(wrist_r[0] - wrist_l[0]) * 0.25
    shoulder_l = [cx - shoulder_offset_x, spine_top[1]]
    shoulder_r = [cx + shoulder_offset_x, spine_top[1]]

    # Elbows: midpoint between shoulder and wrist
    elbow_l = [(shoulder_l[0] + wrist_l[0]) / 2, (shoulder_l[1] + wrist_l[1]) / 2]
    elbow_r = [(shoulder_r[0] + wrist_r[0]) / 2, (shoulder_r[1] + wrist_r[1]) / 2]

    # Hips: at spine_base Y, offset left/right narrower than shoulders
    hip_offset_x = shoulder_offset_x * 0.7
    hip_l = [cx - hip_offset_x, spine_base[1]]
    hip_r = [cx + hip_offset_x, spine_base[1]]

    # Knees: midpoint between hip and ankle
    knee_l = [(hip_l[0] + ankle_l[0]) / 2, (hip_l[1] + ankle_l[1]) / 2]
    knee_r = [(hip_r[0] + ankle_r[0]) / 2, (hip_r[1] + ankle_r[1]) / 2]

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

    return {
        "joints": joints,
        "image_size": [img_w, img_h],
        "coordinate_space": "pixels",
    }


def register(mcp):
    """Register the adobe_ai_skeleton_annotate tool."""

    @mcp.tool(
        name="adobe_ai_skeleton_annotate",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_skeleton_annotate(params: AiSkeletonAnnotateInput) -> str:
        """Mark joint positions on a character for skeleton-based posing.

        Actions:
        - add: Store a joint position and optionally draw a marker in AI.
        - list: Return all joints with positions.
        - remove: Remove a single joint.
        - clear: Remove all joints.
        - auto_detect: Estimate joints from reference image contour analysis.
        """
        rig = _load_rig(params.character_name)
        action = params.action.lower()

        # ── ADD ──────────────────────────────────────────────────
        if action == "add":
            if not params.joint_name:
                return json.dumps({"error": "joint_name is required for add action"})
            if params.x is None or params.y is None:
                return json.dumps({"error": "x and y are required for add action"})

            rig["joints"][params.joint_name] = {"x": params.x, "y": params.y}
            _save_rig(params.character_name, rig)

            # Draw a small circle marker on the Skeleton layer in Illustrator
            marker_radius = 4
            escaped_name = escape_jsx_string(params.joint_name)
            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Skeleton") {{
            layer = doc.layers[i];
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "Skeleton";
    }}
    doc.activeLayer = layer;

    // Draw a small circle at the joint position
    var marker = layer.pathItems.ellipse(
        {params.y + marker_radius}, {params.x - marker_radius},
        {marker_radius * 2}, {marker_radius * 2}
    );
    var col = new RGBColor();
    col.red = 255; col.green = 50; col.blue = 50;
    marker.fillColor = col;
    marker.stroked = false;
    marker.name = "joint_{escaped_name}";

    return JSON.stringify({{
        joint: "{escaped_name}",
        x: {params.x},
        y: {params.y},
        marker_placed: true
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)
            if result["success"]:
                return json.dumps({
                    "action": "add",
                    "joint": params.joint_name,
                    "position": {"x": params.x, "y": params.y},
                    "marker_placed": True,
                    "character": params.character_name,
                })
            else:
                # Joint saved to rig file even if AI marker failed
                return json.dumps({
                    "action": "add",
                    "joint": params.joint_name,
                    "position": {"x": params.x, "y": params.y},
                    "marker_placed": False,
                    "marker_error": result["stderr"],
                    "character": params.character_name,
                })

        # ── LIST ─────────────────────────────────────────────────
        elif action == "list":
            return json.dumps({
                "action": "list",
                "character": params.character_name,
                "joints": rig["joints"],
                "count": len(rig["joints"]),
            }, indent=2)

        # ── REMOVE ───────────────────────────────────────────────
        elif action == "remove":
            if not params.joint_name:
                return json.dumps({"error": "joint_name is required for remove action"})
            removed = rig["joints"].pop(params.joint_name, None)
            _save_rig(params.character_name, rig)

            # Try to remove the marker from AI too
            if removed:
                escaped_name = escape_jsx_string(params.joint_name)
                jsx = f"""
(function() {{
    var doc = app.activeDocument;
    try {{
        var marker = doc.pageItems.getByName("joint_{escaped_name}");
        marker.remove();
        return "removed";
    }} catch(e) {{
        return "no_marker";
    }}
}})();
"""
                await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "remove",
                "joint": params.joint_name,
                "was_present": removed is not None,
                "character": params.character_name,
            })

        # ── CLEAR ────────────────────────────────────────────────
        elif action == "clear":
            count = len(rig["joints"])
            rig["joints"] = {}
            _save_rig(params.character_name, rig)

            # Remove all joint markers from Skeleton layer
            jsx = """
(function() {
    var doc = app.activeDocument;
    var removed = 0;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Skeleton") {
            var items = doc.layers[i].pageItems;
            for (var j = items.length - 1; j >= 0; j--) {
                if (items[j].name.indexOf("joint_") === 0) {
                    items[j].remove();
                    removed++;
                }
            }
            break;
        }
    }
    return JSON.stringify({removed: removed});
})();
"""
            await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "clear",
                "joints_removed": count,
                "character": params.character_name,
            })

        # ── AUTO_DETECT ──────────────────────────────────────────
        elif action == "auto_detect":
            if not params.image_path:
                return json.dumps({"error": "image_path is required for auto_detect action"})
            if not os.path.isfile(params.image_path):
                return json.dumps({"error": f"Image not found: {params.image_path}"})

            detection = _auto_detect_joints(params.image_path)
            if "error" in detection:
                return json.dumps(detection)

            pixel_joints = detection["joints"]
            img_w, img_h = detection["image_size"]

            # Get artboard dimensions from AI to transform pixel coords
            jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
            ab_result = await _async_run_jsx("illustrator", jsx_info)
            if not ab_result["success"]:
                # Save pixel-space joints anyway
                rig["joints"] = pixel_joints
                _save_rig(params.character_name, rig)
                return json.dumps({
                    "action": "auto_detect",
                    "joints": pixel_joints,
                    "coordinate_space": "pixels",
                    "transform_error": ab_result["stderr"],
                    "character": params.character_name,
                }, indent=2)

            try:
                ab = json.loads(ab_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                rig["joints"] = pixel_joints
                _save_rig(params.character_name, rig)
                return json.dumps({
                    "action": "auto_detect",
                    "joints": pixel_joints,
                    "coordinate_space": "pixels",
                    "transform_error": f"Bad artboard response: {ab_result['stdout']}",
                    "character": params.character_name,
                }, indent=2)

            # Transform pixel coords to AI artboard coords
            ab_w = ab["right"] - ab["left"]
            ab_h = ab["top"] - ab["bottom"]  # top > bottom in AI
            scale_x = ab_w / img_w
            scale_y = ab_h / img_h
            scale = min(scale_x, scale_y)
            offset_x = ab["left"] + (ab_w - img_w * scale) / 2
            offset_y = ab["top"] - (ab_h - img_h * scale) / 2

            ai_joints = {}
            for name, pos in pixel_joints.items():
                ai_x = round(pos["x"] * scale + offset_x, 1)
                ai_y = round(offset_y - pos["y"] * scale, 1)
                ai_joints[name] = {"x": ai_x, "y": ai_y}

            rig["joints"] = ai_joints
            _save_rig(params.character_name, rig)

            # Draw all detected joints as markers on Skeleton layer
            markers_jsx_parts = []
            for jname, jpos in ai_joints.items():
                escaped = escape_jsx_string(jname)
                markers_jsx_parts.append(f"""
    var m_{jname.replace("-", "_")} = layer.pathItems.ellipse(
        {jpos["y"] + 4}, {jpos["x"] - 4}, 8, 8
    );
    var c = new RGBColor(); c.red = 255; c.green = 50; c.blue = 50;
    m_{jname.replace("-", "_")}.fillColor = c;
    m_{jname.replace("-", "_")}.stroked = false;
    m_{jname.replace("-", "_")}.name = "joint_{escaped}";
""")
            markers_jsx = "\n".join(markers_jsx_parts)

            jsx_draw = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Skeleton") {{
            layer = doc.layers[i];
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "Skeleton";
    }}
    doc.activeLayer = layer;
{markers_jsx}
    return JSON.stringify({{markers_placed: {len(ai_joints)}}});
}})();
"""
            draw_result = await _async_run_jsx("illustrator", jsx_draw)

            return json.dumps({
                "action": "auto_detect",
                "joints": ai_joints,
                "count": len(ai_joints),
                "coordinate_space": "illustrator_points",
                "markers_placed": draw_result["success"],
                "character": params.character_name,
            }, indent=2)

        else:
            return json.dumps({"error": f"Unknown action: {action}. Use add, list, remove, clear, or auto_detect."})
