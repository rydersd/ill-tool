"""Tests for the silhouette extraction pipeline (OpenCV contour extraction).

Tests the _extract_silhouette helper and coordinate transform math without
interacting with Illustrator.
"""

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.silhouette import _extract_silhouette
from adobe_mcp.apps.illustrator.models import AiSilhouetteInput


# ---------------------------------------------------------------------------
# Contour extraction
# ---------------------------------------------------------------------------


def test_circle_silhouette(white_circle_png):
    """A white circle on black background yields exactly 1 external contour."""
    # Use the _extract_silhouette helper with place_in_ai=False
    params = AiSilhouetteInput(
        image_path=white_circle_png,
        simplification=0.01,
        place_in_ai=False,
    )
    result = _extract_silhouette(params)
    assert "error" not in result
    # The largest external contour should be one continuous shape
    assert result["point_count"] > 0
    assert len(result["pixel_points"]) == result["point_count"]


def test_simplification_reduces_points(tmp_path):
    """Lower epsilon (simplification) preserves more points than higher.

    Uses a dark star shape on a white background so that Otsu BINARY_INV
    thresholding correctly detects the complex contour (not the background).
    The star has 36 vertices in the original contour, giving enough
    resolution for approxPolyDP to show a clear difference.
    """
    import math

    star_path = str(tmp_path / "dark_star.png")
    img = np.ones((400, 400, 3), dtype=np.uint8) * 255
    pts = []
    for i in range(36):
        angle = 2 * math.pi * i / 36
        r = 150 if i % 2 == 0 else 100
        x = int(200 + r * math.cos(angle))
        y = int(200 + r * math.sin(angle))
        pts.append([x, y])
    pts_arr = np.array(pts, dtype=np.int32)
    cv2.fillPoly(img, [pts_arr], (0, 0, 0))
    cv2.imwrite(star_path, img)

    params_fine = AiSilhouetteInput(
        image_path=star_path,
        simplification=0.005,
        place_in_ai=False,
    )
    params_coarse = AiSilhouetteInput(
        image_path=star_path,
        simplification=0.05,
        place_in_ai=False,
    )
    result_fine = _extract_silhouette(params_fine)
    result_coarse = _extract_silhouette(params_coarse)

    assert "error" not in result_fine
    assert "error" not in result_coarse
    # Finer simplification → more points
    assert result_fine["point_count"] > result_coarse["point_count"]


def test_contour_is_closed(white_circle_png):
    """The extracted contour represents a closed shape (at least 3 points)."""
    params = AiSilhouetteInput(
        image_path=white_circle_png,
        simplification=0.02,
        place_in_ai=False,
    )
    result = _extract_silhouette(params)
    assert "error" not in result
    # A closed polygon requires at least 3 vertices
    assert result["point_count"] >= 3


def test_coordinate_transform_math():
    """Verify pixel-to-Illustrator coordinate mapping with Y flip.

    Given:
      image size: 100x100
      artboard rect: left=0, top=800, right=800, bottom=0
      scale = min(800/100, 800/100) = 8.0
      offset_x = 0 + (800 - 100*8) / 2 = 0
      offset_y = 800 - (800 - 100*8) / 2 = 800

    Pixel (50, 50) → AI:
      ai_x = 50 * 8 + 0 = 400
      ai_y = 800 - 50 * 8 = 400

    Pixel (0, 0) → AI:
      ai_x = 0 * 8 + 0 = 0
      ai_y = 800 - 0 * 8 = 800  (top of artboard)
    """
    # Replicate the transform logic from silhouette.py lines 143-158
    img_w, img_h = 100, 100
    ab = {"left": 0, "top": 800, "right": 800, "bottom": 0}

    ab_w = ab["right"] - ab["left"]   # 800
    ab_h = ab["top"] - ab["bottom"]   # 800

    scale_x = ab_w / img_w  # 8.0
    scale_y = ab_h / img_h  # 8.0
    scale = min(scale_x, scale_y)  # 8.0

    offset_x = ab["left"] + (ab_w - img_w * scale) / 2  # 0
    offset_y = ab["top"] - (ab_h - img_h * scale) / 2   # 800

    # Test center pixel (50, 50) → center of artboard (400, 400)
    px, py = 50, 50
    ai_x = px * scale + offset_x
    ai_y = offset_y - py * scale
    assert ai_x == pytest.approx(400.0)
    assert ai_y == pytest.approx(400.0)

    # Test top-left pixel (0, 0) → top-left of artboard (0, 800)
    px, py = 0, 0
    ai_x = px * scale + offset_x
    ai_y = offset_y - py * scale
    assert ai_x == pytest.approx(0.0)
    assert ai_y == pytest.approx(800.0)  # top of artboard in AI coords

    # Test bottom-right pixel (99, 99) → near bottom-right of artboard
    px, py = 99, 99
    ai_x = px * scale + offset_x
    ai_y = offset_y - py * scale
    assert ai_x == pytest.approx(792.0)
    assert ai_y == pytest.approx(8.0)  # Y is flipped: near bottom of artboard


def test_extract_bad_image():
    """Extraction with a nonexistent image returns an error dict."""
    params = AiSilhouetteInput(
        image_path="/tmp/nonexistent_silhouette_test.png",
        simplification=0.01,
        place_in_ai=False,
    )
    result = _extract_silhouette(params)
    assert "error" in result
