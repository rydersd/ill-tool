"""Premiere Pro sequence operations — create, list, get info, set active."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrSequenceInput


def register(mcp):
    """Register the adobe_pr_sequence tool."""

    @mcp.tool(
        name="adobe_pr_sequence",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_sequence(params: PrSequenceInput) -> str:
        """Premiere Pro sequence operations — create, list, get info, set active."""
        if params.action == "create":
            jsx = f'app.project.createNewSequence("{params.name or "New Sequence"}", "sequenceID"); "Sequence created";'
        elif params.action == "list":
            jsx = """
var seqs = [];
for (var i = 0; i < app.project.sequences.numSequences; i++) {
    var s = app.project.sequences[i];
    seqs.push({ name: s.name, id: s.sequenceID });
}
JSON.stringify({ count: seqs.length, sequences: seqs }, null, 2);
"""
        elif params.action == "get_info":
            jsx = """
var s = app.project.activeSequence;
JSON.stringify({
    name: s.name, id: s.sequenceID,
    videoTracks: s.videoTracks.numTracks, audioTracks: s.audioTracks.numTracks,
    inPoint: s.getInPoint(), outPoint: s.getOutPoint(),
    zeroPoint: s.zeroPoint, end: s.end
}, null, 2);
"""
        elif params.action == "set_active":
            jsx = f"""
for (var i = 0; i < app.project.sequences.numSequences; i++) {{
    if (app.project.sequences[i].name === "{params.name}") {{
        app.project.activeSequence = app.project.sequences[i];
        break;
    }}
}}
"Active sequence set to {params.name}";
"""
        else:
            jsx = f'"Unknown sequence action: {params.action}"'
        result = await _async_run_jsx("premierepro", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
