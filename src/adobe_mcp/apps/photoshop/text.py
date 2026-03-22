"""Add or edit a text layer in Photoshop with font, size, color, and position."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.photoshop.models import PsTextInput


def register(mcp):
    """Register the adobe_ps_text tool."""

    @mcp.tool(
        name="adobe_ps_text",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_text(params: PsTextInput) -> str:
        """Add or edit a text layer in Photoshop with font, size, color, and position."""
        if params.action == "edit" and params.layer_name:
            escaped_name = escape_jsx_string(params.layer_name)
            # Build JSX that only sets properties that are provided
            jsx_parts = [f'var l = app.activeDocument.artLayers.getByName("{escaped_name}");']
            jsx_parts.append('var txt = l.textItem;')
            if params.text is not None:
                escaped_text = escape_jsx_string(params.text)
                jsx_parts.append(f'txt.contents = "{escaped_text}";')
            if params.font:
                jsx_parts.append(f'txt.font = "{params.font}";')
            if params.size:
                jsx_parts.append(f'txt.size = UnitValue({params.size}, "pt");')
            if params.color_r is not None:
                jsx_parts.append(f'var c = new SolidColor(); c.rgb.red = {params.color_r}; c.rgb.green = {params.color_g}; c.rgb.blue = {params.color_b}; txt.color = c;')
            jsx_parts.append('JSON.stringify({ name: l.name, contents: txt.contents });')
            jsx = "\n".join(jsx_parts)
        else:
            # Create action — text is required
            if not params.text:
                return "Error: 'text' is required for create action"
            escaped_text = escape_jsx_string(params.text)
            jsx = f"""
var doc = app.activeDocument;
var layer = doc.artLayers.add();
layer.kind = LayerKind.TEXT;
var txt = layer.textItem;
txt.contents = "{escaped_text}";
txt.position = [UnitValue({params.x}, 'px'), UnitValue({params.y}, 'px')];
txt.font = "{params.font}";
txt.size = UnitValue({params.size}, 'pt');
var c = new SolidColor();
c.rgb.red = {params.color_r}; c.rgb.green = {params.color_g}; c.rgb.blue = {params.color_b};
txt.color = c;
txt.antiAliasMethod = AntiAlias.{params.anti_alias};
txt.justification = Justification.{params.justification};
layer.name;
"""
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
