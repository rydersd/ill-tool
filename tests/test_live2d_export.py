"""Tests for the Live2D PSD layer naming export tool.

Verifies layer mapping, convention coverage, and structure validation.
All tests are pure Python — no Live2D SDK required.
"""

import pytest

from adobe_mcp.apps.illustrator.live2d_export import (
    LIVE2D_CONVENTIONS,
    rig_to_live2d_layers,
    validate_live2d_structure,
)


# ---------------------------------------------------------------------------
# Layer mapping
# ---------------------------------------------------------------------------


def test_layer_mapping_basic_body_parts():
    """Common body parts should map to correct Live2D layer names."""
    rig = {
        "body_part_labels": {
            "head": {"bounds": [0, 0, 100, 100]},
            "left_eye": {"bounds": [20, 20, 40, 35]},
            "right_eye": {"bounds": [60, 20, 80, 35]},
            "mouth": {"bounds": [35, 50, 65, 65]},
            "torso": {"bounds": [10, 100, 90, 300]},
            "left_arm": {"bounds": [0, 120, 10, 250]},
            "right_arm": {"bounds": [90, 120, 100, 250]},
        },
        "bindings": {},
    }

    result = rig_to_live2d_layers(rig)

    layer_map = result["layer_map"]

    # Check specific mappings
    assert layer_map["head"] == "face"
    assert layer_map["left_eye"] == "eye_l"
    assert layer_map["right_eye"] == "eye_r"
    assert layer_map["mouth"] == "mouth"
    assert layer_map["torso"] == "body"
    assert layer_map["left_arm"] == "arm_l"
    assert layer_map["right_arm"] == "arm_r"

    # All parts should be mapped (none unmapped for standard names)
    assert result["total_unmapped"] == 0


def test_layer_mapping_groups_organized():
    """Mapped layers should be organized into Live2D groups."""
    rig = {
        "body_part_labels": {
            "face": {},
            "left_eye": {},
            "right_eye": {},
            "mouth": {},
            "torso": {},
            "neck": {},
        },
        "bindings": {},
    }

    result = rig_to_live2d_layers(rig)

    groups = result["groups"]

    # Face group should contain face, eye, mouth layers
    assert "face" in groups
    face_layers = groups["face"]
    assert "face" in face_layers
    assert "eye_l" in face_layers
    assert "eye_r" in face_layers
    assert "mouth" in face_layers

    # Body group should contain body, neck
    assert "body" in groups
    assert "body" in groups["body"]
    assert "neck" in groups["body"]


def test_layer_mapping_unmapped_parts():
    """Non-standard part names should appear in unmapped list."""
    rig = {
        "body_part_labels": {
            "custom_widget": {},
            "head": {},
        },
        "bindings": {},
    }

    result = rig_to_live2d_layers(rig)

    # "custom_widget" has no Live2D convention
    assert result["total_unmapped"] == 1
    assert "custom_widget" in result["unmapped"]


# ---------------------------------------------------------------------------
# Convention coverage
# ---------------------------------------------------------------------------


def test_conventions_cover_standard_parts():
    """LIVE2D_CONVENTIONS should map all common body parts."""
    standard_parts = [
        "head", "face", "left_eye", "right_eye", "mouth",
        "torso", "body", "neck",
        "left_arm", "right_arm", "left_leg", "right_leg",
    ]

    for part in standard_parts:
        assert part in LIVE2D_CONVENTIONS, f"Missing convention for: {part}"


# ---------------------------------------------------------------------------
# Structure validation
# ---------------------------------------------------------------------------


def test_validate_complete_structure():
    """Structure with all required groups should validate."""
    layer_map = {
        "head": "face",
        "left_eye": "eye_l",
        "right_eye": "eye_r",
        "mouth": "mouth",
        "torso": "body",
    }

    result = validate_live2d_structure(layer_map)

    assert result["valid"] is True
    assert "face" in result["present_groups"]
    assert "eyes" in result["present_groups"]
    assert "mouth" in result["present_groups"]
    assert "body" in result["present_groups"]
    assert len(result["missing_groups"]) == 0


def test_validate_missing_groups():
    """Structure missing required groups should fail validation."""
    # Only has body, missing face, eyes, mouth
    layer_map = {
        "torso": "body",
    }

    result = validate_live2d_structure(layer_map)

    assert result["valid"] is False
    assert "face" in result["missing_groups"]
    assert "eyes" in result["missing_groups"]
    assert "mouth" in result["missing_groups"]


def test_validate_accepts_result_dict():
    """Validation should accept the full result dict from rig_to_live2d_layers."""
    rig = {
        "body_part_labels": {
            "face": {},
            "left_eye": {},
            "right_eye": {},
            "mouth": {},
            "torso": {},
        },
        "bindings": {},
    }

    layer_result = rig_to_live2d_layers(rig)
    validation = validate_live2d_structure(layer_result)

    assert validation["valid"] is True
