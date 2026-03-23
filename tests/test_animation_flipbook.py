"""Tests for the animation flipbook tool.

Verifies artboard creation per pose, spacing calculations, and
flipbook info reporting.
All tests are pure Python -- no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.animation_flipbook import (
    create_flipbook,
    flipbook_info,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_three_poses_create_three_artboards():
    """3 poses should produce 3 artboards with correct indices."""
    rig = {"character_name": "flipbook_test", "joints": {}}
    result = create_flipbook(
        rig,
        pose_names=["standing", "walking", "running"],
        spacing=50.0,
        artboard_width=300.0,
        artboard_height=400.0,
    )

    assert result["frame_count"] == 3
    assert len(result["artboards"]) == 3

    # Check indices
    assert result["artboards"][0]["index"] == 0
    assert result["artboards"][1]["index"] == 1
    assert result["artboards"][2]["index"] == 2

    # Check pose names
    assert result["artboards"][0]["pose_name"] == "standing"
    assert result["artboards"][1]["pose_name"] == "walking"
    assert result["artboards"][2]["pose_name"] == "running"


def test_artboard_spacing_correct():
    """Artboards should be spaced correctly with the given spacing value."""
    rig = {"character_name": "spacing_test", "joints": {}}
    result = create_flipbook(
        rig,
        pose_names=["standing", "sitting"],
        spacing=100.0,
        artboard_width=200.0,
        artboard_height=300.0,
    )

    # First artboard at x=0
    assert result["artboards"][0]["x_offset"] == 0.0
    # Second artboard at x = 200 (width) + 100 (spacing) = 300
    assert result["artboards"][1]["x_offset"] == 300.0

    # Total width = 200 + 100 + 200 = 500
    assert result["total_width"] == 500.0


def test_flipbook_info_returns_correct_count():
    """flipbook_info should return correct frame count after creation."""
    rig = {"character_name": "info_test", "joints": {}}

    # Before creation, no flipbook
    info_before = flipbook_info(rig)
    assert info_before["has_flipbook"] is False
    assert info_before["frame_count"] == 0

    # Create flipbook
    create_flipbook(
        rig,
        pose_names=["standing", "waving", "jumping", "crouching"],
        spacing=50.0,
    )

    # After creation
    info_after = flipbook_info(rig)
    assert info_after["has_flipbook"] is True
    assert info_after["frame_count"] == 4
    assert len(info_after["artboards"]) == 4
