"""Tests for InstantMesh quality 3D reconstruction tool.

All tests work WITHOUT ML/3D dependencies (torch, trimesh) installed.
Validates graceful fallback, quality scoring, and status check.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.reconstruct_3d_quality import (
    ML_AVAILABLE,
    TRIMESH_AVAILABLE,
    _ml_status,
    _reconstruct,
    estimate_quality_score,
    Reconstruct3DQualityInput,
)


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with pipeline info."""
    status = _ml_status()

    assert "ml_available" in status
    assert "trimesh_available" in status
    assert "tool" in status
    assert "pipeline" in status
    assert "multi-view" in status["pipeline"]
    assert "supported_formats" in status

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_estimate_quality_score: pure Python quality estimation
# ---------------------------------------------------------------------------


def test_estimate_quality_score():
    """estimate_quality_score correctly categorizes mesh quality by vertex count.

    Pure Python test — no trimesh needed.
    """
    # Create OBJ with different vertex counts to test quality tiers

    # "preview" quality: < 1000 vertices
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".obj", delete=False
    ) as f:
        for i in range(100):
            f.write(f"v {i * 0.1} {i * 0.2} {i * 0.3}\n")
        for i in range(50):
            f.write(f"f {i + 1} {(i + 1) % 100 + 1} {(i + 2) % 100 + 1}\n")
        preview_path = f.name

    try:
        result = estimate_quality_score(preview_path)
        assert result["quality"] == "preview"
        assert result["vertex_count"] == 100
        assert result["face_count"] == 50
        assert result["vertices_per_face"] == 2.0
    finally:
        os.unlink(preview_path)

    # Nonexistent file
    result = estimate_quality_score("/nonexistent/mesh.obj")
    assert result["quality"] == "unknown"
    assert "error" in result

    # Empty path
    result = estimate_quality_score("")
    assert result["quality"] == "unknown"

    # Wrong format — create a real file so the format check is reached
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".glb", delete=False
    ) as f:
        f.write(b"\x00\x00\x00\x00")  # Not valid glTF
        glb_path = f.name

    try:
        result = estimate_quality_score(glb_path)
        assert result["quality"] == "unknown"
        assert "only supports OBJ" in result["error"]
    finally:
        os.unlink(glb_path)


# ---------------------------------------------------------------------------
# test_graceful_fallback: reconstruct without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_reconstruct without ML deps returns error with install instructions."""
    with patch(
        "adobe_mcp.apps.illustrator.reconstruct_3d_quality.ML_AVAILABLE", False
    ):
        result = _reconstruct("/tmp/test.png", 6, "obj", None)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
