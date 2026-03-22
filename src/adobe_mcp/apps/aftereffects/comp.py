"""After Effects composition operations — create, list, duplicate, delete."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.aftereffects.models import AeCompInput


def register(mcp):
    """Register the adobe_ae_comp tool."""

    @mcp.tool(
        name="adobe_ae_comp",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ae_comp(params: AeCompInput) -> str:
        """After Effects composition operations — create, list, duplicate, delete."""
        if params.action == "create":
            jsx = f"""
var comp = app.project.items.addComp("{params.name or 'Comp 1'}", {params.width}, {params.height}, 1, {params.duration}, {params.framerate});
JSON.stringify({{ name: comp.name, width: comp.width, height: comp.height, duration: comp.duration, fps: comp.frameRate }});
"""
        elif params.action == "list":
            jsx = """
var comps = [];
for (var i = 1; i <= app.project.numItems; i++) {
    if (app.project.item(i) instanceof CompItem) {
        var c = app.project.item(i);
        comps.push({ name: c.name, width: c.width, height: c.height, duration: c.duration, fps: c.frameRate, layers: c.numLayers });
    }
}
JSON.stringify({ count: comps.length, comps: comps }, null, 2);
"""
        elif params.action == "get_info":
            jsx = """
var c = app.project.activeItem;
if (c && c instanceof CompItem) {
    var layers = [];
    for (var i = 1; i <= c.numLayers; i++) {
        var l = c.layer(i);
        var info = {
            index: i,
            name: l.name,
            enabled: l.enabled,
            inPoint: l.inPoint,
            outPoint: l.outPoint,
            startTime: l.startTime,
            stretch: l.stretch,
            shy: l.shy,
            locked: l.locked,
            label: l.label,
            hasParent: l.parent !== null
        };
        try { info.parentName = l.parent ? l.parent.name : null; } catch(e) { info.parentName = null; }
        try { info.isNull = (l instanceof ShapeLayer === false && l instanceof TextLayer === false && l instanceof AVLayer && l.nullLayer); } catch(e) {}
        layers.push(info);
    }
    JSON.stringify({ name: c.name, width: c.width, height: c.height, duration: c.duration,
        fps: c.frameRate, numLayers: c.numLayers, layers: layers }, null, 2);
} else { "No active composition"; }
"""
        elif params.action == "set_active" and params.name:
            jsx = f"""
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{params.name}") {{
        app.project.item(i).openInViewer();
        break;
    }}
}}
"Set active: {params.name}";
"""
        else:
            jsx = f'"Unknown comp action: {params.action}"'
        result = await _async_run_jsx("aftereffects", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
