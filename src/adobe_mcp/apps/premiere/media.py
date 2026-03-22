"""Import and manage media in Premiere Pro."""

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.apps.premiere.models import PrMediaInput


def register(mcp):
    """Register the adobe_pr_media tool."""

    @mcp.tool(
        name="adobe_pr_media",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    async def adobe_pr_media(params: PrMediaInput) -> str:
        """Import and manage media in Premiere Pro."""
        if params.action == "import" and params.file_paths:
            jsx = f"""
var paths = {params.file_paths};
app.project.importFiles(paths);
"Imported " + paths.length + " files";
"""
        elif params.action == "import_folder" and params.folder_path:
            safe_path = params.folder_path.replace(chr(92), "/")
            jsx = f'app.project.importFiles(["{safe_path}"], true); "Folder imported";'
        elif params.action == "list_bin":
            jsx = """
var items = [];
var root = app.project.rootItem;
for (var i = 0; i < root.children.numItems; i++) {
    var item = root.children[i];
    items.push({ name: item.name, type: String(item.type), treePath: item.treePath });
}
JSON.stringify({ count: items.length, items: items }, null, 2);
"""
        elif params.action == "create_bin":
            jsx = f'app.project.rootItem.createBin("{params.bin_name}"); "Bin created";'
        else:
            jsx = f'"Action {params.action} — use adobe_run_jsx for complex media operations";'
        result = await _async_run_jsx("premierepro", jsx)
        return result["stdout"] if result["success"] else f"Error: {result['stderr']}"
