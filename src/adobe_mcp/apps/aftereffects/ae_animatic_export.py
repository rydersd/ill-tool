"""Create a timed animatic from storyboard panels in After Effects.

Imports storyboard panel images as layers in a new AE composition, sets
in/out points to match each panel's duration, applies transitions between
panels (cut, dissolve, wipe), and optionally adds comp markers at panel
boundaries for audio sync.
"""

import json
import os

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects.models import AeAnimaticExportInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


def _build_animatic_jsx(
    comp_name: str,
    panels: list[dict],
    transition: str,
    transition_frames: int,
    fps: float,
    add_markers: bool,
    width: int,
    height: int,
) -> str:
    """Build JSX to create an animatic composition from storyboard panels.

    Creates a comp sized to the panels, imports each panel image as a layer,
    sets timing (in/out points), applies transitions, and adds markers.

    Args:
        comp_name: Name for the animatic composition.
        panels: List of panel dicts with keys:
            - path: File path to the panel image
            - name: Panel label
            - duration_frames: How many frames this panel lasts
        transition: Transition type: "cut", "dissolve", "wipe"
        transition_frames: Number of frames for the transition
        fps: Frame rate.
        add_markers: Whether to add comp markers at panel boundaries.
        width: Composition width.
        height: Composition height.

    Returns:
        JSX code string.
    """
    escaped_comp = escape_jsx_string(comp_name)

    # Calculate total duration from all panels
    total_frames = sum(p.get("duration_frames", 48) for p in panels)
    total_duration = total_frames / fps

    # Build panel import and timing JSX
    panel_blocks = []
    cumulative_frame = 0

    for i, panel in enumerate(panels):
        panel_path = panel.get("path", "").replace("\\", "/")
        panel_name = escape_jsx_string(panel.get("name", f"Panel {i + 1}"))
        duration_frames = panel.get("duration_frames", 48)

        in_time = cumulative_frame / fps
        out_time = (cumulative_frame + duration_frames) / fps
        transition_sec = transition_frames / fps

        # Import the panel image and add as a layer
        panel_blocks.append(f"""
// -- Panel {i + 1}: {panel_name} --
try {{
    var panelFile = new File("{panel_path}");
    if (panelFile.exists) {{
        var footage = app.project.importFile(new ImportOptions(panelFile));
        var layer = comp.layers.add(footage);
        layer.name = "{panel_name}";
        layer.startTime = {in_time};
        layer.inPoint = {in_time};
        layer.outPoint = {out_time};

        // Scale layer to fit comp if needed
        try {{
            var srcW = footage.width;
            var srcH = footage.height;
            if (srcW > 0 && srcH > 0) {{
                var scaleX = (comp.width / srcW) * 100;
                var scaleY = (comp.height / srcH) * 100;
                var scale = Math.min(scaleX, scaleY);
                layer.property("Transform").property("Scale").setValue([scale, scale]);
            }}
        }} catch(scaleErr) {{}}

        panelLayers.push({{
            name: "{panel_name}",
            inPoint: {in_time},
            outPoint: {out_time},
            durationFrames: {duration_frames}
        }});
""")

        # Apply transition from the previous panel
        if i > 0 and transition != "cut" and transition_frames > 0:
            if transition == "dissolve":
                # Cross-dissolve: fade current layer in while previous fades out
                panel_blocks.append(f"""
        // Dissolve transition in
        layer.property("Transform").property("Opacity").setValueAtTime({in_time}, 0);
        layer.property("Transform").property("Opacity").setValueAtTime({in_time} + {transition_sec}, 100);
        // Extend previous layer to overlap
        if (comp.numLayers > 1) {{
            try {{
                var prevLayer = panelLayerRefs[panelLayerRefs.length - 1];
                if (prevLayer) {{
                    prevLayer.outPoint = {in_time} + {transition_sec};
                    prevLayer.property("Transform").property("Opacity").setValueAtTime({in_time}, 100);
                    prevLayer.property("Transform").property("Opacity").setValueAtTime({in_time} + {transition_sec}, 0);
                }}
            }} catch(transErr) {{}}
        }}
""")
            elif transition == "wipe":
                # Linear Wipe effect for a directional transition
                panel_blocks.append(f"""
        // Wipe transition
        try {{
            var wipeEff = layer.property("Effects").addProperty("ADBE Linear Wipe");
            wipeEff.property("Transition Completion").setValueAtTime({in_time}, 100);
            wipeEff.property("Transition Completion").setValueAtTime({in_time} + {transition_sec}, 0);
            wipeEff.property("Wipe Angle").setValue(0);
            wipeEff.property("Feather").setValue(20);
        }} catch(wipeErr) {{
            errors.push({{ panel: "{panel_name}", error: "Linear Wipe: " + wipeErr.toString() }});
        }}
""")

        # Store layer reference for transition handling
        panel_blocks.append(f"""
        panelLayerRefs.push(layer);
    }} else {{
        notFound.push("{panel_path}");
    }}
}} catch(e) {{
    errors.push({{ panel: "{panel_name}", error: e.toString() }});
}}
""")

        cumulative_frame += duration_frames

    panels_block = "\n".join(panel_blocks)

    # Build marker JSX
    markers_jsx = ""
    if add_markers:
        marker_blocks = []
        cum_frame = 0
        for i, panel in enumerate(panels):
            marker_time = cum_frame / fps
            marker_name = escape_jsx_string(panel.get("name", f"Panel {i + 1}"))
            marker_blocks.append(f"""
try {{
    var marker = new MarkerValue("{marker_name}");
    comp.markerProperty.setValueAtTime({marker_time}, marker);
    markersAdded++;
}} catch(mErr) {{}}
""")
            cum_frame += panel.get("duration_frames", 48)

        markers_jsx = "\n".join(marker_blocks)

    return f"""
// -- Create animatic from storyboard panels --
var panelLayers = [];
var panelLayerRefs = [];
var notFound = [];
var errors = [];
var markersAdded = 0;

// Create the animatic composition
var comp = app.project.items.addComp(
    "{escaped_comp}",
    {width},
    {height},
    1,
    {total_duration},
    {fps}
);

// Import and arrange panels
{panels_block}

// Add markers at panel boundaries
{markers_jsx}

// Build result
var result = {{
    comp: {{
        name: comp.name,
        width: comp.width,
        height: comp.height,
        duration: comp.duration,
        fps: comp.frameRate
    }},
    panelCount: panelLayers.length,
    totalDuration: comp.duration,
    transition: "{transition}",
    transitionFrames: {transition_frames},
    panels: panelLayers,
    markersAdded: markersAdded
}};
if (notFound.length > 0) result.notFound = notFound;
if (errors.length > 0) result.errors = errors;

// Open the animatic in the viewer
comp.openInViewer();

JSON.stringify(result, null, 2);
"""


def register(mcp):
    """Register the adobe_ae_animatic_export tool."""

    @mcp.tool(
        name="adobe_ae_animatic_export",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ae_animatic_export(params: AeAnimaticExportInput) -> str:
        """Create a timed animatic from storyboard panels in After Effects.

        Imports storyboard panel images as layers, sets in/out points for each
        panel's duration, applies transitions (cut, dissolve, wipe), and adds
        comp markers at panel boundaries for audio sync.
        """
        # Validate transition type
        valid_transitions = ("cut", "dissolve", "wipe")
        if params.panel_transition not in valid_transitions:
            return json.dumps({
                "error": f"Invalid panel_transition '{params.panel_transition}'. "
                         f"Must be one of: {', '.join(valid_transitions)}"
            })

        # Load the rig to get storyboard/panel data
        rig = _load_rig(params.character_name)

        # Get storyboard panels from the rig
        storyboard = rig.get("storyboard", {})
        panels = storyboard.get("panels", [])

        if not panels:
            return json.dumps({
                "error": f"No storyboard panels found for character '{params.character_name}'. "
                         "Store panel data in the rig's 'storyboard.panels' array, "
                         "each with 'path', 'name', and 'duration_frames'."
            })

        # Validate that panel files exist (warn but don't block)
        for panel in panels:
            path = panel.get("path", "")
            if not path:
                panel["path"] = ""
            # Ensure duration_frames has a default
            if "duration_frames" not in panel:
                panel["duration_frames"] = 48  # 2 seconds at 24fps

        # Get comp dimensions from rig or defaults
        ae_mapping = rig.get("ae_mapping", {})
        width = 1920
        height = 1080
        fps = 24.0

        # Try to match the character comp dimensions
        if ae_mapping:
            comp_info = ae_mapping.get("comp_info", {})
            if comp_info:
                width = comp_info.get("width", width)
                height = comp_info.get("height", height)

        # Build and execute the JSX
        jsx = _build_animatic_jsx(
            comp_name=params.comp_name,
            panels=panels,
            transition=params.panel_transition,
            transition_frames=params.transition_frames,
            fps=fps,
            add_markers=params.add_audio_markers,
            width=width,
            height=height,
        )
        result = await _async_run_jsx("aftereffects", jsx)

        if not result["success"]:
            return f"Error: {result['stderr']}"

        return result["stdout"]
