"""Tests for DiffVG differentiable path optimization tool.

All tests work WITHOUT ML dependencies (torch, diffvg) installed.
Validates graceful fallback, pure Python loss computation, status,
and separate availability reporting for torch vs diffvg.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.ml_vision.diffvg_correct import (
    TORCH_AVAILABLE,
    DIFFVG_AVAILABLE,
    _ml_status,
    _optimize_paths,
    _parse_svg_paths,
    _parse_svg_dimensions,
    _svg_paths_to_contours,
    compute_pixel_loss,
    DiffVGCorrectInput,
)


# ---------------------------------------------------------------------------
# test_pixel_loss_computation: pure Python MSE calculation
# ---------------------------------------------------------------------------


def test_pixel_loss_computation():
    """compute_pixel_loss correctly computes MSE between two images.

    Pure Python test -- no ML dependencies needed.
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
# test_status_reports_torch_and_diffvg_separately
# ---------------------------------------------------------------------------


def test_status_reports_torch_and_diffvg_separately():
    """_ml_status reports TORCH_AVAILABLE and DIFFVG_AVAILABLE as separate keys."""
    status = _ml_status()

    # Must have both keys
    assert "torch_available" in status
    assert "diffvg_available" in status
    assert "tool" in status
    assert "capabilities" in status
    assert isinstance(status["capabilities"], list)
    assert len(status["capabilities"]) > 0

    # Fallback availability is always reported
    assert "fallback_available" in status


def test_status_without_torch():
    """When torch is unavailable, status reports correct hints."""
    with patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.TORCH_AVAILABLE", False), \
         patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.DIFFVG_AVAILABLE", False):
        status = _ml_status()

    assert status["torch_available"] is False
    assert status["diffvg_available"] is False
    assert status["device"] == "unavailable"
    assert "torch_install_hint" in status
    assert "diffvg_install_hint" in status


def test_status_torch_without_diffvg():
    """When torch available but diffvg not, status shows partial availability."""
    with patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.TORCH_AVAILABLE", True), \
         patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.DIFFVG_AVAILABLE", False):
        # Need to mock torch module attributes for the status function
        import types
        mock_torch = types.ModuleType("torch")
        mock_torch.__version__ = "2.0.0"
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        mock_torch.backends = types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: False)
        )
        with patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.torch", mock_torch):
            status = _ml_status()

    assert status["torch_available"] is True
    assert status["diffvg_available"] is False
    assert status["device"] == "cpu"
    assert "diffvg_install_hint" in status
    assert "torch_install_hint" not in status


# ---------------------------------------------------------------------------
# test_graceful_fallback: optimize without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback_no_ml():
    """_optimize_paths without any ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.TORCH_AVAILABLE", False), \
         patch("adobe_mcp.apps.illustrator.ml_vision.diffvg_correct.DIFFVG_AVAILABLE", False):
        # Create a temporary SVG and target file so file-not-found doesn't trigger
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
            f.write('<svg><path d="M 0 0 L 10 10"/></svg>')
            svg_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            target_path = f.name
        try:
            result = _optimize_paths(svg_path, target_path, 100, 0.01)
            assert "error" in result
            assert "install" in result["error"].lower() or "not installed" in result["error"].lower()
            assert "required_packages" in result
        finally:
            os.unlink(svg_path)
            os.unlink(target_path)


def test_optimize_missing_svg():
    """_optimize_paths returns error for missing SVG file."""
    result = _optimize_paths("/nonexistent/file.svg", "/tmp/target.png", 100, 0.01)
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_optimize_missing_target():
    """_optimize_paths returns error for missing target image."""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
        f.write('<svg><path d="M 0 0 L 10 10"/></svg>')
        svg_path = f.name
    try:
        result = _optimize_paths(svg_path, "/nonexistent/target.png", 100, 0.01)
        assert "error" in result
        assert "not found" in result["error"].lower()
    finally:
        os.unlink(svg_path)


# ---------------------------------------------------------------------------
# SVG parsing tests (pure Python, no ML needed)
# ---------------------------------------------------------------------------


def test_parse_svg_paths():
    """_parse_svg_paths extracts path d='' elements from SVG."""
    svg_content = '''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <path d="M 10 10 L 90 10 L 90 90 Z" fill="red" id="square"/>
  <path d="M 50 50 C 60 60 70 70 80 80" stroke="blue" id="curve"/>
  <rect x="0" y="0" width="10" height="10"/>
</svg>'''
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
        f.write(svg_content)
        svg_path = f.name
    try:
        paths = _parse_svg_paths(svg_path)
        assert len(paths) == 2, f"Expected 2 paths, got {len(paths)}"
        assert paths[0]["id"] == "square"
        assert paths[0]["fill"] == "red"
        assert "M 10 10" in paths[0]["d"]
        assert paths[1]["id"] == "curve"
    finally:
        os.unlink(svg_path)


def test_parse_svg_dimensions():
    """_parse_svg_dimensions extracts width/height from viewBox."""
    svg_content = '<svg viewBox="0 0 200 150"></svg>'
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
        f.write(svg_content)
        svg_path = f.name
    try:
        w, h = _parse_svg_dimensions(svg_path)
        assert w == 200
        assert h == 150
    finally:
        os.unlink(svg_path)


def test_svg_paths_to_contours():
    """_svg_paths_to_contours converts parsed SVG path data to numpy arrays."""
    import numpy as np
    path_data = [
        {"id": "test", "d": "M 10 20 L 30 40 L 50 60 Z", "fill": "none", "stroke": "none"},
    ]
    contours = _svg_paths_to_contours(path_data, (100, 100))
    assert len(contours) == 1
    assert contours[0].shape[0] == 3  # M, L, L = 3 points
    assert contours[0].dtype == np.float64
    # Check coordinate values
    np.testing.assert_array_almost_equal(contours[0][0], [10, 20])
    np.testing.assert_array_almost_equal(contours[0][1], [30, 40])
    np.testing.assert_array_almost_equal(contours[0][2], [50, 60])


# ---------------------------------------------------------------------------
# DiffVG-specific tests (skip when diffvg not installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not DIFFVG_AVAILABLE,
    reason="DiffVG not installed (requires source compilation)",
)
def test_diffvg_optimize_roundtrip():
    """DiffVG optimization preserves path count and reduces loss.

    Only runs when diffvg is actually installed.
    """
    from adobe_mcp.apps.illustrator.ml_vision.diffvg_correct import optimize_paths_diffvg

    # Create a simple SVG with one path
    svg_content = '''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <path d="M 20 20 L 44 20 L 44 44 L 20 44 Z" fill="black"/>
</svg>'''
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
        f.write(svg_content)
        svg_path = f.name

    # Create a simple target image (white square on black background)
    import numpy as np
    import cv2
    target = np.zeros((64, 64, 3), dtype=np.uint8)
    cv2.rectangle(target, (22, 22), (42, 42), (255, 255, 255), -1)
    target_path = tempfile.mktemp(suffix=".png")
    cv2.imwrite(target_path, target)

    try:
        result = optimize_paths_diffvg(svg_path, target_path, iterations=10, lr=0.1)
        assert "error" not in result
        assert result["path_count"] >= 1
        assert result["iterations_run"] > 0
    finally:
        os.unlink(svg_path)
        if os.path.exists(target_path):
            os.unlink(target_path)
        # Clean up optimized output if created
        optimized_path = svg_path.replace(".svg", "_optimized.svg")
        if os.path.exists(optimized_path):
            os.unlink(optimized_path)


@pytest.mark.skipif(
    not DIFFVG_AVAILABLE,
    reason="DiffVG not installed (requires source compilation)",
)
def test_diffvg_loss_decreases():
    """DiffVG optimization reduces loss over iterations.

    Only runs when diffvg is actually installed.
    """
    from adobe_mcp.apps.illustrator.ml_vision.diffvg_correct import optimize_paths_diffvg

    svg_content = '''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <path d="M 15 15 L 50 15 L 50 50 L 15 50 Z" fill="white"/>
</svg>'''
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
        f.write(svg_content)
        svg_path = f.name

    import numpy as np
    import cv2
    target = np.zeros((64, 64, 3), dtype=np.uint8)
    cv2.rectangle(target, (20, 20), (45, 45), (255, 255, 255), -1)
    target_path = tempfile.mktemp(suffix=".png")
    cv2.imwrite(target_path, target)

    try:
        result = optimize_paths_diffvg(svg_path, target_path, iterations=20, lr=0.05)
        assert "error" not in result
        assert result["final_loss"] < result["initial_loss"], (
            f"Loss should decrease: {result['initial_loss']:.6f} -> "
            f"{result['final_loss']:.6f}"
        )
    finally:
        os.unlink(svg_path)
        if os.path.exists(target_path):
            os.unlink(target_path)
        optimized_path = svg_path.replace(".svg", "_optimized.svg")
        if os.path.exists(optimized_path):
            os.unlink(optimized_path)


# ---------------------------------------------------------------------------
# Input model validation
# ---------------------------------------------------------------------------


def test_input_model_defaults():
    """DiffVGCorrectInput has correct default values."""
    inp = DiffVGCorrectInput()
    assert inp.action == "status"
    assert inp.svg_path is None
    assert inp.target_image_path is None
    assert inp.iterations == 100
    assert inp.learning_rate == 0.01


def test_input_model_layer_fields():
    """DiffVGCorrectInput supports layer_name and reference_path fields."""
    inp = DiffVGCorrectInput(
        action="optimize",
        layer_name="Drawing",
        reference_path="/tmp/ref.png",
    )
    assert inp.layer_name == "Drawing"
    assert inp.reference_path == "/tmp/ref.png"
