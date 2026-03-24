"""Tests for the Rive-ready SVG export tool.

Verifies CSS-to-presentation conversion, unsupported feature stripping,
and SVG validation for Rive compatibility.
All tests are pure Python — no Rive runtime required.
"""

import pytest

from adobe_mcp.apps.illustrator.rive_export import (
    convert_css_to_presentation,
    strip_unsupported_rive,
    validate_rive_svg,
)


# ---------------------------------------------------------------------------
# CSS to presentation attribute conversion
# ---------------------------------------------------------------------------


def test_convert_css_to_presentation_basic():
    """Inline CSS style should be converted to SVG presentation attributes."""
    svg = '<rect style="fill: red; stroke: blue; stroke-width: 2" />'

    result = convert_css_to_presentation(svg)

    assert 'fill="red"' in result
    assert 'stroke="blue"' in result
    assert 'stroke-width="2"' in result
    # Original style attribute should be gone (all props were convertible)
    assert 'style=' not in result


def test_convert_css_to_presentation_mixed():
    """CSS with both supported and unsupported properties."""
    svg = '<text style="fill: black; font-family: Arial; cursor: pointer" />'

    result = convert_css_to_presentation(svg)

    # Supported CSS properties become presentation attributes
    assert 'fill="black"' in result
    assert 'font-family="Arial"' in result
    # Unsupported CSS properties stay in a reduced style attribute
    assert 'cursor: pointer' in result


def test_convert_css_preserves_existing_attributes():
    """Conversion should not damage existing presentation attributes."""
    svg = '<rect fill="green" style="stroke: red" />'

    result = convert_css_to_presentation(svg)

    # Existing fill should be unchanged
    assert 'fill="green"' in result
    # Style stroke should become presentation attribute
    assert 'stroke="red"' in result


# ---------------------------------------------------------------------------
# Stripping unsupported features
# ---------------------------------------------------------------------------


def test_strip_gradient_strokes():
    """Gradient strokes should be replaced with flat black."""
    svg = '<path stroke="url(#myGradient)" fill="red" />'

    result = strip_unsupported_rive(svg)

    assert 'url(#myGradient)' not in result
    assert 'stroke="#000000"' in result
    # fill should be unchanged
    assert 'fill="red"' in result


def test_strip_filter_elements():
    """SVG filter elements and attributes should be removed."""
    svg = '''<svg>
        <defs>
            <filter id="blur"><feGaussianBlur stdDeviation="5"/></filter>
        </defs>
        <rect filter="url(#blur)" fill="red" />
    </svg>'''

    result = strip_unsupported_rive(svg)

    assert '<filter' not in result
    assert 'feGaussianBlur' not in result
    assert 'filter="url(#blur)"' not in result
    # Content should survive
    assert 'fill="red"' in result


def test_strip_skew_transforms():
    """Skew transforms should be removed."""
    svg = '<g transform="translate(10,20) skewX(15) rotate(30)">'

    result = strip_unsupported_rive(svg)

    assert 'skewX' not in result
    # Other transforms should remain
    assert 'translate(10,20)' in result
    assert 'rotate(30)' in result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_clean_svg():
    """Clean SVG without unsupported features should validate."""
    svg = '<svg><rect fill="red" stroke="blue" stroke-width="2" /></svg>'

    result = validate_rive_svg(svg)

    assert result["valid"] is True
    assert result["issue_count"] == 0


def test_validate_svg_with_issues():
    """SVG with unsupported features should report issues."""
    svg = '''<svg>
        <filter id="f1"><feBlend mode="multiply"/></filter>
        <rect filter="url(#f1)" stroke="url(#grad)" />
    </svg>'''

    result = validate_rive_svg(svg)

    assert result["valid"] is False
    assert result["issue_count"] > 0

    issue_features = [i["feature"] for i in result["issues"]]
    # Should detect filter-related issues
    assert any("filter" in f for f in issue_features)
