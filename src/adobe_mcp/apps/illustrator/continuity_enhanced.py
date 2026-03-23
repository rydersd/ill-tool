"""Enhanced continuity tracker for cross-panel character consistency.

Analyzes character scale, eyeline, and prop consistency across storyboard
panels using rig data and storyboard panel metadata.  All logic is pure
Python data comparison.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiContinuityEnhancedInput(BaseModel):
    """Cross-panel analysis of character consistency using landmarks."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: check_scale, check_eyeline, check_props, full_report"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    scale_tolerance_pct: float = Field(
        default=15.0,
        description="Maximum allowed scale variation percentage between panels",
        ge=1.0, le=100.0,
    )
    eyeline_tolerance_pct: float = Field(
        default=10.0,
        description="Maximum allowed eyeline height variation percentage",
        ge=1.0, le=100.0,
    )


# ---------------------------------------------------------------------------
# Panel data helpers
# ---------------------------------------------------------------------------


def _get_panels_with_snapshots(rig: dict) -> list[dict]:
    """Get panels that have character snapshot data, sorted by number."""
    panels = rig.get("storyboard", {}).get("panels", [])
    result = []
    for p in panels:
        if p.get("character_snapshot"):
            result.append(p)
    return sorted(result, key=lambda p: p.get("number", 0))


def _get_bounding_box(snapshot: dict) -> Optional[dict]:
    """Extract bounding box from a character snapshot.

    Returns {width, height, area} or None if not available.
    """
    bbox = snapshot.get("bounding_box")
    if bbox and "width" in bbox and "height" in bbox:
        return {
            "width": bbox["width"],
            "height": bbox["height"],
            "area": bbox["width"] * bbox["height"],
        }
    # Fall back to proportions data if available
    proportions = snapshot.get("proportions", {})
    if "full_body" in proportions:
        fb = proportions["full_body"]
        return {
            "width": fb.get("width", 0),
            "height": fb.get("height", 0),
            "area": fb.get("width", 0) * fb.get("height", 0),
        }
    return None


def _get_eyeline_y(snapshot: dict) -> Optional[float]:
    """Extract eye Y position from character snapshot.

    Returns the Y coordinate of the eyes, or None if not available.
    Uses landmarks, proportions, or bounding_box to estimate.
    """
    # Check for explicit eye landmarks
    landmarks = snapshot.get("landmarks", {})
    for key in ("eye_l", "eye_r", "eyes", "eye_center"):
        if key in landmarks and "y" in landmarks[key]:
            return landmarks[key]["y"]

    # Estimate from bounding box: eyes at ~15% from top of character
    bbox = snapshot.get("bounding_box")
    if bbox and "top" in bbox and "height" in bbox:
        return bbox["top"] + bbox["height"] * 0.15

    return None


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def check_scale(panels: list[dict], tolerance_pct: float) -> dict:
    """Compare character bounding box size across panels.

    Flags any panel where the character area deviates by more than
    tolerance_pct from the reference panel (first panel).
    """
    if len(panels) < 2:
        return {
            "check": "scale",
            "status": "skipped",
            "reason": "Need at least 2 panels with character data",
            "panel_count": len(panels),
        }

    ref_panel = panels[0]
    ref_snapshot = ref_panel["character_snapshot"]
    ref_bbox = _get_bounding_box(ref_snapshot)

    if ref_bbox is None or ref_bbox["area"] <= 0:
        return {
            "check": "scale",
            "status": "skipped",
            "reason": "Reference panel has no bounding box data",
        }

    ref_area = ref_bbox["area"]
    tolerance_frac = tolerance_pct / 100.0
    issues = []

    for panel in panels[1:]:
        snapshot = panel["character_snapshot"]
        bbox = _get_bounding_box(snapshot)
        if bbox is None or bbox["area"] <= 0:
            continue

        deviation = abs(bbox["area"] - ref_area) / ref_area
        deviation_pct = round(deviation * 100, 1)

        if deviation > tolerance_frac:
            issues.append({
                "panel": panel.get("number"),
                "area": round(bbox["area"], 1),
                "reference_area": round(ref_area, 1),
                "deviation_pct": deviation_pct,
                "exceeds_tolerance": True,
            })

    return {
        "check": "scale",
        "status": "pass" if not issues else "fail",
        "reference_panel": ref_panel.get("number"),
        "reference_area": round(ref_area, 1),
        "tolerance_pct": tolerance_pct,
        "panels_checked": len(panels) - 1,
        "issues": issues,
        "issue_count": len(issues),
    }


def check_eyeline(panels: list[dict], tolerance_pct: float) -> dict:
    """Verify character eye positions are at consistent height across panels.

    For dialogue scenes, eye positions should be roughly at the same
    Y coordinate (relative to panel height) for continuity.
    """
    eyeline_data = []
    for panel in panels:
        snapshot = panel["character_snapshot"]
        eye_y = _get_eyeline_y(snapshot)
        if eye_y is not None:
            eyeline_data.append({
                "panel": panel.get("number"),
                "eye_y": eye_y,
            })

    if len(eyeline_data) < 2:
        return {
            "check": "eyeline",
            "status": "skipped",
            "reason": "Need at least 2 panels with eyeline data",
            "panels_with_data": len(eyeline_data),
        }

    ref_y = eyeline_data[0]["eye_y"]
    tolerance_frac = tolerance_pct / 100.0
    issues = []

    for entry in eyeline_data[1:]:
        if ref_y == 0:
            continue
        deviation = abs(entry["eye_y"] - ref_y) / abs(ref_y) if ref_y != 0 else 0
        deviation_pct = round(deviation * 100, 1)

        if deviation > tolerance_frac:
            issues.append({
                "panel": entry["panel"],
                "eye_y": round(entry["eye_y"], 2),
                "reference_eye_y": round(ref_y, 2),
                "deviation_pct": deviation_pct,
                "exceeds_tolerance": True,
            })

    return {
        "check": "eyeline",
        "status": "pass" if not issues else "fail",
        "reference_panel": eyeline_data[0]["panel"],
        "reference_eye_y": round(ref_y, 2),
        "tolerance_pct": tolerance_pct,
        "panels_checked": len(eyeline_data) - 1,
        "issues": issues,
        "issue_count": len(issues),
    }


def check_props(rig: dict, panels: list[dict]) -> dict:
    """Check if props from asset_registry appear consistently across panels.

    Cross-references the asset_registry with per-panel data to find
    missing props.
    """
    asset_entries = rig.get("asset_registry", [])

    # Build a map of panel -> expected props
    expected_props = {}
    for entry in asset_entries:
        if entry.get("type") == "prop":
            pnum = entry.get("panel")
            name = entry.get("name", "")
            if pnum is not None:
                expected_props.setdefault(pnum, set()).add(name)

    if not expected_props:
        return {
            "check": "props",
            "status": "skipped",
            "reason": "No props registered in asset_registry",
        }

    # Check each panel's snapshot for listed props
    issues = []
    for panel in panels:
        pnum = panel.get("number")
        if pnum not in expected_props:
            continue

        snapshot = panel.get("character_snapshot", {})
        present_props = set(snapshot.get("props", []))
        missing = expected_props[pnum] - present_props

        if missing:
            issues.append({
                "panel": pnum,
                "missing_props": sorted(missing),
                "expected": sorted(expected_props[pnum]),
                "present": sorted(present_props),
            })

    return {
        "check": "props",
        "status": "pass" if not issues else "fail",
        "panels_with_props": len(expected_props),
        "issues": issues,
        "issue_count": len(issues),
    }


def full_report(rig: dict, panels: list[dict],
                scale_tolerance: float, eyeline_tolerance: float) -> dict:
    """Run all continuity checks and return unified report."""
    scale_result = check_scale(panels, scale_tolerance)
    eyeline_result = check_eyeline(panels, eyeline_tolerance)
    props_result = check_props(rig, panels)

    total_issues = (
        scale_result.get("issue_count", 0)
        + eyeline_result.get("issue_count", 0)
        + props_result.get("issue_count", 0)
    )

    return {
        "report": "full_continuity",
        "total_panels": len(panels),
        "total_issues": total_issues,
        "overall_status": "pass" if total_issues == 0 else "fail",
        "scale": scale_result,
        "eyeline": eyeline_result,
        "props": props_result,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_continuity_enhanced tool."""

    @mcp.tool(
        name="adobe_ai_continuity_enhanced",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_continuity_enhanced(params: AiContinuityEnhancedInput) -> str:
        """Cross-panel analysis of character consistency using landmarks.

        Actions:
        - check_scale: compare character bounding box size across panels
        - check_eyeline: verify eye positions are at consistent height
        - check_props: check if registered props appear consistently
        - full_report: run all checks and return unified report
        """
        rig = _load_rig(params.character_name)
        panels = _get_panels_with_snapshots(rig)
        action = params.action.lower().strip()

        if action == "check_scale":
            result = check_scale(panels, params.scale_tolerance_pct)
        elif action == "check_eyeline":
            result = check_eyeline(panels, params.eyeline_tolerance_pct)
        elif action == "check_props":
            result = check_props(rig, panels)
        elif action == "full_report":
            result = full_report(
                rig, panels,
                params.scale_tolerance_pct,
                params.eyeline_tolerance_pct,
            )
        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["check_scale", "check_eyeline", "check_props", "full_report"],
            })

        result["character_name"] = params.character_name
        return json.dumps(result, indent=2)
