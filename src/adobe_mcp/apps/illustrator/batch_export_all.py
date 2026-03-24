"""Export all panels, formats, and metadata in one call.

Orchestrates multi-format export: PNG panels, PDF storyboard,
JSON rig data, EDL timeline, and AE import script.

Pure Python orchestrator — generates specs and file manifests.
"""

import json
import os
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiBatchExportAllInput(BaseModel):
    """Export all storyboard data in multiple formats."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="export_all",
        description="Action: export_all or manifest",
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    output_dir: str = Field(
        default="/tmp/ai_storyboard_export",
        description="Root output directory",
    )
    formats: Optional[list[str]] = Field(
        default=None,
        description="Formats to export: png, pdf, json, edl, ae_jsx (default: all)",
    )
    fps: int = Field(
        default=24,
        description="Frames per second for timeline exports",
        ge=1,
    )
    title: str = Field(
        default="Storyboard",
        description="Project / sequence title",
    )


# ---------------------------------------------------------------------------
# Default export formats
# ---------------------------------------------------------------------------


ALL_FORMATS = ["png", "pdf", "json", "edl", "ae_jsx"]


# ---------------------------------------------------------------------------
# Export helpers (pure Python — generate specs/manifests)
# ---------------------------------------------------------------------------


def _ensure_subdirs(output_dir: str) -> dict[str, str]:
    """Create and return subdirectory paths for each export type."""
    subdirs = {
        "panels": os.path.join(output_dir, "panels"),
        "pdf": os.path.join(output_dir, "pdf"),
        "data": os.path.join(output_dir, "data"),
        "ae": os.path.join(output_dir, "ae"),
    }
    for path in subdirs.values():
        os.makedirs(path, exist_ok=True)
    return subdirs


def _export_png_specs(panels: list[dict], subdirs: dict[str, str]) -> list[dict]:
    """Generate PNG export specs for each panel (no actual rendering)."""
    specs = []
    for panel in panels:
        num = panel.get("number", 0)
        path = os.path.join(subdirs["panels"], f"panel_{num:03d}.png")
        specs.append({
            "panel_number": num,
            "format": "png",
            "path": path,
            "description": panel.get("description", ""),
        })
    return specs


def _export_pdf_spec(panels: list[dict], subdirs: dict[str, str], title: str) -> dict:
    """Generate PDF export spec."""
    path = os.path.join(subdirs["pdf"], f"{title.lower().replace(' ', '_')}.pdf")
    return {
        "format": "pdf",
        "path": path,
        "panel_count": len(panels),
        "title": title,
    }


def _export_json_rig(rig: dict, subdirs: dict[str, str], character_name: str) -> dict:
    """Write rig JSON to data directory."""
    path = os.path.join(subdirs["data"], f"{character_name}_rig.json")
    with open(path, "w") as f:
        json.dump(rig, f, indent=2)
    return {
        "format": "json",
        "path": path,
        "keys": list(rig.keys()),
    }


def _export_edl(panels: list[dict], subdirs: dict[str, str], title: str, fps: int) -> dict:
    """Generate EDL content and write to data directory."""
    path = os.path.join(subdirs["data"], f"{title.lower().replace(' ', '_')}.edl")

    lines = [
        f"TITLE: {title}",
        "FCM: NON-DROP FRAME",
        "",
    ]

    record_frame = 0
    for i, panel in enumerate(panels):
        event_num = i + 1
        duration = panel.get("duration_frames", 24)
        reel = f"PANEL_{panel.get('number', event_num):03d}"
        description = panel.get("description", "")

        def _tc(frames: int) -> str:
            if fps <= 0:
                return "00:00:00:00"
            h = frames // (fps * 3600)
            rem = frames % (fps * 3600)
            m = rem // (fps * 60)
            rem = rem % (fps * 60)
            s = rem // fps
            f_ = rem % fps
            return f"{h:02d}:{m:02d}:{s:02d}:{f_:02d}"

        src_in = _tc(0)
        src_out = _tc(duration)
        rec_in = _tc(record_frame)
        rec_out = _tc(record_frame + duration)

        lines.append(
            f"{event_num:03d}  {reel:<8s} V     C        "
            f"{src_in} {src_out} {rec_in} {rec_out}"
        )
        if description:
            lines.append(f"* FROM CLIP NAME: {description}")
        lines.append("")
        record_frame += duration

    with open(path, "w") as f:
        f.write("\n".join(lines))

    return {
        "format": "edl",
        "path": path,
        "event_count": len(panels),
        "total_frames": record_frame,
    }


def _export_ae_jsx(panels: list[dict], subdirs: dict[str, str], title: str, fps: int) -> dict:
    """Generate AE import JSX script."""
    path = os.path.join(subdirs["ae"], f"import_{title.lower().replace(' ', '_')}.jsx")

    jsx_lines = [
        '// Auto-generated AE import script',
        f'// Project: {title}',
        f'// Panels: {len(panels)}',
        f'// FPS: {fps}',
        '',
        '(function() {',
        '    app.beginUndoGroup("Import Storyboard");',
        '',
        '    var comp = app.project.items.addComp(',
        f'        "{title}",',
        '        1920, 1080,',
        '        1.0,',
        f'        {sum(p.get("duration_frames", 24) for p in panels) / fps},',
        f'        {fps}',
        '    );',
        '',
    ]

    record_frame = 0
    for panel in panels:
        num = panel.get("number", 0)
        duration = panel.get("duration_frames", 24)
        start_time = record_frame / fps
        end_time = (record_frame + duration) / fps

        jsx_lines.extend([
            f'    // Panel {num}: {panel.get("description", "")}',
            f'    var file_{num} = new ImportOptions(new File("panels/panel_{num:03d}.png"));',
            f'    var footage_{num} = app.project.importFile(file_{num});',
            f'    var layer_{num} = comp.layers.add(footage_{num});',
            f'    layer_{num}.startTime = {start_time};',
            f'    layer_{num}.outPoint = {end_time};',
            f'    layer_{num}.name = "Panel {num}";',
            '',
        ])
        record_frame += duration

    jsx_lines.extend([
        '    app.endUndoGroup();',
        '})();',
    ])

    with open(path, "w") as f:
        f.write("\n".join(jsx_lines))

    return {
        "format": "ae_jsx",
        "path": path,
        "panel_count": len(panels),
    }


# ---------------------------------------------------------------------------
# Main export orchestrator
# ---------------------------------------------------------------------------


def export_all(
    rig: dict,
    output_dir: str,
    formats: Optional[list[str]] = None,
    fps: int = 24,
    title: str = "Storyboard",
) -> dict:
    """Export all panels, formats, and metadata.

    Args:
        rig: Full rig dict (must have storyboard.panels).
        output_dir: Root output directory.
        formats: List of formats to export (default: all).
        fps: Frames per second.
        title: Project title.

    Returns:
        Manifest dict listing all exported files.
    """
    active_formats = formats if formats else list(ALL_FORMATS)
    subdirs = _ensure_subdirs(output_dir)
    panels = rig.get("storyboard", {}).get("panels", [])
    panels = sorted(panels, key=lambda p: p.get("number", 0))

    manifest = {
        "project": title,
        "character": rig.get("character_name", "unknown"),
        "output_dir": output_dir,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "formats": active_formats,
        "panel_count": len(panels),
        "exports": {},
    }

    if "png" in active_formats:
        manifest["exports"]["png"] = _export_png_specs(panels, subdirs)

    if "pdf" in active_formats:
        manifest["exports"]["pdf"] = _export_pdf_spec(panels, subdirs, title)

    if "json" in active_formats:
        manifest["exports"]["json"] = _export_json_rig(rig, subdirs, rig.get("character_name", "character"))

    if "edl" in active_formats:
        manifest["exports"]["edl"] = _export_edl(panels, subdirs, title, fps)

    if "ae_jsx" in active_formats:
        manifest["exports"]["ae_jsx"] = _export_ae_jsx(panels, subdirs, title, fps)

    # Write manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    manifest["manifest_path"] = manifest_path

    return manifest


def export_manifest(output_dir: str) -> Optional[dict]:
    """Read an existing export manifest from an output directory.

    Returns None if no manifest exists.
    """
    manifest_path = os.path.join(output_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_batch_export_all tool."""

    @mcp.tool(
        name="adobe_ai_batch_export_all",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_batch_export_all(params: AiBatchExportAllInput) -> str:
        """Export all panels, formats, and metadata in one call.

        Actions:
        - export_all: generate all exports (PNG specs, PDF spec, JSON rig, EDL, AE JSX)
        - manifest: read existing export manifest
        """
        action = params.action.lower().strip()

        if action == "export_all":
            # Build a minimal rig for export
            rig = {
                "character_name": params.character_name,
                "storyboard": {"panels": []},
            }
            manifest = export_all(
                rig=rig,
                output_dir=params.output_dir,
                formats=params.formats,
                fps=params.fps,
                title=params.title,
            )
            return json.dumps(manifest, indent=2)

        elif action == "manifest":
            existing = export_manifest(params.output_dir)
            if existing is None:
                return json.dumps({"error": f"No manifest found in {params.output_dir}"})
            return json.dumps(existing, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["export_all", "manifest"],
            })
