"""Tests for the panel composer tool.

Verifies camera framing for different shot types, pose application,
and composition assembly.
All tests are pure Python -- no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard.panel_composer import (
    compose_panel,
    camera_frame,
    _estimate_character_bounds,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_wide_frame_includes_full_bounds():
    """Wide camera should include the full character bounds plus margin."""
    bounds = [100.0, 50.0, 200.0, 400.0]
    result = camera_frame(bounds, "wide")

    assert result["camera_type"] == "wide"
    rect = result["camera_rect"]
    # Wide shot: full height + 20% margin
    # Camera rect should be wider than character bounds
    assert rect[2] > bounds[2]  # width > char width
    assert rect[3] > bounds[3]  # height > char height
    # Should include full character (rect origin before char origin)
    assert rect[0] < bounds[0]
    assert rect[1] < bounds[1]


def test_close_up_smaller_than_wide():
    """Close-up camera should produce a smaller rect than wide."""
    bounds = [100.0, 50.0, 200.0, 400.0]
    wide = camera_frame(bounds, "wide")
    close = camera_frame(bounds, "close_up")

    # Close-up should be smaller in both dimensions
    assert close["camera_rect"][2] < wide["camera_rect"][2]
    assert close["camera_rect"][3] < wide["camera_rect"][3]


def test_medium_between_wide_and_close():
    """Medium shot should be between wide and close-up in size."""
    bounds = [50.0, 20.0, 300.0, 500.0]
    wide = camera_frame(bounds, "wide")
    medium = camera_frame(bounds, "medium")
    close = camera_frame(bounds, "close_up")

    assert close["camera_rect"][3] < medium["camera_rect"][3] < wide["camera_rect"][3]


def test_compose_panel_with_pose(tmp_rig_dir):
    """compose_panel should apply pose and return composition spec."""
    result = compose_panel(
        character_name="test_comp_char",
        pose_name="waving",
        camera_type="medium",
        panel_number=3,
        description="Character waves hello",
    )

    assert result["panel_number"] == 3
    assert result["camera_type"] == "medium"
    assert result["description"] == "Character waves hello"
    assert result["pose_applied"] is not None
    assert result["pose_applied"]["pose"] == "waving"
    assert len(result["camera_rect"]) == 4
    assert len(result["character_bounds"]) == 4


def test_compose_panel_stores_description(tmp_rig_dir):
    """Description text should be preserved in the composition spec."""
    result = compose_panel(
        character_name="test_desc_char",
        camera_type="wide",
        panel_number=1,
        description="Wide establishing shot of the kitchen",
    )

    assert result["description"] == "Wide establishing shot of the kitchen"
    assert result["panel_number"] == 1
