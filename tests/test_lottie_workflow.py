"""Tests for the Lottie workflow pipeline helper.

Verifies Bodymovin compatibility checking, settings generation,
and Lottie JSON optimization.
All tests are pure Python — no AE or Bodymovin dep required.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.lottie_workflow import (
    check_bodymovin_compatibility,
    generate_bodymovin_settings,
    optimize_lottie,
)


# ---------------------------------------------------------------------------
# Compatibility checking
# ---------------------------------------------------------------------------


def test_check_compatible_comp():
    """Composition with only supported features should pass."""
    comp_info = {
        "layers": [
            {"name": "bg", "type": "shape", "blend_mode": "normal"},
            {"name": "character", "type": "shape", "blend_mode": "multiply"},
        ],
        "effects": [],
    }

    result = check_bodymovin_compatibility(comp_info)

    assert result["compatible"] is True
    assert result["error_count"] == 0
    assert result["layer_count"] == 2


def test_check_incompatible_3d_layers():
    """3D layers should be flagged as errors."""
    comp_info = {
        "layers": [
            {"name": "3d_object", "type": "shape", "is_3d": True},
        ],
        "effects": [],
    }

    result = check_bodymovin_compatibility(comp_info)

    assert result["compatible"] is False
    assert result["error_count"] >= 1
    assert any("3D" in e for e in result["errors"])


def test_check_unsupported_blend_mode_warns():
    """Unsupported blend modes should produce warnings (not errors)."""
    comp_info = {
        "layers": [
            {"name": "glow", "type": "shape", "blend_mode": "color_burn"},
        ],
        "effects": [],
    }

    result = check_bodymovin_compatibility(comp_info)

    # Blend mode issues are warnings, not errors
    assert result["warning_count"] >= 1
    assert any("color_burn" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Settings generation
# ---------------------------------------------------------------------------


def test_generate_settings_structure():
    """Generated settings should have correct Bodymovin structure."""
    settings = generate_bodymovin_settings(
        comp_name="MainComp",
        output_path="/tmp/output/animation.json",
    )

    assert settings["bm_export"]["comp_name"] == "MainComp"
    assert settings["bm_export"]["destination"] == "/tmp/output/animation.json"
    assert settings["bm_renderer"] == "svg"
    assert settings["bm_settings"]["standalone"] is True
    assert settings["bm_settings"]["glyphs"] is True
    assert "bm_version" in settings


def test_generate_settings_with_options():
    """Custom options should override defaults."""
    settings = generate_bodymovin_settings(
        comp_name="TestComp",
        output_path="/out/test.json",
        options={
            "renderer": "canvas",
            "compress": True,
            "standalone": False,
        },
    )

    assert settings["bm_renderer"] == "canvas"
    assert settings["bm_settings"]["should_compress"] is True
    assert settings["bm_settings"]["standalone"] is False


# ---------------------------------------------------------------------------
# Lottie JSON optimization
# ---------------------------------------------------------------------------


def test_optimize_rounds_floats():
    """Optimization should round float values to specified precision."""
    lottie = {
        "v": "5.7.0",
        "fr": 30,
        "layers": [
            {
                "ks": {
                    "p": {"k": [100.123456789, 200.987654321, 0]},
                    "s": {"k": [100.0, 100.0, 100.0]},
                }
            }
        ],
    }

    result = optimize_lottie(lottie, precision=2)

    pos = result["layers"][0]["ks"]["p"]["k"]
    assert pos[0] == 100.12
    assert pos[1] == 200.99


def test_optimize_strips_empty_properties():
    """Optimization should remove null and empty properties."""
    lottie = {
        "v": "5.7.0",
        "nm": "Animation",
        "layers": [],
        "assets": [],
        "meta": None,
        "empty_dict": {},
    }

    result = optimize_lottie(lottie)

    # Empty lists, None, and empty dicts should be stripped
    assert "meta" not in result
    assert "empty_dict" not in result
    # Non-empty string should remain
    assert result["v"] == "5.7.0"


def test_optimize_preserves_structure():
    """Optimization should not break valid Lottie structure."""
    lottie = {
        "v": "5.7.0",
        "fr": 24,
        "ip": 0,
        "op": 120,
        "w": 1920,
        "h": 1080,
        "layers": [
            {
                "ty": 4,
                "nm": "Shape",
                "ks": {"o": {"k": 100}},
                "shapes": [{"ty": "rc", "s": {"k": [200.0, 200.0]}}],
            }
        ],
    }

    result = optimize_lottie(lottie, precision=1)

    # Core structure should be intact
    assert result["v"] == "5.7.0"
    assert result["fr"] == 24
    assert result["w"] == 1920
    assert len(result["layers"]) == 1
    assert result["layers"][0]["ty"] == 4

    # Serialization should succeed
    json_str = json.dumps(result)
    assert len(json_str) > 0
