"""Tests for the character turnaround view system.

Tests view transforms, spacing calculations, and view parsing.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.character_turnaround import (
    VIEW_TRANSFORMS,
    _get_view_transform,
    _parse_views,
    _calculate_view_positions,
    _total_width,
)


# ---------------------------------------------------------------------------
# VIEW_TRANSFORMS
# ---------------------------------------------------------------------------


def test_front_transform():
    """Front view has no scaling or mirroring."""
    t = VIEW_TRANSFORMS["front"]
    assert t["scale_x"] == 1.0
    assert t["mirror"] is False


def test_side_transform():
    """Side view scales X by 0.6 (flatten profile)."""
    t = VIEW_TRANSFORMS["side"]
    assert t["scale_x"] == pytest.approx(0.6)
    assert t["mirror"] is False


def test_three_quarter_transform():
    """3/4 view scales X by 0.85 (slight perspective)."""
    t = VIEW_TRANSFORMS["3-4"]
    assert t["scale_x"] == pytest.approx(0.85)
    assert t["mirror"] is False


def test_back_transform():
    """Back view mirrors horizontally (scale_x=1.0, mirror=True)."""
    t = VIEW_TRANSFORMS["back"]
    assert t["scale_x"] == 1.0
    assert t["mirror"] is True


def test_all_views_have_labels():
    """All view transforms include a label string."""
    for name, t in VIEW_TRANSFORMS.items():
        assert "label" in t, f"View '{name}' missing label"
        assert isinstance(t["label"], str)
        assert len(t["label"]) > 0


# ---------------------------------------------------------------------------
# _get_view_transform
# ---------------------------------------------------------------------------


def test_get_view_transform_known():
    """Known view names return correct transforms."""
    assert _get_view_transform("front")["scale_x"] == 1.0
    assert _get_view_transform("side")["scale_x"] == 0.6
    assert _get_view_transform("3-4")["scale_x"] == 0.85
    assert _get_view_transform("back")["mirror"] is True


def test_get_view_transform_case_insensitive():
    """View name matching is case-insensitive."""
    assert _get_view_transform("FRONT")["scale_x"] == 1.0
    assert _get_view_transform("Side")["scale_x"] == 0.6


def test_get_view_transform_whitespace():
    """Whitespace around view name is stripped."""
    assert _get_view_transform("  side  ")["scale_x"] == 0.6


def test_get_view_transform_unknown_defaults_to_front():
    """Unknown view name returns front transform (no transform)."""
    t = _get_view_transform("isometric")
    assert t["scale_x"] == 1.0
    assert t["mirror"] is False


# ---------------------------------------------------------------------------
# _parse_views
# ---------------------------------------------------------------------------


def test_parse_views_standard():
    """Standard comma-separated views are parsed correctly."""
    views = _parse_views("front,3-4,side,back")
    assert views == ["front", "3-4", "side", "back"]


def test_parse_views_subset():
    """Subset of views can be specified."""
    views = _parse_views("front,back")
    assert views == ["front", "back"]


def test_parse_views_single():
    """Single view is parsed correctly."""
    views = _parse_views("side")
    assert views == ["side"]


def test_parse_views_with_whitespace():
    """Whitespace around view names is handled."""
    views = _parse_views("  front , side , back  ")
    assert views == ["front", "side", "back"]


def test_parse_views_case_insensitive():
    """View names are lowercased during parsing."""
    views = _parse_views("FRONT,SIDE")
    assert views == ["front", "side"]


def test_parse_views_invalid_skipped():
    """Invalid view names are silently skipped."""
    views = _parse_views("front,invalid,side")
    assert views == ["front", "side"]


def test_parse_views_all_invalid():
    """All-invalid input returns empty list."""
    views = _parse_views("foo,bar,baz")
    assert views == []


def test_parse_views_empty_string():
    """Empty string returns empty list."""
    views = _parse_views("")
    assert views == []


def test_parse_views_preserves_order():
    """Views are returned in the order specified."""
    views = _parse_views("back,front,3-4,side")
    assert views == ["back", "front", "3-4", "side"]


# ---------------------------------------------------------------------------
# _calculate_view_positions
# ---------------------------------------------------------------------------


def test_calculate_positions_basic():
    """Basic position calculation with 4 views."""
    views = ["front", "3-4", "side", "back"]
    positions = _calculate_view_positions(views, spacing=100, char_width=200)

    assert len(positions) == 4

    # First view starts at x=0
    assert positions[0]["x_offset"] == pytest.approx(0)
    assert positions[0]["view"] == "front"
    assert positions[0]["scale_x"] == 1.0

    # Second view at char_width + spacing = 300
    assert positions[1]["x_offset"] == pytest.approx(300)
    assert positions[1]["view"] == "3-4"
    assert positions[1]["scale_x"] == 0.85

    # Third view at 2 * 300 = 600
    assert positions[2]["x_offset"] == pytest.approx(600)
    assert positions[2]["view"] == "side"
    assert positions[2]["scale_x"] == 0.6

    # Fourth view at 3 * 300 = 900
    assert positions[3]["x_offset"] == pytest.approx(900)
    assert positions[3]["view"] == "back"
    assert positions[3]["mirror"] is True


def test_calculate_positions_includes_labels():
    """Each position includes the view label."""
    positions = _calculate_view_positions(["front", "side"], spacing=50, char_width=100)
    assert positions[0]["label"] == "FRONT"
    assert positions[1]["label"] == "SIDE"


def test_calculate_positions_single_view():
    """Single view starts at x=0."""
    positions = _calculate_view_positions(["front"], spacing=100, char_width=200)
    assert len(positions) == 1
    assert positions[0]["x_offset"] == 0


def test_calculate_positions_spacing_affects_offset():
    """Larger spacing increases the distance between views."""
    pos_small = _calculate_view_positions(["front", "side"], spacing=50, char_width=100)
    pos_large = _calculate_view_positions(["front", "side"], spacing=200, char_width=100)

    assert pos_large[1]["x_offset"] > pos_small[1]["x_offset"]


# ---------------------------------------------------------------------------
# _total_width
# ---------------------------------------------------------------------------


def test_total_width_basic():
    """Total width for 4 views with 100pt spacing and 200pt char width."""
    width = _total_width(["front", "3-4", "side", "back"], spacing=100, char_width=200)
    # 4 * 200 + 3 * 100 = 1100
    assert width == pytest.approx(1100)


def test_total_width_single_view():
    """Single view: total width equals char_width (no spacing)."""
    width = _total_width(["front"], spacing=100, char_width=200)
    assert width == pytest.approx(200)


def test_total_width_two_views():
    """Two views: char_width * 2 + spacing * 1."""
    width = _total_width(["front", "back"], spacing=50, char_width=150)
    assert width == pytest.approx(350)


def test_total_width_empty():
    """Empty views list: total width is 0."""
    assert _total_width([], spacing=100, char_width=200) == 0


def test_total_width_zero_spacing():
    """Zero spacing: views are adjacent."""
    width = _total_width(["front", "side", "back"], spacing=0, char_width=100)
    assert width == pytest.approx(300)
