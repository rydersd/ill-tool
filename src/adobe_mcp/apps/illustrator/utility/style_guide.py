"""Enforce consistent visual style across a project.

Define style rules (stroke weights, color palettes, line caps,
proportions) and validate character rigs against them. Style guides
can be saved/loaded for reuse across projects.

Pure Python implementation.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiStyleGuideInput(BaseModel):
    """Enforce consistent visual style across a project."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: define_style, check_style, save_style, load_style, list_styles",
    )
    style_name: Optional[str] = Field(
        default=None,
        description="Name of the style guide",
    )
    rules: Optional[dict] = Field(
        default=None,
        description="Style rules dict for define_style",
    )
    character_name: Optional[str] = Field(
        default=None,
        description="Character to check against style",
    )
    path: Optional[str] = Field(
        default=None,
        description="File path for save_style / load_style",
    )


# ---------------------------------------------------------------------------
# In-memory style storage
# ---------------------------------------------------------------------------

_styles: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Style rule keys and their validation logic
# ---------------------------------------------------------------------------

_RULE_VALIDATORS = {
    "stroke_weight_range": "range",     # [min, max] — check stroke weights
    "colors": "palette",                 # list of hex strings — check color usage
    "line_cap": "enum",                  # "round", "butt", "projecting"
    "head_body_ratio": "range",          # [min, max] — head size / body height
    "max_parts": "max_int",             # maximum number of parts
    "min_parts": "min_int",             # minimum number of parts
    "allowed_joint_types": "set",        # set of allowed pivot types
    "symmetry_required": "bool",         # whether bilateral symmetry is required
}


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def define_style(style_name: str, rules: dict) -> dict:
    """Define a named style guide with validation rules.

    Supported rules:
        - stroke_weight_range: [min, max] for stroke widths
        - colors: list of allowed hex color strings
        - line_cap: "round", "butt", or "projecting"
        - head_body_ratio: [min, max] for head/body proportion
        - max_parts: maximum number of character parts
        - min_parts: minimum number of character parts
        - allowed_joint_types: list of allowed pivot types
        - symmetry_required: bool

    Args:
        style_name: identifier for this style
        rules: dict of rule names to their values

    Returns:
        Confirmation dict with style name and rule count.
    """
    if not style_name:
        return {"error": "Style name is required"}
    if not rules or not isinstance(rules, dict):
        return {"error": "Rules must be a non-empty dict"}

    _styles[style_name] = dict(rules)

    return {
        "style": style_name,
        "rules_count": len(rules),
        "rules": list(rules.keys()),
    }


def check_style(rig: dict, style_name: str) -> dict:
    """Validate a character rig against a style guide.

    Checks each rule in the style against the rig data and reports
    any violations found.

    Args:
        rig: character rig dict
        style_name: name of the style to check against

    Returns:
        Dict with violations list and pass/fail status.
    """
    if style_name not in _styles:
        return {"error": f"Style '{style_name}' not defined"}

    rules = _styles[style_name]
    violations = []

    # Check stroke_weight_range
    if "stroke_weight_range" in rules:
        weight_range = rules["stroke_weight_range"]
        if isinstance(weight_range, list) and len(weight_range) >= 2:
            min_w, max_w = weight_range[0], weight_range[1]
            # Check any stored stroke weights in the rig
            for part_name, part_data in rig.get("wizard_parts", [{}]):
                if isinstance(part_data, dict):
                    sw = part_data.get("stroke_weight", 0)
                    if sw and (sw < min_w or sw > max_w):
                        violations.append({
                            "rule": "stroke_weight_range",
                            "part": part_name,
                            "value": sw,
                            "expected": weight_range,
                            "message": f"Stroke weight {sw} outside range [{min_w}, {max_w}]",
                        })

    # Check colors
    if "colors" in rules:
        allowed_colors = set(c.lower() for c in rules["colors"])
        for part in _iter_parts(rig):
            color = part.get("color_hex", "").lower()
            if color and color not in allowed_colors:
                violations.append({
                    "rule": "colors",
                    "part": part.get("name", "unknown"),
                    "value": color,
                    "expected": sorted(allowed_colors),
                    "message": f"Color {color} not in allowed palette",
                })

    # Check line_cap
    if "line_cap" in rules:
        expected_cap = rules["line_cap"]
        rig_cap = rig.get("line_cap")
        if rig_cap and rig_cap != expected_cap:
            violations.append({
                "rule": "line_cap",
                "value": rig_cap,
                "expected": expected_cap,
                "message": f"Line cap '{rig_cap}' should be '{expected_cap}'",
            })

    # Check head_body_ratio
    if "head_body_ratio" in rules:
        ratio_range = rules["head_body_ratio"]
        if isinstance(ratio_range, list) and len(ratio_range) >= 2:
            ratio = _compute_head_body_ratio(rig)
            if ratio is not None:
                min_r, max_r = ratio_range[0], ratio_range[1]
                if ratio < min_r or ratio > max_r:
                    violations.append({
                        "rule": "head_body_ratio",
                        "value": round(ratio, 3),
                        "expected": ratio_range,
                        "message": f"Head/body ratio {ratio:.3f} outside range [{min_r}, {max_r}]",
                    })

    # Check max_parts
    if "max_parts" in rules:
        max_p = rules["max_parts"]
        part_count = len(rig.get("joints", {}))
        if part_count > max_p:
            violations.append({
                "rule": "max_parts",
                "value": part_count,
                "expected": max_p,
                "message": f"Part count {part_count} exceeds maximum {max_p}",
            })

    # Check min_parts
    if "min_parts" in rules:
        min_p = rules["min_parts"]
        part_count = len(rig.get("joints", {}))
        if part_count < min_p:
            violations.append({
                "rule": "min_parts",
                "value": part_count,
                "expected": min_p,
                "message": f"Part count {part_count} below minimum {min_p}",
            })

    # Check allowed_joint_types
    if "allowed_joint_types" in rules:
        allowed_types = set(rules["allowed_joint_types"])
        for name, lm_data in rig.get("landmarks", {}).items():
            pivot = lm_data.get("pivot", {})
            ptype = pivot.get("type")
            if ptype and ptype not in allowed_types:
                violations.append({
                    "rule": "allowed_joint_types",
                    "part": name,
                    "value": ptype,
                    "expected": sorted(allowed_types),
                    "message": f"Joint type '{ptype}' not in allowed set",
                })

    # Check symmetry_required
    if rules.get("symmetry_required"):
        joints = rig.get("joints", {})
        left_joints = [n for n in joints if "_l" in n or "left" in n.lower()]
        right_joints = [n for n in joints if "_r" in n or "right" in n.lower()]
        if len(left_joints) != len(right_joints):
            violations.append({
                "rule": "symmetry_required",
                "value": {"left": len(left_joints), "right": len(right_joints)},
                "expected": "equal left/right joint counts",
                "message": f"Asymmetric: {len(left_joints)} left joints vs {len(right_joints)} right joints",
            })

    return {
        "style": style_name,
        "character": rig.get("character_name", "unknown"),
        "violations": violations,
        "violation_count": len(violations),
        "passed": len(violations) == 0,
    }


def save_style(style_name: str, path: str) -> dict:
    """Save a style guide to a JSON file.

    Args:
        style_name: name of the style to save
        path: filesystem path for the output file

    Returns:
        Confirmation dict or error.
    """
    if style_name not in _styles:
        return {"error": f"Style '{style_name}' not defined"}

    data = {
        "name": style_name,
        "rules": _styles[style_name],
    }

    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return {"saved": path, "style": style_name, "rules_count": len(data["rules"])}


def load_style(path: str) -> dict:
    """Load a style guide from a JSON file.

    Args:
        path: filesystem path to the style guide JSON

    Returns:
        Confirmation dict with loaded style name and rules.
    """
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    with open(path) as f:
        data = json.load(f)

    name = data.get("name")
    rules = data.get("rules")

    if not name or not rules:
        return {"error": "Invalid style file: must contain 'name' and 'rules'"}

    _styles[name] = rules
    return {
        "loaded": name,
        "rules_count": len(rules),
        "rules": list(rules.keys()),
    }


def list_styles() -> dict:
    """List all defined style guides.

    Returns:
        Dict mapping style names to their rule summaries.
    """
    return {
        "styles": {
            name: {"rules_count": len(rules), "rules": list(rules.keys())}
            for name, rules in _styles.items()
        },
        "total": len(_styles),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_parts(rig: dict):
    """Iterate over parts from wizard data or joints."""
    wizard_parts = rig.get("wizard_parts", [])
    if wizard_parts:
        yield from wizard_parts
    else:
        # Fall back to joints as pseudo-parts
        for name, data in rig.get("joints", {}).items():
            yield {"name": name, **data}


def _compute_head_body_ratio(rig: dict) -> Optional[float]:
    """Compute head-to-body size ratio from joint positions.

    Returns None if not enough data is available.
    """
    joints = rig.get("joints", {})

    # Look for head and body markers
    head_joint = None
    body_joints = []
    for name, data in joints.items():
        name_lower = name.lower()
        if "head" in name_lower:
            head_joint = data
        else:
            body_joints.append(data)

    if not head_joint or not body_joints:
        return None

    # Estimate head size from its area or use a default
    head_area = head_joint.get("area", 0)
    if head_area <= 0:
        return None

    # Estimate total body area
    total_area = sum(j.get("area", 0) for j in body_joints) + head_area
    if total_area <= 0:
        return None

    return head_area / total_area


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_style_guide tool."""

    @mcp.tool(
        name="adobe_ai_style_guide",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_style_guide(params: AiStyleGuideInput) -> str:
        """Enforce consistent visual style across a project.

        Actions:
        - define_style: create a style guide with rules
        - check_style: validate a character against a style
        - save_style: persist a style guide to JSON
        - load_style: load a style guide from JSON
        - list_styles: show all defined styles
        """
        action = params.action.lower().strip()

        if action == "define_style":
            if not params.style_name or not params.rules:
                return json.dumps({"error": "define_style requires style_name and rules"})
            result = define_style(params.style_name, params.rules)
            return json.dumps(result)

        elif action == "check_style":
            if not params.style_name or not params.character_name:
                return json.dumps({"error": "check_style requires style_name and character_name"})
            rig = _load_rig(params.character_name)
            result = check_style(rig, params.style_name)
            return json.dumps(result)

        elif action == "save_style":
            if not params.style_name or not params.path:
                return json.dumps({"error": "save_style requires style_name and path"})
            result = save_style(params.style_name, params.path)
            return json.dumps(result)

        elif action == "load_style":
            if not params.path:
                return json.dumps({"error": "load_style requires a path"})
            result = load_style(params.path)
            return json.dumps(result)

        elif action == "list_styles":
            result = list_styles()
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
