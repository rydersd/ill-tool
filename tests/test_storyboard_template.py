"""Tests for the storyboard template layout system.

Tests preset resolution, ratio parsing, and panel dimension calculation.
All tests are pure math — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.storyboard_template import (
    PRESETS,
    _resolve_preset,
    _parse_ratio,
    _calculate_panel_dimensions,
)


# ---------------------------------------------------------------------------
# _resolve_preset
# ---------------------------------------------------------------------------


def test_resolve_standard():
    """Standard preset resolves to 2 columns, 3 rows."""
    cols, rows = _resolve_preset("standard", 1, 1)
    assert cols == 2
    assert rows == 3


def test_resolve_widescreen():
    """Widescreen preset resolves to 2 columns, 2 rows."""
    cols, rows = _resolve_preset("widescreen", 1, 1)
    assert cols == 2
    assert rows == 2


def test_resolve_vertical():
    """Vertical preset resolves to 1 column, 4 rows."""
    cols, rows = _resolve_preset("vertical", 1, 1)
    assert cols == 1
    assert rows == 4


def test_resolve_cinematic():
    """Cinematic preset resolves to 3 columns, 3 rows."""
    cols, rows = _resolve_preset("cinematic", 1, 1)
    assert cols == 3
    assert rows == 3


def test_resolve_custom():
    """Custom preset uses caller-provided columns and rows."""
    cols, rows = _resolve_preset("custom", 4, 5)
    assert cols == 4
    assert rows == 5


def test_resolve_unknown_falls_through():
    """Unknown preset name falls through to custom values."""
    cols, rows = _resolve_preset("nonexistent", 3, 2)
    assert cols == 3
    assert rows == 2


# ---------------------------------------------------------------------------
# _parse_ratio
# ---------------------------------------------------------------------------


def test_parse_ratio_16_9():
    """Parse '16:9' to approximately 1.778."""
    assert _parse_ratio("16:9") == pytest.approx(16 / 9, abs=0.001)


def test_parse_ratio_4_3():
    """Parse '4:3' to approximately 1.333."""
    assert _parse_ratio("4:3") == pytest.approx(4 / 3, abs=0.001)


def test_parse_ratio_1_1():
    """Parse '1:1' to 1.0."""
    assert _parse_ratio("1:1") == pytest.approx(1.0)


def test_parse_ratio_cinematic():
    """Parse '2.39:1' to 2.39."""
    assert _parse_ratio("2.39:1") == pytest.approx(2.39, abs=0.01)


def test_parse_ratio_float_string():
    """Parse plain float string '1.85' to 1.85."""
    assert _parse_ratio("1.85") == pytest.approx(1.85)


def test_parse_ratio_with_whitespace():
    """Whitespace around ratio string is handled."""
    assert _parse_ratio("  16:9  ") == pytest.approx(16 / 9, abs=0.001)


def test_parse_ratio_invalid_falls_back():
    """Invalid ratio string falls back to 16:9."""
    assert _parse_ratio("invalid") == pytest.approx(16 / 9, abs=0.001)


def test_parse_ratio_zero_denominator():
    """Zero denominator in ratio falls back to 1.0."""
    assert _parse_ratio("16:0") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _calculate_panel_dimensions
# ---------------------------------------------------------------------------


def test_panel_dimensions_basic():
    """Basic calculation with standard preset (2x3) on letter landscape."""
    dims = _calculate_panel_dimensions(
        page_width=792,   # 11 inches
        page_height=612,  # 8.5 inches
        margin=36,
        gutter=18,
        columns=2,
        rows=3,
        ratio=16 / 9,
        title_height=0,
        field_height=0,
    )

    assert dims["total_panels"] == 6
    assert dims["fits"] is True
    assert dims["panel_width"] > 0
    assert dims["panel_height"] > 0
    assert len(dims["positions"]) == 6

    # When ratio constrains: panel_width / panel_height == ratio
    # The function picks the smaller of grid-height vs ratio-height,
    # then recalculates width if needed to maintain the ratio.
    initial_width = (792 - 2 * 36 - 18) / 2  # 351
    grid_height = (612 - 2 * 36 - 2 * 18) / 3  # 168
    ratio_height = initial_width / (16 / 9)  # ~197.4

    # Grid height (168) < ratio height (197.4), so height is grid-constrained.
    # Width is recalculated: 168 * (16/9) = ~298.67
    expected_height = grid_height
    expected_width = expected_height * (16 / 9)

    assert dims["panel_height"] == pytest.approx(expected_height, abs=1)
    assert dims["panel_width"] == pytest.approx(expected_width, abs=1)


def test_panel_dimensions_with_title():
    """Title height reduces available vertical space."""
    dims_no_title = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=2, rows=3,
        ratio=16 / 9, title_height=0, field_height=0,
    )

    dims_with_title = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=2, rows=3,
        ratio=16 / 9, title_height=40, field_height=0,
    )

    # With title, either panel height is smaller or width was adjusted
    # The total available vertical space is reduced
    assert dims_with_title["panel_height"] <= dims_no_title["panel_height"]


def test_panel_dimensions_with_fields():
    """Field height per row reduces available panel space."""
    dims_no_fields = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=2, rows=3,
        ratio=16 / 9, title_height=0, field_height=0,
    )

    dims_with_fields = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=2, rows=3,
        ratio=16 / 9, title_height=0, field_height=50,
    )

    assert dims_with_fields["panel_height"] <= dims_no_fields["panel_height"]


def test_panel_dimensions_single_column():
    """Single column (vertical preset) uses full usable width or ratio-limited."""
    dims = _calculate_panel_dimensions(
        page_width=612, page_height=792,
        margin=36, gutter=18, columns=1, rows=4,
        ratio=16 / 9, title_height=0, field_height=0,
    )

    assert dims["total_panels"] == 4
    assert dims["fits"] is True

    # Full usable width: 612 - 2*36 = 540
    # Grid height per row: (792 - 72 - 54) / 4 = 166.5
    # Ratio height from 540 width: 540 / 1.778 = 303.7
    # Grid height (166.5) < ratio height (303.7) → height is grid-constrained
    # Width recalculated: 166.5 * 1.778 = ~296
    grid_height = (792 - 2 * 36 - 3 * 18) / 4
    expected_width = grid_height * (16 / 9)
    assert dims["panel_width"] == pytest.approx(expected_width, abs=1)


def test_panel_dimensions_square_ratio():
    """1:1 ratio produces square panels."""
    dims = _calculate_panel_dimensions(
        page_width=800, page_height=800,
        margin=50, gutter=20, columns=2, rows=2,
        ratio=1.0, title_height=0, field_height=0,
    )

    assert dims["fits"] is True
    # With 1:1 ratio, height should equal width (or be limited by grid)
    # Width: (800 - 100 - 20) / 2 = 340
    expected_width = (800 - 100 - 20) / 2
    ratio_height = expected_width  # 1:1
    grid_height = (800 - 100 - 20) / 2  # 340
    expected_height = min(ratio_height, grid_height)
    assert dims["panel_width"] == pytest.approx(expected_width, abs=1)
    assert dims["panel_height"] == pytest.approx(expected_height, abs=1)


def test_panel_positions_count():
    """Number of positions matches columns * rows."""
    dims = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=3, rows=3,
        ratio=16 / 9, title_height=0, field_height=0,
    )

    assert len(dims["positions"]) == 9
    assert dims["total_panels"] == 9


def test_panel_positions_ordered_left_to_right():
    """Panels are ordered left-to-right, top-to-bottom."""
    dims = _calculate_panel_dimensions(
        page_width=792, page_height=612,
        margin=36, gutter=18, columns=2, rows=2,
        ratio=16 / 9, title_height=0, field_height=0,
    )

    positions = dims["positions"]
    # First row: positions[0] should be left of positions[1]
    assert positions[0][0] < positions[1][0]
    # First column: positions[0] should be above positions[2] (higher Y in AI coords)
    assert positions[0][1] > positions[2][1]


def test_all_presets_fit_letter():
    """All built-in presets produce panels that fit on a letter page."""
    for name, preset in PRESETS.items():
        dims = _calculate_panel_dimensions(
            page_width=792, page_height=612,
            margin=36, gutter=18,
            columns=preset["columns"], rows=preset["rows"],
            ratio=16 / 9, title_height=40, field_height=50,
        )
        assert dims["fits"] is True, f"Preset '{name}' does not fit"
        assert dims["panel_width"] > 0, f"Preset '{name}' has zero width"
        assert dims["panel_height"] > 0, f"Preset '{name}' has zero height"
