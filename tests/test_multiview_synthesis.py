"""Tests for the multi-view synthesis tool.

Verifies camera position math for 4-view and 8-view layouts,
and status reporting.
All tests are pure Python — no 3D rendering deps required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.threed.multiview_synthesis import compute_camera_positions


# ---------------------------------------------------------------------------
# Camera position math
# ---------------------------------------------------------------------------


def test_four_views_cardinal_directions():
    """4 views should produce front, right, back, left at 0/90/180/270 degrees."""
    cameras = compute_camera_positions(n_views=4, radius=5.0, elevation_deg=0.0)

    assert len(cameras) == 4

    # Check azimuth angles
    azimuths = [c["azimuth_deg"] for c in cameras]
    assert azimuths == [0.0, 90.0, 180.0, 270.0]

    # Check labels
    labels = [c["label"] for c in cameras]
    assert labels == ["front", "right", "back", "left"]

    # At 0 elevation, all cameras should be at same Z height
    z_values = [c["position"][2] for c in cameras]
    for z in z_values:
        assert abs(z) < 1e-6, f"Expected z≈0 at 0° elevation, got {z}"

    # All cameras should be at distance=radius from origin
    for cam in cameras:
        x, y, z = cam["position"]
        dist = math.sqrt(x**2 + y**2 + z**2)
        assert abs(dist - 5.0) < 1e-4, f"Expected radius=5.0, got {dist}"


def test_eight_views_includes_diagonals():
    """8 views should include both cardinal and diagonal positions."""
    cameras = compute_camera_positions(n_views=8, radius=3.0, elevation_deg=0.0)

    assert len(cameras) == 8

    # Check azimuth angles at 45° increments
    azimuths = [c["azimuth_deg"] for c in cameras]
    expected_azimuths = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
    for actual, expected in zip(azimuths, expected_azimuths):
        assert abs(actual - expected) < 1e-4, f"Expected {expected}°, got {actual}°"

    # Check that diagonal labels are present
    labels = [c["label"] for c in cameras]
    assert "front_right" in labels
    assert "back_right" in labels
    assert "back_left" in labels
    assert "front_left" in labels


def test_camera_positions_with_elevation():
    """Cameras at non-zero elevation should have positive Z offset."""
    cameras = compute_camera_positions(
        n_views=4, radius=10.0, elevation_deg=30.0
    )

    assert len(cameras) == 4

    # All cameras should have positive Z (elevated above equator)
    for cam in cameras:
        z = cam["position"][2]
        expected_z = 10.0 * math.sin(math.radians(30.0))
        assert abs(z - expected_z) < 1e-4, f"Expected z≈{expected_z}, got {z}"

    # Horizontal radius should be reduced by cos(elevation)
    expected_r_horiz = 10.0 * math.cos(math.radians(30.0))
    for cam in cameras:
        x, y, _ = cam["position"]
        r_horiz = math.sqrt(x**2 + y**2)
        assert abs(r_horiz - expected_r_horiz) < 1e-4, (
            f"Expected horizontal radius≈{expected_r_horiz}, got {r_horiz}"
        )
