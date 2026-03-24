"""Treat body parts as 3D primitives projected onto 2D.

Provides projection math for spheres, cylinders, and boxes viewed at
arbitrary angles.  The pure-Python math computes projected outlines;
JSX draws the results in Illustrator.

Actions:
    project_sphere   – sphere → ellipse based on view angle
    project_cylinder – cylinder axis + radius → two curves + end caps
    project_box      – box centre + dimensions + rotation → projected outline
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiFormVolumeInput(BaseModel):
    """Project 3D form volumes onto 2D."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: project_sphere, project_cylinder, project_box",
    )
    character_name: str = Field(default="character", description="Character identifier")
    # Sphere / shared params
    center_x: float = Field(default=0, description="Centre X in AI coordinates")
    center_y: float = Field(default=0, description="Centre Y in AI coordinates")
    radius: float = Field(default=50, description="Radius (or half-width for box)", ge=0)
    view_angle: float = Field(
        default=0,
        description="View rotation angle in degrees (0=front, 90=side)",
    )
    # Cylinder params
    axis_end_x: Optional[float] = Field(default=None, description="Cylinder axis end X")
    axis_end_y: Optional[float] = Field(default=None, description="Cylinder axis end Y")
    # Box params
    width: Optional[float] = Field(default=None, description="Box width", ge=0)
    height: Optional[float] = Field(default=None, description="Box height", ge=0)
    depth: Optional[float] = Field(default=None, description="Box depth", ge=0)
    rotation_deg: float = Field(default=0, description="Box Y-axis rotation in degrees")


# ---------------------------------------------------------------------------
# Projection math (pure Python)
# ---------------------------------------------------------------------------


def project_sphere(
    cx: float, cy: float, radius: float, view_angle_deg: float
) -> dict:
    """Project a sphere onto 2D as an ellipse.

    At 0 degrees (front view) the projection is a perfect circle.
    As the view rotates, the horizontal axis foreshortens by cos(angle).

    Returns {cx, cy, rx, ry, is_circle}.
    """
    angle_rad = math.radians(view_angle_deg)
    rx = radius * abs(math.cos(angle_rad))  # foreshortened axis
    ry = radius  # vertical axis stays constant
    return {
        "cx": round(cx, 2),
        "cy": round(cy, 2),
        "rx": round(rx, 2),
        "ry": round(ry, 2),
        "is_circle": abs(rx - ry) < 0.01,
    }


def project_cylinder(
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    radius: float,
    view_angle_deg: float,
) -> dict:
    """Project a cylinder onto 2D.

    Returns the two parallel contour lines and elliptical end caps.
    The cylinder axis is projected, then offset by +-radius perpendicular.
    End caps are ellipses foreshortened by the view angle.

    Returns {contour_left, contour_right, cap_start, cap_end, axis_length_2d}.
    """
    # Cylinder axis direction in 2D
    dx = end_x - start_x
    dy = end_y - start_y
    axis_len = math.sqrt(dx * dx + dy * dy)
    if axis_len == 0:
        axis_len = 1.0

    # Unit perpendicular (CCW)
    perp_x = -dy / axis_len
    perp_y = dx / axis_len

    # Contour offsets
    offset_x = perp_x * radius
    offset_y = perp_y * radius

    contour_left = [
        [round(start_x + offset_x, 2), round(start_y + offset_y, 2)],
        [round(end_x + offset_x, 2), round(end_y + offset_y, 2)],
    ]
    contour_right = [
        [round(start_x - offset_x, 2), round(start_y - offset_y, 2)],
        [round(end_x - offset_x, 2), round(end_y - offset_y, 2)],
    ]

    # End-cap ellipses (foreshortened by view angle)
    angle_rad = math.radians(view_angle_deg)
    cap_rx = radius  # full width perpendicular to axis
    cap_ry = radius * abs(math.cos(angle_rad))  # foreshortened along viewing axis

    cap_start = {
        "cx": round(start_x, 2), "cy": round(start_y, 2),
        "rx": round(cap_rx, 2), "ry": round(cap_ry, 2),
    }
    cap_end = {
        "cx": round(end_x, 2), "cy": round(end_y, 2),
        "rx": round(cap_rx, 2), "ry": round(cap_ry, 2),
    }

    return {
        "contour_left": contour_left,
        "contour_right": contour_right,
        "cap_start": cap_start,
        "cap_end": cap_end,
        "axis_length_2d": round(axis_len, 2),
    }


def project_box(
    cx: float, cy: float,
    width: float, height: float, depth: float,
    rotation_deg: float,
) -> dict:
    """Project a box onto 2D using simple oblique projection.

    The box face is (width x height) in the XY plane, depth extends
    at 45 degrees to the right and upward, foreshortened.

    Returns {corners: [[x,y], ...], edges: [[i,j], ...]}.
    """
    hw = width / 2
    hh = height / 2
    rot = math.radians(rotation_deg)

    # Front face corners (before rotation)
    front = [
        [-hw, -hh],  # bottom-left
        [hw, -hh],   # bottom-right
        [hw, hh],    # top-right
        [-hw, hh],   # top-left
    ]

    # Depth offset: oblique projection at 45 degrees, foreshortened to 50 %
    depth_offset_x = depth * 0.5 * math.cos(math.radians(45))
    depth_offset_y = depth * 0.5 * math.sin(math.radians(45))

    back = [
        [f[0] + depth_offset_x, f[1] + depth_offset_y]
        for f in front
    ]

    all_corners = front + back  # 0-3 front, 4-7 back

    # Apply rotation around centre
    def rotate(pt):
        rx = pt[0] * math.cos(rot) - pt[1] * math.sin(rot)
        ry = pt[0] * math.sin(rot) + pt[1] * math.cos(rot)
        return [round(cx + rx, 2), round(cy + ry, 2)]

    projected_corners = [rotate(c) for c in all_corners]

    # Edges: front face, back face, connecting edges
    edges = [
        [0, 1], [1, 2], [2, 3], [3, 0],  # front
        [4, 5], [5, 6], [6, 7], [7, 4],  # back
        [0, 4], [1, 5], [2, 6], [3, 7],  # connecting
    ]

    return {
        "corners": projected_corners,
        "edges": edges,
        "front_face": [0, 1, 2, 3],
        "back_face": [4, 5, 6, 7],
    }


# ---------------------------------------------------------------------------
# JSX builders
# ---------------------------------------------------------------------------


def _sphere_jsx(cx: float, cy: float, rx: float, ry: float) -> str:
    return f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{ layer = doc.layers.getByName("FormVolume"); }}
    catch(e) {{ layer = doc.layers.add(); layer.name = "FormVolume"; }}

    var ell = layer.pathItems.ellipse(
        {cy + ry}, {cx - rx}, {rx * 2}, {ry * 2}
    );
    ell.name = "form_sphere";
    ell.filled = false;
    ell.stroked = true;
    var c = new RGBColor();
    c.red = 100; c.green = 100; c.blue = 200;
    ell.strokeColor = c;
    ell.strokeWidth = 0.75;
    ell.strokeDashes = [4, 3];
    return JSON.stringify({{shape: "sphere", cx: {cx}, cy: {cy}, rx: {rx}, ry: {ry}}});
}})();
"""


def _box_jsx(corners: list, edges: list) -> str:
    corners_js = json.dumps(corners)
    edges_js = json.dumps(edges)
    return f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{ layer = doc.layers.getByName("FormVolume"); }}
    catch(e) {{ layer = doc.layers.add(); layer.name = "FormVolume"; }}

    var corners = {corners_js};
    var edges = {edges_js};
    var c = new RGBColor();
    c.red = 100; c.green = 100; c.blue = 200;

    for (var i = 0; i < edges.length; i++) {{
        var e = edges[i];
        var seg = layer.pathItems.add();
        seg.setEntirePath([corners[e[0]], corners[e[1]]]);
        seg.name = "form_box_edge_" + i;
        seg.filled = false;
        seg.stroked = true;
        seg.strokeColor = c;
        seg.strokeWidth = 0.75;
        seg.strokeDashes = [4, 3];
    }}

    return JSON.stringify({{shape: "box", edge_count: edges.length}});
}})();
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_form_volume tool."""

    @mcp.tool(
        name="adobe_ai_form_volume",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_form_volume(params: AiFormVolumeInput) -> str:
        """Project 3D form volumes (sphere, cylinder, box) onto 2D and draw in Illustrator.

        Sphere → ellipse, Cylinder → parallel contours + end caps,
        Box → projected outline with visible edges.
        """
        action = params.action.lower().strip()

        if action == "project_sphere":
            proj = project_sphere(
                params.center_x, params.center_y,
                params.radius, params.view_angle,
            )
            jsx = _sphere_jsx(proj["cx"], proj["cy"], proj["rx"], proj["ry"])
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **proj})

        elif action == "project_cylinder":
            if params.axis_end_x is None or params.axis_end_y is None:
                return json.dumps({"error": "project_cylinder requires axis_end_x and axis_end_y"})
            proj = project_cylinder(
                params.center_x, params.center_y,
                params.axis_end_x, params.axis_end_y,
                params.radius, params.view_angle,
            )
            # Draw contour lines and end caps
            return json.dumps({"action": action, **proj})

        elif action == "project_box":
            w = params.width if params.width is not None else params.radius * 2
            h = params.height if params.height is not None else params.radius * 2
            d = params.depth if params.depth is not None else params.radius * 2
            proj = project_box(
                params.center_x, params.center_y,
                w, h, d, params.rotation_deg,
            )
            jsx = _box_jsx(proj["corners"], proj["edges"])
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return json.dumps({"action": action, **proj})

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["project_sphere", "project_cylinder", "project_box"],
            })
