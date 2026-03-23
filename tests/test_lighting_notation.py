"""Tests for the lighting notation tool.

Tests data storage and the direction_to_angle mapping function
using direct rig manipulation via _load_rig/_save_rig.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.lighting_notation import (
    _ensure_lighting,
    direction_to_angle,
    DIRECTION_ANGLES,
    MOOD_TINTS,
)
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_lighting
# ---------------------------------------------------------------------------


def test_ensure_lighting_creates_empty_dict():
    """_ensure_lighting adds an empty lighting dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_lighting(rig)
    assert "lighting" in result
    assert result["lighting"] == {}


# ---------------------------------------------------------------------------
# direction_to_angle mapping
# ---------------------------------------------------------------------------


def test_direction_to_angle_known_values():
    """Known directions map to correct angles."""
    assert direction_to_angle("top_left") == 135
    assert direction_to_angle("right") == 0
    assert direction_to_angle("top") == 90
    assert direction_to_angle("left") == 180
    assert direction_to_angle("bottom") == 270
    assert direction_to_angle("top_right") == 45
    assert direction_to_angle("bottom_left") == 225
    assert direction_to_angle("front") == 90
    assert direction_to_angle("back") == 270


def test_direction_to_angle_unknown_returns_zero():
    """Unknown direction names return 0 as default."""
    assert direction_to_angle("from_the_moon") == 0
    assert direction_to_angle("") == 0


# ---------------------------------------------------------------------------
# Lighting data storage
# ---------------------------------------------------------------------------


def test_lighting_data_storage(tmp_rig_dir):
    """Lighting data round-trips through rig save/load correctly."""
    char = "test_lighting"
    rig = _load_rig(char)
    rig = _ensure_lighting(rig)

    # Store lighting for panel 1
    rig["lighting"]["1"] = {
        "key": "top_left",
        "fill": "right",
        "rim": True,
        "mood": "dramatic",
    }
    _save_rig(char, rig)

    # Reload and verify
    reloaded = _load_rig(char)
    panel_lighting = reloaded["lighting"]["1"]
    assert panel_lighting["key"] == "top_left"
    assert panel_lighting["fill"] == "right"
    assert panel_lighting["rim"] is True
    assert panel_lighting["mood"] == "dramatic"

    # Verify the mood maps to valid tint values
    mood = panel_lighting["mood"]
    assert mood in MOOD_TINTS
    r, g, b = MOOD_TINTS[mood]
    assert r == 30
    assert g == 25
    assert b == 40


def test_lighting_multiple_panels(tmp_rig_dir):
    """Lighting data can be stored independently for multiple panels."""
    char = "test_lighting_multi"
    rig = _load_rig(char)
    rig = _ensure_lighting(rig)

    rig["lighting"]["1"] = {"key": "top_left", "fill": "right", "rim": True, "mood": "bright"}
    rig["lighting"]["2"] = {"key": "left", "fill": "top_right", "rim": False, "mood": "noir"}
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert len(reloaded["lighting"]) == 2
    assert reloaded["lighting"]["1"]["mood"] == "bright"
    assert reloaded["lighting"]["2"]["mood"] == "noir"
    assert reloaded["lighting"]["1"]["rim"] is True
    assert reloaded["lighting"]["2"]["rim"] is False
