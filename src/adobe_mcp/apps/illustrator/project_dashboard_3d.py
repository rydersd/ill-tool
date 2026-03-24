"""Enhanced project dashboard with 3D pipeline status.

Extends the project dashboard with 3D mesh status, pipeline completion
tracking, and format export availability. Generates a self-contained
HTML dashboard showing both 2D and 3D pipeline progress.

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


class AiProjectDashboard3dInput(BaseModel):
    """Enhanced project dashboard with 3D status."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="generate",
        description="Action: generate (HTML) or data (raw data only)",
    )
    character_name: str = Field(
        default="character",
        description="Character / project identifier",
    )
    rig: Optional[dict] = Field(
        default=None,
        description="Full rig dict with 2D and 3D pipeline data",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Path to write HTML file (returns string if None)",
    )


# ---------------------------------------------------------------------------
# Pipeline step definitions for completion tracking
# ---------------------------------------------------------------------------

PIPELINE_STEPS_2D = [
    "image_loaded",
    "threshold_traced",
    "contours_detected",
    "skeleton_built",
    "parts_bound",
    "poses_defined",
    "timeline_set",
]

PIPELINE_STEPS_3D = [
    "mesh_generated",
    "mesh_textured",
    "turnaround_rendered",
    "3d_rig_created",
    "animations_exported",
]


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def collect_3d_status(rig: dict) -> dict:
    """Check 3D mesh status, quality, and available format exports.

    Examines the rig dict for 3D-related data:
    - mesh_3d: whether a 3D mesh exists and its quality metrics
    - exports: which 3D export formats have been generated
    - turnaround: whether turnaround views exist

    Args:
        rig: full rig dict.

    Returns:
        dict with 3D status information.
    """
    mesh_3d = rig.get("mesh_3d", {})
    has_mesh = bool(mesh_3d)

    # Mesh quality score (0-100) based on available data
    quality_score = 0
    quality_details = {}

    if has_mesh:
        vertex_count = mesh_3d.get("vertex_count", 0)
        face_count = mesh_3d.get("face_count", 0)
        has_uvs = mesh_3d.get("has_uvs", False)
        has_normals = mesh_3d.get("has_normals", False)
        has_texture = mesh_3d.get("has_texture", False)

        # Score components
        if vertex_count > 0:
            quality_score += 20
        if vertex_count > 1000:
            quality_score += 10
        if face_count > 0:
            quality_score += 20
        if has_uvs:
            quality_score += 20
        if has_normals:
            quality_score += 15
        if has_texture:
            quality_score += 15

        quality_details = {
            "vertex_count": vertex_count,
            "face_count": face_count,
            "has_uvs": has_uvs,
            "has_normals": has_normals,
            "has_texture": has_texture,
        }

    # Check available 3D exports
    exports_3d = rig.get("exports_3d", {})
    available_formats = []
    for fmt_name, fmt_data in exports_3d.items():
        if isinstance(fmt_data, dict):
            available_formats.append({
                "format": fmt_name,
                "path": fmt_data.get("path", ""),
                "exported": bool(fmt_data.get("exported", False)),
            })
        elif isinstance(fmt_data, str):
            available_formats.append({
                "format": fmt_name,
                "path": fmt_data,
                "exported": True,
            })

    # Turnaround status
    turnaround = rig.get("turnaround", {})
    has_turnaround = bool(turnaround)
    turnaround_views = turnaround.get("view_count", 0) if has_turnaround else 0

    return {
        "has_mesh": has_mesh,
        "quality_score": quality_score,
        "quality_details": quality_details,
        "export_formats": available_formats,
        "export_count": len(available_formats),
        "has_turnaround": has_turnaround,
        "turnaround_views": turnaround_views,
    }


def collect_pipeline_status(rig: dict) -> dict:
    """Compute overall pipeline completion for 2D and 3D tracks.

    Checks which pipeline steps have been completed by looking at
    corresponding keys in the rig dict.

    Args:
        rig: full rig dict.

    Returns:
        dict with completion counts and percentages for each track.
    """
    # 2D pipeline status
    step_checks_2d = {
        "image_loaded": bool(rig.get("source_image") or rig.get("image_path")),
        "threshold_traced": bool(rig.get("traced") or rig.get("contours")),
        "contours_detected": bool(rig.get("contours") or rig.get("shapes")),
        "skeleton_built": bool(rig.get("skeleton") or rig.get("joints")),
        "parts_bound": bool(rig.get("bindings") or rig.get("part_bindings")),
        "poses_defined": bool(rig.get("poses")),
        "timeline_set": bool(rig.get("timeline")),
    }

    # 3D pipeline status
    step_checks_3d = {
        "mesh_generated": bool(rig.get("mesh_3d")),
        "mesh_textured": bool(
            rig.get("mesh_3d", {}).get("has_texture")
            or rig.get("texture")
        ),
        "turnaround_rendered": bool(rig.get("turnaround")),
        "3d_rig_created": bool(rig.get("rig_3d")),
        "animations_exported": bool(rig.get("exports_3d")),
    }

    completed_2d = sum(1 for v in step_checks_2d.values() if v)
    completed_3d = sum(1 for v in step_checks_3d.values() if v)
    total_2d = len(PIPELINE_STEPS_2D)
    total_3d = len(PIPELINE_STEPS_3D)

    pct_2d = round(100.0 * completed_2d / total_2d, 1) if total_2d > 0 else 0.0
    pct_3d = round(100.0 * completed_3d / total_3d, 1) if total_3d > 0 else 0.0

    total_all = total_2d + total_3d
    completed_all = completed_2d + completed_3d
    pct_overall = round(100.0 * completed_all / total_all, 1) if total_all > 0 else 0.0

    return {
        "pipeline_2d": {
            "completed": completed_2d,
            "total": total_2d,
            "percentage": pct_2d,
            "steps": step_checks_2d,
        },
        "pipeline_3d": {
            "completed": completed_3d,
            "total": total_3d,
            "percentage": pct_3d,
            "steps": step_checks_3d,
        },
        "overall": {
            "completed": completed_all,
            "total": total_all,
            "percentage": pct_overall,
        },
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_CSS_3D = """
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
.progress-bar {
    height: 8px;
    background: #333;
    border-radius: 4px;
    margin: 8px 0;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
}
.progress-2d { background: #27ae60; }
.progress-3d { background: #3498db; }
.progress-overall { background: #e94560; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    margin: 2px;
}
.badge-yes { background: #27ae60; color: #fff; }
.badge-no { background: #555; color: #aaa; }
.step-list {
    list-style: none;
    padding: 0;
    margin: 0;
}
.step-list li {
    padding: 4px 0;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.step-done { color: #27ae60; }
.step-pending { color: #888; }
"""


def generate_dashboard_html(data: dict) -> str:
    """Generate a self-contained HTML dashboard with 2D and 3D status.

    Args:
        data: dict with pipeline_status, status_3d, and character info.

    Returns:
        Complete HTML string.
    """
    esc = html_module.escape
    char_name = esc(data.get("character_name", "character"))
    timestamp = esc(data.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")))

    pipeline = data.get("pipeline_status", {})
    p2d = pipeline.get("pipeline_2d", {})
    p3d = pipeline.get("pipeline_3d", {})
    overall = pipeline.get("overall", {})

    status_3d = data.get("status_3d", {})

    # Build step lists
    def _step_items(steps: dict) -> str:
        items = []
        for step_name, done in steps.items():
            cls = "step-done" if done else "step-pending"
            icon = "&#10003;" if done else "&#9675;"
            label = step_name.replace("_", " ").title()
            items.append(f'<li class="{cls}">{icon} {esc(label)}</li>')
        return "".join(items)

    steps_2d_html = _step_items(p2d.get("steps", {}))
    steps_3d_html = _step_items(p3d.get("steps", {}))

    # 3D quality
    quality_score = status_3d.get("quality_score", 0)
    has_mesh = status_3d.get("has_mesh", False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{char_name} — 3D Pipeline Dashboard</title>
    <style>{_CSS_3D}</style>
</head>
<body>
<div class="dashboard">
    <h1>{char_name} — Pipeline Dashboard</h1>
    <div class="subtitle">Generated: {timestamp}</div>

    <div class="grid">
        <div class="card">
            <h2>Overall Progress</h2>
            <div class="stat">
                <span class="label">Completion</span>
                <span class="value">{overall.get("percentage", 0)}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill progress-overall"
                     style="width: {overall.get('percentage', 0)}%"></div>
            </div>
            <div class="stat">
                <span class="label">Steps</span>
                <span class="value">{overall.get("completed", 0)} / {overall.get("total", 0)}</span>
            </div>
        </div>

        <div class="card">
            <h2>2D Pipeline</h2>
            <div class="stat">
                <span class="label">Progress</span>
                <span class="value">{p2d.get("percentage", 0)}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill progress-2d"
                     style="width: {p2d.get('percentage', 0)}%"></div>
            </div>
            <ul class="step-list">{steps_2d_html}</ul>
        </div>

        <div class="card">
            <h2>3D Pipeline</h2>
            <div class="stat">
                <span class="label">Progress</span>
                <span class="value">{p3d.get("percentage", 0)}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill progress-3d"
                     style="width: {p3d.get('percentage', 0)}%"></div>
            </div>
            <ul class="step-list">{steps_3d_html}</ul>
        </div>

        <div class="card">
            <h2>3D Mesh Status</h2>
            <div class="stat">
                <span class="label">Mesh</span>
                <span class="value">
                    <span class="badge {"badge-yes" if has_mesh else "badge-no"}">
                        {"Present" if has_mesh else "Not Generated"}
                    </span>
                </span>
            </div>
            <div class="stat">
                <span class="label">Quality Score</span>
                <span class="value">{quality_score}/100</span>
            </div>
            <div class="stat">
                <span class="label">Turnaround</span>
                <span class="value">
                    <span class="badge {"badge-yes" if status_3d.get("has_turnaround") else "badge-no"}">
                        {status_3d.get("turnaround_views", 0)} views
                    </span>
                </span>
            </div>
            <div class="stat">
                <span class="label">Exports</span>
                <span class="value">{status_3d.get("export_count", 0)} formats</span>
            </div>
        </div>
    </div>
</div>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_project_dashboard_3d tool."""

    @mcp.tool(
        name="adobe_ai_project_dashboard_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_project_dashboard_3d(params: AiProjectDashboard3dInput) -> str:
        """Enhanced project dashboard with 3D pipeline status.

        Actions:
        - generate: produce a self-contained HTML dashboard with 2D+3D status
        - data: collect dashboard data without HTML generation
        """
        action = params.action.lower().strip()
        rig = params.rig or {"character_name": params.character_name}

        status_3d = collect_3d_status(rig)
        pipeline_status = collect_pipeline_status(rig)

        dashboard_data = {
            "character_name": params.character_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status_3d": status_3d,
            "pipeline_status": pipeline_status,
        }

        if action == "generate":
            html_str = generate_dashboard_html(dashboard_data)

            if params.output_path:
                import os
                os.makedirs(
                    os.path.dirname(params.output_path) if os.path.dirname(params.output_path) else ".",
                    exist_ok=True,
                )
                with open(params.output_path, "w") as f:
                    f.write(html_str)

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
            return json.dumps({
                "action": "data",
                **dashboard_data,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["generate", "data"],
            })
