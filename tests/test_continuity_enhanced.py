"""Tests for the enhanced continuity tracker.

Verifies scale deviation calculation, eyeline consistency check,
and props checking. All tests are pure Python.
"""

import pytest

from adobe_mcp.apps.illustrator.production.continuity_enhanced import (
    check_scale,
    check_eyeline,
    check_props,
    full_report,
    _get_bounding_box,
)


# ---------------------------------------------------------------------------
# Helper to build panel data
# ---------------------------------------------------------------------------


def _make_panel(number, bbox_w, bbox_h, eye_y=None, props=None):
    """Build a panel dict with character_snapshot for testing."""
    snapshot = {
        "bounding_box": {"width": bbox_w, "height": bbox_h},
    }
    if eye_y is not None:
        snapshot["landmarks"] = {"eye_center": {"y": eye_y}}
    if props is not None:
        snapshot["props"] = props
    return {
        "number": number,
        "character_snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# check_scale
# ---------------------------------------------------------------------------


def test_scale_pass_within_tolerance():
    """Panels within 15% scale variation pass."""
    panels = [
        _make_panel(1, 100, 200),  # area = 20000
        _make_panel(2, 105, 200),  # area = 21000 (5% increase)
    ]
    result = check_scale(panels, tolerance_pct=15.0)
    assert result["status"] == "pass"
    assert result["issue_count"] == 0


def test_scale_fail_exceeds_tolerance():
    """Panels exceeding 15% scale variation fail."""
    panels = [
        _make_panel(1, 100, 200),  # area = 20000
        _make_panel(2, 80, 150),   # area = 12000 (40% decrease)
    ]
    result = check_scale(panels, tolerance_pct=15.0)
    assert result["status"] == "fail"
    assert result["issue_count"] == 1
    assert result["issues"][0]["panel"] == 2
    assert result["issues"][0]["deviation_pct"] > 15.0


def test_scale_skipped_with_single_panel():
    """Scale check is skipped with fewer than 2 panels."""
    panels = [_make_panel(1, 100, 200)]
    result = check_scale(panels, tolerance_pct=15.0)
    assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# check_eyeline
# ---------------------------------------------------------------------------


def test_eyeline_consistent():
    """Consistent eye positions across panels pass."""
    panels = [
        _make_panel(1, 100, 200, eye_y=50.0),
        _make_panel(2, 100, 200, eye_y=52.0),  # 4% deviation
    ]
    result = check_eyeline(panels, tolerance_pct=10.0)
    assert result["status"] == "pass"
    assert result["issue_count"] == 0


def test_eyeline_inconsistent():
    """Large eyeline variation is flagged."""
    panels = [
        _make_panel(1, 100, 200, eye_y=50.0),
        _make_panel(2, 100, 200, eye_y=70.0),  # 40% deviation
    ]
    result = check_eyeline(panels, tolerance_pct=10.0)
    assert result["status"] == "fail"
    assert result["issue_count"] == 1
    assert result["issues"][0]["panel"] == 2
