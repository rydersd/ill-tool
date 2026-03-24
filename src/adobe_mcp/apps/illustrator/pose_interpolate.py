"""Interpolate between two saved poses to create in-between frames.

Given two named poses and a parameter t (0..1), linearly interpolates
every joint position and every path anchor point / bezier handle.
If apply=True the interpolated state is written to the Illustrator
document via JSX.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiPoseInterpolateInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between *a* and *b* at parameter *t*."""
    return a + t * (b - a)


def _interpolate_path_states(states_a: dict, states_b: dict, t: float) -> dict:
    """Interpolate path geometry between two pose snapshots.

    For every path present in *both* snapshots, interpolates each anchor
    point and bezier handle pair-wise.  Paths in only one snapshot are
    left untouched (taken from whichever snapshot has them).
    """
    result = {}
    all_names = set(list(states_a.keys()) + list(states_b.keys()))

    for name in all_names:
        if name not in states_a:
            result[name] = states_b[name]
            continue
        if name not in states_b:
            result[name] = states_a[name]
            continue

        sa = states_a[name]
        sb = states_b[name]
        pts_a = sa.get("points", [])
        pts_b = sb.get("points", [])
        hdl_a = sa.get("handles", [])
        hdl_b = sb.get("handles", [])

        # Only interpolate if both have the same number of points
        if len(pts_a) != len(pts_b):
            # Fall back to the closer pose
            result[name] = sa if t < 0.5 else sb
            continue

        interp_pts = []
        interp_hdl = []
        for i in range(len(pts_a)):
            interp_pts.append([
                round(_lerp(pts_a[i][0], pts_b[i][0], t), 3),
                round(_lerp(pts_a[i][1], pts_b[i][1], t), 3),
            ])

            ha = hdl_a[i] if i < len(hdl_a) else {"left": pts_a[i], "right": pts_a[i]}
            hb = hdl_b[i] if i < len(hdl_b) else {"left": pts_b[i], "right": pts_b[i]}
            interp_hdl.append({
                "left": [
                    round(_lerp(ha["left"][0], hb["left"][0], t), 3),
                    round(_lerp(ha["left"][1], hb["left"][1], t), 3),
                ],
                "right": [
                    round(_lerp(ha["right"][0], hb["right"][0], t), 3),
                    round(_lerp(ha["right"][1], hb["right"][1], t), 3),
                ],
            })

        result[name] = {
            "points": interp_pts,
            "handles": interp_hdl,
            "closed": sa.get("closed", False),
        }

    return result


def _interpolate_joints(joints_a: dict, joints_b: dict, t: float) -> dict:
    """Interpolate joint positions between two pose snapshots."""
    result = {}
    all_names = set(list(joints_a.keys()) + list(joints_b.keys()))
    for name in all_names:
        if name not in joints_a:
            result[name] = joints_b[name]
            continue
        if name not in joints_b:
            result[name] = joints_a[name]
            continue
        ja = joints_a[name]
        jb = joints_b[name]
        result[name] = {
            "x": round(_lerp(ja["x"], jb["x"], t), 3),
            "y": round(_lerp(ja["y"], jb["y"], t), 3),
        }
    return result


def register(mcp):
    """Register the adobe_ai_pose_interpolate tool."""

    @mcp.tool(
        name="adobe_ai_pose_interpolate",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_pose_interpolate(params: AiPoseInterpolateInput) -> str:
        """Interpolate between two saved poses.

        Linearly interpolates joint positions and path geometry between
        pose_a and pose_b at parameter t (0=pose_a, 1=pose_b).
        If apply=True, writes the interpolated state to Illustrator.
        """
        rig = _load_rig(params.character_name)
        poses = rig.get("poses", {})

        # Validate both poses exist
        missing = []
        if params.pose_a not in poses:
            missing.append(params.pose_a)
        if params.pose_b not in poses:
            missing.append(params.pose_b)
        if missing:
            return json.dumps({
                "error": f"Pose(s) not found: {missing}. "
                         f"Available: {list(poses.keys())}"
            })

        pose_a = poses[params.pose_a]
        pose_b = poses[params.pose_b]

        # Interpolate joints
        joints_a = pose_a.get("joints", {})
        joints_b = pose_b.get("joints", {})
        interp_joints = _interpolate_joints(joints_a, joints_b, params.t)

        # Interpolate path states
        states_a = pose_a.get("path_states", {})
        states_b = pose_b.get("path_states", {})
        interp_states = _interpolate_path_states(states_a, states_b, params.t)

        if not params.apply:
            return json.dumps({
                "t": params.t,
                "pose_a": params.pose_a,
                "pose_b": params.pose_b,
                "interpolated_joints": interp_joints,
                "path_count": len(interp_states),
                "applied": False,
            })

        # Apply the interpolated state via JSX
        states_js = json.dumps(interp_states)

        jsx = f"""(function() {{
    var doc = app.activeDocument;
    var states = {states_js};
    var applied = [];
    var errors = [];

    for (var pName in states) {{
        if (!states.hasOwnProperty(pName)) continue;
        var state = states[pName];
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

        var pts = state.points;
        var handles = state.handles;

        // Set anchor positions
        item.setEntirePath(pts);

        // Restore bezier handles
        for (var i = 0; i < item.pathPoints.length && i < handles.length; i++) {{
            item.pathPoints[i].leftDirection = handles[i].left;
            item.pathPoints[i].rightDirection = handles[i].right;
        }}

        applied.push(pName);
    }}

    return JSON.stringify({{
        applied_paths: applied,
        errors: errors
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        # Update joint positions in the rig to the interpolated state
        rig["joints"] = interp_joints
        _save_rig(params.character_name, rig)

        try:
            jsx_data = json.loads(result["stdout"])
        except json.JSONDecodeError:
            jsx_data = {"raw": result["stdout"]}

        jsx_data["t"] = params.t
        jsx_data["pose_a"] = params.pose_a
        jsx_data["pose_b"] = params.pose_b
        jsx_data["interpolated_joints"] = interp_joints
        jsx_data["applied"] = True
        return json.dumps(jsx_data)
