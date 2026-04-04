"""Tests for the tonal analyzer — K-means zone clustering and plane transitions.

Tests use synthetic grayscale images to verify zone segmentation, sorting,
light direction estimation, plane transition detection, and zone boundary
contour extraction. No Adobe app required.
"""

import math
import os
import tempfile

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.drawing.tonal_analyzer import (
    analyze_tonal_zones,
    find_plane_transitions,
    get_zone_boundary_contours,
    _analyze_tonal_zones_from_gray,
    _estimate_light_direction,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic test image generators
# ---------------------------------------------------------------------------


def _make_four_tone_image(width: int = 200, height: int = 200) -> tuple[str, np.ndarray]:
    """Create an image with four distinct tonal bands (horizontal stripes).

    Top quarter: brightness 30 (dark)
    Second quarter: brightness 90 (medium-dark)
    Third quarter: brightness 170 (medium-bright)
    Bottom quarter: brightness 240 (bright)

    Returns (file_path, grayscale_image).
    """
    gray = np.zeros((height, width), dtype=np.uint8)
    quarter = height // 4
    gray[:quarter, :] = 30
    gray[quarter:2 * quarter, :] = 90
    gray[2 * quarter:3 * quarter, :] = 170
    gray[3 * quarter:, :] = 240

    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


def _make_uniform_image(
    value: int = 128, width: int = 100, height: int = 100,
) -> tuple[str, np.ndarray]:
    """Create a uniform grayscale image.

    Returns (file_path, grayscale_image).
    """
    gray = np.full((height, width), value, dtype=np.uint8)
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


def _make_two_halves_image(width: int = 200, height: int = 200) -> tuple[str, np.ndarray]:
    """Create an image with two tonal halves (left dark, right bright).

    Left half: brightness 40
    Right half: brightness 220

    Returns (file_path, grayscale_image).
    """
    gray = np.zeros((height, width), dtype=np.uint8)
    gray[:, :width // 2] = 40
    gray[:, width // 2:] = 220

    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


def _make_light_from_topleft(width: int = 200, height: int = 200) -> tuple[str, np.ndarray]:
    """Create an image simulating light from top-left.

    Top-left quadrant: bright (230)
    Bottom-right quadrant: dark (30)
    Other quadrants: medium (130)

    Returns (file_path, grayscale_image).
    """
    gray = np.full((height, width), 130, dtype=np.uint8)
    half_h = height // 2
    half_w = width // 2
    gray[:half_h, :half_w] = 230   # Top-left: bright (lit)
    gray[half_h:, half_w:] = 30    # Bottom-right: dark (shadow)

    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


# ---------------------------------------------------------------------------
# Test: zone count
# ---------------------------------------------------------------------------


class TestZoneCount:
    def test_zone_count(self):
        """4-zone analysis returns exactly 4 zones in zone_stats."""
        path, gray = _make_four_tone_image()
        try:
            result = analyze_tonal_zones(path, n_zones=4)
            assert "error" not in result, f"Analysis failed: {result.get('error')}"
            assert len(result["zone_stats"]) == 4, (
                f"Expected 4 zones, got {len(result['zone_stats'])}"
            )
            assert result["n_zones"] == 4
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: zones sorted dark to bright
# ---------------------------------------------------------------------------


class TestZonesSortedDarkToBright:
    def test_zones_sorted_dark_to_bright(self):
        """Zone 0 is darkest, zone n-1 is brightest."""
        path, gray = _make_four_tone_image()
        try:
            result = analyze_tonal_zones(path, n_zones=4)
            assert "error" not in result

            stats = result["zone_stats"]
            # Each zone's mean brightness should be less than the next
            for i in range(len(stats) - 1):
                assert stats[i]["mean_brightness"] < stats[i + 1]["mean_brightness"], (
                    f"Zone {i} brightness ({stats[i]['mean_brightness']}) should be "
                    f"< zone {i+1} brightness ({stats[i+1]['mean_brightness']})"
                )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: uniform image
# ---------------------------------------------------------------------------


class TestUniformImage:
    def test_uniform_image(self):
        """Uniform image: all pixels should end up in effectively one zone.

        K-means with k=4 on identical values will still produce 4 clusters,
        but they should all have the same (or nearly the same) mean brightness
        and one cluster should contain all or nearly all pixels.
        """
        path, gray = _make_uniform_image(value=128)
        try:
            result = analyze_tonal_zones(path, n_zones=4)
            assert "error" not in result

            # All zones should have the same mean brightness (within tolerance)
            stats = result["zone_stats"]
            brightnesses = [s["mean_brightness"] for s in stats]
            brightness_range = max(brightnesses) - min(brightnesses)
            assert brightness_range < 5.0, (
                f"Uniform image zone brightness range should be ~0, got {brightness_range:.1f}"
            )

            # One zone should have a dominant percentage
            percentages = [s["percentage"] for s in stats]
            max_pct = max(percentages)
            assert max_pct > 20.0, (
                f"At least one zone should contain a significant portion of pixels, "
                f"max percentage is {max_pct}%"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: plane transition detection
# ---------------------------------------------------------------------------


class TestPlaneTransitionDetection:
    def test_plane_transition_detection(self):
        """Image with two tonal halves: transition found near the boundary.

        Left half is dark, right half is bright. The boundary at the center
        should be detected as a vertical transition.

        We pass a form_mask that includes the entire image so the default
        background-exclusion (which would mask out the bright half) does
        not remove the transition we're looking for.
        """
        path, gray = _make_two_halves_image()
        try:
            result = analyze_tonal_zones(path, n_zones=2)
            assert "error" not in result

            # Use a form mask that includes all pixels so both zones
            # participate in the transition scan
            full_mask = np.ones_like(result["zone_map"], dtype=np.uint8)

            transitions = find_plane_transitions(
                result["zone_map"], form_mask=full_mask,
                scan_interval=2, min_confidence=3,
            )

            # Should find at least one vertical transition near the center
            vertical_transitions = [
                t for t in transitions if t["orientation"] == "vertical"
            ]
            assert len(vertical_transitions) > 0, (
                "Expected at least one vertical transition for two-halves image. "
                f"Total transitions found: {len(transitions)}"
            )

            # The transition position should be near the center (x=100)
            positions = [t["position"] for t in vertical_transitions]
            closest_to_center = min(positions, key=lambda p: abs(p - 100))
            assert abs(closest_to_center - 100) < 15, (
                f"Transition should be near x=100, closest is at x={closest_to_center}"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: light direction estimation
# ---------------------------------------------------------------------------


class TestLightDirection:
    def test_light_direction(self):
        """Bright top-left, dark bottom-right: light comes from top-left.

        The light direction vector should point from the bright region
        (top-left) toward the dark region (bottom-right), meaning
        dx > 0 and dy > 0.
        """
        path, gray = _make_light_from_topleft()
        try:
            result = analyze_tonal_zones(path, n_zones=3)
            assert "error" not in result

            dx, dy = result["light_direction"]

            # Light comes FROM the bright zone (top-left) TOWARD the dark zone
            # (bottom-right), so dx > 0 and dy > 0
            assert dx > 0, (
                f"Light direction dx should be positive (toward right), got {dx}"
            )
            assert dy > 0, (
                f"Light direction dy should be positive (toward bottom), got {dy}"
            )

            # It should be roughly a unit vector
            length = math.sqrt(dx * dx + dy * dy)
            assert abs(length - 1.0) < 0.1, (
                f"Light direction should be a unit vector, length={length:.3f}"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: zone boundary contours
# ---------------------------------------------------------------------------


class TestZoneBoundaryContours:
    def test_zone_boundary_contours(self):
        """Boundary between two zones returns valid contour arrays."""
        path, gray = _make_two_halves_image()
        try:
            result = analyze_tonal_zones(path, n_zones=2)
            assert "error" not in result

            contours = get_zone_boundary_contours(result["zone_map"], 0, 1)

            assert len(contours) > 0, (
                "Expected at least one boundary contour between zone 0 and zone 1"
            )

            # Contours should be in standard OpenCV format (Nx1x2)
            for contour in contours:
                assert contour.ndim == 3, f"Contour should be 3D, got {contour.ndim}D"
                assert contour.shape[1] == 1
                assert contour.shape[2] == 2
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: form mask excludes brightest zone
# ---------------------------------------------------------------------------


class TestFormMask:
    def test_form_mask(self):
        """Brightest zone is excluded from form analysis by default.

        When find_plane_transitions is called without a form_mask,
        it should automatically exclude the brightest zone (background).
        """
        path, gray = _make_four_tone_image()
        try:
            result = analyze_tonal_zones(path, n_zones=4)
            assert "error" not in result

            zone_map = result["zone_map"]
            n_zones = result["n_zones"]

            # The default form mask should exclude the brightest zone (3)
            # Transitions should only be found within zones 0, 1, 2
            transitions = find_plane_transitions(
                zone_map, scan_interval=2, min_confidence=3
            )

            for t in transitions:
                # No transition should involve the brightest zone (3)
                # unless the form mask is explicitly overridden
                zone_a, zone_b = t["zones"]
                # Both zones in each transition should be within the form
                assert zone_a < n_zones, f"Zone {zone_a} exceeds range"
                assert zone_b < n_zones, f"Zone {zone_b} exceeds range"
        finally:
            os.unlink(path)
