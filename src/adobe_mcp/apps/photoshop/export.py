"""Export the active Photoshop document to PNG, JPEG, PSD, TIFF, PDF, etc."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.photoshop.models import PsExportInput


def register(mcp):
    """Register the adobe_ps_export tool."""

    @mcp.tool(
        name="adobe_ps_export",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_ps_export(params: PsExportInput) -> str:
        """Export the active Photoshop document to PNG, JPEG, PSD, TIFF, PDF, etc."""
        path = params.file_path.replace("\\", "\\\\")
        fmt = params.format.value

        if fmt == "png":
            jsx = f"""
var opts = new PNGSaveOptions();
opts.interlaced = false; opts.compression = 6;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PNG";
"""
        elif fmt == "jpeg":
            jsx = f"""
var opts = new JPEGSaveOptions();
opts.quality = {params.quality}; opts.embedColorProfile = true;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported JPEG quality={params.quality}";
"""
        elif fmt == "tiff":
            jsx = f"""
var opts = new TiffSaveOptions();
opts.imageCompression = TIFFEncoding.TIFFLZW;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported TIFF";
"""
        elif fmt == "pdf":
            jsx = f"""
var opts = new PDFSaveOptions();
opts.compatibility = PDFCompatibility.PDF17;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PDF";
"""
        elif fmt == "psd":
            jsx = f"""
var opts = new PhotoshopSaveOptions();
opts.layers = true;
app.activeDocument.saveAs(new File("{path}"), opts, true, Extension.LOWERCASE);
"Exported PSD";
"""
        else:
            jsx = f'app.activeDocument.saveAs(new File("{path}")); "Exported";'

        result = await _async_run_jsx("photoshop", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
