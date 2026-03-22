"""Create a new Photoshop document with specified dimensions, resolution, color mode."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsNewDocInput


def register(mcp):
    """Register the adobe_ps_new_document tool."""

    @mcp.tool(
        name="adobe_ps_new_document",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_new_document(params: PsNewDocInput) -> str:
        """Create a new Photoshop document with specified dimensions, resolution, color mode."""
        color_map = {"RGB": "NewDocumentMode.RGB", "CMYK": "NewDocumentMode.CMYK", "LAB": "NewDocumentMode.LAB", "GRAYSCALE": "NewDocumentMode.GRAYSCALE"}
        bg_map = {"WHITE": "DocumentFill.WHITE", "BLACK": "DocumentFill.BLACK", "TRANSPARENT": "DocumentFill.TRANSPARENT"}
        color_mode = color_map.get(params.color_mode.value, "NewDocumentMode.RGB")
        bg = bg_map.get(params.background.upper(), "DocumentFill.WHITE")
        bit = {8: "BitsPerChannelType.EIGHT", 16: "BitsPerChannelType.SIXTEEN", 32: "BitsPerChannelType.THIRTYTWO"}.get(params.bit_depth, "BitsPerChannelType.EIGHT")

        jsx = f"""
var doc = app.documents.add(
    UnitValue({params.width}, 'px'), UnitValue({params.height}, 'px'),
    {params.resolution}, '{params.name}', {color_mode}, {bg}, 1, {bit}
);
JSON.stringify({{ name: doc.name, width: doc.width.value, height: doc.height.value, resolution: doc.resolution }});
"""
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
