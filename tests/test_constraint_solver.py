"""Tests for the constraint solver module.

Verifies that semantic edge constraints resolve to correct pixel coordinates
using synthetic test images. All tests are pure Python — no Adobe app required.
"""

import math
import os
import tempfile

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.constraint_solver import (
    extract_silhouette_edges,
    resolve_edge_constraint,
    resolve_shape_constraint,
    snap_to_vanishing_point,
)
from adobe_mcp.apps.illustrator.landmark_axis import compute_transform, pixel_to_ai


# ---------------------------------------------------------------------------
# Helpers: synthetic test image generators
# ---------------------------------------------------------------------------


def _make_white_bg_black_rect(
    width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200,
) -> np.ndarray:
    """Create a grayscale image: black rectangle on white background.

    Returns 2D uint8 numpy array (grayscale, not saved to disk).
    """
    img = np.full((height, width), 255, dtype=np.uint8)
    cv2.rectangle(
        img, (rect_x, rect_y), (rect_x + rect_w, rect_y + rect_h), 0, -1
    )
    return img


def _make_two_zone_image(
    width=200, height=200, split_x=100,
    left_brightness=30, right_brightness=200,
) -> np.ndarray:
    """Create a grayscale image with two brightness zones split at split_x.

    Left half is dark (low zone), right half is bright (high zone).
    Returns 2D uint8 numpy array.
    """
    img = np.full((height, width), right_brightness, dtype=np.uint8)
    img[:, :split_x] = left_brightness
    return img


def _make_circle_silhouette(
    width=200, height=200, center=(100, 100), radius=50,
) -> np.ndarray:
    """Create a grayscale image: black circle on white background.

    Returns 2D uint8 numpy array.
    """
    img = np.full((height, width), 255, dtype=np.uint8)
    cv2.circle(img, center, radius, 0, -1)
    return img


# ---------------------------------------------------------------------------
# Test: silhouette edge extraction
# ---------------------------------------------------------------------------


class TestSilhouetteExtraction:
    def test_silhouette_edge_extraction(self):
        """Black rect on white bg: left/right edges found at rect boundaries."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        assert len(sil["left_edge"]) > 0, "Expected left edge points"
        assert len(sil["right_edge"]) > 0, "Expected right edge points"

        # Left edge x values should cluster near rect_x (50)
        left_xs = [p[0] for p in sil["left_edge"]]
        avg_left_x = sum(left_xs) / len(left_xs)
        assert abs(avg_left_x - 50) < 3, (
            f"Left edge average x={avg_left_x:.1f}, expected ~50"
        )

        # Right edge x values should cluster near rect_x + rect_w (150)
        right_xs = [p[0] for p in sil["right_edge"]]
        avg_right_x = sum(right_xs) / len(right_xs)
        assert abs(avg_right_x - 150) < 3, (
            f"Right edge average x={avg_right_x:.1f}, expected ~150"
        )

    def test_silhouette_y_range(self):
        """Silhouette y_range matches the vertical extent of the shape."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=80, rect_w=100, rect_h=140
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        y_min, y_max = sil["y_range"]
        assert abs(y_min - 80) <= 1, f"y_min={y_min}, expected ~80"
        assert abs(y_max - 220) <= 1, f"y_max={y_max}, expected ~220"

    def test_silhouette_empty_image(self):
        """All-white image produces empty silhouette edges."""
        gray = np.full((100, 100), 255, dtype=np.uint8)
        sil = extract_silhouette_edges(gray, threshold=200)

        assert sil["left_edge"] == []
        assert sil["right_edge"] == []
        assert sil["contour"] is None


# ---------------------------------------------------------------------------
# Test: resolve_edge_constraint
# ---------------------------------------------------------------------------


class TestResolveEdgeConstraint:
    def test_resolve_silhouette_left(self):
        """Silhouette left constraint returns left edge points."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        points = resolve_edge_constraint(
            {"type": "silhouette", "side": "left"},
            silhouette=sil,
        )
        assert len(points) > 0
        # All x values should be near 50
        xs = [p[0] for p in points]
        assert all(abs(x - 50) < 3 for x in xs), (
            f"Left edge x values should cluster near 50, got range [{min(xs)}, {max(xs)}]"
        )

    def test_resolve_silhouette_right(self):
        """Silhouette right constraint returns right edge points."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        points = resolve_edge_constraint(
            {"type": "silhouette", "side": "right"},
            silhouette=sil,
        )
        assert len(points) > 0
        xs = [p[0] for p in points]
        assert all(abs(x - 150) < 3 for x in xs), (
            f"Right edge x values should cluster near 150, got range [{min(xs)}, {max(xs)}]"
        )

    def test_resolve_tonal_boundary(self):
        """Image with two brightness zones: boundary resolves to correct x."""
        gray = _make_two_zone_image(width=200, height=200, split_x=100)

        # Zone 0 = darkest (left half at brightness 30), Zone 3 = brightest
        # With 4 zones (default), zone boundaries at 64, 128, 192
        # Left half (brightness 30) → zone 0
        # Right half (brightness 200) → zone 3
        # Boundary should be near x=100
        points = resolve_edge_constraint(
            {"type": "tonal_boundary", "from_zone": 0, "to_zone": 3},
            tonal_data=gray,
        )
        assert len(points) > 0
        # Boundary x values should cluster near 100
        xs = [p[0] for p in points]
        avg_x = sum(xs) / len(xs)
        assert abs(avg_x - 100) < 3, (
            f"Tonal boundary average x={avg_x:.1f}, expected ~100"
        )

    def test_resolve_contour_id(self):
        """Specific contour referenced by ID returns correct points."""
        gray = _make_circle_silhouette(width=200, height=200, center=(100, 100), radius=40)

        # Get contours via OpenCV
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

        assert len(contours) > 0, "Should find at least one contour"

        points = resolve_edge_constraint(
            {"type": "contour_id", "id": 0},
            contours=contours,
        )
        assert len(points) > 10, "Circle contour should have many points"

        # Points should surround center (100, 100)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        assert min(xs) < 70 and max(xs) > 130, "Contour should span the circle horizontally"
        assert min(ys) < 70 and max(ys) > 130, "Contour should span the circle vertically"

    def test_resolve_y_level(self):
        """Horizontal constraint at specific y returns horizontal line."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        points = resolve_edge_constraint(
            {"type": "y_level", "y": 150},
            silhouette=sil,
        )
        assert len(points) == 2, "y_level should produce 2 endpoints"
        # Both points at y=150
        assert points[0][1] == 150.0
        assert points[1][1] == 150.0
        # x values should span the silhouette width
        assert points[0][0] < points[1][0], "Left endpoint should be left of right"

    def test_resolve_y_level_without_silhouette(self):
        """y_level without silhouette uses default width."""
        points = resolve_edge_constraint(
            {"type": "y_level", "y": 100},
        )
        assert len(points) == 2
        assert points[0][1] == 100.0
        assert points[1][1] == 100.0

    def test_resolve_y_range(self):
        """y_range constraint returns silhouette slice within y bounds."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        points = resolve_edge_constraint(
            {"type": "y_range", "start": 100, "end": 200, "x": "silhouette_left"},
            silhouette=sil,
        )
        assert len(points) > 0
        # All points should be within the y range
        for p in points:
            assert 100 <= p[1] <= 200, f"Point y={p[1]} outside range [100, 200]"
        # All x values should be near the left edge (50)
        xs = [p[0] for p in points]
        assert all(abs(x - 50) < 3 for x in xs)

    def test_unknown_constraint_type_raises(self):
        """Unknown constraint type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown constraint type"):
            resolve_edge_constraint({"type": "nonexistent"})

    def test_missing_silhouette_raises(self):
        """Silhouette constraint without silhouette data raises ValueError."""
        with pytest.raises(ValueError, match="silhouette data required"):
            resolve_edge_constraint({"type": "silhouette", "side": "left"})

    def test_contour_id_out_of_range_raises(self):
        """Contour ID out of range raises ValueError."""
        dummy_contour = np.array([[[10, 10]], [[20, 20]]], dtype=np.int32)
        with pytest.raises(ValueError, match="out of range"):
            resolve_edge_constraint(
                {"type": "contour_id", "id": 5},
                contours=[dummy_contour],
            )


# ---------------------------------------------------------------------------
# Test: full shape constraint resolution
# ---------------------------------------------------------------------------


class TestShapeConstraint:
    def test_full_shape_constraint(self):
        """4-edge shape constraint produces a closed polygon."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        shape = resolve_shape_constraint(
            {
                "name": "front_face",
                "edges": {
                    "left": {"type": "silhouette", "side": "left"},
                    "right": {"type": "silhouette", "side": "right"},
                    "top": {"type": "y_level", "y": 75},
                    "bottom": {"type": "y_level", "y": 200},
                },
            },
            silhouette=sil,
        )

        assert shape["name"] == "front_face"
        assert len(shape["points"]) > 4, (
            f"Shape should have multiple points, got {len(shape['points'])}"
        )
        # The polygon should form a roughly rectangular region
        xs = [p[0] for p in shape["points"]]
        ys = [p[1] for p in shape["points"]]
        assert min(xs) < 55, "Polygon should reach left edge"
        assert max(xs) > 145, "Polygon should reach right edge"

    def test_shape_contains_form(self):
        """Resolved shape overlaps with the actual form region."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        shape = resolve_shape_constraint(
            {
                "name": "body",
                "edges": {
                    "left": {"type": "silhouette", "side": "left"},
                    "right": {"type": "silhouette", "side": "right"},
                    "top": {"type": "y_level", "y": 60},
                    "bottom": {"type": "y_level", "y": 240},
                },
            },
            silhouette=sil,
        )

        # Check that the shape polygon encompasses the form center (100, 150)
        points = shape["points"]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        # Bounding box of the polygon should contain the form center
        assert min(xs) <= 100 <= max(xs), "Polygon bbox should contain form center x"
        assert min(ys) <= 150 <= max(ys), "Polygon bbox should contain form center y"

    def test_shape_with_ai_coords(self):
        """Shape constraint with transform produces AI coordinates."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)
        transform = compute_transform(200, 300, 0.0, 300.0, 200.0, 0.0)

        shape = resolve_shape_constraint(
            {
                "name": "test",
                "edges": {
                    "left": {"type": "silhouette", "side": "left"},
                    "right": {"type": "silhouette", "side": "right"},
                    "top": {"type": "y_level", "y": 100},
                    "bottom": {"type": "y_level", "y": 200},
                },
            },
            silhouette=sil,
            transform=transform,
        )

        assert len(shape["ai_points"]) > 0, "Should produce AI coordinate points"
        assert len(shape["ai_points"]) == len(shape["points"]), (
            "AI points count should match pixel points count"
        )


# ---------------------------------------------------------------------------
# Test: vanishing point snap
# ---------------------------------------------------------------------------


class TestVanishingPointSnap:
    def test_snap_to_vp(self):
        """Edge not converging to VP is snapped to converge within tolerance."""
        # Horizontal edge at y=200 — VP is at (500, 0), so edges should
        # converge upward-right. A horizontal line does NOT converge.
        edge = [[100.0, 200.0], [200.0, 200.0], [300.0, 200.0]]
        vp = (500.0, 0.0)

        snapped = snap_to_vanishing_point(edge, vp, tolerance=5.0)

        assert len(snapped) == 3
        # First point unchanged (anchor)
        assert snapped[0] == [100.0, 200.0]

        # Subsequent points should be adjusted toward the VP direction
        # The original horizontal edge has angle 0 degrees.
        # The VP from midpoint (150, 200) is at direction ~ -30 degrees.
        # After snap, the edge should be rotated away from horizontal.
        # Point 2's y should be less than 200 (tilted upward toward VP)
        assert snapped[1][1] < 200.0, (
            f"Snapped point y={snapped[1][1]} should be < 200 (tilted toward VP)"
        )

    def test_no_snap_when_aligned(self):
        """Edge already converging to VP remains unchanged."""
        # Edge pointing directly at the VP
        vp = (500.0, 100.0)
        edge = [[100.0, 100.0], [300.0, 100.0]]  # horizontal line toward VP

        snapped = snap_to_vanishing_point(edge, vp, tolerance=5.0)

        # Points should be unchanged (edge is already pointing at VP)
        assert snapped[0] == [100.0, 100.0]
        assert abs(snapped[1][0] - 300.0) < 0.01
        assert abs(snapped[1][1] - 100.0) < 0.01

    def test_snap_single_point(self):
        """Single point edge returns unchanged."""
        snapped = snap_to_vanishing_point([[50.0, 50.0]], (500.0, 0.0))
        assert snapped == [[50.0, 50.0]]

    def test_snap_empty(self):
        """Empty edge list returns empty."""
        snapped = snap_to_vanishing_point([], (500.0, 0.0))
        assert snapped == []

    def test_snap_preserves_segment_length(self):
        """Snapping rotates but preserves distance between consecutive points."""
        edge = [[100.0, 200.0], [200.0, 200.0]]
        vp = (500.0, 0.0)

        snapped = snap_to_vanishing_point(edge, vp, tolerance=5.0)

        # Original segment length
        orig_len = math.sqrt(
            (edge[1][0] - edge[0][0]) ** 2 + (edge[1][1] - edge[0][1]) ** 2
        )
        # Snapped segment length
        snap_len = math.sqrt(
            (snapped[1][0] - snapped[0][0]) ** 2
            + (snapped[1][1] - snapped[0][1]) ** 2
        )
        assert abs(orig_len - snap_len) < 0.1, (
            f"Segment length changed: {orig_len:.2f} -> {snap_len:.2f}"
        )


# ---------------------------------------------------------------------------
# Test: pixel to AI coordinate conversion
# ---------------------------------------------------------------------------


class TestPixelToAIConversion:
    def test_pixel_to_ai_conversion(self):
        """Resolved constraint points correctly convert to AI coordinates."""
        gray = _make_white_bg_black_rect(
            width=200, height=300, rect_x=50, rect_y=50, rect_w=100, rect_h=200
        )
        sil = extract_silhouette_edges(gray, threshold=200)

        # Resolve a simple constraint
        points = resolve_edge_constraint(
            {"type": "silhouette", "side": "left"},
            silhouette=sil,
        )

        # Convert to AI coords: 200x300 image on 200x300 artboard at origin
        transform = compute_transform(200, 300, 0.0, 300.0, 200.0, 0.0)

        ai_points = []
        for pt in points:
            ai_x, ai_y = pixel_to_ai(pt[0], pt[1], transform)
            ai_points.append([round(ai_x, 2), round(ai_y, 2)])

        assert len(ai_points) == len(points)

        # In pixel space, left edge is at x~50, y ranges from 50 to 250.
        # In AI space (Y flipped): x~50, y ranges from 250 down to 50.
        # AI Y should be higher for smaller pixel Y (top of image = high AI Y).
        first_ai = ai_points[0]
        last_ai = ai_points[-1]
        assert first_ai[1] > last_ai[1] or abs(first_ai[1] - last_ai[1]) < 1, (
            "AI y should decrease as pixel y increases (Y-flip)"
        )
