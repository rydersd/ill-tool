"""Show ghost frames of adjacent poses for animation planning.

Creates an "Onion Skin" layer containing semi-transparent, tinted
duplicates of the character in different poses.  Previous-frame ghosts
are tinted one colour (default blue) and next-frame ghosts another
(default red), with opacity decreasing the further the ghost is from
the current frame.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiOnionSkinInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def register(mcp):
    """Register the adobe_ai_onion_skin tool."""

    @mcp.tool(
        name="adobe_ai_onion_skin",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_onion_skin(params: AiOnionSkinInput) -> str:
        """Show or clear onion skin ghost frames for animation planning.

        Actions:
        - show: For each pose in pose_names, duplicate all bound character
          paths onto an "Onion Skin" layer with reduced opacity and tinted
          colour.  Poses listed before the midpoint are tinted with the
          "before" colour, poses after with the "after" colour.
        - clear: Remove the Onion Skin layer and all its contents.
        """
        rig = _load_rig(params.character_name)

        # ── CLEAR ─────────────────────────────────────────────
        if params.action == "clear":
            jsx = """(function() {
    var doc = app.activeDocument;
    var removed = false;
    for (var i = doc.layers.length - 1; i >= 0; i--) {
        if (doc.layers[i].name === "Onion Skin") {
            doc.layers[i].remove();
            removed = true;
        }
    }
    return JSON.stringify({cleared: removed});
})();"""
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return result["stdout"]

        # ── SHOW ──────────────────────────────────────────────
        if params.action != "show":
            return json.dumps({
                "error": f"Unknown action: {params.action}. Valid: show, clear"
            })

        if not params.pose_names:
            return json.dumps({
                "error": "pose_names is required for the 'show' action. "
                         "Provide a comma-separated list of pose names."
            })

        pose_name_list = [n.strip() for n in params.pose_names.split(",") if n.strip()]
        poses = rig.get("poses", {})

        # Validate all pose names exist
        missing = [p for p in pose_name_list if p not in poses]
        if missing:
            return json.dumps({
                "error": f"Pose(s) not found: {missing}. "
                         f"Available: {list(poses.keys())}"
            })

        # Collect all bound path names for the character
        bindings = rig.get("bindings", {})
        all_path_names = set()
        for parts in bindings.values():
            if isinstance(parts, str):
                all_path_names.add(parts)
            elif isinstance(parts, list):
                all_path_names.update(parts)
        all_path_names = sorted(all_path_names)

        if not all_path_names:
            return json.dumps({
                "error": "No paths are bound to bones. "
                         "Use adobe_ai_part_bind first."
            })

        # Build the onion skin data: for each pose, include the path_states
        # and colour/opacity settings.  Poses in the first half get "before"
        # colour, second half get "after" colour.
        midpoint = len(pose_name_list) / 2.0
        onion_frames = []

        for idx, pname in enumerate(pose_name_list):
            pose_data = poses[pname]
            path_states = pose_data.get("path_states", {})

            # Determine opacity: decreases as we move away from midpoint
            distance_from_mid = abs(idx - midpoint)
            opacity = max(5, 100 - params.opacity_step * (distance_from_mid + 1))

            # Determine tint colour
            if idx < midpoint:
                tint = {
                    "r": params.color_before_r,
                    "g": params.color_before_g,
                    "b": params.color_before_b,
                }
            else:
                tint = {
                    "r": params.color_after_r,
                    "g": params.color_after_g,
                    "b": params.color_after_b,
                }

            onion_frames.append({
                "pose_name": pname,
                "path_states": path_states,
                "opacity": round(opacity, 1),
                "tint": tint,
            })

        # Build JSX to create onion skin layer and populate it
        # Strategy:
        #   1. Remove existing onion skin layer if present
        #   2. Create new locked layer at the bottom
        #   3. For each frame/pose, create paths with stored geometry,
        #      apply tint colour and opacity
        frames_js = json.dumps(onion_frames)
        path_names_js = json.dumps(all_path_names)

        jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Remove existing Onion Skin layer
    for (var i = doc.layers.length - 1; i >= 0; i--) {{
        if (doc.layers[i].name === "Onion Skin") {{
            doc.layers[i].remove();
        }}
    }}

    // Create new Onion Skin layer at the bottom
    var onionLayer = doc.layers.add();
    onionLayer.name = "Onion Skin";
    onionLayer.zOrder(ZOrderMethod.SENDTOBACK);

    var frames = {frames_js};
    var created = 0;

    for (var f = 0; f < frames.length; f++) {{
        var frame = frames[f];
        var states = frame.path_states;
        var opacity = frame.opacity;
        var tR = frame.tint.r;
        var tG = frame.tint.g;
        var tB = frame.tint.b;

        for (var pName in states) {{
            if (!states.hasOwnProperty(pName)) continue;
            var state = states[pName];
            var pts = state.points;
            if (!pts || pts.length < 2) continue;

            // Create a new pathItem on the onion layer
            var ghost = onionLayer.pathItems.add();
            ghost.name = frame.pose_name + "_" + pName + "_ghost";
            ghost.setEntirePath(pts);

            // Restore bezier handles
            var handles = state.handles || [];
            for (var h = 0; h < ghost.pathPoints.length && h < handles.length; h++) {{
                ghost.pathPoints[h].leftDirection = handles[h].left;
                ghost.pathPoints[h].rightDirection = handles[h].right;
            }}

            ghost.closed = state.closed || false;

            // Apply tint as stroke colour with the pose opacity
            ghost.filled = false;
            ghost.stroked = true;
            var strokeColor = new RGBColor();
            strokeColor.red = tR;
            strokeColor.green = tG;
            strokeColor.blue = tB;
            ghost.strokeColor = strokeColor;
            ghost.strokeWidth = 1;
            ghost.opacity = opacity;

            created++;
        }}
    }}

    // Lock the onion skin layer so it doesn't interfere with drawing
    onionLayer.locked = true;

    return JSON.stringify({{
        layer: "Onion Skin",
        frames: frames.length,
        ghost_paths_created: created
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        try:
            data = json.loads(result["stdout"])
        except json.JSONDecodeError:
            data = {"raw": result["stdout"]}

        data["pose_names"] = pose_name_list
        return json.dumps(data)
