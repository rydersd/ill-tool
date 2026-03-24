"""Two-bone inverse kinematics solver for character posing.

Given an end-effector joint (e.g. wrist_l, ankle_r) and a target
position, solves the standard two-bone IK problem using the law of
cosines to find the intermediate joint position (elbow/knee), then
updates joint positions and rotates bound paths accordingly.

Chain topology:
    shoulder → elbow → wrist   (arm)
    hip      → knee  → ankle   (leg)
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiIKSolverInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# Maps end-effector joints to their 3-joint chain (root, mid, tip)
_IK_CHAINS = {
    "wrist_l":  ("shoulder_l", "elbow_l", "wrist_l"),
    "wrist_r":  ("shoulder_r", "elbow_r", "wrist_r"),
    "ankle_l":  ("hip_l", "knee_l", "ankle_l"),
    "ankle_r":  ("hip_r", "knee_r", "ankle_r"),
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)


def _solve_two_bone(
    root_x: float, root_y: float,
    target_x: float, target_y: float,
    upper_len: float, lower_len: float,
    prefer_positive_bend: bool = True,
) -> tuple:
    """Solve two-bone IK and return the mid-joint position.

    Uses the law of cosines to compute the elbow/knee position given
    the root (shoulder/hip) and target (wrist/ankle) positions plus
    the two bone lengths.

    *prefer_positive_bend* controls which of the two possible solutions
    is returned -- True gives the solution where the mid-joint bends
    counterclockwise from the root-to-target line (natural elbow/knee).
    """
    d = _distance(root_x, root_y, target_x, target_y)
    max_reach = upper_len + lower_len - 0.01
    # Clamp to reachable range
    d = min(d, max_reach)

    # Angle at root joint using law of cosines
    cos_a = (upper_len ** 2 + d ** 2 - lower_len ** 2) / (2 * upper_len * d)
    cos_a = _clamp(cos_a, -1.0, 1.0)
    angle_a = math.acos(cos_a)

    # Angle from root to target
    angle_to_target = math.atan2(target_y - root_y, target_x - root_x)

    # Mid-joint position (two solutions: +/- angle_a)
    if prefer_positive_bend:
        mid_angle = angle_to_target - angle_a
    else:
        mid_angle = angle_to_target + angle_a

    mid_x = root_x + upper_len * math.cos(mid_angle)
    mid_y = root_y + upper_len * math.sin(mid_angle)

    return (round(mid_x, 3), round(mid_y, 3))


def _collect_bone_paths(bones: list, bindings: dict, parent_joint: str) -> list:
    """Return all path names bound to bones whose parent_joint matches."""
    names = set()
    for bone in bones:
        if bone.get("parent_joint") == parent_joint:
            bone_name = bone.get("name", "")
            parts = bindings.get(bone_name, [])
            if isinstance(parts, str):
                parts = [parts]
            names.update(parts)
    return list(names)


def register(mcp):
    """Register the adobe_ai_ik_solver tool."""

    @mcp.tool(
        name="adobe_ai_ik_solver",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_ik_solver(params: AiIKSolverInput) -> str:
        """Solve two-bone inverse kinematics for an end effector.

        Supported end effectors: wrist_l, wrist_r, ankle_l, ankle_r.
        Computes the intermediate joint position (elbow/knee) so the
        chain reaches the target position, then optionally applies the
        result by rotating bound paths.
        """
        if params.end_effector not in _IK_CHAINS:
            return json.dumps({
                "error": f"Unknown end effector: {params.end_effector}. "
                         f"Supported: {list(_IK_CHAINS.keys())}"
            })

        rig = _load_rig(params.character_name)
        joints = rig.get("joints", {})
        bones = rig.get("bones", [])
        bindings = rig.get("bindings", {})

        root_name, mid_name, tip_name = _IK_CHAINS[params.end_effector]

        # Validate all three joints exist
        for jn in (root_name, mid_name, tip_name):
            if jn not in joints:
                return json.dumps({
                    "error": f"Joint '{jn}' not found in rig. "
                             f"Available: {list(joints.keys())}"
                })

        root = joints[root_name]
        mid = joints[mid_name]
        tip = joints[tip_name]

        root_x, root_y = root["x"], root["y"]
        old_mid_x, old_mid_y = mid["x"], mid["y"]
        old_tip_x, old_tip_y = tip["x"], tip["y"]

        # Compute bone lengths from current positions
        upper_len = _distance(root_x, root_y, old_mid_x, old_mid_y)
        lower_len = _distance(old_mid_x, old_mid_y, old_tip_x, old_tip_y)

        if upper_len < 0.01 or lower_len < 0.01:
            return json.dumps({
                "error": "Bone lengths are effectively zero. "
                         "Check joint positions."
            })

        # Solve IK
        new_mid_x, new_mid_y = _solve_two_bone(
            root_x, root_y,
            params.target_x, params.target_y,
            upper_len, lower_len,
        )

        # Compute new tip position (along the direction from mid to target,
        # at distance lower_len)
        d_to_target = _distance(new_mid_x, new_mid_y,
                                params.target_x, params.target_y)
        if d_to_target < 0.001:
            # Target is at the mid joint -- just extend downward
            new_tip_x = new_mid_x
            new_tip_y = new_mid_y - lower_len
        else:
            dir_x = (params.target_x - new_mid_x) / d_to_target
            dir_y = (params.target_y - new_mid_y) / d_to_target
            new_tip_x = round(new_mid_x + dir_x * lower_len, 3)
            new_tip_y = round(new_mid_y + dir_y * lower_len, 3)

        result_data = {
            "end_effector": params.end_effector,
            "chain": [root_name, mid_name, tip_name],
            "bone_lengths": {
                "upper": round(upper_len, 3),
                "lower": round(lower_len, 3),
            },
            "old_positions": {
                root_name: {"x": root_x, "y": root_y},
                mid_name: {"x": old_mid_x, "y": old_mid_y},
                tip_name: {"x": old_tip_x, "y": old_tip_y},
            },
            "new_positions": {
                root_name: {"x": root_x, "y": root_y},
                mid_name: {"x": new_mid_x, "y": new_mid_y},
                tip_name: {"x": new_tip_x, "y": new_tip_y},
            },
            "target": {"x": params.target_x, "y": params.target_y},
        }

        if not params.apply:
            result_data["applied"] = False
            return json.dumps(result_data)

        # Apply: compute rotation angles for each bone segment and rotate
        # bound paths.  For the upper bone (root→mid), we rotate around
        # root.  For the lower bone (mid→tip), we rotate around mid.

        # Upper bone rotation angle
        old_upper_angle = math.atan2(old_mid_y - root_y, old_mid_x - root_x)
        new_upper_angle = math.atan2(new_mid_y - root_y, new_mid_x - root_x)
        delta_upper = new_upper_angle - old_upper_angle

        # Lower bone rotation angle
        old_lower_angle = math.atan2(old_tip_y - old_mid_y,
                                     old_tip_x - old_mid_x)
        new_lower_angle = math.atan2(new_tip_y - new_mid_y,
                                     new_tip_x - new_mid_x)
        delta_lower = new_lower_angle - old_lower_angle

        # Collect paths for each bone segment
        upper_paths = _collect_bone_paths(bones, bindings, root_name)
        lower_paths = _collect_bone_paths(bones, bindings, mid_name)

        # Build JSX for both rotations
        rotations = []
        if upper_paths and abs(delta_upper) > 0.0001:
            cos_u = math.cos(delta_upper)
            sin_u = math.sin(delta_upper)
            rotations.append({
                "paths": upper_paths,
                "pivot_x": root_x,
                "pivot_y": root_y,
                "cos": cos_u,
                "sin": sin_u,
            })
        if lower_paths and abs(delta_lower) > 0.0001:
            # The lower bone rotation is relative to the NEW mid position
            # and includes the upper rotation that already happened
            total_lower = delta_upper + delta_lower
            cos_l = math.cos(total_lower)
            sin_l = math.sin(total_lower)
            rotations.append({
                "paths": lower_paths,
                "pivot_x": root_x,  # rotate around root for full chain
                "pivot_y": root_y,
                "cos": cos_l,
                "sin": sin_l,
            })

        if rotations:
            rotations_js = json.dumps(rotations)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var rotations = {rotations_js};
    var applied = [];
    var errors = [];

    for (var r = 0; r < rotations.length; r++) {{
        var rot = rotations[r];
        var pivotX = rot.pivot_x;
        var pivotY = rot.pivot_y;
        var cosA = rot.cos;
        var sinA = rot.sin;

        for (var n = 0; n < rot.paths.length; n++) {{
            var pName = rot.paths[n];
            var item = null;
            for (var l = 0; l < doc.layers.length; l++) {{
                try {{
                    item = doc.layers[l].pathItems.getByName(pName);
                    if (item) break;
                }} catch(e) {{}}
            }}
            if (!item) {{
                errors.push("PathItem not found: " + pName);
                continue;
            }}

            var pts = item.pathPoints;
            for (var i = 0; i < pts.length; i++) {{
                var p = pts[i];
                var a = p.anchor;
                var ld = p.leftDirection;
                var rd = p.rightDirection;

                var adx = a[0] - pivotX;
                var ady = a[1] - pivotY;
                p.anchor = [pivotX + adx * cosA - ady * sinA,
                            pivotY + adx * sinA + ady * cosA];

                var ldx = ld[0] - pivotX;
                var ldy = ld[1] - pivotY;
                p.leftDirection = [pivotX + ldx * cosA - ldy * sinA,
                                   pivotY + ldx * sinA + ldy * cosA];

                var rdx = rd[0] - pivotX;
                var rdy = rd[1] - pivotY;
                p.rightDirection = [pivotX + rdx * cosA - rdy * sinA,
                                    pivotY + rdx * sinA + rdy * cosA];
            }}

            applied.push(pName);
        }}
    }}

    return JSON.stringify({{
        applied_paths: applied,
        errors: errors
    }});
}})();"""

            jsx_result = await _async_run_jsx("illustrator", jsx)
            if not jsx_result["success"]:
                return json.dumps({"error": jsx_result["stderr"]})

            try:
                jsx_data = json.loads(jsx_result["stdout"])
            except json.JSONDecodeError:
                jsx_data = {"raw": jsx_result["stdout"]}

            result_data["jsx_result"] = jsx_data

        # Update rig joint positions
        joints[mid_name] = {"x": new_mid_x, "y": new_mid_y}
        joints[tip_name] = {"x": new_tip_x, "y": new_tip_y}
        rig["joints"] = joints
        _save_rig(params.character_name, rig)

        result_data["applied"] = True
        return json.dumps(result_data)
