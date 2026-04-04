"""Tests for the continuity_check tool.

Tests pure-Python comparison logic with mock data:
- Color comparison (same = pass, different = fail)
- Proportion comparison (within/outside tolerance)
- Costume element checking (present/missing)
- Full continuity check pipeline
"""

import json

import pytest

from adobe_mcp.apps.illustrator.production.continuity_check import (
    _compare_colors,
    _compare_proportions,
    _check_costume_elements,
    _run_continuity_check,
    COLOR_TOLERANCE,
    PROPORTION_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Color comparison
# ---------------------------------------------------------------------------


def test_compare_colors_exact_match():
    """Identical colors should match."""
    a = {"r": 200, "g": 100, "b": 50}
    b = {"r": 200, "g": 100, "b": 50}
    result = _compare_colors(a, b)
    assert result["match"] is True


def test_compare_colors_within_tolerance():
    """Colors within tolerance should match."""
    a = {"r": 200, "g": 100, "b": 50}
    b = {"r": 205, "g": 95, "b": 55}
    result = _compare_colors(a, b)
    # Each channel diff is 5, which is within COLOR_TOLERANCE (10)
    assert result["match"] is True


def test_compare_colors_outside_tolerance():
    """Colors with channel diff > tolerance should fail."""
    a = {"r": 200, "g": 100, "b": 50}
    b = {"r": 200, "g": 50, "b": 50}  # green diff = 50
    result = _compare_colors(a, b)
    assert result["match"] is False
    assert "channel_diffs" in result
    assert "g" in result["channel_diffs"]


def test_compare_colors_one_none():
    """One filled and one unfilled should fail."""
    result = _compare_colors({"r": 200, "g": 100, "b": 50}, None)
    assert result["match"] is False


# ---------------------------------------------------------------------------
# Proportion comparison
# ---------------------------------------------------------------------------


def test_compare_proportions_matching():
    """Same proportions should pass."""
    a = {"head": {"width": 50, "height": 60}, "torso": {"width": 80, "height": 120}}
    b = {"head": {"width": 52, "height": 62}, "torso": {"width": 82, "height": 122}}
    result = _compare_proportions(a, b)
    assert result["match"] is True


def test_compare_proportions_mismatch():
    """Proportions outside tolerance should fail with details."""
    a = {"head": {"width": 50, "height": 60}}
    b = {"head": {"width": 50, "height": 100}}  # height ratio = 100/60 = 1.67
    result = _compare_proportions(a, b)
    assert result["match"] is False
    assert "mismatches" in result
    # Should flag the height mismatch
    dims = [m["dimension"] for m in result["mismatches"]]
    assert "height" in dims


# ---------------------------------------------------------------------------
# Costume elements
# ---------------------------------------------------------------------------


def test_costume_all_present():
    """All expected elements present should pass."""
    expected = ["hat", "cape", "boots"]
    actual = ["hat", "cape", "boots", "gloves"]
    result = _check_costume_elements(expected, actual)
    assert result["match"] is True
    # Extra elements are noted but not a failure
    assert "gloves" in result.get("extra", [])


def test_costume_missing_elements():
    """Missing expected elements should fail."""
    expected = ["hat", "cape", "boots"]
    actual = ["hat"]
    result = _check_costume_elements(expected, actual)
    assert result["match"] is False
    assert "cape" in result["missing"]
    assert "boots" in result["missing"]


# ---------------------------------------------------------------------------
# Full continuity check pipeline
# ---------------------------------------------------------------------------


def test_full_check_with_consistent_panels():
    """Full check across panels with consistent data should pass."""
    rig = {
        "storyboard": {
            "panels": [
                {
                    "number": 1,
                    "character_snapshot": {
                        "colors": {"skin": {"r": 200, "g": 180, "b": 160}},
                        "proportions": {"head": {"width": 50, "height": 60}},
                        "costume_elements": ["hat", "cape"],
                    },
                },
                {
                    "number": 2,
                    "character_snapshot": {
                        "colors": {"skin": {"r": 202, "g": 178, "b": 162}},
                        "proportions": {"head": {"width": 51, "height": 61}},
                        "costume_elements": ["hat", "cape"],
                    },
                },
            ],
        },
    }
    result = _run_continuity_check(rig, "full")
    assert result["status"] == "completed"
    assert result["issue_count"] == 0


def test_full_check_with_inconsistent_colors():
    """Full check should flag color inconsistencies."""
    rig = {
        "storyboard": {
            "panels": [
                {
                    "number": 1,
                    "character_snapshot": {
                        "colors": {"skin": {"r": 200, "g": 180, "b": 160}},
                        "proportions": {},
                        "costume_elements": [],
                    },
                },
                {
                    "number": 2,
                    "character_snapshot": {
                        "colors": {"skin": {"r": 100, "g": 180, "b": 160}},
                        "proportions": {},
                        "costume_elements": [],
                    },
                },
            ],
        },
    }
    result = _run_continuity_check(rig, "full")
    assert result["status"] == "completed"
    assert result["issue_count"] > 0
    assert 2 in result["panels_with_issues"]
