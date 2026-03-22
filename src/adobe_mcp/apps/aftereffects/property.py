"""Get or set After Effects layer properties, read/write keyframes."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AePropertyInput


def register(mcp):
    """Register the adobe_ae_property tool."""

    @mcp.tool(
        name="adobe_ae_property",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_property(params: AePropertyInput) -> str:
        """Get or set After Effects layer properties, read/write keyframes, with optional keyframing."""
        comp_sel = ae_comp_selector(params.comp_name)
        prop_path = ".".join([f'property("{p}")' for p in params.property_path.split(".")])

        if params.action == "get":
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
var info = {{ value: prop.value, numKeys: prop.numKeys }};
if (prop.numKeys > 0) {{
    info.keyframes = [];
    for (var i = 1; i <= prop.numKeys; i++) {{
        info.keyframes.push({{ index: i, time: prop.keyTime(i), value: prop.keyValue(i) }});
    }}
}}
JSON.stringify(info, null, 2);
"""
        elif params.action == "get_keyframes":
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
var kfs = [];
for (var i = 1; i <= prop.numKeys; i++) {{
    var kf = {{ index: i, time: prop.keyTime(i), value: prop.keyValue(i) }};
    try {{
        var easeIn = prop.keyInTemporalEase(i);
        var easeOut = prop.keyOutTemporalEase(i);
        kf.easeIn = [];
        kf.easeOut = [];
        for (var j = 0; j < easeIn.length; j++) {{
            kf.easeIn.push({{ speed: easeIn[j].speed, influence: easeIn[j].influence }});
            kf.easeOut.push({{ speed: easeOut[j].speed, influence: easeOut[j].influence }});
        }}
    }} catch(e) {{}}
    kfs.push(kf);
}}
JSON.stringify({{ numKeys: prop.numKeys, keyframes: kfs }}, null, 2);
"""
        elif params.action == "delete_keyframe" and params.key_index is not None:
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.removeKey({params.key_index});
"Keyframe {params.key_index} removed";
"""
        elif params.time is not None:
            # Set keyframe (existing behavior)
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.setValueAtTime({params.time}, {params.value});
"Keyframe set at t={params.time}";
"""
        else:
            # Set static value (existing behavior)
            jsx = f"""
{comp_sel}
var layer = comp.layer("{params.layer_name}");
var prop = layer.{prop_path};
prop.setValue({params.value});
"Property set";
"""
        result = await _async_run_jsx("aftereffects", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
