"""Create and modify selections in Photoshop."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsSelectionInput


def register(mcp):
    """Register the adobe_ps_selection tool."""

    @mcp.tool(
        name="adobe_ps_selection",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_selection(params: PsSelectionInput) -> str:
        """Create and modify selections in Photoshop."""
        actions = {
            "select_all": 'app.activeDocument.selection.selectAll(); "Selected all";',
            "deselect": 'app.activeDocument.selection.deselect(); "Deselected";',
            "inverse": 'app.activeDocument.selection.invert(); "Inverted selection";',
            "feather": f'app.activeDocument.selection.feather({params.feather or 5}); "Feathered";',
            "expand": f'app.activeDocument.selection.expand(UnitValue({params.width or 5}, "px")); "Expanded";',
            "contract": f'app.activeDocument.selection.contract(UnitValue({params.width or 5}, "px")); "Contracted";',
            "smooth": f'app.activeDocument.selection.smooth({params.width or 5}); "Smoothed";',
        }
        if params.action == "rect" and all(v is not None for v in [params.x, params.y, params.width, params.height]):
            x2, y2 = params.x + params.width, params.y + params.height
            jsx = f'var r = [[{params.x},{params.y}],[{x2},{params.y}],[{x2},{y2}],[{params.x},{y2}]]; app.activeDocument.selection.select(r, SelectionType.REPLACE, {params.feather}, false); "Rectangular selection created";'
        elif params.action == "ellipse" and all(v is not None for v in [params.x, params.y, params.width, params.height]):
            jsx = f'app.activeDocument.selection.selectEllipse([{params.x},{params.y},{params.x+params.width},{params.y+params.height}], SelectionType.REPLACE, {params.feather}, false); "Elliptical selection created";'
        else:
            jsx = actions.get(params.action, f'"Unknown selection action: {params.action}"')

        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
