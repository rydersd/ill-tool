"""Spine skeleton JSON export.

Converts our internal rig schema to Spine's skeleton JSON format,
mapping joints to bones, bindings to slots/attachments, and poses
to animations.

Pure Python — no Spine runtime dependency.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiSpineExportInput(BaseModel):
    """Export rig as Spine skeleton JSON."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: export, status"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path (auto-generated if None)"
    )
    image_width: int = Field(
        default=1024, description="Source image width for coordinate mapping", ge=1
    )
    image_height: int = Field(
        default=1024, description="Source image height for coordinate mapping", ge=1
    )


# ---------------------------------------------------------------------------
# Spine bone builder
# ---------------------------------------------------------------------------


def spine_bone(
    name: str,
    parent: Optional[str] = None,
    x: float = 0.0,
    y: float = 0.0,
    rotation: float = 0.0,
    length: float = 0.0,
) -> dict:
    """Create a single Spine bone dict.

    Args:
        name: bone name
        parent: parent bone name (None for root)
        x: local X offset from parent
        y: local Y offset from parent
        rotation: local rotation in degrees
        length: bone length (visual, used by Spine editor)

    Returns:
        Dict matching Spine's bone JSON format.
    """
    bone = {"name": name}
    if parent is not None:
        bone["parent"] = parent
    bone["length"] = round(length, 2)
    bone["rotation"] = round(rotation, 2)
    bone["x"] = round(x, 2)
    bone["y"] = round(y, 2)
    return bone


def _compute_bone_from_joint(
    joint_name: str,
    joint_data: dict,
    parent_joint_data: Optional[dict],
) -> dict:
    """Compute Spine bone parameters from our joint data.

    Our joints store absolute positions; Spine bones use local offsets
    relative to parent.
    """
    pos = joint_data.get("position", joint_data.get("ai", [0, 0]))
    jx, jy = pos[0], pos[1]

    parent_name = joint_data.get("parent")

    if parent_joint_data:
        pp = parent_joint_data.get("position", parent_joint_data.get("ai", [0, 0]))
        px, py = pp[0], pp[1]
        # Local offset
        dx = jx - px
        dy = jy - py
        length = math.sqrt(dx * dx + dy * dy)
        rotation = math.degrees(math.atan2(dy, dx)) if length > 0 else 0
    else:
        dx, dy = jx, jy
        length = 0
        rotation = 0

    return spine_bone(
        name=joint_name,
        parent=parent_name,
        x=dx,
        y=dy,
        rotation=rotation,
        length=length,
    )


# ---------------------------------------------------------------------------
# Full skeleton conversion
# ---------------------------------------------------------------------------


def rig_to_spine_skeleton(rig: dict) -> dict:
    """Convert our rig schema to Spine's skeleton JSON format.

    Mapping:
    - Our joints → Spine bones (name, parent, length, rotation, x, y)
    - Our bindings → Spine slots and attachments
    - Our poses → Spine animations

    Args:
        rig: our internal rig dict with joints, bindings, poses

    Returns:
        Dict matching Spine's skeleton JSON structure.
    """
    joints = rig.get("joints", {})
    bindings = rig.get("bindings", {})
    poses = rig.get("poses", {})
    character_name = rig.get("character_name", "character")

    # ── Build bones ─────────────────────────────────────────────
    # Root bone is always first
    bones = [spine_bone("root")]

    # Sort joints so parents come before children
    processed = {"root"}
    remaining = dict(joints)
    max_iterations = len(remaining) + 1

    while remaining and max_iterations > 0:
        max_iterations -= 1
        for jname, jdata in list(remaining.items()):
            parent = jdata.get("parent", "root")
            if parent in processed or parent == jname:
                parent_data = joints.get(parent)
                bone = _compute_bone_from_joint(jname, jdata, parent_data)
                # Ensure parent references root if no explicit parent
                if bone.get("parent") is None:
                    bone["parent"] = "root"
                bones.append(bone)
                processed.add(jname)
                del remaining[jname]

    # Add any remaining joints with forced root parent (prevents orphans)
    for jname, jdata in remaining.items():
        bone = _compute_bone_from_joint(jname, jdata, None)
        bone["parent"] = "root"
        bones.append(bone)

    # ── Build slots and skins ───────────────────────────────────
    slots = []
    skin_attachments = {}

    for part_name, binding in bindings.items():
        joint_name = binding if isinstance(binding, str) else binding.get("joint", "root")
        slot = {
            "name": part_name,
            "bone": joint_name if joint_name in processed else "root",
            "attachment": part_name,
        }
        slots.append(slot)

        # Default skin attachment (region type)
        skin_attachments[part_name] = {
            part_name: {
                "type": "region",
                "name": part_name,
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
            }
        }

    # ── Build animations from poses ────────────────────────────
    animations = {}
    for pose_name, pose_data in poses.items():
        bone_timelines = {}

        if isinstance(pose_data, dict):
            joint_rotations = pose_data.get("joint_rotations", {})
            for jname, angle in joint_rotations.items():
                bone_timelines[jname] = {
                    "rotate": [
                        {"time": 0, "angle": 0},
                        {"time": 0.5, "angle": round(angle, 2)},
                    ]
                }

        if bone_timelines:
            animations[pose_name] = {"bones": bone_timelines}

    # ── Assemble skeleton JSON ──────────────────────────────────
    skeleton = {
        "skeleton": {
            "hash": "",
            "spine": "4.1",
            "x": 0,
            "y": 0,
            "width": rig.get("image_size", [1024, 1024])[0] if rig.get("image_size") else 1024,
            "height": rig.get("image_size", [1024, 1024])[1] if rig.get("image_size") else 1024,
            "images": f"./images/{character_name}/",
        },
        "bones": bones,
        "slots": slots,
        "skins": {
            "default": skin_attachments,
        },
        "animations": animations,
    }

    return skeleton


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_spine_export tool."""

    @mcp.tool(
        name="adobe_ai_spine_export",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_spine_export(params: AiSpineExportInput) -> str:
        """Export character rig as Spine skeleton JSON.

        Actions:
        - export: convert rig to Spine skeleton JSON format
        - status: report rig readiness for Spine export
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            rig = _load_rig(params.character_name)
            return json.dumps({
                "action": "status",
                "character_name": params.character_name,
                "joint_count": len(rig.get("joints", {})),
                "binding_count": len(rig.get("bindings", {})),
                "pose_count": len(rig.get("poses", {})),
                "ready_for_export": bool(rig.get("joints")),
                "supported_actions": ["export", "status"],
            }, indent=2)

        # ── export ──────────────────────────────────────────────────
        if action == "export":
            rig = _load_rig(params.character_name)

            if not rig.get("joints"):
                return json.dumps({
                    "error": "No joints found in rig.",
                    "hint": "Build a skeleton first using skeleton_build.",
                })

            spine_data = rig_to_spine_skeleton(rig)
            spine_json = json.dumps(spine_data, indent=2)

            if params.output_path:
                import os
                os.makedirs(os.path.dirname(params.output_path), exist_ok=True)
                with open(params.output_path, "w") as f:
                    f.write(spine_json)

            return json.dumps({
                "action": "export",
                "character_name": params.character_name,
                "bone_count": len(spine_data["bones"]),
                "slot_count": len(spine_data["slots"]),
                "animation_count": len(spine_data["animations"]),
                "spine_data": spine_data,
                "output_path": params.output_path,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["export", "status"],
        })
