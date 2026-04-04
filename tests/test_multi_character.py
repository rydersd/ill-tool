"""Tests for multi-character placement in storyboard panels.

Tests the data layer for placing, reposing, removing, and listing
character placements.  All tests use tmp_rig_dir to isolate storage.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.character.multi_character import (
    _ensure_placements,
    _find_placement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rig_with_placements(placements: list[dict]) -> dict:
    """Create and persist a rig with pre-built character placements."""
    rig = _load_rig("storyboard")
    rig = _ensure_placements(rig)
    rig["character_placements"] = placements
    _save_rig("storyboard", rig)
    return rig


# ---------------------------------------------------------------------------
# _ensure_placements
# ---------------------------------------------------------------------------


def test_ensure_placements_creates_empty_list():
    """_ensure_placements adds an empty list if missing."""
    rig = {"character_name": "storyboard"}
    result = _ensure_placements(rig)
    assert "character_placements" in result
    assert result["character_placements"] == []


# ---------------------------------------------------------------------------
# Place character
# ---------------------------------------------------------------------------


def test_place_character(tmp_rig_dir):
    """Placing a character stores position, pose, and scale."""
    _make_rig_with_placements([])

    rig = _load_rig("storyboard")
    rig = _ensure_placements(rig)

    entry = {
        "panel": 1,
        "character": "gir",
        "pose": "idle",
        "x": 200.0,
        "y": -300.0,
        "scale": 100,
    }
    rig["character_placements"].append(entry)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["character_placements"]) == 1
    p = reloaded["character_placements"][0]
    assert p["character"] == "gir"
    assert p["panel"] == 1
    assert p["x"] == 200.0
    assert p["y"] == -300.0


# ---------------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------------


def test_duplicate_prevention(tmp_rig_dir):
    """Same character cannot be placed twice in the same panel."""
    _make_rig_with_placements([
        {"panel": 1, "character": "gir", "pose": "idle", "x": 0, "y": 0, "scale": 100},
    ])

    rig = _load_rig("storyboard")
    placements = rig["character_placements"]

    # Attempt to find existing placement — should exist
    existing, _ = _find_placement(placements, 1, "gir")
    assert existing is not None

    # Different character in same panel should be fine
    existing2, _ = _find_placement(placements, 1, "zim")
    assert existing2 is None


# ---------------------------------------------------------------------------
# Repose character
# ---------------------------------------------------------------------------


def test_repose_character(tmp_rig_dir):
    """Reposing updates the pose field while preserving other data."""
    _make_rig_with_placements([
        {"panel": 1, "character": "gir", "pose": "idle", "x": 100, "y": -200, "scale": 100},
    ])

    rig = _load_rig("storyboard")
    placements = rig["character_placements"]
    entry, idx = _find_placement(placements, 1, "gir")
    assert entry is not None

    entry["pose"] = "menacing"
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert reloaded["character_placements"][0]["pose"] == "menacing"
    assert reloaded["character_placements"][0]["x"] == 100  # unchanged


# ---------------------------------------------------------------------------
# Remove character
# ---------------------------------------------------------------------------


def test_remove_character(tmp_rig_dir):
    """Removing a character deletes its placement entry."""
    _make_rig_with_placements([
        {"panel": 1, "character": "gir", "pose": "idle", "x": 0, "y": 0, "scale": 100},
        {"panel": 1, "character": "zim", "pose": "angry", "x": 400, "y": -100, "scale": 80},
    ])

    rig = _load_rig("storyboard")
    placements = rig["character_placements"]
    _, idx = _find_placement(placements, 1, "gir")
    assert idx is not None

    placements.pop(idx)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["character_placements"]) == 1
    assert reloaded["character_placements"][0]["character"] == "zim"


# ---------------------------------------------------------------------------
# List characters in panel
# ---------------------------------------------------------------------------


def test_list_characters_by_panel(tmp_rig_dir):
    """Listing characters for a panel returns only that panel's placements."""
    _make_rig_with_placements([
        {"panel": 1, "character": "gir", "pose": "idle", "x": 0, "y": 0, "scale": 100},
        {"panel": 1, "character": "zim", "pose": "angry", "x": 400, "y": 0, "scale": 80},
        {"panel": 2, "character": "dib", "pose": "scared", "x": 200, "y": -100, "scale": 100},
    ])

    rig = _load_rig("storyboard")
    placements = rig["character_placements"]

    # Filter panel 1
    panel_1 = [p for p in placements if p.get("panel") == 1]
    assert len(panel_1) == 2
    names = {p["character"] for p in panel_1}
    assert names == {"gir", "zim"}

    # Filter panel 2
    panel_2 = [p for p in placements if p.get("panel") == 2]
    assert len(panel_2) == 1
    assert panel_2[0]["character"] == "dib"
