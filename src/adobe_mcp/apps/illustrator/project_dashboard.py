"""Generate HTML overview of entire storyboard project.

Creates a self-contained HTML dashboard showing project status,
character data, panel overview, timeline, and export status.

Pure Python — no JSX or Adobe required.
"""

import json
import html as html_module
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiProjectDashboardInput(BaseModel):
    """Generate HTML project dashboard."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="generate",
        description="Action: generate (HTML) or data (raw data only)",
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Project display name (defaults to character_name)",
    )
    rig: Optional[dict] = Field(
        default=None,
        description="Full rig dict (if not provided, uses minimal defaults)",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Path to write HTML file (returns string if None)",
    )


# ---------------------------------------------------------------------------
# Dashboard data collector
# ---------------------------------------------------------------------------


def dashboard_data(rig: dict) -> dict:
    """Collect all data needed for the dashboard from a rig dict.

    Returns a structured dict with:
    - project: name, status, timestamp
    - characters: count, rig completion status
    - panels: count, list with metadata
    - timeline: total duration, scene count, fps
    - color_script: mood summary
    - exports: what's been exported
    """
    char_name = rig.get("character_name", "Unknown")
    project_name = rig.get("project_name", char_name)

    # Character rig completion status
    has_hierarchy = bool(rig.get("hierarchy"))
    has_poses = bool(rig.get("poses"))
    has_timeline = bool(rig.get("timeline"))
    has_skeleton = bool(rig.get("skeleton"))

    # Panel data
    storyboard = rig.get("storyboard", {})
    panels = storyboard.get("panels", [])
    panels_sorted = sorted(panels, key=lambda p: p.get("number", 0))

    # Timeline calculations
    timeline = rig.get("timeline", {"fps": 24})
    fps = timeline.get("fps", 24)
    total_frames = sum(p.get("duration_frames", 24) for p in panels)
    total_seconds = round(total_frames / fps, 2) if fps > 0 else 0

    # Scene count (unique scene_ids or panel count if no scenes)
    scene_ids = set()
    for p in panels:
        sid = p.get("scene_id", p.get("number", 0))
        scene_ids.add(sid)
    scene_count = len(scene_ids) if scene_ids else 0

    # Color script summary
    color_script = rig.get("color_script", [])
    mood_summary = {}
    for entry in color_script:
        mood = entry.get("mood", "neutral")
        mood_summary[mood] = mood_summary.get(mood, 0) + 1

    # Export status
    exports = rig.get("exports", {})

    return {
        "project": {
            "name": project_name,
            "character": char_name,
            "status": "active",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "characters": {
            "count": 1,
            "rig_status": {
                "has_hierarchy": has_hierarchy,
                "has_poses": has_poses,
                "has_timeline": has_timeline,
                "has_skeleton": has_skeleton,
            },
        },
        "panels": {
            "count": len(panels),
            "list": [
                {
                    "number": p.get("number", 0),
                    "description": p.get("description", ""),
                    "camera": p.get("camera", "medium"),
                    "duration_frames": p.get("duration_frames", 24),
                }
                for p in panels_sorted
            ],
        },
        "timeline": {
            "fps": fps,
            "total_frames": total_frames,
            "total_seconds": total_seconds,
            "scene_count": scene_count,
        },
        "color_script": {
            "mood_summary": mood_summary,
            "scene_count": len(color_script),
        },
        "exports": exports,
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: #1a1a2e;
    color: #eee;
    margin: 0;
    padding: 20px;
}
.dashboard {
    max-width: 1200px;
    margin: 0 auto;
}
h1 {
    color: #e94560;
    margin-bottom: 5px;
}
.subtitle {
    color: #888;
    font-size: 14px;
    margin-bottom: 30px;
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
}
.card {
    background: #16213e;
    border-radius: 12px;
    padding: 20px;
    border: 1px solid #0f3460;
}
.card h2 {
    color: #e94560;
    font-size: 16px;
    margin-top: 0;
    margin-bottom: 12px;
    border-bottom: 1px solid #0f3460;
    padding-bottom: 8px;
}
.stat {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 14px;
}
.stat .label { color: #888; }
.stat .value { color: #fff; font-weight: 600; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
}
.badge-yes { background: #27ae60; color: #fff; }
.badge-no { background: #555; color: #aaa; }
.panel-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.panel-table th {
    text-align: left;
    color: #888;
    padding: 6px 8px;
    border-bottom: 1px solid #0f3460;
}
.panel-table td {
    padding: 6px 8px;
    border-bottom: 1px solid #0f3460;
}
"""


def generate_dashboard(rig: dict, output_path: Optional[str] = None) -> str:
    """Generate a self-contained HTML dashboard for the project.

    Args:
        rig: Full rig dict.
        output_path: If provided, writes HTML to this path.

    Returns:
        HTML string.
    """
    data = dashboard_data(rig)
    proj = data["project"]
    chars = data["characters"]
    panels = data["panels"]
    timeline = data["timeline"]
    color_script = data["color_script"]
    exports = data["exports"]

    esc = html_module.escape

    # Build rig status badges
    rig_status = chars["rig_status"]
    status_badges = []
    for key, has_it in rig_status.items():
        label = key.replace("has_", "").replace("_", " ").title()
        badge_class = "badge-yes" if has_it else "badge-no"
        status_badges.append(f'<span class="badge {badge_class}">{esc(label)}</span>')

    # Build panel table rows
    panel_rows = []
    for p in panels["list"]:
        panel_rows.append(
            f'<tr>'
            f'<td>#{p["number"]}</td>'
            f'<td>{esc(p["description"])}</td>'
            f'<td>{esc(p["camera"])}</td>'
            f'<td>{p["duration_frames"]}f</td>'
            f'</tr>'
        )

    # Build mood summary
    mood_parts = []
    for mood, count in color_script["mood_summary"].items():
        mood_parts.append(f'{esc(mood)}: {count}')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{esc(proj["name"])} — Storyboard Dashboard</title>
    <style>{_CSS}</style>
</head>
<body>
<div class="dashboard">
    <h1>{esc(proj["name"])}</h1>
    <div class="subtitle">Character: {esc(proj["character"])} | Generated: {esc(proj["timestamp"])}</div>

    <div class="grid">
        <div class="card">
            <h2>Character Rig</h2>
            <div class="stat"><span class="label">Character</span><span class="value">{esc(proj["character"])}</span></div>
            <div class="stat"><span class="label">Components</span><span class="value">{" ".join(status_badges)}</span></div>
        </div>

        <div class="card">
            <h2>Timeline</h2>
            <div class="stat"><span class="label">FPS</span><span class="value">{timeline["fps"]}</span></div>
            <div class="stat"><span class="label">Total Frames</span><span class="value">{timeline["total_frames"]}</span></div>
            <div class="stat"><span class="label">Duration</span><span class="value">{timeline["total_seconds"]}s</span></div>
            <div class="stat"><span class="label">Scenes</span><span class="value">{timeline["scene_count"]}</span></div>
        </div>

        <div class="card">
            <h2>Panels</h2>
            <div class="stat"><span class="label">Total</span><span class="value">{panels["count"]}</span></div>
        </div>

        <div class="card">
            <h2>Color Script</h2>
            <div class="stat"><span class="label">Scenes</span><span class="value">{color_script["scene_count"]}</span></div>
            <div class="stat"><span class="label">Moods</span><span class="value">{", ".join(mood_parts) if mood_parts else "None"}</span></div>
        </div>
    </div>

    <div class="card" style="margin-bottom: 30px;">
        <h2>Panel Details</h2>
        <table class="panel-table">
            <thead>
                <tr><th>#</th><th>Description</th><th>Camera</th><th>Duration</th></tr>
            </thead>
            <tbody>
                {"".join(panel_rows) if panel_rows else "<tr><td colspan='4' style='color:#888'>No panels yet</td></tr>"}
            </tbody>
        </table>
    </div>
</div>
</body>
</html>"""

    if output_path:
        import os
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(html)

    return html


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_project_dashboard tool."""

    @mcp.tool(
        name="adobe_ai_project_dashboard",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_project_dashboard(params: AiProjectDashboardInput) -> str:
        """Generate HTML overview of the storyboard project.

        Actions:
        - generate: produce a self-contained HTML dashboard
        - data: collect dashboard data without HTML generation
        """
        action = params.action.lower().strip()
        rig = params.rig or {"character_name": params.character_name}
        if params.project_name:
            rig["project_name"] = params.project_name

        if action == "generate":
            html_str = generate_dashboard(rig, params.output_path)
            result = {
                "action": "generate",
                "html_length": len(html_str),
            }
            if params.output_path:
                result["output_path"] = params.output_path
            else:
                result["html"] = html_str
            return json.dumps(result, indent=2)

        elif action == "data":
            data = dashboard_data(rig)
            return json.dumps({
                "action": "data",
                **data,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["generate", "data"],
            })
