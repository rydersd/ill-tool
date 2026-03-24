"""Tests for speed/motion lines and impact lines.

Verifies motion line direction, impact line radiation, and count accuracy.
All tests are pure Python — no JSX or Adobe required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.action_lines import (
    generate_action_lines,
    generate_impact_lines,
)


# ---------------------------------------------------------------------------
# Motion lines point in correct direction
# ---------------------------------------------------------------------------


def test_motion_lines_opposite_direction():
    """Motion lines emanate in the opposite direction of travel."""
    # Moving right (0 degrees) => lines should go to the LEFT (180 degrees)
    origin = [100, 100]
    lines = generate_action_lines(
        direction_angle=0,
        origin=origin,
        length=50,
        count=5,
        spread=10,
    )

    for line in lines:
        sx, sy = line["start"]
        ex, ey = line["end"]
        # End point should be to the LEFT of the start (lower x)
        assert ex < sx, f"Line end x={ex} should be less than start x={sx}"


# ---------------------------------------------------------------------------
# Impact lines radiate from center
# ---------------------------------------------------------------------------


def test_impact_lines_radiate_from_center():
    """Impact lines all start at the center point and radiate outward."""
    center = [200, 200]
    radius = 80
    count = 12
    lines = generate_impact_lines(center, radius, count)

    assert len(lines) == count

    for line in lines:
        sx, sy = line["start"]
        ex, ey = line["end"]

        # All lines start at center
        assert sx == pytest.approx(center[0], abs=0.01)
        assert sy == pytest.approx(center[1], abs=0.01)

        # Distance from center to end should be ~radius
        dist = math.sqrt((ex - center[0]) ** 2 + (ey - center[1]) ** 2)
        assert dist == pytest.approx(radius, abs=0.01)


# ---------------------------------------------------------------------------
# Count matches requested
# ---------------------------------------------------------------------------


def test_line_count_matches():
    """The number of generated lines matches the requested count."""
    motion_lines = generate_action_lines(
        direction_angle=45,
        origin=[0, 0],
        length=100,
        count=15,
        spread=30,
    )
    assert len(motion_lines) == 15

    impact_lines = generate_impact_lines(
        center=[0, 0],
        radius=50,
        count=20,
    )
    assert len(impact_lines) == 20
