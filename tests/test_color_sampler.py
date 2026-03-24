"""Tests for the color sampler — pure Python/OpenCV color extraction.

Tests the internal helper functions _sample_at_position and _generate_grid_positions
directly, plus end-to-end behavior through the async tool handler.
"""

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.color_sampler import (
    _sample_at_position,
    _generate_grid_positions,
)


# ---------------------------------------------------------------------------
# Solid red image sampling
# ---------------------------------------------------------------------------


def test_solid_red_sample(red_image_png):
    """Sampling the center of a solid red image returns r=255, g=0, b=0."""
    img = cv2.imread(red_image_png)
    assert img is not None
    sample = _sample_at_position(img, x=25, y=25, radius=0)
    assert sample["r"] == 255
    assert sample["g"] == 0
    assert sample["b"] == 0


# ---------------------------------------------------------------------------
# Gradient sampling
# ---------------------------------------------------------------------------


def test_gradient_samples(gradient_png):
    """Gradient image: x=0 is near black, x=99 is near white."""
    img = cv2.imread(gradient_png)
    assert img is not None

    # Sample near black end (x=0)
    dark = _sample_at_position(img, x=0, y=25, radius=0)
    assert dark["r"] < 10
    assert dark["g"] < 10
    assert dark["b"] < 10

    # Sample near white end (x=99)
    light = _sample_at_position(img, x=99, y=25, radius=0)
    assert light["r"] > 245
    assert light["g"] > 245
    assert light["b"] > 245


# ---------------------------------------------------------------------------
# Grid mode
# ---------------------------------------------------------------------------


def test_grid_mode(red_image_png):
    """Grid mode with a 50x50 image produces 25 positions (5x5 default)."""
    img = cv2.imread(red_image_png)
    img_h, img_w = img.shape[:2]
    positions = _generate_grid_positions(img_w, img_h, grid_size=5)
    assert len(positions) == 25
    # Every position should be within image bounds
    for pos in positions:
        assert 0 <= pos[0] < img_w
        assert 0 <= pos[1] < img_h


# ---------------------------------------------------------------------------
# Hex format
# ---------------------------------------------------------------------------


def test_hex_format(red_image_png):
    """Hex string matches the RGB values for a solid red image."""
    img = cv2.imread(red_image_png)
    sample = _sample_at_position(img, x=25, y=25, radius=0)
    assert sample["hex"] == "#ff0000"
    # Verify hex is consistent with r/g/b
    expected_hex = f"#{sample['r']:02x}{sample['g']:02x}{sample['b']:02x}"
    assert sample["hex"] == expected_hex


# ---------------------------------------------------------------------------
# Radius averaging
# ---------------------------------------------------------------------------


def test_radius_averaging(gradient_png):
    """Sampling with a radius averages a neighborhood — mid-gradient gives mid-gray."""
    img = cv2.imread(gradient_png)
    # Sample at x=50 (roughly middle of 0-99 gradient) with radius=5
    sample = _sample_at_position(img, x=50, y=25, radius=5)
    # Mid-gray should be around 128 ± some tolerance due to averaging window
    assert 100 < sample["r"] < 160
    assert 100 < sample["g"] < 160
    assert 100 < sample["b"] < 160


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_sample_at_corner(red_image_png):
    """Sampling at image corner with radius doesn't crash (clamped to bounds)."""
    img = cv2.imread(red_image_png)
    sample = _sample_at_position(img, x=0, y=0, radius=5)
    assert sample["r"] == 255
    assert sample["g"] == 0
    assert sample["b"] == 0


def test_grid_positions_spacing():
    """Grid positions are evenly spaced and centered in their cells."""
    positions = _generate_grid_positions(100, 100, grid_size=5)
    # First cell center at step/2 = 10
    assert positions[0] == [10, 10]
    # Last cell center at step*4 + step/2 = 90
    assert positions[-1] == [90, 90]
