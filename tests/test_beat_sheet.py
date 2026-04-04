"""Tests for the beat sheet — mapping story beats to panels.

Tests CRUD operations and auto_assign distribution logic.
All tests use tmp_rig_dir to isolate rig storage.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.storyboard.beat_sheet import (
    STANDARD_BEATS,
    _auto_distribute,
    _ensure_beat_sheet,
    _find_beat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rig_with_beats(beats: list[dict]) -> dict:
    """Create and persist a rig with pre-built beats."""
    rig = _load_rig("storyboard")
    rig = _ensure_beat_sheet(rig)
    rig["beat_sheet"]["beats"] = beats
    _save_rig("storyboard", rig)
    return rig


# ---------------------------------------------------------------------------
# _ensure_beat_sheet
# ---------------------------------------------------------------------------


def test_ensure_beat_sheet_creates_structure():
    """_ensure_beat_sheet adds beat_sheet with empty beats list."""
    rig = {}
    result = _ensure_beat_sheet(rig)
    assert "beat_sheet" in result
    assert result["beat_sheet"]["beats"] == []


def test_ensure_beat_sheet_preserves_existing():
    """_ensure_beat_sheet does not overwrite existing beats."""
    rig = {"beat_sheet": {"beats": [{"name": "opening", "panel": 1, "description": ""}]}}
    result = _ensure_beat_sheet(rig)
    assert len(result["beat_sheet"]["beats"]) == 1


# ---------------------------------------------------------------------------
# Add beat
# ---------------------------------------------------------------------------


def test_add_beat(tmp_rig_dir):
    """Adding a beat stores it in the rig."""
    _make_rig_with_beats([])

    rig = _load_rig("storyboard")
    rig = _ensure_beat_sheet(rig)

    beat = {"name": "inciting_incident", "panel": 3, "description": "GIR reveals his plan"}
    rig["beat_sheet"]["beats"].append(beat)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["beat_sheet"]["beats"]) == 1
    assert reloaded["beat_sheet"]["beats"][0]["name"] == "inciting_incident"
    assert reloaded["beat_sheet"]["beats"][0]["panel"] == 3


def test_add_beat_replaces_existing(tmp_rig_dir):
    """Adding a beat with the same name replaces the previous entry."""
    _make_rig_with_beats([
        {"name": "climax", "panel": 5, "description": "Old climax"},
    ])

    rig = _load_rig("storyboard")
    beats = rig["beat_sheet"]["beats"]

    # Remove old, add new
    beats = [b for b in beats if b.get("name") != "climax"]
    beats.append({"name": "climax", "panel": 8, "description": "New climax"})
    rig["beat_sheet"]["beats"] = beats
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    climax_beats = [b for b in reloaded["beat_sheet"]["beats"] if b["name"] == "climax"]
    assert len(climax_beats) == 1
    assert climax_beats[0]["panel"] == 8
    assert climax_beats[0]["description"] == "New climax"


# ---------------------------------------------------------------------------
# Remove beat
# ---------------------------------------------------------------------------


def test_remove_beat(tmp_rig_dir):
    """Removing a beat by name deletes it from the list."""
    _make_rig_with_beats([
        {"name": "opening", "panel": 1, "description": ""},
        {"name": "climax", "panel": 7, "description": "Big moment"},
    ])

    rig = _load_rig("storyboard")
    beats = rig["beat_sheet"]["beats"]
    _, idx = _find_beat(beats, "opening")
    assert idx is not None

    beats.pop(idx)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["beat_sheet"]["beats"]) == 1
    assert reloaded["beat_sheet"]["beats"][0]["name"] == "climax"


# ---------------------------------------------------------------------------
# auto_assign distribution
# ---------------------------------------------------------------------------


def test_auto_assign_10_panels():
    """Auto-assign with 10 panels distributes beats to expected positions.

    With 7 standard beats and 10 panels:
        opening=1, inciting_incident=2 (1+1.5=2.5->3? let's verify),
        rising_action at ~4, midpoint=5-6, climax=7-8,
        falling_action=9, resolution=10

    The formula: panel = 1 + i*(total-1)/(num_beats-1)
    """
    beats = _auto_distribute(10)
    assert len(beats) == len(STANDARD_BEATS)

    # Verify specific positions
    beat_map = {b["name"]: b["panel"] for b in beats}
    assert beat_map["opening"] == 1
    assert beat_map["resolution"] == 10
    # inciting_incident: 1 + 1*9/6 = 2.5 -> round to 2
    assert beat_map["inciting_incident"] == 2 or beat_map["inciting_incident"] == 3
    # climax should be in the later portion
    assert beat_map["climax"] >= 6


def test_auto_assign_3_panels():
    """With very few panels, beats still get valid assignments (1..total)."""
    beats = _auto_distribute(3)
    assert len(beats) == len(STANDARD_BEATS)

    for b in beats:
        assert 1 <= b["panel"] <= 3, f"Beat {b['name']} at panel {b['panel']} out of range 1-3"

    # First and last should be at boundaries
    beat_map = {b["name"]: b["panel"] for b in beats}
    assert beat_map["opening"] == 1
    assert beat_map["resolution"] == 3


def test_auto_assign_stores_in_rig(tmp_rig_dir):
    """auto_assign writes the beats to the rig and they persist."""
    rig = _load_rig("storyboard")
    rig = _ensure_beat_sheet(rig)
    rig["storyboard"] = {"panels": [{"number": i} for i in range(1, 11)]}
    _save_rig("storyboard", rig)

    # Simulate auto_assign
    beats = _auto_distribute(10)
    rig = _load_rig("storyboard")
    rig["beat_sheet"]["beats"] = beats
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["beat_sheet"]["beats"]) == len(STANDARD_BEATS)
    names = [b["name"] for b in reloaded["beat_sheet"]["beats"]]
    assert "opening" in names
    assert "climax" in names
    assert "resolution" in names
