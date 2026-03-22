"""Apply expressions to After Effects layer properties."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeExpressionInput


def register(mcp):
    """Register the adobe_ae_expression tool."""

    @mcp.tool(
        name="adobe_ae_expression",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_expression(params: AeExpressionInput) -> str:
        """Apply expressions to After Effects layer properties."""
        comp_sel = ae_comp_selector(params.comp_name)
        prop_path = ".".join([f'property("{p}")' for p in params.property_path.split(".")])
        expr = params.expression.replace('"', '\\"').replace("\n", "\\n")
        jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.expression = "{expr}";
"Expression applied";
"""
        result = await _async_run_jsx("aftereffects", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
