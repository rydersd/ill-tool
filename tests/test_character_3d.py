"""Tests for StdGEN character 3D decomposition tool.

All tests work WITHOUT ML/3D dependencies (torch, trimesh) installed.
Validates graceful fallback, mesh list validation, and status check.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.character.character_3d import (
    ML_AVAILABLE,
    TRIMESH_AVAILABLE,
    VALID_COMPONENTS,
    _ml_status,
    _decompose,
    merge_or_split_meshes,
    Character3DInput,
)


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with component info."""
    status = _ml_status()

    assert "ml_available" in status
    assert "trimesh_available" in status
    assert "tool" in status
    assert "supported_components" in status
    assert "body" in status["supported_components"]
    assert "clothes" in status["supported_components"]
    assert "hair" in status["supported_components"]

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_merge_or_split_meshes: pure Python mesh list validation
# ---------------------------------------------------------------------------


def test_merge_or_split_meshes():
    """merge_or_split_meshes correctly validates and organizes mesh paths.

    Pure Python test — no trimesh needed.
    """
    # Create temp files to simulate mesh outputs
    temp_files = []
    for name in ["body.obj", "clothes.obj", "hair.obj"]:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=f"_{name}", delete=False
        )
        f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        f.close()
        temp_files.append(f.name)

    try:
        # Split mode: validates each mesh exists
        result = merge_or_split_meshes(temp_files, mode="split")
        assert result["mode"] == "split"
        assert result["total_meshes"] == 3
        assert result["valid_meshes"] == 3
        assert result["missing_meshes"] == 0
        assert len(result["meshes"]) == 3

        # Each mesh should have file info
        for mesh in result["meshes"]:
            assert mesh["exists"] is True
            assert mesh["file_size_bytes"] > 0
            assert mesh["format"] == "obj" or "_" in mesh["format"]

        # With a missing file
        result = merge_or_split_meshes(
            temp_files + ["/nonexistent/missing.obj"], mode="split"
        )
        assert result["valid_meshes"] == 3
        assert result["missing_meshes"] == 1

        # Merge mode with all files present
        result = merge_or_split_meshes(temp_files, mode="merge")
        assert result["mode"] == "merge"
        # merge_ready depends on trimesh availability
        if not TRIMESH_AVAILABLE:
            assert result["merge_ready"] is False
            assert "trimesh" in result.get("warning", "").lower()

        # Empty list
        result = merge_or_split_meshes([], mode="split")
        assert "error" in result

        # Invalid mode
        result = merge_or_split_meshes(temp_files, mode="invalid")
        assert "error" in result

    finally:
        for path in temp_files:
            os.unlink(path)


# ---------------------------------------------------------------------------
# test_graceful_fallback: decompose without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_decompose without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.character.character_3d.ML_AVAILABLE", False):
        result = _decompose("/tmp/test.png", None, ["body", "clothes", "hair"])

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
