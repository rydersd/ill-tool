"""Tests for the cross-section guides tool.

Verifies ellipse positions along axis and tilt angles.
All tests are pure Python — no JSX or Adobe required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.cross_section import (
    compute_ellipse_params,
    compute_all_cross_sections,
)


# ---------------------------------------------------------------------------
# Single ellipse computation
# ---------------------------------------------------------------------------


def test_ellipse_at_axis_start():
    """Ellipse at position_frac=0 is at the axis origin."""
    params = compute_ellipse_params(
        axis_origin=[100.0, -200.0],
        axis_angle_rad=0.0,  # horizontal axis
        axis_length=200.0,
        position_frac=0.0,
        cross_width=40.0,
        taper=0.0,
        foreshorten=1.0,
    )
    assert params["center"] == [100.0, -200.0]
    assert params["width"] == pytest.approx(40.0)


def test_ellipse_at_axis_end():
    """Ellipse at position_frac=1.0 is at the axis endpoint."""
    params = compute_ellipse_params(
        axis_origin=[0.0, 0.0],
        axis_angle_rad=0.0,  # horizontal axis
        axis_length=200.0,
        position_frac=1.0,
        cross_width=40.0,
        taper=0.0,
        foreshorten=1.0,
    )
    assert params["center"][0] == pytest.approx(200.0)
    assert params["center"][1] == pytest.approx(0.0)


def test_ellipse_taper_reduces_width():
    """Taper factor reduces width at the far end of the axis."""
    params_start = compute_ellipse_params(
        axis_origin=[0.0, 0.0], axis_angle_rad=0.0, axis_length=200.0,
        position_frac=0.0, cross_width=40.0, taper=0.5, foreshorten=1.0,
    )
    params_end = compute_ellipse_params(
        axis_origin=[0.0, 0.0], axis_angle_rad=0.0, axis_length=200.0,
        position_frac=1.0, cross_width=40.0, taper=0.5, foreshorten=1.0,
    )
    # At start: width = 40 * (1 - 0.5*0) = 40
    assert params_start["width"] == pytest.approx(40.0)
    # At end: width = 40 * (1 - 0.5*1) = 20
    assert params_end["width"] == pytest.approx(20.0)


def test_ellipse_foreshorten_reduces_height():
    """Foreshorten factor reduces ellipse height (minor axis)."""
    params = compute_ellipse_params(
        axis_origin=[0.0, 0.0], axis_angle_rad=0.0, axis_length=200.0,
        position_frac=0.5, cross_width=40.0, taper=0.0, foreshorten=0.5,
    )
    assert params["width"] == pytest.approx(40.0)
    assert params["height"] == pytest.approx(20.0)  # 40 * 0.5


# ---------------------------------------------------------------------------
# Multiple cross sections
# ---------------------------------------------------------------------------


def test_all_cross_sections_count():
    """compute_all_cross_sections returns the correct number of sections."""
    sections = compute_all_cross_sections(
        axis_origin=[0.0, 0.0],
        axis_angle_rad=0.0,
        axis_length=200.0,
        num_sections=5,
        cross_width=40.0,
        taper=0.3,
        foreshorten=1.0,
    )
    assert len(sections) == 5
    # First section at origin
    assert sections[0]["position_frac"] == pytest.approx(0.0)
    # Last section at end
    assert sections[4]["position_frac"] == pytest.approx(1.0)
