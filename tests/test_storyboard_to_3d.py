"""Tests for the storyboard to 3D tool.

Verifies scene conversion, depth estimation, and status —
all pure Python, no 3D engine required.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard_to_3d import (
    panel_to_3d_scene,
    estimate_depth_from_scale,
    CAMERA_PRESETS,
)


# ---------------------------------------------------------------------------
# test_panel_to_3d_scene
# ---------------------------------------------------------------------------


class TestPanelTo3dScene:
    """Convert panel data to 3D scene description."""

    def test_basic_scene(self):
        """A panel with camera and characters produces a valid scene."""
        panel = {
            "camera": "medium",
            "description": "Two characters talking",
        }
        chars = [
            {"name": "Alice", "position_x": 640, "position_y": 540, "scale": 1.0},
            {"name": "Bob", "position_x": 1280, "position_y": 540, "scale": 0.8},
        ]

        scene = panel_to_3d_scene(panel, characters=chars)

        assert "error" not in scene
        assert scene["object_count"] == 2
        assert scene["camera"]["shot_type"] == "medium"
        assert scene["camera"]["focal_length_mm"] == CAMERA_PRESETS["medium"]["focal_length"]

        # Verify objects
        names = [o["name"] for o in scene["objects"]]
        assert "Alice" in names
        assert "Bob" in names

        # Environment
        assert scene["environment"]["ground_plane"] is True
        assert scene["environment"]["description"] == "Two characters talking"

    def test_wide_shot_farther_camera(self):
        """Wide shot places camera farther than close shot."""
        wide_scene = panel_to_3d_scene({"camera": "wide"})
        close_scene = panel_to_3d_scene({"camera": "close"})

        # Camera Z position (distance) should be larger for wide
        wide_z = wide_scene["camera"]["position"][2]
        close_z = close_scene["camera"]["position"][2]
        assert wide_z > close_z

    def test_empty_panel_error(self):
        """Empty or None panel returns an error."""
        result = panel_to_3d_scene(None)
        assert "error" in result

    def test_characters_from_panel_data(self):
        """Characters embedded in panel_data are used when no separate list."""
        panel = {
            "camera": "medium",
            "description": "Group shot",
            "characters": [
                {"name": "CharA", "x": 500, "y": 400, "scale": 1.2},
            ],
        }

        scene = panel_to_3d_scene(panel, characters=None)
        assert scene["object_count"] == 1
        assert scene["objects"][0]["name"] == "CharA"


# ---------------------------------------------------------------------------
# test_estimate_depth_from_scale
# ---------------------------------------------------------------------------


class TestEstimateDepthFromScale:
    """Depth estimation from character scale."""

    def test_larger_scale_closer(self):
        """Larger scale means closer to camera (smaller depth)."""
        close_depth = estimate_depth_from_scale(2.0)
        far_depth = estimate_depth_from_scale(0.5)

        assert close_depth < far_depth

    def test_normal_scale_baseline(self):
        """Scale 1.0 gives the baseline depth of 6.0."""
        depth = estimate_depth_from_scale(1.0)
        assert depth == pytest.approx(6.0, abs=0.1)

    def test_tiny_scale_large_depth(self):
        """Very small scale produces large depth (far away)."""
        depth = estimate_depth_from_scale(0.1)
        assert depth > 50.0

    def test_zero_scale_clamped(self):
        """Zero scale is clamped to avoid division by zero."""
        depth = estimate_depth_from_scale(0.0)
        # Should not raise, and depth should be finite
        assert depth > 0
        assert depth < 100000


# ---------------------------------------------------------------------------
# test_status: camera presets accessible
# ---------------------------------------------------------------------------


def test_camera_presets_complete():
    """Camera presets have all required fields."""
    for name, preset in CAMERA_PRESETS.items():
        assert "distance" in preset, f"Preset '{name}' missing 'distance'"
        assert "focal_length" in preset, f"Preset '{name}' missing 'focal_length'"
        assert "height" in preset, f"Preset '{name}' missing 'height'"
        assert preset["distance"] > 0
        assert preset["focal_length"] > 0
