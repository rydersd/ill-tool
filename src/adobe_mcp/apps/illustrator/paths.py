"""Create and manipulate paths in Illustrator."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiPathInput


def register(mcp):
    """Register the adobe_ai_path tool."""

    @mcp.tool(
        name="adobe_ai_path",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_path(params: AiPathInput) -> str:
        """Create and manipulate paths in Illustrator."""
        if params.action == "create" and params.points:
            jsx = f"""
var doc = app.activeDocument;
var path = doc.pathItems.add();
var pts = {params.points};
path.setEntirePath(pts);
path.closed = {str(params.closed).lower()};
{"var fc = new RGBColor(); fc.red=" + str(params.fill_r) + "; fc.green=" + str(params.fill_g) + "; fc.blue=" + str(params.fill_b) + "; path.fillColor = fc;" if params.fill_r is not None else "path.filled = false;"}
path.strokeWidth = {params.stroke_width};
"Path created with " + pts.length + " points";
"""
        else:
            jsx = f'"Action {params.action} requires direct JSX — use adobe_run_jsx for complex path operations";'
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
