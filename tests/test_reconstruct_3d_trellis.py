"""Tests for TRELLIS.2 single-image 3D reconstruction tool.

All tests work WITHOUT ML/3D dependencies (torch, trimesh, trellis)
installed.  Validates pure-Python helpers, graceful fallback, status
structure, and input validation.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis import (
    ML_AVAILABLE,
    TRELLIS_AVAILABLE,
    ReconstructTrellisInput,
    _ml_status,
    _reconstruct,
    estimate_mesh_complexity,
    validate_trellis_output,
)


# ---------------------------------------------------------------------------
# Synthetic OBJ fixtures
# ---------------------------------------------------------------------------

# Minimal cube: 8 vertices, 6 quad faces
CUBE_OBJ = """\
# Synthetic cube for testing
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
v 1 1 1
v 0 1 1
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""


def _write_obj(content: str) -> str:
    """Write OBJ content to a temporary file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".obj", delete=False
    )
    f.write(content)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# 1. Status action returns correct structure
# ---------------------------------------------------------------------------


def test_status_returns_correct_structure():
    """_ml_status reports ML_AVAILABLE, TRELLIS_AVAILABLE, device, and formats."""
    status = _ml_status()

    assert "ml_available" in status
    assert "trellis_available" in status
    assert "tool" in status
    assert "supported_formats" in status
    assert "obj" in status["supported_formats"]
    assert "glb" in status["supported_formats"]
    assert "supported_resolutions" in status
    assert 512 in status["supported_resolutions"]

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")
        assert "model_loaded" in status


# ---------------------------------------------------------------------------
# 2. validate_trellis_output on valid OBJ file
# ---------------------------------------------------------------------------


def test_validate_valid_obj():
    """validate_trellis_output correctly parses a well-formed OBJ cube."""
    path = _write_obj(CUBE_OBJ)
    try:
        result = validate_trellis_output(path)
        assert result["valid"] is True
        assert result["format"] == "obj"
        assert result["vertex_count"] == 8
        assert result["face_count"] == 6
        assert result["file_size_bytes"] > 0
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 3. validate_trellis_output on invalid file (wrong format content)
# ---------------------------------------------------------------------------


def test_validate_invalid_obj_content():
    """validate_trellis_output rejects an OBJ with no vertices."""
    path = _write_obj("# empty obj, no vertex lines\n")
    try:
        result = validate_trellis_output(path)
        assert result["valid"] is False
        assert "no vertices" in result["error"].lower()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 4. validate_trellis_output on nonexistent file
# ---------------------------------------------------------------------------


def test_validate_nonexistent_file():
    """validate_trellis_output returns error for missing file."""
    result = validate_trellis_output("/nonexistent/path/mesh.obj")
    assert result["valid"] is False
    assert "not found" in result["error"].lower()


def test_validate_none_path():
    """validate_trellis_output handles None/empty path."""
    assert validate_trellis_output(None)["valid"] is False
    assert validate_trellis_output("")["valid"] is False


# ---------------------------------------------------------------------------
# 5. estimate_mesh_complexity quality tier thresholds
# ---------------------------------------------------------------------------


def test_estimate_complexity_quality_tiers():
    """estimate_mesh_complexity assigns correct quality tier by vertex count.

    Thresholds: high >= 50k, medium >= 10k, low >= 1k, preview < 1k.
    """
    # preview: 8 vertices (cube)
    path = _write_obj(CUBE_OBJ)
    try:
        result = estimate_mesh_complexity(path)
        assert result["quality_tier"] == "preview"
        assert result["vertex_count"] == 8
        assert result["face_count"] == 6
    finally:
        os.unlink(path)

    # low: 1000 vertices
    lines = ["v {} 0 0\n".format(i) for i in range(1000)]
    lines.append("f 1 2 3\n")
    path = _write_obj("".join(lines))
    try:
        result = estimate_mesh_complexity(path)
        assert result["quality_tier"] == "low"
    finally:
        os.unlink(path)

    # medium: 10000 vertices
    lines = ["v {} 0 0\n".format(i) for i in range(10_000)]
    lines.append("f 1 2 3\n")
    path = _write_obj("".join(lines))
    try:
        result = estimate_mesh_complexity(path)
        assert result["quality_tier"] == "medium"
    finally:
        os.unlink(path)

    # high: 50000 vertices
    lines = ["v {} 0 0\n".format(i) for i in range(50_000)]
    lines.append("f 1 2 3\n")
    path = _write_obj("".join(lines))
    try:
        result = estimate_mesh_complexity(path)
        assert result["quality_tier"] == "high"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 6. estimate_mesh_complexity bounding box computation
# ---------------------------------------------------------------------------


def test_estimate_complexity_bounding_box():
    """estimate_mesh_complexity computes correct bounding box from OBJ vertices."""
    path = _write_obj(CUBE_OBJ)
    try:
        result = estimate_mesh_complexity(path)
        bb = result["bounding_box"]
        assert bb["min"] == [0.0, 0.0, 0.0]
        assert bb["max"] == [1.0, 1.0, 1.0]
        assert bb["size"] == [1.0, 1.0, 1.0]
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 7. Input validation rejects missing image_path for reconstruct action
# ---------------------------------------------------------------------------


def test_reconstruct_rejects_missing_image_path():
    """_reconstruct returns error when image_path is missing or doesn't exist."""
    # None path
    result = _reconstruct(None, None, 512, "obj")
    assert "error" in result

    # Empty path
    result = _reconstruct("", None, 512, "obj")
    assert "error" in result

    # Nonexistent file (when ML is available, it should catch this;
    # when ML is not available, it returns ML-not-installed error)
    result = _reconstruct("/nonexistent/image.png", None, 512, "obj")
    assert "error" in result


# ---------------------------------------------------------------------------
# 8. Graceful fallback when TRELLIS not installed
# ---------------------------------------------------------------------------


def test_graceful_fallback_ml_unavailable():
    """_reconstruct without ML deps returns error with install hint."""
    with patch(
        "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.ML_AVAILABLE", False
    ):
        result = _reconstruct("/tmp/test.png", None, 512, "obj")

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result


def test_graceful_fallback_trellis_unavailable():
    """_reconstruct with ML but without TRELLIS returns install instructions."""
    with patch(
        "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.ML_AVAILABLE", True
    ), patch(
        "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.TRELLIS_AVAILABLE", False
    ):
        result = _reconstruct("/tmp/test.png", None, 512, "obj")

    assert "error" in result
    assert "trellis" in result["error"].lower()
    assert "github.com/microsoft/TRELLIS" in result["error"]


def test_status_reports_trellis_install_hint_when_ml_only():
    """Status shows TRELLIS install hint when torch is available but trellis isn't."""
    with patch(
        "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.ML_AVAILABLE", True
    ), patch(
        "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.TRELLIS_AVAILABLE", False
    ):
        # Need to also mock torch for the version string and device check
        import types

        mock_torch = types.SimpleNamespace(
            __version__="2.3.0",
            cuda=types.SimpleNamespace(is_available=lambda: False),
            backends=types.SimpleNamespace(
                mps=types.SimpleNamespace(is_available=lambda: False)
            ),
        )
        with patch(
            "adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis.torch", mock_torch
        ):
            status = _ml_status()

    assert status["ml_available"] is True
    assert status["trellis_available"] is False
    assert "trellis_install_hint" in status
    assert "github.com/microsoft/TRELLIS" in status["trellis_install_hint"]


# ---------------------------------------------------------------------------
# GLB validation (synthetic magic bytes)
# ---------------------------------------------------------------------------


def test_validate_valid_glb():
    """validate_trellis_output accepts GLB with correct glTF magic bytes."""
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        # glTF magic: 0x46546C67 = b"glTF"
        f.write(b"glTF\x02\x00\x00\x00" + b"\x00" * 100)
        glb_path = f.name

    try:
        result = validate_trellis_output(glb_path)
        assert result["valid"] is True
        assert result["format"] == "glb"
        assert result["has_gltf_magic"] is True
    finally:
        os.unlink(glb_path)


def test_validate_invalid_glb():
    """validate_trellis_output rejects GLB without glTF magic bytes."""
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        f.write(b"NOTG\x00\x00\x00\x00" + b"\x00" * 50)
        glb_path = f.name

    try:
        result = validate_trellis_output(glb_path)
        assert result["valid"] is False
        assert "magic" in result["error"].lower()
    finally:
        os.unlink(glb_path)
