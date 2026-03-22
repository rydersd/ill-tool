"""Add composition to After Effects render queue and start rendering."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeRenderInput


def register(mcp):
    """Register the adobe_ae_render tool."""

    @mcp.tool(
        name="adobe_ae_render",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_render(params: AeRenderInput) -> str:
        """Add composition to After Effects render queue and start rendering."""
        path = params.output_path.replace("\\", "/")
        comp_sel = ae_comp_selector(params.comp_name)
        jsx = f"""
{comp_sel}
var rq = app.project.renderQueue;
var item = rq.items.add(comp);
{"item.applyTemplate('" + params.template + "');" if params.template else ""}
var om = item.outputModule(1);
{"om.applyTemplate('" + params.output_module + "');" if params.output_module else ""}
om.file = new File("{path}");
rq.render();
"Render complete: {path}";
"""
        result = await _async_run_jsx("aftereffects", jsx, timeout=600)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
