"""Tests for the storyboard from script parser.

Verifies script parsing, panel counting, timing estimates, dialogue
detection, and camera tag extraction.
All tests are pure Python -- no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard_from_script import (
    parse_script,
    generate_panel_specs,
    count_panels,
    DURATION_ACTION,
    DURATION_DIALOGUE,
    DURATION_ESTABLISHING,
)


# ---------------------------------------------------------------------------
# Sample scripts
# ---------------------------------------------------------------------------

SIMPLE_SCRIPT = """
SCENE 1: INT. KITCHEN - DAY
- GIR stands on table [wide]
- GIR: "I'm gonna sing the doom song!" [medium]
- Close on GIR's face, eyes glowing [close_up]

SCENE 2: EXT. YARD - NIGHT
- Wide establishing shot [wide]
- ZIM runs across yard [medium]
"""

DIALOGUE_SCRIPT = """
SCENE 1: INT. LAB - NIGHT
- ZIM: "The plan is brilliant!" [medium]
- GIR: "Tacos!" [close_up]
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_simple_script():
    """parse_script should extract scenes with correct panels."""
    scenes = parse_script(SIMPLE_SCRIPT)

    assert len(scenes) == 2
    assert scenes[0]["scene"] == 1
    assert scenes[0]["location"] == "INT. KITCHEN - DAY"
    assert len(scenes[0]["panels"]) == 3

    # First panel
    assert "GIR stands on table" in scenes[0]["panels"][0]["description"]
    assert scenes[0]["panels"][0]["camera"] == "wide"

    # Second scene
    assert scenes[1]["scene"] == 2
    assert len(scenes[1]["panels"]) == 2


def test_count_panels_total():
    """count_panels should return correct total across scenes."""
    result = count_panels(SIMPLE_SCRIPT)

    assert result["total_panels"] == 5
    assert result["scenes"] == 2
    assert len(result["per_scene"]) == 2
    assert result["per_scene"][0]["panels"] == 3
    assert result["per_scene"][1]["panels"] == 2


def test_timing_estimates_by_type():
    """generate_panel_specs should assign correct durations by panel type."""
    scenes = parse_script(SIMPLE_SCRIPT)
    specs = generate_panel_specs(scenes, fps=24)

    # Panel 1 is action (GIR stands) -> DURATION_ACTION
    action_panels = [s for s in specs if s["panel_type"] == "action"]
    for ap in action_panels:
        assert ap["duration_frames"] == DURATION_ACTION

    # Dialogue panels -> DURATION_DIALOGUE
    dialogue_panels = [s for s in specs if s["panel_type"] == "dialogue"]
    for dp in dialogue_panels:
        assert dp["duration_frames"] == DURATION_DIALOGUE

    # Establishing panels -> DURATION_ESTABLISHING
    establishing_panels = [s for s in specs if s["panel_type"] == "establishing"]
    for ep in establishing_panels:
        assert ep["duration_frames"] == DURATION_ESTABLISHING


def test_dialogue_detection():
    """Parser should detect character names and dialogue text."""
    scenes = parse_script(DIALOGUE_SCRIPT)
    panels = scenes[0]["panels"]

    # First panel has ZIM dialogue
    assert panels[0]["character"] == "ZIM"
    assert panels[0]["dialogue"] == "The plan is brilliant!"

    # Second panel has GIR dialogue
    assert panels[1]["character"] == "GIR"
    assert panels[1]["dialogue"] == "Tacos!"


def test_camera_tags_extracted():
    """Camera tags in brackets should be parsed correctly."""
    scenes = parse_script(SIMPLE_SCRIPT)
    cameras = [p["camera"] for p in scenes[0]["panels"]]

    assert cameras[0] == "wide"
    assert cameras[1] == "medium"
    assert cameras[2] == "close_up"
