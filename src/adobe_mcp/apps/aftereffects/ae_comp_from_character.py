"""Create an AE composition from a posable Illustrator character with separated layers.

Imports an Illustrator file as a composition (preserving AI layers), then maps
the layer structure to the character rig data so downstream tools can apply
puppet pins, keyframes, and expressions to the correct body part layers.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeCompFromCharacterInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _build_comp_from_character_jsx(
    ai_path: str,
    comp_name: str,
    width: int,
    height: int,
    fps: float,
    duration: float,
) -> str:
    """Build JSX to import an AI file as a layered AE composition.

    Uses ImportAsType.COMP so each Illustrator layer becomes a separate
    AE layer in the resulting composition. After import, the script collects
    all layer names and reports them back for rig mapping.

    Args:
        ai_path: Absolute path to the .ai file.
        comp_name: Desired name for the AE composition.
        width: Composition width in pixels.
        height: Composition height in pixels.
        fps: Frame rate.
        duration: Duration in seconds.

    Returns:
        JSX code string ready for execution in After Effects.
    """
    escaped_path = ai_path.replace("\\", "/")
    escaped_comp = escape_jsx_string(comp_name)

    return f"""
// -- Import AI file as layered composition --
var result = {{}};
var aiFile = new File("{escaped_path}");

if (!aiFile.exists) {{
    result.error = "AI file not found: {escaped_path}";
    JSON.stringify(result);
}} else {{
    // Import AI file as a composition (each AI layer becomes an AE layer)
    var io = new ImportOptions(aiFile);
    io.importAs = ImportAsType.COMP;

    var imported = app.project.importFile(io);

    // imported is a CompItem containing layers from the AI file
    var srcComp = imported;

    // Rename the imported comp to our desired name
    srcComp.name = "{escaped_comp}";

    // Adjust comp settings to match requested dimensions/duration/fps
    srcComp.width = {width};
    srcComp.height = {height};
    srcComp.frameRate = {fps};
    srcComp.duration = {duration};

    // Collect layer information for rig mapping
    var layers = [];
    for (var i = 1; i <= srcComp.numLayers; i++) {{
        var layer = srcComp.layer(i);
        var info = {{
            index: i,
            name: layer.name,
            enabled: layer.enabled,
            hasParent: layer.parent !== null
        }};
        // Capture initial transform values for reference
        try {{
            var pos = layer.property("Transform").property("Position").value;
            var anchor = layer.property("Transform").property("Anchor Point").value;
            info.position = [pos[0], pos[1]];
            info.anchorPoint = [anchor[0], anchor[1]];
        }} catch(e) {{}}
        layers.push(info);
    }}

    result.comp = {{
        name: srcComp.name,
        width: srcComp.width,
        height: srcComp.height,
        duration: srcComp.duration,
        fps: srcComp.frameRate,
        numLayers: srcComp.numLayers
    }};
    result.layers = layers;

    // Open the comp in the viewer
    srcComp.openInViewer();

    JSON.stringify(result, null, 2);
}}
"""


def register(mcp):
    """Register the adobe_ae_comp_from_character tool."""

    @mcp.tool(
        name="adobe_ae_comp_from_character",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ae_comp_from_character(params: AeCompFromCharacterInput) -> str:
        """Create an AE composition from a posable Illustrator character with separated layers.

        Imports the AI file as a layered composition (one AE layer per AI layer),
        resizes to the requested dimensions, and maps layers to the character rig
        so puppet pins and keyframes can target the correct body parts.
        """
        # Load the rig data from the Illustrator skeleton
        rig = _load_rig(params.character_name)

        # Determine the comp name (auto-generate from character if not specified)
        comp_name = params.comp_name or f"{params.character_name}_comp"

        # Build and execute the JSX
        jsx = _build_comp_from_character_jsx(
            ai_path=params.ai_file_path,
            comp_name=comp_name,
            width=params.width,
            height=params.height,
            fps=params.fps,
            duration=params.duration,
        )
        result = await _async_run_jsx("aftereffects", jsx)

        if not result["success"]:
            return f"Error: {result['stderr']}"

        # Parse the JSX output to update rig data with AE layer mapping
        stdout = result["stdout"]
        try:
            ae_result = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout

        # If the JSX reported an error (file not found, etc.), relay it
        if "error" in ae_result:
            return f"Error: {ae_result['error']}"

        # Store the AE comp/layer mapping in the rig so downstream tools
        # (puppet pins, keyframes, expressions) can find the correct layers
        ae_mapping = {
            "comp_name": ae_result.get("comp", {}).get("name", comp_name),
            "ai_file_path": params.ai_file_path,
            "layers": {},
        }
        for layer_info in ae_result.get("layers", []):
            layer_name = layer_info.get("name", "")
            ae_mapping["layers"][layer_name] = {
                "index": layer_info.get("index"),
                "position": layer_info.get("position"),
                "anchorPoint": layer_info.get("anchorPoint"),
            }

        rig["ae_mapping"] = ae_mapping
        _save_rig(params.character_name, rig)

        return stdout
