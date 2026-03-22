"""Smart Object operations — convert, rasterize, replace contents."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsSmartObjectInput


def register(mcp):
    """Register the adobe_ps_smart_object tool."""

    @mcp.tool(
        name="adobe_ps_smart_object",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_smart_object(params: PsSmartObjectInput) -> str:
        """Smart Object operations — convert, rasterize, replace contents."""
        if params.layer_name:
            prefix = f'app.activeDocument.activeLayer = app.activeDocument.artLayers.getByName("{params.layer_name}");'
        else:
            prefix = ""

        # Bug #3 fix: compute safe_path in Python before JSX string interpolation
        safe_path = (params.file_path or "").replace("\\", "/")

        actions = {
            "convert_to": f'{prefix} var idnewPlacedLayer = stringIDToTypeID("newPlacedLayer"); executeAction(idnewPlacedLayer, undefined, DialogModes.NO); "Converted to Smart Object";',
            "rasterize": f'{prefix} app.activeDocument.activeLayer.rasterize(RasterizeType.ENTIRELAYER); "Rasterized";',
            "replace_contents": f"""{prefix}
var idplacedLayerReplaceContents = stringIDToTypeID("placedLayerReplaceContents");
var desc = new ActionDescriptor();
desc.putPath(charIDToTypeID("null"), new File("{safe_path}"));
executeAction(idplacedLayerReplaceContents, desc, DialogModes.NO);
"Replaced contents";""",
        }
        jsx = actions.get(params.action, f'"Unknown smart object action: {params.action}"')
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
