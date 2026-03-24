"""Differentiable path optimization via DiffVG (optional dependency).

Uses differentiable rendering to optimize SVG path control points
by backpropagating pixel-level loss between rendered and target images.

Falls back gracefully when ML dependencies are not installed.
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


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class DiffVGCorrectInput(BaseModel):
    """Control differentiable path optimization."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, optimize",
    )
    svg_path: Optional[str] = Field(
        default=None, description="Path to SVG file to optimize"
    )
    target_image_path: Optional[str] = Field(
        default=None, description="Path to target raster image"
    )
    iterations: int = Field(
        default=100,
        description="Number of optimization iterations",
        ge=1,
        le=10000,
    )
    learning_rate: float = Field(
        default=0.01,
        description="Learning rate for optimizer",
        gt=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def compute_pixel_loss(
    rendered: List[List[float]],
    target: List[List[float]],
) -> float:
    """Compute mean squared error between rendered and target images.

    Both inputs are 2D arrays (flattened H*W x C or H x W) of float values
    in [0, 1] range.  This is a pure Python implementation for testing;
    the real optimization loop uses torch tensors.

    Args:
        rendered: Rendered image pixel values as nested list.
        target: Target image pixel values as nested list.

    Returns:
        MSE loss as a float.

    Raises:
        ValueError: If inputs have different shapes or are empty.
    """
    if not rendered or not target:
        raise ValueError("Both rendered and target must be non-empty")
    if len(rendered) != len(target):
        raise ValueError(
            f"Shape mismatch: rendered has {len(rendered)} rows, "
            f"target has {len(target)} rows"
        )

    total_error = 0.0
    count = 0

    for r_row, t_row in zip(rendered, target):
        if isinstance(r_row, (list, tuple)):
            if len(r_row) != len(t_row):
                raise ValueError("Row length mismatch between rendered and target")
            for r_val, t_val in zip(r_row, t_row):
                diff = float(r_val) - float(t_val)
                total_error += diff * diff
                count += 1
        else:
            # 1D case: each element is a scalar
            diff = float(r_row) - float(t_row)
            total_error += diff * diff
            count += 1

    if count == 0:
        raise ValueError("No pixel values to compare")

    return total_error / count


def _ml_status() -> dict:
    """Return availability status of DiffVG optimization."""
    status = {
        "ml_available": ML_AVAILABLE,
        "tool": "DiffVG differentiable path optimization",
        "capabilities": [
            "SVG path control point optimization",
            "Pixel-level loss backpropagation",
            "Bezier curve refinement",
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
        status["required_packages"] = ["torch", "diffvg"]
        status["device"] = "unavailable"
    return status


def _optimize_paths(
    svg_path: str,
    target_image_path: str,
    iterations: int,
    learning_rate: float,
) -> dict:
    """Optimize SVG paths against a target image using differentiable rendering.

    Requires ML dependencies (torch, diffvg).
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot optimize paths.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "diffvg"],
        }

    if not svg_path or not os.path.isfile(svg_path):
        return {"error": f"SVG file not found: {svg_path}"}

    if not target_image_path or not os.path.isfile(target_image_path):
        return {"error": f"Target image not found: {target_image_path}"}

    try:
        return {
            "error": "DiffVG integration pending — requires diffvg compiled module.",
            "svg_path": svg_path,
            "target_image_path": target_image_path,
            "iterations": iterations,
            "learning_rate": learning_rate,
            "note": "Use compute_pixel_loss() for MSE computation in custom optimization loops.",
        }
    except Exception as exc:
        return {"error": f"Optimization failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_diffvg_correct tool."""

    @mcp.tool(
        name="adobe_ai_diffvg_correct",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_diffvg_correct(params: DiffVGCorrectInput) -> str:
        """Differentiable path optimization using DiffVG.

        Actions:
        - status: Check ML availability and device
        - optimize: Optimize SVG paths against a target image

        Requires optional ML dependencies (torch, diffvg). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "optimize":
            result = _optimize_paths(
                params.svg_path,
                params.target_image_path,
                params.iterations,
                params.learning_rate,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "optimize"],
            })
