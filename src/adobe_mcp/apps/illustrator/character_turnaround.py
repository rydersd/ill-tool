"""Generate multiple views (front, side, 3/4, back) of a rigged character.

Creates turnaround sheets by duplicating the character's bound paths and
applying view-specific transforms:
  - front:  original paths as-is
  - side:   scale X by 0.6 (flatten profile)
  - 3-4:    scale X by 0.85 (slight perspective)
  - back:   mirror horizontally (flip X)

Each view is placed on a separate artboard or spaced horizontally with
optional horizontal guideline overlays for proportion consistency.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiCharacterTurnaroundInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# View transform definitions (testable without JSX)
# ---------------------------------------------------------------------------

VIEW_TRANSFORMS = {
    "front": {"scale_x": 1.0, "mirror": False, "label": "FRONT"},
    "side":  {"scale_x": 0.6, "mirror": False, "label": "SIDE"},
    "3-4":   {"scale_x": 0.85, "mirror": False, "label": "3/4"},
    "back":  {"scale_x": 1.0, "mirror": True,  "label": "BACK"},
}


def _get_view_transform(view_name: str) -> dict:
    """Return the transform parameters for a named view.

    Returns the transform dict with scale_x, mirror, and label.
    Unknown views default to front (no transform).
    """
    return VIEW_TRANSFORMS.get(view_name.lower().strip(), VIEW_TRANSFORMS["front"])


def _parse_views(views_str: str) -> list[str]:
    """Parse comma-separated view names into a validated list.

    Unrecognized view names are silently skipped.
    """
    raw = [v.strip().lower() for v in views_str.split(",") if v.strip()]
    return [v for v in raw if v in VIEW_TRANSFORMS]


def _calculate_view_positions(
    views: list[str],
    spacing: float,
    char_width: float,
) -> list[dict]:
    """Calculate horizontal positions for each view.

    Each view gets: x_offset (left edge of view space), scale_x, mirror, label.

    Args:
        views: list of view names in order
        spacing: horizontal spacing between view centers in points
        char_width: estimated character width in points

    Returns:
        list of dicts with x_offset, scale_x, mirror, label per view
    """
    positions = []
    for i, view in enumerate(views):
        transform = _get_view_transform(view)
        x_offset = i * (char_width + spacing)
        positions.append({
            "view": view,
            "x_offset": round(x_offset, 2),
            "scale_x": transform["scale_x"],
            "mirror": transform["mirror"],
            "label": transform["label"],
        })
    return positions


def _total_width(views: list[str], spacing: float, char_width: float) -> float:
    """Calculate total width needed for all views."""
    if not views:
        return 0
    return len(views) * char_width + (len(views) - 1) * spacing


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_turnaround tool."""

    @mcp.tool(
        name="adobe_ai_character_turnaround",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_turnaround(params: AiCharacterTurnaroundInput) -> str:
        """Generate front/side/3-4/back views of a rigged character.

        Duplicates the character's Drawing layer paths for each view,
        applying scale and mirror transforms. Optionally adds horizontal
        proportion guidelines across all views.
        """
        rig = _load_rig(params.character_name)
        bindings = rig.get("bindings", {})
        joints = rig.get("joints", {})

        # Collect all bound path names for duplication
        all_paths = set()
        for bone_name, bound in bindings.items():
            if isinstance(bound, str):
                all_paths.add(bound)
            elif isinstance(bound, list):
                all_paths.update(bound)

        views = _parse_views(params.views)
        if not views:
            return json.dumps({
                "error": "No valid views specified.",
                "valid_views": list(VIEW_TRANSFORMS.keys()),
            })

        views_js = json.dumps(views)
        paths_js = json.dumps(list(all_paths))
        show_guides = "true" if params.include_guidelines else "false"
        spacing = params.spacing

        # Build transforms array for JSX
        transforms = []
        for view in views:
            t = _get_view_transform(view)
            transforms.append({
                "view": view,
                "scale_x": t["scale_x"],
                "mirror": t["mirror"],
                "label": t["label"],
            })
        transforms_js = json.dumps(transforms)

        jsx = f"""(function() {{
    var doc = app.activeDocument;
    var views = {views_js};
    var transforms = {transforms_js};
    var pathNames = {paths_js};
    var spacing = {spacing};
    var showGuides = {show_guides};

    // Find source paths from Drawing layer
    var sourceLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Drawing") {{
            sourceLayer = doc.layers[i];
            break;
        }}
    }}

    if (!sourceLayer) {{
        return JSON.stringify({{error: "No Drawing layer found. Create character paths first."}});
    }}

    // Get character bounding box from source layer
    var srcItems = [];
    for (var p = 0; p < pathNames.length; p++) {{
        try {{
            var item = sourceLayer.pathItems.getByName(pathNames[p]);
            if (item) srcItems.push(item);
        }} catch(e) {{}}
    }}

    // If no bound paths, use all items on Drawing layer
    if (srcItems.length === 0) {{
        for (var s = 0; s < sourceLayer.pageItems.length; s++) {{
            srcItems.push(sourceLayer.pageItems[s]);
        }}
    }}

    if (srcItems.length === 0) {{
        return JSON.stringify({{error: "No items found to duplicate."}});
    }}

    // Calculate character bounds
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (var b = 0; b < srcItems.length; b++) {{
        var gb = srcItems[b].geometricBounds;
        if (gb[0] < minX) minX = gb[0];
        if (gb[2] > maxX) maxX = gb[2];
        if (gb[3] < minY) minY = gb[3];
        if (gb[1] > maxY) maxY = gb[1];
    }}

    var charWidth = maxX - minX;
    var charHeight = maxY - minY;
    var charCenterX = (minX + maxX) / 2;
    var charCenterY = (minY + maxY) / 2;

    var createdViews = [];

    for (var v = 0; v < transforms.length; v++) {{
        var tf = transforms[v];
        var xOffset = v * (charWidth + spacing);

        // Create a layer for this view
        var viewLayer = doc.layers.add();
        viewLayer.name = "Turnaround_" + tf.label;

        // Duplicate each source item
        for (var d = 0; d < srcItems.length; d++) {{
            var dup = srcItems[d].duplicate(viewLayer, ElementPlacement.PLACEATEND);
            dup.name = srcItems[d].name + "_" + tf.view;

            // Move to view position
            var dupBounds = dup.geometricBounds;
            var dupCenterX = (dupBounds[0] + dupBounds[2]) / 2;
            dup.translate(xOffset + charCenterX - dupCenterX, 0);

            // Apply horizontal scale
            if (tf.mirror) {{
                // Mirror: scale X by -100% around character center
                var mx = dup.geometricBounds;
                var mcx = (mx[0] + mx[2]) / 2;
                dup.resize(-100, 100, true, true, true, true, 100,
                    Transformation.CENTER);
            }} else if (tf.scale_x !== 1.0) {{
                dup.resize(tf.scale_x * 100, 100, true, true, true, true, 100,
                    Transformation.CENTER);
            }}
        }}

        // Add view label below
        var labelTf = viewLayer.textFrames.add();
        labelTf.contents = tf.label;
        labelTf.name = "turnaround_label_" + tf.view;
        labelTf.position = [xOffset + charCenterX - 15, minY - 15];
        labelTf.textRange.characterAttributes.size = 10;
        var labelClr = new RGBColor();
        labelClr.red = 80; labelClr.green = 80; labelClr.blue = 80;
        labelTf.textRange.characterAttributes.fillColor = labelClr;

        createdViews.push({{
            view: tf.view,
            label: tf.label,
            x_offset: xOffset,
            scale_x: tf.scale_x,
            mirror: tf.mirror
        }});
    }}

    // Optional horizontal proportion guidelines
    if (showGuides && views.length > 1) {{
        var guideLayer = doc.layers.add();
        guideLayer.name = "Turnaround_Guidelines";

        // Draw horizontal lines at key Y positions:
        // top of head, chin, shoulders, waist, knees, feet
        var fractions = [0, 0.12, 0.25, 0.5, 0.75, 1.0];
        var totalWidth = (views.length - 1) * (charWidth + spacing) + charWidth;
        var guideClr = new RGBColor();
        guideClr.red = 200; guideClr.green = 200; guideClr.blue = 200;

        for (var g = 0; g < fractions.length; g++) {{
            var gy = maxY - fractions[g] * charHeight;
            var guide = guideLayer.pathItems.add();
            guide.setEntirePath([
                [minX - 10, gy],
                [minX + totalWidth + 10, gy]
            ]);
            guide.name = "turnaround_guide_" + g;
            guide.filled = false;
            guide.stroked = true;
            guide.strokeWidth = 0.5;
            guide.strokeColor = guideClr;
            guide.strokeDashes = [4, 4];
        }}
    }}

    return JSON.stringify({{
        views: createdViews,
        character_bounds: {{
            width: charWidth,
            height: charHeight,
            center: [charCenterX, charCenterY]
        }},
        total_views: createdViews.length,
        guidelines: showGuides
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result.get("success", False):
            return json.dumps({"error": result.get("stderr", "Unknown error")})

        try:
            jsx_data = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            jsx_data = {"total_views": len(views)}

        # Check for JSX-level error
        if "error" in jsx_data:
            return json.dumps(jsx_data)

        # Store turnaround info in rig
        rig["turnaround"] = {
            "views": views,
            "spacing": spacing,
            "include_guidelines": params.include_guidelines,
        }
        _save_rig(params.character_name, rig)

        return json.dumps({
            "character_name": params.character_name,
            "views": jsx_data.get("views", []),
            "character_bounds": jsx_data.get("character_bounds", {}),
            "total_views": len(views),
            "guidelines": params.include_guidelines,
        }, indent=2)
