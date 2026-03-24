"""Tests for the reference crop and re-analysis pipeline.

Tests the _analyze_cropped_region helper and crop dimension validation
using synthetic fixtures.
"""

import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.reference_crop import _analyze_cropped_region


# ---------------------------------------------------------------------------
# Crop dimensions
# ---------------------------------------------------------------------------


def test_crop_dimensions(white_rect_png):
    """Cropping at (10, 10, 50, 50) produces a 50x50 region."""
    img = cv2.imread(white_rect_png)
    assert img is not None

    cropped = img[10:10 + 50, 10:10 + 50]
    assert cropped.shape[0] == 50  # height
    assert cropped.shape[1] == 50  # width


def test_crop_preserves_content(white_rect_png):
    """Cropping the rectangle area preserves white pixels.

    The white rect is drawn from (20,30) to (80,70) on a 100x100 image.
    Cropping at (25, 35, 50, 30) should contain mostly white.
    """
    img = cv2.imread(white_rect_png)
    cropped = img[35:35 + 30, 25:25 + 50]
    # The center of this crop should be entirely within the white rectangle
    center_pixel = cropped[15, 25]
    # BGR format — white is (255, 255, 255)
    assert center_pixel[0] == 255
    assert center_pixel[1] == 255
    assert center_pixel[2] == 255


def test_analysis_on_crop(white_rect_png):
    """Cropping the rect region and analyzing it detects shapes."""
    img = cv2.imread(white_rect_png)
    # Crop a region that includes part of the white rectangle border
    # on the black background — this creates edges for contour detection
    cropped = img[20:80, 10:90]

    result = _analyze_cropped_region(cropped, min_area_pct=0.5)
    assert "shapes" in result
    assert "crop_size" in result
    assert result["crop_size"] == [80, 60]  # width=90-10, height=80-20


def test_save_to_disk(white_rect_png, tmp_path):
    """Verify cropped image is written to disk when requested."""
    img = cv2.imread(white_rect_png)
    cropped = img[10:60, 10:60]

    crop_path = str(tmp_path / "test_crop.png")
    cv2.imwrite(crop_path, cropped)

    assert os.path.isfile(crop_path)
    # Re-read and verify dimensions
    reloaded = cv2.imread(crop_path)
    assert reloaded.shape[0] == 50
    assert reloaded.shape[1] == 50


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_analysis_min_area_filter(white_rect_png):
    """High min_area_pct filters out small contours."""
    img = cv2.imread(white_rect_png)
    cropped = img[20:80, 10:90]

    result_strict = _analyze_cropped_region(cropped, min_area_pct=30.0)
    result_loose = _analyze_cropped_region(cropped, min_area_pct=0.1)

    # Strict filtering should return fewer or equal shapes
    assert result_strict["shapes_returned"] <= result_loose["shapes_returned"]


def test_analysis_max_contours_cap(two_rects_png):
    """max_contours parameter caps the number of returned shapes."""
    img = cv2.imread(two_rects_png)
    result = _analyze_cropped_region(img, min_area_pct=0.1, max_contours=1)
    assert result["shapes_returned"] <= 1
