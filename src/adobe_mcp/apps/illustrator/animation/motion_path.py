"""Define motion paths — arcs that a character follows across frames.

Motion paths are stored in the rig file under `motion_paths` and can
optionally be drawn as smooth spline curves on a "Motion" layer in
Illustrator for visual reference.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiMotionPathInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _ensure_motion_paths(rig: dict) -> dict:
    """Ensure the rig has a motion_paths structure."""
    if "motion_paths" not in rig:
        rig["motion_paths"] = {}
    return rig


def _parse_waypoints(points_json: str) -> list:
    """Parse a JSON string of [[x, y, frame], ...] waypoints.

    Returns a list of dicts: [{"x": float, "y": float, "frame": int}, ...].
    Raises ValueError on bad input.
    """
    raw = json.loads(points_json)
    if not isinstance(raw, list):
        raise ValueError("points must be a JSON array of [x, y, frame] arrays")

    waypoints = []
    for i, pt in enumerate(raw):
        if not isinstance(pt, (list, tuple)) or len(pt) < 3:
            raise ValueError(
                f"Waypoint {i} must be [x, y, frame] — got {pt!r}"
            )
        waypoints.append({
            "x": float(pt[0]),
            "y": float(pt[1]),
            "frame": int(pt[2]),
        })

    # Sort by frame for clean ordering
    waypoints.sort(key=lambda w: w["frame"])
    return waypoints


async def _draw_motion_path(waypoints: list, path_name: str) -> dict:
    """Draw a smooth motion path on the Motion layer in Illustrator.

    Uses waypoint positions as anchor points and auto-smooths the curve.
    Returns the JSX result dict.
    """
    if len(waypoints) < 2:
        return {"success": False, "stderr": "Need at least 2 waypoints to draw a path"}

    # Build the AI coordinate points array
    ai_points = [[wp["x"], wp["y"]] for wp in waypoints]
    points_json = json.dumps(ai_points)
    escaped_name = escape_jsx_string(path_name)

    jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create Motion layer
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Motion") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "Motion";
    }}
    doc.activeLayer = layer;

    // Remove any existing path with the same name
    try {{
        var existing = layer.pathItems.getByName("{escaped_name}");
        if (existing) existing.remove();
    }} catch(e) {{}}

    // Create the motion path
    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = false;
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = 1.5;
    path.name = "{escaped_name}";

    // Dashed stroke for motion path visual
    var motionColor = new RGBColor();
    motionColor.red = 100;
    motionColor.green = 150;
    motionColor.blue = 255;
    path.strokeColor = motionColor;
    path.strokeDashes = [8, 4];

    // Smooth the path: set bezier handles to 1/3 distance to neighbors
    var n = path.pathPoints.length;
    if (n >= 3) {{
        for (var i = 0; i < n; i++) {{
            var pt = path.pathPoints[i];
            var prevIdx = Math.max(0, i - 1);
            var nextIdx = Math.min(n - 1, i + 1);
            var prev = path.pathPoints[prevIdx];
            var next = path.pathPoints[nextIdx];

            if (i > 0) {{
                var dx_l = (pt.anchor[0] - prev.anchor[0]) / 3;
                var dy_l = (pt.anchor[1] - prev.anchor[1]) / 3;
                pt.leftDirection = [pt.anchor[0] - dx_l, pt.anchor[1] - dy_l];
            }}
            if (i < n - 1) {{
                var dx_r = (next.anchor[0] - pt.anchor[0]) / 3;
                var dy_r = (next.anchor[1] - pt.anchor[1]) / 3;
                pt.rightDirection = [pt.anchor[0] + dx_r, pt.anchor[1] + dy_r];
            }}
        }}
    }}

    // Add small diamond markers at each waypoint
    var markerSize = 5;
    for (var w = 0; w < {len(ai_points)}; w++) {{
        var wp = {points_json}[w];
        var marker = layer.pathItems.add();
        // Diamond shape: 4 points rotated 45 degrees
        marker.setEntirePath([
            [wp[0], wp[1] + markerSize],
            [wp[0] + markerSize, wp[1]],
            [wp[0], wp[1] - markerSize],
            [wp[0] - markerSize, wp[1]]
        ]);
        marker.closed = true;
        marker.filled = true;
        marker.stroked = false;
        marker.fillColor = motionColor;
        marker.name = "{escaped_name}_wp_" + w;
    }}

    return JSON.stringify({{
        name: path.name,
        layer: "Motion",
        pointCount: path.pathPoints.length,
        bounds: path.geometricBounds
    }});
}})();
"""
    return await _async_run_jsx("illustrator", jsx)


async def _remove_motion_path_visual(path_name: str) -> dict:
    """Remove the visual representation of a motion path from the Motion layer."""
    escaped_name = escape_jsx_string(path_name)
    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var removed = 0;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Motion") {{
            var layer = doc.layers[i];
            // Remove the main path
            try {{
                var p = layer.pathItems.getByName("{escaped_name}");
                if (p) {{ p.remove(); removed++; }}
            }} catch(e) {{}}
            // Remove waypoint markers
            var toRemove = [];
            for (var j = 0; j < layer.pathItems.length; j++) {{
                var name = layer.pathItems[j].name;
                if (name.indexOf("{escaped_name}_wp_") === 0) {{
                    toRemove.push(layer.pathItems[j]);
                }}
            }}
            for (var k = toRemove.length - 1; k >= 0; k--) {{
                toRemove[k].remove();
                removed++;
            }}
            break;
        }}
    }}
    return JSON.stringify({{removed: removed}});
}})();
"""
    return await _async_run_jsx("illustrator", jsx)


def register(mcp):
    """Register the adobe_ai_motion_path tool."""

    @mcp.tool(
        name="adobe_ai_motion_path",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_motion_path(params: AiMotionPathInput) -> str:
        """Define motion paths for character movement across frames.

        Motion paths are arcs defined by waypoints [x, y, frame] that the
        character root follows.  Stored in the rig file and optionally
        drawn on a Motion layer in Illustrator as a dashed spline with
        diamond waypoint markers.
        """
        rig = _load_rig(params.character_name)
        rig = _ensure_motion_paths(rig)

        action = params.action.lower().strip()

        # ── create ──────────────────────────────────────────────────────
        if action == "create":
            if not params.points:
                return json.dumps({
                    "error": "points is required for create action.",
                    "format": "JSON array of [x, y, frame] arrays, e.g. [[100, -300, 0], [400, -200, 24]]",
                })

            try:
                waypoints = _parse_waypoints(params.points)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                return json.dumps({"error": f"Invalid points: {exc}"})

            if len(waypoints) < 2:
                return json.dumps({"error": "Need at least 2 waypoints to define a motion path."})

            # Store in rig
            rig["motion_paths"][params.path_name] = {
                "waypoints": waypoints,
                "character_name": params.character_name,
            }
            _save_rig(params.character_name, rig)

            # Optionally draw in Illustrator
            drawn = False
            draw_error = None
            if params.show_path:
                draw_result = await _draw_motion_path(waypoints, params.path_name)
                drawn = draw_result.get("success", False)
                if not drawn:
                    draw_error = draw_result.get("stderr", "Unknown draw error")

            # Compute path stats
            total_distance = 0.0
            for i in range(1, len(waypoints)):
                dx = waypoints[i]["x"] - waypoints[i - 1]["x"]
                dy = waypoints[i]["y"] - waypoints[i - 1]["y"]
                total_distance += (dx ** 2 + dy ** 2) ** 0.5

            frame_span = waypoints[-1]["frame"] - waypoints[0]["frame"]

            result = {
                "action": "create",
                "path_name": params.path_name,
                "waypoint_count": len(waypoints),
                "waypoints": waypoints,
                "total_distance_pts": round(total_distance, 1),
                "frame_span": frame_span,
                "drawn_in_ai": drawn,
            }
            if draw_error:
                result["draw_error"] = draw_error
            return json.dumps(result, indent=2)

        # ── edit ────────────────────────────────────────────────────────
        elif action == "edit":
            if params.path_name not in rig["motion_paths"]:
                available = list(rig["motion_paths"].keys())
                return json.dumps({
                    "error": f"Motion path '{params.path_name}' not found.",
                    "available_paths": available,
                })

            if not params.points:
                return json.dumps({"error": "points is required for edit action."})

            try:
                waypoints = _parse_waypoints(params.points)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                return json.dumps({"error": f"Invalid points: {exc}"})

            if len(waypoints) < 2:
                return json.dumps({"error": "Need at least 2 waypoints."})

            rig["motion_paths"][params.path_name]["waypoints"] = waypoints
            _save_rig(params.character_name, rig)

            # Redraw if show_path
            drawn = False
            if params.show_path:
                draw_result = await _draw_motion_path(waypoints, params.path_name)
                drawn = draw_result.get("success", False)

            return json.dumps({
                "action": "edit",
                "path_name": params.path_name,
                "waypoint_count": len(waypoints),
                "waypoints": waypoints,
                "drawn_in_ai": drawn,
            }, indent=2)

        # ── delete ──────────────────────────────────────────────────────
        elif action == "delete":
            if params.path_name not in rig["motion_paths"]:
                available = list(rig["motion_paths"].keys())
                return json.dumps({
                    "error": f"Motion path '{params.path_name}' not found.",
                    "available_paths": available,
                })

            del rig["motion_paths"][params.path_name]
            _save_rig(params.character_name, rig)

            # Remove visual from Illustrator
            remove_result = await _remove_motion_path_visual(params.path_name)

            return json.dumps({
                "action": "delete",
                "path_name": params.path_name,
                "deleted": True,
                "remaining_paths": list(rig["motion_paths"].keys()),
            }, indent=2)

        # ── list ────────────────────────────────────────────────────────
        elif action == "list":
            paths_summary = []
            for name, data in rig["motion_paths"].items():
                wps = data.get("waypoints", [])
                total_dist = 0.0
                for i in range(1, len(wps)):
                    dx = wps[i]["x"] - wps[i - 1]["x"]
                    dy = wps[i]["y"] - wps[i - 1]["y"]
                    total_dist += (dx ** 2 + dy ** 2) ** 0.5

                frame_span = 0
                if wps:
                    frame_span = wps[-1]["frame"] - wps[0]["frame"]

                paths_summary.append({
                    "name": name,
                    "character_name": data.get("character_name", ""),
                    "waypoint_count": len(wps),
                    "waypoints": wps,
                    "total_distance_pts": round(total_dist, 1),
                    "frame_span": frame_span,
                })

            return json.dumps({
                "action": "list",
                "motion_paths": paths_summary,
                "total_paths": len(paths_summary),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "edit", "delete", "list"],
            })
