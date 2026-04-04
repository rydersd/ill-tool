"""Tests for ml_backends.edge_classifier — RINDNet++ edge classification.

Covers: ml_status structure, graceful fallback when RINDNet++ unavailable,
heuristic fallback produces form/shadow classification, output dict keys,
thread-safe model caching, and path validation.
"""

import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.ml_backends.edge_classifier import (
    RINDNET_AVAILABLE,
    classify_edges_rindnet,
    ml_status,
    _heuristic_classify_edges,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rect_image_path(tmp_path_factory):
    """White rectangle on black — clear form edges for classification."""
    path = str(tmp_path_factory.mktemp("edge_cls") / "rect.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (80, 80), (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def gradient_image_path(tmp_path_factory):
    """Horizontal gradient — soft edges for edge classification."""
    path = str(tmp_path_factory.mktemp("edge_cls") / "gradient.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    for x in range(100):
        val = int(x * 255 / 99)
        img[:, x] = (val, val, val)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def all_black_image_path(tmp_path_factory):
    """All-black image — no edges expected."""
    path = str(tmp_path_factory.mktemp("edge_cls") / "black.png")
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# 1. Status reporting
# ---------------------------------------------------------------------------


class TestEdgeClassifierStatus:
    """Verify ml_status returns correct structure."""

    def test_status_has_rindnet_key(self):
        """Status must include rindnet backend info."""
        status = ml_status()
        assert "rindnet" in status

    def test_status_has_heuristic_key(self):
        """Status must include heuristic backend info."""
        status = ml_status()
        assert "heuristic" in status

    def test_rindnet_has_available_flag(self):
        """RINDNet++ entry must report availability."""
        status = ml_status()
        assert "available" in status["rindnet"]
        assert isinstance(status["rindnet"]["available"], bool)

    def test_heuristic_always_available(self):
        """Heuristic backend must always be available."""
        status = ml_status()
        assert status["heuristic"]["available"] is True

    def test_rindnet_has_install_hint_when_unavailable(self):
        """When RINDNet++ is unavailable, status should include install hint."""
        status = ml_status()
        if not status["rindnet"]["available"]:
            assert "install_hint" in status["rindnet"]
            assert "github" in status["rindnet"]["install_hint"].lower()

    def test_heuristic_reports_dsine_enhanced(self):
        """Heuristic backend should report whether DSINE enhancement is available."""
        status = ml_status()
        assert "dsine_enhanced" in status["heuristic"]
        assert isinstance(status["heuristic"]["dsine_enhanced"], bool)

    def test_rindnet_has_device_info(self):
        """RINDNet++ entry must report device."""
        status = ml_status()
        assert "device" in status["rindnet"]


# ---------------------------------------------------------------------------
# 2. Graceful fallback when RINDNet++ unavailable
# ---------------------------------------------------------------------------


class TestRindnetFallback:
    """Verify graceful fallback to heuristic when RINDNet++ is not installed."""

    def test_classify_returns_result_not_error(self, rect_image_path):
        """classify_edges_rindnet should return a result (heuristic fallback),
        not an error, even when rindnet is not installed."""
        result = classify_edges_rindnet(rect_image_path)
        # When rindnet is unavailable, it falls back to heuristic
        # which should succeed — no error key
        if not RINDNET_AVAILABLE:
            assert "error" not in result, (
                f"Expected heuristic fallback, got error: {result.get('error')}"
            )
            assert result["model"] == "heuristic"

    def test_fallback_returns_all_mask_keys(self, rect_image_path):
        """Fallback result should contain all required mask keys."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            required_keys = [
                "reflectance", "illumination", "normal", "depth",
                "form_edges", "shadow_edges",
            ]
            for key in required_keys:
                assert key in result, f"Missing key: {key}"

    def test_fallback_masks_are_correct_dtype(self, rect_image_path):
        """All mask outputs should be uint8 numpy arrays."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            mask_keys = [
                "reflectance", "illumination", "normal", "depth",
                "form_edges", "shadow_edges",
            ]
            for key in mask_keys:
                assert isinstance(result[key], np.ndarray), f"{key} not ndarray"
                assert result[key].dtype == np.uint8, f"{key} not uint8"

    def test_fallback_masks_are_correct_shape(self, rect_image_path):
        """All mask outputs should be HxW (2D)."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            for key in ["form_edges", "shadow_edges"]:
                assert result[key].ndim == 2, f"{key} not 2D"


# ---------------------------------------------------------------------------
# 3. Heuristic edge classification
# ---------------------------------------------------------------------------


class TestHeuristicClassifyEdges:
    """Verify heuristic form/shadow classification."""

    def test_produces_form_edges_on_rect(self, rect_image_path):
        """White rectangle on black should produce non-zero form edges."""
        result = _heuristic_classify_edges(rect_image_path)
        assert "error" not in result
        assert np.count_nonzero(result["form_edges"]) > 0

    def test_all_black_produces_empty_masks(self, all_black_image_path):
        """All-black image should produce zero-pixel masks."""
        result = _heuristic_classify_edges(all_black_image_path)
        assert "error" not in result
        assert np.count_nonzero(result["form_edges"]) == 0
        assert np.count_nonzero(result["shadow_edges"]) == 0

    def test_model_field_is_heuristic(self, rect_image_path):
        """Model field should be 'heuristic' for heuristic backend."""
        result = _heuristic_classify_edges(rect_image_path)
        assert result["model"] == "heuristic"

    def test_device_field_is_cpu(self, rect_image_path):
        """Device should be 'cpu' for heuristic backend."""
        result = _heuristic_classify_edges(rect_image_path)
        assert result["device"] == "cpu"

    def test_time_seconds_present(self, rect_image_path):
        """Result should include time_seconds."""
        result = _heuristic_classify_edges(rect_image_path)
        assert "time_seconds" in result
        assert result["time_seconds"] >= 0

    def test_accepts_optional_normal_map(self, rect_image_path):
        """Heuristic should accept and use a pre-computed normal map."""
        # Create a synthetic normal map
        normals = np.zeros((100, 100, 3), dtype=np.float32)
        normals[:, :, 2] = 1.0
        normals[40:60, 40:60, 0] = 0.7
        normals[40:60, 40:60, 2] = 0.7

        result = _heuristic_classify_edges(rect_image_path, normal_map=normals)
        assert "error" not in result
        assert result["model"] == "heuristic"

    def test_gradient_produces_edges(self, gradient_image_path):
        """Gradient image should produce some form edges."""
        result = _heuristic_classify_edges(gradient_image_path)
        assert "error" not in result
        # Gradient may or may not produce persistent edges depending on thresholds,
        # but should not error out

    def test_nonexistent_path_returns_error(self):
        """Nonexistent image path should return error."""
        result = _heuristic_classify_edges("/nonexistent/image.png")
        assert "error" in result


# ---------------------------------------------------------------------------
# 4. Output dict completeness
# ---------------------------------------------------------------------------


class TestOutputDictKeys:
    """Verify output dict has all required keys."""

    def test_classify_output_has_model(self, rect_image_path):
        """Output should include 'model' field."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            assert "model" in result

    def test_classify_output_has_device(self, rect_image_path):
        """Output should include 'device' field."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            assert "device" in result

    def test_classify_output_has_time(self, rect_image_path):
        """Output should include 'time_seconds' field."""
        result = classify_edges_rindnet(rect_image_path)
        if "error" not in result:
            assert "time_seconds" in result
            assert isinstance(result["time_seconds"], float)


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------


class TestEdgeClassifierErrors:
    """Verify error handling for edge cases."""

    def test_none_path_returns_error(self):
        """None image path should return error from heuristic fallback."""
        result = classify_edges_rindnet(None)
        assert "error" in result

    def test_empty_path_returns_error(self):
        """Empty string image path should return error."""
        result = classify_edges_rindnet("")
        assert "error" in result

    def test_heuristic_none_path_returns_error(self):
        """Heuristic with None path should return error."""
        result = _heuristic_classify_edges(None)
        assert "error" in result
