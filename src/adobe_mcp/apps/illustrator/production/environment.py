"""Environment and set design tools for storyboard panels.

Places perspective grids, horizon lines, and background layers on a
dedicated "Environment" layer.  Supports 1-point, 2-point, and 3-point
perspective grid construction.

JSX draws on an "Environment" layer.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiEnvironmentInput(BaseModel):
    """Place perspective grids and background layers per scene."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: perspective_grid, horizon_line, place_background, clear"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    panel_number: int = Field(default=1, description="Target panel number", ge=1)
    grid_type: str = Field(
        default="2_point",
        description="Perspective type: 1_point, 2_point, 3_point",
    )
    vanishing_point_x: Optional[float] = Field(
        default=None, description="X position of primary vanishing point"
    )
    vanishing_point_y: Optional[float] = Field(
        default=None, description="Y position of primary vanishing point"
    )
    horizon_y_pct: float = Field(
        default=0.5, description="Horizon line Y position as fraction of panel height (0=top, 1=bottom)",
        ge=0.0, le=1.0,
    )
    num_lines: int = Field(
        default=12, description="Number of radiating perspective lines", ge=4, le=48
    )
    image_path: Optional[str] = Field(
        default=None, description="Background image path for place_background"
    )
    panel_width: float = Field(default=960.0, description="Panel width in points", gt=0)
    panel_height: float = Field(default=540.0, description="Panel height in points", gt=0)


# ---------------------------------------------------------------------------
# Perspective calculation helpers
# ---------------------------------------------------------------------------


def compute_vanishing_points(
    grid_type: str,
    panel_w: float,
    panel_h: float,
    horizon_y_pct: float,
    vp_x: Optional[float] = None,
    vp_y: Optional[float] = None,
) -> list[dict]:
    """Compute vanishing point positions for a perspective grid.

    Returns a list of vanishing point dicts: [{x, y, label}, ...]

    1-point: single VP at center of horizon
    2-point: two VPs at left/right edges of horizon
    3-point: two on horizon + one above or below
    """
    horizon_y = panel_h * horizon_y_pct
    center_x = panel_w / 2

    if grid_type == "1_point":
        vpx = vp_x if vp_x is not None else center_x
        vpy = vp_y if vp_y is not None else horizon_y
        return [{"x": round(vpx, 2), "y": round(vpy, 2), "label": "VP"}]

    elif grid_type == "2_point":
        # Two vanishing points on the horizon, near the edges
        vp_left_x = panel_w * 0.1
        vp_right_x = panel_w * 0.9
        return [
            {"x": round(vp_left_x, 2), "y": round(horizon_y, 2), "label": "VP_L"},
            {"x": round(vp_right_x, 2), "y": round(horizon_y, 2), "label": "VP_R"},
        ]

    elif grid_type == "3_point":
        vp_left_x = panel_w * 0.1
        vp_right_x = panel_w * 0.9
        # Third VP above or below center
        third_y = 0 if horizon_y_pct > 0.5 else panel_h
        return [
            {"x": round(vp_left_x, 2), "y": round(horizon_y, 2), "label": "VP_L"},
            {"x": round(vp_right_x, 2), "y": round(horizon_y, 2), "label": "VP_R"},
            {"x": round(center_x, 2), "y": round(third_y, 2), "label": "VP_V"},
        ]

    return []


def compute_grid_lines(
    vanishing_points: list[dict],
    panel_w: float,
    panel_h: float,
    num_lines: int,
) -> list[dict]:
    """Compute radiating lines from each vanishing point to panel edges.

    Returns list of line dicts: [{start: [x,y], end: [x,y], vp_label}, ...]
    """
    lines = []

    for vp in vanishing_points:
        vpx, vpy = vp["x"], vp["y"]
        label = vp["label"]

        # Distribute target points along the panel edges
        for i in range(num_lines):
            t = i / max(num_lines - 1, 1)
            angle = t * math.pi * 2  # full circle distribution

            # Ray from VP outward
            dx = math.cos(angle)
            dy = math.sin(angle)

            # Find intersection with panel boundary
            # Check all four edges
            best_t = float("inf")
            end_x, end_y = vpx + dx * 1000, vpy + dy * 1000  # fallback

            # Left edge (x=0)
            if dx != 0:
                t_edge = -vpx / dx
                if t_edge > 0:
                    ey = vpy + dy * t_edge
                    if 0 <= ey <= panel_h and t_edge < best_t:
                        best_t = t_edge
                        end_x, end_y = 0, ey

            # Right edge (x=panel_w)
            if dx != 0:
                t_edge = (panel_w - vpx) / dx
                if t_edge > 0:
                    ey = vpy + dy * t_edge
                    if 0 <= ey <= panel_h and t_edge < best_t:
                        best_t = t_edge
                        end_x, end_y = panel_w, ey

            # Top edge (y=0)
            if dy != 0:
                t_edge = -vpy / dy
                if t_edge > 0:
                    ex = vpx + dx * t_edge
                    if 0 <= ex <= panel_w and t_edge < best_t:
                        best_t = t_edge
                        end_x, end_y = ex, 0

            # Bottom edge (y=panel_h)
            if dy != 0:
                t_edge = (panel_h - vpy) / dy
                if t_edge > 0:
                    ex = vpx + dx * t_edge
                    if 0 <= ex <= panel_w and t_edge < best_t:
                        best_t = t_edge
                        end_x, end_y = ex, panel_h

            lines.append({
                "start": [round(vpx, 2), round(vpy, 2)],
                "end": [round(end_x, 2), round(end_y, 2)],
                "vp_label": label,
            })

    return lines


def _ensure_environment(rig: dict) -> dict:
    """Ensure the rig has an environment structure."""
    if "environment" not in rig:
        rig["environment"] = {}
    return rig


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_environment tool."""

    @mcp.tool(
        name="adobe_ai_environment",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_environment(params: AiEnvironmentInput) -> str:
        """Place perspective grids, horizon lines, and backgrounds.

        Actions:
        - perspective_grid: draw 1/2/3-point perspective grid
        - horizon_line: draw horizon at a Y position
        - place_background: place image as background layer
        - clear: remove environment layer for a panel
        """
        action = params.action.lower().strip()
        panel_num = params.panel_number
        pw = params.panel_width
        ph = params.panel_height

        rig = _load_rig(params.character_name)
        rig = _ensure_environment(rig)

        panel_gap = 40
        panel_idx = panel_num - 1
        ab_left = (pw + panel_gap) * panel_idx
        ab_top = 0

        # ── perspective_grid ─────────────────────────────────────────
        if action == "perspective_grid":
            grid_type = params.grid_type.lower().strip()
            if grid_type not in ("1_point", "2_point", "3_point"):
                return json.dumps({
                    "error": f"Unknown grid_type: {grid_type}",
                    "valid_types": ["1_point", "2_point", "3_point"],
                })

            vps = compute_vanishing_points(
                grid_type, pw, ph, params.horizon_y_pct,
                params.vanishing_point_x, params.vanishing_point_y,
            )
            grid_lines = compute_grid_lines(vps, pw, ph, params.num_lines)

            # Store in rig
            rig["environment"][str(panel_num)] = {
                "grid_type": grid_type,
                "vanishing_points": vps,
                "horizon_y_pct": params.horizon_y_pct,
                "line_count": len(grid_lines),
            }
            _save_rig(params.character_name, rig)

            # Build JSX for drawing grid lines
            line_jsx_parts = []
            for idx, line in enumerate(grid_lines):
                sx = ab_left + line["start"][0]
                sy = ab_top - line["start"][1]  # AI Y-up
                ex = ab_left + line["end"][0]
                ey = ab_top - line["end"][1]
                line_jsx_parts.append(
                    f"var ln{idx} = layer.pathItems.add();"
                    f"ln{idx}.setEntirePath([[{sx},{sy}],[{ex},{ey}]]);"
                    f"ln{idx}.stroked=true;ln{idx}.strokeWidth=0.5;"
                    f"ln{idx}.filled=false;"
                    f"ln{idx}.strokeColor=gridColor;"
                    f"ln{idx}.strokeDashes=[4,4];"
                )

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Environment_{panel_num}");
        while (layer.pageItems.length > 0) layer.pageItems[0].remove();
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Environment_{panel_num}";
    }}
    var gridColor = new RGBColor();
    gridColor.red = 180; gridColor.green = 180; gridColor.blue = 200;
    {"".join(line_jsx_parts)}
    return JSON.stringify({{panel: {panel_num}, lines: {len(grid_lines)}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "perspective_grid",
                "panel_number": panel_num,
                "grid_type": grid_type,
                "vanishing_points": vps,
                "line_count": len(grid_lines),
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── horizon_line ─────────────────────────────────────────────
        elif action == "horizon_line":
            horizon_y = ph * params.horizon_y_pct
            ai_y = ab_top - horizon_y  # convert to AI coords

            # Store in rig
            rig["environment"].setdefault(str(panel_num), {})
            rig["environment"][str(panel_num)]["horizon_y_pct"] = params.horizon_y_pct
            rig["environment"][str(panel_num)]["horizon_y_ai"] = round(ai_y, 2)
            _save_rig(params.character_name, rig)

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Environment_{panel_num}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Environment_{panel_num}";
    }}
    var hlColor = new RGBColor();
    hlColor.red = 100; hlColor.green = 150; hlColor.blue = 255;
    var hl = layer.pathItems.add();
    hl.setEntirePath([[{ab_left}, {ai_y}], [{ab_left + pw}, {ai_y}]]);
    hl.name = "horizon_{panel_num}";
    hl.stroked = true;
    hl.strokeWidth = 1;
    hl.strokeColor = hlColor;
    hl.strokeDashes = [8, 4];
    hl.filled = false;
    return JSON.stringify({{panel: {panel_num}, horizon_y: {ai_y}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "horizon_line",
                "panel_number": panel_num,
                "horizon_y_pct": params.horizon_y_pct,
                "horizon_y_ai": round(ai_y, 2),
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── place_background ─────────────────────────────────────────
        elif action == "place_background":
            if not params.image_path:
                return json.dumps({
                    "error": "place_background requires image_path",
                })

            escaped_path = params.image_path.replace("\\", "\\\\")

            # Store in rig
            rig["environment"].setdefault(str(panel_num), {})
            rig["environment"][str(panel_num)]["background_image"] = params.image_path
            _save_rig(params.character_name, rig)

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Environment_{panel_num}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Environment_{panel_num}";
    }}
    var bgFile = new File("{escaped_path}");
    if (!bgFile.exists) {{
        return JSON.stringify({{"error": "Image file not found"}});
    }}
    var placed = layer.placedItems.add();
    placed.file = bgFile;
    placed.name = "background_{panel_num}";
    placed.position = [{ab_left}, {ab_top}];
    // Move to back of layer
    placed.move(layer, ElementPlacement.PLACEATEND);
    return JSON.stringify({{panel: {panel_num}, placed: true}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "place_background",
                "panel_number": panel_num,
                "image_path": params.image_path,
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── clear ────────────────────────────────────────────────────
        elif action == "clear":
            removed = str(panel_num) in rig["environment"]
            if removed:
                del rig["environment"][str(panel_num)]
                _save_rig(params.character_name, rig)

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    try {{
        var layer = doc.layers.getByName("Environment_{panel_num}");
        layer.remove();
        return JSON.stringify({{"cleared": true}});
    }} catch(e) {{
        return JSON.stringify({{"cleared": false, "reason": "layer not found"}});
    }}
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "clear",
                "panel_number": panel_num,
                "removed_data": removed,
                "jsx_success": result.get("success", False),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["perspective_grid", "horizon_line", "place_background", "clear"],
            })
