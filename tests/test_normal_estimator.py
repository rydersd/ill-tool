"""Tests for DSINE surface normal estimation ML backend.

Tests work both WITH and WITHOUT ML dependencies (torch, torchvision).
Validates graceful fallback, status reporting, device selection, thread
safety, FOV validation, and (when DSINE is available) output shape and
dtype correctness.
"""

import os
import threading
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
    DSINE_AVAILABLE,
    MARIGOLD_AVAILABLE,
    _intrins_from_fov,
    _load_module_from_file,
    _model_lock,
    estimate_normals,
    estimate_normals_dsine,
    get_device,
    ml_status,
)


# ---------------------------------------------------------------------------
# ml_status: correct structure regardless of ML availability
# ---------------------------------------------------------------------------


class TestMLStatus:
    """ml_status() returns well-formed dicts in all environments."""

    def test_status_has_both_backends(self):
        """Status dict contains keys for dsine and marigold."""
        status = ml_status()
        assert "dsine" in status
        assert "marigold" in status

    def test_dsine_entry_structure(self):
        """DSINE status has required fields."""
        status = ml_status()
        dsine = status["dsine"]

        assert "available" in dsine
        assert isinstance(dsine["available"], bool)
        assert "device" in dsine

        if dsine["available"]:
            assert "torch_version" in dsine
            assert "model_loaded" in dsine
            assert dsine["device"] in ("cuda", "mps", "cpu")
        else:
            assert "install_hint" in dsine
            assert "required_packages" in dsine
            assert "torch" in dsine["required_packages"]
            assert "torchvision" in dsine["required_packages"]

    def test_marigold_entry_structure(self):
        """Marigold status has required fields."""
        status = ml_status()
        marigold = status["marigold"]

        assert "available" in marigold
        assert isinstance(marigold["available"], bool)
        assert "device" in marigold

        if not marigold["available"]:
            assert "install_hint" in marigold
            assert "required_packages" in marigold

    def test_status_reflects_actual_availability(self):
        """Status booleans match the module-level flags."""
        status = ml_status()
        assert status["dsine"]["available"] == DSINE_AVAILABLE
        assert status["marigold"]["available"] == MARIGOLD_AVAILABLE


# ---------------------------------------------------------------------------
# get_device: returns a valid string
# ---------------------------------------------------------------------------


class TestGetDevice:
    """get_device() returns a recognised device string."""

    def test_returns_string(self):
        """Device is always a string."""
        device = get_device()
        assert isinstance(device, str)

    def test_valid_device_name(self):
        """Device is one of the known options."""
        device = get_device()
        assert device in ("cuda", "mps", "cpu", "unavailable")

    def test_unavailable_when_no_torch(self):
        """Device is 'unavailable' when torch cannot be imported."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            False,
        ):
            assert get_device() == "unavailable"

    def test_device_matches_availability(self):
        """If DSINE is available, device must not be 'unavailable'."""
        if DSINE_AVAILABLE:
            assert get_device() != "unavailable"


# ---------------------------------------------------------------------------
# Graceful fallback: helpful errors when ML unavailable
# ---------------------------------------------------------------------------


class TestGracefulFallback:
    """All estimation functions degrade gracefully without ML deps."""

    def test_estimate_normals_dsine_without_ml(self):
        """estimate_normals_dsine returns error + install_hint."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            False,
        ):
            result = estimate_normals_dsine("/tmp/test.png")

        assert "error" in result
        assert "install_hint" in result
        assert "ml-form-edge" in result["install_hint"]
        assert "required_packages" in result

    def test_estimate_normals_auto_without_ml(self):
        """estimate_normals(model='auto') returns error when no backend."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            False,
        ):
            result = estimate_normals("/tmp/test.png", model="auto")

        assert "error" in result
        assert "install_hint" in result
        assert "available_backends" in result

    def test_estimate_normals_dsine_explicit_without_ml(self):
        """estimate_normals(model='dsine') returns error when unavailable."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            False,
        ):
            result = estimate_normals("/tmp/test.png", model="dsine")

        assert "error" in result
        assert "install_hint" in result

    def test_marigold_not_yet_implemented(self):
        """Requesting marigold explicitly returns 'not implemented' error."""
        result = estimate_normals("/tmp/test.png", model="marigold")
        assert "error" in result
        assert "not yet implemented" in result["error"].lower()

    def test_unknown_model_returns_error(self):
        """estimate_normals with bogus model name returns error."""
        result = estimate_normals("/tmp/test.png", model="fakenet")
        assert "error" in result
        assert "valid_models" in result
        assert "dsine" in result["valid_models"]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Bad inputs produce clear error messages."""

    def test_nonexistent_image_dsine(self):
        """estimate_normals_dsine with missing file returns error."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            True,
        ):
            result = estimate_normals_dsine("/nonexistent/path/fake.png")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_none_image_path(self):
        """estimate_normals_dsine with None path returns error."""
        with patch(
            "adobe_mcp.apps.illustrator.ml_backends.normal_estimator.DSINE_AVAILABLE",
            True,
        ):
            result = estimate_normals_dsine(None)
        assert "error" in result


# ---------------------------------------------------------------------------
# FOV validation (fix #6)
# ---------------------------------------------------------------------------


class TestFOVValidation:
    """_intrins_from_fov rejects invalid FOV values."""

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="torch not installed")
    def test_zero_fov_raises(self):
        """FOV of 0 raises ValueError."""
        import torch

        with pytest.raises(ValueError, match="must be positive"):
            _intrins_from_fov(0.0, 64, 64, torch.device("cpu"))

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="torch not installed")
    def test_negative_fov_raises(self):
        """Negative FOV raises ValueError."""
        import torch

        with pytest.raises(ValueError, match="must be positive"):
            _intrins_from_fov(-30.0, 64, 64, torch.device("cpu"))

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="torch not installed")
    def test_valid_fov_succeeds(self):
        """Positive FOV produces a 3x3 intrinsics matrix."""
        import torch

        result = _intrins_from_fov(60.0, 64, 64, torch.device("cpu"))
        assert result.shape == (3, 3)
        assert result.dtype == torch.float32


# ---------------------------------------------------------------------------
# Thread safety (fix #2)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Model loading lock exists and is a threading.Lock."""

    def test_model_lock_exists(self):
        """Module-level _model_lock is a Lock instance."""
        assert isinstance(_model_lock, type(threading.Lock()))

    def test_lock_is_reentrant_safe(self):
        """Lock can be acquired and released without deadlock."""
        # Just verify the lock is functional
        acquired = _model_lock.acquire(timeout=1)
        if acquired:
            _model_lock.release()
        assert acquired


# ---------------------------------------------------------------------------
# Module loader helper (fix #3)
# ---------------------------------------------------------------------------


class TestLoadModuleFromFile:
    """_load_module_from_file loads modules without sys.path mutation."""

    def test_load_nonexistent_file_raises(self):
        """Attempting to load a nonexistent file raises ImportError."""
        with pytest.raises((ImportError, FileNotFoundError)):
            _load_module_from_file("fake_mod", "/nonexistent/path/fake.py")

    def test_load_real_module(self, tmp_path):
        """Can load a simple Python module from a file path."""
        mod_file = tmp_path / "test_mod.py"
        mod_file.write_text("VALUE = 42\n")
        mod = _load_module_from_file("test_mod", str(mod_file))
        assert mod.VALUE == 42


# ---------------------------------------------------------------------------
# DSINE integration (runs only when torch+torchvision are installed)
# ---------------------------------------------------------------------------


class TestDSINEIntegration:
    """Integration tests that exercise the real DSINE model.

    These tests run naturally when DSINE dependencies are installed,
    and are skipped otherwise -- no special markers needed.
    """

    @pytest.fixture(scope="class")
    def test_image(self, tmp_path_factory):
        """Create a simple synthetic test image."""
        path = str(tmp_path_factory.mktemp("normals") / "test_sphere.png")
        # 64x64 gradient image -- enough for DSINE to process
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        for y in range(64):
            for x in range(64):
                img[y, x] = (x * 4, y * 4, 128)
        import cv2
        cv2.imwrite(path, img)
        return path

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="DSINE not installed")
    def test_dsine_output_shape_and_dtype(self, test_image):
        """DSINE output is HxWx3 float32 with unit-length normals."""
        result = estimate_normals_dsine(test_image)
        assert "error" not in result, f"DSINE failed: {result.get('error')}"

        normal_map = result["normal_map"]
        assert isinstance(normal_map, np.ndarray)
        assert normal_map.dtype == np.float32
        assert normal_map.ndim == 3
        assert normal_map.shape[2] == 3  # RGB channels = xyz normals

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="DSINE not installed")
    def test_dsine_normals_are_unit_vectors(self, test_image):
        """Each pixel's normal vector has magnitude ~1.0."""
        result = estimate_normals_dsine(test_image)
        assert "error" not in result

        normal_map = result["normal_map"]
        norms = np.linalg.norm(normal_map, axis=2)
        # Allow small floating-point tolerance
        assert np.allclose(norms, 1.0, atol=1e-4), (
            f"Normal magnitudes range: [{norms.min():.6f}, {norms.max():.6f}]"
        )

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="DSINE not installed")
    def test_dsine_normals_value_range(self, test_image):
        """Normal components are in [-1, 1]."""
        result = estimate_normals_dsine(test_image)
        assert "error" not in result

        normal_map = result["normal_map"]
        assert normal_map.min() >= -1.0 - 1e-6
        assert normal_map.max() <= 1.0 + 1e-6

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="DSINE not installed")
    def test_dsine_metadata_fields(self, test_image):
        """Result contains expected metadata keys."""
        result = estimate_normals_dsine(test_image)
        assert "error" not in result

        assert result["model"] == "dsine"
        assert result["device"] in ("cuda", "mps", "cpu")
        assert isinstance(result["time_seconds"], float)
        assert result["time_seconds"] > 0
        assert isinstance(result["height"], int)
        assert isinstance(result["width"], int)
        assert result["height"] > 0
        assert result["width"] > 0

    @pytest.mark.skipif(not DSINE_AVAILABLE, reason="DSINE not installed")
    def test_dispatcher_auto_uses_dsine(self, test_image):
        """estimate_normals(model='auto') routes to DSINE when available."""
        result = estimate_normals(test_image, model="auto")
        assert "error" not in result
        assert result["model"] == "dsine"
