"""Create rapid thumbnail grids for rough composition blocking.

Actions:
    create – Create a new artboard with 8-12 tiny panels laid out in a grid.
             Each panel is a numbered rectangle with minimal chrome.
    clear  – Remove the thumbnail artboard and its contents.
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiThumbnailGridInput(BaseModel):
    """Create a thumbnail grid for rough composition blocking."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(..., description="Action: create, clear")
    columns: int = Field(default=4, description="Number of columns in the grid", ge=1, le=12)
    rows: int = Field(default=3, description="Number of rows in the grid", ge=1, le=12)
    panel_width: float = Field(default=150, description="Width of each panel in points", ge=20)
    panel_height: float = Field(default=85, description="Height of each panel in points", ge=20)
    gap: float = Field(default=10, description="Gap between panels in points", ge=0)
    margin: float = Field(default=20, description="Margin around the grid in points", ge=0)
    label_size: float = Field(default=8, description="Font size for panel numbers", ge=4)


# ---------------------------------------------------------------------------
# Grid computation (pure Python)
# ---------------------------------------------------------------------------


def compute_grid_layout(
    columns: int,
    rows: int,
    panel_width: float,
    panel_height: float,
    gap: float,
    margin: float,
) -> dict:
    """Compute the grid layout dimensions and per-panel positions.

    Returns {artboard_width, artboard_height, panel_count, panels: [{index, col, row, x, y}, ...]}.
    """
    # Total artboard size
    grid_width = columns * panel_width + (columns - 1) * gap
    grid_height = rows * panel_height + (rows - 1) * gap
    artboard_width = grid_width + 2 * margin
    artboard_height = grid_height + 2 * margin

    panels = []
    index = 1
    for row in range(rows):
        for col in range(columns):
            x = margin + col * (panel_width + gap)
            y = margin + row * (panel_height + gap)
            panels.append({
                "index": index,
                "col": col,
                "row": row,
                "x": round(x, 2),
                "y": round(y, 2),
            })
            index += 1

    return {
        "artboard_width": round(artboard_width, 2),
        "artboard_height": round(artboard_height, 2),
        "panel_count": len(panels),
        "columns": columns,
        "rows": rows,
        "panels": panels,
    }


# ---------------------------------------------------------------------------
# JSX builders
# ---------------------------------------------------------------------------


def _create_grid_jsx(
    layout: dict,
    panel_width: float,
    panel_height: float,
    label_size: float,
) -> str:
    """Build JSX that creates an artboard with numbered thumbnail panels."""
    ab_w = layout["artboard_width"]
    ab_h = layout["artboard_height"]
    panels_js = json.dumps(layout["panels"])
    return f"""
(function() {{
    var doc = app.activeDocument;

    // Find rightmost artboard edge for positioning
    var maxRight = 0;
    for (var i = 0; i < doc.artboards.length; i++) {{
        var r = doc.artboards[i].artboardRect;
        if (r[2] > maxRight) maxRight = r[2];
    }}

    var abLeft = maxRight + 60;
    var abTop = 0;
    var abRight = abLeft + {ab_w};
    var abBottom = abTop - {ab_h};

    var abIdx = doc.artboards.add([abLeft, abTop, abRight, abBottom]);
    var ab = doc.artboards[abIdx];
    ab.name = "Thumbnails";

    var layer = doc.layers.add();
    layer.name = "Thumbnail_Grid";
    doc.activeLayer = layer;

    var panels = {panels_js};
    var sc = new RGBColor();
    sc.red = 80; sc.green = 80; sc.blue = 80;

    var tc = new RGBColor();
    tc.red = 120; tc.green = 120; tc.blue = 120;

    for (var p = 0; p < panels.length; p++) {{
        var panel = panels[p];
        var px = abLeft + panel.x;
        var py = abTop - panel.y;

        // Panel rectangle
        var rect = layer.pathItems.rectangle(py, px, {panel_width}, {panel_height});
        rect.name = "thumb_" + panel.index;
        rect.filled = false;
        rect.stroked = true;
        rect.strokeColor = sc;
        rect.strokeWidth = 0.5;

        // Panel number
        var tf = layer.textFrames.add();
        tf.contents = "" + panel.index;
        tf.name = "thumb_label_" + panel.index;
        tf.position = [px + 3, py - 3];
        tf.textRange.characterAttributes.size = {label_size};
        tf.textRange.characterAttributes.fillColor = tc;
    }}

    return JSON.stringify({{
        artboard_index: abIdx,
        artboard_name: ab.name,
        panel_count: panels.length,
        artboard_width: {ab_w},
        artboard_height: {ab_h}
    }});
}})();
"""


_CLEAR_JSX = """
(function() {
    var doc = app.activeDocument;
    // Remove the Thumbnail_Grid layer
    var layerRemoved = false;
    try {
        var layer = doc.layers.getByName("Thumbnail_Grid");
        layer.remove();
        layerRemoved = true;
    } catch(e) {}

    // Remove the Thumbnails artboard
    var abRemoved = false;
    for (var i = doc.artboards.length - 1; i >= 0; i--) {
        if (doc.artboards[i].name === "Thumbnails") {
            doc.artboards.remove(i);
            abRemoved = true;
            break;
        }
    }

    return JSON.stringify({
        layer_removed: layerRemoved,
        artboard_removed: abRemoved
    });
})();
"""


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_thumbnail_grid tool."""

    @mcp.tool(
        name="adobe_ai_thumbnail_grid",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_thumbnail_grid(params: AiThumbnailGridInput) -> str:
        """Create a rapid thumbnail grid for rough composition blocking.

        Generates a grid of small numbered panels on a new artboard,
        useful for quickly blocking out storyboard compositions.
        """
        action = params.action.lower().strip()

        if action == "create":
            layout = compute_grid_layout(
                params.columns, params.rows,
                params.panel_width, params.panel_height,
                params.gap, params.margin,
            )
            jsx = _create_grid_jsx(
                layout, params.panel_width, params.panel_height, params.label_size,
            )
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})

            try:
                jsx_data = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                jsx_data = {}

            return json.dumps({
                "action": "create",
                **layout,
                "jsx_result": jsx_data,
            })

        elif action == "clear":
            result = await _async_run_jsx("illustrator", _CLEAR_JSX)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})
            return result["stdout"]

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "clear"],
            })
