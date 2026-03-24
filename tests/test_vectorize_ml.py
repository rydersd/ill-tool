"""Tests for ML-powered vectorization tool.

All tests work WITHOUT ML dependencies (torch, transformers) installed.
Validates graceful fallback, error messages, and input validation.
"""

import json
import sys
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.vectorize_ml import (
    ML_AVAILABLE,
    _ml_status,
    _check_model,
    _vectorize_image,
    VectorizeMLInput,
)


# ---------------------------------------------------------------------------
# test_status_no_ml: when torch not installed → ML_AVAILABLE = False
# ---------------------------------------------------------------------------


def test_status_no_ml():
    """_ml_status returns correct structure regardless of ML availability.

    When ML deps are missing, it should report ml_available=False and
    include an install_hint.  When available, it should report the device.
    """
    status = _ml_status()

    # Always has these keys
    assert "ml_available" in status
    assert "torch_installed" in status
    assert "transformers_installed" in status
    assert "device" in status

    if not ML_AVAILABLE:
        # Without ML: helpful guidance
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert "uv pip install" in status["install_hint"]
        assert status["device"] == "unavailable"
    else:
        # With ML: device info
        assert status["ml_available"] is True
        assert status["device"] in ("cuda", "mps", "cpu")
        assert "torch_version" in status


# ---------------------------------------------------------------------------
# test_graceful_fallback: vectorize without ML → helpful error message
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """Calling _vectorize_image without ML deps returns a helpful error, not an exception.

    We force ML_AVAILABLE=False to test the fallback path even if torch
    happens to be installed in the test environment.
    """
    with patch("adobe_mcp.apps.illustrator.vectorize_ml.ML_AVAILABLE", False):
        result = _vectorize_image("/tmp/test.png", "starvector/starvector-1b-im2svg", 4096)

    assert "error" in result
    assert "not installed" in result["error"].lower() or "ml" in result["error"].lower()
    assert "install_hint" in result
    assert "uv pip install" in result["install_hint"]
    assert "required_packages" in result
    assert "torch" in result["required_packages"]
    assert "transformers" in result["required_packages"]


# ---------------------------------------------------------------------------
# test_input_validation: bad image path → error
# ---------------------------------------------------------------------------


def test_input_validation_missing_image():
    """_vectorize_image with a nonexistent image path returns an error dict."""
    # Only test when ML is available — otherwise the ML_AVAILABLE check fires first
    if not ML_AVAILABLE:
        # Force ML_AVAILABLE=True to test the file-check path
        with patch("adobe_mcp.apps.illustrator.vectorize_ml.ML_AVAILABLE", True):
            result = _vectorize_image(
                "/nonexistent/path/fake.png",
                "starvector/starvector-1b-im2svg",
                4096,
            )
    else:
        result = _vectorize_image(
            "/nonexistent/path/fake.png",
            "starvector/starvector-1b-im2svg",
            4096,
        )

    assert "error" in result
    assert "not found" in result["error"].lower() or "image" in result["error"].lower()


def test_input_validation_none_image():
    """_vectorize_image with None image_path returns an error."""
    if not ML_AVAILABLE:
        with patch("adobe_mcp.apps.illustrator.vectorize_ml.ML_AVAILABLE", True):
            result = _vectorize_image(None, "starvector/starvector-1b-im2svg", 4096)
    else:
        result = _vectorize_image(None, "starvector/starvector-1b-im2svg", 4096)

    assert "error" in result


def test_check_model_without_ml():
    """_check_model without ML returns helpful error."""
    with patch("adobe_mcp.apps.illustrator.vectorize_ml.ML_AVAILABLE", False):
        result = _check_model("starvector/starvector-1b-im2svg")

    assert result["available"] is False
    assert "error" in result
    assert "install_hint" in result


def test_input_model_defaults():
    """VectorizeMLInput has correct defaults."""
    model = VectorizeMLInput()
    assert model.action == "vectorize"
    assert model.model_id == "starvector/starvector-1b-im2svg"
    assert model.max_tokens == 4096
    assert model.place_in_ai is False
    assert model.layer_name == "ML_Trace"
