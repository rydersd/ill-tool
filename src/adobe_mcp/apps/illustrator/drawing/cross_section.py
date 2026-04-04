"""Cross-section guide drawing for character form volume.

Draws cross-contour ellipses along a limb axis that show 3D form.
Ellipses are placed at evenly-spaced positions along the axis,
with width determined by cross_width at that position and tilt
perpendicular to the axis direction.

JSX draws on a "Cross Sections" layer.
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


class AiCrossSectionInput(BaseModel):
    """Draw cross-contour ellipses showing form volume along limbs."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="draw_cross_sections",
        description="Action: draw_cross_sections",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    axis_name: Optional[str] = Field(
        default=None, description="Named axis from rig (alternative to from/to landmarks)"
    )
    from_landmark: Optional[str] = Field(
        default=None, description="Start landmark for axis"
    )
    to_landmark: Optional[str] = Field(
        default=None, description="End landmark for axis"
    )
    num_sections: int = Field(
        default=5, description="Number of cross-section ellipses", ge=2, le=20
    )
    cross_width: float = Field(
        default=40.0, description="Ellipse width at widest point", gt=0
    )
    taper: float = Field(
        default=0.3,
        description="Taper factor: 0=uniform, 1=fully tapered to point at end",
        ge=0.0, le=1.0,
    )
    foreshorten: float = Field(
        default=1.0,
        description="Foreshortening factor for far-side ellipses (1=none, 0.5=half)",
        ge=0.1, le=1.0,
    )
    layer_name: str = Field(
        default="Cross Sections", description="Target layer name"
    )
    stroke_width: float = Field(default=1.0, ge=0.1)


# ---------------------------------------------------------------------------
# Cross-section geometry
# ---------------------------------------------------------------------------


def compute_ellipse_params(
    axis_origin: list[float],
    axis_angle_rad: float,
    axis_length: float,
    position_frac: float,
    cross_width: float,
    taper: float,
    foreshorten: float,
) -> dict:
    """Compute ellipse parameters for a single cross-section.

    Args:
        axis_origin: [x, y] start of axis in AI coords
        axis_angle_rad: angle of the axis in radians
        axis_length: length of the axis
        position_frac: 0.0=start, 1.0=end of axis
        cross_width: base width of ellipse
        taper: taper factor (0=uniform, 1=fully tapered)
        foreshorten: foreshortening for ellipse height

    Returns:
        {center: [x,y], width, height, tilt_deg}
    """
    # Position along axis
    along_dist = position_frac * axis_length
    cos_a = math.cos(axis_angle_rad)
    sin_a = math.sin(axis_angle_rad)
    cx = axis_origin[0] + along_dist * cos_a
    cy = axis_origin[1] + along_dist * sin_a

    # Tapered width: full at start, reduced at end
    width = cross_width * (1.0 - taper * position_frac)

    # Height (minor axis) is foreshortened
    height = width * foreshorten

    # Tilt: perpendicular to axis
    # Axis angle + 90 degrees = perpendicular
    tilt_deg = math.degrees(axis_angle_rad) + 90.0

    return {
        "center": [round(cx, 2), round(cy, 2)],
        "width": round(width, 2),
        "height": round(height, 2),
        "tilt_deg": round(tilt_deg, 2),
        "position_frac": round(position_frac, 4),
    }


def compute_all_cross_sections(
    axis_origin: list[float],
    axis_angle_rad: float,
    axis_length: float,
    num_sections: int,
    cross_width: float,
    taper: float,
    foreshorten: float,
) -> list[dict]:
    """Compute all cross-section ellipses along an axis.

    Returns a list of ellipse parameter dicts.
    """
    sections = []
    for i in range(num_sections):
        frac = i / max(num_sections - 1, 1)
        params = compute_ellipse_params(
            axis_origin, axis_angle_rad, axis_length,
            frac, cross_width, taper, foreshorten,
        )
        sections.append(params)
    return sections


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_cross_section tool."""

    @mcp.tool(
        name="adobe_ai_cross_section",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_cross_section(params: AiCrossSectionInput) -> str:
        """Draw cross-contour ellipses showing form volume along limbs.

        Places ellipses at evenly-spaced positions along an axis with
        taper and perspective foreshortening.
        """
        action = params.action.lower().strip()
        if action != "draw_cross_sections":
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["draw_cross_sections"],
            })

        rig = _load_rig(params.character_name)
        rig.setdefault("landmarks", {})
        rig.setdefault("axes", {})

        # Resolve axis
        axis_def = None
        if params.axis_name and params.axis_name in rig.get("axes", {}):
            axis_def = rig["axes"][params.axis_name]
        elif params.from_landmark and params.to_landmark:
            lm_a = rig["landmarks"].get(params.from_landmark)
            lm_b = rig["landmarks"].get(params.to_landmark)
            if not lm_a or "ai" not in lm_a:
                return json.dumps({"error": f"Landmark '{params.from_landmark}' not found"})
            if not lm_b or "ai" not in lm_b:
                return json.dumps({"error": f"Landmark '{params.to_landmark}' not found"})

            # Compute axis inline
            ax, ay = lm_a["ai"]
            bx, by = lm_b["ai"]
            dx, dy = bx - ax, by - ay
            length = math.sqrt(dx * dx + dy * dy)
            angle_rad = math.atan2(dy, dx) if length > 0 else 0
            axis_def = {
                "origin": [ax, ay],
                "angle_rad": angle_rad,
                "length": length,
            }
        else:
            return json.dumps({
                "error": "Requires axis_name (stored) or from_landmark + to_landmark",
            })

        # Compute cross sections
        sections = compute_all_cross_sections(
            axis_def["origin"],
            axis_def["angle_rad"],
            axis_def["length"],
            params.num_sections,
            params.cross_width,
            params.taper,
            params.foreshorten,
        )

        # Build JSX to draw ellipses
        escaped_layer = params.layer_name.replace("\\", "\\\\").replace('"', '\\"')
        ellipse_jsx_parts = []

        for idx, sec in enumerate(sections):
            cx, cy = sec["center"]
            w = sec["width"]
            h = sec["height"]
            tilt = sec["tilt_deg"]

            # AI ellipse(top, left, width, height)
            # Center the ellipse on the point
            e_top = cy + h / 2
            e_left = cx - w / 2

            ellipse_jsx_parts.append(f"""
    var e{idx} = layer.pathItems.ellipse({e_top}, {e_left}, {w}, {h});
    e{idx}.name = "cross_section_{idx}";
    e{idx}.stroked = true;
    e{idx}.strokeWidth = {params.stroke_width};
    e{idx}.strokeColor = csColor;
    e{idx}.filled = false;
    // Rotate to align perpendicular to axis
    e{idx}.rotate({tilt - 90});
""")

        jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("{escaped_layer}");
        while (layer.pageItems.length > 0) layer.pageItems[0].remove();
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}
    var csColor = new RGBColor();
    csColor.red = 100; csColor.green = 180; csColor.blue = 220;
    {"".join(ellipse_jsx_parts)}
    return JSON.stringify({{sections: {len(sections)}}});
}})();
"""
        result = await _async_run_jsx("illustrator", jsx)

        return json.dumps({
            "action": "draw_cross_sections",
            "section_count": len(sections),
            "sections": sections,
            "axis_length": round(axis_def["length"], 2),
            "jsx_success": result.get("success", False),
        }, indent=2)
