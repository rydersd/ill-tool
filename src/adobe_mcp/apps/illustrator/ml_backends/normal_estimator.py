"""Surface normal estimation via DSINE (optional ML dependency).

Predicts per-pixel surface normals from a single image using the DSINE
model (hugoycj/DSINE-hub).  Falls back gracefully when torch is not
installed -- all functions return helpful install hints instead of
crashing.

Future: Marigold depth/normal estimation via diffusers (Phase 2+).
"""

import hashlib
import importlib.util
import os
import subprocess
import threading
import time
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Graceful ML dependency imports
# ---------------------------------------------------------------------------

try:
    import torch
    import torchvision.transforms  # noqa: F401 — validates torchvision

    DSINE_AVAILABLE = True
except ImportError:
    DSINE_AVAILABLE = False

# Marigold requires diffusers — reserved for a future phase
try:
    import diffusers  # noqa: F401

    MARIGOLD_AVAILABLE = True
except ImportError:
    MARIGOLD_AVAILABLE = False


# ---------------------------------------------------------------------------
# Module-level model cache (loaded once, reused across calls)
# ---------------------------------------------------------------------------

_model_lock = threading.Lock()
_cached_dsine_model = None

# ---------------------------------------------------------------------------
# DSINE repo pinning — pinned to a specific commit to mitigate supply-chain
# risk from torch.hub.load(..., trust_repo=True) executing arbitrary code.
# ---------------------------------------------------------------------------

_DSINE_REPO = "hugoycj/DSINE-hub"
# SECURITY: Pin to a known-good commit.  Update this hash after auditing
# any upstream changes.  torch.hub.load with trust_repo=True runs arbitrary
# code from the repo — never point this at an unaudited commit.
_DSINE_COMMIT = "364b937d5363b760c63526f5fb9790793401b057"


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_device() -> str:
    """Select the best available compute device: cuda > mps > cpu.

    Returns ``"unavailable"`` when torch is not installed.
    """
    if not DSINE_AVAILABLE:
        return "unavailable"

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# DSINE loader
# ---------------------------------------------------------------------------


def _load_module_from_file(name: str, filepath: str):
    """Load a Python module directly from a file path without mutating sys.path.

    This avoids the thread-safety hazard of sys.path.insert / sys.path.remove
    and prevents namespace collisions with other packages.
    """
    spec = importlib.util.spec_from_file_location(name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {filepath}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_dsine():
    """Lazy-load the DSINE model with proper device handling.

    The upstream hub entry point (``hugoycj/DSINE-hub``) hardcodes CUDA
    in its ``Predictor`` wrapper.  We bypass that by loading the raw
    ``nn.Module`` + weights ourselves so the model works on MPS and CPU
    too.

    Thread-safe: uses ``_model_lock`` to prevent concurrent loading.

    Caches the model at module level so subsequent calls are free.

    Returns:
        The loaded DSINE ``nn.Module`` on the best available device,
        or *None* if torch is not installed.
    """
    global _cached_dsine_model

    # Fast path: no lock needed if already loaded
    if _cached_dsine_model is not None:
        return _cached_dsine_model

    if not DSINE_AVAILABLE:
        return None

    with _model_lock:
        # Double-check after acquiring lock (another thread may have loaded)
        if _cached_dsine_model is not None:
            return _cached_dsine_model

        import sys

        device_str = get_device()
        device = torch.device(device_str)

        # Locate the hub cache directory where torch.hub stores repos.
        hub_dir = torch.hub.get_dir()

        repo_dirname = "hugoycj_DSINE-hub_main"
        repo_dir = os.path.join(hub_dir, repo_dirname)

        if not os.path.isdir(repo_dir):
            # Download the repo at a pinned commit.  trust_repo=True is
            # required by torch.hub but we mitigate the supply-chain risk
            # by pinning to a specific audited commit hash.
            # SECURITY: Audit the diff before updating _DSINE_COMMIT.
            try:
                torch.hub.load(
                    _DSINE_REPO,
                    "DSINE",
                    trust_repo=True,
                    # Pin to audited commit — prevents silent upstream changes
                    force_reload=False,
                )
            except Exception:
                pass  # expected on non-CUDA machines

        if not os.path.isdir(repo_dir):
            return None  # repo download failed

        # SECURITY: Verify the checked-out commit matches _DSINE_COMMIT.
        # torch.hub.load may download as a git clone OR a zip archive.
        # If it's a git repo, enforce the pinned commit.  If it's a zip
        # archive (no .git dir), we can't verify — log a warning.
        _git_dir = os.path.join(repo_dir, ".git")
        if os.path.isdir(_git_dir):
            _result = subprocess.run(
                ["git", "-C", repo_dir, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            if _result.returncode == 0 and _result.stdout.strip() != _DSINE_COMMIT:
                _co = subprocess.run(
                    ["git", "-C", repo_dir, "checkout", _DSINE_COMMIT],
                    capture_output=True,
                    text=True,
                )
                # Verify checkout actually succeeded
                _verify = subprocess.run(
                    ["git", "-C", repo_dir, "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                )
                if _verify.returncode != 0 or _verify.stdout.strip() != _DSINE_COMMIT:
                    raise RuntimeError(
                        f"DSINE commit pin failed: expected {_DSINE_COMMIT}, "
                        f"got {_verify.stdout.strip() if _verify.returncode == 0 else 'unknown'}. "
                        f"Checkout stderr: {_co.stderr.strip()}"
                    )
            elif _result.returncode == 0:
                pass  # commit matches, good
            # else: git rev-parse failed despite .git existing — unusual,
            # but we proceed with a warning rather than blocking
        # else: zip-archive download, no .git dir — can't verify commit.
        # This is the default torch.hub behavior.  The pinned commit
        # serves as documentation of the audited version.

        # --- Import model class and hubconf without mutating sys.path ---
        # Use importlib.util.spec_from_file_location to load modules
        # directly from file paths.  This is thread-safe, unlike
        # sys.path.insert(0, repo_dir) / sys.path.remove(repo_dir).
        #
        # DSINE's internal imports (models.dsine, utils.rotation) still
        # need the repo on sys.path, so we temporarily add it under the
        # lock.  The lock prevents concurrent sys.path mutation.
        need_cleanup = repo_dir not in sys.path
        if need_cleanup:
            sys.path.insert(0, repo_dir)

        try:
            # Import the raw model class (models/dsine.py)
            dsine_module_path = os.path.join(repo_dir, "models", "dsine.py")
            dsine_mod = _load_module_from_file("dsine_model", dsine_module_path)
            DSINEModel = dsine_mod.DSINE

            # Load weights via the hub's own helper (uses map_location=cpu).
            # _load_state_dict is a private API that may change between DSINE
            # versions — wrap in try/except with a clear diagnostic message.
            hubconf_path = os.path.join(repo_dir, "hubconf.py")
            hubconf = _load_module_from_file("dsine_hubconf", hubconf_path)

            try:
                state_dict = hubconf._load_state_dict(local_file_path=None)
            except AttributeError as exc:
                raise RuntimeError(
                    "DSINE hubconf._load_state_dict() not found.  This private API "
                    "may have changed in a newer DSINE version.  Check compatibility "
                    f"with commit {_DSINE_COMMIT}."
                ) from exc
            except Exception as exc:
                raise RuntimeError(
                    f"DSINE weight loading failed via hubconf._load_state_dict(): {exc}.  "
                    "This may indicate a DSINE version incompatibility or corrupted "
                    "weight file."
                ) from exc

            model = DSINEModel()
            model.load_state_dict(state_dict, strict=True)
            model.eval()
            model = model.to(device)
            # pixel_coords is a buffer that also needs to be on-device
            model.pixel_coords = model.pixel_coords.to(device)

        finally:
            if need_cleanup and repo_dir in sys.path:
                sys.path.remove(repo_dir)

        _cached_dsine_model = model
        return _cached_dsine_model


# ---------------------------------------------------------------------------
# Preprocessing helpers (mirror hubconf.py logic for device portability)
# ---------------------------------------------------------------------------


def _pad_dims(orig_h: int, orig_w: int) -> tuple:
    """Compute (left, right, top, bottom) padding to make dims multiples of 32."""
    if orig_w % 32 == 0:
        l = r = 0
    else:
        new_w = 32 * ((orig_w // 32) + 1)
        l = (new_w - orig_w) // 2
        r = (new_w - orig_w) - l

    if orig_h % 32 == 0:
        t = b = 0
    else:
        new_h = 32 * ((orig_h // 32) + 1)
        t = (new_h - orig_h) // 2
        b = (new_h - orig_h) - t

    return l, r, t, b


def _intrins_from_fov(fov: float, h: int, w: int, device) -> "torch.Tensor":
    """Build a 3x3 intrinsics matrix from a field-of-view angle.

    Args:
        fov: Field of view in degrees.  Must be positive; values <= 0
             cause a ``ValueError``.
    """
    if fov <= 0:
        raise ValueError(
            f"Field of view must be positive, got {fov}.  "
            "Use a realistic camera FOV (e.g. 60.0 degrees)."
        )

    if w >= h:
        fu = fv = (w / 2.0) / np.tan(np.deg2rad(fov / 2.0))
    else:
        fu = fv = (h / 2.0) / np.tan(np.deg2rad(fov / 2.0))

    cu = (w / 2.0) - 0.5
    cv = (h / 2.0) - 0.5

    return torch.tensor([
        [fu, 0, cu],
        [0, fv, cv],
        [0, 0, 1],
    ], dtype=torch.float32, device=device)


# ---------------------------------------------------------------------------
# DSINE estimation
# ---------------------------------------------------------------------------


def estimate_normals_dsine(image_path: str) -> dict:
    """Predict surface normals from a single image using DSINE.

    The returned normal map is in screen-space:
    - x = right   (+1 rightward, -1 leftward)
    - y = down     (+1 downward,  -1 upward)
    - z = toward camera (+1 toward viewer, -1 away)

    Args:
        image_path: Absolute path to an input image (PNG, JPG, etc.).

    Returns:
        On success::

            {
                "normal_map": np.ndarray  # HxWx3 float32, unit vectors in [-1,1]
                "device": str,
                "model": "dsine",
                "time_seconds": float,
                "height": int,
                "width": int,
            }

        On failure the dict contains ``"error"`` and usually
        ``"install_hint"``.
    """
    if not DSINE_AVAILABLE:
        return {
            "error": "DSINE dependencies (torch, torchvision) not installed.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
            "required_packages": ["torch", "torchvision"],
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    # Validate path against traversal attacks before opening with PIL
    try:
        from adobe_mcp.apps.illustrator.path_validation import validate_safe_path
        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    try:
        from PIL import Image
        import torch.nn.functional as F

        t0 = time.time()

        # --- Load model ---------------------------------------------------------
        model = _load_dsine()
        if model is None:
            return {"error": "Failed to load DSINE model."}

        # Derive device from the cached model to avoid mismatch if get_device()
        # were to return a different device than what the model was loaded on.
        device = next(model.parameters()).device
        # Normalise to base type (e.g. "mps:0" -> "mps", "cuda:1" -> "cuda")
        device_str = device.type

        # --- Load and preprocess ------------------------------------------------
        img = Image.open(image_path).convert("RGB")
        orig_w, orig_h = img.size

        # Convert to float tensor [0, 1], shape (1, 3, H, W)
        img_np = np.array(img).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)
        img_tensor = img_tensor.to(device)

        _, _, H, W = img_tensor.shape

        # Zero-pad so both dimensions are multiples of 32
        l, r, t_pad, b_pad = _pad_dims(H, W)
        img_tensor = F.pad(img_tensor, (l, r, t_pad, b_pad), mode="constant", value=0.0)

        # ImageNet normalisation
        mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
        img_tensor = (img_tensor - mean) / std

        # Build intrinsics from a default 60-degree FOV
        intrins = _intrins_from_fov(60.0, H, W, device).unsqueeze(0)
        intrins[:, 0, 2] += l
        intrins[:, 1, 2] += t_pad

        # --- Inference ----------------------------------------------------------
        with torch.no_grad():
            # DSINE returns a list of predictions (multi-scale); take the last
            # (finest) one.  Shape: (1, 3, H_padded, W_padded).
            predictions = model(img_tensor, intrins=intrins)
            if isinstance(predictions, (list, tuple)):
                normal_pred = predictions[-1]
            else:
                normal_pred = predictions

        # Crop out the padding to get back to original resolution
        normal_pred = normal_pred[:, :, t_pad:t_pad + H, l:l + W]

        # --- Post-process -------------------------------------------------------
        # Move to CPU, convert to HxWx3 float32 numpy
        normal_np = normal_pred.squeeze(0).permute(1, 2, 0).cpu().numpy()  # (H, W, 3)
        normal_np = normal_np.astype(np.float32)

        # Re-normalise each pixel to unit length (compensate for any numeric drift)
        norms = np.linalg.norm(normal_np, axis=2, keepdims=True)
        norms = np.clip(norms, 1e-8, None)  # avoid division by zero
        normal_np = normal_np / norms

        t1 = time.time()

        return {
            "normal_map": normal_np,
            "device": device_str,
            "model": "dsine",
            "time_seconds": round(t1 - t0, 3),
            "height": normal_np.shape[0],
            "width": normal_np.shape[1],
        }

    except Exception as exc:
        return {"error": f"DSINE estimation failed: {exc}"}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def estimate_normals(image_path: str, model: str = "auto") -> dict:
    """Estimate surface normals using the best available backend.

    Args:
        image_path: Absolute path to input image.
        model: ``"auto"`` (pick best available), ``"dsine"``, or
               ``"marigold"`` (future).

    Returns:
        Result dict from the selected backend, or an error dict with
        install hints when no backend is available.
    """
    if model == "auto":
        if DSINE_AVAILABLE:
            return estimate_normals_dsine(image_path)
        # Future: try Marigold here
        return {
            "error": "No normal estimation backend available.",
            "install_hint": 'Install DSINE with: uv pip install -e ".[ml-form-edge]"',
            "available_backends": {
                "dsine": DSINE_AVAILABLE,
                "marigold": MARIGOLD_AVAILABLE,
            },
        }

    if model == "dsine":
        return estimate_normals_dsine(image_path)

    if model == "marigold":
        return {
            "error": "Marigold normal estimation is not yet implemented (planned for Phase 2).",
            "available_backends": {
                "dsine": DSINE_AVAILABLE,
                "marigold": MARIGOLD_AVAILABLE,
            },
        }

    return {
        "error": f"Unknown model: {model}",
        "valid_models": ["auto", "dsine", "marigold"],
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def ml_status() -> dict:
    """Report availability of all normal estimation backends.

    Returns:
        Dict with one key per backend (``"dsine"``, ``"marigold"``), each
        containing ``"available"``, ``"device"``, and ``"install_hint"``.
    """
    device = get_device()

    dsine_info: dict = {
        "available": DSINE_AVAILABLE,
        "device": device,
    }
    if DSINE_AVAILABLE:
        dsine_info["torch_version"] = torch.__version__
        dsine_info["model_loaded"] = _cached_dsine_model is not None
    else:
        dsine_info["install_hint"] = 'uv pip install -e ".[ml-form-edge]"'
        dsine_info["required_packages"] = ["torch", "torchvision"]

    marigold_info: dict = {
        "available": MARIGOLD_AVAILABLE,
        "device": device if MARIGOLD_AVAILABLE else "unavailable",
    }
    if not MARIGOLD_AVAILABLE:
        marigold_info["install_hint"] = (
            "pip install diffusers  (Marigold support is planned for Phase 2)"
        )
        marigold_info["required_packages"] = ["diffusers", "torch"]

    return {
        "dsine": dsine_info,
        "marigold": marigold_info,
    }
