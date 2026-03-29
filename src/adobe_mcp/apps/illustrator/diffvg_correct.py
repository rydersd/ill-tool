"""Differentiable path optimization via DiffVG (optional dependency).

Uses differentiable rendering to optimize SVG path control points
by backpropagating pixel-level loss between rendered and target images.

Falls back to path_gradient_approx (finite-difference) when DiffVG
is not compiled, and returns an error when torch is also missing.
"""

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Graceful ML dependency imports — torch and diffvg are separate concerns
# ---------------------------------------------------------------------------

try:
    import torch
    TORCH_AVAILABLE = True
    try:
        import diffvg
        DIFFVG_AVAILABLE = True
    except ImportError:
        DIFFVG_AVAILABLE = False
except ImportError:
    TORCH_AVAILABLE = False
    DIFFVG_AVAILABLE = False


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
    layer_name: Optional[str] = Field(
        default=None,
        description="Illustrator layer name (for optimize_layer action)",
    )
    reference_path: Optional[str] = Field(
        default=None,
        description="Path to reference image (for optimize_layer action)",
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


# ---------------------------------------------------------------------------
# SVG parsing helpers for DiffVG integration
# ---------------------------------------------------------------------------


def _parse_svg_paths(svg_path: str) -> list[dict]:
    """Parse SVG file and extract path d="" elements.

    Returns a list of dicts with 'id', 'd' (path data string),
    'fill', and 'stroke' attributes.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()
    # Handle SVG namespace
    ns = {"svg": "http://www.w3.org/2000/svg"}
    paths = []
    # Search with and without namespace
    for path_el in root.iter():
        tag = path_el.tag
        # Strip namespace if present
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "path":
            d = path_el.get("d", "")
            if d:
                paths.append({
                    "id": path_el.get("id", ""),
                    "d": d,
                    "fill": path_el.get("fill", "none"),
                    "stroke": path_el.get("stroke", "none"),
                })
    return paths


def _parse_svg_dimensions(svg_path: str) -> tuple[int, int]:
    """Extract width and height from SVG viewBox or width/height attributes.

    Returns (width, height) as integers.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()
    viewbox = root.get("viewBox")
    if viewbox:
        parts = viewbox.split()
        if len(parts) == 4:
            return int(float(parts[2])), int(float(parts[3]))
    # Fall back to width/height attributes
    w = root.get("width", "256")
    h = root.get("height", "256")
    # Strip units like "px"
    w = "".join(c for c in w if c.isdigit() or c == ".")
    h = "".join(c for c in h if c.isdigit() or c == ".")
    return int(float(w or "256")), int(float(h or "256"))


def _export_optimized_svg(
    original_svg_path: str,
    optimized_paths_data: list[str],
    output_path: str,
) -> str:
    """Write optimized path d="" strings back to SVG file.

    Preserves all non-path elements and attributes from the original.
    Only updates the 'd' attribute of path elements, in order.
    """
    tree = ET.parse(original_svg_path)
    root = tree.getroot()
    path_idx = 0
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "path" and el.get("d"):
            if path_idx < len(optimized_paths_data):
                el.set("d", optimized_paths_data[path_idx])
                path_idx += 1
    tree.write(output_path, xml_declaration=True, encoding="unicode")
    return output_path


# ---------------------------------------------------------------------------
# DiffVG optimization (requires torch + diffvg)
# ---------------------------------------------------------------------------


def optimize_paths_diffvg(
    svg_path: str,
    target_image_path: str,
    iterations: int = 200,
    lr: float = 0.01,
) -> dict:
    """Optimize SVG paths against target image via differentiable rendering.

    Pipeline:
    1. PARSE: Load SVG, extract path d="" elements via xml.etree
    2. Convert path commands (M, C, L, Z) to diffvg.Path objects
    3. RENDER: diffvg.RenderFunction.apply() -> rendered tensor [H,W,4]
    4. LOSS: MSE between rendered[:,:,:3] and target[:,:,:3], both [0,1]
    5. BACKPROP: loss.backward() through differentiable rasterizer
    6. UPDATE: Adam optimizer on control point position tensors
    7. CONVERGE: Stop when loss delta < 1e-5 for 10 consecutive iters
    8. EXPORT: Convert optimized tensors back to SVG path d="" strings

    Args:
        svg_path: Path to input SVG file.
        target_image_path: Path to target raster image.
        iterations: Maximum optimization iterations.
        lr: Learning rate for Adam optimizer.

    Returns:
        dict with initial_loss, final_loss, iterations_run, output_svg_path.
    """
    if not DIFFVG_AVAILABLE:
        return {
            "error": "DiffVG not available. Install from source: "
                     "https://github.com/BachiLi/diffvg",
            "fallback": "Use path_gradient_approx for CPU-only optimization.",
        }

    import cv2
    import numpy as np

    # Load target image as torch tensor
    target_np = cv2.imread(target_image_path)
    if target_np is None:
        return {"error": f"Could not load target image: {target_image_path}"}
    target_np = cv2.cvtColor(target_np, cv2.COLOR_BGR2RGB)
    canvas_h, canvas_w = target_np.shape[:2]
    target_tensor = torch.tensor(
        target_np.astype(np.float32) / 255.0,
        device=torch.device("cpu"),
    )

    # Parse SVG paths
    svg_paths = _parse_svg_paths(svg_path)
    if not svg_paths:
        return {"error": "No paths found in SVG file."}

    # Load SVG scene via diffvg
    canvas_width, canvas_height = _parse_svg_dimensions(svg_path)
    # Use diffvg's SVG loader to get shapes and shape groups
    canvas_width, canvas_height, shapes, shape_groups = diffvg.svg_to_scene(svg_path)

    # Collect all trainable point tensors
    point_vars = []
    for shape in shapes:
        shape.points.requires_grad_(True)
        point_vars.append(shape.points)

    optimizer = torch.optim.Adam(point_vars, lr=lr)

    # Convergence tracking
    prev_loss_val = float("inf")
    patience_counter = 0
    initial_loss_val = None
    final_loss_val = None
    iterations_run = 0

    for i in range(iterations):
        optimizer.zero_grad()

        # Render scene
        scene_args = diffvg.RenderFunction.serialize_scene(
            canvas_width, canvas_height, shapes, shape_groups
        )
        rendered = diffvg.RenderFunction.apply(
            canvas_width, canvas_height, 2, *scene_args  # 2 = num_samples_x
        )

        # Compute loss: MSE on RGB channels
        # rendered is [H, W, 4], target_tensor is [H, W, 3]
        loss = torch.mean((rendered[:, :, :3] - target_tensor) ** 2)
        loss_val = loss.item()

        if initial_loss_val is None:
            initial_loss_val = loss_val

        # Backprop through differentiable rasterizer
        loss.backward()
        optimizer.step()

        iterations_run = i + 1
        final_loss_val = loss_val

        # Convergence check
        if abs(prev_loss_val - loss_val) < 1e-5:
            patience_counter += 1
            if patience_counter >= 10:
                break
        else:
            patience_counter = 0
        prev_loss_val = loss_val

    # Export optimized SVG
    output_dir = os.path.dirname(svg_path)
    base = os.path.splitext(os.path.basename(svg_path))[0]
    output_path = os.path.join(output_dir, f"{base}_optimized.svg")
    diffvg.save_svg(output_path, canvas_width, canvas_height, shapes, shape_groups)

    return {
        "initial_loss": initial_loss_val,
        "final_loss": final_loss_val,
        "iterations_run": iterations_run,
        "output_svg_path": output_path,
        "path_count": len(shapes),
        "converged": patience_counter >= 10,
    }


# ---------------------------------------------------------------------------
# Illustrator integration
# ---------------------------------------------------------------------------


def optimize_illustrator_paths(
    layer_name: str,
    reference_path: str,
    iterations: int = 200,
) -> dict:
    """Read paths from AI layer, optimize via DiffVG, apply back.

    Uses _build_read_jsx from auto_correct.py to read paths.
    Converts to SVG, optimizes, converts back, applies via _build_apply_jsx.

    This requires a running Illustrator instance and is only callable
    through the MCP tool registration path.

    Args:
        layer_name: Name of the Illustrator layer containing paths.
        reference_path: Path to the target reference image on disk.
        iterations: Number of optimization iterations.

    Returns:
        dict with optimization results or error information.
    """
    if not os.path.isfile(reference_path):
        return {"error": f"Reference image not found: {reference_path}"}

    if not DIFFVG_AVAILABLE and not TORCH_AVAILABLE:
        return {
            "error": "Neither DiffVG nor torch available. Cannot optimize.",
            "install_hint": (
                "Install torch: pip install torch>=2.0\n"
                "Install DiffVG from source: "
                "https://github.com/BachiLi/diffvg"
            ),
        }

    # This function requires Illustrator to be running -- the actual JSX
    # calls happen asynchronously via the MCP engine. For now, return
    # a description of what would happen; actual integration requires
    # the MCP event loop.
    return {
        "status": "pending_integration",
        "layer_name": layer_name,
        "reference_path": reference_path,
        "iterations": iterations,
        "diffvg_available": DIFFVG_AVAILABLE,
        "torch_available": TORCH_AVAILABLE,
        "note": (
            "Illustrator path optimization requires the MCP event loop. "
            "Use the 'optimize' action with an SVG file for standalone "
            "optimization, or the spatial_pipeline for end-to-end flow."
        ),
    }


# ---------------------------------------------------------------------------
# Status reporting
# ---------------------------------------------------------------------------


def _ml_status() -> dict:
    """Return availability status of DiffVG optimization.

    Reports torch and diffvg availability separately so callers can
    determine whether to fall back to path_gradient_approx.
    """
    status = {
        "torch_available": TORCH_AVAILABLE,
        "diffvg_available": DIFFVG_AVAILABLE,
        "tool": "DiffVG differentiable path optimization",
        "capabilities": [
            "SVG path control point optimization",
            "Pixel-level loss backpropagation",
            "Bezier curve refinement",
        ],
    }
    if TORCH_AVAILABLE:
        status["torch_version"] = torch.__version__
        if torch.cuda.is_available():
            status["device"] = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            status["device"] = "mps"
        else:
            status["device"] = "cpu"
    else:
        status["device"] = "unavailable"

    if not DIFFVG_AVAILABLE:
        status["diffvg_install_hint"] = (
            "DiffVG requires source compilation: "
            "https://github.com/BachiLi/diffvg"
        )
    if not TORCH_AVAILABLE:
        status["torch_install_hint"] = (
            'Install torch: pip install torch>=2.0 or uv pip install -e ".[ml-diffvg]"'
        )

    # Report fallback availability
    try:
        from adobe_mcp.apps.illustrator.path_gradient_approx import (
            optimize_paths_approx,
        )
        status["fallback_available"] = True
        status["fallback"] = "path_gradient_approx (finite-difference, CPU-only)"
    except ImportError:
        status["fallback_available"] = False

    return status


# ---------------------------------------------------------------------------
# Optimize dispatcher — routes to DiffVG or fallback
# ---------------------------------------------------------------------------


def _optimize_paths(
    svg_path: str,
    target_image_path: str,
    iterations: int,
    learning_rate: float,
) -> dict:
    """Optimize SVG paths against a target image.

    Routing:
    1. If DIFFVG_AVAILABLE: use optimize_paths_diffvg()
    2. Else if TORCH_AVAILABLE: fall back to path_gradient_approx
    3. Else: return error with install instructions
    """
    if not svg_path or not os.path.isfile(svg_path):
        return {"error": f"SVG file not found: {svg_path}"}

    if not target_image_path or not os.path.isfile(target_image_path):
        return {"error": f"Target image not found: {target_image_path}"}

    # Route 1: Full DiffVG differentiable rendering
    if DIFFVG_AVAILABLE:
        return optimize_paths_diffvg(
            svg_path, target_image_path, iterations, learning_rate
        )

    # Route 2: Fallback to finite-difference gradient approximation
    if TORCH_AVAILABLE:
        try:
            import cv2
            import numpy as np
            from adobe_mcp.apps.illustrator.path_gradient_approx import (
                optimize_paths_approx,
                rasterize_contours,
            )

            # Load target image
            target_np = cv2.imread(target_image_path, cv2.IMREAD_GRAYSCALE)
            if target_np is None:
                return {"error": f"Could not load target image: {target_image_path}"}
            target_float = target_np.astype(np.float32) / 255.0

            # Parse SVG paths into contours for the approx optimizer
            svg_paths = _parse_svg_paths(svg_path)
            if not svg_paths:
                return {"error": "No paths found in SVG file."}

            # Convert SVG path d="" strings to contour arrays
            # (simplified: extract coordinate pairs from path data)
            contours = _svg_paths_to_contours(svg_paths, target_float.shape)
            if not contours:
                return {"error": "Could not extract contours from SVG paths."}

            optimized, stats = optimize_paths_approx(
                contours,
                target_float,
                iterations=min(iterations, 50),  # Approx is slower, cap iterations
                lr=1.0,
                epsilon=0.5,
            )
            stats["method"] = "path_gradient_approx"
            stats["note"] = (
                "Used finite-difference fallback. For better quality, "
                "install DiffVG from source."
            )
            return stats
        except Exception as exc:
            return {"error": f"Fallback optimization failed: {exc}"}

    # Route 3: Nothing available
    return {
        "error": "Neither DiffVG nor torch is installed. Cannot optimize paths.",
        "install_hint": (
            'Install torch: pip install torch>=2.0 or uv pip install -e ".[ml-diffvg]"\n'
            "Install DiffVG from source: https://github.com/BachiLi/diffvg"
        ),
        "required_packages": ["torch", "diffvg (source build)"],
    }


def _svg_paths_to_contours(
    svg_paths: list[dict], canvas_shape: tuple[int, int]
) -> list:
    """Convert parsed SVG path dicts to numpy contour arrays.

    Simplified parser that handles M (moveto), L (lineto), and Z (close)
    commands. Cubic bezier (C) commands are sampled at control points only.
    For full bezier support, use DiffVG directly.

    Args:
        svg_paths: list of dicts from _parse_svg_paths().
        canvas_shape: (height, width) of the target canvas.

    Returns:
        list of Nx2 float64 numpy arrays.
    """
    import numpy as np
    import re

    contours = []
    for path_dict in svg_paths:
        d = path_dict["d"]
        # Tokenize: split on command letters, keeping them
        tokens = re.findall(r"[MmLlCcHhVvSsQqTtAaZz]|[-+]?\d*\.?\d+", d)
        points = []
        i = 0
        current_x, current_y = 0.0, 0.0
        while i < len(tokens):
            cmd = tokens[i]
            if cmd in ("M", "m"):
                i += 1
                if i + 1 < len(tokens):
                    x, y = float(tokens[i]), float(tokens[i + 1])
                    if cmd == "m":
                        x += current_x
                        y += current_y
                    current_x, current_y = x, y
                    points.append([x, y])
                    i += 2
            elif cmd in ("L", "l"):
                i += 1
                if i + 1 < len(tokens):
                    x, y = float(tokens[i]), float(tokens[i + 1])
                    if cmd == "l":
                        x += current_x
                        y += current_y
                    current_x, current_y = x, y
                    points.append([x, y])
                    i += 2
            elif cmd in ("C", "c"):
                # Cubic bezier: take all 3 coordinate pairs
                i += 1
                for _ in range(3):
                    if i + 1 < len(tokens):
                        x, y = float(tokens[i]), float(tokens[i + 1])
                        if cmd == "c":
                            x += current_x
                            y += current_y
                        i += 2
                # End point is the last pair
                if len(points) > 0 or (i >= 6):
                    # Record the endpoint of the cubic bezier
                    if i >= 2:
                        ex = float(tokens[i - 2])
                        ey = float(tokens[i - 1])
                        if cmd == "c":
                            ex += current_x
                            ey += current_y
                        current_x, current_y = ex, ey
                        points.append([ex, ey])
            elif cmd in ("H", "h"):
                i += 1
                if i < len(tokens):
                    x = float(tokens[i])
                    if cmd == "h":
                        x += current_x
                    current_x = x
                    points.append([current_x, current_y])
                    i += 1
            elif cmd in ("V", "v"):
                i += 1
                if i < len(tokens):
                    y = float(tokens[i])
                    if cmd == "v":
                        y += current_y
                    current_y = y
                    points.append([current_x, current_y])
                    i += 1
            elif cmd in ("Z", "z"):
                i += 1
                # Close path — no new point needed
            else:
                i += 1  # Skip unrecognized tokens

        if len(points) >= 2:
            contours.append(np.array(points, dtype=np.float64))

    return contours


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
        - status: Check ML availability (torch + diffvg) and device
        - optimize: Optimize SVG paths against a target image

        Routes to DiffVG when available, falls back to path_gradient_approx
        (finite-difference) when only torch is available, and returns an
        error with install instructions when neither is present.
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
