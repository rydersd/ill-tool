"""One-click character pipeline orchestrator.

Plans and reports on the full character setup pipeline: from source
image through threshold tracing, contour detection, landmark detection,
part segmentation, and optional 3D mesh generation.  Steps are
selectively included based on available capabilities (ML, 3D libs).

Pure Python — no JSX or Adobe required.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiOneClickCharacterInput(BaseModel):
    """Full character pipeline orchestrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: run, status, resume",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Source character image path (for run/resume)",
    )
    capabilities: Optional[dict[str, bool]] = Field(
        default=None,
        description=(
            "Available capabilities: "
            "{'ml': True/False, '3d': True/False, 'opencv': True/False}"
        ),
    )
    completed_steps: Optional[list[str]] = Field(
        default=None,
        description="List of already-completed step IDs (for resume)",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier",
    )


# ---------------------------------------------------------------------------
# Pipeline step definitions
# ---------------------------------------------------------------------------

# Every step has: id, name, description, required capability (None = always),
# depends_on (list of prerequisite step IDs)
PIPELINE_STEPS = [
    {
        "id": "validate_image",
        "name": "Validate Source Image",
        "description": "Check image exists, is readable, supported format",
        "requires": None,  # Always available
        "depends_on": [],
        "phase": "input",
    },
    {
        "id": "threshold_trace",
        "name": "Threshold Trace",
        "description": "Binary threshold to extract line art from source image",
        "requires": None,
        "depends_on": ["validate_image"],
        "phase": "tracing",
    },
    {
        "id": "contour_detection",
        "name": "Contour Detection",
        "description": "Find and sort contours by area, generate path data",
        "requires": None,
        "depends_on": ["threshold_trace"],
        "phase": "tracing",
    },
    {
        "id": "sdpose_landmarks",
        "name": "SDPose Landmark Detection",
        "description": "ML-based pose estimation for character landmark positions",
        "requires": "ml",
        "depends_on": ["validate_image"],
        "phase": "analysis",
    },
    {
        "id": "cartoonseg_parts",
        "name": "CartoonSeg Part Segmentation",
        "description": "ML-based semantic segmentation of character body parts",
        "requires": "ml",
        "depends_on": ["validate_image"],
        "phase": "analysis",
    },
    {
        "id": "build_skeleton",
        "name": "Build Skeleton",
        "description": "Create joint hierarchy from landmarks and contours",
        "requires": None,
        "depends_on": ["contour_detection"],
        "phase": "rigging",
    },
    {
        "id": "bind_parts",
        "name": "Bind Parts to Skeleton",
        "description": "Associate contour regions with skeleton joints",
        "requires": None,
        "depends_on": ["build_skeleton", "contour_detection"],
        "phase": "rigging",
    },
    {
        "id": "triposr_mesh",
        "name": "TripoSR Quick Mesh",
        "description": "Generate 3D mesh from character image using TripoSR",
        "requires": "3d",
        "depends_on": ["validate_image"],
        "phase": "3d",
    },
    {
        "id": "generate_turnaround",
        "name": "Generate Turnaround Sheet",
        "description": "Create multi-view character sheet from 3D mesh",
        "requires": "3d",
        "depends_on": ["triposr_mesh"],
        "phase": "3d",
    },
    {
        "id": "export_rig",
        "name": "Export Rig Data",
        "description": "Save final rig JSON with joints, hierarchy, and bindings",
        "requires": None,
        "depends_on": ["bind_parts"],
        "phase": "output",
    },
]


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def _detect_capabilities() -> dict[str, bool]:
    """Auto-detect available capabilities by checking for installed packages.

    Returns:
        dict mapping capability names to availability booleans.
    """
    caps = {
        "ml": False,
        "3d": False,
        "opencv": False,
    }

    # Check for OpenCV
    try:
        import cv2  # noqa: F401
        caps["opencv"] = True
    except ImportError:
        pass

    # Check for ML libs (torch as proxy)
    try:
        import torch  # noqa: F401
        caps["ml"] = True
    except ImportError:
        pass

    # Check for 3D libs (trimesh as proxy)
    try:
        import trimesh  # noqa: F401
        caps["3d"] = True
    except ImportError:
        pass

    return caps


def plan_pipeline(
    image_path: Optional[str] = None,
    capabilities: Optional[dict[str, bool]] = None,
) -> dict:
    """Determine which pipeline steps to run based on available capabilities.

    Steps that require unavailable capabilities are marked as skipped.
    Steps are topologically ordered (dependencies before dependents).

    Args:
        image_path: source image path (for validation info).
        capabilities: dict of available capabilities (auto-detected if None).

    Returns:
        dict with included steps, skipped steps, and ordering.
    """
    caps = capabilities if capabilities is not None else _detect_capabilities()

    included = []
    skipped = []

    for step in PIPELINE_STEPS:
        req = step["requires"]

        if req is None or caps.get(req, False):
            included.append({
                "id": step["id"],
                "name": step["name"],
                "description": step["description"],
                "phase": step["phase"],
                "depends_on": step["depends_on"],
            })
        else:
            skipped.append({
                "id": step["id"],
                "name": step["name"],
                "reason": f"Requires '{req}' capability (not available)",
                "phase": step["phase"],
            })

    # Filter out included steps whose dependencies are all skipped
    included_ids = {s["id"] for s in included}
    final_included = []
    final_skipped = list(skipped)

    for step in included:
        deps = step["depends_on"]
        missing_deps = [d for d in deps if d not in included_ids]
        if missing_deps:
            final_skipped.append({
                "id": step["id"],
                "name": step["name"],
                "reason": f"Dependencies not available: {missing_deps}",
                "phase": step["phase"],
            })
        else:
            final_included.append(step)

    return {
        "image_path": image_path,
        "capabilities": caps,
        "included_steps": final_included,
        "skipped_steps": final_skipped,
        "included_count": len(final_included),
        "skipped_count": len(final_skipped),
        "total_steps": len(PIPELINE_STEPS),
        "phases": sorted(set(s["phase"] for s in final_included)),
    }


def pipeline_report(
    completed_steps: list[str],
    skipped_steps: list[str],
    errors: Optional[dict[str, str]] = None,
) -> dict:
    """Generate a structured progress report for the pipeline.

    Args:
        completed_steps: list of step IDs that finished successfully.
        skipped_steps: list of step IDs that were skipped.
        errors: optional dict mapping step IDs to error messages.

    Returns:
        dict with completion percentage, per-step status, and summary.
    """
    errors = errors or {}
    all_step_ids = [s["id"] for s in PIPELINE_STEPS]

    completed_set = set(completed_steps)
    skipped_set = set(skipped_steps)
    error_set = set(errors.keys())

    # Categorize each step
    step_statuses = []
    for step in PIPELINE_STEPS:
        sid = step["id"]
        if sid in error_set:
            status = "error"
        elif sid in completed_set:
            status = "completed"
        elif sid in skipped_set:
            status = "skipped"
        else:
            status = "pending"

        entry = {
            "id": sid,
            "name": step["name"],
            "status": status,
            "phase": step["phase"],
        }
        if sid in errors:
            entry["error_message"] = errors[sid]
        step_statuses.append(entry)

    # Calculate completion — only count non-skipped steps
    actionable = [s for s in step_statuses if s["status"] != "skipped"]
    completed_count = sum(1 for s in actionable if s["status"] == "completed")
    total_actionable = len(actionable)
    pct = round(100.0 * completed_count / total_actionable, 1) if total_actionable > 0 else 0.0

    # Next step to run
    next_step = None
    for s in step_statuses:
        if s["status"] == "pending":
            next_step = s["id"]
            break

    return {
        "completion_pct": pct,
        "completed": completed_count,
        "total_actionable": total_actionable,
        "skipped": len(skipped_set),
        "errors": len(error_set),
        "next_step": next_step,
        "steps": step_statuses,
    }


def compute_resume_plan(
    completed_steps: list[str],
    capabilities: Optional[dict[str, bool]] = None,
) -> dict:
    """Compute the remaining steps for resume, respecting dependencies.

    Args:
        completed_steps: step IDs already finished.
        capabilities: available capabilities.

    Returns:
        dict with remaining steps to run.
    """
    plan = plan_pipeline(capabilities=capabilities)
    completed_set = set(completed_steps)

    remaining = []
    for step in plan["included_steps"]:
        if step["id"] not in completed_set:
            remaining.append(step)

    return {
        "completed": sorted(completed_set),
        "remaining_steps": remaining,
        "remaining_count": len(remaining),
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_one_click_character tool."""

    @mcp.tool(
        name="adobe_ai_one_click_character",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_one_click_character(params: AiOneClickCharacterInput) -> str:
        """Full character pipeline orchestrator.

        Actions:
        - run: plan the full pipeline based on capabilities
        - status: show pipeline step definitions
        - resume: compute remaining steps from partially completed pipeline
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "one_click_character",
                "total_steps": len(PIPELINE_STEPS),
                "step_ids": [s["id"] for s in PIPELINE_STEPS],
                "phases": sorted(set(s["phase"] for s in PIPELINE_STEPS)),
                "ready": True,
            }, indent=2)

        elif action == "run":
            caps = params.capabilities if params.capabilities else _detect_capabilities()
            plan = plan_pipeline(
                image_path=params.image_path,
                capabilities=caps,
            )
            plan["action"] = "run"
            plan["character_name"] = params.character_name
            return json.dumps(plan, indent=2)

        elif action == "resume":
            caps = params.capabilities if params.capabilities else _detect_capabilities()
            completed = params.completed_steps or []
            resume = compute_resume_plan(completed, capabilities=caps)
            resume["action"] = "resume"
            resume["character_name"] = params.character_name
            return json.dumps(resume, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["run", "status", "resume"],
            })
