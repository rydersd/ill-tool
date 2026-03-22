"""Apply color/tone adjustments in Photoshop — levels, curves, hue/sat, brightness/contrast, etc."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsAdjustmentInput


def register(mcp):
    """Register the adobe_ps_adjustment tool."""

    @mcp.tool(
        name="adobe_ps_adjustment",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_adjustment(params: PsAdjustmentInput) -> str:
        """Apply color/tone adjustments in Photoshop — levels, curves, hue/sat, brightness/contrast, etc."""
        adjustments = {
            "brightness_contrast": f'app.activeDocument.activeLayer.adjustBrightnessContrast({params.brightness or 0}, {params.contrast or 0}); "Applied B/C";',
            "hue_saturation": f'app.activeDocument.activeLayer.adjustColorBalance(undefined, undefined, undefined, undefined, {params.hue or 0}, {params.saturation or 0}, {params.lightness or 0}); "Applied Hue/Sat";',
            "auto_tone": 'app.activeDocument.autoLevels(); "Auto Tone applied";',
            "auto_contrast": 'app.activeDocument.autoContrast(); "Auto Contrast applied";',
            "auto_color": 'app.activeDocument.autoColor(); "Auto Color applied";',
            "invert": 'app.activeDocument.activeLayer.invert(); "Inverted";',
            "desaturate": 'app.activeDocument.activeLayer.desaturate(); "Desaturated";',
            "posterize": f'app.activeDocument.activeLayer.posterize({params.brightness or 4}); "Posterized";',
            "threshold": f'app.activeDocument.activeLayer.threshold({params.brightness or 128}); "Threshold applied";',
        }
        jsx = adjustments.get(params.adjustment, f'"Unknown adjustment: {params.adjustment}"')
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
