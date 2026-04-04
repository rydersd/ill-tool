"""Tests for the OpenCV reference-image analysis pipeline.

Covers shape classification, edge measurement, and the full _analyze_image pipeline
using synthetic fixtures from conftest.py.
"""

import json

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.ml_vision.analyze_reference import (
    _classify_shape,
    _edge_lengths,
    _edge_ratios,
    _analyze_image,
)
from adobe_mcp.apps.illustrator.models import AiAnalyzeReferenceInput


# ---------------------------------------------------------------------------
# _classify_shape
# ---------------------------------------------------------------------------


def test_classify_triangle():
    assert _classify_shape(3, 100, 100) == "triangle"


def test_classify_square():
    # aspect = 95/100 = 0.95 > 0.9 → square
    assert _classify_shape(4, 100, 95) == "square"


def test_classify_rectangle():
    # aspect = 100/200 = 0.5, which is > 0.4 → rectangle
    assert _classify_shape(4, 200, 100) == "rectangle"


def test_classify_hexagon():
    assert _classify_shape(6, 100, 100) == "hexagon"


def test_classify_circle():
    # >8 vertices → circle/ellipse
    assert _classify_shape(12, 100, 100) == "circle/ellipse"


# ---------------------------------------------------------------------------
# _edge_lengths
# ---------------------------------------------------------------------------


def test_edge_lengths_triangle():
    # Equilateral triangle with side length 100
    pts = np.array([[0, 0], [100, 0], [50, 87]], dtype=np.float32).reshape(-1, 1, 2)
    lengths = _edge_lengths(pts)
    assert len(lengths) == 3
    # All edges should be approximately equal (~100)
    assert all(abs(l - lengths[0]) < 5 for l in lengths)


# ---------------------------------------------------------------------------
# _edge_ratios
# ---------------------------------------------------------------------------


def test_edge_ratios_uniform():
    # Equal lengths → all ratios = 1.0
    lengths = [100.0, 100.0, 100.0]
    ratios = _edge_ratios(lengths)
    assert ratios == [1.0, 1.0, 1.0]


def test_edge_ratios_varied():
    # max = 200 → ratios are length/200
    lengths = [100.0, 200.0, 50.0]
    ratios = _edge_ratios(lengths)
    assert ratios == [0.5, 1.0, 0.25]


# ---------------------------------------------------------------------------
# _analyze_image — full pipeline with fixtures
# ---------------------------------------------------------------------------


def test_basic_rect_analysis(white_rect_png):
    params = AiAnalyzeReferenceInput(image_path=white_rect_png)
    result = _analyze_image(params)
    assert "error" not in result
    assert result["shapes_returned"] >= 1
    shape_type = result["shapes"][0]["type"]
    assert shape_type in ("rectangle", "square")


def test_circle_analysis(white_circle_png):
    params = AiAnalyzeReferenceInput(image_path=white_circle_png)
    result = _analyze_image(params)
    assert "error" not in result
    assert result["shapes_returned"] >= 1
    shape = result["shapes"][0]
    # Circle approximation yields many vertices or is classified as circle/ellipse
    assert shape["type"] == "circle/ellipse" or shape["vertices"] >= 8


def test_min_area_filter(white_rect_png):
    # The white rect is 60x40 = 2400 px in a 100x100 = 10000 px image → 24%.
    # Setting min_area_pct=50 should filter it out.
    params = AiAnalyzeReferenceInput(image_path=white_rect_png, min_area_pct=50)
    result = _analyze_image(params)
    assert "error" not in result
    assert result["shapes_returned"] == 0


def test_two_shapes(two_rects_png):
    params = AiAnalyzeReferenceInput(image_path=two_rects_png)
    result = _analyze_image(params)
    assert "error" not in result
    assert result["shapes_returned"] == 2


def test_missing_image():
    params = AiAnalyzeReferenceInput(image_path="/nonexistent/path/missing.png")
    result = _analyze_image(params)
    assert "error" in result


def test_multi_scale(white_rect_png):
    params = AiAnalyzeReferenceInput(image_path=white_rect_png, multi_scale=True)
    result = _analyze_image(params)
    assert "error" not in result
    assert result.get("analysis_mode") == "multi_scale"
    # Multi-scale shapes should have a "scale" key
    if result["shapes_returned"] > 0:
        assert "scale" in result["shapes"][0]


def test_output_structure(white_rect_png):
    params = AiAnalyzeReferenceInput(image_path=white_rect_png)
    result = _analyze_image(params)

    # Top-level keys
    assert "image_size" in result
    assert "total_contours_found" in result
    assert "shapes_returned" in result
    assert "shapes" in result

    assert result["shapes_returned"] >= 1
    shape = result["shapes"][0]

    # Required shape keys
    expected_keys = {
        "index",
        "type",
        "vertices",
        "center",
        "width",
        "height",
        "rotation_deg",
        "area",
        "perimeter",
        "edge_lengths",
        "edge_ratios",
        "bounding_rect",
        "approx_points",
    }
    assert expected_keys.issubset(shape.keys()), (
        f"Missing keys: {expected_keys - shape.keys()}"
    )
