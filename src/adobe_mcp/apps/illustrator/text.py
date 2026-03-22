"""Add text in Illustrator."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiTextInput


def register(mcp):
    """Register the adobe_ai_text tool."""

    @mcp.tool(
        name="adobe_ai_text",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_text(params: AiTextInput) -> str:
        """Add text in Illustrator."""
        escaped_text = escape_jsx_string(params.text)
        jsx = f"""
var doc = app.activeDocument;
var tf = doc.textFrames.add();
tf.contents = "{escaped_text}";
tf.top = {params.y}; tf.left = {params.x};
var attr = tf.textRange.characterAttributes;
attr.size = {params.size};
try {{ attr.textFont = app.textFonts.getByName("{params.font}"); }} catch(e) {{}}
var c = new RGBColor(); c.red = {params.color_r}; c.green = {params.color_g}; c.blue = {params.color_b};
attr.fillColor = c;
JSON.stringify({{ name: tf.contents, x: tf.left, y: tf.top }});
"""
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
