"""Tests for AE camera expression generators.

Verifies shake expression contains wiggle, zoom uses linear interpolation,
and pan has correct start/end positions.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.camera_expressions import (
    generate_shake_expression,
    generate_zoom_expression,
    generate_pan_expression,
    generate_dolly_zoom,
)


# ---------------------------------------------------------------------------
# Shake expression contains wiggle
# ---------------------------------------------------------------------------


def test_shake_expression_contains_wiggle():
    """Shake expression uses AE wiggle function with decay."""
    expr = generate_shake_expression(amplitude=10, frequency=5, decay=0.9)

    assert "wiggle" in expr, "Shake expression must use wiggle()"
    assert "10" in expr, "Amplitude value should appear in expression"
    assert "5" in expr, "Frequency value should appear in expression"
    assert "0.9" in expr, "Decay value should appear in expression"
    assert "Math.pow" in expr or "pow" in expr, "Decay should use pow()"


# ---------------------------------------------------------------------------
# Zoom has linear interpolation
# ---------------------------------------------------------------------------


def test_zoom_expression_has_linear():
    """Zoom expression uses AE linear() for smooth interpolation."""
    expr = generate_zoom_expression(start_scale=100, end_scale=200, duration_sec=3)

    assert "linear" in expr, "Zoom expression must use linear()"
    assert "100" in expr, "Start scale should appear in expression"
    assert "200" in expr, "End scale should appear in expression"
    assert "3" in expr, "Duration should appear in expression"


# ---------------------------------------------------------------------------
# Pan has correct start/end
# ---------------------------------------------------------------------------


def test_pan_expression_has_start_end():
    """Pan expression references the correct start and end positions."""
    start = [100, 200]
    end = [900, 500]
    expr = generate_pan_expression(start_pos=start, end_pos=end, duration_sec=2)

    assert "100" in expr, "Start x should appear"
    assert "200" in expr, "Start y should appear"
    assert "900" in expr, "End x should appear"
    assert "500" in expr, "End y should appear"
    assert "linear" in expr, "Pan should use linear interpolation"
    assert "[x, y]" in expr or "[x,y]" in expr.replace(" ", ""), "Should return [x, y] array"
