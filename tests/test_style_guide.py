"""Tests for the style guide enforcement tool.

Verifies style definition, conformance checking, violation detection,
and save/load persistence.
All tests are pure Python -- no JSX or Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.style_guide import (
    define_style,
    check_style,
    save_style,
    load_style,
    list_styles,
    _styles,
)


# ---------------------------------------------------------------------------
# Cleanup fixture to reset styles between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_styles():
    """Clear defined styles before each test."""
    _styles.clear()
    yield
    _styles.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_define_and_check_conforming_character():
    """A character that conforms to style rules should pass with no violations."""
    define_style("cartoon", {
        "max_parts": 20,
        "min_parts": 2,
        "allowed_joint_types": ["hinge", "ball", "fixed"],
    })

    # Create a conforming rig
    rig = {
        "character_name": "good_char",
        "joints": {
            "hip": {"position": [100, 200]},
            "knee_l": {"position": [80, 300]},
            "knee_r": {"position": [120, 300]},
        },
        "landmarks": {
            "shoulder": {"position": [100, 100], "pivot": {"type": "ball"}},
        },
    }

    result = check_style(rig, "cartoon")
    assert result["passed"] is True
    assert result["violation_count"] == 0


def test_non_conforming_reports_violations():
    """A character that violates rules should report violations."""
    define_style("strict", {
        "max_parts": 2,
        "allowed_joint_types": ["hinge"],
    })

    # Create a non-conforming rig (too many parts, wrong joint type)
    rig = {
        "character_name": "bad_char",
        "joints": {
            "hip": {"position": [100, 200]},
            "knee_l": {"position": [80, 300]},
            "knee_r": {"position": [120, 300]},
        },
        "landmarks": {
            "shoulder": {"position": [100, 100], "pivot": {"type": "ball"}},
        },
    }

    result = check_style(rig, "strict")
    assert result["passed"] is False
    assert result["violation_count"] > 0

    # Should have max_parts violation (3 joints > max 2)
    rules_violated = [v["rule"] for v in result["violations"]]
    assert "max_parts" in rules_violated
    # Should have allowed_joint_types violation ("ball" not in ["hinge"])
    assert "allowed_joint_types" in rules_violated


def test_save_load_style_roundtrip(tmp_path):
    """save_style then load_style should restore the same style."""
    define_style("my_style", {
        "stroke_weight_range": [1.0, 4.0],
        "colors": ["#8bc153", "#bedc87", "#000000"],
        "line_cap": "round",
    })

    save_path = str(tmp_path / "style.json")
    save_result = save_style("my_style", save_path)
    assert save_result["saved"] == save_path
    assert os.path.isfile(save_path)

    # Clear and reload
    _styles.clear()
    assert "my_style" not in _styles

    load_result = load_style(save_path)
    assert load_result["loaded"] == "my_style"
    assert load_result["rules_count"] == 3

    # Should be available for checking after load
    styles = list_styles()
    assert "my_style" in styles["styles"]
