"""Apply/manage effects on After Effects layers."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeEffectInput


def register(mcp):
    """Register the adobe_ae_effect tool."""

    @mcp.tool(
        name="adobe_ae_effect",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_effect(params: AeEffectInput) -> str:
        """Apply/manage effects on After Effects layers."""
        comp_sel = ae_comp_selector(params.comp_name)
        if params.action == "apply" and params.effect_name:
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var effect = layer.property("Effects").addProperty("{params.effect_name}");
effect.name;
"""
        elif params.action == "remove" and params.effect_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").property("Effects").property("{params.effect_name}").remove(); "Removed";'
        elif params.action == "list":
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var effects = [];
var fx = layer.property("Effects");
for (var i = 1; i <= fx.numProperties; i++) {{
    effects.push({{ name: fx.property(i).name, matchName: fx.property(i).matchName, enabled: fx.property(i).enabled }});
}}
JSON.stringify({{ count: effects.length, effects: effects }}, null, 2);
"""
        elif params.action in ("enable", "disable") and params.effect_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").property("Effects").property("{params.effect_name}").enabled = {"true" if params.action == "enable" else "false"}; "{params.action}d";'
        else:
            jsx = f'"Unknown effect action: {params.action}"'
        result = await _async_run_jsx("aftereffects", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
