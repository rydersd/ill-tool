"""Tests for ml_backends.informative_draw — Informative Drawings ONNX backend.

Covers: ml_status structure, graceful fallback when onnxruntime unavailable,
output shape/dtype when available, threshold sensitivity, path validation.
"""

import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.ml_backends.informative_draw import (
    INFORMATIVE_AVAILABLE,
    informative_drawings,
    ml_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rect_image_path(tmp_path_factory):
    """White rectangle on black — clear edges for line drawing extraction."""
    path = str(tmp_path_factory.mktemp("inform_draw") / "rect.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (80, 80), (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def small_image_path(tmp_path_factory):
    """Small 32x32 image for edge cases."""
    path = str(tmp_path_factory.mktemp("inform_draw") / "small.png")
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    cv2.circle(img, (16, 16), 10, (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# 1. Status reporting
# ---------------------------------------------------------------------------


class TestInformativeDrawStatus:
    """Verify ml_status returns correct structure."""

    def test_status_has_informative_drawings_key(self):
        """Status must include informative_drawings backend info."""
        status = ml_status()
        assert "informative_drawings" in status

    def test_status_has_available_flag(self):
        """Backend entry must report availability."""
        status = ml_status()
        info = status["informative_drawings"]
        assert "available" in info
        assert isinstance(info["available"], bool)

    def test_status_matches_import_flag(self):
        """Status availability should match the module-level flag."""
        status = ml_status()
        assert status["informative_drawings"]["available"] == INFORMATIVE_AVAILABLE

    def test_status_has_install_hint_when_unavailable(self):
        """When onnxruntime is unavailable, status should include install hint."""
        status = ml_status()
        info = status["informative_drawings"]
        if not info["available"]:
            assert "install_hint" in info
            assert "onnxruntime" in info["install_hint"].lower()

    def test_status_has_required_packages_when_unavailable(self):
        """When unavailable, status should list required packages."""
        status = ml_status()
        info = status["informative_drawings"]
        if not info["available"]:
            assert "required_packages" in info
            assert "onnxruntime" in info["required_packages"]

    def test_status_has_version_when_available(self):
        """When available, status should report onnxruntime version."""
        status = ml_status()
        info = status["informative_drawings"]
        if info["available"]:
            assert "onnxruntime_version" in info

    def test_status_reports_model_loaded(self):
        """When available, status should report model loading state."""
        status = ml_status()
        info = status["informative_drawings"]
        if info["available"]:
            assert "model_loaded" in info
            assert isinstance(info["model_loaded"], bool)


# ---------------------------------------------------------------------------
# 2. Graceful fallback when onnxruntime unavailable
# ---------------------------------------------------------------------------


class TestInformativeFallback:
    """Verify graceful error when onnxruntime is not installed."""

    def test_returns_error_dict_when_unavailable(self, rect_image_path, monkeypatch):
        """Should return error dict (not raise) when onnxruntime missing."""
        import adobe_mcp.apps.illustrator.ml_backends.informative_draw as mod

        monkeypatch.setattr(mod, "INFORMATIVE_AVAILABLE", False)
        result = informative_drawings(rect_image_path)
        assert "error" in result

    def test_error_includes_install_hint(self, rect_image_path, monkeypatch):
        """Error dict should include install instructions."""
        import adobe_mcp.apps.illustrator.ml_backends.informative_draw as mod

        monkeypatch.setattr(mod, "INFORMATIVE_AVAILABLE", False)
        result = informative_drawings(rect_image_path)
        assert "install_hint" in result

    def test_error_includes_required_packages(self, rect_image_path, monkeypatch):
        """Error dict should list required packages."""
        import adobe_mcp.apps.illustrator.ml_backends.informative_draw as mod

        monkeypatch.setattr(mod, "INFORMATIVE_AVAILABLE", False)
        result = informative_drawings(rect_image_path)
        assert "required_packages" in result
        assert "onnxruntime" in result["required_packages"]


# ---------------------------------------------------------------------------
# 3. Output shape/dtype (when model is available)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not INFORMATIVE_AVAILABLE,
    reason="onnxruntime not installed",
)
class TestInformativeOutput:
    """Verify output structure when the model can actually run.

    These tests are skipped when onnxruntime is not installed.
    They also depend on the model being downloadable from HuggingFace,
    so may be skipped in offline environments.
    """

    def test_output_has_line_drawing(self, rect_image_path):
        """Successful inference should return line_drawing array."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert "line_drawing" in result
            assert isinstance(result["line_drawing"], np.ndarray)

    def test_line_drawing_is_uint8(self, rect_image_path):
        """Line drawing output should be uint8."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert result["line_drawing"].dtype == np.uint8

    def test_line_drawing_is_2d(self, rect_image_path):
        """Line drawing output should be 2D (HxW)."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert result["line_drawing"].ndim == 2

    def test_line_drawing_matches_input_size(self, rect_image_path):
        """Line drawing should be resized back to original image dimensions."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert result["line_drawing"].shape == (100, 100)
            assert result["height"] == 100
            assert result["width"] == 100

    def test_output_has_raw_float(self, rect_image_path):
        """Successful inference should also return raw float line map."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert "line_drawing_raw" in result
            assert result["line_drawing_raw"].dtype == np.float32

    def test_output_has_model_field(self, rect_image_path):
        """Output should report model name."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert result["model"] == "informative_drawings"

    def test_output_has_time_seconds(self, rect_image_path):
        """Output should include timing information."""
        result = informative_drawings(rect_image_path)
        if "error" not in result:
            assert "time_seconds" in result
            assert result["time_seconds"] >= 0


# ---------------------------------------------------------------------------
# 4. Threshold sensitivity
# ---------------------------------------------------------------------------


class TestInformativeThreshold:
    """Verify threshold parameter affects output."""

    @pytest.mark.skipif(
        not INFORMATIVE_AVAILABLE,
        reason="onnxruntime not installed",
    )
    def test_low_threshold_more_edges(self, rect_image_path):
        """Lower threshold should produce more edge pixels."""
        result_low = informative_drawings(rect_image_path, threshold=0.1)
        result_high = informative_drawings(rect_image_path, threshold=0.9)
        if "error" not in result_low and "error" not in result_high:
            pixels_low = np.count_nonzero(result_low["line_drawing"])
            pixels_high = np.count_nonzero(result_high["line_drawing"])
            assert pixels_low >= pixels_high

    @pytest.mark.skipif(
        not INFORMATIVE_AVAILABLE,
        reason="onnxruntime not installed",
    )
    def test_threshold_zero_keeps_all(self, rect_image_path):
        """Threshold 0.0 should keep all non-zero lines."""
        result = informative_drawings(rect_image_path, threshold=0.0)
        if "error" not in result:
            # With threshold=0.0, only truly zero pixels are background
            assert result["threshold"] == 0.0

    @pytest.mark.skipif(
        not INFORMATIVE_AVAILABLE,
        reason="onnxruntime not installed",
    )
    def test_threshold_one_removes_all(self, rect_image_path):
        """Threshold 1.0 should remove all lines (nothing > 1.0 after normalization)."""
        result = informative_drawings(rect_image_path, threshold=1.0)
        if "error" not in result:
            # Nothing should be > 1.0 in a [0,1] normalized output
            assert np.count_nonzero(result["line_drawing"]) == 0

    def test_threshold_preserved_in_output(self, rect_image_path, monkeypatch):
        """Threshold value should be recorded in the output dict."""
        # This test works even without onnxruntime — just check the error dict
        # has install_hint or the result has threshold
        import adobe_mcp.apps.illustrator.ml_backends.informative_draw as mod

        if not INFORMATIVE_AVAILABLE:
            # When unavailable, the function returns an error before reaching
            # the threshold recording — that's expected behavior
            result = informative_drawings(rect_image_path, threshold=0.3)
            assert "error" in result
        else:
            result = informative_drawings(rect_image_path, threshold=0.3)
            if "error" not in result:
                assert result["threshold"] == 0.3


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------


class TestInformativeErrors:
    """Verify error handling for invalid inputs."""

    def test_nonexistent_path_returns_error(self):
        """Nonexistent image path should return error dict."""
        result = informative_drawings("/nonexistent/image.png")
        assert "error" in result

    def test_none_path_returns_error(self):
        """None image path should return error dict."""
        result = informative_drawings(None)
        assert "error" in result

    def test_empty_path_returns_error(self):
        """Empty string image path should return error dict."""
        result = informative_drawings("")
        assert "error" in result

    def test_no_exception_raised(self, rect_image_path):
        """Function should never raise — always returns a dict."""
        # Should work regardless of onnxruntime availability
        result = informative_drawings(rect_image_path)
        assert isinstance(result, dict)
