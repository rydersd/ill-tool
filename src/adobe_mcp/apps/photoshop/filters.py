"""Apply filters to the active layer in Photoshop."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsFilterInput


def register(mcp):
    """Register the adobe_ps_filter tool."""

    @mcp.tool(
        name="adobe_ps_filter",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_filter(params: PsFilterInput) -> str:
        """Apply filters to the active layer in Photoshop."""
        amt = params.amount or 5
        filters = {
            "gaussianBlur": f'app.activeDocument.activeLayer.applyGaussianBlur({amt}); "Applied Gaussian Blur radius={amt}";',
            "unsharpMask": f'app.activeDocument.activeLayer.applyUnSharpMask({amt}, {params.threshold or 1}, 0); "Applied Unsharp Mask";',
            "motionBlur": f'app.activeDocument.activeLayer.applyMotionBlur({params.angle or 0}, {amt}); "Applied Motion Blur";',
            "radialBlur": f'app.activeDocument.activeLayer.applyRadialBlur({amt}, RadialBlurMethod.SPIN, RadialBlurQuality.GOOD); "Applied Radial Blur";',
            "smartSharpen": f'app.activeDocument.activeLayer.applySharpen(); "Applied Sharpen";',
            "noise": f'app.activeDocument.activeLayer.applyAddNoise({amt}, NoiseDistribution.GAUSSIAN, false); "Applied Noise";',
            "median": f'app.activeDocument.activeLayer.applyMedianNoise({amt}); "Applied Median";',
            "highPass": f'app.activeDocument.activeLayer.applyHighPass({amt}); "Applied High Pass";',
            "findEdges": 'app.activeDocument.activeLayer.applyStyleize(SmartBlurQuality.HIGH); "Applied Find Edges";',
        }
        jsx = filters.get(params.filter_name, f'"Unknown filter: {params.filter_name}"')
        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
