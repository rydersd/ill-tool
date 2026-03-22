"""Export from Premiere Pro via AME or direct render."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrExportInput


def register(mcp):
    """Register the adobe_pr_export tool."""

    @mcp.tool(
        name="adobe_pr_export",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_export(params: PrExportInput) -> str:
        """Export from Premiere Pro via AME or direct render."""
        path = params.file_path.replace("\\", "/")
        if params.use_ame:
            jsx = f"""
var seq = app.project.activeSequence;
var outputFile = new File("{path}");
app.encoder.launchEncoder();
app.encoder.encodeSequence(seq, outputFile.fsName, "{params.preset}", 0, 1);
"Export queued in AME";
"""
        else:
            jsx = f"""
var seq = app.project.activeSequence;
seq.exportAsMediaDirect("{path}", "{params.preset}", 0);
"Direct export started";
"""
        result = await _async_run_jsx("premierepro", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
