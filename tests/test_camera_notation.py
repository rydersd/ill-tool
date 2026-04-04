"""Tests for the camera notation system.

Tests notation data storage, intensity mapping, and movement direction helpers.
All tests are pure Python — no JSX or Adobe required.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.ui.camera_notation import (
    INTENSITY_SCALE,
    _get_intensity_scale,
    _ensure_camera_notations,
    _movement_label,
    _arrow_direction,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _get_intensity_scale
# ---------------------------------------------------------------------------


def test_intensity_subtle():
    """Subtle intensity maps to 0.5x scale."""
    assert _get_intensity_scale("subtle") == pytest.approx(0.5)


def test_intensity_medium():
    """Medium intensity maps to 1.0x scale."""
    assert _get_intensity_scale("medium") == pytest.approx(1.0)


def test_intensity_dramatic():
    """Dramatic intensity maps to 2.0x scale."""
    assert _get_intensity_scale("dramatic") == pytest.approx(2.0)


def test_intensity_unknown_defaults_to_medium():
    """Unknown intensity defaults to 1.0x (medium)."""
    assert _get_intensity_scale("extreme") == pytest.approx(1.0)


def test_intensity_case_insensitive():
    """Intensity matching is case-insensitive."""
    assert _get_intensity_scale("SUBTLE") == pytest.approx(0.5)
    assert _get_intensity_scale("Dramatic") == pytest.approx(2.0)


def test_intensity_whitespace_stripped():
    """Whitespace around intensity is stripped."""
    assert _get_intensity_scale("  medium  ") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _movement_label
# ---------------------------------------------------------------------------


def test_movement_label_truck():
    """Truck movements get 'T' label."""
    assert _movement_label("truck_left") == "T"
    assert _movement_label("truck_right") == "T"


def test_movement_label_dolly():
    """Dolly movements get 'D' label."""
    assert _movement_label("dolly_in") == "D"
    assert _movement_label("dolly_out") == "D"


def test_movement_label_crane():
    """Crane movements get 'C' label."""
    assert _movement_label("crane_up") == "C"
    assert _movement_label("crane_down") == "C"


def test_movement_label_pan_empty():
    """Pan movements have no special label."""
    assert _movement_label("pan_left") == ""
    assert _movement_label("pan_right") == ""


def test_movement_label_tilt_empty():
    """Tilt movements have no special label."""
    assert _movement_label("tilt_up") == ""
    assert _movement_label("tilt_down") == ""


def test_movement_label_static_empty():
    """Static has no label."""
    assert _movement_label("static") == ""


# ---------------------------------------------------------------------------
# _arrow_direction
# ---------------------------------------------------------------------------


def test_arrow_direction_pan_left():
    """Pan left direction is (-1, 0)."""
    dx, dy = _arrow_direction("pan_left")
    assert dx == -1
    assert dy == 0


def test_arrow_direction_pan_right():
    """Pan right direction is (1, 0)."""
    dx, dy = _arrow_direction("pan_right")
    assert dx == 1
    assert dy == 0


def test_arrow_direction_tilt_up():
    """Tilt up direction is (0, 1)."""
    dx, dy = _arrow_direction("tilt_up")
    assert dx == 0
    assert dy == 1


def test_arrow_direction_tilt_down():
    """Tilt down direction is (0, -1)."""
    dx, dy = _arrow_direction("tilt_down")
    assert dx == 0
    assert dy == -1


def test_arrow_direction_truck_left():
    """Truck left direction is (-1, 0) — same as pan_left."""
    dx, dy = _arrow_direction("truck_left")
    assert dx == -1
    assert dy == 0


def test_arrow_direction_dolly_in():
    """Dolly in direction is (0, 1) — toward subject."""
    dx, dy = _arrow_direction("dolly_in")
    assert dx == 0
    assert dy == 1


def test_arrow_direction_unknown():
    """Unknown movement returns (0, 0) — no direction."""
    dx, dy = _arrow_direction("unknown_move")
    assert dx == 0
    assert dy == 0


# ---------------------------------------------------------------------------
# _ensure_camera_notations
# ---------------------------------------------------------------------------


def test_ensure_camera_notations_creates_key():
    """Creates camera_notations dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_camera_notations(rig)
    assert "camera_notations" in result
    assert result["camera_notations"] == {}


def test_ensure_camera_notations_preserves_existing():
    """Does not overwrite existing camera_notations."""
    rig = {"camera_notations": {"1": {"movement": "pan_left"}}}
    result = _ensure_camera_notations(rig)
    assert "1" in result["camera_notations"]


# ---------------------------------------------------------------------------
# Rig data storage
# ---------------------------------------------------------------------------


def test_store_camera_notation_in_rig(tmp_rig_dir):
    """Camera notation data roundtrips through rig save/load."""
    rig = _load_rig("storyboard")
    rig = _ensure_camera_notations(rig)

    rig["camera_notations"]["1"] = {
        "movement": "pan_left",
        "intensity": "medium",
        "scale": 1.0,
    }
    _save_rig("storyboard", rig)

    loaded = _load_rig("storyboard")
    notation = loaded["camera_notations"]["1"]
    assert notation["movement"] == "pan_left"
    assert notation["intensity"] == "medium"
    assert notation["scale"] == 1.0


def test_store_multiple_notations(tmp_rig_dir):
    """Multiple panels can have different camera notations."""
    rig = _load_rig("storyboard")
    rig = _ensure_camera_notations(rig)

    rig["camera_notations"]["1"] = {
        "movement": "pan_right",
        "intensity": "subtle",
        "scale": _get_intensity_scale("subtle"),
    }
    rig["camera_notations"]["2"] = {
        "movement": "zoom_in",
        "intensity": "dramatic",
        "scale": _get_intensity_scale("dramatic"),
    }
    _save_rig("storyboard", rig)

    loaded = _load_rig("storyboard")
    assert loaded["camera_notations"]["1"]["movement"] == "pan_right"
    assert loaded["camera_notations"]["1"]["scale"] == pytest.approx(0.5)
    assert loaded["camera_notations"]["2"]["movement"] == "zoom_in"
    assert loaded["camera_notations"]["2"]["scale"] == pytest.approx(2.0)


def test_overwrite_notation(tmp_rig_dir):
    """Overwriting a panel's notation replaces the previous one."""
    rig = _load_rig("storyboard")
    rig = _ensure_camera_notations(rig)

    rig["camera_notations"]["3"] = {
        "movement": "static",
        "intensity": "medium",
        "scale": 1.0,
    }
    _save_rig("storyboard", rig)

    # Overwrite
    loaded = _load_rig("storyboard")
    loaded["camera_notations"]["3"] = {
        "movement": "handheld",
        "intensity": "dramatic",
        "scale": 2.0,
    }
    _save_rig("storyboard", loaded)

    final = _load_rig("storyboard")
    assert final["camera_notations"]["3"]["movement"] == "handheld"
    assert final["camera_notations"]["3"]["scale"] == 2.0


def test_intensity_scale_values():
    """All defined intensity scale values are correct."""
    assert INTENSITY_SCALE["subtle"] == 0.5
    assert INTENSITY_SCALE["medium"] == 1.0
    assert INTENSITY_SCALE["dramatic"] == 2.0
    assert len(INTENSITY_SCALE) == 3
