"""Create storyboard page layouts with panel grids, gutters, and annotation fields.

Generates a structured storyboard template document with configurable panel
counts, aspect ratios, gutters, margins, title areas, and optional text fields
for description, dialogue, and duration per panel.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiStoryboardTemplateInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Presets: columns x rows
# ---------------------------------------------------------------------------

PRESETS = {
    "standard":   {"columns": 2, "rows": 3},
    "widescreen": {"columns": 2, "rows": 2},
    "vertical":   {"columns": 1, "rows": 4},
    "cinematic":  {"columns": 3, "rows": 3},
}


# ---------------------------------------------------------------------------
# Pure-math helpers (testable without JSX)
# ---------------------------------------------------------------------------


def _resolve_preset(preset: str, custom_cols: int, custom_rows: int) -> tuple[int, int]:
    """Resolve a preset name to (columns, rows).

    For the 'custom' preset, the caller-supplied columns/rows are used.
    Returns (columns, rows).
    """
    if preset in PRESETS:
        p = PRESETS[preset]
        return p["columns"], p["rows"]
    # custom or unknown → use explicit values
    return custom_cols, custom_rows


def _parse_ratio(ratio_str: str) -> float:
    """Parse a panel aspect ratio string to a float.

    Supports formats:
      - "16:9"  → 1.778
      - "4:3"   → 1.333
      - "2.39:1" → 2.39
      - "1:1"   → 1.0
      - "1.85"  → 1.85  (plain float)
    """
    ratio_str = ratio_str.strip()
    if ":" in ratio_str:
        parts = ratio_str.split(":")
        try:
            w = float(parts[0])
            h = float(parts[1])
            if h == 0:
                return 1.0
            return w / h
        except (ValueError, IndexError):
            return 16.0 / 9.0
    try:
        return float(ratio_str)
    except ValueError:
        return 16.0 / 9.0


def _calculate_panel_dimensions(
    page_width: float,
    page_height: float,
    margin: float,
    gutter: float,
    columns: int,
    rows: int,
    ratio: float,
    title_height: float,
    field_height: float,
) -> dict:
    """Calculate panel dimensions that fit within the page constraints.

    Returns a dict with:
      - panel_width, panel_height: dimensions of each panel rectangle
      - positions: list of (x, y) top-left positions for each panel
      - total_panels: columns * rows
      - fits: whether the calculated dimensions are positive
    """
    # Available drawing area
    usable_width = page_width - 2 * margin
    usable_height = page_height - 2 * margin - title_height

    # Width per panel (accounting for gutters between columns)
    total_gutter_w = gutter * (columns - 1) if columns > 1 else 0
    panel_width = (usable_width - total_gutter_w) / columns

    # Height per panel row (accounting for gutters and per-panel fields)
    total_gutter_h = gutter * (rows - 1) if rows > 1 else 0
    total_field_h = field_height * rows
    available_h = usable_height - total_gutter_h - total_field_h
    panel_height_from_grid = available_h / rows

    # Apply aspect ratio constraint: panel_width / panel_height = ratio
    panel_height_from_ratio = panel_width / ratio if ratio > 0 else panel_height_from_grid

    # Use the smaller of the two to ensure panels fit
    panel_height = min(panel_height_from_grid, panel_height_from_ratio)

    # If ratio-constrained height is smaller, width is already correct.
    # If grid-constrained height is smaller, recalculate width from ratio.
    if panel_height == panel_height_from_grid and panel_height_from_ratio > panel_height_from_grid:
        panel_width = panel_height * ratio

    # Calculate positions (top-left of each panel, AI coordinate system)
    # AI: Y increases upward, so top of page is positive Y
    positions = []
    for row in range(rows):
        for col in range(columns):
            x = margin + col * (panel_width + gutter)
            # Y position: start from top of usable area, go downward
            # In AI coords, "top" is page_height - margin - title_height
            y_offset = title_height + row * (panel_height + field_height + gutter)
            y = page_height - margin - y_offset
            positions.append((round(x, 2), round(y, 2)))

    return {
        "panel_width": round(panel_width, 2),
        "panel_height": round(panel_height, 2),
        "positions": positions,
        "total_panels": columns * rows,
        "fits": panel_width > 0 and panel_height > 0,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_storyboard_template tool."""

    @mcp.tool(
        name="adobe_ai_storyboard_template",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_storyboard_template(params: AiStoryboardTemplateInput) -> str:
        """Create a storyboard page layout with panel rectangles, gutters,
        title area, and annotation fields.

        Presets: standard (2x3), widescreen (2x2), vertical (1x4), cinematic (3x3).
        """
        action = params.action.lower().strip()

        # ── list_presets ──────────────────────────────────────────────
        if action == "list_presets":
            return json.dumps({
                "action": "list_presets",
                "presets": {
                    name: {"columns": p["columns"], "rows": p["rows"]}
                    for name, p in PRESETS.items()
                },
            }, indent=2)

        # ── clear ─────────────────────────────────────────────────────
        elif action == "clear":
            jsx = """(function() {
    var doc = app.activeDocument;
    var removed = false;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Template") {
            doc.layers[i].remove();
            removed = true;
            break;
        }
    }
    return JSON.stringify({removed: removed});
})();"""
            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            return json.dumps({"action": "clear", "removed": True})

        # ── create ────────────────────────────────────────────────────
        elif action == "create":
            columns, rows = _resolve_preset(params.preset, params.columns, params.rows)
            ratio = _parse_ratio(params.panel_ratio)

            title_height = 40.0 if params.title else 0.0
            field_height = 50.0 if params.include_fields else 0.0

            dims = _calculate_panel_dimensions(
                page_width=params.page_width,
                page_height=params.page_height,
                margin=params.margin,
                gutter=params.gutter,
                columns=columns,
                rows=rows,
                ratio=ratio,
                title_height=title_height,
                field_height=field_height,
            )

            if not dims["fits"]:
                return json.dumps({
                    "error": "Panels do not fit within the page with current settings. "
                             "Try reducing margins, gutter, rows, or columns.",
                })

            pw = dims["panel_width"]
            ph = dims["panel_height"]
            positions_js = json.dumps(dims["positions"])
            title_text = escape_jsx_string(params.title) if params.title else ""
            include_fields = "true" if params.include_fields else "false"

            jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Remove existing Template layer if present
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Template") {{
            doc.layers[i].remove();
            break;
        }}
    }}

    var tplLayer = doc.layers.add();
    tplLayer.name = "Template";

    var positions = {positions_js};
    var panelW = {pw};
    var panelH = {ph};
    var created = [];

    // Title text
    var titleText = "{title_text}";
    if (titleText.length > 0) {{
        var tf = tplLayer.textFrames.add();
        tf.contents = titleText;
        tf.name = "storyboard_title";
        tf.position = [{params.margin}, {params.page_height - params.margin}];
        tf.textRange.characterAttributes.size = 18;
        var titleClr = new RGBColor();
        titleClr.red = 40; titleClr.green = 40; titleClr.blue = 40;
        tf.textRange.characterAttributes.fillColor = titleClr;
    }}

    // Draw panels
    for (var i = 0; i < positions.length; i++) {{
        var pos = positions[i];
        var px = pos[0];
        var py = pos[1];
        var panelNum = i + 1;

        // Panel rectangle
        var rect = tplLayer.pathItems.rectangle(py, px, panelW, panelH);
        rect.name = "panel_" + panelNum + "_frame";
        rect.filled = false;
        rect.stroked = true;
        rect.strokeWidth = 1;
        var strokeClr = new RGBColor();
        strokeClr.red = 60; strokeClr.green = 60; strokeClr.blue = 60;
        rect.strokeColor = strokeClr;

        // Panel number label
        var numLabel = tplLayer.textFrames.add();
        numLabel.contents = "Panel " + panelNum;
        numLabel.name = "panel_" + panelNum + "_label";
        numLabel.position = [px + 4, py - 4];
        numLabel.textRange.characterAttributes.size = 8;
        var numClr = new RGBColor();
        numClr.red = 120; numClr.green = 120; numClr.blue = 120;
        numLabel.textRange.characterAttributes.fillColor = numClr;

        // Optional annotation fields below panel
        if ({include_fields}) {{
            var fieldY = py - panelH - 4;
            var fields = ["Description:", "Dialogue:", "Duration:"];
            for (var f = 0; f < fields.length; f++) {{
                var fieldTf = tplLayer.textFrames.add();
                fieldTf.contents = fields[f];
                fieldTf.name = "panel_" + panelNum + "_field_" + f;
                fieldTf.position = [px + 2, fieldY - (f * 14)];
                fieldTf.textRange.characterAttributes.size = 7;
                var fClr = new RGBColor();
                fClr.red = 150; fClr.green = 150; fClr.blue = 150;
                fieldTf.textRange.characterAttributes.fillColor = fClr;
            }}
        }}

        created.push({{
            panel: panelNum,
            x: px,
            y: py,
            width: panelW,
            height: panelH
        }});
    }}

    // Lock the template layer
    tplLayer.locked = true;

    return JSON.stringify({{
        panels: created,
        total: created.length
    }});
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            try:
                jsx_data = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                jsx_data = {"total": dims["total_panels"]}

            return json.dumps({
                "action": "create",
                "preset": params.preset,
                "columns": columns,
                "rows": rows,
                "panel_ratio": params.panel_ratio,
                "panel_width": pw,
                "panel_height": ph,
                "total_panels": dims["total_panels"],
                "page_size": [params.page_width, params.page_height],
                "title": params.title,
                "include_fields": params.include_fields,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "clear", "list_presets"],
            })
