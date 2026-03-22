"""Adobe Media Encoder tools — 1 tool for queue management and encoding."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.media_encoder.models import AmeEncodeInput


def register_media_encoder_tools(mcp):
    """Register 1 Media Encoder tool."""

    @mcp.tool(
        name="adobe_ame_encode",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ame_encode(params: AmeEncodeInput) -> str:
        """Adobe Media Encoder — queue management and encoding."""
        if params.action == "add_to_queue" and params.source_path:
            src = params.source_path.replace("\\", "/")
            out = (params.output_path or "").replace("\\", "/")
            jsx = f"""
var enc = app;
enc.addItemToQueue("{src}", "{params.preset or "H.264 - Match Source - High bitrate"}", "{out}");
"Added to queue";
"""
        elif params.action == "start_queue":
            jsx = 'app.startBatch(); "Queue started";'
        elif params.action == "stop_queue":
            jsx = 'app.stopBatch(); "Queue stopped";'
        elif params.action == "get_status":
            jsx = 'JSON.stringify({ status: app.getBatchStatus(), items: app.getEncoderHost().numItems });'
        elif params.action == "list_presets":
            jsx = """
var presets = app.getPresetList();
JSON.stringify({ presets: presets });
"""
        else:
            jsx = f'"Unknown AME action: {params.action}"'
        result = await _async_run_jsx("mediaencoder", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
