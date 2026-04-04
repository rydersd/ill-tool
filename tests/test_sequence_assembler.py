"""Tests for the sequence assembler tool.

Tests CRUD operations, summary calculation, and outline formatting
using direct rig manipulation via _load_rig/_save_rig.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.production.sequence_assembler import (
    _ensure_sequence,
    _get_act,
    compute_summary,
    generate_outline,
    _format_runtime,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_sequence
# ---------------------------------------------------------------------------


def test_ensure_sequence_creates_empty_structure():
    """_ensure_sequence adds a sequence dict with empty acts list."""
    rig = {"character_name": "test"}
    result = _ensure_sequence(rig)
    assert "sequence" in result
    assert result["sequence"]["acts"] == []


def test_ensure_sequence_preserves_existing():
    """_ensure_sequence does not overwrite existing sequence data."""
    rig = {"sequence": {"acts": [{"number": 1, "name": "Setup", "scenes": []}]}}
    result = _ensure_sequence(rig)
    assert len(result["sequence"]["acts"]) == 1


# ---------------------------------------------------------------------------
# Create and list acts
# ---------------------------------------------------------------------------


def test_create_act(tmp_rig_dir):
    """Creating an act stores it in the rig sequence data."""
    char = "test_seq_create"
    rig = _load_rig(char)
    rig = _ensure_sequence(rig)

    act = {"number": 1, "name": "Setup", "scenes": [1, 2]}
    rig["sequence"]["acts"].append(act)
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert len(reloaded["sequence"]["acts"]) == 1
    stored = reloaded["sequence"]["acts"][0]
    assert stored["number"] == 1
    assert stored["name"] == "Setup"
    assert stored["scenes"] == [1, 2]


def test_add_scenes_to_act(tmp_rig_dir):
    """Adding scenes to an existing act appends them."""
    char = "test_seq_scenes"
    rig = _load_rig(char)
    rig = _ensure_sequence(rig)

    rig["sequence"]["acts"] = [
        {"number": 1, "name": "Setup", "scenes": [1]},
        {"number": 2, "name": "Confrontation", "scenes": []},
    ]
    _save_rig(char, rig)

    # Add scenes 3, 4, 5 to act 2
    reloaded = _load_rig(char)
    act2 = _get_act(reloaded, 2)
    assert act2 is not None
    act2["scenes"].extend([3, 4, 5])
    _save_rig(char, reloaded)

    final = _load_rig(char)
    act2_final = _get_act(final, 2)
    assert act2_final["scenes"] == [3, 4, 5]


# ---------------------------------------------------------------------------
# Summary calculation
# ---------------------------------------------------------------------------


def test_summary_counts_panels_across_acts(tmp_rig_dir):
    """Summary correctly counts panels, scenes, acts, and runtime."""
    char = "test_seq_summary"
    rig = _load_rig(char)
    rig = _ensure_sequence(rig)

    # 3 acts with scenes
    rig["sequence"]["acts"] = [
        {"number": 1, "name": "Setup", "scenes": [1, 2]},
        {"number": 2, "name": "Confrontation", "scenes": [3, 4, 5]},
        {"number": 3, "name": "Resolution", "scenes": [6]},
    ]

    # 6 panels, 24 frames each = 144 frames total
    rig["storyboard"] = {
        "panels": [
            {"number": i, "duration_frames": 24}
            for i in range(1, 7)
        ]
    }
    rig["timeline"] = {"fps": 24}
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    summary = compute_summary(reloaded)

    assert summary["total_acts"] == 3
    assert summary["total_scenes"] == 6
    assert summary["total_panels"] == 6
    assert summary["total_frames"] == 144
    assert summary["fps"] == 24
    assert summary["total_duration_seconds"] == pytest.approx(6.0)
    assert summary["estimated_runtime"] == "0:06"


# ---------------------------------------------------------------------------
# Outline formatting
# ---------------------------------------------------------------------------


def test_outline_formatting(tmp_rig_dir):
    """Export outline produces correctly formatted hierarchical text."""
    char = "test_seq_outline"
    rig = _load_rig(char)
    rig = _ensure_sequence(rig)

    rig["sequence"]["acts"] = [
        {"number": 1, "name": "Setup", "scenes": [1, 2]},
        {"number": 2, "name": "Confrontation", "scenes": [3]},
    ]

    # Scene data with panel assignments
    rig["scenes"] = [
        {"scene_number": 1, "panel_numbers": [1, 2, 3]},
        {"scene_number": 2, "panel_numbers": [4, 5]},
        {"scene_number": 3, "panel_numbers": [6]},
    ]
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    outline = generate_outline(reloaded)

    assert "Act I: Setup" in outline
    assert "Act II: Confrontation" in outline
    assert "Scene 1" in outline
    assert "Panels 1-3" in outline
    assert "Panels 4-5" in outline
    assert "Panel 6" in outline  # single panel, no range


def test_format_runtime():
    """_format_runtime formats seconds as MM:SS or HH:MM:SS."""
    assert _format_runtime(6.0) == "0:06"
    assert _format_runtime(65.0) == "1:05"
    assert _format_runtime(3661.0) == "1:01:01"
    assert _format_runtime(0.0) == "0:00"
