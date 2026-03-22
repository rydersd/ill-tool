"""InDesign tools — 3 tools for documents, text, and images."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.indesign.models import (
    IdDocInput,
    IdImageInput,
    IdTextInput,
)


def register_indesign_tools(mcp):
    """Register 3 InDesign tools."""

    @mcp.tool(
        name="adobe_id_document",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_id_document(params: IdDocInput) -> str:
        """InDesign document operations — new, open, save, export PDF/EPUB/HTML, package, preflight."""
        if params.action == "new":
            w = params.width or 612
            h = params.height or 792
            jsx = f"""
var doc = app.documents.add();
doc.documentPreferences.pageWidth = "{w}pt";
doc.documentPreferences.pageHeight = "{h}pt";
doc.documentPreferences.pagesPerDocument = {params.pages or 1};
JSON.stringify({{ name: doc.name, pages: doc.pages.length, width: "{w}pt", height: "{h}pt" }});
"""
        elif params.action == "export_pdf" and params.file_path:
            path = params.file_path.replace("\\", "/")
            preset = params.preset or "[High Quality Print]"
            jsx = f"""
var doc = app.activeDocument;
var preset = app.pdfExportPresets.item("{preset}");
doc.exportFile(ExportFormat.PDF_TYPE, new File("{path}"), false, preset);
"PDF exported";
"""
        elif params.action == "export_epub" and params.file_path:
            path = params.file_path.replace("\\", "/")
            jsx = f'app.activeDocument.exportFile(ExportFormat.EPUB, new File("{path}")); "EPUB exported";'
        elif params.action == "package" and params.file_path:
            path = params.file_path.replace("\\", "/")
            jsx = f'app.activeDocument.packageForPrint("{path}", true, true, true, true, true, true); "Packaged";'
        elif params.action == "preflight":
            jsx = """
var doc = app.activeDocument;
var profile = app.preflightProfiles[0];
var process = app.preflightProcesses.add(doc, profile);
process.waitForProcess();
var results = process.processResults;
JSON.stringify({ results: results });
"""
        elif params.action == "get_info":
            jsx = """
var d = app.activeDocument;
JSON.stringify({
    name: d.name, pages: d.pages.length, spreads: d.spreads.length,
    stories: d.stories.length, layers: d.layers.length,
    masterSpreads: d.masterSpreads.length, textFrames: d.textFrames.length
}, null, 2);
"""
        else:
            jsx = f'"Use adobe_open_file/adobe_save_file for basic operations, or adobe_run_jsx for: {params.action}";'
        result = await _async_run_jsx("indesign", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"

    @mcp.tool(
        name="adobe_id_text",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_id_text(params: IdTextInput) -> str:
        """InDesign text operations — create frames, insert text, format, find/replace, styles."""
        if params.action == "create_frame":
            # Bug #4 fix: define escaped_text before using it in the JSX template
            escaped_text = escape_jsx_string(params.text or "")
            jsx = f"""
var doc = app.activeDocument;
var page = doc.pages[{params.page_index or 0}];
var tf = page.textFrames.add();
tf.geometricBounds = ["{params.y or 0}pt", "{params.x or 0}pt", "{(params.y or 0) + (params.height or 200)}pt", "{(params.x or 0) + (params.width or 300)}pt"];
if ("{escaped_text}") tf.contents = "{escaped_text}";
"Text frame created";
"""
        elif params.action == "insert_text" and params.text:
            escaped_text = escape_jsx_string(params.text)
            jsx = f"""
var doc = app.activeDocument;
var tf = doc.textFrames[0];
tf.insertionPoints[-1].contents = "{escaped_text}";
"Text inserted";
"""
        elif params.action == "find_replace" and params.find_what:
            jsx = f"""
app.findTextPreferences = NothingEnum.NOTHING;
app.changeTextPreferences = NothingEnum.NOTHING;
app.findTextPreferences.findWhat = "{params.find_what}";
app.changeTextPreferences.changeTo = "{params.replace_with or ""}";
var found = app.activeDocument.changeText();
"Replaced " + found.length + " instances";
"""
        elif params.action == "list_styles":
            jsx = """
var doc = app.activeDocument;
var pStyles = [], cStyles = [];
for (var i = 0; i < doc.paragraphStyles.length; i++) pStyles.push(doc.paragraphStyles[i].name);
for (var i = 0; i < doc.characterStyles.length; i++) cStyles.push(doc.characterStyles[i].name);
JSON.stringify({ paragraphStyles: pStyles, characterStyles: cStyles }, null, 2);
"""
        elif params.action == "apply_grep" and params.find_what:
            jsx = f"""
app.findGrepPreferences = NothingEnum.NOTHING;
app.changeGrepPreferences = NothingEnum.NOTHING;
app.findGrepPreferences.findWhat = "{params.find_what}";
app.changeGrepPreferences.changeTo = "{params.replace_with or ""}";
var found = app.activeDocument.changeGrep();
"GREP replaced " + found.length + " instances";
"""
        else:
            jsx = f'"Use adobe_run_jsx for advanced text operations: {params.action}";'
        result = await _async_run_jsx("indesign", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"

    @mcp.tool(
        name="adobe_id_image",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_id_image(params: IdImageInput) -> str:
        """Place images in InDesign documents."""
        path = params.file_path.replace("\\", "/")
        jsx = f"""
var doc = app.activeDocument;
var page = doc.pages[{params.page_index or 0}];
var frame = page.rectangles.add();
frame.geometricBounds = ["{params.y}pt", "{params.x}pt", "{params.y + (params.height or 300)}pt", "{params.x + (params.width or 400)}pt"];
frame.place(new File("{path}"));
{"frame.fit(FitOptions.PROPORTIONALLY); " if params.fit == "proportionally" else ""}
{"frame.fit(FitOptions.FILL_PROPORTIONALLY); " if params.fit == "fill" else ""}
{"frame.fit(FitOptions.FRAME_TO_CONTENT); " if params.fit == "frame" else ""}
{"frame.fit(FitOptions.CENTER_CONTENT); " if params.fit == "center" else ""}
"Image placed";
"""
        result = await _async_run_jsx("indesign", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
