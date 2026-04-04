"""DrawingSpinUp bridge — validate inputs and map outputs.

Bridges the DrawingSpinUp ML service to our rig + animation schema.
Validates image inputs before sending to the service, and maps the
service's output format to our internal rig/animation data structures.

Pure Python — no JSX or Adobe required.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiDrawingSpinupBridgeInput(BaseModel):
    """DrawingSpinUp bridge for rig + animation pipeline."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, process",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Path to source drawing image (required for process)",
    )
    spinup_response: Optional[dict] = Field(
        default=None,
        description="Raw DrawingSpinUp output to map (for testing/offline mapping)",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for output rig data",
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum file size we accept (50 MB) — avoids sending enormous files to
# the ML service or running out of memory during preprocessing.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Image extensions that DrawingSpinUp can handle.
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def validate_drawing_input(image_path: str) -> dict:
    """Check that an image exists, is readable, and has a reasonable size.

    Performs the following checks:
    1. Path is not empty
    2. File exists on disk
    3. File extension is a supported image format
    4. File is readable (not a directory, permission OK)
    5. File size is under MAX_FILE_SIZE_BYTES

    Args:
        image_path: filesystem path to the source image.

    Returns:
        dict with ``valid: True`` and file metadata on success, or
        ``valid: False`` and an ``error`` string on failure.
    """
    if not image_path or not image_path.strip():
        return {"valid": False, "error": "image_path is empty"}

    if not os.path.exists(image_path):
        return {"valid": False, "error": f"File not found: {image_path}"}

    if os.path.isdir(image_path):
        return {"valid": False, "error": f"Path is a directory, not a file: {image_path}"}

    # Extension check
    _, ext = os.path.splitext(image_path)
    ext_lower = ext.lower()
    if ext_lower not in SUPPORTED_EXTENSIONS:
        return {
            "valid": False,
            "error": f"Unsupported extension '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        }

    # Readability check
    if not os.access(image_path, os.R_OK):
        return {"valid": False, "error": f"File is not readable: {image_path}"}

    # Size check
    file_size = os.path.getsize(image_path)
    if file_size == 0:
        return {"valid": False, "error": "File is empty (0 bytes)"}
    if file_size > MAX_FILE_SIZE_BYTES:
        return {
            "valid": False,
            "error": (
                f"File too large: {file_size} bytes "
                f"(max {MAX_FILE_SIZE_BYTES} bytes / {MAX_FILE_SIZE_BYTES // (1024*1024)} MB)"
            ),
        }

    return {
        "valid": True,
        "image_path": image_path,
        "file_size": file_size,
        "extension": ext_lower,
    }


def map_spinup_output(response: dict) -> dict:
    """Map DrawingSpinUp service output to our rig + animation schema.

    DrawingSpinUp typically returns:
    - ``mesh``: 3D mesh vertices/faces
    - ``texture``: UV-mapped texture data
    - ``skeleton`` / ``joints``: bone hierarchy
    - ``animations``: list of animation clips

    We map these to our internal format:
    - ``hierarchy``: bone parent-child tree
    - ``joints``: joint positions with names
    - ``poses``: animation frames mapped to pose snapshots
    - ``mesh_3d``: raw mesh reference

    Args:
        response: raw dict from DrawingSpinUp service.

    Returns:
        dict in our rig/animation schema.
    """
    if not response or not isinstance(response, dict):
        return {"error": "Empty or invalid DrawingSpinUp response"}

    # ── Map skeleton / joints ──────────────────────────────────────
    raw_joints = response.get("joints", response.get("skeleton", {}).get("joints", []))
    mapped_joints = []
    hierarchy = {}

    if isinstance(raw_joints, list):
        for jdata in raw_joints:
            name = jdata.get("name", jdata.get("id", f"joint_{len(mapped_joints)}"))
            parent = jdata.get("parent", None)
            position = jdata.get("position", jdata.get("pos", [0, 0, 0]))

            mapped_joints.append({
                "name": name,
                "position": position[:3] if len(position) >= 3 else position + [0] * (3 - len(position)),
                "parent": parent,
            })

            # Build hierarchy dict
            if parent:
                hierarchy.setdefault(parent, []).append(name)
            else:
                hierarchy.setdefault("root", []).append(name)

    # ── Map animations → poses ─────────────────────────────────────
    raw_anims = response.get("animations", [])
    poses = []

    if isinstance(raw_anims, list):
        for anim in raw_anims:
            clip_name = anim.get("name", anim.get("clip", f"clip_{len(poses)}"))
            frames = anim.get("frames", anim.get("keyframes", []))
            duration = anim.get("duration", len(frames))

            poses.append({
                "name": clip_name,
                "frame_count": len(frames) if isinstance(frames, list) else 0,
                "duration": duration,
                "keyframes": frames if isinstance(frames, list) else [],
            })

    # ── Map mesh data ──────────────────────────────────────────────
    raw_mesh = response.get("mesh", {})
    mesh_3d = None
    if raw_mesh and isinstance(raw_mesh, dict):
        vertices = raw_mesh.get("vertices", [])
        faces = raw_mesh.get("faces", [])
        mesh_3d = {
            "vertex_count": len(vertices) if isinstance(vertices, list) else 0,
            "face_count": len(faces) if isinstance(faces, list) else 0,
            "has_uvs": bool(raw_mesh.get("uvs") or raw_mesh.get("texture_coords")),
        }

    # ── Map texture data ───────────────────────────────────────────
    raw_texture = response.get("texture", {})
    texture_info = None
    if raw_texture and isinstance(raw_texture, dict):
        texture_info = {
            "width": raw_texture.get("width", 0),
            "height": raw_texture.get("height", 0),
            "format": raw_texture.get("format", "unknown"),
        }

    return {
        "source": "drawing_spinup",
        "joints": mapped_joints,
        "hierarchy": hierarchy,
        "poses": poses,
        "mesh_3d": mesh_3d,
        "texture": texture_info,
        "joint_count": len(mapped_joints),
        "pose_count": len(poses),
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_drawing_spinup_bridge tool."""

    @mcp.tool(
        name="adobe_ai_drawing_spinup_bridge",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def adobe_ai_drawing_spinup_bridge(params: AiDrawingSpinupBridgeInput) -> str:
        """Bridge to DrawingSpinUp ML service for rig + animation.

        Actions:
        - status: check bridge readiness
        - process: validate input and map output
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "drawing_spinup_bridge",
                "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
                "max_file_size_mb": MAX_FILE_SIZE_BYTES // (1024 * 1024),
                "ready": True,
            }, indent=2)

        elif action == "process":
            result = {"action": "process"}

            # Validate input if provided
            if params.image_path:
                validation = validate_drawing_input(params.image_path)
                result["input_validation"] = validation
                if not validation.get("valid"):
                    return json.dumps(result, indent=2)

            # Map output if provided
            if params.spinup_response:
                mapped = map_spinup_output(params.spinup_response)
                result["mapped_output"] = mapped
                result["character_name"] = params.character_name
            elif not params.image_path:
                result["error"] = "Provide image_path and/or spinup_response for process action"

            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "process"],
            })
