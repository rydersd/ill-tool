"""Run a pre-recorded Photoshop Action."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsActionInput


def register(mcp):
    """Register the adobe_ps_action tool."""

    @mcp.tool(
        name="adobe_ps_action",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_action(params: PsActionInput) -> str:
        """Run a pre-recorded Photoshop Action."""
        jsx = f'app.doAction("{params.action_name}", "{params.action_set}"); "Action executed";'
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
