"""Tests for the audio sync tool.

Tests CRUD operations and absolute frame calculation using direct rig
manipulation via _load_rig/_save_rig.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.audio_sync import (
    _ensure_audio_cues,
    _compute_panel_start_frames,
    export_markers,
    VALID_CUE_TYPES,
)
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_audio_cues
# ---------------------------------------------------------------------------


def test_ensure_audio_cues_creates_empty_list():
    """_ensure_audio_cues adds an empty list if missing."""
    rig = {"character_name": "test"}
    result = _ensure_audio_cues(rig)
    assert "audio_cues" in result
    assert result["audio_cues"] == []


def test_ensure_audio_cues_preserves_existing():
    """_ensure_audio_cues does not overwrite existing cues."""
    rig = {"audio_cues": [{"panel": 1, "type": "dialogue"}]}
    result = _ensure_audio_cues(rig)
    assert len(result["audio_cues"]) == 1


# ---------------------------------------------------------------------------
# Add and list cues
# ---------------------------------------------------------------------------


def test_add_audio_cue(tmp_rig_dir):
    """Adding an audio cue stores it with correct data."""
    char = "test_audio_add"
    rig = _load_rig(char)
    rig = _ensure_audio_cues(rig)

    cue = {
        "panel": 1,
        "type": "dialogue",
        "name": "GIR: I'm gonna sing the doom song!",
        "start_frame": 0,
        "duration": 48,
    }
    rig["audio_cues"].append(cue)
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert len(reloaded["audio_cues"]) == 1
    stored = reloaded["audio_cues"][0]
    assert stored["panel"] == 1
    assert stored["type"] == "dialogue"
    assert stored["name"] == "GIR: I'm gonna sing the doom song!"
    assert stored["start_frame"] == 0
    assert stored["duration"] == 48


def test_remove_audio_cue(tmp_rig_dir):
    """Removing a cue by name within a panel leaves others intact."""
    char = "test_audio_remove"
    rig = _load_rig(char)
    rig = _ensure_audio_cues(rig)

    rig["audio_cues"] = [
        {"panel": 1, "type": "dialogue", "name": "line_1", "start_frame": 0, "duration": 24},
        {"panel": 1, "type": "sfx", "name": "explosion", "start_frame": 12, "duration": 6},
        {"panel": 2, "type": "music", "name": "theme", "start_frame": 0, "duration": 48},
    ]
    _save_rig(char, rig)

    # Remove the explosion SFX from panel 1
    reloaded = _load_rig(char)
    reloaded["audio_cues"] = [
        c for c in reloaded["audio_cues"]
        if not (c.get("panel") == 1 and c.get("name") == "explosion")
    ]
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert len(final["audio_cues"]) == 2
    names = [c["name"] for c in final["audio_cues"]]
    assert "explosion" not in names
    assert "line_1" in names
    assert "theme" in names


# ---------------------------------------------------------------------------
# Absolute frame calculation
# ---------------------------------------------------------------------------


def test_absolute_frame_calculation(tmp_rig_dir):
    """export_markers computes correct absolute frames from panel durations.

    Panel 1 = 24 frames, panel 2 = 24 frames.
    A cue at panel 2, start_frame 12 → absolute frame = 24 + 12 = 36.
    """
    char = "test_audio_abs"
    rig = _load_rig(char)
    rig = _ensure_audio_cues(rig)

    # Set up storyboard with two panels
    rig["storyboard"] = {
        "panels": [
            {"number": 1, "duration_frames": 24},
            {"number": 2, "duration_frames": 24},
        ]
    }

    rig["audio_cues"] = [
        {"panel": 1, "type": "dialogue", "name": "intro", "start_frame": 0, "duration": 20},
        {"panel": 2, "type": "sfx", "name": "bang", "start_frame": 12, "duration": 6},
    ]
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    markers = export_markers(reloaded)

    assert len(markers) == 2

    # Panel 1 cue: absolute frame = 0 + 0 = 0
    assert markers[0]["absolute_frame"] == 0
    assert markers[0]["name"] == "intro"

    # Panel 2 cue: absolute frame = 24 + 12 = 36
    assert markers[1]["absolute_frame"] == 36
    assert markers[1]["name"] == "bang"
    assert markers[1]["absolute_end_frame"] == 42  # 36 + 6


def test_absolute_frame_multi_panel(tmp_rig_dir):
    """Absolute frame calculation across multiple panels with varying durations."""
    char = "test_audio_multi"
    rig = _load_rig(char)
    rig = _ensure_audio_cues(rig)

    # Panels with different durations: 48, 24, 36
    rig["storyboard"] = {
        "panels": [
            {"number": 1, "duration_frames": 48},
            {"number": 2, "duration_frames": 24},
            {"number": 3, "duration_frames": 36},
        ]
    }

    rig["audio_cues"] = [
        {"panel": 1, "type": "dialogue", "name": "a", "start_frame": 0, "duration": 10},
        {"panel": 3, "type": "music", "name": "b", "start_frame": 6, "duration": 30},
    ]
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    markers = export_markers(reloaded)

    # Panel 1 starts at 0, so cue at frame 0 → absolute 0
    assert markers[0]["absolute_frame"] == 0
    # Panel 3 starts at 48 + 24 = 72, cue at frame 6 → absolute 78
    assert markers[1]["absolute_frame"] == 78
    assert markers[1]["absolute_end_frame"] == 108  # 78 + 30
