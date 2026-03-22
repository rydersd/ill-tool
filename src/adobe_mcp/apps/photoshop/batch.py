"""Batch process files — open each file in input_folder, run JSX code, save to output_folder."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsBatchInput


def register(mcp):
    """Register the adobe_ps_batch tool."""

    @mcp.tool(
        name="adobe_ps_batch",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_batch(params: PsBatchInput) -> str:
        """Batch process files — open each file in input_folder, run JSX code, save to output_folder."""
        in_dir = params.input_folder.replace("\\", "\\\\")
        out_dir = params.output_folder.replace("\\", "\\\\")
        jsx = f"""
var inFolder = new Folder("{in_dir}");
var outFolder = new Folder("{out_dir}");
if (!outFolder.exists) outFolder.create();
var files = inFolder.getFiles("{params.file_filter}");
var processed = 0;
for (var i = 0; i < files.length; i++) {{
    try {{
        app.open(files[i]);
        {params.jsx_code}
        var outFile = new File(outFolder.fsName + "/" + files[i].name.replace(/\\.[^.]+$/, ".{params.format.value}"));
        app.activeDocument.saveAs(outFile);
        app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
        processed++;
    }} catch(e) {{ /* skip */ }}
}}
"Processed " + processed + " of " + files.length + " files";
"""
        result = await _async_run_jsx("photoshop", jsx, timeout=600)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
