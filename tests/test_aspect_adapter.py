"""Tests for aspect ratio adaptation.

Verifies 16:9 to 4:3 cropping, 4:3 to 16:9 letterboxing,
and square-to-square identity.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.ui.aspect_adapter import (
    adapt_panel,
    batch_adapt,
)


# ---------------------------------------------------------------------------
# 16:9 -> 4:3 adds horizontal crop
# ---------------------------------------------------------------------------


def test_16_9_to_4_3_crops_horizontally():
    """Converting 16:9 to 4:3 (taller target) crops the sides."""
    panel = [0, 0, 1920, 1080]  # standard 16:9
    result = adapt_panel(panel, "16:9", "4:3")

    crop = result["crop_rect"]
    # The crop should be narrower than the original
    assert crop[2] < panel[2], "Crop width should be less than source width"

    # Height should stay the same (crop, not pad)
    assert crop[3] == pytest.approx(panel[3], abs=1)

    # Should NOT be letterboxed (we're cropping, not padding vertically)
    assert result["letterbox"] is False
    assert result["pillarbox"] is False


# ---------------------------------------------------------------------------
# 4:3 -> 16:9 adds letterbox (or horizontal pad)
# ---------------------------------------------------------------------------


def test_4_3_to_16_9_adds_pillarbox():
    """Converting 4:3 to 16:9 (wider target) adds horizontal padding or crops vertically."""
    panel = [0, 0, 1024, 768]  # standard 4:3
    result = adapt_panel(panel, "4:3", "16:9")

    # Target is wider than source, so we either crop vertically or add pillarbox
    # 4:3 = 1.333, 16:9 = 1.778 -> target is wider
    # new_h = 1024 / 1.778 = 575.8 < 768 -> crop vertically
    crop = result["crop_rect"]
    assert crop[3] < panel[3], "Should crop height for wider target"


# ---------------------------------------------------------------------------
# Square to square: no change
# ---------------------------------------------------------------------------


def test_square_to_square_no_change():
    """Adapting square to square produces identity (no crop, no pad)."""
    panel = [0, 0, 500, 500]
    result = adapt_panel(panel, "1:1", "1:1")

    assert result["crop_rect"] == [0, 0, 500, 500], "Square to square should be identity"
    assert result["scale"] == pytest.approx(1.0)
    assert result["letterbox"] is False
    assert result["pillarbox"] is False
    assert result["pad_top"] == 0.0
    assert result["pad_bottom"] == 0.0
    assert result["pad_left"] == 0.0
    assert result["pad_right"] == 0.0
