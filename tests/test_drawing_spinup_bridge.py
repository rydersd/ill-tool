"""Tests for the DrawingSpinUp bridge tool.

Verifies input validation, output mapping with mock data, and status —
all pure Python, no Adobe or ML service required.
"""

import os

import pytest

from adobe_mcp.apps.illustrator.pipeline.drawing_spinup_bridge import (
    validate_drawing_input,
    map_spinup_output,
    SUPPORTED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
)


# ---------------------------------------------------------------------------
# test_validate_drawing_input: image validation
# ---------------------------------------------------------------------------


class TestValidateDrawingInput:
    """Input validation for image files."""

    def test_valid_png(self, tmp_path):
        """A valid PNG file passes validation with correct metadata."""
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)

        result = validate_drawing_input(str(img))

        assert result["valid"] is True
        assert result["extension"] == ".png"
        assert result["file_size"] > 0
        assert result["image_path"] == str(img)

    def test_missing_file(self):
        """Non-existent file returns valid=False with error message."""
        result = validate_drawing_input("/nonexistent/drawing.png")

        assert result["valid"] is False
        assert "not found" in result["error"].lower() or "File not found" in result["error"]

    def test_empty_path(self):
        """Empty path string returns valid=False."""
        result = validate_drawing_input("")
        assert result["valid"] is False
        assert "empty" in result["error"].lower()

    def test_directory_path(self, tmp_path):
        """A directory path (not a file) returns valid=False."""
        result = validate_drawing_input(str(tmp_path))
        assert result["valid"] is False
        assert "directory" in result["error"].lower()

    def test_unsupported_extension(self, tmp_path):
        """A file with an unsupported extension returns valid=False."""
        txt_file = tmp_path / "drawing.txt"
        txt_file.write_text("not an image")

        result = validate_drawing_input(str(txt_file))
        assert result["valid"] is False
        assert "unsupported" in result["error"].lower() or "Unsupported" in result["error"]

    def test_empty_file(self, tmp_path):
        """A zero-byte file returns valid=False."""
        empty = tmp_path / "empty.png"
        empty.write_bytes(b"")

        result = validate_drawing_input(str(empty))
        assert result["valid"] is False
        assert "empty" in result["error"].lower()

    def test_supported_extensions_all(self, tmp_path):
        """All supported extensions pass the extension check."""
        for ext in SUPPORTED_EXTENSIONS:
            f = tmp_path / f"test{ext}"
            f.write_bytes(b"\x00" * 50)
            result = validate_drawing_input(str(f))
            assert result["valid"] is True, f"Extension {ext} should be valid"


# ---------------------------------------------------------------------------
# test_map_spinup_output: output mapping with mock data
# ---------------------------------------------------------------------------


class TestMapSpinupOutput:
    """Map DrawingSpinUp service output to rig/animation schema."""

    def test_full_mapping(self):
        """A complete DrawingSpinUp response maps all fields correctly."""
        mock_response = {
            "joints": [
                {"name": "hip", "parent": None, "position": [0, 1, 0]},
                {"name": "knee", "parent": "hip", "position": [0, 0.5, 0]},
                {"name": "ankle", "parent": "knee", "position": [0, 0, 0]},
            ],
            "animations": [
                {
                    "name": "walk",
                    "frames": [{"t": 0}, {"t": 1}, {"t": 2}],
                    "duration": 1.0,
                },
            ],
            "mesh": {
                "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "faces": [[0, 1, 2]],
                "uvs": [[0, 0], [1, 0], [0, 1]],
            },
            "texture": {
                "width": 1024,
                "height": 1024,
                "format": "png",
            },
        }

        result = map_spinup_output(mock_response)

        assert result["source"] == "drawing_spinup"
        assert result["joint_count"] == 3
        assert result["pose_count"] == 1

        # Verify joints
        assert result["joints"][0]["name"] == "hip"
        assert result["joints"][0]["parent"] is None
        assert result["joints"][1]["parent"] == "hip"

        # Verify hierarchy
        assert "hip" in result["hierarchy"]["root"]
        assert "knee" in result["hierarchy"]["hip"]

        # Verify poses (mapped from animations)
        assert result["poses"][0]["name"] == "walk"
        assert result["poses"][0]["frame_count"] == 3
        assert result["poses"][0]["duration"] == 1.0

        # Verify mesh
        assert result["mesh_3d"]["vertex_count"] == 3
        assert result["mesh_3d"]["face_count"] == 1
        assert result["mesh_3d"]["has_uvs"] is True

        # Verify texture
        assert result["texture"]["width"] == 1024
        assert result["texture"]["format"] == "png"

    def test_empty_response(self):
        """Empty or None response returns an error."""
        result_empty = map_spinup_output({})
        assert "error" in result_empty

        result_none = map_spinup_output(None)
        assert "error" in result_none

    def test_skeleton_alt_format(self):
        """Response with 'skeleton.joints' instead of top-level 'joints' is handled."""
        mock_response = {
            "skeleton": {
                "joints": [
                    {"name": "root", "parent": None, "pos": [0, 0, 0]},
                    {"name": "spine", "parent": "root", "pos": [0, 1, 0]},
                ],
            },
        }

        result = map_spinup_output(mock_response)
        assert result["joint_count"] == 2
        assert result["joints"][0]["name"] == "root"
        assert result["joints"][1]["name"] == "spine"


# ---------------------------------------------------------------------------
# test_status: status action
# ---------------------------------------------------------------------------


def test_status_returns_config():
    """Calling map_spinup_output is tested; status is tested via tool integration.
    Here we verify the pure Python constants are accessible and sensible.
    """
    assert len(SUPPORTED_EXTENSIONS) >= 5
    assert MAX_FILE_SIZE_BYTES > 0
    assert ".png" in SUPPORTED_EXTENSIONS
    assert ".jpg" in SUPPORTED_EXTENSIONS
