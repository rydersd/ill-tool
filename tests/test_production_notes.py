"""Tests for the production_notes tool.

Tests CRUD operations, priority filtering, and export formatting
using direct rig manipulation via _load_rig/_save_rig with
the tmp_rig_dir fixture.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.production.production_notes import (
    _ensure_production_notes,
    _filter_by_priority,
    _export_notes,
    _get_panel_notes,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_production_notes
# ---------------------------------------------------------------------------


def test_ensure_production_notes_creates_dict():
    """_ensure_production_notes adds an empty dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_production_notes(rig)
    assert "production_notes" in result
    assert result["production_notes"] == {}


def test_ensure_production_notes_preserves_existing():
    """_ensure_production_notes does not overwrite existing notes."""
    rig = {
        "production_notes": {
            "1": [{"type": "direction", "note": "Camera shakes", "priority": "high"}],
        },
    }
    result = _ensure_production_notes(rig)
    assert len(result["production_notes"]["1"]) == 1
    assert result["production_notes"]["1"][0]["note"] == "Camera shakes"


# ---------------------------------------------------------------------------
# CRUD via rig manipulation
# ---------------------------------------------------------------------------


def test_add_and_retrieve_notes(tmp_rig_dir):
    """Adding notes to a panel and reading them back."""
    char = "test_notes_crud"
    rig = _load_rig(char)
    rig = _ensure_production_notes(rig)

    # Add two notes to panel 1
    rig["production_notes"]["1"] = [
        {"type": "direction", "note": "Slow pan left", "priority": "normal"},
        {"type": "vfx", "note": "Add rain particles", "priority": "high"},
    ]
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    notes = _get_panel_notes(reloaded, 1)
    assert len(notes) == 2
    assert notes[0]["note"] == "Slow pan left"
    assert notes[1]["type"] == "vfx"


def test_clear_panel_notes(tmp_rig_dir):
    """Clearing notes from a panel removes them entirely."""
    char = "test_notes_clear"
    rig = _load_rig(char)
    rig = _ensure_production_notes(rig)
    rig["production_notes"]["3"] = [
        {"type": "audio", "note": "Thunder SFX", "priority": "high"},
    ]
    _save_rig(char, rig)

    # Clear panel 3
    reloaded = _load_rig(char)
    reloaded["production_notes"].pop("3", None)
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert "3" not in final.get("production_notes", {})


# ---------------------------------------------------------------------------
# Priority filtering
# ---------------------------------------------------------------------------


def test_filter_by_priority():
    """_filter_by_priority returns only notes matching the given priority."""
    notes = [
        {"type": "direction", "note": "A", "priority": "low"},
        {"type": "vfx", "note": "B", "priority": "high"},
        {"type": "audio", "note": "C", "priority": "high"},
        {"type": "technical", "note": "D", "priority": "normal"},
    ]

    high_notes = _filter_by_priority(notes, "high")
    assert len(high_notes) == 2
    assert all(n["priority"] == "high" for n in high_notes)

    # None returns all
    all_notes = _filter_by_priority(notes, None)
    assert len(all_notes) == 4


# ---------------------------------------------------------------------------
# Export format
# ---------------------------------------------------------------------------


def test_export_formatted_text():
    """_export_notes produces human-readable text grouped by panel."""
    rig = {
        "production_notes": {
            "1": [
                {"type": "direction", "note": "Camera shakes", "priority": "high"},
                {"type": "vfx", "note": "Add sparks", "priority": "normal"},
            ],
            "2": [
                {"type": "audio", "note": "Thunder SFX", "priority": "critical"},
            ],
        },
    }

    text = _export_notes(rig)

    # Verify structure
    assert "PRODUCTION NOTES" in text
    assert "Panel 1" in text
    assert "Panel 2" in text
    assert "Camera shakes" in text
    assert "Thunder SFX" in text
    # Critical should appear before normal within a panel
    assert "[HIGH]" in text
    assert "[CRITICAL]" in text
