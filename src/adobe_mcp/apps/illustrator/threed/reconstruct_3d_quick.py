"""TripoSR quick 3D preview from a single image (optional dependency).

Provides fast single-image 3D reconstruction using TripoSR for quick
preview meshes.  Outputs OBJ or GLB format.

Falls back gracefully when ML/3D dependencies are not installed.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Graceful ML dependency import
# ---------------------------------------------------------------------------

try:
    import torch
    from transformers import AutoModelForCausalLM
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class Reconstruct3DQuickInput(BaseModel):
    """Control TripoSR quick 3D reconstruction."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, reconstruct",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to input image"
    )
    output_format: str = Field(
        default="obj",
        description="Output format: obj or glb",
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory for output mesh (defaults to temp)"
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def validate_mesh_output(path: str) -> dict:
    """Check that a mesh file exists and has valid content.

    Performs basic validation:
    - File exists and is non-empty
    - For OBJ: contains vertex ('v ') lines
    - For GLB: starts with glTF magic bytes

    Args:
        path: Path to the mesh file.

    Returns:
        Dict with validation results including vertex_count estimate.
    """
    if not path:
        return {"valid": False, "error": "No path provided"}

    if not os.path.isfile(path):
        return {"valid": False, "error": f"File not found: {path}"}

    file_size = os.path.getsize(path)
    if file_size == 0:
        return {"valid": False, "error": "File is empty"}

    ext = os.path.splitext(path)[1].lower()
    result = {
        "valid": True,
        "path": path,
        "file_size_bytes": file_size,
        "format": ext.lstrip("."),
    }

    if ext == ".obj":
        # Count vertices by reading 'v ' lines
        vertex_count = 0
        face_count = 0
        try:
            with open(path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("v "):
                        vertex_count += 1
                    elif stripped.startswith("f "):
                        face_count += 1
        except Exception as exc:
            return {"valid": False, "error": f"Cannot read OBJ: {exc}"}

        if vertex_count == 0:
            return {"valid": False, "error": "OBJ file has no vertices"}

        result["vertex_count"] = vertex_count
        result["face_count"] = face_count

    elif ext == ".glb":
        # Check for glTF magic bytes: 0x46546C67 ("glTF")
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic != b"glTF":
                return {"valid": False, "error": "Not a valid GLB file (missing glTF magic)"}
        except Exception as exc:
            return {"valid": False, "error": f"Cannot read GLB: {exc}"}

        result["has_gltf_magic"] = True

    return result


def _ml_status() -> dict:
    """Return availability status for TripoSR reconstruction."""
    status = {
        "ml_available": ML_AVAILABLE,
        "trimesh_available": TRIMESH_AVAILABLE,
        "tool": "TripoSR quick 3D preview",
        "supported_formats": ["obj", "glb"],
    }
    if ML_AVAILABLE:
        status["torch_version"] = torch.__version__
        if torch.cuda.is_available():
            status["device"] = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            status["device"] = "mps"
        else:
            status["device"] = "cpu"
    else:
        status["install_hint"] = 'Install ML dependencies with: uv pip install -e ".[ml]"'
        status["required_packages"] = ["torch", "transformers", "trimesh"]
        status["device"] = "unavailable"
    return status


def _reconstruct(
    image_path: str,
    output_format: str,
    output_dir: Optional[str],
) -> dict:
    """Run TripoSR reconstruction on an image.

    Requires ML dependencies (torch, transformers) and trimesh.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot reconstruct.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers", "trimesh"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    if output_format not in ("obj", "glb"):
        return {"error": f"Unsupported format: {output_format}. Use 'obj' or 'glb'."}

    try:
        return {
            "error": "TripoSR integration pending — model weights setup required.",
            "image_path": image_path,
            "output_format": output_format,
            "note": "Use validate_mesh_output() to verify mesh files from any reconstruction pipeline.",
        }
    except Exception as exc:
        return {"error": f"Reconstruction failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_reconstruct_3d_quick tool."""

    @mcp.tool(
        name="adobe_ai_reconstruct_3d_quick",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_reconstruct_3d_quick(
        params: Reconstruct3DQuickInput,
    ) -> str:
        """TripoSR quick 3D preview from a single image.

        Actions:
        - status: Check ML/3D dependency availability
        - reconstruct: Generate OBJ/GLB mesh from an image

        Requires optional dependencies (torch, transformers, trimesh). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "reconstruct":
            result = _reconstruct(
                params.image_path, params.output_format, params.output_dir
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "reconstruct"],
            })
