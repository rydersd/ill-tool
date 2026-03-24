"""Check character visual consistency across storyboard panels.

Compares stored character template/path data across panels to detect
color drift, proportion changes, and missing costume elements.

All logic is pure Python data comparison -- no Adobe calls required
for the check itself.
"""

import json

from adobe_mcp.apps.illustrator.models import AiContinuityCheckInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig


# Tolerance for color comparison (per RGB channel, 0-255 scale)
COLOR_TOLERANCE = 10

# Tolerance for proportion comparison (ratio difference)
PROPORTION_TOLERANCE = 0.15


def _compare_colors(color_a: dict | None, color_b: dict | None) -> dict:
    """Compare two RGB color dicts and report differences.

    Each color is {"r": int, "g": int, "b": int} or None.
    Returns a result dict with pass/fail and details.
    """
    if color_a is None and color_b is None:
        return {"match": True, "detail": "both unfilled"}
    if color_a is None or color_b is None:
        return {
            "match": False,
            "detail": "one has fill, the other does not",
            "a": color_a,
            "b": color_b,
        }

    diffs = {}
    total_diff = 0
    for ch in ("r", "g", "b"):
        va = color_a.get(ch, 0)
        vb = color_b.get(ch, 0)
        d = abs(va - vb)
        if d > COLOR_TOLERANCE:
            diffs[ch] = {"a": va, "b": vb, "diff": d}
        total_diff += d

    if diffs:
        return {"match": False, "channel_diffs": diffs, "total_diff": total_diff}
    return {"match": True, "total_diff": total_diff}


def _compare_proportions(parts_a: dict, parts_b: dict) -> dict:
    """Compare relative body part sizes between two snapshots.

    Each snapshot is a dict of part_name -> {"width": float, "height": float}.
    Compares width/height ratios between corresponding parts.
    """
    common_parts = set(parts_a.keys()) & set(parts_b.keys())
    if not common_parts:
        return {
            "match": True,
            "detail": "no common parts to compare",
            "parts_a": sorted(parts_a.keys()),
            "parts_b": sorted(parts_b.keys()),
        }

    mismatches = []
    for part in sorted(common_parts):
        a = parts_a[part]
        b = parts_b[part]

        # Compare width ratio
        aw = a.get("width", 1)
        bw = b.get("width", 1)
        if aw > 0 and bw > 0:
            ratio = max(aw, bw) / min(aw, bw)
            if ratio - 1.0 > PROPORTION_TOLERANCE:
                mismatches.append({
                    "part": part,
                    "dimension": "width",
                    "panel_a": aw,
                    "panel_b": bw,
                    "ratio": round(ratio, 3),
                })

        # Compare height ratio
        ah = a.get("height", 1)
        bh = b.get("height", 1)
        if ah > 0 and bh > 0:
            ratio = max(ah, bh) / min(ah, bh)
            if ratio - 1.0 > PROPORTION_TOLERANCE:
                mismatches.append({
                    "part": part,
                    "dimension": "height",
                    "panel_a": ah,
                    "panel_b": bh,
                    "ratio": round(ratio, 3),
                })

    if mismatches:
        return {"match": False, "mismatches": mismatches}
    return {"match": True, "parts_checked": len(common_parts)}


def _check_costume_elements(expected: list[str], actual: list[str]) -> dict:
    """Check that all expected costume elements are present.

    Returns missing and extra elements.
    """
    expected_set = set(expected)
    actual_set = set(actual)

    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)

    if missing:
        return {
            "match": False,
            "missing": missing,
            "extra": extra,
        }
    return {
        "match": True,
        "extra": extra,
        "element_count": len(actual_set),
    }


def _run_continuity_check(rig: dict, check_type: str) -> dict:
    """Run the continuity check against stored panel snapshots.

    Looks at rig["storyboard"]["panels"] for per-panel character data
    and rig["character_template"] (or poses/bindings) for reference.
    """
    panels = rig.get("storyboard", {}).get("panels", [])
    if len(panels) < 2:
        return {
            "status": "skipped",
            "reason": "Need at least 2 panels for continuity check.",
            "panel_count": len(panels),
        }

    # Gather per-panel character snapshots from the rig
    # Each panel may have a "character_snapshot" with colors, proportions, parts
    snapshots = {}
    for panel in panels:
        pnum = panel.get("number")
        snapshot = panel.get("character_snapshot")
        if snapshot and pnum is not None:
            snapshots[pnum] = snapshot

    if len(snapshots) < 2:
        return {
            "status": "skipped",
            "reason": "Need character snapshot data in at least 2 panels. "
                      "Run pose capture or character placement first.",
            "panels_with_data": list(snapshots.keys()),
        }

    # Use the first panel as the reference
    panel_nums = sorted(snapshots.keys())
    reference_num = panel_nums[0]
    reference = snapshots[reference_num]

    issues = []

    for pnum in panel_nums[1:]:
        current = snapshots[pnum]
        panel_issues = {
            "panel": pnum,
            "compared_to": reference_num,
            "checks": {},
        }

        # Color check
        if check_type in ("full", "colors_only"):
            ref_colors = reference.get("colors", {})
            cur_colors = current.get("colors", {})
            # Compare each named color region
            color_results = {}
            all_regions = set(ref_colors.keys()) | set(cur_colors.keys())
            for region in sorted(all_regions):
                result = _compare_colors(
                    ref_colors.get(region),
                    cur_colors.get(region),
                )
                color_results[region] = result
            panel_issues["checks"]["colors"] = color_results

        # Proportion check
        if check_type in ("full", "proportions_only"):
            ref_props = reference.get("proportions", {})
            cur_props = current.get("proportions", {})
            panel_issues["checks"]["proportions"] = _compare_proportions(
                ref_props, cur_props,
            )

        # Costume check
        if check_type in ("full", "costume_only"):
            ref_costume = reference.get("costume_elements", [])
            cur_costume = current.get("costume_elements", [])
            panel_issues["checks"]["costume"] = _check_costume_elements(
                ref_costume, cur_costume,
            )

        # Determine if any check failed
        has_failure = False
        for check_name, check_result in panel_issues["checks"].items():
            if isinstance(check_result, dict):
                if check_result.get("match") is False:
                    has_failure = True
                    break
                # For nested color results (dict of dicts)
                if check_name == "colors":
                    for region_result in check_result.values():
                        if isinstance(region_result, dict) and region_result.get("match") is False:
                            has_failure = True
                            break

        panel_issues["has_issues"] = has_failure
        issues.append(panel_issues)

    # Summary
    panels_with_issues = [i["panel"] for i in issues if i.get("has_issues")]
    return {
        "status": "completed",
        "check_type": check_type,
        "reference_panel": reference_num,
        "panels_checked": len(issues),
        "panels_with_issues": panels_with_issues,
        "issue_count": len(panels_with_issues),
        "details": issues,
    }


def register(mcp):
    """Register the adobe_ai_continuity_check tool."""

    @mcp.tool(
        name="adobe_ai_continuity_check",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_continuity_check(params: AiContinuityCheckInput) -> str:
        """Check character consistency across storyboard panels.

        Compares color consistency, body proportions, and costume elements
        between the first panel and all subsequent panels.

        Check types:
        - full: all checks (colors, proportions, costume)
        - colors_only: just color consistency
        - proportions_only: just proportion matching
        - costume_only: just costume element presence
        """
        rig = _load_rig(params.character_name)
        check_type = params.check_type.lower().strip()

        valid_types = {"full", "colors_only", "proportions_only", "costume_only"}
        if check_type not in valid_types:
            return json.dumps({
                "error": f"Invalid check_type: {check_type}",
                "valid_types": sorted(valid_types),
            })

        result = _run_continuity_check(rig, check_type)
        result["character_name"] = params.character_name
        return json.dumps(result, indent=2)
