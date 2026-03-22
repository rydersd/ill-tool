"""Create shapes in Illustrator — rectangles, ellipses, polygons, stars, lines."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiShapeInput


def register(mcp):
    """Register the adobe_ai_shapes tool."""

    @mcp.tool(
        name="adobe_ai_shapes",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_shapes(params: AiShapeInput) -> str:
        """Create shapes in Illustrator — rectangles, ellipses, polygons, stars, lines."""
        fill_setup = ""
        if params.fill_r is not None:
            fill_setup = f"""
var fillColor = new RGBColor();
fillColor.red = {params.fill_r}; fillColor.green = {params.fill_g}; fillColor.blue = {params.fill_b};
"""
        stroke_setup = f"""
var strokeColor = new RGBColor();
strokeColor.red = {params.stroke_r}; strokeColor.green = {params.stroke_g}; strokeColor.blue = {params.stroke_b};
"""
        shapes = {
            "rectangle": f'var shape = doc.pathItems.rectangle({params.y}, {params.x}, {params.width}, {params.height});',
            "ellipse": f'var shape = doc.pathItems.ellipse({params.y}, {params.x}, {params.width}, {params.height});',
            "polygon": f'var shape = doc.pathItems.polygon({params.x}, {params.y}, {(params.width or 100)/2}, {params.sides});',
            "star": f'var shape = doc.pathItems.star({params.x}, {params.y}, {(params.width or 100)/2}, {(params.width or 100)/4}, {params.points});',
            "line": f'var shape = doc.pathItems.add(); shape.setEntirePath([[{params.x},{params.y}],[{params.x+(params.width or 100)},{params.y+(params.height or 0)}]]);',
        }
        shape_code = shapes.get(params.shape, f'"Unknown shape: {params.shape}"')

        jsx = f"""
var doc = app.activeDocument;
{fill_setup}
{stroke_setup}
{shape_code}
{"shape.fillColor = fillColor;" if params.fill_r is not None else "shape.filled = false;"}
shape.strokeColor = strokeColor;
shape.strokeWidth = {params.stroke_width};
"Created {params.shape}";
"""
        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
