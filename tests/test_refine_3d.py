"""Tests for PyTorch3D mesh refinement tool.

All tests work WITHOUT ML/3D dependencies (torch, pytorch3d, trimesh) installed.
Validates graceful fallback, IoU computation, convergence detection, and status.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.threed.refine_3d import (
    ML_AVAILABLE,
    TRIMESH_AVAILABLE,
    _ml_status,
    _refine_mesh,
    compute_silhouette_iou,
    convergence_check,
    Refine3DInput,
)


# ---------------------------------------------------------------------------
# test_silhouette_iou: pure Python IoU computation
# ---------------------------------------------------------------------------


def test_silhouette_iou():
    """compute_silhouette_iou correctly computes intersection over union.

    Pure Python test — no ML dependencies needed.
    """
    # Perfect overlap -> IoU = 1.0
    mask_a = [[1, 1, 0], [1, 1, 0], [0, 0, 0]]
    mask_b = [[1, 1, 0], [1, 1, 0], [0, 0, 0]]
    assert compute_silhouette_iou(mask_a, mask_b) == 1.0

    # No overlap -> IoU = 0.0
    mask_a = [[1, 1, 0], [0, 0, 0], [0, 0, 0]]
    mask_b = [[0, 0, 0], [0, 0, 0], [0, 0, 1]]
    assert compute_silhouette_iou(mask_a, mask_b) == 0.0

    # Both empty -> IoU = 0.0
    mask_a = [[0, 0], [0, 0]]
    mask_b = [[0, 0], [0, 0]]
    assert compute_silhouette_iou(mask_a, mask_b) == 0.0

    # Partial overlap: intersection=2, union=4 -> IoU=0.5
    mask_a = [[1, 1, 0], [0, 0, 0]]
    mask_b = [[0, 1, 1], [0, 0, 0]]
    iou = compute_silhouette_iou(mask_a, mask_b)
    assert abs(iou - 1 / 3) < 1e-9  # intersection=1, union=3

    # Error on dimension mismatch
    with pytest.raises(ValueError, match="Height mismatch"):
        compute_silhouette_iou([[1]], [[1], [0]])

    with pytest.raises(ValueError, match="Width mismatch"):
        compute_silhouette_iou([[1, 0]], [[1]])

    with pytest.raises(ValueError, match="non-empty"):
        compute_silhouette_iou([], [])


# ---------------------------------------------------------------------------
# test_convergence_detection: pure Python plateau detection
# ---------------------------------------------------------------------------


def test_convergence_detection():
    """convergence_check correctly detects optimization plateaus.

    Pure Python test — no ML dependencies needed.
    """
    # Rapidly improving -> not converged
    history = [0.1, 0.3, 0.5, 0.7, 0.85, 0.90]
    result = convergence_check(history, threshold=0.01)
    assert result["converged"] is False
    assert result["iterations"] == 6
    assert result["current_iou"] == 0.9

    # Plateaued -> converged
    history = [0.90, 0.901, 0.902, 0.9025, 0.903]
    result = convergence_check(history, threshold=0.01)
    assert result["converged"] is True
    assert "Stop" in result.get("recommendation", "")

    # Too few iterations -> not converged
    result = convergence_check([0.5], threshold=0.01)
    assert result["converged"] is False
    assert "Too few" in result["reason"]

    # Empty history
    result = convergence_check([], threshold=0.01)
    assert result["converged"] is False
    assert result["iterations"] == 0


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with capabilities."""
    status = _ml_status()

    assert "ml_available" in status
    assert "trimesh_available" in status
    assert "tool" in status
    assert "capabilities" in status
    assert isinstance(status["capabilities"], list)

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_input_validation: refine with missing inputs returns error
# ---------------------------------------------------------------------------


def test_input_validation():
    """_refine_mesh with missing inputs returns helpful errors."""
    # No ML -> fallback error
    with patch("adobe_mcp.apps.illustrator.threed.refine_3d.ML_AVAILABLE", False):
        result = _refine_mesh("/tmp/mesh.obj", ["/tmp/target.png"], 100, 0.001, 0.01, None)
    assert "error" in result
    assert "install_hint" in result

    # With ML but missing mesh file
    with patch("adobe_mcp.apps.illustrator.threed.refine_3d.ML_AVAILABLE", True):
        result = _refine_mesh("/nonexistent/mesh.obj", ["/tmp/t.png"], 100, 0.001, 0.01, None)
    assert "error" in result
    assert "not found" in result["error"].lower()

    # With ML and mesh but no target images — create a real mesh file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".obj", delete=False
    ) as f:
        f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        real_mesh = f.name

    try:
        with patch("adobe_mcp.apps.illustrator.threed.refine_3d.ML_AVAILABLE", True):
            result = _refine_mesh(real_mesh, [], 100, 0.001, 0.01, None)
        assert "error" in result
        assert "target" in result["error"].lower()
    finally:
        os.unlink(real_mesh)


# ---------------------------------------------------------------------------
# test_plateau_detection: convergence with different patterns
# ---------------------------------------------------------------------------


def test_plateau_detection():
    """convergence_check handles various convergence patterns correctly."""
    # Oscillating (not converged because range > threshold)
    history = [0.5, 0.55, 0.5, 0.55, 0.5]
    result = convergence_check(history, threshold=0.01)
    assert result["converged"] is False

    # Perfectly flat (converged)
    history = [0.8, 0.8, 0.8, 0.8, 0.8]
    result = convergence_check(history, threshold=0.01)
    assert result["converged"] is True

    # Decreasing (diverging — should not be converged if range is large)
    history = [0.9, 0.85, 0.80, 0.75, 0.70]
    result = convergence_check(history, threshold=0.01)
    assert result["converged"] is False

    # Best IoU tracking
    history = [0.1, 0.5, 0.8, 0.79, 0.78]
    result = convergence_check(history, threshold=0.01)
    assert result["best_iou"] == 0.8
