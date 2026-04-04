"""Live2D PSD layer naming and structure export.

Maps our internal body_part_labels and rig data to Live2D's required
layer naming conventions.  Validates that all required Live2D groups
are present for a functional model.

Pure Python — no Live2D SDK dependency.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiLive2dExportInput(BaseModel):
    """Generate Live2D-compatible layer naming from rig data."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: generate_layer_map, status"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path for layer map JSON"
    )


# ---------------------------------------------------------------------------
# Live2D naming conventions
# ---------------------------------------------------------------------------

# Mapping from our body part labels to Live2D required layer names.
# Live2D uses a specific hierarchy: group > part naming convention
# for its Cubism Editor to auto-detect deformation regions.
LIVE2D_CONVENTIONS = {
    # Head / Face group
    "head": "face",
    "face": "face",
    "left_eye": "eye_l",
    "right_eye": "eye_r",
    "left_eyebrow": "eyebrow_l",
    "right_eyebrow": "eyebrow_r",
    "mouth": "mouth",
    "nose": "nose",
    "left_ear": "ear_l",
    "right_ear": "ear_r",
    "hair_front": "hair_front",
    "hair_back": "hair_back",
    "hair_side_l": "hair_side_l",
    "hair_side_r": "hair_side_r",
    "hair": "hair_front",
    "jaw": "face",
    "chin": "face",
    "forehead": "face",

    # Torso / Body group
    "torso": "body",
    "chest": "body",
    "abdomen": "body",
    "waist": "body",
    "neck": "neck",
    "body": "body",

    # Arms
    "left_upper_arm": "arm_l_upper",
    "left_forearm": "arm_l_lower",
    "left_hand": "hand_l",
    "right_upper_arm": "arm_r_upper",
    "right_forearm": "arm_r_lower",
    "right_hand": "hand_r",
    "left_arm": "arm_l",
    "right_arm": "arm_r",

    # Legs
    "left_thigh": "leg_l_upper",
    "left_shin": "leg_l_lower",
    "left_foot": "foot_l",
    "right_thigh": "leg_r_upper",
    "right_shin": "leg_r_lower",
    "right_foot": "foot_r",
    "left_leg": "leg_l",
    "right_leg": "leg_r",

    # Accessories
    "tail": "tail",
    "wings": "wings",
    "accessory": "accessory",
}

# Required Live2D groups for a minimal functional model
REQUIRED_GROUPS = {
    "face": ["face"],
    "eyes": ["eye_l", "eye_r"],
    "mouth": ["mouth"],
    "body": ["body"],
}

# Live2D group hierarchy: which layers belong to which groups
LIVE2D_GROUPS = {
    "face": [
        "face", "eye_l", "eye_r", "eyebrow_l", "eyebrow_r",
        "mouth", "nose", "ear_l", "ear_r",
    ],
    "hair": [
        "hair_front", "hair_back", "hair_side_l", "hair_side_r",
    ],
    "body": [
        "body", "neck",
    ],
    "arm_l": [
        "arm_l", "arm_l_upper", "arm_l_lower", "hand_l",
    ],
    "arm_r": [
        "arm_r", "arm_r_upper", "arm_r_lower", "hand_r",
    ],
    "leg_l": [
        "leg_l", "leg_l_upper", "leg_l_lower", "foot_l",
    ],
    "leg_r": [
        "leg_r", "leg_r_upper", "leg_r_lower", "foot_r",
    ],
}


def rig_to_live2d_layers(rig: dict) -> dict:
    """Map our body_part_labels to Live2D layer naming conventions.

    Processes the rig's body_part_labels and maps each to the
    corresponding Live2D layer name, organized by Live2D groups.

    Args:
        rig: our internal rig dict with body_part_labels

    Returns:
        Dict with:
        - layer_map: {our_name: live2d_name} mapping
        - groups: {group_name: [live2d_layer_names]} organized hierarchy
        - unmapped: list of our parts that don't have a Live2D mapping
    """
    labels = rig.get("body_part_labels", {})
    bindings = rig.get("bindings", {})

    # Combine all known part names from labels and bindings
    all_parts = set(labels.keys()) | set(bindings.keys())

    layer_map = {}
    unmapped = []

    for part_name in sorted(all_parts):
        # Normalize the part name for lookup
        normalized = part_name.lower().replace(" ", "_").replace("-", "_")

        if normalized in LIVE2D_CONVENTIONS:
            layer_map[part_name] = LIVE2D_CONVENTIONS[normalized]
        else:
            # Try partial matching for compound names
            matched = False
            for key, live2d_name in LIVE2D_CONVENTIONS.items():
                if key in normalized or normalized in key:
                    layer_map[part_name] = live2d_name
                    matched = True
                    break
            if not matched:
                unmapped.append(part_name)
                # Use the original name as fallback
                layer_map[part_name] = normalized

    # Organize into Live2D groups
    groups = {}
    mapped_live2d_names = set(layer_map.values())

    for group_name, group_layers in LIVE2D_GROUPS.items():
        present = [l for l in group_layers if l in mapped_live2d_names]
        if present:
            groups[group_name] = present

    return {
        "layer_map": layer_map,
        "groups": groups,
        "unmapped": unmapped,
        "total_mapped": len(layer_map) - len(unmapped),
        "total_unmapped": len(unmapped),
    }


def validate_live2d_structure(layer_map: dict) -> dict:
    """Check that all required Live2D groups are present.

    Args:
        layer_map: dict mapping our part names to Live2D layer names,
                   as returned by rig_to_live2d_layers()

    Returns:
        Dict with 'valid' bool, 'present_groups', 'missing_groups',
        and 'missing_layers' detail.
    """
    # Get all Live2D names from the layer_map
    # layer_map can be the full result dict or just the mapping
    if "layer_map" in layer_map:
        live2d_names = set(layer_map["layer_map"].values())
    else:
        live2d_names = set(layer_map.values())

    present_groups = []
    missing_groups = []
    missing_layers = {}

    for group_name, required_layers in REQUIRED_GROUPS.items():
        found = [l for l in required_layers if l in live2d_names]
        if found:
            present_groups.append(group_name)
        else:
            missing_groups.append(group_name)
            missing_layers[group_name] = required_layers

    return {
        "valid": len(missing_groups) == 0,
        "present_groups": present_groups,
        "missing_groups": missing_groups,
        "missing_layers": missing_layers,
        "total_required_groups": len(REQUIRED_GROUPS),
        "present_count": len(present_groups),
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_live2d_export tool."""

    @mcp.tool(
        name="adobe_ai_live2d_export",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_live2d_export(params: AiLive2dExportInput) -> str:
        """Generate Live2D-compatible layer naming from character rig.

        Actions:
        - generate_layer_map: map body part labels to Live2D conventions
        - status: report rig readiness for Live2D export
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            rig = _load_rig(params.character_name)
            return json.dumps({
                "action": "status",
                "character_name": params.character_name,
                "body_part_count": len(rig.get("body_part_labels", {})),
                "binding_count": len(rig.get("bindings", {})),
                "supported_conventions": len(LIVE2D_CONVENTIONS),
                "required_groups": list(REQUIRED_GROUPS.keys()),
                "supported_actions": ["generate_layer_map", "status"],
            }, indent=2)

        # ── generate_layer_map ──────────────────────────────────────
        if action == "generate_layer_map":
            rig = _load_rig(params.character_name)

            if not rig.get("body_part_labels") and not rig.get("bindings"):
                return json.dumps({
                    "error": "No body part labels or bindings found in rig.",
                    "hint": "Label body parts first using body_part_label tool.",
                })

            layer_result = rig_to_live2d_layers(rig)
            validation = validate_live2d_structure(layer_result)

            # Save if output path provided
            if params.output_path:
                import os
                os.makedirs(os.path.dirname(params.output_path), exist_ok=True)
                export_data = {
                    "layer_map": layer_result,
                    "validation": validation,
                    "conventions": LIVE2D_CONVENTIONS,
                }
                with open(params.output_path, "w") as f:
                    json.dump(export_data, f, indent=2)

            return json.dumps({
                "action": "generate_layer_map",
                "character_name": params.character_name,
                **layer_result,
                "validation": validation,
                "output_path": params.output_path,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["generate_layer_map", "status"],
        })
