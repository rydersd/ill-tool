"""Tests for the Sketch2Anim bridge tool.

Verifies panel parsing, animation output validation, and status —
all pure Python, no Adobe or ML service required.
"""

import pytest

from adobe_mcp.apps.illustrator.sketch2anim_bridge import (
    parse_storyboard_for_animation,
    validate_animation_output,
    REQUIRED_ANIMATION_FIELDS,
    REQUIRED_FRAME_FIELDS,
)


# ---------------------------------------------------------------------------
# test_parse_storyboard_for_animation
# ---------------------------------------------------------------------------


class TestParseStoryboardForAnimation:
    """Extract action descriptions and character positions from panel data."""

    def test_basic_panel_parsing(self):
        """Panels with descriptions and characters are parsed correctly."""
        panels = [
            {
                "number": 1,
                "description": "Hero enters the room",
                "camera": "wide",
                "duration_frames": 48,
                "characters": [
                    {"name": "Hero", "position": [100, 200], "scale": 0.8, "facing": "right"},
                ],
            },
            {
                "number": 2,
                "action": "Hero confronts villain",
                "camera": "close",
                "duration_frames": 36,
                "characters": [
                    {"name": "Hero", "position": [300, 200], "facing": "left"},
                    {"name": "Villain", "position": [600, 200], "facing": "right"},
                ],
            },
        ]

        result = parse_storyboard_for_animation(panels)

        assert result["panel_count"] == 2
        assert result["total_duration_frames"] == 84  # 48 + 36
        assert "Hero" in result["unique_characters"]
        assert "Villain" in result["unique_characters"]

        # First panel
        p1 = result["panels"][0]
        assert p1["panel_number"] == 1
        assert p1["action_description"] == "Hero enters the room"
        assert p1["character_count"] == 1
        assert p1["characters"][0]["name"] == "Hero"
        assert p1["camera"] == "wide"

        # Second panel uses 'action' field instead of 'description'
        p2 = result["panels"][1]
        assert p2["action_description"] == "Hero confronts villain"
        assert p2["character_count"] == 2

    def test_empty_panels(self):
        """Empty panel list returns error with empty parsed list."""
        result = parse_storyboard_for_animation([])
        assert "error" in result

    def test_string_character_names(self):
        """Characters specified as simple strings are handled."""
        panels = [
            {
                "number": 1,
                "description": "Group shot",
                "characters": ["Alice", "Bob", "Charlie"],
                "duration_frames": 24,
            },
        ]

        result = parse_storyboard_for_animation(panels)

        assert result["panel_count"] == 1
        p = result["panels"][0]
        assert p["character_count"] == 3
        assert {"Alice", "Bob", "Charlie"} == set(result["unique_characters"])


# ---------------------------------------------------------------------------
# test_validate_animation_output
# ---------------------------------------------------------------------------


class TestValidateAnimationOutput:
    """Check that animation output meets required schema."""

    def test_valid_output(self):
        """Complete animation output passes validation."""
        output = {
            "frames": [
                {"index": 0, "timestamp": 0.0, "data": {}},
                {"index": 1, "timestamp": 0.042, "data": {}},
            ],
            "duration": 2.0,
            "resolution": [1920, 1080],
        }

        result = validate_animation_output(output)
        assert result["valid"] is True
        assert result["frame_count"] == 2
        assert result["duration"] == 2.0

    def test_missing_fields(self):
        """Output missing required top-level fields fails validation."""
        # Missing 'frames' and 'resolution'
        output = {"duration": 1.0}

        result = validate_animation_output(output)
        assert result["valid"] is False
        assert result["error_count"] >= 1
        # Should mention missing fields
        has_missing_error = any("missing" in e.lower() or "Missing" in e for e in result["errors"])
        assert has_missing_error

    def test_empty_frames(self):
        """Output with empty frames list fails validation."""
        output = {
            "frames": [],
            "duration": 1.0,
            "resolution": [1920, 1080],
        }

        result = validate_animation_output(output)
        assert result["valid"] is False
        assert any("empty" in e.lower() for e in result["errors"])

    def test_negative_duration(self):
        """Negative duration fails validation."""
        output = {
            "frames": [{"index": 0, "timestamp": 0.0}],
            "duration": -1.0,
            "resolution": [1920, 1080],
        }

        result = validate_animation_output(output)
        assert result["valid"] is False
        assert any("positive" in e.lower() or "duration" in e.lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# test_status: constants are accessible
# ---------------------------------------------------------------------------


def test_required_fields_constants():
    """Required field sets are non-empty and contain expected fields."""
    assert "frames" in REQUIRED_ANIMATION_FIELDS
    assert "duration" in REQUIRED_ANIMATION_FIELDS
    assert "resolution" in REQUIRED_ANIMATION_FIELDS
    assert "index" in REQUIRED_FRAME_FIELDS
    assert "timestamp" in REQUIRED_FRAME_FIELDS
