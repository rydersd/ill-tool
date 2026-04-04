"""Tests for CartoonSegmentation ML tool.

All tests work WITHOUT ML dependencies (torch, transformers) installed.
Validates graceful fallback, pure Python conversion, and status check.
"""

import json
from unittest.mock import patch

import pytest

from adobe_mcp.apps.illustrator.ml_vision.segment_ml import (
    ML_AVAILABLE,
    PART_LABELS,
    _ml_status,
    _segment_image,
    masks_to_parts,
    SegmentMLInput,
)


# ---------------------------------------------------------------------------
# test_status: structure is correct regardless of ML availability
# ---------------------------------------------------------------------------


def test_status():
    """_ml_status returns correct structure with part labels and availability."""
    status = _ml_status()

    assert "ml_available" in status
    assert "model" in status
    assert "supported_parts" in status
    assert "part_count" in status
    assert status["part_count"] == len(PART_LABELS)
    assert isinstance(status["supported_parts"], list)
    assert "body" in status["supported_parts"]
    assert "head" in status["supported_parts"]

    if not ML_AVAILABLE:
        assert status["ml_available"] is False
        assert "install_hint" in status
        assert status["device"] == "unavailable"
    else:
        assert status["device"] in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# test_masks_to_parts: pure Python conversion function
# ---------------------------------------------------------------------------


def test_masks_to_parts():
    """masks_to_parts correctly converts model output to parts format.

    Pure Python test — no ML dependencies needed.
    """
    # Create simple test masks (5x5 binary)
    mask_body = [
        [0, 0, 0, 0, 0],
        [0, 1, 1, 1, 0],
        [0, 1, 1, 1, 0],
        [0, 1, 1, 1, 0],
        [0, 0, 0, 0, 0],
    ]
    mask_head = [
        [0, 1, 1, 1, 0],
        [0, 1, 1, 1, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ]

    masks = [mask_body, mask_head]
    scores = [0.95, 0.80]
    labels = [1, 2]  # body=1, head=2 in PART_LABELS

    result = masks_to_parts(masks, scores, labels, min_score=0.5)

    assert len(result) == 2

    # Body part
    body = result[0]
    assert body["label"] == "body"
    assert body["score"] == 0.95
    assert body["pixel_count"] == 9  # 3x3 block
    assert body["bbox"] is not None
    assert body["bbox"]["x"] == 1
    assert body["bbox"]["y"] == 1
    assert body["bbox"]["width"] == 3
    assert body["bbox"]["height"] == 3

    # Head part
    head = result[1]
    assert head["label"] == "head"
    assert head["score"] == 0.80
    assert head["pixel_count"] == 6  # 3x2 block

    # Test filtering by min_score
    filtered = masks_to_parts(masks, [0.95, 0.30], labels, min_score=0.5)
    assert len(filtered) == 1  # Only body passes threshold
    assert filtered[0]["label"] == "body"


# ---------------------------------------------------------------------------
# test_graceful_fallback: segment without ML returns helpful error
# ---------------------------------------------------------------------------


def test_graceful_fallback():
    """_segment_image without ML deps returns error with install instructions."""
    with patch("adobe_mcp.apps.illustrator.ml_vision.segment_ml.ML_AVAILABLE", False):
        result = _segment_image("/tmp/test.png", 0.5)

    assert "error" in result
    assert "not installed" in result["error"].lower()
    assert "install_hint" in result
    assert "required_packages" in result
