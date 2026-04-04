"""Pathfinder boolean operations via JSX menu commands.

Illustrator's Pathfinder panel is not directly scriptable via pathfinder
object methods in a reliable way. Instead we select the two operand paths
by name and execute the corresponding Live Pathfinder menu command, then
expand the live effect into final geometry.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPathBooleanInput

# Map operation names to Illustrator menu command strings
_PATHFINDER_COMMANDS = {
    "unite": "Live Pathfinder Add",
    "minus_front": "Live Pathfinder Minus Front",
    "minus_back": "Live Pathfinder Minus Back",
    "intersect": "Live Pathfinder Intersect",
    "exclude": "Live Pathfinder Exclude",
    "divide": "Live Pathfinder Divide",
}


def register(mcp):
    """Register the adobe_ai_path_boolean tool."""

    @mcp.tool(
        name="adobe_ai_path_boolean",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_path_boolean(params: AiPathBooleanInput) -> str:
        """Run Pathfinder boolean operations (unite, subtract, intersect, etc.) on two named paths.

        Selects both operands by name, executes the Live Pathfinder menu
        command, expands the result, and names it. Returns the result name,
        geometric bounds, and path count.
        """
        # Validate operation
        menu_cmd = _PATHFINDER_COMMANDS.get(params.operation)
        if menu_cmd is None:
            valid = ", ".join(_PATHFINDER_COMMANDS.keys())
            return json.dumps({
                "error": f"Unknown operation: {params.operation}. Valid: {valid}"
            })

        if not params.front_name or not params.back_name:
            return json.dumps({
                "error": "Both front_name and back_name are required."
            })

        escaped_front = escape_jsx_string(params.front_name)
        escaped_back = escape_jsx_string(params.back_name)
        escaped_result = escape_jsx_string(params.result_name)
        escaped_menu = escape_jsx_string(menu_cmd)

        jsx = f"""(function() {{
    var doc = app.activeDocument;

    // --- Locate both pathItems by name across all layers and groups ---
    function findPathItem(targetName) {{
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{
                return doc.layers[l].pathItems.getByName(targetName);
            }} catch(e) {{}}
            // Also search inside groups on each layer
            for (var g = 0; g < doc.layers[l].groupItems.length; g++) {{
                try {{
                    return doc.layers[l].groupItems[g].pathItems.getByName(targetName);
                }} catch(e) {{}}
            }}
        }}
        return null;
    }}

    var front = findPathItem("{escaped_front}");
    var back = findPathItem("{escaped_back}");

    if (!front) return JSON.stringify({{error: "Front item not found: {escaped_front}"}});
    if (!back) return JSON.stringify({{error: "Back item not found: {escaped_back}"}});

    // --- Deselect everything, then select the two operands ---
    doc.selection = null;
    back.selected = true;
    front.selected = true;

    // --- Execute the Pathfinder menu command ---
    app.executeMenuCommand("{escaped_menu}");

    // --- Expand the live pathfinder effect into editable geometry ---
    app.executeMenuCommand("expandStyle");

    // --- The result is the current selection ---
    var sel = doc.selection;
    if (!sel || sel.length === 0) {{
        return JSON.stringify({{error: "Pathfinder produced no selection — operation may have failed."}});
    }}

    // Count total paths in the result (may be a group after divide)
    var resultItem = sel[0];
    var pathCount = 0;
    var bounds = null;

    if (resultItem.typename === "GroupItem") {{
        // Dive into the group to count paths
        pathCount = resultItem.pathItems.length;
        bounds = resultItem.geometricBounds;
        resultItem.name = "{escaped_result}";
    }} else if (resultItem.typename === "PathItem") {{
        pathCount = 1;
        bounds = resultItem.geometricBounds;
        resultItem.name = "{escaped_result}";
    }} else if (resultItem.typename === "CompoundPathItem") {{
        pathCount = resultItem.pathItems.length;
        bounds = resultItem.geometricBounds;
        resultItem.name = "{escaped_result}";
    }} else {{
        // Unexpected type — still name it and report
        resultItem.name = "{escaped_result}";
        pathCount = 1;
        bounds = resultItem.geometricBounds;
    }}

    // Deselect after naming
    doc.selection = null;

    return JSON.stringify({{
        result_name: "{escaped_result}",
        operation: "{params.operation}",
        path_count: pathCount,
        bounds: bounds ? [
            Math.round(bounds[0] * 100) / 100,
            Math.round(bounds[1] * 100) / 100,
            Math.round(bounds[2] * 100) / 100,
            Math.round(bounds[3] * 100) / 100
        ] : null
    }});
}})();"""

        # Pathfinder menu commands + expandStyle can be slow — use extended timeout
        result = await _async_run_jsx("illustrator", jsx, timeout=300)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        return result["stdout"]
