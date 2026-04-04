"""Coordinate transform utilities for pixel <-> Illustrator conversions.

Consolidates the Y-flip transform logic that was duplicated across
auto_correct.py, contour_to_path.py, silhouette.py, and others.

All Illustrator documents have artboards with varying coordinate systems:
  - Some: [left=0, top=0, right=W, bottom=-H] (Y goes negative downward)
  - Others: [left=0, top=H, right=W, bottom=0] (Y goes from top positive to 0)

This module handles both cases by always reading artboardRect dynamically.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class TransformContext:
    """Cached artboard geometry for coordinate conversion.

    Constructed from an Illustrator artboardRect (left, top, right, bottom)
    plus the pixel dimensions of the source image.  All derived values
    (scale, offsets) are computed on-the-fly from these six fields.
    """

    ab_left: float
    ab_top: float
    ab_right: float
    ab_bottom: float
    img_width: int
    img_height: int

    @property
    def ab_width(self) -> float:
        return self.ab_right - self.ab_left

    @property
    def ab_height(self) -> float:
        return self.ab_top - self.ab_bottom  # always positive for valid artboards

    @property
    def scale(self) -> float:
        """Uniform scale factor that preserves aspect ratio (fit-inside)."""
        if self.img_width == 0 or self.img_height == 0:
            return 1.0
        scale_x = self.ab_width / self.img_width
        scale_y = self.ab_height / self.img_height
        return min(abs(scale_x), abs(scale_y))

    @property
    def offset_x(self) -> float:
        """Horizontal offset that centres the image on the artboard."""
        return self.ab_left + (self.ab_width - self.img_width * self.scale) / 2

    @property
    def offset_y(self) -> float:
        """Vertical offset that centres the image on the artboard."""
        return self.ab_top - (self.ab_height - self.img_height * self.scale) / 2


def pixel_to_ai(
    px: float, py: float, ctx: TransformContext
) -> Tuple[float, float]:
    """Convert pixel coordinates (origin top-left) to Illustrator coordinates.

    Args:
        px: Pixel x coordinate (0 = left).
        py: Pixel y coordinate (0 = top, increases downward).
        ctx: Transform context with artboard geometry.

    Returns:
        (ai_x, ai_y) in Illustrator's coordinate system.
    """
    ai_x = px * ctx.scale + ctx.offset_x
    ai_y = ctx.offset_y - py * ctx.scale
    return (ai_x, ai_y)


def ai_to_pixel(
    ai_x: float, ai_y: float, ctx: TransformContext
) -> Tuple[float, float]:
    """Convert Illustrator coordinates to pixel coordinates.

    Args:
        ai_x: Illustrator x coordinate.
        ai_y: Illustrator y coordinate.
        ctx: Transform context with artboard geometry.

    Returns:
        (px, py) in pixel coordinates (origin top-left).
    """
    s = ctx.scale
    if s == 0:
        return (0.0, 0.0)
    px = (ai_x - ctx.offset_x) / s
    py = (ctx.offset_y - ai_y) / s
    return (px, py)


def query_artboard_jsx() -> str:
    """Return JSX code that queries the active artboard dimensions.

    When executed inside Illustrator the snippet produces a pipe-delimited
    string: ``"left|top|right|bottom"``.
    """
    return """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return ab[0] + "|" + ab[1] + "|" + ab[2] + "|" + ab[3];
})();
"""


def parse_artboard_result(
    stdout: str, img_width: int, img_height: int
) -> TransformContext:
    """Parse the JSX artboardRect result into a TransformContext.

    Args:
        stdout: Pipe-delimited string ``"left|top|right|bottom"`` from JSX.
        img_width: Width of the source image in pixels.
        img_height: Height of the source image in pixels.

    Returns:
        TransformContext ready for coordinate conversion.

    Raises:
        ValueError: If *stdout* cannot be parsed into four numbers.
    """
    parts = stdout.strip().split("|")
    if len(parts) != 4:
        raise ValueError(f"Expected 4 pipe-delimited values, got: {stdout!r}")

    return TransformContext(
        ab_left=float(parts[0]),
        ab_top=float(parts[1]),
        ab_right=float(parts[2]),
        ab_bottom=float(parts[3]),
        img_width=img_width,
        img_height=img_height,
    )
