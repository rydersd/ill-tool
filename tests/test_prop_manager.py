"""Tests for the prop manager tool.

Tests CRUD operations and joint attachment data using direct rig
manipulation via _load_rig/_save_rig with the tmp_rig_dir fixture.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.prop_manager import _ensure_props
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_props
# ---------------------------------------------------------------------------


def test_ensure_props_creates_empty_dict():
    """_ensure_props adds an empty props dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_props(rig)
    assert "props" in result
    assert result["props"] == {}


def test_ensure_props_preserves_existing():
    """_ensure_props does not overwrite existing props."""
    rig = {"props": {"sword": {"panels": [], "attached_to": None}}}
    result = _ensure_props(rig)
    assert "sword" in result["props"]


# ---------------------------------------------------------------------------
# Create and list props
# ---------------------------------------------------------------------------


def test_create_and_list_props(tmp_rig_dir):
    """Creating a prop stores it in rig data and listing returns it."""
    char = "test_props_create"
    rig = _load_rig(char)
    rig = _ensure_props(rig)

    # Create a sword prop
    rig["props"]["sword"] = {
        "panels": [],
        "prop_path": "/assets/sword.svg",
        "attached_to": None,
    }
    _save_rig(char, rig)

    # Reload and verify
    reloaded = _load_rig(char)
    assert "sword" in reloaded["props"]
    assert reloaded["props"]["sword"]["prop_path"] == "/assets/sword.svg"
    assert reloaded["props"]["sword"]["panels"] == []
    assert reloaded["props"]["sword"]["attached_to"] is None


# ---------------------------------------------------------------------------
# Place and remove props from panels
# ---------------------------------------------------------------------------


def test_place_prop_in_panels(tmp_rig_dir):
    """Placing a prop in panels adds panel entries with position data."""
    char = "test_props_place"
    rig = _load_rig(char)
    rig = _ensure_props(rig)

    rig["props"]["shield"] = {
        "panels": [],
        "prop_path": "",
        "attached_to": None,
    }

    # Place in panels 3 and 5
    rig["props"]["shield"]["panels"] = [
        {"panel": 3, "x": 100, "y": 200},
        {"panel": 5, "x": 150, "y": 250},
    ]
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    panels = reloaded["props"]["shield"]["panels"]
    assert len(panels) == 2
    assert panels[0]["panel"] == 3
    assert panels[0]["x"] == 100
    assert panels[1]["panel"] == 5


def test_remove_prop_from_panel(tmp_rig_dir):
    """Removing a prop from a specific panel leaves others intact."""
    char = "test_props_remove"
    rig = _load_rig(char)
    rig = _ensure_props(rig)

    rig["props"]["hat"] = {
        "panels": [
            {"panel": 1, "x": 10, "y": 20},
            {"panel": 2, "x": 30, "y": 40},
            {"panel": 3, "x": 50, "y": 60},
        ],
        "prop_path": "",
        "attached_to": None,
    }
    _save_rig(char, rig)

    # Remove from panel 2
    reloaded = _load_rig(char)
    reloaded["props"]["hat"]["panels"] = [
        p for p in reloaded["props"]["hat"]["panels"]
        if p.get("panel") != 2
    ]
    _save_rig(char, reloaded)

    final = _load_rig(char)
    remaining = final["props"]["hat"]["panels"]
    assert len(remaining) == 2
    panel_nums = [p["panel"] for p in remaining]
    assert 2 not in panel_nums
    assert 1 in panel_nums
    assert 3 in panel_nums


# ---------------------------------------------------------------------------
# Joint attachment
# ---------------------------------------------------------------------------


def test_attach_to_joint(tmp_rig_dir):
    """Attaching a prop to a joint stores character and joint name."""
    char = "test_props_joint"
    rig = _load_rig(char)
    rig = _ensure_props(rig)

    rig["props"]["sword"] = {
        "panels": [3, 5],
        "prop_path": "",
        "attached_to": None,
    }
    _save_rig(char, rig)

    # Attach sword to wrist_r joint
    reloaded = _load_rig(char)
    reloaded["props"]["sword"]["attached_to"] = {
        "character": "gir",
        "joint": "wrist_r",
    }
    _save_rig(char, reloaded)

    final = _load_rig(char)
    attachment = final["props"]["sword"]["attached_to"]
    assert attachment is not None
    assert attachment["character"] == "gir"
    assert attachment["joint"] == "wrist_r"
