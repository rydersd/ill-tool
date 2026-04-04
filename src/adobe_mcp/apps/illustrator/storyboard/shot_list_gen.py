"""Generate a production shot list from storyboard data.

Reads panels, scenes, camera notations, and timing from the rig to
produce a formatted table, CSV, or JSON export of every shot.

Output columns: Shot, Scene, Panel, Camera, Movement, Duration, Description.
"""

import csv
import io
import json

from adobe_mcp.apps.illustrator.models import AiShotListInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


def _build_shot_rows(rig: dict, include_timing: bool, include_camera: bool) -> list[dict]:
    """Build a list of shot-row dicts from the rig's storyboard data.

    Each row contains: shot, scene, panel, camera, movement, duration_frames,
    duration_seconds, cumulative_seconds, and description.
    """
    # Gather data from rig
    storyboard = rig.get("storyboard", {})
    panels = storyboard.get("panels", [])
    scenes = rig.get("scenes", [])
    timeline = rig.get("timeline", {"fps": 24})
    fps = timeline.get("fps", 24)

    # Build a panel-number -> scene-number lookup
    panel_to_scene: dict[int, int] = {}
    for scene in scenes:
        for pn in scene.get("panels", []):
            panel_to_scene[pn] = scene.get("number", 0)

    rows = []
    cumulative_frames = 0

    for shot_index, panel in enumerate(panels, start=1):
        panel_num = panel.get("number", shot_index)
        duration = panel.get("duration_frames", 24)
        duration_secs = round(duration / fps, 3) if fps > 0 else 0.0
        cumulative_frames += duration
        cumulative_secs = round(cumulative_frames / fps, 3) if fps > 0 else 0.0

        row = {
            "shot": shot_index,
            "scene": panel_to_scene.get(panel_num, 0),
            "panel": panel_num,
            "camera": panel.get("camera", "MEDIUM").upper() if include_camera else "",
            "movement": "STATIC",
            "duration_frames": duration if include_timing else 0,
            "duration_seconds": duration_secs if include_timing else 0.0,
            "cumulative_seconds": cumulative_secs if include_timing else 0.0,
            "description": panel.get("description", ""),
        }

        # Check for camera notation stored per-panel
        camera_notations = rig.get("camera_notations", {})
        notation = camera_notations.get(str(panel_num), {})
        if notation and include_camera:
            row["movement"] = notation.get("movement", "STATIC").upper()

        rows.append(row)

    return rows


def _format_table(rows: list[dict]) -> str:
    """Render shot rows as an aligned text table."""
    if not rows:
        return "No shots in storyboard."

    header = f"{'Shot':<5} | {'Scene':<5} | {'Panel':<5} | {'Camera':<8} | {'Movement':<10} | {'Duration':<10} | Description"
    sep = "-" * len(header)
    lines = [header, sep]

    for r in rows:
        duration_str = f"{r['duration_seconds']:.1f}s"
        lines.append(
            f"{r['shot']:<5} | {r['scene']:<5} | {r['panel']:<5} | "
            f"{r['camera']:<8} | {r['movement']:<10} | {duration_str:<10} | "
            f"{r['description']}"
        )

    return "\n".join(lines)


def _format_csv(rows: list[dict]) -> str:
    """Render shot rows as CSV text."""
    if not rows:
        return ""

    output = io.StringIO()
    fieldnames = [
        "shot", "scene", "panel", "camera", "movement",
        "duration_frames", "duration_seconds", "cumulative_seconds",
        "description",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return output.getvalue()


def register(mcp):
    """Register the adobe_ai_shot_list_gen tool."""

    @mcp.tool(
        name="adobe_ai_shot_list_gen",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_shot_list_gen(params: AiShotListInput) -> str:
        """Generate a production shot list from storyboard data.

        Reads all panel, scene, camera, and timing data to produce a
        formatted shot list.  Output as a text table, CSV, or JSON.
        """
        rig = _load_rig("storyboard")

        action = params.action.lower().strip()

        rows = _build_shot_rows(
            rig,
            include_timing=params.include_timing,
            include_camera=params.include_camera,
        )

        # ── generate ─────────────────────────────────────────────────
        if action == "generate":
            table = _format_table(rows)
            return json.dumps({
                "action": "generate",
                "shot_list": table,
                "total_shots": len(rows),
            }, indent=2)

        # ── export_csv ───────────────────────────────────────────────
        elif action == "export_csv":
            csv_text = _format_csv(rows)
            return json.dumps({
                "action": "export_csv",
                "csv": csv_text,
                "total_shots": len(rows),
            }, indent=2)

        # ── export_json ──────────────────────────────────────────────
        elif action == "export_json":
            return json.dumps({
                "action": "export_json",
                "shots": rows,
                "total_shots": len(rows),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["generate", "export_csv", "export_json"],
            })
