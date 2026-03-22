"""After Effects layer operations — add solid, text, shape, null, adjustment, camera, light, media; manage layers."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeLayerInput


def register(mcp):
    """Register the adobe_ae_layer tool."""

    @mcp.tool(
        name="adobe_ae_layer",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_layer(params: AeLayerInput) -> str:
        """After Effects layer operations — add solid, text, shape, null, adjustment, camera, light, media; manage layers."""
        comp_sel = ae_comp_selector(params.comp_name)

        if params.action == "add_solid":
            jsx = f"""
{comp_sel}
var layer = comp.layers.addSolid([{params.color_r}/255, {params.color_g}/255, {params.color_b}/255], "{params.new_name or 'Solid'}", {params.width or 'comp.width'}, {params.height or 'comp.height'}, 1);
layer.name;
"""
        elif params.action == "add_text":
            escaped_ae_text = (params.text or "Text").replace(chr(34), chr(92) + chr(34))
            jsx = f"""
{comp_sel}
var layer = comp.layers.addText("{escaped_ae_text}");
layer.name = "{params.new_name or params.text or 'Text'}";
layer.name;
"""
        elif params.action == "add_null":
            jsx = f'{comp_sel} var layer = comp.layers.addNull(); layer.name = "{params.new_name or "Null"}"; layer.name;'
        elif params.action == "add_adjustment":
            jsx = f'{comp_sel} var layer = comp.layers.addSolid([1,1,1], "{params.new_name or "Adjustment"}", comp.width, comp.height, 1); layer.adjustmentLayer = true; layer.name;'
        elif params.action == "add_camera":
            jsx = f'{comp_sel} var layer = comp.layers.addCamera("{params.new_name or "Camera"}", [comp.width/2, comp.height/2]); layer.name;'
        elif params.action == "add_light":
            jsx = f'{comp_sel} var layer = comp.layers.addLight("{params.new_name or "Light"}", [comp.width/2, comp.height/2]); layer.name;'
        elif params.action == "add_media" and params.file_path:
            jsx = f"""
{comp_sel}
var item = app.project.importFile(new ImportOptions(new File("{params.file_path.replace(chr(92), "/")}")));
var layer = comp.layers.add(item);
layer.name;
"""
        elif params.action == "add_shape":
            jsx = f'{comp_sel} var layer = comp.layers.addShape(); layer.name = "{params.new_name or "Shape"}"; layer.name;'
        elif params.action == "delete" and params.layer_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").remove(); "Deleted";'
        elif params.action == "rename" and params.layer_name and params.new_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").name = "{params.new_name}"; "Renamed";'
        elif params.action == "duplicate" and params.layer_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").duplicate(); "Duplicated";'
        elif params.action in ("enable", "disable") and params.layer_name:
            jsx = f'{comp_sel} comp.layer("{params.layer_name}").enabled = {"true" if params.action == "enable" else "false"}; "{params.action}d";'
        elif params.action == "solo" and params.layer_name:
            jsx = f'{comp_sel} var l = comp.layer("{params.layer_name}"); l.solo = !l.solo; "Solo toggled";'
        elif params.action == "set_parent" and params.layer_name:
            if params.parent_name:
                jsx = f'{comp_sel} var l = comp.layer("{params.layer_name}"); l.parent = comp.layer("{params.parent_name}"); "Parent set to {params.parent_name}";'
            else:
                # Clear parent
                jsx = f'{comp_sel} var l = comp.layer("{params.layer_name}"); l.parent = null; "Parent cleared";'
        elif params.action == "precompose" and params.layer_indices:
            indices = [int(x.strip()) for x in params.layer_indices.split(",")]
            indices_jsx = "[" + ",".join(str(i) for i in indices) + "]"
            precomp_name = escape_jsx_string(params.precomp_name or "Precomp")
            jsx = f'{comp_sel} comp.layers.precompose({indices_jsx}, "{precomp_name}", true); "Precomposed into {precomp_name}";'
        elif params.action == "get_info" and params.layer_name:
            jsx = f"""
{comp_sel}
var l = comp.layer("{params.layer_name}");
var info = {{
    name: l.name,
    index: l.index,
    enabled: l.enabled,
    inPoint: l.inPoint,
    outPoint: l.outPoint,
    startTime: l.startTime,
    stretch: l.stretch,
    shy: l.shy,
    locked: l.locked,
    label: l.label,
    hasParent: l.parent !== null,
    solo: l.solo
}};
try {{ info.parentName = l.parent ? l.parent.name : null; }} catch(e) {{ info.parentName = null; }}
try {{
    var pos = l.property("Transform").property("Position").value;
    var scale = l.property("Transform").property("Scale").value;
    var rot = l.property("Transform").property("Rotation").value;
    var opa = l.property("Transform").property("Opacity").value;
    info.transform = {{ position: pos, scale: scale, rotation: rot, opacity: opa }};
}} catch(e) {{}}
try {{
    var fx = l.property("Effects");
    if (fx) {{
        var effects = [];
        for (var i = 1; i <= fx.numProperties; i++) {{
            effects.push({{ name: fx.property(i).name, enabled: fx.property(i).enabled }});
        }}
        info.effects = effects;
    }}
}} catch(e) {{}}
JSON.stringify(info, null, 2);
"""
        else:
            jsx = f'"Use adobe_run_jsx for advanced AE layer operations: {params.action}";'

        result = await _async_run_jsx("aftereffects", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
