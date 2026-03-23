"""Tests for the director markup tool.

Verifies markup data structures and toggle state using rig persistence.
All tests are pure Python — no JSX or Adobe required.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.director_markup import (
    _ensure_markup,
    _get_panel_markup,
    _set_panel_markup,
)
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_markup
# ---------------------------------------------------------------------------


def test_ensure_markup_creates_empty_dict():
    """_ensure_markup adds director_markup dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_markup(rig)
    assert "director_markup" in result
    assert result["director_markup"] == {}


def test_ensure_markup_preserves_existing():
    """_ensure_markup does not overwrite existing markup data."""
    rig = {"director_markup": {"1": {"items": [{"type": "note"}], "visible": True}}}
    result = _ensure_markup(rig)
    assert len(result["director_markup"]["1"]["items"]) == 1


# ---------------------------------------------------------------------------
# Markup data structure
# ---------------------------------------------------------------------------


def test_note_item_structure():
    """Note markup item has required fields."""
    note = {"type": "note", "text": "Move camera left", "x": 100.0, "y": 200.0}
    assert note["type"] == "note"
    assert note["text"] == "Move camera left"
    assert note["x"] == 100.0
    assert note["y"] == 200.0


def test_arrow_item_structure():
    """Arrow markup item has start and end points."""
    arrow = {"type": "arrow", "x1": 100.0, "y1": 200.0, "x2": 300.0, "y2": 250.0}
    assert arrow["type"] == "arrow"
    assert arrow["x1"] < arrow["x2"]


# ---------------------------------------------------------------------------
# Toggle state and persistence
# ---------------------------------------------------------------------------


def test_toggle_visibility_state(tmp_rig_dir):
    """Markup visibility state persists through rig save/load."""
    char = "test_markup_toggle"
    rig = _load_rig(char)
    rig = _ensure_markup(rig)

    # Set visible = False
    items = [{"type": "note", "text": "Test", "x": 50, "y": 50}]
    rig = _set_panel_markup(rig, 1, items, visible=False)
    _save_rig(char, rig)

    # Reload and verify
    reloaded = _load_rig(char)
    panel_data = reloaded["director_markup"]["1"]
    assert panel_data["visible"] is False
    assert len(panel_data["items"]) == 1

    # Toggle back to visible
    rig = _set_panel_markup(reloaded, 1, items, visible=True)
    _save_rig(char, rig)

    reloaded2 = _load_rig(char)
    assert reloaded2["director_markup"]["1"]["visible"] is True
