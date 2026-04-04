"""Tests for speech bubble layout relative to characters.

Verifies single bubble positioning, two-speaker alternation,
and panel bounds clamping.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard.dialogue_layout import (
    compute_bubble_position,
    layout_dialogue,
)


# ---------------------------------------------------------------------------
# Single bubble position
# ---------------------------------------------------------------------------


def test_single_bubble_above_and_to_side():
    """A single bubble is placed above the character and to the requested side."""
    char_bounds = [100, 100, 80, 200]  # x, y, w, h
    result = compute_bubble_position(char_bounds, speaker_side="right")

    bx, by, bw, bh = result["bubble_rect"]

    # Bubble should be above the character (lower y value)
    assert by < char_bounds[1], "Bubble should be above the character"

    # Bubble should be to the right of the character
    assert bx > char_bounds[0] + char_bounds[2], "Bubble should be right of character"

    # Tail point should be near character's head area
    tail_x, tail_y = result["tail_point"]
    assert tail_y == char_bounds[1], "Tail points to top of character (head area)"

    # Tail base should have 4 coordinates
    assert len(result["tail_base"]) == 4


# ---------------------------------------------------------------------------
# Two speakers alternate sides
# ---------------------------------------------------------------------------


def test_two_speakers_alternate_sides():
    """Two speakers get bubbles on alternating sides (right, left)."""
    speakers = [
        {"bounds": [50, 100, 60, 180], "lines": ["Hello!"]},
        {"bounds": [300, 100, 60, 180], "lines": ["Hi there!"]},
    ]
    lines = [["Hello!"], ["Hi there!"]]
    panel_bounds = [0, 0, 960, 540]

    bubbles = layout_dialogue(speakers, lines, panel_bounds)

    assert len(bubbles) == 2

    # Sorted by x position (left-to-right): first speaker gets "right", second gets "left"
    sides = [b["side"] for b in bubbles]
    assert sides == ["right", "left"], f"Expected alternating sides, got {sides}"


# ---------------------------------------------------------------------------
# Stays within panel bounds
# ---------------------------------------------------------------------------


def test_bubble_clamped_to_panel_bounds():
    """A bubble near the panel edge is clamped to stay within bounds."""
    # Character at far right edge of a small panel
    char_bounds = [880, 50, 60, 150]
    panel_bounds = [0, 0, 960, 540]

    result = compute_bubble_position(
        char_bounds,
        speaker_side="right",
        panel_bounds=panel_bounds,
        bubble_width=140,
    )

    bx, by, bw, bh = result["bubble_rect"]

    # Bubble must not exceed panel right edge
    assert bx + bw <= panel_bounds[0] + panel_bounds[2], (
        f"Bubble right edge {bx + bw} exceeds panel right {panel_bounds[0] + panel_bounds[2]}"
    )

    # Bubble must not go above panel top
    assert by >= panel_bounds[1], (
        f"Bubble top {by} is above panel top {panel_bounds[1]}"
    )
