"""Tests for the vtracer raster-to-SVG conversion pipeline.

Tests the vtracer library directly (not the MCP tool handler) to verify
SVG output structure, path generation, and error handling.
"""

import os
import re
import tempfile

import pytest
import vtracer


# ---------------------------------------------------------------------------
# Helper — vtracer writes to a file, so we read it back
# ---------------------------------------------------------------------------


def _run_vtrace(image_path: str, **kwargs) -> str:
    """Run vtracer with out_path and return the SVG content as a string."""
    out_path = tempfile.mktemp(suffix=".svg", prefix="vtrace_test_")
    vtracer.convert_image_to_svg_py(
        image_path=image_path,
        out_path=out_path,
        colormode=kwargs.get("colormode", "color"),
        hierarchical=kwargs.get("hierarchical", "stacked"),
        mode=kwargs.get("mode", "polygon"),
        filter_speckle=kwargs.get("filter_speckle", 4),
        color_precision=kwargs.get("color_precision", 6),
        layer_difference=kwargs.get("layer_difference", 25),
        corner_threshold=kwargs.get("corner_threshold", 60),
        length_threshold=kwargs.get("length_threshold", 4.0),
        max_iterations=kwargs.get("max_iterations", 10),
        splice_threshold=kwargs.get("splice_threshold", 45),
        path_precision=kwargs.get("path_precision", 3),
    )
    with open(out_path) as f:
        svg = f.read()
    os.unlink(out_path)
    return svg


# ---------------------------------------------------------------------------
# Basic conversion
# ---------------------------------------------------------------------------


def test_basic_conversion(white_rect_png):
    """vtracer produces an SVG string containing <svg and <path tags."""
    svg = _run_vtrace(white_rect_png)
    assert isinstance(svg, str)
    assert "<svg" in svg
    assert "<path" in svg


def test_dimensions_present(white_rect_png):
    """SVG output includes width and height attributes for proper scaling."""
    svg = _run_vtrace(white_rect_png)
    assert re.search(r'width="[^"]*"', svg) is not None
    assert re.search(r'height="[^"]*"', svg) is not None


def test_path_count_nonzero(white_rect_png):
    """SVG contains at least one <path element."""
    svg = _run_vtrace(white_rect_png)
    path_count = len(re.findall(r"<path", svg))
    assert path_count > 0


def test_missing_image():
    """vtracer panics (raises pyo3 PanicException) when given a nonexistent image path."""
    out_path = tempfile.mktemp(suffix=".svg", prefix="vtrace_missing_")
    with pytest.raises(BaseException):
        vtracer.convert_image_to_svg_py(
            image_path="/tmp/nonexistent_vtrace_test_image.png",
            out_path=out_path,
            colormode="color",
            hierarchical="stacked",
            mode="polygon",
            filter_speckle=4,
            color_precision=6,
            layer_difference=25,
            corner_threshold=60,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3,
        )


@pytest.mark.parametrize("mode", ["polygon", "spline"])
def test_polygon_vs_spline(white_rect_png, mode):
    """Both polygon and spline modes produce valid SVG with paths."""
    svg = _run_vtrace(white_rect_png, mode=mode)
    assert "<svg" in svg
    assert "<path" in svg
