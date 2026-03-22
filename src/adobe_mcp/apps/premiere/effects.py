"""Apply and manage effects in Premiere Pro."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrEffectInput


def register(mcp):
    """Register the adobe_pr_effects tool."""

    @mcp.tool(
        name="adobe_pr_effects",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_effects(params: PrEffectInput) -> str:
        """Apply and manage effects in Premiere Pro."""
        jsx = f'"Effect action {params.action} — use adobe_run_jsx for Premiere Pro effect operations. Effects API varies by version.";'
        if params.action == "list":
            jsx = """
var effects = [];
var seq = app.project.activeSequence;
var clip = seq.videoTracks[0].clips[0];
if (clip) {
    for (var i = 0; i < clip.components.numItems; i++) {
        effects.push({ name: clip.components[i].displayName, matchName: clip.components[i].matchName });
    }
}
JSON.stringify({ count: effects.length, effects: effects }, null, 2);
"""
        result = await _async_run_jsx("premierepro", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
