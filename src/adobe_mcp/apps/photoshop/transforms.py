"""Transform operations — resize, rotate, flip, crop, trim."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsTransformInput


def register(mcp):
    """Register the adobe_ps_transform tool."""

    @mcp.tool(
        name="adobe_ps_transform",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_transform(params: PsTransformInput) -> str:
        """Transform operations — resize, rotate, flip, crop, trim."""
        resample_map = {
            "BICUBIC": "ResampleMethod.BICUBIC",
            "BILINEAR": "ResampleMethod.BILINEAR",
            "NEARESTNEIGHBOR": "ResampleMethod.NEARESTNEIGHBOR",
            "BICUBICSHARPER": "ResampleMethod.BICUBICSHARPER",
            "BICUBICSMOOTHER": "ResampleMethod.BICUBICSMOOTHER",
        }
        rs = resample_map.get(params.resample, "ResampleMethod.BICUBIC")

        actions = {
            "resize_image": f'app.activeDocument.resizeImage(UnitValue({params.width},"px"), UnitValue({params.height},"px"), {params.resolution or "app.activeDocument.resolution"}, {rs}); "Resized image";',
            "resize_canvas": f'app.activeDocument.resizeCanvas(UnitValue({params.width},"px"), UnitValue({params.height},"px")); "Resized canvas";',
            "rotate": f'app.activeDocument.rotateCanvas({params.angle or 0}); "Rotated {params.angle}\u00b0";',
            "flip_horizontal": 'app.activeDocument.flipCanvas(Direction.HORIZONTAL); "Flipped horizontal";',
            "flip_vertical": 'app.activeDocument.flipCanvas(Direction.VERTICAL); "Flipped vertical";',
            "crop": f'app.activeDocument.crop([{params.x or 0},{params.y or 0},{params.width or "app.activeDocument.width.value"},{params.height or "app.activeDocument.height.value"}]); "Cropped";',
            "trim": 'app.activeDocument.trim(TrimType.TRANSPARENT); "Trimmed";',
        }
        jsx = actions.get(params.action, f'"Unknown transform: {params.action}"')
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
