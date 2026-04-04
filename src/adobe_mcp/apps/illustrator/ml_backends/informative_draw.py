"""Informative Drawings ONNX backend for artist-like line extraction.

Extracts clean, artist-style line drawings from photographs using the
Informative Drawings model (Chan & Durand, ECCV 2022).  The ONNX model
is lightweight (~17MB) and runs via onnxruntime without requiring torch.

Model source: HuggingFace hub ``carolineec/informative-drawings``.
Paper: https://arxiv.org/abs/2203.12691

Falls back gracefully when onnxruntime or huggingface_hub are not
installed -- all functions return helpful install hints.
"""

import os
import threading
import time
from typing import Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Graceful ML dependency imports
# ---------------------------------------------------------------------------

INFORMATIVE_AVAILABLE = False
_informative_import_error: Optional[str] = None

try:
    import onnxruntime  # noqa: F401

    INFORMATIVE_AVAILABLE = True
except ImportError:
    _informative_import_error = (
        "onnxruntime not installed.  "
        "Install with: uv pip install -e \".[ml-form-edge]\""
    )

# huggingface_hub is needed to download the model
_HF_HUB_AVAILABLE = False
try:
    import huggingface_hub  # noqa: F401

    _HF_HUB_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Module-level session cache (loaded once, reused across calls)
# ---------------------------------------------------------------------------

_model_lock = threading.Lock()
_cached_session = None

# Model coordinates on HuggingFace
_HF_REPO_ID = "carolineec/informative-drawings"
_HF_MODEL_FILENAME = "model2.onnx"


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def _load_session():
    """Lazy-load the ONNX inference session.

    Downloads the model from HuggingFace Hub on first call, then caches
    the session at module level.

    Thread-safe: uses ``_model_lock`` to prevent concurrent loading.

    Returns:
        ``onnxruntime.InferenceSession`` or *None* if dependencies are
        missing.
    """
    global _cached_session

    # Fast path: no lock needed if already loaded
    if _cached_session is not None:
        return _cached_session

    if not INFORMATIVE_AVAILABLE:
        return None

    with _model_lock:
        # Double-check after acquiring lock
        if _cached_session is not None:
            return _cached_session

        import onnxruntime

        # Locate the model file — try HuggingFace Hub download first,
        # then fall back to a local path if someone placed it manually.
        model_path = None

        if _HF_HUB_AVAILABLE:
            try:
                from huggingface_hub import hf_hub_download

                model_path = hf_hub_download(
                    repo_id=_HF_REPO_ID,
                    filename=_HF_MODEL_FILENAME,
                )
            except Exception:
                pass  # download failed, try local fallback

        # Local fallback: check a well-known cache location
        if model_path is None or not os.path.isfile(model_path):
            local_candidates = [
                os.path.expanduser(
                    f"~/.cache/huggingface/hub/models--carolineec--informative-drawings/"
                    f"snapshots/*/{_HF_MODEL_FILENAME}"
                ),
                os.path.expanduser(f"~/.cache/informative_drawings/{_HF_MODEL_FILENAME}"),
            ]
            import glob as _glob

            for pattern in local_candidates:
                matches = _glob.glob(pattern)
                if matches:
                    model_path = matches[0]
                    break

        if model_path is None or not os.path.isfile(model_path):
            return None

        # Create ONNX session with CPU provider (GPU optional)
        providers = ["CPUExecutionProvider"]
        try:
            # Prefer GPU if available
            if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                providers.insert(0, "CUDAExecutionProvider")
        except Exception:
            pass

        session = onnxruntime.InferenceSession(model_path, providers=providers)
        _cached_session = session
        return _cached_session


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def informative_drawings(image_path: str, threshold: float = 0.5) -> dict:
    """Extract artist-like line drawing from an image.

    Preprocesses the input image (resize to 512x512, normalize to [0,1],
    NCHW float32), runs the Informative Drawings ONNX model, and returns
    the thresholded single-channel line drawing.

    Args:
        image_path: Absolute path to input image (PNG/JPG).
        threshold: Binarization threshold (0.0 = keep all lines,
            1.0 = keep nothing).  Applied after model output is
            normalized to [0, 1].

    Returns:
        On success::

            {
                "line_drawing": np.ndarray (HxW uint8, 0 or 255),
                "line_drawing_raw": np.ndarray (HxW float32, [0,1]),
                "model": "informative_drawings",
                "time_seconds": float,
                "height": int,
                "width": int,
                "threshold": float,
            }

        On failure the dict contains ``"error"`` and usually
        ``"install_hint"``.
    """
    if not INFORMATIVE_AVAILABLE:
        return {
            "error": "onnxruntime not installed.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
            "required_packages": ["onnxruntime"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Validate path against traversal attacks
    try:
        from adobe_mcp.apps.illustrator.path_validation import validate_safe_path

        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    try:
        t0 = time.time()

        # Load ONNX session
        session = _load_session()
        if session is None:
            return {
                "error": "Failed to load Informative Drawings ONNX model.",
                "install_hint": (
                    "Model download requires huggingface_hub: "
                    "pip install huggingface_hub.  "
                    "Model: carolineec/informative-drawings (model2.onnx)"
                ),
            }

        # Load and preprocess image
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}

        orig_h, orig_w = image.shape[:2]

        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Resize to 512x512 (model input size)
        img_resized = cv2.resize(img_rgb, (512, 512), interpolation=cv2.INTER_AREA)

        # Normalize to [0, 1] float32
        img_float = img_resized.astype(np.float32) / 255.0

        # Convert to NCHW format: (1, 3, 512, 512)
        img_nchw = np.transpose(img_float, (2, 0, 1))[np.newaxis, ...]

        # Run inference
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: img_nchw})

        # Parse output — single-channel line drawing
        raw_output = outputs[0]  # shape: (1, 1, 512, 512) or (1, 512, 512)

        # Squeeze to 2D
        if raw_output.ndim == 4:
            line_map = raw_output[0, 0]  # (512, 512)
        elif raw_output.ndim == 3:
            line_map = raw_output[0]  # (512, 512)
        else:
            line_map = raw_output

        # Normalize to [0, 1]
        lmin, lmax = line_map.min(), line_map.max()
        if lmax > lmin:
            line_map = (line_map - lmin) / (lmax - lmin)
        else:
            line_map = np.zeros_like(line_map)

        line_map = line_map.astype(np.float32)

        # Resize back to original dimensions
        if line_map.shape != (orig_h, orig_w):
            line_map = cv2.resize(
                line_map, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR
            )

        # Threshold to binary
        binary = ((line_map > threshold) * 255).astype(np.uint8)

        t1 = time.time()

        return {
            "line_drawing": binary,
            "line_drawing_raw": line_map,
            "model": "informative_drawings",
            "time_seconds": round(t1 - t0, 4),
            "height": orig_h,
            "width": orig_w,
            "threshold": threshold,
        }

    except Exception as exc:
        return {"error": f"Informative Drawings inference failed: {exc}"}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def ml_status() -> dict:
    """Report availability of the Informative Drawings backend.

    Returns:
        Dict with key ``"informative_drawings"`` containing
        ``"available"``, ``"install_hint"`` (if needed), and
        ``"model_loaded"``.
    """
    info: dict = {
        "available": INFORMATIVE_AVAILABLE,
    }

    if INFORMATIVE_AVAILABLE:
        import onnxruntime

        info["onnxruntime_version"] = onnxruntime.__version__
        info["model_loaded"] = _cached_session is not None
        info["hf_hub_available"] = _HF_HUB_AVAILABLE
    else:
        info["install_hint"] = (
            'Install onnxruntime with: uv pip install -e ".[ml-form-edge]"  '
            "Also install huggingface_hub for automatic model download: "
            "pip install huggingface_hub"
        )
        info["required_packages"] = ["onnxruntime", "huggingface_hub"]

    return {
        "informative_drawings": info,
    }
