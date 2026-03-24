"""Tests for the shading-to-form inference tool.

Uses synthetic shaded sphere images to verify light direction inference.
All tests are pure Python using OpenCV and numpy.
"""

import math
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.shading_inference import (
    detect_shading_regions,
    infer_light_direction,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic shaded images
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def shaded_sphere_top_left(tmp_path_factory):
    """200x200 sphere with highlight at top-left (light from top-left).

    White highlight at top-left quadrant, dark shadow at bottom-right.
    """
    path = str(tmp_path_factory.mktemp("shading") / "sphere_tl.png")
    img = np.full((200, 200), 128, dtype=np.uint8)  # midtone base

    # Create gradient: bright at top-left, dark at bottom-right
    for y in range(200):
        for x in range(200):
            # Distance from top-left corner
            dist = math.sqrt(x * x + y * y)
            max_dist = math.sqrt(200 * 200 + 200 * 200)
            brightness = int(255 * (1 - dist / max_dist))
            img[y, x] = brightness

    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def uniform_gray_image(tmp_path_factory):
    """200x200 uniform gray image (no shading variation)."""
    path = str(tmp_path_factory.mktemp("shading") / "uniform.png")
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def highlight_right_image(tmp_path_factory):
    """200x200 image with bright region on the right side."""
    path = str(tmp_path_factory.mktemp("shading") / "highlight_right.png")
    img = np.full((200, 200), 50, dtype=np.uint8)  # dark base

    # Bright region on right half
    img[:, 150:] = 240

    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# detect_shading_regions
# ---------------------------------------------------------------------------


def test_detect_shading_finds_three_regions(shaded_sphere_top_left):
    """Shading detection identifies highlight, midtone, and shadow regions."""
    result = detect_shading_regions(shaded_sphere_top_left)
    assert "error" not in result
    assert "regions" in result
    assert "highlight" in result["regions"]
    assert "midtone" in result["regions"]
    assert "shadow" in result["regions"]
    # All regions should have nonzero pixel counts
    assert result["regions"]["highlight"]["pixel_count"] > 0
    assert result["regions"]["midtone"]["pixel_count"] > 0
    assert result["regions"]["shadow"]["pixel_count"] > 0


def test_detect_shading_highlight_centroid_position(shaded_sphere_top_left):
    """Highlight centroid is in the top-left region of the image."""
    result = detect_shading_regions(shaded_sphere_top_left)
    centroid = result["regions"]["highlight"]["centroid"]
    assert centroid is not None
    # Highlight should be in the top-left quadrant (x < 100, y < 100)
    assert centroid[0] < 100, f"Highlight centroid x={centroid[0]} should be < 100"
    assert centroid[1] < 100, f"Highlight centroid y={centroid[1]} should be < 100"


# ---------------------------------------------------------------------------
# infer_light_direction
# ---------------------------------------------------------------------------


def test_infer_light_from_top_left(shaded_sphere_top_left):
    """Light direction inferred from top-left highlight points toward top-left."""
    result = detect_shading_regions(shaded_sphere_top_left)
    centroid = result["regions"]["highlight"]["centroid"]
    w, h = result["image_size"]
    center = [w / 2, h / 2]

    light = infer_light_direction(centroid, center)
    # Light direction should point toward top-left
    # In our convention: negative x = left, positive y = up (because we negate image Y)
    assert light["direction"][0] < 0, "Light should be from the left"
    assert light["direction"][1] > 0, "Light should be from the top (Y-up)"
    assert light["confidence"] > 0.0


def test_infer_light_no_highlight():
    """No highlight detected returns zero confidence."""
    light = infer_light_direction(None, [100, 100])
    assert light["confidence"] == 0.0
    assert "unknown" in light["description"]


def test_infer_light_from_right(highlight_right_image):
    """Light from right side detected when highlight is on the right."""
    result = detect_shading_regions(highlight_right_image)
    centroid = result["regions"]["highlight"]["centroid"]
    w, h = result["image_size"]
    center = [w / 2, h / 2]

    light = infer_light_direction(centroid, center)
    # Light should be from the right (positive x direction)
    assert light["direction"][0] > 0, "Light should be from the right"
    assert light["confidence"] > 0.0
    assert "right" in light["description"].lower()
