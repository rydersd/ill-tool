"""Create a new Illustrator document."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiNewDocInput


def register(mcp):
    """Register the adobe_ai_new_document tool."""

    @mcp.tool(
        name="adobe_ai_new_document",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_new_document(params: AiNewDocInput) -> str:
        """Create a new Illustrator document."""
        color = "DocumentColorSpace.RGB" if params.color_mode == "RGB" else "DocumentColorSpace.CMYK"
        jsx = f"""
var preset = new DocumentPreset();
preset.width = {params.width}; preset.height = {params.height};
preset.colorMode = {color}; preset.numArtboards = {params.artboard_count};
preset.title = "{params.name}";
var doc = app.documents.addDocument("{params.color_mode}", preset);
JSON.stringify({{ name: doc.name, width: doc.width, height: doc.height, artboards: doc.artboards.length }});
"""
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
