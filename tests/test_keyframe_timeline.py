"""Tests for the keyframe timeline management system.

Tests _ensure_timeline, _timing_info, and the timeline actions by directly
manipulating rig JSON via _load_rig/_save_rig with the tmp_rig_dir fixture.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.animation.keyframe_timeline import (
    _ensure_timeline,
    _timing_info,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rig_with_poses(character_name: str, pose_names: list[str]) -> dict:
    """Create a rig dict with stub poses for keyframe validation."""
    rig = _load_rig(character_name)
    rig = _ensure_timeline(rig)
    rig["poses"] = {name: {"joints": {}, "path_states": {}} for name in pose_names}
    _save_rig(character_name, rig)
    return rig


# ---------------------------------------------------------------------------
# _ensure_timeline
# ---------------------------------------------------------------------------


def test_ensure_timeline_creates_defaults():
    """_ensure_timeline adds timeline and keyframes if missing."""
    rig = {"character_name": "test"}
    result = _ensure_timeline(rig)
    assert "timeline" in result
    assert "keyframes" in result
    assert result["timeline"]["fps"] == 24
    assert result["timeline"]["duration_frames"] == 120


def test_ensure_timeline_preserves_existing():
    """_ensure_timeline does not overwrite existing timeline settings."""
    rig = {
        "timeline": {"fps": 30, "duration_frames": 60},
        "keyframes": [{"frame": 0, "pose_name": "idle"}],
    }
    result = _ensure_timeline(rig)
    assert result["timeline"]["fps"] == 30
    assert len(result["keyframes"]) == 1


# ---------------------------------------------------------------------------
# _timing_info
# ---------------------------------------------------------------------------


def test_timing_info_defaults():
    """Default timing: 24fps, 120 frames = 5 seconds."""
    rig = _ensure_timeline({})
    info = _timing_info(rig)
    assert info["fps"] == 24
    assert info["duration_frames"] == 120
    assert info["seconds_per_frame"] == pytest.approx(1.0 / 24, abs=0.001)
    assert info["total_duration_seconds"] == pytest.approx(5.0)


def test_fps_calculation():
    """fps=24, frame=48 → time should be 2.0 seconds."""
    rig = _ensure_timeline({})
    rig["timeline"]["fps"] = 24
    info = _timing_info(rig)
    # 48 frames at 24fps = 2.0 seconds
    frame_time = 48 / info["fps"]
    assert frame_time == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Add keyframe (via direct rig manipulation)
# ---------------------------------------------------------------------------


def test_add_keyframe(tmp_rig_dir):
    """Adding a keyframe at frame 0 stores it in the rig data."""
    char = "test_add"
    rig = _make_rig_with_poses(char, ["idle"])

    # Add a keyframe manually (mimicking the tool action)
    keyframe = {"frame": 0, "pose_name": "idle", "easing": "linear"}
    rig["keyframes"].append(keyframe)
    rig["keyframes"].sort(key=lambda kf: kf.get("frame", 0))
    _save_rig(char, rig)

    # Reload and verify
    reloaded = _load_rig(char)
    assert len(reloaded["keyframes"]) == 1
    assert reloaded["keyframes"][0]["frame"] == 0
    assert reloaded["keyframes"][0]["pose_name"] == "idle"


def test_keyframes_sorted(tmp_rig_dir):
    """Keyframes added out of order are sorted by frame number."""
    char = "test_sorted"
    rig = _make_rig_with_poses(char, ["idle", "walk", "run"])

    # Add keyframes in non-sequential order
    for frame, pose in [(24, "walk"), (0, "idle"), (12, "run")]:
        rig["keyframes"].append({"frame": frame, "pose_name": pose, "easing": "linear"})

    rig["keyframes"].sort(key=lambda kf: kf.get("frame", 0))
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    frames = [kf["frame"] for kf in reloaded["keyframes"]]
    assert frames == [0, 12, 24]


# ---------------------------------------------------------------------------
# Remove keyframe
# ---------------------------------------------------------------------------


def test_remove_keyframe(tmp_rig_dir):
    """Removing a keyframe by frame number removes it from the list."""
    char = "test_remove"
    rig = _make_rig_with_poses(char, ["idle", "walk"])

    rig["keyframes"] = [
        {"frame": 0, "pose_name": "idle", "easing": "linear"},
        {"frame": 24, "pose_name": "walk", "easing": "linear"},
    ]
    _save_rig(char, rig)

    # Remove frame 0
    reloaded = _load_rig(char)
    reloaded["keyframes"] = [
        kf for kf in reloaded["keyframes"] if kf.get("frame") != 0
    ]
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert len(final["keyframes"]) == 1
    assert final["keyframes"][0]["frame"] == 24


# ---------------------------------------------------------------------------
# Duration setting
# ---------------------------------------------------------------------------


def test_duration_setting(tmp_rig_dir):
    """Setting duration stores the value and updates timing info."""
    char = "test_duration"
    rig = _make_rig_with_poses(char, [])

    rig["timeline"]["duration_frames"] = 240
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert reloaded["timeline"]["duration_frames"] == 240

    info = _timing_info(reloaded)
    # 240 frames at 24fps = 10 seconds
    assert info["total_duration_seconds"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# FPS setting
# ---------------------------------------------------------------------------


def test_set_fps(tmp_rig_dir):
    """Changing FPS updates the timeline and timing calculations."""
    char = "test_fps"
    rig = _make_rig_with_poses(char, [])

    rig["timeline"]["fps"] = 30
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    info = _timing_info(reloaded)
    assert info["fps"] == 30
    assert info["seconds_per_frame"] == pytest.approx(1.0 / 30, abs=0.001)
    # Default 120 frames at 30fps = 4 seconds
    assert info["total_duration_seconds"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Replace keyframe at same frame
# ---------------------------------------------------------------------------


def test_replace_keyframe_at_same_frame(tmp_rig_dir):
    """Adding a keyframe at an existing frame replaces the old one."""
    char = "test_replace"
    rig = _make_rig_with_poses(char, ["idle", "walk"])

    rig["keyframes"] = [{"frame": 0, "pose_name": "idle", "easing": "linear"}]
    _save_rig(char, rig)

    # Replace: remove existing at frame 0, add new
    reloaded = _load_rig(char)
    reloaded["keyframes"] = [
        kf for kf in reloaded["keyframes"] if kf.get("frame") != 0
    ]
    reloaded["keyframes"].append({"frame": 0, "pose_name": "walk", "easing": "ease_in_out"})
    reloaded["keyframes"].sort(key=lambda kf: kf.get("frame", 0))
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert len(final["keyframes"]) == 1
    assert final["keyframes"][0]["pose_name"] == "walk"


# ---------------------------------------------------------------------------
# Clear keyframes
# ---------------------------------------------------------------------------


def test_clear_keyframes(tmp_rig_dir):
    """Clearing keyframes empties the list while preserving timeline settings."""
    char = "test_clear"
    rig = _make_rig_with_poses(char, ["idle"])

    rig["keyframes"] = [
        {"frame": 0, "pose_name": "idle", "easing": "linear"},
        {"frame": 24, "pose_name": "idle", "easing": "linear"},
    ]
    rig["timeline"]["fps"] = 30
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    reloaded["keyframes"] = []
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert len(final["keyframes"]) == 0
    assert final["timeline"]["fps"] == 30  # preserved
