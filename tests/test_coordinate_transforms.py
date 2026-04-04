"""Tests for coordinate_transforms — pixel <-> Illustrator coordinate conversion."""

import math

import pytest

from adobe_mcp.apps.illustrator.coordinate_transforms import (
    TransformContext,
    ai_to_pixel,
    parse_artboard_result,
    pixel_to_ai,
    query_artboard_jsx,
)

EPS = 0.001  # tolerance for floating-point comparisons


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_close(a: tuple, b: tuple, *, eps: float = EPS) -> None:
    """Assert two 2-tuples are element-wise within *eps*."""
    assert abs(a[0] - b[0]) < eps, f"x mismatch: {a[0]} vs {b[0]}"
    assert abs(a[1] - b[1]) < eps, f"y mismatch: {a[1]} vs {b[1]}"


# ---------------------------------------------------------------------------
# 1. Round-trip identity
# ---------------------------------------------------------------------------


_ARTBOARDS = [
    # (ab_left, ab_top, ab_right, ab_bottom, img_w, img_h)
    (0, 792, 612, 0, 100, 100),  # US Letter
    (0, 0, 758, -1052, 758, 1052),  # GIR (Y-negative)
    (0, 1272, 952, 0, 952, 1272),  # Mech
    (100, 900, 700, 300, 600, 600),  # Non-origin offset
    (0, 792, 612, 0, 200, 50),  # Wide image on tall artboard
    (0, 500, 1000, 0, 100, 100),  # Wide artboard on square image
]

_PIXEL_POINTS = [(0, 0), (50, 50), (99, 99), (25, 75), (0, 99), (99, 0)]


@pytest.mark.parametrize("ab", _ARTBOARDS, ids=[
    "us-letter", "gir", "mech", "offset", "wide-img", "wide-ab",
])
@pytest.mark.parametrize("px,py", _PIXEL_POINTS, ids=[
    "origin", "center-ish", "corner", "quarter", "left-bottom", "right-top",
])
def test_round_trip_identity(ab, px, py):
    """pixel -> AI -> pixel should return the original pixel coordinate."""
    ctx = TransformContext(*ab)
    ai = pixel_to_ai(px, py, ctx)
    back = ai_to_pixel(*ai, ctx)
    _assert_close(back, (px, py))


# ---------------------------------------------------------------------------
# 2. Standard US Letter artboard (612 x 792)
# ---------------------------------------------------------------------------


class TestUSLetter:
    """US Letter: ab = (0, 792, 612, 0), image 100x100."""

    @pytest.fixture()
    def ctx(self) -> TransformContext:
        return TransformContext(0, 792, 612, 0, 100, 100)

    def test_pixel_origin_maps_near_top_left(self, ctx):
        ai_x, ai_y = pixel_to_ai(0, 0, ctx)
        # Image is square (100x100), artboard is 612x792 => scale = 6.12
        # Image centred: offset_x = (612 - 612) / 2 = 0
        #                offset_y = 792 - (792 - 612) / 2 = 792 - 90 = 702
        # So origin -> (0, 702)  (not the very top because of centering)
        assert ai_x == pytest.approx(0.0, abs=EPS)
        assert ai_y == pytest.approx(ctx.offset_y, abs=EPS)

    def test_pixel_100_100_maps_near_bottom_right(self, ctx):
        ai_x, ai_y = pixel_to_ai(100, 100, ctx)
        # ai_x = 100 * 6.12 + 0 = 612
        # ai_y = 702 - 100 * 6.12 = 702 - 612 = 90
        assert ai_x == pytest.approx(612.0, abs=EPS)
        assert ai_y == pytest.approx(ctx.offset_y - 100 * ctx.scale, abs=EPS)

    def test_pixel_center_maps_to_artboard_center(self, ctx):
        ai_x, ai_y = pixel_to_ai(50, 50, ctx)
        # Center of image -> center of the mapped region
        expected_x = 50 * ctx.scale + ctx.offset_x
        expected_y = ctx.offset_y - 50 * ctx.scale
        assert ai_x == pytest.approx(expected_x, abs=EPS)
        assert ai_y == pytest.approx(expected_y, abs=EPS)


# ---------------------------------------------------------------------------
# 3. GIR artboard (Y goes negative)
# ---------------------------------------------------------------------------


class TestGIRArtboard:
    """GIR: ab = (0, 0, 758, -1052), image 758x1052."""

    @pytest.fixture()
    def ctx(self) -> TransformContext:
        return TransformContext(0, 0, 758, -1052, 758, 1052)

    def test_scale_is_one(self, ctx):
        # Image exactly matches artboard dimensions => scale = 1.0
        assert ctx.scale == pytest.approx(1.0, abs=EPS)

    def test_ab_height_positive(self, ctx):
        # ab_height = top - bottom = 0 - (-1052) = 1052
        assert ctx.ab_height == pytest.approx(1052.0, abs=EPS)

    def test_pixel_origin_maps_to_ai_origin(self, ctx):
        ai_x, ai_y = pixel_to_ai(0, 0, ctx)
        assert ai_x == pytest.approx(0.0, abs=EPS)
        assert ai_y == pytest.approx(0.0, abs=EPS)

    def test_pixel_bottom_right(self, ctx):
        ai_x, ai_y = pixel_to_ai(758, 1052, ctx)
        assert ai_x == pytest.approx(758.0, abs=EPS)
        assert ai_y == pytest.approx(-1052.0, abs=EPS)

    def test_round_trip(self, ctx):
        for px, py in [(0, 0), (379, 526), (758, 1052)]:
            ai = pixel_to_ai(px, py, ctx)
            back = ai_to_pixel(*ai, ctx)
            _assert_close(back, (px, py))


# ---------------------------------------------------------------------------
# 4. Mech artboard
# ---------------------------------------------------------------------------


class TestMechArtboard:
    """Mech: ab = (0, 1272, 952, 0), image 952x1272."""

    @pytest.fixture()
    def ctx(self) -> TransformContext:
        return TransformContext(0, 1272, 952, 0, 952, 1272)

    def test_scale_is_one(self, ctx):
        assert ctx.scale == pytest.approx(1.0, abs=EPS)

    def test_pixel_origin_maps_to_top_left(self, ctx):
        ai_x, ai_y = pixel_to_ai(0, 0, ctx)
        assert ai_x == pytest.approx(0.0, abs=EPS)
        assert ai_y == pytest.approx(1272.0, abs=EPS)

    def test_pixel_bottom_right(self, ctx):
        ai_x, ai_y = pixel_to_ai(952, 1272, ctx)
        assert ai_x == pytest.approx(952.0, abs=EPS)
        assert ai_y == pytest.approx(0.0, abs=EPS)

    def test_round_trip(self, ctx):
        for px, py in [(0, 0), (476, 636), (952, 1272)]:
            ai = pixel_to_ai(px, py, ctx)
            back = ai_to_pixel(*ai, ctx)
            _assert_close(back, (px, py))


# ---------------------------------------------------------------------------
# 5. Non-origin offset artboard
# ---------------------------------------------------------------------------


class TestNonOriginOffset:
    """Offset: ab = (100, 900, 700, 300), image 600x600."""

    @pytest.fixture()
    def ctx(self) -> TransformContext:
        return TransformContext(100, 900, 700, 300, 600, 600)

    def test_dimensions(self, ctx):
        assert ctx.ab_width == pytest.approx(600.0, abs=EPS)
        assert ctx.ab_height == pytest.approx(600.0, abs=EPS)

    def test_scale_is_one(self, ctx):
        # 600x600 artboard, 600x600 image => scale = 1.0
        assert ctx.scale == pytest.approx(1.0, abs=EPS)

    def test_centered_placement(self, ctx):
        # Offsets should centre the image on the artboard
        assert ctx.offset_x == pytest.approx(100.0, abs=EPS)
        assert ctx.offset_y == pytest.approx(900.0, abs=EPS)

    def test_pixel_origin_maps_to_top_left_of_artboard(self, ctx):
        ai_x, ai_y = pixel_to_ai(0, 0, ctx)
        assert ai_x == pytest.approx(100.0, abs=EPS)
        assert ai_y == pytest.approx(900.0, abs=EPS)

    def test_pixel_bottom_right(self, ctx):
        ai_x, ai_y = pixel_to_ai(600, 600, ctx)
        assert ai_x == pytest.approx(700.0, abs=EPS)
        assert ai_y == pytest.approx(300.0, abs=EPS)

    def test_round_trip(self, ctx):
        for px, py in [(0, 0), (300, 300), (600, 600)]:
            ai = pixel_to_ai(px, py, ctx)
            back = ai_to_pixel(*ai, ctx)
            _assert_close(back, (px, py))


# ---------------------------------------------------------------------------
# 6. Zero-size image (edge case)
# ---------------------------------------------------------------------------


class TestZeroSizeImage:
    """img_width=0, img_height=0 should not crash; scale defaults to 1.0."""

    @pytest.fixture()
    def ctx(self) -> TransformContext:
        return TransformContext(0, 792, 612, 0, 0, 0)

    def test_scale_is_one(self, ctx):
        assert ctx.scale == pytest.approx(1.0, abs=EPS)

    def test_pixel_to_ai_does_not_crash(self, ctx):
        # Should return something without raising
        result = pixel_to_ai(50, 50, ctx)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_ai_to_pixel_does_not_crash(self, ctx):
        result = ai_to_pixel(100, 200, ctx)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 7. parse_artboard_result
# ---------------------------------------------------------------------------


class TestParseArtboardResult:
    def test_valid_input(self):
        ctx = parse_artboard_result("0|792|612|0", 100, 100)
        assert ctx.ab_left == pytest.approx(0.0)
        assert ctx.ab_top == pytest.approx(792.0)
        assert ctx.ab_right == pytest.approx(612.0)
        assert ctx.ab_bottom == pytest.approx(0.0)
        assert ctx.img_width == 100
        assert ctx.img_height == 100

    def test_valid_input_with_whitespace(self):
        ctx = parse_artboard_result("  0|792|612|0  \n", 50, 50)
        assert ctx.ab_left == pytest.approx(0.0)

    def test_negative_values(self):
        ctx = parse_artboard_result("0|0|758|-1052", 758, 1052)
        assert ctx.ab_bottom == pytest.approx(-1052.0)

    def test_float_values(self):
        ctx = parse_artboard_result("0.5|792.3|612.1|0.7", 100, 100)
        assert ctx.ab_left == pytest.approx(0.5)
        assert ctx.ab_top == pytest.approx(792.3)

    def test_invalid_too_few_parts(self):
        with pytest.raises(ValueError, match="Expected 4"):
            parse_artboard_result("0|792|612", 100, 100)

    def test_invalid_too_many_parts(self):
        with pytest.raises(ValueError, match="Expected 4"):
            parse_artboard_result("0|792|612|0|999", 100, 100)

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="Expected 4"):
            parse_artboard_result("", 100, 100)

    def test_invalid_non_numeric(self):
        with pytest.raises(ValueError):
            parse_artboard_result("a|b|c|d", 100, 100)


# ---------------------------------------------------------------------------
# 8. query_artboard_jsx
# ---------------------------------------------------------------------------


class TestQueryArtboardJsx:
    def test_returns_non_empty_string(self):
        jsx = query_artboard_jsx()
        assert isinstance(jsx, str)
        assert len(jsx.strip()) > 0

    def test_contains_artboard_rect(self):
        jsx = query_artboard_jsx()
        assert "artboardRect" in jsx

    def test_contains_active_document(self):
        jsx = query_artboard_jsx()
        assert "activeDocument" in jsx

    def test_uses_pipe_delimiter(self):
        jsx = query_artboard_jsx()
        assert '"|"' in jsx


# ---------------------------------------------------------------------------
# 9. Scale preserves aspect ratio
# ---------------------------------------------------------------------------


class TestScaleAspectRatio:
    """For non-square images on non-square artboards, scale = min(sx, sy)."""

    def test_wide_image_on_tall_artboard(self):
        # Artboard 612x792, image 200x50 => scale_x=3.06, scale_y=15.84 => 3.06
        ctx = TransformContext(0, 792, 612, 0, 200, 50)
        expected = min(612.0 / 200, 792.0 / 50)
        assert ctx.scale == pytest.approx(expected, abs=EPS)

    def test_tall_image_on_wide_artboard(self):
        # Artboard 1000x500, image 100x400 => scale_x=10, scale_y=1.25 => 1.25
        ctx = TransformContext(0, 500, 1000, 0, 100, 400)
        expected = min(1000.0 / 100, 500.0 / 400)
        assert ctx.scale == pytest.approx(expected, abs=EPS)

    def test_square_image_on_square_artboard(self):
        ctx = TransformContext(0, 500, 500, 0, 100, 100)
        assert ctx.scale == pytest.approx(5.0, abs=EPS)

    def test_scale_uses_abs_for_negative_artboards(self):
        # GIR-style: ab_width=758, ab_height=1052 (top=0, bottom=-1052)
        ctx = TransformContext(0, 0, 758, -1052, 758, 1052)
        sx = abs(758 / 758)
        sy = abs(1052 / 1052)
        assert ctx.scale == pytest.approx(min(sx, sy), abs=EPS)

    def test_non_matching_ratio_centres_horizontally(self):
        # Artboard 1000x500, image 100x100 => scale=5.0
        # Image mapped region: 500x500, artboard is 1000 wide
        # offset_x should centre: 0 + (1000 - 500) / 2 = 250
        ctx = TransformContext(0, 500, 1000, 0, 100, 100)
        assert ctx.offset_x == pytest.approx(250.0, abs=EPS)

    def test_non_matching_ratio_centres_vertically(self):
        # Artboard 500x1000, image 100x100 => scale=5.0
        # Image mapped region: 500x500, artboard is 1000 tall
        # offset_y = 1000 - (1000 - 500) / 2 = 1000 - 250 = 750
        ctx = TransformContext(0, 1000, 500, 0, 100, 100)
        assert ctx.offset_y == pytest.approx(750.0, abs=EPS)


# ---------------------------------------------------------------------------
# 10. Zero-artboard edge case
# ---------------------------------------------------------------------------


class TestZeroArtboard:
    def test_zero_artboard_does_not_crash(self):
        ctx = TransformContext(0, 0, 0, 0, 100, 100)
        result = pixel_to_ai(50, 50, ctx)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_subpixel_round_trip(self):
        ctx = TransformContext(0, 792, 612, 0, 100, 100)
        ai = pixel_to_ai(50.3, 75.7, ctx)
        back = ai_to_pixel(*ai, ctx)
        assert abs(back[0] - 50.3) < 0.01
        assert abs(back[1] - 75.7) < 0.01
