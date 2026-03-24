"""Tests for TripoSR quick 3D preview tool.

All tests work WITHOUT ML/3D dependencies (torch, trimesh) installed.
Validates graceful fallback, mesh validation, and status check.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.reconstruct_3d_quick import (
    ML_AVAILABLE,
    TRIMESH_AVAILABLE,
    _ml_status,
    _reconstruct,
    validate_mesh_output,
    Reconstruct3DQuickInput,
)


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with format support info."""
    status = _ml_status()

    assert "ml_available" in status
    assert "trimesh_available" in status
    assert "tool" in status
    assert "supported_formats" in status
    assert "obj" in status["supported_formats"]
    assert "glb" in status["supported_formats"]

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_validate_mesh_output: pure Python validation of mesh files
# ---------------------------------------------------------------------------


def test_validate_mesh_output():
    """validate_mesh_output correctly validates OBJ mesh files.

    Pure Python test — no trimesh needed.
    """
    # Create a valid OBJ file with known vertices and faces
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".obj", delete=False
    ) as f:
        f.write("# Test OBJ\n")
        f.write("v 0.0 0.0 0.0\n")
        f.write("v 1.0 0.0 0.0\n")
        f.write("v 0.0 1.0 0.0\n")
        f.write("f 1 2 3\n")
        obj_path = f.name

    try:
        result = validate_mesh_output(obj_path)
        assert result["valid"] is True
        assert result["vertex_count"] == 3
        assert result["face_count"] == 1
        assert result["format"] == "obj"
        assert result["file_size_bytes"] > 0
    finally:
        os.unlink(obj_path)

    # Nonexistent file
    result = validate_mesh_output("/nonexistent/mesh.obj")
    assert result["valid"] is False
    assert "not found" in result["error"].lower()

    # Empty path
    result = validate_mesh_output("")
    assert result["valid"] is False

    # None path
    result = validate_mesh_output(None)
    assert result["valid"] is False

    # Empty OBJ (no vertices)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".obj", delete=False
    ) as f:
        f.write("# Empty OBJ\n")
        empty_path = f.name

    try:
        result = validate_mesh_output(empty_path)
        assert result["valid"] is False
        assert "no vertices" in result["error"].lower()
    finally:
        os.unlink(empty_path)


# ---------------------------------------------------------------------------
# test_graceful_fallback: reconstruct without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_reconstruct without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.reconstruct_3d_quick.ML_AVAILABLE", False):
        result = _reconstruct("/tmp/test.png", "obj", None)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
