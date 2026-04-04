"""StdGEN character decomposition into 3D meshes (optional dependency).

Decomposes a character image into separate 3D meshes for body, clothes,
and hair using the StdGEN model.  Returns paths to the individual mesh
files.

Falls back gracefully when ML/3D dependencies are not installed.
"""

import json
import os
from typing import List, Optional

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


class Character3DInput(BaseModel):
    """Control StdGEN character decomposition."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, decompose",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to character image"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Directory for output meshes (defaults to temp)"
    )
    components: List[str] = Field(
        default=["body", "clothes", "hair"],
        description="Which components to extract",
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------

VALID_COMPONENTS = ["body", "clothes", "hair", "face", "accessories"]


def merge_or_split_meshes(mesh_paths: List[str], mode: str = "split") -> dict:
    """Validate and organize a list of mesh file paths.

    In 'split' mode: validates each mesh exists and returns them separately.
    In 'merge' mode: validates all meshes exist for a merge operation.

    This is a pure-Python pre-validation step. The actual merge uses trimesh
    when available.

    Args:
        mesh_paths: List of file paths to mesh files.
        mode: 'split' to keep separate, 'merge' to combine.

    Returns:
        Dict with validated mesh info and mode result.
    """
    if not mesh_paths:
        return {"error": "No mesh paths provided", "meshes": []}

    if mode not in ("split", "merge"):
        return {"error": f"Invalid mode: {mode}. Use 'split' or 'merge'."}

    validated = []
    missing = []
    total_size = 0

    for path in mesh_paths:
        if os.path.isfile(path):
            size = os.path.getsize(path)
            total_size += size
            validated.append({
                "path": path,
                "exists": True,
                "file_size_bytes": size,
                "format": os.path.splitext(path)[1].lstrip("."),
            })
        else:
            missing.append(path)

    result = {
        "mode": mode,
        "total_meshes": len(mesh_paths),
        "valid_meshes": len(validated),
        "missing_meshes": len(missing),
        "meshes": validated,
        "total_size_bytes": total_size,
    }

    if missing:
        result["missing_paths"] = missing

    if mode == "merge":
        if missing:
            result["merge_ready"] = False
            result["error"] = "Cannot merge — some mesh files are missing"
        else:
            result["merge_ready"] = True
            if not TRIMESH_AVAILABLE:
                result["warning"] = "trimesh not installed — merge requires trimesh"
                result["merge_ready"] = False

    return result


def _ml_status() -> dict:
    """Return availability status for StdGEN decomposition."""
    status = {
        "ml_available": ML_AVAILABLE,
        "trimesh_available": TRIMESH_AVAILABLE,
        "tool": "StdGEN character 3D decomposition",
        "supported_components": VALID_COMPONENTS,
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


def _decompose(
    image_path: str,
    output_dir: Optional[str],
    components: List[str],
) -> dict:
    """Run StdGEN character decomposition.

    Requires ML dependencies (torch, transformers) and trimesh.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot decompose.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers", "trimesh"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Validate requested components
    invalid = [c for c in components if c not in VALID_COMPONENTS]
    if invalid:
        return {
            "error": f"Invalid components: {invalid}",
            "valid_components": VALID_COMPONENTS,
        }

    try:
        return {
            "error": "StdGEN integration pending — model weights setup required.",
            "image_path": image_path,
            "components": components,
            "note": "Use merge_or_split_meshes() to organize output mesh files.",
        }
    except Exception as exc:
        return {"error": f"Decomposition failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_3d tool."""

    @mcp.tool(
        name="adobe_ai_character_3d",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_3d(params: Character3DInput) -> str:
        """StdGEN character decomposition into 3D meshes.

        Actions:
        - status: Check ML/3D dependency availability
        - decompose: Decompose character into body, clothes, hair meshes

        Requires optional dependencies (torch, transformers, trimesh). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "decompose":
            result = _decompose(
                params.image_path, params.output_dir, params.components
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "decompose"],
            })
