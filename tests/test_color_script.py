"""Tests for color script mood detection and palette progression.

Verifies keyword-based mood detection, color arc variety,
and adjacent scene contrast.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.color_script import (
    assign_mood,
    create_color_script,
    generate_color_arc,
    MOOD_PALETTES,
)


# ---------------------------------------------------------------------------
# Mood detection from keywords
# ---------------------------------------------------------------------------


def test_mood_detection_from_keywords():
    """Known keywords map to the correct mood."""
    assert assign_mood("A dark and stormy night") == "tense"
    assert assign_mood("Sunny day at the park with joy") == "happy"
    assert assign_mood("A cold winter ocean") == "cool"
    assert assign_mood("Fog and mystery everywhere") == "mysterious"
    assert assign_mood("A desert sunset with fire") == "warm"
    assert assign_mood("Rain and grief") == "sad"

    # No keywords -> neutral
    assert assign_mood("A regular Tuesday afternoon") == "neutral"
    assert assign_mood("") == "neutral"


# ---------------------------------------------------------------------------
# Color arc has variety
# ---------------------------------------------------------------------------


def test_color_arc_has_variety():
    """Color arc with repeated moods still produces visual variety."""
    moods = ["happy", "happy", "happy"]
    arc = generate_color_arc(moods)

    assert len(arc) == 3

    # Adjacent entries with same mood should flip dominant/accent
    # so dominant colors differ between adjacent entries
    assert arc[0]["dominant"] != arc[1]["dominant"], (
        "Adjacent same-mood entries should have different dominant colors"
    )


# ---------------------------------------------------------------------------
# Adjacent scenes differ
# ---------------------------------------------------------------------------


def test_adjacent_scenes_have_contrast():
    """Adjacent scenes in a color arc have measurable contrast between dominants."""
    moods = ["happy", "tense", "cool", "warm", "sad"]
    arc = generate_color_arc(moods)

    assert len(arc) == 5

    # Every entry after the first should have a contrast_with_previous value
    for i in range(1, len(arc)):
        assert "contrast_with_previous" in arc[i], (
            f"Entry {i} should have contrast_with_previous"
        )
        assert arc[i]["contrast_with_previous"] > 0, (
            f"Entry {i} should have positive contrast with previous"
        )
