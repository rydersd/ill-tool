"""Tests for the animatic_preview tool.

Tests HTML generation structure, timing calculations, and
presence of keyboard controls. Pure Python -- no Adobe needed.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.animatic_preview import (
    _compute_panel_timings,
    _generate_html,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_panels(count: int = 3, fps: int = 24) -> list[dict]:
    """Create panel dicts for testing."""
    panels = []
    for i in range(1, count + 1):
        panels.append({
            "number": i,
            "description": f"Panel {i} description",
            "camera": "medium",
            "duration_frames": 24 * i,  # Panel 1=24f, 2=48f, 3=72f
        })
    return panels


# ---------------------------------------------------------------------------
# Timing calculations
# ---------------------------------------------------------------------------


def test_timing_basic():
    """Panel timings at 24fps: 24 frames = 1000ms."""
    panels = _make_panels(1, fps=24)
    timings = _compute_panel_timings(panels, fps=24)

    assert len(timings) == 1
    t = timings[0]
    assert t["number"] == 1
    assert t["duration_ms"] == 1000
    assert t["start_ms"] == 0
    assert t["end_ms"] == 1000


def test_timing_cumulative():
    """Multiple panels accumulate timing correctly."""
    panels = _make_panels(3, fps=24)
    timings = _compute_panel_timings(panels, fps=24)

    assert len(timings) == 3

    # Panel 1: 24f = 1000ms, starts at 0
    assert timings[0]["start_ms"] == 0
    assert timings[0]["end_ms"] == 1000

    # Panel 2: 48f = 2000ms, starts at 1000
    assert timings[1]["start_ms"] == 1000
    assert timings[1]["end_ms"] == 3000

    # Panel 3: 72f = 3000ms, starts at 3000
    assert timings[2]["start_ms"] == 3000
    assert timings[2]["end_ms"] == 6000


def test_timing_different_fps():
    """Timing at 30fps: 30 frames = 1000ms."""
    panels = [{"number": 1, "description": "A", "camera": "wide", "duration_frames": 30}]
    timings = _compute_panel_timings(panels, fps=30)
    assert timings[0]["duration_ms"] == 1000


# ---------------------------------------------------------------------------
# HTML generation structure
# ---------------------------------------------------------------------------


def test_html_contains_panels_data():
    """Generated HTML embeds panel data as JSON."""
    panels = _make_panels(2)
    timings = _compute_panel_timings(panels, fps=24)

    html = _generate_html(timings, fps=24, auto_play=True,
                          show_timing=True, show_descriptions=True)

    # HTML should contain panel numbers and descriptions
    assert "Panel 1 description" in html
    assert "Panel 2 description" in html
    assert "var panels =" in html


def test_html_contains_keyboard_controls():
    """Generated HTML has Space/Left/Right keyboard event handlers."""
    panels = _make_panels(1)
    timings = _compute_panel_timings(panels, fps=24)

    html = _generate_html(timings, fps=24, auto_play=False,
                          show_timing=True, show_descriptions=True)

    # Check for keyboard event handling
    assert "keydown" in html
    assert "Space" in html
    assert "ArrowLeft" in html
    assert "ArrowRight" in html


def test_html_has_progress_bar():
    """Generated HTML includes a progress bar element."""
    panels = _make_panels(1)
    timings = _compute_panel_timings(panels, fps=24)

    html = _generate_html(timings, fps=24, auto_play=True,
                          show_timing=True, show_descriptions=True)

    assert "progress-bar" in html
    assert "progress-container" in html


def test_html_auto_play_flag():
    """auto_play flag controls initial playback state in JS."""
    panels = _make_panels(1)
    timings = _compute_panel_timings(panels, fps=24)

    html_auto = _generate_html(timings, fps=24, auto_play=True,
                               show_timing=True, show_descriptions=True)
    html_manual = _generate_html(timings, fps=24, auto_play=False,
                                 show_timing=True, show_descriptions=True)

    # The auto-play version should initialize with playing = true
    assert "var playing = true" in html_auto
    assert "var playing = false" in html_manual
