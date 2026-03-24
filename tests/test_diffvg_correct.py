"""Tests for DiffVG differentiable path optimization tool.

All tests work WITHOUT ML dependencies (torch, diffvg) installed.
Validates graceful fallback, pure Python loss computation, and status.
"""

import json
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.diffvg_correct import (
    ML_AVAILABLE,
    _ml_status,
    _optimize_paths,
    compute_pixel_loss,
    DiffVGCorrectInput,
)


# ---------------------------------------------------------------------------
# test_pixel_loss_computation: pure Python MSE calculation
# ---------------------------------------------------------------------------


def test_pixel_loss_computation():
    """compute_pixel_loss correctly computes MSE between two images.

    Pure Python test — no ML dependencies needed.
    """
    # Identical images -> loss = 0
    rendered = [[0.5, 0.5], [0.5, 0.5]]
    target = [[0.5, 0.5], [0.5, 0.5]]
    assert compute_pixel_loss(rendered, target) == 0.0

    # Known difference: all pixels differ by 0.1
    rendered = [[0.0, 0.0], [0.0, 0.0]]
    target = [[0.1, 0.1], [0.1, 0.1]]
    loss = compute_pixel_loss(rendered, target)
    assert abs(loss - 0.01) < 1e-9  # MSE of 0.1 diff = 0.01

    # Full white vs full black
    rendered = [[1.0, 1.0], [1.0, 1.0]]
    target = [[0.0, 0.0], [0.0, 0.0]]
    loss = compute_pixel_loss(rendered, target)
    assert abs(loss - 1.0) < 1e-9  # MSE = 1.0

    # Error on shape mismatch
    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_pixel_loss([[0.0]], [[0.0], [0.0]])

    # Error on empty inputs
    with pytest.raises(ValueError, match="non-empty"):
        compute_pixel_loss([], [])


# ---------------------------------------------------------------------------
# test_status_check: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status_check():
    """_ml_status returns correct structure with capabilities list."""
    status = _ml_status()

    assert "ml_available" in status
    assert "tool" in status
    assert "capabilities" in status
    assert isinstance(status["capabilities"], list)
    assert len(status["capabilities"]) > 0

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_graceful_fallback: optimize without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_optimize_paths without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.diffvg_correct.ML_AVAILABLE", False):
        result = _optimize_paths("/tmp/test.svg", "/tmp/target.png", 100, 0.01)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
