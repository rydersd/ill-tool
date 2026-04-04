"""ML-powered vectorization using StarVector (optional dependency).

Provides high-quality image-to-SVG conversion via a HuggingFace causal LM
that generates SVG code from raster images.  Falls back gracefully when ML
dependencies (torch, transformers) are not installed — all non-ML actions
still work and return helpful guidance for installation.
"""

import json
import os
import tempfile
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ---------------------------------------------------------------------------
# Graceful ML dependency import
# ---------------------------------------------------------------------------

try:
    from transformers import AutoModelForCausalLM, AutoProcessor
    import torch
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class VectorizeMLInput(BaseModel):
    """Control ML-powered vectorization."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="vectorize",
        description="Action: vectorize, check_model, status",
    )
    image_path: Optional[str] = Field(
        default=None, description="Image to vectorize"
    )
    model_id: str = Field(
        default="starvector/starvector-1b-im2svg",
        description="HuggingFace model ID",
    )
    max_tokens: int = Field(
        default=4096,
        description="Max SVG tokens to generate",
        ge=256,
        le=16384,
    )
    place_in_ai: bool = Field(
        default=False, description="Place result in Illustrator"
    )
    layer_name: str = Field(
        default="ML_Trace", description="Layer for placed result"
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def _ml_status() -> dict:
    """Return status of ML dependencies, GPU availability, and model cache."""
    status = {
        "ml_available": ML_AVAILABLE,
        "torch_installed": ML_AVAILABLE,
        "transformers_installed": ML_AVAILABLE,
    }
    if ML_AVAILABLE:
        status["torch_version"] = torch.__version__
        status["cuda_available"] = torch.cuda.is_available()
        status["mps_available"] = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        if status["cuda_available"]:
            status["device"] = "cuda"
        elif status["mps_available"]:
            status["device"] = "mps"
        else:
            status["device"] = "cpu"
    else:
        status["install_hint"] = 'Install ML dependencies with: uv pip install -e ".[ml]"'
        status["required_packages"] = ["torch", "transformers"]
        status["device"] = "unavailable"
    return status


def _check_model(model_id: str) -> dict:
    """Check if the model is cached locally, report size and status."""
    if not ML_AVAILABLE:
        return {
            "model_id": model_id,
            "available": False,
            "error": "ML dependencies not installed",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
        }

    # Check the HuggingFace cache for the model
    from huggingface_hub import scan_cache_dir, HFCacheInfo
    try:
        cache_info: HFCacheInfo = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == model_id:
                return {
                    "model_id": model_id,
                    "available": True,
                    "cached": True,
                    "size_bytes": repo.size_on_disk,
                    "size_mb": round(repo.size_on_disk / (1024 * 1024), 1),
                    "last_accessed": str(repo.last_accessed),
                }
    except Exception:
        pass

    return {
        "model_id": model_id,
        "available": True,
        "cached": False,
        "message": "Model not in local cache — will download on first use",
    }


def _vectorize_image(image_path: str, model_id: str, max_tokens: int) -> dict:
    """Run StarVector model to convert a raster image to SVG code.

    Returns the SVG string and a temp file path where it's saved.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot vectorize.",
            "install_hint": 'Install with: uv pip install -e ".[ml]"',
            "required_packages": ["torch", "transformers"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        from PIL import Image

        # Load and preprocess the image
        image = Image.open(image_path).convert("RGB")

        # Determine device
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

        # Load model and processor
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, trust_remote_code=True
        ).to(device)

        # Process image and generate SVG tokens
        inputs = processor(images=image, return_tensors="pt").to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
            )

        # Decode the generated tokens to SVG string
        svg_code = processor.batch_decode(outputs, skip_special_tokens=True)[0]

        # Extract SVG content (model may include preamble text)
        svg_start = svg_code.find("<svg")
        svg_end = svg_code.rfind("</svg>")
        if svg_start >= 0 and svg_end >= 0:
            svg_code = svg_code[svg_start:svg_end + 6]
        elif svg_start >= 0:
            # No closing tag — append one
            svg_code = svg_code[svg_start:] + "</svg>"

        # Save SVG to temp file
        svg_dir = tempfile.mkdtemp(prefix="ml_vectorize_")
        svg_path = os.path.join(svg_dir, "vectorized.svg")
        with open(svg_path, "w") as f:
            f.write(svg_code)

        # Count paths in SVG (rough estimate)
        path_count = svg_code.count("<path")

        return {
            "svg_path": svg_path,
            "svg_length": len(svg_code),
            "path_count": path_count,
            "model_id": model_id,
            "device": device,
            "max_tokens": max_tokens,
        }
    except Exception as exc:
        return {"error": f"Vectorization failed: {exc}"}


# ---------------------------------------------------------------------------
# JSX helper — place SVG in Illustrator
# ---------------------------------------------------------------------------


async def _place_svg_in_ai(svg_path: str, layer_name: str) -> dict:
    """Open the SVG in Illustrator and copy paths to the specified layer."""
    escaped_svg = escape_jsx_string(svg_path)
    escaped_layer = escape_jsx_string(layer_name)

    jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create the target layer
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i];
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}

    // Open the SVG as a new document
    var svgFile = new File("{escaped_svg}");
    var svgDoc = app.open(svgFile);

    // Select all in the SVG document
    svgDoc.selection = null;
    for (var j = 0; j < svgDoc.pageItems.length; j++) {{
        svgDoc.pageItems[j].selected = true;
    }}
    var itemCount = svgDoc.selection.length;

    // Copy and paste into the target document
    if (itemCount > 0) {{
        app.copy();
        svgDoc.close(SaveOptions.DONOTSAVECHANGES);
        app.activeDocument = doc;
        doc.activeLayer = layer;
        app.paste();
    }} else {{
        svgDoc.close(SaveOptions.DONOTSAVECHANGES);
    }}

    return JSON.stringify({{
        layer: "{escaped_layer}",
        items_placed: itemCount,
        placed: itemCount > 0
    }});
}})();
"""
    result = await _async_run_jsx("illustrator", jsx)
    if not result["success"]:
        return {"error": f"Placement failed: {result['stderr']}"}

    try:
        return json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        return {"raw": result["stdout"]}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_vectorize_ml tool."""

    @mcp.tool(
        name="adobe_ai_vectorize_ml",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_vectorize_ml(params: VectorizeMLInput) -> str:
        """ML-powered image vectorization using StarVector.

        Actions:
        - status: Check if ML dependencies are installed and GPU availability
        - check_model: Check if the StarVector model is downloaded
        - vectorize: Convert a raster image to SVG using the ML model

        Requires optional ML dependencies (torch, transformers). Install with:
            uv pip install -e ".[ml]"
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "check_model":
            return json.dumps(_check_model(params.model_id), indent=2)

        elif action == "vectorize":
            result = _vectorize_image(params.image_path, params.model_id, params.max_tokens)
            if "error" in result:
                return json.dumps(result, indent=2)

            # Optionally place in Illustrator
            if params.place_in_ai and "svg_path" in result:
                placement = await _place_svg_in_ai(result["svg_path"], params.layer_name)
                result["placement"] = placement

            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["vectorize", "check_model", "status"],
            })
