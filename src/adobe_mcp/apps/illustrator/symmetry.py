"""Mirror/reflect a path across a vertical or horizontal axis.

Operates directly on pathPoints and their bezier handles so the mirror
is geometrically exact. For a vertical axis (left-right mirror), X
coordinates are reflected and bezier handle directions are swapped
left<->right. For a horizontal axis (top-bottom mirror), Y coordinates
are reflected and handle Y values are flipped.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSymmetryInput


def register(mcp):
    """Register the adobe_ai_symmetry tool."""

    @mcp.tool(
        name="adobe_ai_symmetry",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_symmetry(params: AiSymmetryInput) -> str:
        """Mirror a pathItem across a vertical or horizontal axis.

        For vertical axis: reflects left-right (X flipped around axis_position).
        For horizontal axis: reflects top-bottom (Y flipped around axis_position).
        If axis_position is null, uses the center of the active artboard.
        If copy is true, duplicates the item first and mirrors the copy.
        """
        # Build the item-finder expression depending on name vs index
        if params.name:
            escaped_name = escape_jsx_string(params.name)
            find_item_js = f"""
    // Search all layers and groups for the named pathItem
    var item = null;
    for (var l = 0; l < doc.layers.length; l++) {{
        try {{ item = doc.layers[l].pathItems.getByName("{escaped_name}"); }} catch(e) {{}}
        if (item) break;
        // Also search inside groups on each layer
        for (var g = 0; g < doc.layers[l].groupItems.length; g++) {{
            try {{ item = doc.layers[l].groupItems[g].pathItems.getByName("{escaped_name}"); }} catch(e) {{}}
            if (item) break;
        }}
        if (item) break;
    }}
    if (!item) return JSON.stringify({{error: "PathItem not found: {escaped_name}"}});
"""
        elif params.index is not None:
            find_item_js = f"""
    var allPaths = doc.pathItems;
    if ({params.index} >= allPaths.length) return JSON.stringify({{error: "Index {params.index} out of range, doc has " + allPaths.length + " pathItems"}});
    var item = allPaths[{params.index}];
"""
        else:
            return json.dumps({"error": "Either 'name' or 'index' is required."})

        # Determine mirror name
        if params.mirror_name:
            mirror_name = params.mirror_name
        elif params.name:
            mirror_name = f"{params.name}_mirror"
        else:
            mirror_name = f"mirror_{params.index}"
        escaped_mirror = escape_jsx_string(mirror_name)

        axis = params.axis  # "vertical" or "horizontal"
        copy_str = "true" if params.duplicate else "false"

        # axis_position handling: null means get artboard center via JSX
        if params.axis_position is not None:
            axis_pos_js = f"var axisPos = {params.axis_position};"
        else:
            if axis == "vertical":
                # Center X of active artboard
                axis_pos_js = """
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var axisPos = (abRect[0] + abRect[2]) / 2;  // center X
"""
            else:
                # Center Y of active artboard
                axis_pos_js = """
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var axisPos = (abRect[1] + abRect[3]) / 2;  // center Y
"""

        jsx = f"""(function() {{
    var doc = app.activeDocument;
{find_item_js}
{axis_pos_js}

    // Optionally duplicate the item first
    var target = item;
    var doCopy = {copy_str};
    if (doCopy) {{
        target = item.duplicate();
    }}

    // Mirror all pathPoints
    var pts = target.pathPoints;
    for (var i = 0; i < pts.length; i++) {{
        var p = pts[i];
        var anchor = p.anchor;
        var leftDir = p.leftDirection;
        var rightDir = p.rightDirection;

        if ("{axis}" === "vertical") {{
            // Reflect X coordinates around axisPos, swap left<->right handles
            var newAnchorX = 2 * axisPos - anchor[0];
            var newLeftX = 2 * axisPos - rightDir[0];   // left gets old right (mirrored)
            var newLeftY = rightDir[1];
            var newRightX = 2 * axisPos - leftDir[0];   // right gets old left (mirrored)
            var newRightY = leftDir[1];

            p.anchor = [newAnchorX, anchor[1]];
            p.leftDirection = [newLeftX, newLeftY];
            p.rightDirection = [newRightX, newRightY];
        }} else {{
            // Horizontal mirror: reflect Y coordinates, swap left<->right handle Y
            var newAnchorY = 2 * axisPos - anchor[1];
            var newLeftX2 = rightDir[0];
            var newLeftY2 = 2 * axisPos - rightDir[1];
            var newRightX2 = leftDir[0];
            var newRightY2 = 2 * axisPos - leftDir[1];

            p.anchor = [anchor[0], newAnchorY];
            p.leftDirection = [newLeftX2, newLeftY2];
            p.rightDirection = [newRightX2, newRightY2];
        }}
    }}

    // Reverse the point order so winding direction stays correct after mirror
    // (otherwise filled shapes may render inverted)
    // We do this by reading all points, reversing, and re-setting
    var allPts = [];
    for (var j = 0; j < pts.length; j++) {{
        allPts.push({{
            anchor: [pts[j].anchor[0], pts[j].anchor[1]],
            left: [pts[j].leftDirection[0], pts[j].leftDirection[1]],
            right: [pts[j].rightDirection[0], pts[j].rightDirection[1]]
        }});
    }}
    allPts.reverse();
    // After reversing, left and right handles need to swap
    for (var k = 0; k < allPts.length; k++) {{
        var tmp = allPts[k].left;
        allPts[k].left = allPts[k].right;
        allPts[k].right = tmp;
    }}

    // Build anchor array for setEntirePath, then restore handles
    var anchorArr = [];
    for (var m = 0; m < allPts.length; m++) {{
        anchorArr.push(allPts[m].anchor);
    }}
    target.setEntirePath(anchorArr);
    for (var n = 0; n < target.pathPoints.length; n++) {{
        target.pathPoints[n].leftDirection = allPts[n].left;
        target.pathPoints[n].rightDirection = allPts[n].right;
    }}

    // Name the result
    target.name = "{escaped_mirror}";

    return JSON.stringify({{
        mirror_name: target.name,
        axis: "{axis}",
        axis_position: axisPos,
        copied: doCopy,
        point_count: target.pathPoints.length,
        bounds: [
            Math.round(target.geometricBounds[0] * 100) / 100,
            Math.round(target.geometricBounds[1] * 100) / 100,
            Math.round(target.geometricBounds[2] * 100) / 100,
            Math.round(target.geometricBounds[3] * 100) / 100
        ]
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        return result["stdout"]
