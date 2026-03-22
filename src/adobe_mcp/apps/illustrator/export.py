"""Export Illustrator document to SVG, PNG, PDF, EPS, JPG."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.illustrator.models import AiExportInput


def register(mcp):
    """Register the adobe_ai_export tool."""

    @mcp.tool(
        name="adobe_ai_export",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ai_export(params: AiExportInput) -> str:
        """Export Illustrator document to SVG, PNG, PDF, EPS, JPG."""
        path = params.file_path.replace("\\", "\\\\")
        fmt = params.format.lower()
        if fmt == "svg":
            jsx = f"""
var opts = new ExportOptionsSVG();
app.activeDocument.exportFile(new File("{path}"), ExportType.SVG, opts);
"Exported SVG";
"""
        elif fmt == "png":
            jsx = f"""
var opts = new ExportOptionsPNG24();
opts.horizontalScale = {(params.scale or 1) * 100}; opts.verticalScale = {(params.scale or 1) * 100};
opts.transparency = true; opts.antiAliasing = true;
app.activeDocument.exportFile(new File("{path}"), ExportType.PNG24, opts);
"Exported PNG";
"""
        elif fmt == "pdf":
            jsx = f"""
var opts = new PDFSaveOptions();
app.activeDocument.saveAs(new File("{path}"), opts);
"Exported PDF";
"""
        elif fmt == "eps":
            jsx = f"""
var opts = new EPSSaveOptions();
app.activeDocument.saveAs(new File("{path}"), opts);
"Exported EPS";
"""
        elif fmt in ("jpg", "jpeg"):
            jsx = f"""
var opts = new ExportOptionsJPEG();
opts.qualitySetting = 100; opts.horizontalScale = {(params.scale or 1) * 100}; opts.verticalScale = {(params.scale or 1) * 100};
app.activeDocument.exportFile(new File("{path}"), ExportType.JPEG, opts);
"Exported JPEG";
"""
        else:
            jsx = f'app.activeDocument.saveAs(new File("{path}")); "Exported";'

        result = await _async_run_jsx("illustrator", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
