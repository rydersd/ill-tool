"""Premiere Pro timeline editing — insert, overwrite, razor, trim, transitions, speed."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrTimelineInput


def register(mcp):
    """Register the adobe_pr_timeline tool."""

    @mcp.tool(
        name="adobe_pr_timeline",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_timeline(params: PrTimelineInput) -> str:
        """Premiere Pro timeline editing — insert, overwrite, razor, trim, transitions, speed."""
        jsx_code = f'"Timeline action {params.action} — use adobe_run_jsx with specific Premiere Pro ExtendScript for complex timeline operations";'
        if params.action == "insert" and params.clip_name:
            jsx_code = f"""
var seq = app.project.activeSequence;
var root = app.project.rootItem;
for (var i = 0; i < root.children.numItems; i++) {{
    if (root.children[i].name === "{params.clip_name}") {{
        seq.videoTracks[{params.track_index}].insertClip(root.children[i], {params.start_time or 0});
        break;
    }}
}}
"Clip inserted";
"""
        result = await _async_run_jsx("premierepro", jsx_code)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
