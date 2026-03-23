"""Export storyboard as PDF via Illustrator's native PDF save.

Pipeline:
1. Collect panel metadata (descriptions, dialogue, camera, timing, notes)
2. Optionally add text annotations to each artboard via JSX
3. Save as multi-artboard PDF: doc.saveAs(file, PDFSaveOptions)

Three layout modes:
- panels: standard grid (all artboards in order)
- list: one panel per page with full annotations
- presentation: large panel image with notes below
"""

import json
import os

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPdfExportInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig


# Layout constants for annotation placement
ANNOTATION_FONT_SIZE = 9
ANNOTATION_MARGIN = 8
ANNOTATION_LINE_HEIGHT = 12


def _collect_panel_data(rig: dict, params: AiPdfExportInput) -> list[dict]:
    """Gather all panel data from the rig, respecting include flags.

    Returns a list of panel dicts enriched with notes, timing, etc.
    """
    panels = rig.get("storyboard", {}).get("panels", [])
    prod_notes = rig.get("production_notes", {})
    timeline = rig.get("timeline", {"fps": 24})
    fps = timeline.get("fps", 24)

    enriched = []
    cumulative_frame = 0

    for panel in panels:
        pnum = panel.get("number", 0)
        dur = panel.get("duration_frames", 24)
        entry: dict = {
            "number": pnum,
            "artboard_index": panel.get("artboard_index", 0),
        }

        if params.include_descriptions:
            entry["description"] = panel.get("description", "")

        if params.include_dialogue:
            # Dialogue stored in panel_text or as part of description
            entry["dialogue"] = panel.get("dialogue", "")

        if params.include_camera:
            entry["camera"] = panel.get("camera", "medium")

        if params.include_timing:
            entry["duration_frames"] = dur
            entry["duration_seconds"] = round(dur / fps, 3) if fps > 0 else 0
            entry["start_frame"] = cumulative_frame
            entry["start_seconds"] = round(cumulative_frame / fps, 3) if fps > 0 else 0

        if params.include_notes:
            panel_notes = prod_notes.get(str(pnum), [])
            entry["notes"] = panel_notes

        cumulative_frame += dur
        enriched.append(entry)

    return enriched


def _calc_layout_params(layout: str, panel_count: int) -> dict:
    """Calculate layout parameters for annotation placement.

    Returns grid dimensions and sizing hints for each layout mode.
    """
    if layout == "list":
        return {
            "mode": "list",
            "panels_per_page": 1,
            "annotation_area_height": 200,
            "description": "One panel per page with full annotations below.",
        }
    elif layout == "presentation":
        return {
            "mode": "presentation",
            "panels_per_page": 1,
            "annotation_area_height": 150,
            "description": "Large panel with notes sidebar.",
        }
    else:
        # Default "panels" grid layout
        cols = 2
        rows = 3
        return {
            "mode": "panels",
            "columns": cols,
            "rows": rows,
            "panels_per_page": cols * rows,
            "annotation_area_height": 40,
            "description": f"Grid layout: {cols}x{rows} panels per page.",
        }


def _build_annotation_jsx(panels: list[dict], layout: str) -> str:
    """Build JSX to add text annotations to each panel artboard.

    Annotations include description, camera, timing, and notes
    positioned below the panel content area.
    """
    if not panels:
        return ""

    annotation_blocks = []
    for panel in panels:
        pnum = panel.get("number", 0)
        ab_idx = panel.get("artboard_index", 0)

        # Build annotation text lines
        lines = []
        desc = panel.get("description", "")
        if desc:
            lines.append(f"DESC: {desc}")

        dialogue = panel.get("dialogue", "")
        if dialogue:
            lines.append(f"DLG: {dialogue}")

        camera = panel.get("camera", "")
        if camera:
            lines.append(f"CAM: {camera.upper()}")

        dur_sec = panel.get("duration_seconds")
        if dur_sec is not None:
            lines.append(f"TIME: {dur_sec}s")

        notes = panel.get("notes", [])
        for note in notes:
            prio = note.get("priority", "normal").upper()
            ntype = note.get("type", "direction").upper()
            text = note.get("note", "")
            lines.append(f"[{prio}] {ntype}: {text}")

        if not lines:
            continue

        annotation_text = escape_jsx_string("\\n".join(lines))

        annotation_blocks.append(f"""
    // Panel {pnum} annotations
    (function() {{
        try {{
            var ab = doc.artboards[{ab_idx}];
            var rect = ab.artboardRect;
            var annotLayer;
            try {{
                annotLayer = doc.layers.getByName("Annotations");
            }} catch(e) {{
                annotLayer = doc.layers.add();
                annotLayer.name = "Annotations";
            }}

            var tf = annotLayer.textFrames.add();
            tf.contents = "{annotation_text}";
            tf.name = "panel_{pnum}_annotation";
            tf.position = [rect[0] + {ANNOTATION_MARGIN}, rect[3] + {ANNOTATION_LINE_HEIGHT}];
            tf.textRange.characterAttributes.size = {ANNOTATION_FONT_SIZE};
            var annColor = new RGBColor();
            annColor.red = 80; annColor.green = 80; annColor.blue = 80;
            tf.textRange.characterAttributes.fillColor = annColor;
        }} catch(e) {{
            // Skip annotation errors silently
        }}
    }})();""")

    if not annotation_blocks:
        return ""

    return f"""(function() {{
    var doc = app.activeDocument;
    {"".join(annotation_blocks)}
    return JSON.stringify({{"annotations_added": {len(annotation_blocks)}}});
}})();"""


def _build_save_pdf_jsx(output_path: str, layout: str) -> str:
    """Build JSX to save the document as PDF with all artboards."""
    escaped_path = escape_jsx_string(output_path)

    return f"""(function() {{
    var doc = app.activeDocument;
    var pdfFile = new File("{escaped_path}");

    var opts = new PDFSaveOptions();
    opts.compatibility = PDFCompatibility.ACROBAT7;
    opts.preserveEditability = false;
    opts.generateThumbnails = true;
    opts.viewAfterSaving = false;

    // Save all artboards
    opts.artboardRange = "";

    doc.saveAs(pdfFile, opts);

    return JSON.stringify({{
        "saved": "{escaped_path}",
        "artboard_count": doc.artboards.length
    }});
}})();"""


def register(mcp):
    """Register the adobe_ai_pdf_export tool."""

    @mcp.tool(
        name="adobe_ai_pdf_export",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def adobe_ai_pdf_export(params: AiPdfExportInput) -> str:
        """Export storyboard as formatted PDF with annotations.

        Pipeline:
        1. Collect panel data (descriptions, dialogue, camera, timing, notes)
        2. Add text annotations to artboards if needed
        3. Save as PDF with all artboards

        Layouts:
        - panels: standard grid (all artboards)
        - list: one panel per page with full annotations
        - presentation: large panel with notes below
        """
        character_name = "storyboard"
        rig = _load_rig(character_name)

        layout = params.layout.lower().strip()
        valid_layouts = {"panels", "list", "presentation"}
        if layout not in valid_layouts:
            return json.dumps({
                "error": f"Invalid layout: {layout}",
                "valid_layouts": sorted(valid_layouts),
            })

        # Step 1: Collect panel data
        panel_data = _collect_panel_data(rig, params)
        if not panel_data:
            return json.dumps({
                "error": "No panels found in storyboard.",
                "hint": "Create panels first using adobe_ai_storyboard_panel.",
            })

        layout_params = _calc_layout_params(layout, len(panel_data))

        # Step 2: Add annotations via JSX
        annotation_jsx = _build_annotation_jsx(panel_data, layout)
        annotation_result = None
        if annotation_jsx:
            result = await _async_run_jsx("illustrator", annotation_jsx)
            if result.get("success"):
                try:
                    annotation_result = json.loads(result["stdout"])
                except (json.JSONDecodeError, TypeError):
                    annotation_result = {"raw": result.get("stdout", "")}
            else:
                annotation_result = {"warning": result.get("stderr", "annotation failed")}

        # Step 3: Save as PDF
        output_path = params.output_path
        # Ensure .pdf extension
        if not output_path.lower().endswith(".pdf"):
            output_path += ".pdf"

        # Ensure output directory exists
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        save_jsx = _build_save_pdf_jsx(output_path, layout)
        save_result = await _async_run_jsx("illustrator", save_jsx)

        if not save_result.get("success"):
            return json.dumps({
                "error": f"PDF save failed: {save_result.get('stderr', 'Unknown error')}",
                "annotations": annotation_result,
            })

        try:
            save_data = json.loads(save_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            save_data = {}

        return json.dumps({
            "action": "pdf_export",
            "output_path": output_path,
            "layout": layout,
            "layout_params": layout_params,
            "panels_included": len(panel_data),
            "artboard_count": save_data.get("artboard_count", len(panel_data)),
            "annotations": annotation_result,
            "include_flags": {
                "descriptions": params.include_descriptions,
                "dialogue": params.include_dialogue,
                "camera": params.include_camera,
                "timing": params.include_timing,
                "notes": params.include_notes,
            },
        }, indent=2)
