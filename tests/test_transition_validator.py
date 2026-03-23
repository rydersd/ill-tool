"""Tests for spatial continuity validation between panels.

Verifies consistent direction passes, 180-degree violation is flagged,
and scale jump is flagged.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.transition_validator import (
    validate_transition,
    validate_sequence,
)


# ---------------------------------------------------------------------------
# Consistent direction -> valid
# ---------------------------------------------------------------------------


def test_consistent_direction_valid():
    """Panels with consistent movement direction pass validation."""
    panel_a = {
        "movement_direction": "right",
        "camera_scale": "wide",
        "subject": "hero",
        "characters": [
            {"name": "hero", "screen_x": 200, "facing": "right"},
            {"name": "villain", "screen_x": 600, "facing": "left"},
        ],
    }
    panel_b = {
        "movement_direction": "right",
        "camera_scale": "close_up",
        "subject": "hero",
        "characters": [
            {"name": "hero", "screen_x": 300, "facing": "right"},
            {"name": "villain", "screen_x": 700, "facing": "left"},
        ],
    }

    result = validate_transition(panel_a, panel_b)
    assert result["valid"] is True
    assert len(result["issues"]) == 0


# ---------------------------------------------------------------------------
# 180-degree violation -> flagged
# ---------------------------------------------------------------------------


def test_180_degree_violation_flagged():
    """Swapping character positions between panels flags a 180-degree violation."""
    panel_a = {
        "characters": [
            {"name": "Alice", "screen_x": 200},
            {"name": "Bob", "screen_x": 600},
        ],
    }
    panel_b = {
        "characters": [
            {"name": "Alice", "screen_x": 700},  # swapped!
            {"name": "Bob", "screen_x": 100},     # swapped!
        ],
    }

    result = validate_transition(panel_a, panel_b)
    assert result["valid"] is False

    rules_found = [issue["rule"] for issue in result["issues"]]
    assert "180_degree" in rules_found, "Should flag 180-degree rule violation"


# ---------------------------------------------------------------------------
# Scale jump -> flagged
# ---------------------------------------------------------------------------


def test_scale_jump_flagged():
    """Small scale jump between different subjects is flagged as jarring."""
    panel_a = {
        "camera_scale": "medium",
        "subject": "hero",
    }
    panel_b = {
        "camera_scale": "medium_close",
        "subject": "sidekick",  # different subject!
    }

    result = validate_transition(panel_a, panel_b)
    assert result["valid"] is False

    rules_found = [issue["rule"] for issue in result["issues"]]
    assert "scale_jump" in rules_found, "Should flag jarring scale jump"
