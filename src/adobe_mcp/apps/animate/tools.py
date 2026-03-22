"""Adobe Animate tools — 2 tools for documents and timeline."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.animate.models import (
    AnDocInput,
    AnTimelineInput,
)


def register_animate_tools(mcp):
    """Register 2 Animate tools."""

    @mcp.tool(
        name="adobe_an_document",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_an_document(params: AnDocInput) -> str:
        """Adobe Animate document operations — new, publish, test, export."""
        if params.action == "new":
            jsx = f"""
fl.createDocument("{params.doc_type or 'html5canvas'}");
var doc = fl.getDocumentDOM();
{"doc.width = " + str(params.width) + ";" if params.width else ""}
{"doc.height = " + str(params.height) + ";" if params.height else ""}
{"doc.frameRate = " + str(params.fps) + ";" if params.fps else ""}
JSON.stringify({{ name: doc.name, width: doc.width, height: doc.height, fps: doc.frameRate }});
"""
        elif params.action == "publish":
            jsx = 'fl.getDocumentDOM().publish(); "Published";'
        elif params.action == "test_movie":
            jsx = 'fl.getDocumentDOM().testMovie(); "Testing movie";'
        elif params.action == "get_info":
            jsx = """
var d = fl.getDocumentDOM();
var tl = d.getTimeline();
JSON.stringify({
    name: d.name, width: d.width, height: d.height, fps: d.frameRate,
    layers: tl.layerCount, frames: tl.frameCount, currentFrame: tl.currentFrame
});
"""
        elif params.action == "export_html5" and params.file_path:
            safe_path = params.file_path.replace(chr(92), "/")
            jsx = f'fl.getDocumentDOM().exportPublishProfile("{safe_path}"); "HTML5 exported";'
        elif params.action == "export_video" and params.file_path:
            safe_path = params.file_path.replace(chr(92), "/")
            jsx = f'fl.getDocumentDOM().exportVideo("{safe_path}"); "Video exported";'
        else:
            jsx = f'"Use adobe_open_file/adobe_save_file or adobe_run_jsx for: {params.action}";'
        result = await _async_run_jsx("animate", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"

    @mcp.tool(
        name="adobe_an_timeline",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_an_timeline(params: AnTimelineInput) -> str:
        """Adobe Animate timeline operations — frames, keyframes, tweens, layers."""
        tl = "fl.getDocumentDOM().getTimeline()"
        if params.action == "insert_keyframe":
            jsx = f'{tl}.insertKeyframe({params.frame or 0}); "Keyframe inserted";'
        elif params.action == "insert_blank_keyframe":
            jsx = f'{tl}.insertBlankKeyframe({params.frame or 0}); "Blank keyframe inserted";'
        elif params.action == "add_frame":
            jsx = f'{tl}.insertFrames({params.duration or 1}, true, {params.frame or 0}); "Frames added";'
        elif params.action == "remove_frame":
            jsx = f'{tl}.removeFrames({params.frame or 0}, {(params.frame or 0) + (params.duration or 1)}); "Frames removed";'
        elif params.action == "create_motion_tween":
            jsx = f'{tl}.createMotionTween({params.frame or 0}); "Motion tween created";'
        elif params.action == "add_layer":
            jsx = f'{tl}.addNewLayer("{params.layer_name or "Layer"}"); "Layer added";'
        elif params.action == "delete_layer":
            jsx = f'{tl}.deleteLayer(); "Layer deleted";'
        elif params.action == "rename_layer":
            jsx = f'{tl}.layers[{tl}.currentLayer].name = "{params.layer_name}"; "Layer renamed";'
        elif params.action == "set_frame_label":
            jsx = f'{tl}.layers[{tl}.currentLayer].frames[{params.frame or 0}].name = "{params.label}"; "Label set";'
        elif params.action == "goto_frame":
            jsx = f'{tl}.currentFrame = {params.frame or 0}; "Moved to frame {params.frame}";'
        else:
            jsx = f'"Use adobe_run_jsx for advanced Animate operations: {params.action}";'
        result = await _async_run_jsx("animate", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
