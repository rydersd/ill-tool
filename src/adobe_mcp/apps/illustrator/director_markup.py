"""Director markup annotations on storyboard panels.

Provides structured markup (notes, arrows, circles) on a dedicated
"Director Notes" layer that can be toggled, exported, and cleared.

JSX draws on "Director Notes" layer in orange color.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiDirectorMarkupInput(BaseModel):
    """Structured markup annotations on storyboard panels."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: add_note, add_arrow, add_circle, clear, toggle_visibility, export"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    panel_number: int = Field(default=1, description="Target panel number", ge=1)
    text: Optional[str] = Field(
        default=None, description="Note text content (for add_note)"
    )
    x: Optional[float] = Field(default=None, description="X position")
    y: Optional[float] = Field(default=None, description="Y position")
    x2: Optional[float] = Field(default=None, description="End X position (for add_arrow)")
    y2: Optional[float] = Field(default=None, description="End Y position (for add_arrow)")
    radius: float = Field(default=30.0, description="Circle radius (for add_circle)", gt=0)
    visible: bool = Field(default=True, description="Visibility state for toggle_visibility")


# ---------------------------------------------------------------------------
# Markup data helpers
# ---------------------------------------------------------------------------

# Default panel dimensions
PANEL_WIDTH = 960
PANEL_HEIGHT = 540


def _ensure_markup(rig: dict) -> dict:
    """Ensure the rig has a director_markup structure."""
    if "director_markup" not in rig:
        rig["director_markup"] = {}
    return rig


def _get_panel_markup(rig: dict, panel_number: int) -> list:
    """Get markup list for a specific panel."""
    return rig.get("director_markup", {}).get(str(panel_number), {}).get("items", [])


def _set_panel_markup(rig: dict, panel_number: int, items: list, visible: bool = True) -> dict:
    """Set markup list for a specific panel."""
    rig = _ensure_markup(rig)
    rig["director_markup"][str(panel_number)] = {
        "items": items,
        "visible": visible,
    }
    return rig


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_director_markup tool."""

    @mcp.tool(
        name="adobe_ai_director_markup",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_director_markup(params: AiDirectorMarkupInput) -> str:
        """Add structured markup annotations to storyboard panels.

        Actions:
        - add_note: text annotation at position
        - add_arrow: arrow from point A to B
        - add_circle: circle highlight around an area
        - clear: remove all markup from a panel
        - toggle_visibility: show/hide the Director Notes layer
        - export: export markup as JSON
        """
        action = params.action.lower().strip()
        panel_num = params.panel_number
        char = params.character_name

        rig = _load_rig(char)
        rig = _ensure_markup(rig)

        panel_key = str(panel_num)
        panel_data = rig["director_markup"].get(panel_key, {"items": [], "visible": True})
        items = panel_data.get("items", [])
        visible = panel_data.get("visible", True)

        panel_gap = 40
        panel_idx = panel_num - 1
        ab_left = (PANEL_WIDTH + panel_gap) * panel_idx
        ab_top = 0

        # ── add_note ─────────────────────────────────────────────────
        if action == "add_note":
            if not params.text:
                return json.dumps({"error": "add_note requires 'text'"})

            note_x = params.x if params.x is not None else PANEL_WIDTH * 0.5
            note_y = params.y if params.y is not None else PANEL_HEIGHT * 0.5

            note = {
                "type": "note",
                "text": params.text,
                "x": note_x,
                "y": note_y,
            }
            items.append(note)
            rig = _set_panel_markup(rig, panel_num, items, visible)
            _save_rig(char, rig)

            # Draw via JSX
            ai_x = ab_left + note_x
            ai_y = ab_top - note_y
            escaped_text = params.text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Director Notes_{panel_num}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Director Notes_{panel_num}";
    }}
    var noteColor = new RGBColor();
    noteColor.red = 255; noteColor.green = 140; noteColor.blue = 0;
    var tf = layer.textFrames.add();
    tf.contents = "{escaped_text}";
    tf.position = [{ai_x}, {ai_y}];
    tf.textRange.characterAttributes.size = 10;
    tf.textRange.characterAttributes.fillColor = noteColor;
    tf.name = "dir_note_{panel_num}_{len(items)}";
    return JSON.stringify({{added: "note", panel: {panel_num}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "add_note",
                "panel_number": panel_num,
                "note": note,
                "total_items": len(items),
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── add_arrow ────────────────────────────────────────────────
        elif action == "add_arrow":
            x1 = params.x if params.x is not None else PANEL_WIDTH * 0.3
            y1 = params.y if params.y is not None else PANEL_HEIGHT * 0.5
            x2 = params.x2 if params.x2 is not None else PANEL_WIDTH * 0.7
            y2 = params.y2 if params.y2 is not None else PANEL_HEIGHT * 0.5

            arrow = {
                "type": "arrow",
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
            }
            items.append(arrow)
            rig = _set_panel_markup(rig, panel_num, items, visible)
            _save_rig(char, rig)

            # Draw via JSX
            ai_x1 = ab_left + x1
            ai_y1 = ab_top - y1
            ai_x2 = ab_left + x2
            ai_y2 = ab_top - y2

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Director Notes_{panel_num}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Director Notes_{panel_num}";
    }}
    var arrowColor = new RGBColor();
    arrowColor.red = 255; arrowColor.green = 140; arrowColor.blue = 0;
    var arrow = layer.pathItems.add();
    arrow.setEntirePath([[{ai_x1}, {ai_y1}], [{ai_x2}, {ai_y2}]]);
    arrow.stroked = true;
    arrow.strokeWidth = 2;
    arrow.strokeColor = arrowColor;
    arrow.filled = false;
    arrow.name = "dir_arrow_{panel_num}_{len(items)}";
    return JSON.stringify({{added: "arrow", panel: {panel_num}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "add_arrow",
                "panel_number": panel_num,
                "arrow": arrow,
                "total_items": len(items),
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── add_circle ───────────────────────────────────────────────
        elif action == "add_circle":
            cx = params.x if params.x is not None else PANEL_WIDTH * 0.5
            cy = params.y if params.y is not None else PANEL_HEIGHT * 0.5
            r = params.radius

            circle = {
                "type": "circle",
                "cx": cx, "cy": cy,
                "radius": r,
            }
            items.append(circle)
            rig = _set_panel_markup(rig, panel_num, items, visible)
            _save_rig(char, rig)

            # AI coords: ellipse(top, left, width, height)
            ai_cx = ab_left + cx
            ai_cy = ab_top - cy

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("Director Notes_{panel_num}");
    }} catch(e) {{
        layer = doc.layers.add();
        layer.name = "Director Notes_{panel_num}";
    }}
    var circColor = new RGBColor();
    circColor.red = 255; circColor.green = 140; circColor.blue = 0;
    var circ = layer.pathItems.ellipse(
        {ai_cy + r}, {ai_cx - r}, {r * 2}, {r * 2}
    );
    circ.stroked = true;
    circ.strokeWidth = 2;
    circ.strokeColor = circColor;
    circ.filled = false;
    circ.name = "dir_circle_{panel_num}_{len(items)}";
    return JSON.stringify({{added: "circle", panel: {panel_num}}});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "add_circle",
                "panel_number": panel_num,
                "circle": circle,
                "total_items": len(items),
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── clear ────────────────────────────────────────────────────
        elif action == "clear":
            had_items = len(items) > 0
            rig = _set_panel_markup(rig, panel_num, [], visible)
            _save_rig(char, rig)

            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    try {{
        var layer = doc.layers.getByName("Director Notes_{panel_num}");
        while (layer.pageItems.length > 0) layer.pageItems[0].remove();
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
                "had_items": had_items,
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── toggle_visibility ────────────────────────────────────────
        elif action == "toggle_visibility":
            new_visible = params.visible
            rig = _set_panel_markup(rig, panel_num, items, new_visible)
            _save_rig(char, rig)

            visible_js = "true" if new_visible else "false"
            jsx = f"""
(function() {{
    var doc = app.activeDocument;
    try {{
        var layer = doc.layers.getByName("Director Notes_{panel_num}");
        layer.visible = {visible_js};
        return JSON.stringify({{"visible": {visible_js}}});
    }} catch(e) {{
        return JSON.stringify({{"error": "layer not found"}});
    }}
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "toggle_visibility",
                "panel_number": panel_num,
                "visible": new_visible,
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── export ───────────────────────────────────────────────────
        elif action == "export":
            return json.dumps({
                "action": "export",
                "panel_number": panel_num,
                "visible": visible,
                "items": items,
                "total_items": len(items),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": [
                    "add_note", "add_arrow", "add_circle",
                    "clear", "toggle_visibility", "export",
                ],
            })
