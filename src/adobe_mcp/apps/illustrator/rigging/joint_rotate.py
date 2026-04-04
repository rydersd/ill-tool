"""Rotate a body part (and optionally its children) around a joint pivot point.

This is the core posing operation. Given a joint name and an angle, it:
1. Loads the rig to find the joint's pivot position
2. Identifies bones that use this joint as their parent
3. Collects all pathItems bound to those bones
4. Rotates every anchor point and bezier handle around the pivot via JSX
5. If cascade=True, recursively rotates child bones and updates their
   joint positions in the rig file
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiJointRotateInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _find_bones_from_joint(bones: list, joint_name: str) -> list:
    """Return all bones whose parent_joint matches *joint_name*."""
    return [b for b in bones if b.get("parent_joint") == joint_name]


def _collect_cascade_joints(bones: list, start_joint: str) -> list:
    """Walk the skeleton tree and return every joint reachable from *start_joint*.

    Each bone has parent_joint and child_joint. Starting from *start_joint*,
    we find bones whose parent_joint == start_joint, then recurse into their
    child_joints.  Returns a list of (joint_name, child_bones) tuples in
    breadth-first order.
    """
    visited = set()
    queue = [start_joint]
    result = []
    while queue:
        jname = queue.pop(0)
        if jname in visited:
            continue
        visited.add(jname)
        child_bones = _find_bones_from_joint(bones, jname)
        result.append((jname, child_bones))
        for bone in child_bones:
            cj = bone.get("child_joint")
            if cj and cj not in visited:
                queue.append(cj)
    return result


def _rotate_point(px: float, py: float, cx: float, cy: float,
                  cos_a: float, sin_a: float) -> tuple:
    """Rotate point (px, py) around center (cx, cy) by precomputed cos/sin."""
    dx = px - cx
    dy = py - cy
    return (cx + dx * cos_a - dy * sin_a,
            cy + dx * sin_a + dy * cos_a)


def register(mcp):
    """Register the adobe_ai_joint_rotate tool."""

    @mcp.tool(
        name="adobe_ai_joint_rotate",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_joint_rotate(params: AiJointRotateInput) -> str:
        """Rotate a body part around its joint pivot point.

        Finds the joint position from the rig, collects all pathItems bound
        to the bone(s) attached to this joint, and rotates their anchor
        points and bezier handles by the specified angle.  When cascade is
        True, child bones are also rotated and their joint positions updated.
        """
        rig = _load_rig(params.character_name)
        joints = rig.get("joints", {})
        bones = rig.get("bones", [])
        bindings = rig.get("bindings", {})

        # Validate joint exists
        if params.joint_name not in joints:
            return json.dumps({
                "error": f"Joint '{params.joint_name}' not found in rig. "
                         f"Available: {list(joints.keys())}"
            })

        pivot = joints[params.joint_name]
        pivot_x = pivot["x"]
        pivot_y = pivot["y"]

        angle_rad = math.radians(params.angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        # Determine which joints (and therefore which bound parts) to rotate
        if params.cascade:
            cascade_entries = _collect_cascade_joints(bones, params.joint_name)
        else:
            child_bones = _find_bones_from_joint(bones, params.joint_name)
            cascade_entries = [(params.joint_name, child_bones)]

        # Collect all path names to rotate via bindings
        path_names_to_rotate = set()
        for _jname, jbones in cascade_entries:
            for bone in jbones:
                bone_name = bone.get("name", "")
                bound_parts = bindings.get(bone_name, [])
                if isinstance(bound_parts, str):
                    bound_parts = [bound_parts]
                path_names_to_rotate.update(bound_parts)

        if not path_names_to_rotate:
            return json.dumps({
                "error": f"No paths are bound to bones attached to joint "
                         f"'{params.joint_name}'. Use adobe_ai_part_bind first."
            })

        # Build JSX to rotate each bound pathItem around the pivot
        # We use a single JSX call that processes all paths for efficiency
        path_names_js = json.dumps(list(path_names_to_rotate))

        jsx = f"""(function() {{
    var doc = app.activeDocument;
    var pathNames = {path_names_js};
    var pivotX = {pivot_x};
    var pivotY = {pivot_y};
    var cosA = {cos_a};
    var sinA = {sin_a};
    var rotated = [];
    var errors = [];

    for (var n = 0; n < pathNames.length; n++) {{
        var pName = pathNames[n];
        var item = null;

        // Search all layers for the named pathItem
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

        // Rotate each anchor point and its handles around the pivot
        var pts = item.pathPoints;
        for (var i = 0; i < pts.length; i++) {{
            var p = pts[i];
            var a = p.anchor;
            var ld = p.leftDirection;
            var rd = p.rightDirection;

            // Rotate anchor
            var adx = a[0] - pivotX;
            var ady = a[1] - pivotY;
            var newAx = pivotX + adx * cosA - ady * sinA;
            var newAy = pivotY + adx * sinA + ady * cosA;

            // Rotate left handle
            var ldx = ld[0] - pivotX;
            var ldy = ld[1] - pivotY;
            var newLx = pivotX + ldx * cosA - ldy * sinA;
            var newLy = pivotY + ldx * sinA + ldy * cosA;

            // Rotate right handle
            var rdx = rd[0] - pivotX;
            var rdy = rd[1] - pivotY;
            var newRx = pivotX + rdx * cosA - rdy * sinA;
            var newRy = pivotY + rdx * sinA + rdy * cosA;

            p.anchor = [newAx, newAy];
            p.leftDirection = [newLx, newLy];
            p.rightDirection = [newRx, newRy];
        }}

        rotated.push(pName);
    }}

    return JSON.stringify({{
        rotated_paths: rotated,
        errors: errors,
        pivot: [pivotX, pivotY],
        point_count: rotated.length
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        # Update joint positions in the rig for all cascade joints
        # (skip the root joint which is the pivot itself)
        updated_joints = {}
        for jname, _jbones in cascade_entries:
            if jname == params.joint_name:
                # The pivot joint itself doesn't move
                updated_joints[jname] = {"x": pivot_x, "y": pivot_y}
                continue
            if jname in joints:
                old = joints[jname]
                new_x, new_y = _rotate_point(
                    old["x"], old["y"], pivot_x, pivot_y, cos_a, sin_a
                )
                joints[jname] = {"x": round(new_x, 3), "y": round(new_y, 3)}
                updated_joints[jname] = joints[jname]

        rig["joints"] = joints
        _save_rig(params.character_name, rig)

        # Merge JSX result with joint update info
        try:
            jsx_data = json.loads(result["stdout"])
        except (json.JSONDecodeError, KeyError):
            jsx_data = {"raw": result["stdout"]}

        jsx_data["angle_degrees"] = params.angle
        jsx_data["cascade"] = params.cascade
        jsx_data["updated_joints"] = updated_joints
        return json.dumps(jsx_data)
