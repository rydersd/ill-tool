"""Tests for the scene manager — grouping panels into scenes.

All tests use tmp_rig_dir to isolate rig storage from /tmp/ai_rigs.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.scene_manager import (
    _ensure_scenes,
    _find_scene,
    _next_scene_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rig_with_scenes(scenes: list[dict]) -> dict:
    """Create and persist a rig with pre-built scenes."""
    rig = _load_rig("storyboard")
    rig = _ensure_scenes(rig)
    rig["scenes"] = scenes
    _save_rig("storyboard", rig)
    return rig


# ---------------------------------------------------------------------------
# _ensure_scenes / _next_scene_number
# ---------------------------------------------------------------------------


def test_ensure_scenes_creates_empty_list():
    """_ensure_scenes adds an empty scenes list if missing."""
    rig = {"character_name": "storyboard"}
    result = _ensure_scenes(rig)
    assert "scenes" in result
    assert result["scenes"] == []


def test_next_scene_number_empty():
    """Next scene number on an empty rig is 1."""
    rig = _ensure_scenes({})
    assert _next_scene_number(rig) == 1


def test_next_scene_number_after_existing():
    """Next scene number is max(existing) + 1."""
    rig = _ensure_scenes({})
    rig["scenes"] = [{"number": 1}, {"number": 3}]
    assert _next_scene_number(rig) == 4


# ---------------------------------------------------------------------------
# Create scene
# ---------------------------------------------------------------------------


def test_create_scene(tmp_rig_dir):
    """Creating a scene stores it in the rig with correct fields."""
    _make_rig_with_scenes([])

    rig = _load_rig("storyboard")
    rig = _ensure_scenes(rig)

    scene = {
        "number": 1,
        "name": "GIR arrives",
        "panels": [1, 2, 3],
        "location": "INT",
        "time": "NIGHT",
    }
    rig["scenes"].append(scene)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["scenes"]) == 1
    assert reloaded["scenes"][0]["name"] == "GIR arrives"
    assert reloaded["scenes"][0]["panels"] == [1, 2, 3]
    assert reloaded["scenes"][0]["location"] == "INT"
    assert reloaded["scenes"][0]["time"] == "NIGHT"


# ---------------------------------------------------------------------------
# Add panel to scene
# ---------------------------------------------------------------------------


def test_add_panel_to_scene(tmp_rig_dir):
    """Adding panels to an existing scene appends without duplicates."""
    _make_rig_with_scenes([
        {"number": 1, "name": "Scene 1", "panels": [1, 2], "location": "INT", "time": "DAY"},
    ])

    rig = _load_rig("storyboard")
    scene, _ = _find_scene(rig, 1)
    assert scene is not None

    # Add panel 3 (new) and panel 2 (duplicate — should be ignored)
    existing_panels = set(scene["panels"])
    for pn in [3, 2]:
        if pn not in existing_panels:
            scene["panels"].append(pn)
            existing_panels.add(pn)

    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert reloaded["scenes"][0]["panels"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Remove panel from scene
# ---------------------------------------------------------------------------


def test_remove_panel_from_scene(tmp_rig_dir):
    """Removing a panel from a scene leaves the remaining panels intact."""
    _make_rig_with_scenes([
        {"number": 1, "name": "Scene 1", "panels": [1, 2, 3], "location": "EXT", "time": "DAWN"},
    ])

    rig = _load_rig("storyboard")
    scene, _ = _find_scene(rig, 1)
    assert scene is not None

    remove_set = {2}
    scene["panels"] = [p for p in scene["panels"] if p not in remove_set]
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert reloaded["scenes"][0]["panels"] == [1, 3]


# ---------------------------------------------------------------------------
# Reorder panels within scene
# ---------------------------------------------------------------------------


def test_reorder_panels(tmp_rig_dir):
    """Reordering panels replaces the panel list with a new ordering."""
    _make_rig_with_scenes([
        {"number": 1, "name": "Scene 1", "panels": [1, 2, 3], "location": "INT", "time": "DAY"},
    ])

    rig = _load_rig("storyboard")
    scene, _ = _find_scene(rig, 1)
    scene["panels"] = [3, 1, 2]
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert reloaded["scenes"][0]["panels"] == [3, 1, 2]


# ---------------------------------------------------------------------------
# Delete scene
# ---------------------------------------------------------------------------


def test_delete_scene(tmp_rig_dir):
    """Deleting a scene removes it from the list."""
    _make_rig_with_scenes([
        {"number": 1, "name": "Scene 1", "panels": [1], "location": "INT", "time": "DAY"},
        {"number": 2, "name": "Scene 2", "panels": [4, 5], "location": "EXT", "time": "NIGHT"},
    ])

    rig = _load_rig("storyboard")
    scene, idx = _find_scene(rig, 1)
    assert scene is not None
    rig["scenes"].pop(idx)
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert len(reloaded["scenes"]) == 1
    assert reloaded["scenes"][0]["number"] == 2


# ---------------------------------------------------------------------------
# Find scene returns None for missing
# ---------------------------------------------------------------------------


def test_find_scene_missing():
    """_find_scene returns (None, None) for a non-existent scene number."""
    rig = _ensure_scenes({})
    rig["scenes"] = [{"number": 1, "name": "A", "panels": [], "location": "INT", "time": "DAY"}]
    scene, idx = _find_scene(rig, 99)
    assert scene is None
    assert idx is None
