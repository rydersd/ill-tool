"""RINDNet++ edge type classification (optional ML dependency).

Classifies edge pixels into four types: reflectance (material boundaries),
illumination (shadow edges), normal (surface orientation changes), and
depth (occlusion boundaries).  Form edges = normal | depth; shadow edges
= illumination.

Falls back to a heuristic approach when RINDNet++ is not installed:
runs Canny at multiple thresholds and uses the DSINE normal map (if
available) to classify which edges are near normal discontinuities
(form) vs not (likely shadow).

RINDNet++ is a research repository (GitHub: MengyangPu/RINDNet-plusplus)
and is NOT pip-installable.  The wrapper provides install hints and a
heuristic fallback that is always available.
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

RINDNET_AVAILABLE = False
_rindnet_import_error: Optional[str] = None

try:
    import torch

    # RINDNet++ is a research repo — check if its module is importable.
    # Users must clone and install it manually.
    try:
        import rindnet  # noqa: F401

        RINDNET_AVAILABLE = True
    except ImportError:
        _rindnet_import_error = (
            "rindnet package not found.  RINDNet++ is a research repository "
            "and must be installed from source: "
            "https://github.com/MengyangPu/RINDNet-plusplus"
        )
except ImportError:
    _rindnet_import_error = (
        "torch not installed.  Install with: uv pip install -e \".[ml-form-edge]\""
    )

# DSINE availability for heuristic fallback enhancement
try:
    from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
        estimate_normals_dsine,
        DSINE_AVAILABLE,
    )
except ImportError:
    DSINE_AVAILABLE = False

    def estimate_normals_dsine(image_path: str) -> dict:
        """Stub when normal estimator is not available."""
        return {"error": "DSINE not available"}


# ---------------------------------------------------------------------------
# Module-level model cache (loaded once, reused across calls)
# ---------------------------------------------------------------------------

_model_lock = threading.Lock()
_cached_rindnet_model = None


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def _get_device() -> str:
    """Select the best available compute device: cuda > mps > cpu.

    Returns ``"unavailable"`` when torch is not installed.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    except ImportError:
        return "unavailable"


# ---------------------------------------------------------------------------
# Heuristic edge classification (always available)
# ---------------------------------------------------------------------------


def _heuristic_classify_edges(
    image_path: str,
    normal_map: Optional[np.ndarray] = None,
) -> dict:
    """Classify edges using Canny + optional DSINE normal map.

    Runs Canny edge detection at multiple thresholds and then uses the
    normal map gradient magnitude to classify which Canny edges lie near
    surface orientation discontinuities (form edges) vs those that don't
    (likely shadow/illumination edges).

    When no normal map is available, all persistent Canny edges are
    classified as form edges and shadow classification is unavailable
    (zeros).

    Args:
        image_path: Absolute path to input image.
        normal_map: Optional HxWx3 float32 normal map from DSINE.
            If None, attempts to run DSINE; if that fails, uses
            Canny-only classification.

    Returns:
        Dict with reflectance, illumination, normal, depth, form_edges,
        shadow_edges masks plus metadata.
    """
    from adobe_mcp.apps.illustrator.path_validation import validate_safe_path

    t0 = time.time()

    # Validate path
    try:
        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    image = cv2.imread(image_path)
    if image is None:
        return {"error": f"Failed to read image: {image_path}"}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    # Multi-threshold Canny for robust edge detection
    num_exposures = 5
    vote_map = np.zeros((h, w), dtype=np.int32)
    max_val = float(gray.max())

    if max_val == 0:
        # All-black image — no edges
        empty = np.zeros((h, w), dtype=np.uint8)
        return {
            "reflectance": empty,
            "illumination": empty,
            "normal": empty,
            "depth": empty,
            "form_edges": empty,
            "shadow_edges": empty,
            "model": "heuristic",
            "device": "cpu",
            "time_seconds": round(time.time() - t0, 4),
        }

    for i in range(num_exposures):
        frac = 0.1 + 0.8 * i / max(1, num_exposures - 1)
        low = max(1, int(max_val * frac * 0.5))
        high = max(low + 1, int(max_val * frac))
        edges = cv2.Canny(gray, low, high)
        vote_map += (edges > 0).astype(np.int32)

    # Persistent edges (appear in >= 3 of 5 exposures)
    persistent_edges = (vote_map >= 3).astype(np.uint8) * 255

    # Try to get a normal map for form/shadow classification
    if normal_map is None and DSINE_AVAILABLE:
        dsine_result = estimate_normals_dsine(image_path)
        if "error" not in dsine_result:
            normal_map = dsine_result.get("normal_map")

    if normal_map is not None and normal_map.shape[:2] == (h, w):
        # Compute gradient magnitude on normal map channels
        grad_mag = np.zeros((h, w), dtype=np.float32)
        for ch in range(min(3, normal_map.shape[2])):
            gx = cv2.Sobel(normal_map[:, :, ch], cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(normal_map[:, :, ch], cv2.CV_32F, 0, 1, ksize=3)
            grad_mag += np.sqrt(gx ** 2 + gy ** 2)

        # Normalize to [0, 1]
        gmax = grad_mag.max()
        if gmax > 0:
            grad_mag /= gmax

        # Edges near high normal gradients are form edges
        # Threshold: edges where normal gradient > 0.15 are form edges
        normal_edge_mask = (grad_mag > 0.15).astype(np.uint8)

        # Form edges: persistent Canny edges that coincide with normal
        # discontinuities.  Dilate the normal mask slightly to catch
        # nearby Canny edges.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        normal_dilated = cv2.dilate(normal_edge_mask, kernel, iterations=1)

        form_edges = cv2.bitwise_and(persistent_edges, normal_dilated * 255)

        # Shadow edges: persistent Canny edges NOT near normal discontinuities
        shadow_edges = cv2.bitwise_and(
            persistent_edges,
            cv2.bitwise_not(normal_dilated * 255),
        )

        # Map to RINDNet++ categories for interface compatibility:
        # - "normal" = surface orientation changes (form)
        # - "depth" = occlusion (also form — set to zero for heuristic)
        # - "illumination" = shadow edges
        # - "reflectance" = material boundaries (set to zero for heuristic)
        normal_mask = form_edges
        depth_mask = np.zeros((h, w), dtype=np.uint8)
        illumination_mask = shadow_edges
        reflectance_mask = np.zeros((h, w), dtype=np.uint8)
    else:
        # No normal map — classify all persistent edges as form edges,
        # cannot distinguish shadow edges
        form_edges = persistent_edges.copy()
        shadow_edges = np.zeros((h, w), dtype=np.uint8)
        normal_mask = persistent_edges.copy()
        depth_mask = np.zeros((h, w), dtype=np.uint8)
        illumination_mask = np.zeros((h, w), dtype=np.uint8)
        reflectance_mask = np.zeros((h, w), dtype=np.uint8)

    t1 = time.time()

    return {
        "reflectance": reflectance_mask,
        "illumination": illumination_mask,
        "normal": normal_mask,
        "depth": depth_mask,
        "form_edges": form_edges,
        "shadow_edges": shadow_edges,
        "model": "heuristic",
        "device": "cpu",
        "time_seconds": round(t1 - t0, 4),
    }


# ---------------------------------------------------------------------------
# RINDNet++ inference
# ---------------------------------------------------------------------------


def classify_edges_rindnet(image_path: str) -> dict:
    """Classify every edge pixel as one of four types using RINDNet++.

    Returns:
        On success::

            {
                "reflectance": np.ndarray (HxW uint8 mask),  # material boundaries
                "illumination": np.ndarray (HxW uint8 mask),  # shadow edges
                "normal": np.ndarray (HxW uint8 mask),        # surface orientation (FORM)
                "depth": np.ndarray (HxW uint8 mask),          # occlusion boundaries (FORM)
                "form_edges": np.ndarray (HxW uint8),          # normal | depth combined
                "shadow_edges": np.ndarray (HxW uint8),        # illumination only
                "model": "rindnet",
                "device": str,
                "time_seconds": float,
            }

        On failure::

            {
                "error": str,
                "install_hint": str,
                "fallback_available": True,
            }

        When RINDNet++ is unavailable, falls back to the heuristic
        classifier automatically.
    """
    if not RINDNET_AVAILABLE:
        # Fall back to heuristic classification
        return _heuristic_classify_edges(image_path)

    # --- RINDNet++ model path (when installed) ---
    # This block executes only when rindnet is importable.
    # Implementation would load the model, run inference, and return
    # the four-channel edge classification.  Since rindnet is a research
    # repo that requires manual installation, this path is reached only
    # by users who have followed the install instructions.
    t0 = time.time()

    try:
        from adobe_mcp.apps.illustrator.path_validation import validate_safe_path

        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    if not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        import torch

        device_str = _get_device()
        device = torch.device(device_str)

        global _cached_rindnet_model
        with _model_lock:
            if _cached_rindnet_model is None:
                # Load the RINDNet++ model
                # NOTE: Actual loading depends on the rindnet package API.
                # This is a placeholder for the model loading code that
                # would be filled in once the rindnet package structure
                # is confirmed.
                import rindnet

                model = rindnet.RINDNetPlusPlus()
                model.eval()
                model = model.to(device)
                _cached_rindnet_model = model

        model = _cached_rindnet_model

        # Load and preprocess image
        image = cv2.imread(image_path)
        if image is None:
            return {"error": f"Failed to read image: {image_path}"}

        h, w = image.shape[:2]
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        img_float = img_rgb.astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_float).permute(2, 0, 1).unsqueeze(0)
        img_tensor = img_tensor.to(device)

        # Run inference
        with torch.no_grad():
            outputs = model(img_tensor)

        # Parse outputs — RINDNet++ produces 4-channel edge maps:
        # [reflectance, illumination, normal, depth]
        # Each is a probability map that we threshold to binary
        if isinstance(outputs, (list, tuple)) and len(outputs) >= 4:
            reflectance = (outputs[0].squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
            illumination = (outputs[1].squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
            normal = (outputs[2].squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
            depth = (outputs[3].squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
        else:
            return {
                "error": "Unexpected RINDNet++ output format.",
                "fallback_available": True,
            }

        # Composite masks
        form_edges = cv2.bitwise_or(normal, depth)
        shadow_edges = illumination.copy()

        t1 = time.time()

        return {
            "reflectance": reflectance,
            "illumination": illumination,
            "normal": normal,
            "depth": depth,
            "form_edges": form_edges,
            "shadow_edges": shadow_edges,
            "model": "rindnet",
            "device": device_str,
            "time_seconds": round(t1 - t0, 4),
        }

    except Exception as exc:
        return {
            "error": f"RINDNet++ inference failed: {exc}",
            "fallback_available": True,
        }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def ml_status() -> dict:
    """Report availability of edge classification backends.

    Returns:
        Dict with keys ``"rindnet"`` and ``"heuristic"``, each containing
        ``"available"``, ``"device"``, and ``"install_hint"`` (if needed).
    """
    device = _get_device()

    rindnet_info: dict = {
        "available": RINDNET_AVAILABLE,
        "device": device if RINDNET_AVAILABLE else "unavailable",
    }
    if RINDNET_AVAILABLE:
        rindnet_info["model_loaded"] = _cached_rindnet_model is not None
    else:
        rindnet_info["install_hint"] = (
            "RINDNet++ is a research repository.  Clone and install from: "
            "https://github.com/MengyangPu/RINDNet-plusplus  "
            "Also requires torch: uv pip install -e \".[ml-form-edge]\""
        )

    heuristic_info: dict = {
        "available": True,
        "device": "cpu",
        "description": (
            "Multi-threshold Canny + optional DSINE normal map for "
            "form/shadow classification.  Always available."
        ),
        "dsine_enhanced": DSINE_AVAILABLE,
    }

    return {
        "rindnet": rindnet_info,
        "heuristic": heuristic_info,
    }
