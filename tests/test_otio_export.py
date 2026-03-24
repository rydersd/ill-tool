"""Tests for the OpenTimelineIO export tool.

Verifies OTIO dict structure, clip timing, transition mapping,
roundtrip consistency, and empty timeline handling.
All tests are pure Python — no opentimelineio dep required.
"""

import pytest

from adobe_mcp.apps.illustrator.otio_export import (
    otio_clip,
    otio_transition,
    timeline_to_otio_dict,
)


# ---------------------------------------------------------------------------
# Clip dict structure
# ---------------------------------------------------------------------------


def test_otio_clip_structure():
    """Clip dict should have correct OTIO schema and fields."""
    panel = {
        "number": 1,
        "duration_frames": 48,
        "description": "Opening shot",
        "image_path": "panels/panel_001.png",
    }

    clip = otio_clip(panel, fps=24)

    assert clip["OTIO_SCHEMA"] == "Clip.2"
    assert clip["name"] == "Opening shot"
    assert clip["metadata"]["panel_number"] == 1

    # Source range
    sr = clip["source_range"]
    assert sr["OTIO_SCHEMA"] == "TimeRange.1"
    assert sr["start_time"]["value"] == 0.0
    assert sr["start_time"]["rate"] == 24.0
    assert sr["duration"]["value"] == 48.0
    assert sr["duration"]["rate"] == 24.0

    # Media reference
    mr = clip["media_reference"]
    assert mr["OTIO_SCHEMA"] == "ExternalReference.1"
    assert mr["target_url"] == "panels/panel_001.png"


def test_otio_clip_default_values():
    """Clip with minimal panel data uses sensible defaults."""
    clip = otio_clip({}, fps=30)

    assert clip["OTIO_SCHEMA"] == "Clip.2"
    assert clip["name"] == "Panel 1"
    # Default duration is 24 frames
    assert clip["source_range"]["duration"]["value"] == 24.0
    assert clip["source_range"]["duration"]["rate"] == 30.0


# ---------------------------------------------------------------------------
# Transition dict
# ---------------------------------------------------------------------------


def test_otio_transition_dissolve():
    """Dissolve transition should have correct OTIO structure."""
    trans = otio_transition("dissolve", duration_frames=12, fps=24)

    assert trans["OTIO_SCHEMA"] == "Transition.1"
    assert trans["transition_type"] == "SMPTE_Dissolve"
    assert trans["name"] == "dissolve"

    # In/out offsets should split the duration
    assert trans["in_offset"]["value"] == 6.0
    assert trans["out_offset"]["value"] == 6.0
    assert trans["in_offset"]["rate"] == 24.0


def test_otio_transition_wipe():
    """Wipe transition should map to SMPTE_Wipe type."""
    trans = otio_transition("wipe", duration_frames=24, fps=30)
    assert trans["transition_type"] == "SMPTE_Wipe"
    assert trans["metadata"]["total_duration_frames"] == 24


# ---------------------------------------------------------------------------
# Timeline dict
# ---------------------------------------------------------------------------


def test_timeline_structure():
    """Full timeline dict should have correct OTIO schema hierarchy."""
    rig = {
        "storyboard": {
            "panels": [
                {"number": 1, "duration_frames": 24, "description": "Shot A"},
                {"number": 2, "duration_frames": 48, "description": "Shot B"},
            ],
        },
    }

    timeline = timeline_to_otio_dict(rig, title="Test Timeline", fps=24)

    assert timeline["OTIO_SCHEMA"] == "Timeline.1"
    assert timeline["name"] == "Test Timeline"
    assert timeline["global_start_time"]["rate"] == 24.0

    # Stack > Track > Clips
    tracks = timeline["tracks"]
    assert tracks["OTIO_SCHEMA"] == "Stack.1"
    assert len(tracks["children"]) == 1

    track = tracks["children"][0]
    assert track["OTIO_SCHEMA"] == "Track.1"
    assert track["kind"] == "Video"
    assert len(track["children"]) == 2

    # Metadata
    assert timeline["metadata"]["total_duration_frames"] == 72
    assert timeline["metadata"]["panel_count"] == 2


def test_timeline_roundtrip_consistency():
    """Timeline clips should have timing that sums to total duration."""
    panels = [
        {"number": 1, "duration_frames": 30},
        {"number": 2, "duration_frames": 60},
        {"number": 3, "duration_frames": 15},
    ]
    rig = {"storyboard": {"panels": panels}}

    timeline = timeline_to_otio_dict(rig, fps=30)

    # Total duration from metadata should match sum of panel durations
    expected_total = 30 + 60 + 15
    assert timeline["metadata"]["total_duration_frames"] == expected_total

    # Each clip's duration should match its panel
    track_children = timeline["tracks"]["children"][0]["children"]
    clip_durations = [
        c["source_range"]["duration"]["value"]
        for c in track_children
        if c["OTIO_SCHEMA"].startswith("Clip")
    ]
    assert clip_durations == [30.0, 60.0, 15.0]
    assert sum(clip_durations) == expected_total


def test_timeline_empty_panels():
    """Empty storyboard produces a timeline with no clips."""
    rig = {"storyboard": {"panels": []}}

    timeline = timeline_to_otio_dict(rig, fps=24)

    assert timeline["metadata"]["panel_count"] == 0
    assert timeline["metadata"]["total_duration_frames"] == 0

    track = timeline["tracks"]["children"][0]
    assert len(track["children"]) == 0
