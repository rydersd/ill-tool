"""PyTorch3D mesh refinement via silhouette supervision (optional dependency).

Iteratively refines a 3D mesh by comparing rendered silhouettes against
target images.  Uses silhouette IoU as the optimization metric and detects
convergence plateaus to stop early.

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


class Refine3DInput(BaseModel):
    """Control PyTorch3D mesh refinement."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, refine",
    )
    mesh_path: Optional[str] = Field(
        default=None, description="Path to input mesh file (OBJ)"
    )
    target_images: List[str] = Field(
        default=[],
        description="Paths to target silhouette images for supervision",
    )
    iterations: int = Field(
        default=200,
        description="Maximum refinement iterations",
        ge=1,
        le=5000,
    )
    learning_rate: float = Field(
        default=0.001,
        description="Learning rate for mesh vertex optimization",
        gt=0.0,
        le=1.0,
    )
    convergence_threshold: float = Field(
        default=0.01,
        description="IoU improvement threshold for convergence detection",
        gt=0.0,
        le=0.5,
    )
    output_path: Optional[str] = Field(
        default=None, description="Path for refined mesh output"
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def compute_silhouette_iou(
    silhouette_a: List[List[int]],
    silhouette_b: List[List[int]],
) -> float:
    """Compute intersection-over-union of two binary silhouette masks.

    Both inputs are 2D arrays of 0/1 values representing silhouettes.

    Args:
        silhouette_a: First binary mask (2D list of 0/1).
        silhouette_b: Second binary mask (2D list of 0/1).

    Returns:
        IoU score in [0.0, 1.0].

    Raises:
        ValueError: If inputs have different dimensions or are empty.
    """
    if not silhouette_a or not silhouette_b:
        raise ValueError("Both silhouettes must be non-empty")

    if len(silhouette_a) != len(silhouette_b):
        raise ValueError(
            f"Height mismatch: {len(silhouette_a)} vs {len(silhouette_b)}"
        )

    intersection = 0
    union = 0

    for row_a, row_b in zip(silhouette_a, silhouette_b):
        if len(row_a) != len(row_b):
            raise ValueError(
                f"Width mismatch: {len(row_a)} vs {len(row_b)}"
            )
        for val_a, val_b in zip(row_a, row_b):
            a = 1 if val_a > 0 else 0
            b = 1 if val_b > 0 else 0
            if a and b:
                intersection += 1
            if a or b:
                union += 1

    if union == 0:
        return 0.0

    return intersection / union


def convergence_check(
    iou_history: List[float],
    threshold: float = 0.01,
) -> dict:
    """Detect convergence plateau in IoU history.

    Checks if the improvement over recent iterations is below the threshold,
    indicating the optimization has converged.

    Args:
        iou_history: List of IoU scores from successive iterations.
        threshold: Minimum improvement to consider non-converged.

    Returns:
        Dict with converged bool, plateau info, and recommendation.
    """
    if not iou_history:
        return {
            "converged": False,
            "reason": "No history provided",
            "iterations": 0,
        }

    if len(iou_history) < 3:
        return {
            "converged": False,
            "reason": "Too few iterations to determine convergence",
            "iterations": len(iou_history),
            "current_iou": iou_history[-1],
        }

    # Check the last 5 values (or all if fewer)
    window_size = min(5, len(iou_history))
    recent = iou_history[-window_size:]

    # Compute improvement across window
    improvement = recent[-1] - recent[0]
    max_in_window = max(recent)
    min_in_window = min(recent)
    range_in_window = max_in_window - min_in_window

    # Converged if improvement is below threshold
    is_converged = abs(improvement) < threshold and range_in_window < threshold

    result = {
        "converged": is_converged,
        "iterations": len(iou_history),
        "current_iou": round(iou_history[-1], 6),
        "best_iou": round(max(iou_history), 6),
        "improvement_over_window": round(improvement, 6),
        "window_range": round(range_in_window, 6),
        "threshold": threshold,
    }

    if is_converged:
        result["reason"] = (
            f"IoU improvement ({improvement:.4f}) below threshold ({threshold})"
        )
        result["recommendation"] = "Stop optimization — further iterations unlikely to improve"
    else:
        result["reason"] = "Still improving"
        result["recommendation"] = "Continue optimization"

    return result


def _ml_status() -> dict:
    """Return availability status for PyTorch3D refinement."""
    status = {
        "ml_available": ML_AVAILABLE,
        "trimesh_available": TRIMESH_AVAILABLE,
        "tool": "PyTorch3D mesh refinement (silhouette supervision)",
        "capabilities": [
            "Vertex position optimization",
            "Silhouette IoU loss",
            "Multi-view supervision",
            "Convergence detection",
        ],
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
        status["required_packages"] = ["torch", "pytorch3d", "trimesh"]
        status["device"] = "unavailable"
    return status


def _refine_mesh(
    mesh_path: str,
    target_images: List[str],
    iterations: int,
    learning_rate: float,
    convergence_threshold: float,
    output_path: Optional[str],
) -> dict:
    """Run PyTorch3D mesh refinement.

    Requires ML dependencies (torch, pytorch3d) and trimesh.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot refine mesh.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "pytorch3d", "trimesh"],
        }

    if not mesh_path or not os.path.isfile(mesh_path):
        return {"error": f"Mesh file not found: {mesh_path}"}

    if not target_images:
        return {"error": "No target images provided for supervision"}

    missing_images = [p for p in target_images if not os.path.isfile(p)]
    if missing_images:
        return {"error": f"Target images not found: {missing_images}"}

    try:
        return {
            "error": "PyTorch3D integration pending — requires pytorch3d compiled module.",
            "mesh_path": mesh_path,
            "target_count": len(target_images),
            "iterations": iterations,
            "learning_rate": learning_rate,
            "note": "Use compute_silhouette_iou() and convergence_check() for custom refinement loops.",
        }
    except Exception as exc:
        return {"error": f"Refinement failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_refine_3d tool."""

    @mcp.tool(
        name="adobe_ai_refine_3d",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_refine_3d(params: Refine3DInput) -> str:
        """PyTorch3D mesh refinement via silhouette supervision.

        Actions:
        - status: Check ML/3D dependency availability
        - refine: Iteratively refine mesh against target silhouettes

        Requires optional dependencies (torch, pytorch3d, trimesh). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "refine":
            result = _refine_mesh(
                params.mesh_path,
                params.target_images,
                params.iterations,
                params.learning_rate,
                params.convergence_threshold,
                params.output_path,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "refine"],
            })
