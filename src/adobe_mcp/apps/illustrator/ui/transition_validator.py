"""Check spatial continuity between storyboard panels.

Validates the 180-degree rule, screen direction consistency,
and scale jump appropriateness across adjacent panels.

Pure Python — no JSX or Adobe required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiTransitionValidatorInput(BaseModel):
    """Validate spatial continuity between panels."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="validate",
        description="Action: validate (single pair) or sequence (all consecutive pairs)",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    panel_a: Optional[dict] = Field(
        default=None,
        description="First panel data (characters, camera, direction)",
    )
    panel_b: Optional[dict] = Field(
        default=None,
        description="Second panel data (characters, camera, direction)",
    )
    panels: Optional[list[dict]] = Field(
        default=None,
        description="Ordered list of panels for sequence validation",
    )


# ---------------------------------------------------------------------------
# Scale classification for jump detection
# ---------------------------------------------------------------------------

# Camera scales ordered from wide to tight
SCALE_ORDER = ["wide", "medium_wide", "medium", "medium_close", "close_up", "extreme_close_up"]

_SCALE_INDEX = {s: i for i, s in enumerate(SCALE_ORDER)}


def _scale_distance(scale_a: str, scale_b: str) -> int:
    """Compute the ordinal distance between two camera scales."""
    idx_a = _SCALE_INDEX.get(scale_a, -1)
    idx_b = _SCALE_INDEX.get(scale_b, -1)
    if idx_a < 0 or idx_b < 0:
        return 0
    return abs(idx_a - idx_b)


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


def _check_180_degree_rule(panel_a: dict, panel_b: dict) -> Optional[dict]:
    """Check if the 180-degree rule is maintained between two panels.

    If two characters face each other in panel A, they should maintain
    their relative left/right screen positions in panel B.

    Panel format expected:
        {"characters": [
            {"name": "A", "screen_x": 200, "facing": "right"},
            {"name": "B", "screen_x": 600, "facing": "left"},
        ]}
    """
    chars_a = panel_a.get("characters", [])
    chars_b = panel_b.get("characters", [])

    if len(chars_a) < 2 or len(chars_b) < 2:
        return None  # Rule only applies with 2+ characters

    # Build name-to-position maps
    pos_a = {c.get("name"): c.get("screen_x", 0) for c in chars_a}
    pos_b = {c.get("name"): c.get("screen_x", 0) for c in chars_b}

    # Check each pair of characters that appears in both panels
    for i, ca1 in enumerate(chars_a):
        for ca2 in chars_a[i + 1:]:
            name1 = ca1.get("name")
            name2 = ca2.get("name")

            if name1 not in pos_b or name2 not in pos_b:
                continue

            # Relative position in panel A
            a_order = pos_a[name1] < pos_a[name2]  # True if name1 is left of name2

            # Relative position in panel B
            b_order = pos_b[name1] < pos_b[name2]

            if a_order != b_order:
                return {
                    "rule": "180_degree",
                    "description": (
                        f"Characters '{name1}' and '{name2}' swap screen positions "
                        f"between panels, violating the 180-degree rule."
                    ),
                    "characters": [name1, name2],
                }

    return None


def _check_screen_direction(panel_a: dict, panel_b: dict) -> Optional[dict]:
    """Check screen direction consistency.

    If a character is moving in a direction in panel A, they should
    continue in that direction in panel B (unless it's a deliberate cut).
    """
    dir_a = panel_a.get("movement_direction")
    dir_b = panel_b.get("movement_direction")

    if dir_a is None or dir_b is None:
        return None  # Can't check without direction info

    # Check if directions are contradictory
    # "left" vs "right" is a violation; "left" vs "left" is fine
    opposites = {
        ("left", "right"),
        ("right", "left"),
        ("up", "down"),
        ("down", "up"),
    }

    if (dir_a, dir_b) in opposites:
        is_cut = panel_b.get("is_cut", False)
        if not is_cut:
            return {
                "rule": "screen_direction",
                "description": (
                    f"Movement direction changes from '{dir_a}' to '{dir_b}' "
                    f"without a cut, breaking screen direction continuity."
                ),
                "direction_a": dir_a,
                "direction_b": dir_b,
            }

    return None


def _check_scale_jump(panel_a: dict, panel_b: dict) -> Optional[dict]:
    """Check for jarring scale jumps between panels.

    A jump between two similar scales of different subjects is jarring.
    A jump from wide to close-up (or vice versa) is acceptable.
    Same-scale cuts of the same subject are fine.
    """
    scale_a = panel_a.get("camera_scale", "medium")
    scale_b = panel_b.get("camera_scale", "medium")
    subject_a = panel_a.get("subject")
    subject_b = panel_b.get("subject")

    distance = _scale_distance(scale_a, scale_b)

    # Small scale jump (0 or 1 step) with different subjects is jarring
    if distance <= 1 and distance > 0 and subject_a != subject_b:
        return {
            "rule": "scale_jump",
            "description": (
                f"Small scale jump from '{scale_a}' to '{scale_b}' with "
                f"different subjects ('{subject_a}' → '{subject_b}') may be jarring. "
                f"Consider a more dramatic scale change or matching subjects."
            ),
            "scale_a": scale_a,
            "scale_b": scale_b,
            "distance": distance,
        }

    return None


def validate_transition(panel_a: dict, panel_b: dict) -> dict:
    """Validate spatial continuity between two consecutive panels.

    Checks:
    - 180-degree rule
    - Screen direction consistency
    - Scale jump appropriateness

    Returns:
        Dict with 'valid' bool and list of 'issues'.
    """
    issues = []

    issue = _check_180_degree_rule(panel_a, panel_b)
    if issue:
        issues.append(issue)

    issue = _check_screen_direction(panel_a, panel_b)
    if issue:
        issues.append(issue)

    issue = _check_scale_jump(panel_a, panel_b)
    if issue:
        issues.append(issue)

    return {
        "valid": len(issues) == 0,
        "issues": issues,
    }


def validate_sequence(panels: list[dict]) -> dict:
    """Validate all consecutive panel pairs in a sequence.

    Returns:
        Dict with overall valid status, per-pair results, and issue summary.
    """
    if len(panels) < 2:
        return {
            "valid": True,
            "pair_count": 0,
            "pairs": [],
            "total_issues": 0,
        }

    pairs = []
    total_issues = 0
    all_valid = True

    for i in range(len(panels) - 1):
        result = validate_transition(panels[i], panels[i + 1])
        pair_result = {
            "panels": [i, i + 1],
            "valid": result["valid"],
            "issues": result["issues"],
        }
        pairs.append(pair_result)
        total_issues += len(result["issues"])
        if not result["valid"]:
            all_valid = False

    return {
        "valid": all_valid,
        "pair_count": len(pairs),
        "pairs": pairs,
        "total_issues": total_issues,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_transition_validator tool."""

    @mcp.tool(
        name="adobe_ai_transition_validator",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_transition_validator(params: AiTransitionValidatorInput) -> str:
        """Check spatial continuity between storyboard panels.

        Actions:
        - validate: check a single pair of panels
        - sequence: check all consecutive pairs in a sequence
        """
        action = params.action.lower().strip()

        if action == "validate":
            if params.panel_a is None or params.panel_b is None:
                return json.dumps({"error": "panel_a and panel_b required"})
            result = validate_transition(params.panel_a, params.panel_b)
            return json.dumps({
                "action": "validate",
                **result,
            }, indent=2)

        elif action == "sequence":
            if not params.panels or len(params.panels) < 2:
                return json.dumps({"error": "panels list with >=2 panels required"})
            result = validate_sequence(params.panels)
            return json.dumps({
                "action": "sequence",
                **result,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["validate", "sequence"],
            })
