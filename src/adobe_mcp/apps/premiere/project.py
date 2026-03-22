"""Premiere Pro project operations — new, open, save, close, get info."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrProjectInput


def register(mcp):
    """Register the adobe_pr_project tool."""

    @mcp.tool(
        name="adobe_pr_project",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_project(params: PrProjectInput) -> str:
        """Premiere Pro project operations — new, open, save, close, get info."""
        actions = {
            "save": 'app.project.save(); "Project saved";',
            "get_info": 'JSON.stringify({ name: app.project.name, path: app.project.path, sequences: app.project.sequences.numSequences });',
            "close": 'app.project.closeDocument(); "Project closed";',
        }
        if params.action == "open" and params.file_path:
            safe_path = params.file_path.replace(chr(92), "/")
            jsx = f'app.openDocument("{safe_path}"); "Project opened";'
        elif params.action == "save_as" and params.file_path:
            safe_path = params.file_path.replace(chr(92), "/")
            jsx = f'app.project.saveAs("{safe_path}"); "Saved as";'
        else:
            jsx = actions.get(params.action, f'"Unknown project action: {params.action}"')
        result = await _async_run_jsx("premierepro", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
