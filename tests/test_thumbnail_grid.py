"""Tests for thumbnail grid layout computation.

Tests pure Python compute_grid_layout function.
"""

import pytest

from adobe_mcp.apps.illustrator.ui.thumbnail_grid import compute_grid_layout


# ---------------------------------------------------------------------------
# Panel count
# ---------------------------------------------------------------------------


def test_panel_count_4x3():
    """4 columns x 3 rows = 12 panels."""
    layout = compute_grid_layout(columns=4, rows=3, panel_width=150, panel_height=85, gap=10, margin=20)
    assert layout["panel_count"] == 12


def test_panel_count_3x2():
    """3 columns x 2 rows = 6 panels."""
    layout = compute_grid_layout(columns=3, rows=2, panel_width=150, panel_height=85, gap=10, margin=20)
    assert layout["panel_count"] == 6


# ---------------------------------------------------------------------------
# Artboard dimensions
# ---------------------------------------------------------------------------


def test_artboard_width():
    """Artboard width = columns * panel_width + (columns-1) * gap + 2 * margin."""
    layout = compute_grid_layout(columns=4, rows=3, panel_width=150, panel_height=85, gap=10, margin=20)
    expected_w = 4 * 150 + 3 * 10 + 2 * 20  # 600 + 30 + 40 = 670
    assert layout["artboard_width"] == pytest.approx(expected_w)


def test_artboard_height():
    """Artboard height = rows * panel_height + (rows-1) * gap + 2 * margin."""
    layout = compute_grid_layout(columns=4, rows=3, panel_width=150, panel_height=85, gap=10, margin=20)
    expected_h = 3 * 85 + 2 * 10 + 2 * 20  # 255 + 20 + 40 = 315
    assert layout["artboard_height"] == pytest.approx(expected_h)


# ---------------------------------------------------------------------------
# Panel positions
# ---------------------------------------------------------------------------


def test_first_panel_at_margin():
    """First panel should be positioned at (margin, margin)."""
    layout = compute_grid_layout(columns=4, rows=3, panel_width=150, panel_height=85, gap=10, margin=20)
    first = layout["panels"][0]
    assert first["x"] == pytest.approx(20.0)
    assert first["y"] == pytest.approx(20.0)
    assert first["index"] == 1


def test_second_column_offset():
    """Second column panel should be offset by panel_width + gap."""
    layout = compute_grid_layout(columns=4, rows=3, panel_width=150, panel_height=85, gap=10, margin=20)
    second = layout["panels"][1]
    assert second["x"] == pytest.approx(20.0 + 150 + 10)  # margin + panel_width + gap = 180
    assert second["y"] == pytest.approx(20.0)
    assert second["col"] == 1
    assert second["row"] == 0
