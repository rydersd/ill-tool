"""Tests for the EDL / FCP XML export tool.

Verifies timecode format, event count, and XML structure.
All tests are pure Python — no JSX or Adobe required.
"""

import xml.etree.ElementTree as ET

import pytest

from adobe_mcp.apps.illustrator.edl_export import (
    frames_to_timecode,
    generate_edl,
    generate_fcpxml,
    _get_panels,
)


# ---------------------------------------------------------------------------
# Timecode conversion
# ---------------------------------------------------------------------------


def test_timecode_zero():
    """Frame 0 at any FPS produces 00:00:00:00."""
    assert frames_to_timecode(0, 24) == "00:00:00:00"
    assert frames_to_timecode(0, 30) == "00:00:00:00"


def test_timecode_one_second():
    """24 frames at 24fps = exactly 1 second."""
    assert frames_to_timecode(24, 24) == "00:00:01:00"


def test_timecode_complex():
    """90 frames at 24fps = 3 seconds 18 frames."""
    assert frames_to_timecode(90, 24) == "00:00:03:18"


def test_timecode_minutes():
    """1500 frames at 24fps = 1 minute 2 seconds 12 frames."""
    assert frames_to_timecode(1500, 24) == "00:01:02:12"


def test_timecode_zero_fps():
    """Zero FPS returns 00:00:00:00."""
    assert frames_to_timecode(100, 0) == "00:00:00:00"


# ---------------------------------------------------------------------------
# EDL generation
# ---------------------------------------------------------------------------


def test_edl_event_count():
    """EDL has one event per panel."""
    panels = [
        {"number": 1, "duration_frames": 24, "description": "Opening"},
        {"number": 2, "duration_frames": 48, "description": "Dialogue"},
        {"number": 3, "duration_frames": 24, "description": "Close"},
    ]
    edl = generate_edl(panels, "Test", 24)

    # Count event lines (lines starting with digits)
    event_lines = [
        line for line in edl.strip().split("\n")
        if line and line[0].isdigit()
    ]
    assert len(event_lines) == 3


def test_edl_header():
    """EDL starts with TITLE and FCM header lines."""
    panels = [{"number": 1, "duration_frames": 24, "description": "Test"}]
    edl = generate_edl(panels, "My Project", 24)
    lines = edl.split("\n")
    assert lines[0] == "TITLE: My Project"
    assert lines[1] == "FCM: NON-DROP FRAME"


def test_edl_record_timecodes_are_cumulative():
    """Record IN/OUT timecodes accumulate across events."""
    panels = [
        {"number": 1, "duration_frames": 24},
        {"number": 2, "duration_frames": 48},
    ]
    edl = generate_edl(panels, "Test", 24)

    event_lines = [
        line for line in edl.strip().split("\n")
        if line and line[0].isdigit()
    ]
    # First event: rec_in = 00:00:00:00, rec_out = 00:00:01:00
    assert "00:00:00:00" in event_lines[0]
    assert "00:00:01:00" in event_lines[0]

    # Second event: rec_in = 00:00:01:00, rec_out = 00:00:03:00
    assert "00:00:01:00" in event_lines[1]
    assert "00:00:03:00" in event_lines[1]


# ---------------------------------------------------------------------------
# FCP XML generation
# ---------------------------------------------------------------------------


def test_fcpxml_valid_xml():
    """Generated FCP XML is valid XML."""
    panels = [
        {"number": 1, "duration_frames": 24, "description": "Shot 1"},
        {"number": 2, "duration_frames": 48, "description": "Shot 2"},
    ]
    xml_str = generate_fcpxml(panels, "Test", 24)
    root = ET.fromstring(xml_str)
    assert root.tag == "xmeml"


def test_fcpxml_clip_count():
    """FCP XML contains one clipitem per panel."""
    panels = [
        {"number": 1, "duration_frames": 24, "description": "A"},
        {"number": 2, "duration_frames": 48, "description": "B"},
        {"number": 3, "duration_frames": 24, "description": "C"},
    ]
    xml_str = generate_fcpxml(panels, "Test", 24)
    root = ET.fromstring(xml_str)

    clips = root.findall(".//clipitem")
    assert len(clips) == 3


def test_fcpxml_sequence_duration():
    """FCP XML sequence duration equals sum of panel durations."""
    panels = [
        {"number": 1, "duration_frames": 24},
        {"number": 2, "duration_frames": 48},
    ]
    xml_str = generate_fcpxml(panels, "Test", 24)
    root = ET.fromstring(xml_str)

    duration = root.find(".//sequence/duration")
    assert duration is not None
    assert int(duration.text) == 72  # 24 + 48


def test_fcpxml_timebase():
    """FCP XML includes the correct timebase (FPS)."""
    panels = [{"number": 1, "duration_frames": 30}]
    xml_str = generate_fcpxml(panels, "Test", 30)
    root = ET.fromstring(xml_str)

    timebase = root.find(".//sequence/rate/timebase")
    assert timebase is not None
    assert int(timebase.text) == 30
