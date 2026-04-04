"""Tests for the staging system tool.

Verifies staging suggestions for known scene types and validates
character position calculations. All tests are pure Python.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard.staging_system import (
    suggest_staging,
    STAGING_FUNCTIONS,
    VALID_SCENE_TYPES,
    PANEL_WIDTH,
    PANEL_HEIGHT,
    _ensure_staging,
)


# ---------------------------------------------------------------------------
# suggest_staging — scene type coverage
# ---------------------------------------------------------------------------


def test_dialogue_staging_returns_cameras():
    """Dialogue staging includes over-shoulder and medium shot cameras."""
    result = suggest_staging("dialogue", num_characters=2)
    assert "error" not in result
    assert result["scene_type"] == "dialogue"
    camera_types = [c["type"] for c in result["suggested_cameras"]]
    assert "medium" in camera_types
    assert "over_shoulder" in camera_types


def test_action_staging_starts_with_wide():
    """Action staging starts with a wide establishing shot."""
    result = suggest_staging("action", num_characters=2)
    assert "error" not in result
    assert result["scene_type"] == "action"
    assert result["suggested_cameras"][0]["type"] == "wide"


def test_establishing_characters_small_scale():
    """Establishing staging uses small character scale (0.4)."""
    result = suggest_staging("establishing", num_characters=3)
    assert "error" not in result
    assert result["scene_type"] == "establishing"
    for pos in result["character_positions"]:
        assert pos["scale"] == pytest.approx(0.4)


def test_confrontation_symmetric_facing():
    """Confrontation staging places characters facing each other."""
    result = suggest_staging("confrontation", num_characters=2)
    assert "error" not in result
    facings = [pos["facing"] for pos in result["character_positions"]]
    assert "right" in facings
    assert "left" in facings


def test_unknown_scene_type_returns_error():
    """Unknown scene type returns an error with valid types list."""
    result = suggest_staging("musical_number", num_characters=1)
    assert "error" in result
    assert "valid_types" in result
    assert set(result["valid_types"]) == VALID_SCENE_TYPES
