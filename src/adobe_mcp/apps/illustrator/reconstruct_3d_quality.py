"""InstantMesh quality 3D reconstruction (optional dependency).

Two-stage pipeline: multi-view generation from a single image, then
mesh reconstruction from the generated views.  Produces higher quality
meshes than TripoSR but takes longer.

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


class Reconstruct3DQualityInput(BaseModel):
    """Control InstantMesh quality 3D reconstruction."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, reconstruct",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to input image"
    )
    num_views: int = Field(
        default=6,
        description="Number of views to generate in stage 1",
        ge=2,
        le=16,
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


def estimate_quality_score(mesh_path: str) -> dict:
    """Estimate mesh quality based on vertex/face count.

    Uses vertex and face counts as a proxy for mesh detail and quality.
    Higher counts generally indicate more detail.

    Args:
        mesh_path: Path to mesh file (OBJ format).

    Returns:
        Dict with vertex_count, face_count, and quality tier.
    """
    if not mesh_path:
        return {"error": "No mesh path provided", "quality": "unknown"}

    if not os.path.isfile(mesh_path):
        return {"error": f"File not found: {mesh_path}", "quality": "unknown"}

    vertex_count = 0
    face_count = 0

    ext = os.path.splitext(mesh_path)[1].lower()
    if ext != ".obj":
        return {
            "error": f"Quality scoring only supports OBJ format, got {ext}",
            "quality": "unknown",
        }

    try:
        with open(mesh_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("v "):
                    vertex_count += 1
                elif stripped.startswith("f "):
                    face_count += 1
    except Exception as exc:
        return {"error": f"Cannot read mesh: {exc}", "quality": "unknown"}

    # Quality tiers based on vertex count
    if vertex_count >= 50000:
        quality = "high"
    elif vertex_count >= 10000:
        quality = "medium"
    elif vertex_count >= 1000:
        quality = "low"
    elif vertex_count > 0:
        quality = "preview"
    else:
        quality = "empty"

    return {
        "mesh_path": mesh_path,
        "vertex_count": vertex_count,
        "face_count": face_count,
        "quality": quality,
        "vertices_per_face": round(vertex_count / face_count, 2) if face_count > 0 else 0,
    }


def _ml_status() -> dict:
    """Return availability status for InstantMesh reconstruction."""
    status = {
        "ml_available": ML_AVAILABLE,
        "trimesh_available": TRIMESH_AVAILABLE,
        "tool": "InstantMesh quality 3D reconstruction",
        "pipeline": "multi-view generation -> mesh reconstruction",
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
    num_views: int,
    output_format: str,
    output_dir: Optional[str],
) -> dict:
    """Run InstantMesh two-stage reconstruction.

    Stage 1: Generate multi-view images from single input.
    Stage 2: Reconstruct mesh from the generated views.

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
            "error": "InstantMesh integration pending — model weights setup required.",
            "image_path": image_path,
            "num_views": num_views,
            "output_format": output_format,
            "note": "Use estimate_quality_score() to evaluate mesh quality from any pipeline.",
        }
    except Exception as exc:
        return {"error": f"Reconstruction failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_reconstruct_3d_quality tool."""

    @mcp.tool(
        name="adobe_ai_reconstruct_3d_quality",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_reconstruct_3d_quality(
        params: Reconstruct3DQualityInput,
    ) -> str:
        """InstantMesh quality 3D reconstruction (two-stage pipeline).

        Actions:
        - status: Check ML/3D dependency availability
        - reconstruct: Generate quality mesh from an image via multi-view

        Requires optional dependencies (torch, transformers, trimesh). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "reconstruct":
            result = _reconstruct(
                params.image_path, params.num_views,
                params.output_format, params.output_dir,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "reconstruct"],
            })
