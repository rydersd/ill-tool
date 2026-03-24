"""Manage storyboard panels as artboards in Illustrator.

Each panel is a separate artboard containing the character in a specified
pose with camera framing (wide, medium, close_up, extreme_close_up) and
a text annotation describing the action.  Panel metadata is stored in the
rig file under `storyboard`.
"""

import json
import os

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiStoryboardPanelInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# Camera framing multipliers: fraction of the character's full bounding box
# that is visible in each camera setting.
# Values are (y_start_frac, y_end_frac) from top of character.
CAMERA_FRAMING = {
    "wide": (0.0, 1.0),           # Full character + margins
    "medium": (0.0, 0.55),        # Waist up
    "close_up": (0.0, 0.30),      # Head and shoulders
    "extreme_close_up": (0.0, 0.18),  # Face only
    "over_shoulder": (0.05, 0.45),    # Behind-shoulder framing
}

# Default artboard size for panels
PANEL_WIDTH = 960
PANEL_HEIGHT = 540  # 16:9 aspect ratio


def _ensure_storyboard(rig: dict) -> dict:
    """Ensure the rig has a storyboard structure."""
    if "storyboard" not in rig:
        rig["storyboard"] = {"panels": []}
    return rig


def _next_panel_number(rig: dict) -> int:
    """Get the next available panel number."""
    panels = rig.get("storyboard", {}).get("panels", [])
    if not panels:
        return 1
    return max(p.get("number", 0) for p in panels) + 1


def register(mcp):
    """Register the adobe_ai_storyboard_panel tool."""

    @mcp.tool(
        name="adobe_ai_storyboard_panel",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_storyboard_panel(params: AiStoryboardPanelInput) -> str:
        """Manage storyboard panels as artboards in Illustrator.

        Create panels with character poses and camera framing, duplicate
        existing panels, reorder the sequence, list all panels with metadata,
        or export all panels as numbered PNG files.
        """
        rig = _load_rig(params.character_name)
        rig = _ensure_storyboard(rig)

        action = params.action.lower().strip()

        # ── create ──────────────────────────────────────────────────────
        if action == "create":
            panel_num = params.panel_number if params.panel_number is not None else _next_panel_number(rig)

            # Validate pose exists if specified
            if params.pose_name:
                poses = rig.get("poses", {})
                if params.pose_name not in poses:
                    available = list(poses.keys()) if poses else []
                    return json.dumps({
                        "error": f"Pose '{params.pose_name}' not found in rig.",
                        "available_poses": available,
                    })

            # Camera framing parameters
            camera = params.camera.lower().strip()
            if camera not in CAMERA_FRAMING:
                return json.dumps({
                    "error": f"Unknown camera setting: {camera}",
                    "valid_cameras": list(CAMERA_FRAMING.keys()),
                })

            y_start, y_end = CAMERA_FRAMING[camera]
            description = params.description or f"Panel {panel_num}"
            escaped_desc = escape_jsx_string(description)

            # Calculate artboard position: panels are laid out horizontally
            # with a gap between them
            panel_gap = 40
            existing_count = len(rig["storyboard"]["panels"])
            ab_left = (PANEL_WIDTH + panel_gap) * existing_count
            ab_top = 0
            ab_right = ab_left + PANEL_WIDTH
            ab_bottom = ab_top - PANEL_HEIGHT  # AI coords: top > bottom

            # Build JSX to create the artboard and contents
            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Create artboard for this panel
    var abRect = [{ab_left}, {ab_top}, {ab_right}, {ab_bottom}];
    var abIdx = doc.artboards.add(abRect);
    var ab = doc.artboards[abIdx];
    ab.name = "Panel {panel_num}";

    // Create a layer for panel contents
    var panelLayer = doc.layers.add();
    panelLayer.name = "Panel_{panel_num}";
    doc.activeLayer = panelLayer;

    // Camera framing rectangle (clipping mask boundary)
    var camYStart = {y_start};
    var camYEnd = {y_end};
    var camHeight = (camYEnd - camYStart) * {PANEL_HEIGHT};
    var camTop = {ab_top} - ({PANEL_HEIGHT} * camYStart);
    var camBottom = camTop - camHeight;

    // Draw the framing rectangle
    var frame = panelLayer.pathItems.rectangle(
        {ab_top}, {ab_left}, {PANEL_WIDTH}, {PANEL_HEIGHT}
    );
    frame.name = "panel_{panel_num}_frame";
    frame.filled = false;
    frame.stroked = true;
    frame.strokeWidth = 2;
    var frameColor = new RGBColor();
    frameColor.red = 40; frameColor.green = 40; frameColor.blue = 40;
    frame.strokeColor = frameColor;

    // Camera safe area rectangle (shows the framing)
    if (camYStart > 0 || camYEnd < 1) {{
        var safeFrame = panelLayer.pathItems.rectangle(
            camTop, {ab_left} + 10, {PANEL_WIDTH} - 20, camHeight - 10
        );
        safeFrame.name = "panel_{panel_num}_camera";
        safeFrame.filled = false;
        safeFrame.stroked = true;
        safeFrame.strokeWidth = 0.5;
        var safeColor = new RGBColor();
        safeColor.red = 255; safeColor.green = 100; safeColor.blue = 100;
        safeFrame.strokeColor = safeColor;
        safeFrame.strokeDashes = [4, 4];
    }}

    // Add description text at the bottom of the panel
    var textFrame = panelLayer.textFrames.add();
    textFrame.contents = "{escaped_desc}";
    textFrame.name = "panel_{panel_num}_desc";
    textFrame.position = [{ab_left} + 10, {ab_bottom} + 18];
    textFrame.textRange.characterAttributes.size = 10;
    var textColor = new RGBColor();
    textColor.red = 80; textColor.green = 80; textColor.blue = 80;
    textFrame.textRange.characterAttributes.fillColor = textColor;

    // Add panel number label at top-left
    var numLabel = panelLayer.textFrames.add();
    numLabel.contents = "#{panel_num}";
    numLabel.name = "panel_{panel_num}_number";
    numLabel.position = [{ab_left} + 8, {ab_top} - 8];
    numLabel.textRange.characterAttributes.size = 14;
    var numColor = new RGBColor();
    numColor.red = 60; numColor.green = 60; numColor.blue = 60;
    numLabel.textRange.characterAttributes.fillColor = numColor;

    // Add camera type label
    var camLabel = panelLayer.textFrames.add();
    camLabel.contents = "{camera.upper()}";
    camLabel.name = "panel_{panel_num}_camera_label";
    camLabel.position = [{ab_right} - 80, {ab_top} - 8];
    camLabel.textRange.characterAttributes.size = 8;
    var camLabelColor = new RGBColor();
    camLabelColor.red = 200; camLabelColor.green = 100; camLabelColor.blue = 100;
    camLabel.textRange.characterAttributes.fillColor = camLabelColor;

    return JSON.stringify({{
        artboard_index: abIdx,
        artboard_name: ab.name,
        panel_number: {panel_num},
        bounds: abRect
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            if not result.get("success", False):
                return json.dumps({
                    "error": f"Failed to create panel artboard: {result.get('stderr', 'Unknown error')}",
                })

            try:
                created = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                created = {"artboard_index": existing_count}

            # Store panel metadata in rig
            panel_data = {
                "number": panel_num,
                "pose": params.pose_name or "",
                "camera": camera,
                "description": description,
                "duration_frames": params.duration_frames,
                "artboard_index": created.get("artboard_index", existing_count),
            }

            # Remove any existing panel with the same number
            rig["storyboard"]["panels"] = [
                p for p in rig["storyboard"]["panels"]
                if p.get("number") != panel_num
            ]
            rig["storyboard"]["panels"].append(panel_data)
            rig["storyboard"]["panels"].sort(key=lambda p: p.get("number", 0))

            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "create",
                "panel": panel_data,
                "artboard_index": created.get("artboard_index"),
                "total_panels": len(rig["storyboard"]["panels"]),
            }, indent=2)

        # ── duplicate ───────────────────────────────────────────────────
        elif action == "duplicate":
            if params.panel_number is None:
                return json.dumps({"error": "panel_number is required to specify which panel to duplicate."})

            source_panel = None
            for p in rig["storyboard"]["panels"]:
                if p.get("number") == params.panel_number:
                    source_panel = p
                    break

            if source_panel is None:
                available = [p.get("number") for p in rig["storyboard"]["panels"]]
                return json.dumps({
                    "error": f"Panel {params.panel_number} not found.",
                    "available_panels": available,
                })

            new_num = _next_panel_number(rig)
            source_ab_idx = source_panel.get("artboard_index", 0)

            # Calculate position for new panel
            panel_gap = 40
            total_panels = len(rig["storyboard"]["panels"])
            new_left = (PANEL_WIDTH + panel_gap) * total_panels
            new_top = 0
            new_right = new_left + PANEL_WIDTH
            new_bottom = new_top - PANEL_HEIGHT

            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Create new artboard
    var abRect = [{new_left}, {new_top}, {new_right}, {new_bottom}];
    var abIdx = doc.artboards.add(abRect);
    var ab = doc.artboards[abIdx];
    ab.name = "Panel {new_num}";

    // Find source panel layer and duplicate items
    var sourceLayer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Panel_{params.panel_number}") {{
            sourceLayer = doc.layers[i]; break;
        }}
    }}

    var copied = 0;
    if (sourceLayer) {{
        var newLayer = doc.layers.add();
        newLayer.name = "Panel_{new_num}";

        // Calculate offset from source to new artboard
        var srcAb = doc.artboards[{source_ab_idx}].artboardRect;
        var offsetX = {new_left} - srcAb[0];
        var offsetY = {new_top} - srcAb[1];

        // Duplicate each item from source layer to new layer
        for (var j = sourceLayer.pageItems.length - 1; j >= 0; j--) {{
            var item = sourceLayer.pageItems[j];
            var dup = item.duplicate(newLayer, ElementPlacement.PLACEATBEGINNING);
            dup.translate(offsetX, offsetY);
            copied++;
        }}
    }}

    return JSON.stringify({{
        artboard_index: abIdx,
        panel_number: {new_num},
        copied_items: copied
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            if not result.get("success", False):
                return json.dumps({
                    "error": f"Failed to duplicate panel: {result.get('stderr', 'Unknown error')}",
                })

            try:
                dup_info = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                dup_info = {"panel_number": new_num, "copied_items": 0}

            # Store new panel in rig
            new_panel = {
                "number": new_num,
                "pose": source_panel.get("pose", ""),
                "camera": source_panel.get("camera", "medium"),
                "description": f"(Copy of Panel {params.panel_number}) {source_panel.get('description', '')}",
                "duration_frames": source_panel.get("duration_frames", 24),
                "artboard_index": dup_info.get("artboard_index", total_panels),
            }
            rig["storyboard"]["panels"].append(new_panel)
            rig["storyboard"]["panels"].sort(key=lambda p: p.get("number", 0))
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "duplicate",
                "source_panel": params.panel_number,
                "new_panel": new_panel,
                "copied_items": dup_info.get("copied_items", 0),
                "total_panels": len(rig["storyboard"]["panels"]),
            }, indent=2)

        # ── reorder ─────────────────────────────────────────────────────
        elif action == "reorder":
            if params.panel_number is None:
                return json.dumps({"error": "panel_number is required for reorder (panel to move)."})

            panels = rig["storyboard"]["panels"]
            target_panel = None
            target_idx = None
            for i, p in enumerate(panels):
                if p.get("number") == params.panel_number:
                    target_panel = p
                    target_idx = i
                    break

            if target_panel is None:
                available = [p.get("number") for p in panels]
                return json.dumps({
                    "error": f"Panel {params.panel_number} not found.",
                    "available_panels": available,
                })

            # Use duration_frames as the new position index (1-based)
            # since we don't have a separate "new_position" field
            new_position = params.duration_frames
            if new_position < 1:
                new_position = 1
            if new_position > len(panels):
                new_position = len(panels)

            # Remove and reinsert at new position
            panels.pop(target_idx)
            panels.insert(new_position - 1, target_panel)

            # Renumber all panels sequentially
            for i, p in enumerate(panels):
                p["number"] = i + 1

            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "reorder",
                "moved_panel": params.panel_number,
                "new_position": new_position,
                "panel_order": [
                    {"number": p["number"], "description": p.get("description", "")}
                    for p in panels
                ],
            }, indent=2)

        # ── list ────────────────────────────────────────────────────────
        elif action == "list":
            panels = rig["storyboard"]["panels"]

            # Enrich with timing info from the timeline
            timeline = rig.get("timeline", {"fps": 24})
            fps = timeline.get("fps", 24)

            enriched = []
            cumulative_frame = 0
            for p in panels:
                dur = p.get("duration_frames", 24)
                enriched.append({
                    "number": p.get("number"),
                    "pose": p.get("pose", ""),
                    "camera": p.get("camera", "medium"),
                    "description": p.get("description", ""),
                    "duration_frames": dur,
                    "duration_seconds": round(dur / fps, 3) if fps > 0 else 0,
                    "start_frame": cumulative_frame,
                    "start_seconds": round(cumulative_frame / fps, 3) if fps > 0 else 0,
                    "artboard_index": p.get("artboard_index"),
                })
                cumulative_frame += dur

            total_frames = cumulative_frame
            total_seconds = round(total_frames / fps, 3) if fps > 0 else 0

            return json.dumps({
                "action": "list",
                "character_name": params.character_name,
                "panels": enriched,
                "total_panels": len(enriched),
                "total_frames": total_frames,
                "total_seconds": total_seconds,
                "fps": fps,
            }, indent=2)

        # ── export ──────────────────────────────────────────────────────
        elif action == "export":
            panels = rig["storyboard"]["panels"]
            if not panels:
                return json.dumps({
                    "error": "No panels to export.",
                    "hint": "Create panels first using action='create'.",
                })

            # Export each panel's artboard as a numbered PNG
            export_dir = "/tmp/ai_storyboard_export"
            os.makedirs(export_dir, exist_ok=True)

            exported = []
            errors = []

            for panel in panels:
                panel_num = panel.get("number", 0)
                ab_idx = panel.get("artboard_index", 0)
                out_path = os.path.join(export_dir, f"panel_{panel_num:03d}.png")
                escaped_path = out_path.replace("\\", "\\\\")

                jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Set active artboard to this panel
    doc.artboards.setActiveArtboardIndex({ab_idx});

    // Export as PNG
    var exportFile = new File("{escaped_path}");
    var opts = new ExportOptionsPNG24();
    opts.horizontalScale = 100;
    opts.verticalScale = 100;
    opts.transparency = false;
    opts.antiAliasing = true;
    opts.artBoardClipping = true;

    doc.exportFile(exportFile, ExportType.PNG24, opts);

    return JSON.stringify({{
        panel: {panel_num},
        path: "{escaped_path}",
        artboard_index: {ab_idx}
    }});
}})();
"""
                result = await _async_run_jsx("illustrator", jsx)
                if result.get("success", False):
                    exported.append({
                        "panel": panel_num,
                        "path": out_path,
                        "description": panel.get("description", ""),
                    })
                else:
                    errors.append({
                        "panel": panel_num,
                        "error": result.get("stderr", "Unknown export error"),
                    })

            return json.dumps({
                "action": "export",
                "export_directory": export_dir,
                "exported": exported,
                "errors": errors,
                "total_exported": len(exported),
                "total_errors": len(errors),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "duplicate", "reorder", "list", "export"],
            })
