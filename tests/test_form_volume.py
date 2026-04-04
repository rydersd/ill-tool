"""Tests for form volume projection math.

Tests pure Python projection functions: sphere, cylinder, box.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.drawing.form_volume import (
    project_sphere,
    project_cylinder,
    project_box,
)


# ---------------------------------------------------------------------------
# Sphere projection
# ---------------------------------------------------------------------------


def test_sphere_front_is_circle():
    """At 0 degrees, sphere projects as a perfect circle (rx == ry)."""
    proj = project_sphere(100, 200, 50, view_angle_deg=0)
    assert proj["rx"] == pytest.approx(50.0)
    assert proj["ry"] == pytest.approx(50.0)
    assert proj["is_circle"] is True


def test_sphere_45_deg_is_ellipse():
    """At 45 degrees, rx foreshortens by cos(45)."""
    proj = project_sphere(100, 200, 50, view_angle_deg=45)
    expected_rx = 50 * math.cos(math.radians(45))
    assert proj["rx"] == pytest.approx(expected_rx, abs=0.01)
    assert proj["ry"] == pytest.approx(50.0)
    assert proj["is_circle"] is False


def test_sphere_90_deg_collapse():
    """At 90 degrees, rx collapses to ~0 (edge-on view)."""
    proj = project_sphere(100, 200, 50, view_angle_deg=90)
    assert proj["rx"] == pytest.approx(0.0, abs=0.5)
    assert proj["ry"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Cylinder projection
# ---------------------------------------------------------------------------


def test_cylinder_contour_offset():
    """Cylinder contour lines are offset by radius perpendicular to axis."""
    proj = project_cylinder(0, 0, 100, 0, radius=20, view_angle_deg=0)
    # Horizontal axis → perpendicular is vertical
    # Left contour: offset +20 in Y
    assert proj["contour_left"][0][1] == pytest.approx(20.0)
    assert proj["contour_left"][1][1] == pytest.approx(20.0)
    # Right contour: offset -20 in Y
    assert proj["contour_right"][0][1] == pytest.approx(-20.0)
    assert proj["contour_right"][1][1] == pytest.approx(-20.0)


def test_cylinder_axis_length():
    """Reported axis length matches Euclidean distance."""
    proj = project_cylinder(0, 0, 30, 40, radius=10, view_angle_deg=0)
    assert proj["axis_length_2d"] == pytest.approx(50.0)  # 3-4-5 triangle


# ---------------------------------------------------------------------------
# Box projection
# ---------------------------------------------------------------------------


def test_box_has_8_corners():
    """Projected box should have exactly 8 corners (4 front + 4 back)."""
    proj = project_box(100, 100, 60, 40, 30, rotation_deg=0)
    assert len(proj["corners"]) == 8


def test_box_has_12_edges():
    """Box wireframe should have 12 edges (4 front + 4 back + 4 connecting)."""
    proj = project_box(100, 100, 60, 40, 30, rotation_deg=0)
    assert len(proj["edges"]) == 12
