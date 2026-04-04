"""Tests for the transition planner tool.

Tests data storage and transition type validation using direct rig
manipulation via _load_rig/_save_rig.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.ui.transition_planner import (
    _ensure_transitions,
    VALID_TRANSITIONS,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_transitions
# ---------------------------------------------------------------------------


def test_ensure_transitions_creates_empty_dict():
    """_ensure_transitions adds an empty transitions dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_transitions(rig)
    assert "transitions" in result
    assert result["transitions"] == {}


# ---------------------------------------------------------------------------
# Transition type validation
# ---------------------------------------------------------------------------


def test_valid_transition_types():
    """All documented transition types are in the valid set."""
    expected = {
        "cut", "dissolve", "wipe_left", "wipe_right", "wipe_up", "wipe_down",
        "match_cut", "smash_cut", "fade_in", "fade_out", "iris",
    }
    assert VALID_TRANSITIONS == expected


def test_invalid_transition_rejected():
    """An unknown transition type is not in the valid set."""
    assert "teleport" not in VALID_TRANSITIONS
    assert "jump_cut" not in VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Transition data storage
# ---------------------------------------------------------------------------


def test_transition_data_storage(tmp_rig_dir):
    """Transition data round-trips through rig save/load correctly."""
    char = "test_transitions"
    rig = _load_rig(char)
    rig = _ensure_transitions(rig)

    # Store a dissolve transition for panel 1
    rig["transitions"]["1"] = {
        "type": "dissolve",
        "duration_frames": 12,
    }
    _save_rig(char, rig)

    # Reload and verify
    reloaded = _load_rig(char)
    trans = reloaded["transitions"]["1"]
    assert trans["type"] == "dissolve"
    assert trans["duration_frames"] == 12


def test_transition_multiple_panels(tmp_rig_dir):
    """Multiple panel transitions can coexist independently."""
    char = "test_transitions_multi"
    rig = _load_rig(char)
    rig = _ensure_transitions(rig)

    rig["transitions"]["1"] = {"type": "cut", "duration_frames": 1}
    rig["transitions"]["2"] = {"type": "dissolve", "duration_frames": 12}
    rig["transitions"]["3"] = {"type": "wipe_left", "duration_frames": 8}
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert len(reloaded["transitions"]) == 3
    assert reloaded["transitions"]["1"]["type"] == "cut"
    assert reloaded["transitions"]["2"]["type"] == "dissolve"
    assert reloaded["transitions"]["3"]["type"] == "wipe_left"
    assert reloaded["transitions"]["3"]["duration_frames"] == 8
