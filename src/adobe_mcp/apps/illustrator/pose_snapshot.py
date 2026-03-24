"""Capture, apply, list, or delete named pose snapshots.

A pose snapshot stores the complete state of all joint positions AND the
full path geometry (anchor points, handles) for every bound pathItem.
This allows exact restoration of a pose without computing rotations --
we simply set all path points back to their stored positions.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPoseSnapshotInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def _get_all_bound_path_names(rig: dict) -> list:
    """Return a deduplicated list of all path names bound to any bone."""
    bindings = rig.get("bindings", {})
    names = set()
    for parts in bindings.values():
        if isinstance(parts, str):
            names.add(parts)
        elif isinstance(parts, list):
            names.update(parts)
    return sorted(names)


def register(mcp):
    """Register the adobe_ai_pose_snapshot tool."""

    @mcp.tool(
        name="adobe_ai_pose_snapshot",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_pose_snapshot(params: AiPoseSnapshotInput) -> str:
        """Capture or apply a named pose snapshot.

        Actions:
        - capture: read all current joint positions and path geometry, save
          as a named pose in the rig file.
        - apply: load a named pose and restore all path geometry and joint
          positions to match.
        - list: show all saved poses with joint/path counts.
        - delete: remove a pose from the rig file.
        """
        rig = _load_rig(params.character_name)
        poses = rig.get("poses", {})

        # ── LIST ──────────────────────────────────────────────
        if params.action == "list":
            summary = []
            for pname, pdata in poses.items():
                summary.append({
                    "name": pname,
                    "joint_count": len(pdata.get("joints", {})),
                    "path_count": len(pdata.get("path_states", {})),
                })
            return json.dumps({"poses": summary, "total": len(summary)})

        # ── DELETE ────────────────────────────────────────────
        if params.action == "delete":
            if params.pose_name not in poses:
                return json.dumps({
                    "error": f"Pose '{params.pose_name}' not found. "
                             f"Available: {list(poses.keys())}"
                })
            del poses[params.pose_name]
            rig["poses"] = poses
            _save_rig(params.character_name, rig)
            return json.dumps({
                "deleted": params.pose_name,
                "remaining_poses": list(poses.keys()),
            })

        # ── CAPTURE ───────────────────────────────────────────
        if params.action == "capture":
            path_names = _get_all_bound_path_names(rig)
            if not path_names:
                return json.dumps({
                    "error": "No paths are bound to the skeleton. "
                             "Use adobe_ai_part_bind first."
                })

            # Read all path geometry from Illustrator
            path_names_js = json.dumps(path_names)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var pathNames = {path_names_js};
    var states = {{}};

    for (var n = 0; n < pathNames.length; n++) {{
        var pName = pathNames[n];
        var item = null;
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{
                item = doc.layers[l].pathItems.getByName(pName);
                if (item) break;
            }} catch(e) {{}}
        }}
        if (!item) continue;

        var pts = item.pathPoints;
        var points = [];
        var handles = [];
        for (var i = 0; i < pts.length; i++) {{
            var p = pts[i];
            points.push([
                Math.round(p.anchor[0] * 1000) / 1000,
                Math.round(p.anchor[1] * 1000) / 1000
            ]);
            handles.push({{
                left: [
                    Math.round(p.leftDirection[0] * 1000) / 1000,
                    Math.round(p.leftDirection[1] * 1000) / 1000
                ],
                right: [
                    Math.round(p.rightDirection[0] * 1000) / 1000,
                    Math.round(p.rightDirection[1] * 1000) / 1000
                ]
            }});
        }}

        states[pName] = {{
            points: points,
            handles: handles,
            closed: item.closed
        }};
    }}

    return JSON.stringify(states);
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})

            try:
                path_states = json.loads(result["stdout"])
            except json.JSONDecodeError:
                return json.dumps({
                    "error": "Failed to parse path state from Illustrator",
                    "raw": result["stdout"],
                })

            # Build the pose entry
            pose_data = {
                "joints": dict(rig.get("joints", {})),
                "path_states": path_states,
            }
            poses[params.pose_name] = pose_data
            rig["poses"] = poses
            _save_rig(params.character_name, rig)

            return json.dumps({
                "captured": params.pose_name,
                "joint_count": len(pose_data["joints"]),
                "path_count": len(path_states),
                "path_names": list(path_states.keys()),
            })

        # ── APPLY ─────────────────────────────────────────────
        if params.action == "apply":
            if params.pose_name not in poses:
                return json.dumps({
                    "error": f"Pose '{params.pose_name}' not found. "
                             f"Available: {list(poses.keys())}"
                })

            pose_data = poses[params.pose_name]
            path_states = pose_data.get("path_states", {})
            target_joints = pose_data.get("joints", {})

            if not path_states:
                return json.dumps({
                    "error": f"Pose '{params.pose_name}' has no path state data."
                })

            # Build JSX to restore all path geometry
            # We pass the full path states as a JSON object and iterate in JSX
            states_js = json.dumps(path_states)

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

        // Restore anchor positions via setEntirePath, then restore handles
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

            # Restore joint positions in the rig
            rig["joints"] = dict(target_joints)
            _save_rig(params.character_name, rig)

            try:
                jsx_data = json.loads(result["stdout"])
            except json.JSONDecodeError:
                jsx_data = {"raw": result["stdout"]}

            jsx_data["pose_name"] = params.pose_name
            jsx_data["joints_restored"] = len(target_joints)
            return json.dumps(jsx_data)

        return json.dumps({
            "error": f"Unknown action: {params.action}. "
                     f"Valid: capture, apply, list, delete"
        })
