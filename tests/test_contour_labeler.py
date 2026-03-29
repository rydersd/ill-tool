"""Tests for the contour labeler — classify and connect CV-extracted contours.

Tests use synthetic images to verify contour metadata extraction, classification
based on brightness analysis, contour connection across gaps, and shape assembly.
No Adobe app required.
"""

import math
import os
import tempfile

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.contour_labeler import (
    extract_labeled_contours,
    classify_contour,
    connect_contours_to_shape,
    assemble_shape,
    _compute_contour_metadata,
    _sample_brightness_sides,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic test image generators
# ---------------------------------------------------------------------------


def _make_black_circle_on_white(
    width: int = 200, height: int = 200,
    cx: int = 100, cy: int = 100, radius: int = 40,
) -> tuple[str, np.ndarray]:
    """Create a black filled circle on white background and save to disk.

    Returns (file_path, grayscale_image).
    """
    gray = np.full((height, width), 255, dtype=np.uint8)
    cv2.circle(gray, (cx, cy), radius, 0, -1)

    # Save as BGR image (what _load_grayscale expects from cv2.imread)
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


def _make_two_dark_regions(width: int = 200, height: int = 200) -> tuple[str, np.ndarray]:
    """Create two dark rectangles side by side on a dark gray background.

    Left rectangle: brightness 30 (columns 40-90)
    Right rectangle: brightness 50 (columns 110-160)
    Background: brightness 60

    The boundary between them is dark-on-dark — a panel_line scenario.

    Returns (file_path, grayscale_image).
    """
    gray = np.full((height, width), 60, dtype=np.uint8)
    gray[40:160, 40:90] = 30
    gray[40:160, 110:160] = 50

    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, bgr)
    return path, gray


def _make_contour_segments(
    gap: float = 5.0,
) -> tuple[list[np.ndarray], list[list[float]]]:
    """Create two horizontal contour segments with a known gap between them.

    Segment 0: horizontal line from (10, 50) to (80, 50)
    Segment 1: horizontal line from (80+gap, 50) to (150, 50)

    Returns (contour_arrays, gap_endpoints).
    """
    seg0_pts = np.array([[[x, 50]] for x in range(10, 81)], dtype=np.int32)
    seg1_pts = np.array([[[x, 50]] for x in range(int(80 + gap), 151)], dtype=np.int32)
    return [seg0_pts, seg1_pts], [(80, 50), (int(80 + gap), 50)]


def _make_rectangle_contours() -> list[np.ndarray]:
    """Create 4 contour segments forming the edges of a rectangle.

    Top edge: (20, 20) to (180, 20)
    Right edge: (180, 20) to (180, 150)
    Bottom edge: (180, 150) to (20, 150)
    Left edge: (20, 150) to (20, 20)

    Each edge is a separate contour so they can be connected.
    """
    top = np.array([[[x, 20]] for x in range(20, 181, 2)], dtype=np.int32)
    right = np.array([[[180, y]] for y in range(20, 151, 2)], dtype=np.int32)
    bottom = np.array([[[x, 150]] for x in range(180, 19, -2)], dtype=np.int32)
    left = np.array([[[20, y]] for y in range(150, 19, -2)], dtype=np.int32)
    return [top, right, bottom, left]


def _make_vertical_line_contour() -> np.ndarray:
    """Create a vertical line contour from (50, 10) to (50, 190)."""
    return np.array([[[50, y]] for y in range(10, 191)], dtype=np.int32)


def _make_horizontal_line_contour() -> np.ndarray:
    """Create a horizontal line contour from (10, 50) to (190, 50)."""
    return np.array([[[x, 50]] for x in range(10, 191)], dtype=np.int32)


# ---------------------------------------------------------------------------
# Test: extract_labeled_contours returns metadata
# ---------------------------------------------------------------------------


class TestExtractReturnsMetadata:
    def test_extract_returns_metadata(self):
        """Verify metadata fields exist for each extracted contour."""
        path, gray = _make_black_circle_on_white()
        try:
            result = extract_labeled_contours(path, min_votes=5, min_length=20)

            assert "error" not in result, f"Extraction failed: {result.get('error')}"
            assert result["contour_count"] > 0, "Expected at least one contour"
            assert len(result["metadata"]) == result["contour_count"]

            # Check all required metadata fields are present
            required_fields = [
                "id", "bounding_box", "centroid", "orientation",
                "perimeter", "area", "avg_brightness_left",
                "avg_brightness_right", "position_relative",
            ]
            for meta in result["metadata"]:
                for field in required_fields:
                    assert field in meta, f"Missing metadata field: {field}"

                # Bounding box should have x, y, w, h
                bbox = meta["bounding_box"]
                for key in ["x", "y", "w", "h"]:
                    assert key in bbox, f"Missing bounding_box key: {key}"

                # Centroid should be a tuple of two numbers
                assert len(meta["centroid"]) == 2

                # Orientation should be one of the expected values
                assert meta["orientation"] in ("vertical", "horizontal", "diagonal")

                # Position should be one of the expected values
                assert meta["position_relative"] in ("top", "middle", "bottom")

        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: classify_contour
# ---------------------------------------------------------------------------


class TestClassifySilhouette:
    def test_classify_silhouette(self):
        """Black circle on white background: outer contour is a silhouette_edge.

        The contour separates black (form) from white (background), so one
        side should be very bright (>200) and the difference should be large.
        """
        path, gray = _make_black_circle_on_white()
        try:
            result = extract_labeled_contours(path, min_votes=5, min_length=20)
            assert "error" not in result
            assert result["contour_count"] > 0

            # The main contour should classify as silhouette_edge because
            # one side is white background (255) and the other is black form (0)
            meta = result["metadata"][0]
            classification = classify_contour(meta, gray)
            assert classification == "silhouette_edge", (
                f"Expected silhouette_edge, got {classification}. "
                f"Left={meta['avg_brightness_left']}, Right={meta['avg_brightness_right']}"
            )
        finally:
            os.unlink(path)


class TestClassifyPanelLine:
    def test_classify_panel_line(self):
        """Two dark regions side by side: boundary classified as panel_line.

        When both sides of a contour are dark and the brightness difference
        is small, it's a surface detail on the same plane.
        """
        # Create a synthetic metadata dict simulating a panel line scenario
        meta = {
            "avg_brightness_left": 35.0,
            "avg_brightness_right": 45.0,
        }
        gray_dummy = np.full((100, 100), 40, dtype=np.uint8)

        classification = classify_contour(meta, gray_dummy)
        assert classification == "panel_line", (
            f"Expected panel_line for small brightness diff, got {classification}"
        )


# ---------------------------------------------------------------------------
# Test: connect_contours_to_shape
# ---------------------------------------------------------------------------


class TestConnectCloseContours:
    def test_connect_close_contours(self):
        """Two contour segments with 5px gap: successfully connected."""
        contours, _ = _make_contour_segments(gap=5.0)
        result = connect_contours_to_shape([0, 1], contours, max_gap=15.0)

        assert len(result["points"]) > 0, "Connected shape should have points"
        assert result["gaps_bridged"] == 1, (
            f"Expected 1 gap bridged, got {result['gaps_bridged']}"
        )
        assert result["max_gap_size"] <= 15.0
        assert len(result["disconnected"]) == 0


class TestConnectRejectsLargeGap:
    def test_connect_rejects_large_gap(self):
        """Two segments 50px apart: flagged as disconnected."""
        contours, _ = _make_contour_segments(gap=50.0)
        result = connect_contours_to_shape([0, 1], contours, max_gap=15.0)

        # Points are still combined (the shape is built even with gaps)
        assert len(result["points"]) > 0
        assert len(result["disconnected"]) == 1, (
            f"Expected 1 disconnected gap, got {len(result['disconnected'])}"
        )
        assert result["disconnected"][0][2] > 15.0


# ---------------------------------------------------------------------------
# Test: assemble_shape
# ---------------------------------------------------------------------------


class TestAssembleShape:
    def test_assemble_shape(self):
        """Connect 4 edge segments into a rectangle: verify closed polygon."""
        contours = _make_rectangle_contours()

        # Create mock classified metadata
        classified = [
            {"id": i, "classification": "silhouette_edge"} for i in range(4)
        ]

        shape = assemble_shape(
            name="test_rect",
            classified_contours=classified,
            connection_spec=[0, 1, 2, 3],
            contours_data=contours,
            max_gap=15.0,
        )

        assert shape["name"] == "test_rect"
        assert shape["anchor_count"] > 0, "Shape should have anchor points"
        assert len(shape["points"]) > 0
        assert len(shape["ai_points"]) == len(shape["points"])
        assert shape["source_contour_ids"] == [0, 1, 2, 3]
        assert shape["classification"] == "silhouette_edge"


# ---------------------------------------------------------------------------
# Test: orientation detection
# ---------------------------------------------------------------------------


class TestOrientationDetection:
    def test_vertical_line_orientation(self):
        """A vertical line contour should have orientation 'vertical'."""
        contour = _make_vertical_line_contour()
        gray = np.full((200, 200), 128, dtype=np.uint8)

        meta = _compute_contour_metadata(contour, gray, contour_id=0)
        assert meta["orientation"] == "vertical", (
            f"Expected vertical orientation, got {meta['orientation']}. "
            f"Bounding box: {meta['bounding_box']}"
        )

    def test_horizontal_line_orientation(self):
        """A horizontal line contour should have orientation 'horizontal'."""
        contour = _make_horizontal_line_contour()
        gray = np.full((200, 200), 128, dtype=np.uint8)

        meta = _compute_contour_metadata(contour, gray, contour_id=0)
        assert meta["orientation"] == "horizontal", (
            f"Expected horizontal orientation, got {meta['orientation']}. "
            f"Bounding box: {meta['bounding_box']}"
        )


# ---------------------------------------------------------------------------
# Test: brightness side sampling
# ---------------------------------------------------------------------------


class TestBrightnessSides:
    def test_brightness_sides(self):
        """Contour between bright and dark regions: correct side brightness.

        A vertical contour at x=100 with white (255) on the left and black (0)
        on the right should show high brightness on one side and low on the other.
        """
        # Create an image: left half white, right half black
        gray = np.zeros((200, 200), dtype=np.uint8)
        gray[:, :100] = 255
        gray[:, 100:] = 0

        # Vertical contour at x=100
        contour = np.array([[[100, y]] for y in range(20, 181)], dtype=np.int32)

        avg_left, avg_right = _sample_brightness_sides(contour, gray, offset=5)

        # One side should be much brighter than the other
        diff = abs(avg_left - avg_right)
        assert diff > 100, (
            f"Expected large brightness difference, got {diff:.1f}. "
            f"Left={avg_left:.1f}, Right={avg_right:.1f}"
        )
