"""Tests for background layer data storage and color validation.

Tests the rig persistence layer for background data — does NOT test
JSX execution (that requires a running Illustrator instance).
"""

import json

import pytest

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.background_layer import (
    _ensure_backgrounds,
    _validate_color,
)


# ---------------------------------------------------------------------------
# _validate_color
# ---------------------------------------------------------------------------


def test_validate_color_valid():
    """Valid RGB values return None (no error)."""
    assert _validate_color(0, 0, 0) is None
    assert _validate_color(255, 255, 255) is None
    assert _validate_color(128, 64, 200) is None


def test_validate_color_out_of_range():
    """Out-of-range RGB values return an error string."""
    err = _validate_color(256, 0, 0)
    assert err is not None
    assert "red" in err

    err = _validate_color(0, -1, 0)
    assert err is not None
    assert "green" in err

    err = _validate_color(0, 0, 300)
    assert err is not None
    assert "blue" in err


# ---------------------------------------------------------------------------
# Background data persistence
# ---------------------------------------------------------------------------


def test_solid_background_data(tmp_rig_dir):
    """Solid background data round-trips through the rig."""
    rig = _load_rig("storyboard")
    rig = _ensure_backgrounds(rig)

    bg_data = {
        "type": "solid",
        "color": [40, 40, 60],
        "opacity": 100,
    }
    rig["backgrounds"]["1"] = bg_data
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert "1" in reloaded["backgrounds"]
    assert reloaded["backgrounds"]["1"]["type"] == "solid"
    assert reloaded["backgrounds"]["1"]["color"] == [40, 40, 60]
    assert reloaded["backgrounds"]["1"]["opacity"] == 100


def test_gradient_background_data(tmp_rig_dir):
    """Gradient background stores start and end colors."""
    rig = _load_rig("storyboard")
    rig = _ensure_backgrounds(rig)

    bg_data = {
        "type": "gradient",
        "color": [0, 0, 50],
        "gradient_end": [0, 0, 200],
        "opacity": 80,
    }
    rig["backgrounds"]["2"] = bg_data
    _save_rig("storyboard", rig)

    reloaded = _load_rig("storyboard")
    assert reloaded["backgrounds"]["2"]["type"] == "gradient"
    assert reloaded["backgrounds"]["2"]["gradient_end"] == [0, 0, 200]


def test_remove_background_data(tmp_rig_dir):
    """Removing a background removes it from the rig data."""
    rig = _load_rig("storyboard")
    rig = _ensure_backgrounds(rig)

    rig["backgrounds"]["1"] = {"type": "solid", "color": [0, 0, 0], "opacity": 100}
    rig["backgrounds"]["2"] = {"type": "solid", "color": [255, 255, 255], "opacity": 100}
    _save_rig("storyboard", rig)

    # Remove panel 1 background
    reloaded = _load_rig("storyboard")
    reloaded["backgrounds"].pop("1", None)
    _save_rig("storyboard", reloaded)

    final = _load_rig("storyboard")
    assert "1" not in final["backgrounds"]
    assert "2" in final["backgrounds"]
