"""Style transfer — copy visual style between pathItems or apply a JSON style spec."""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiStyleTransferInput


def register(mcp):
    """Register the adobe_ai_style_transfer tool."""

    @mcp.tool(
        name="adobe_ai_style_transfer",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_style_transfer(params: AiStyleTransferInput) -> str:
        """Copy visual style (stroke, fill, opacity, dash patterns) from one pathItem to others, or apply a style JSON spec."""

        if params.action == "extract":
            # Extract complete visual style from a named pathItem
            if not params.source_name:
                return "Error: extract action requires 'source_name'"

            escaped_source = escape_jsx_string(params.source_name)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var item = null;
    for (var l = 0; l < doc.layers.length; l++) {{
        try {{ item = doc.layers[l].pathItems.getByName("{escaped_source}"); break; }} catch(e) {{}}
    }}
    if (!item) return JSON.stringify({{error: "Item not found: {escaped_source}"}});

    var style = {{
        filled: item.filled,
        stroked: item.stroked,
        opacity: item.opacity
    }};

    if (item.filled && item.fillColor) {{
        if (item.fillColor.typename === "RGBColor") {{
            style.fill = {{r: item.fillColor.red, g: item.fillColor.green, b: item.fillColor.blue}};
        }} else if (item.fillColor.typename === "GrayColor") {{
            style.fill = {{gray: item.fillColor.gray}};
        }} else if (item.fillColor.typename === "NoColor") {{
            style.fill = null;
        }}
    }}

    if (item.stroked && item.strokeColor) {{
        if (item.strokeColor.typename === "RGBColor") {{
            style.stroke = {{r: item.strokeColor.red, g: item.strokeColor.green, b: item.strokeColor.blue}};
        }} else if (item.strokeColor.typename === "GrayColor") {{
            style.stroke = {{gray: item.strokeColor.gray}};
        }}
        style.strokeWidth = item.strokeWidth;
        style.strokeDashes = item.strokeDashes || [];
        style.strokeCap = item.strokeCap.toString();
        style.strokeJoin = item.strokeJoin.toString();
        style.miterLimit = item.miterLimit;
    }}

    return JSON.stringify(style);
}})();"""

        elif params.action == "transfer":
            # Extract style from source, apply to all targets
            if not params.source_name:
                return "Error: transfer action requires 'source_name'"
            if not params.target_names:
                return "Error: transfer action requires 'target_names'"

            escaped_source = escape_jsx_string(params.source_name)
            escaped_targets = escape_jsx_string(params.target_names)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var source = null;
    for (var l = 0; l < doc.layers.length; l++) {{
        try {{ source = doc.layers[l].pathItems.getByName("{escaped_source}"); break; }} catch(e) {{}}
    }}
    if (!source) return JSON.stringify({{error: "Source not found: {escaped_source}"}});

    var targets = "{escaped_targets}".split(",");
    var applied = 0;
    var errors = [];

    for (var t = 0; t < targets.length; t++) {{
        var targetName = targets[t].replace(/^\\s+|\\s+$/g, '');
        var target = null;
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{ target = doc.layers[l].pathItems.getByName(targetName); break; }} catch(e) {{}}
        }}
        if (!target) {{ errors.push(targetName); continue; }}

        // Copy fill
        target.filled = source.filled;
        if (source.filled) target.fillColor = source.fillColor;

        // Copy stroke
        target.stroked = source.stroked;
        if (source.stroked) {{
            target.strokeColor = source.strokeColor;
            target.strokeWidth = source.strokeWidth;
            target.strokeDashes = source.strokeDashes;
            target.strokeCap = source.strokeCap;
            target.strokeJoin = source.strokeJoin;
            target.miterLimit = source.miterLimit;
        }}

        // Copy opacity
        target.opacity = source.opacity;
        applied++;
    }}

    return JSON.stringify({{applied: applied, errors: errors}});
}})();"""

        elif params.action == "apply":
            # Apply a JSON style spec to target items
            if not params.style_json:
                return "Error: apply action requires 'style_json'"
            if not params.target_names:
                return "Error: apply action requires 'target_names'"

            # Validate JSON before sending to JSX
            try:
                json.loads(params.style_json)
            except json.JSONDecodeError as e:
                return f"Error: invalid style_json — {e}"

            escaped_targets = escape_jsx_string(params.target_names)
            # Embed the raw JSON directly — it's valid JS object literal syntax
            style_json_literal = params.style_json
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var style = {style_json_literal};
    var targets = "{escaped_targets}".split(",");
    var applied = 0;
    var errors = [];

    for (var t = 0; t < targets.length; t++) {{
        var targetName = targets[t].replace(/^\\s+|\\s+$/g, '');
        var target = null;
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{ target = doc.layers[l].pathItems.getByName(targetName); break; }} catch(e) {{}}
        }}
        if (!target) {{ errors.push(targetName); continue; }}

        // Apply fill
        if (style.fill !== undefined) {{
            if (style.fill === null || style.filled === false) {{
                target.filled = false;
            }} else {{
                target.filled = true;
                if (style.fill.r !== undefined) {{
                    var fc = new RGBColor();
                    fc.red = style.fill.r;
                    fc.green = style.fill.g;
                    fc.blue = style.fill.b;
                    target.fillColor = fc;
                }} else if (style.fill.gray !== undefined) {{
                    var gc = new GrayColor();
                    gc.gray = style.fill.gray;
                    target.fillColor = gc;
                }}
            }}
        }}

        // Apply stroke
        if (style.stroke !== undefined) {{
            if (style.stroke === null || style.stroked === false) {{
                target.stroked = false;
            }} else {{
                target.stroked = true;
                if (style.stroke.r !== undefined) {{
                    var sc = new RGBColor();
                    sc.red = style.stroke.r;
                    sc.green = style.stroke.g;
                    sc.blue = style.stroke.b;
                    target.strokeColor = sc;
                }} else if (style.stroke.gray !== undefined) {{
                    var sgc = new GrayColor();
                    sgc.gray = style.stroke.gray;
                    target.strokeColor = sgc;
                }}
            }}
        }}

        // Apply stroke properties
        if (style.strokeWidth !== undefined) {{
            target.stroked = true;
            target.strokeWidth = style.strokeWidth;
        }}
        if (style.strokeDashes !== undefined) {{
            target.strokeDashes = style.strokeDashes;
        }}
        if (style.strokeCap !== undefined) {{
            target.strokeCap = StrokeCap[style.strokeCap] || target.strokeCap;
        }}
        if (style.strokeJoin !== undefined) {{
            target.strokeJoin = StrokeJoin[style.strokeJoin] || target.strokeJoin;
        }}
        if (style.miterLimit !== undefined) {{
            target.miterLimit = style.miterLimit;
        }}

        // Apply opacity
        if (style.opacity !== undefined) {{
            target.opacity = style.opacity;
        }}

        applied++;
    }}

    return JSON.stringify({{applied: applied, errors: errors}});
}})();"""

        else:
            return f"Unknown style_transfer action: {params.action}. Use: extract, transfer, apply"

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
