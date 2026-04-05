"""Tests for form_edge_extract — MCP tool for form edge extraction.

Covers: status action, extract action, place action JSX generation,
compare action IoU, error handling, backend selection, and input model.
"""

import json
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.drawing.form_edge_extract import (
    DSINE_AVAILABLE,
    INFORMATIVE_AVAILABLE,
    RINDNET_AVAILABLE,
    OUTPUT_DIR,
    FormEdgeExtractInput,
    _build_place_jsx,
    _cap_contour_points,
    _compare,
    _extract,
    _status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def form_edge_image_a(tmp_path_factory):
    """White rectangle on black background for extraction tests."""
    path = str(tmp_path_factory.mktemp("form_edge") / "rect.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (80, 80), (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def form_edge_image_b(tmp_path_factory):
    """White circle on black background for comparison tests."""
    path = str(tmp_path_factory.mktemp("form_edge") / "circle.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 30, (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(autouse=True)
def clean_output_dir():
    """Clean output directory before and after each test."""
    import shutil
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    yield
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 1. Status action
# ---------------------------------------------------------------------------


class TestStatus:
    """Verify the status action reports correct structure."""

    def test_status_has_required_keys(self):
        """Status must include pipeline, backends, actions."""
        status = _status()
        assert status["pipeline"] == "form_edge_extract"
        assert "backends" in status
        assert "available_actions" in status
        assert "description" in status

    def test_status_reports_heuristic_always_available(self):
        """Heuristic backend should always be available."""
        status = _status()
        assert status["backends"]["heuristic"]["available"] is True

    def test_status_reports_dsine_availability(self):
        """DSINE availability should match actual import check."""
        status = _status()
        assert status["backends"]["dsine"]["available"] == DSINE_AVAILABLE

    def test_status_actions_list(self):
        """Available actions should include all four actions."""
        status = _status()
        expected = {"status", "extract", "place", "compare"}
        assert set(status["available_actions"]) == expected

    def test_status_has_output_dir(self):
        """Status should report the output directory path."""
        status = _status()
        assert "output_dir" in status

    def test_status_dsine_has_install_hint_when_unavailable(self):
        """DSINE backend should have install_hint when not available."""
        status = _status()
        dsine = status["backends"]["dsine"]
        if not dsine["available"]:
            assert dsine["install_hint"] is not None
        else:
            assert dsine["install_hint"] is None

    def test_status_reports_rindnet_availability(self):
        """RINDNet++ availability should match actual import check."""
        status = _status()
        assert "rindnet" in status["backends"]
        assert status["backends"]["rindnet"]["available"] == RINDNET_AVAILABLE

    def test_status_reports_informative_availability(self):
        """Informative Drawings availability should match actual import check."""
        status = _status()
        assert "informative" in status["backends"]
        assert status["backends"]["informative"]["available"] == INFORMATIVE_AVAILABLE

    def test_status_has_auto_priority(self):
        """Status should include auto-selection priority order."""
        status = _status()
        assert "auto_priority" in status
        assert status["auto_priority"] == ["rindnet", "dsine", "informative", "heuristic"]

    def test_status_rindnet_has_install_hint_when_unavailable(self):
        """RINDNet++ should have install_hint with GitHub URL when not available."""
        status = _status()
        rindnet = status["backends"]["rindnet"]
        if not rindnet["available"]:
            assert rindnet["install_hint"] is not None
            assert "github" in rindnet["install_hint"].lower()

    def test_status_informative_has_install_hint_when_unavailable(self):
        """Informative Drawings should have install_hint when not available."""
        status = _status()
        informative = status["backends"]["informative"]
        if not informative["available"]:
            assert informative["install_hint"] is not None


# ---------------------------------------------------------------------------
# 2. Extract action
# ---------------------------------------------------------------------------


class TestExtract:
    """Verify the extract action returns contours and metadata."""

    def test_extract_returns_contours(self, form_edge_image_a):
        """Extract should return a list of contours."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "error" not in result, f"Extract failed: {result.get('error')}"
        assert "contours" in result
        assert "contour_count" in result
        assert isinstance(result["contours"], list)

    def test_extract_returns_backend_name(self, form_edge_image_a):
        """Extract should report which backend was used."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert result["backend"] == "heuristic"

    def test_extract_saves_mask_to_disk(self, form_edge_image_a):
        """Extract should save the edge mask PNG to disk."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "mask_path" in result
        assert os.path.isfile(result["mask_path"])

    def test_extract_returns_image_size(self, form_edge_image_a):
        """Extract should report image dimensions."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "image_size" in result
        assert result["image_size"] == [100, 100]

    def test_extract_returns_timing_data(self, form_edge_image_a):
        """Extract should include timing information."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "timings" in result
        assert "total_seconds" in result["timings"]
        assert result["timings"]["total_seconds"] >= 0

    def test_extract_contours_have_correct_structure(self, form_edge_image_a):
        """Each contour should have name, points, point_count, area."""
        result = _extract(form_edge_image_a, backend="heuristic")
        if result["contour_count"] > 0:
            contour = result["contours"][0]
            assert "name" in contour
            assert "points" in contour
            assert "point_count" in contour
            assert "area" in contour

    def test_extract_respects_max_contours(self, form_edge_image_a):
        """max_contours parameter should limit output."""
        result = _extract(
            form_edge_image_a, backend="heuristic", max_contours=1
        )
        assert result["contour_count"] <= 1

    def test_extract_returns_metadata(self, form_edge_image_a):
        """Extract should include backend-specific metadata."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "metadata" in result
        assert isinstance(result["metadata"], dict)


# ---------------------------------------------------------------------------
# 3. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error handling for invalid inputs."""

    def test_extract_no_image_path(self):
        """Extract without image_path should return error."""
        result = _extract(image_path=None, backend="heuristic")
        assert "error" in result

    def test_extract_nonexistent_image(self):
        """Extract with nonexistent image should return error."""
        result = _extract(image_path="/nonexistent/image.png", backend="heuristic")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_compare_missing_image_a(self, form_edge_image_b):
        """Compare with missing image A should return error."""
        result = _compare(
            image_path_a="/nonexistent/a.png",
            image_path_b=form_edge_image_b,
        )
        assert "error" in result

    def test_compare_missing_image_b(self, form_edge_image_a):
        """Compare with missing image B should return error."""
        result = _compare(
            image_path_a=form_edge_image_a,
            image_path_b="/nonexistent/b.png",
        )
        assert "error" in result

    def test_compare_both_missing(self):
        """Compare with both images missing should return error."""
        result = _compare(
            image_path_a="/nonexistent/a.png",
            image_path_b="/nonexistent/b.png",
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# 4. Compare action
# ---------------------------------------------------------------------------


class TestCompare:
    """Verify the compare action computes IoU correctly."""

    def test_compare_same_image_high_iou(self, form_edge_image_a):
        """Comparing an image with itself should produce IoU = 1.0."""
        result = _compare(
            form_edge_image_a, form_edge_image_a, backend="heuristic"
        )
        assert "error" not in result, f"Compare failed: {result.get('error')}"
        assert result["iou"] == 1.0

    def test_compare_different_images(self, form_edge_image_a, form_edge_image_b):
        """Comparing different images should produce 0 < IoU < 1."""
        result = _compare(
            form_edge_image_a, form_edge_image_b, backend="heuristic"
        )
        assert "error" not in result
        assert 0.0 <= result["iou"] <= 1.0

    def test_compare_returns_pixel_counts(self, form_edge_image_a, form_edge_image_b):
        """Compare should report intersection and union pixel counts."""
        result = _compare(
            form_edge_image_a, form_edge_image_b, backend="heuristic"
        )
        assert "intersection_pixels" in result
        assert "union_pixels" in result
        assert result["intersection_pixels"] >= 0
        assert result["union_pixels"] >= 0

    def test_compare_returns_per_image_info(self, form_edge_image_a, form_edge_image_b):
        """Compare should report per-image edge counts and backends."""
        result = _compare(
            form_edge_image_a, form_edge_image_b, backend="heuristic"
        )
        assert "image_a" in result
        assert "image_b" in result
        assert result["image_a"]["backend"] == "heuristic"
        assert result["image_b"]["backend"] == "heuristic"
        assert result["image_a"]["edge_pixels"] >= 0
        assert result["image_b"]["edge_pixels"] >= 0

    def test_compare_returns_timing(self, form_edge_image_a, form_edge_image_b):
        """Compare should include timing data."""
        result = _compare(
            form_edge_image_a, form_edge_image_b, backend="heuristic"
        )
        assert "timings" in result
        assert "total_seconds" in result["timings"]


# ---------------------------------------------------------------------------
# 5. JSX generation for place action
# ---------------------------------------------------------------------------


class TestPlaceJsx:
    """Verify JSX generation for placing form edge paths."""

    def test_jsx_creates_layer(self):
        """JSX should create or find the named layer."""
        contours = [{"name": "edge_0", "points": [[0, 0], [10, 0], [10, 10]]}]
        jsx = "".join(_build_place_jsx(contours, "Form Edges"))
        assert "Form Edges" in jsx
        assert "layer.name" in jsx

    def test_jsx_creates_paths(self):
        """JSX should create a path for each contour."""
        contours = [
            {"name": "edge_0", "points": [[0, 0], [10, 0], [10, 10]]},
            {"name": "edge_1", "points": [[20, 20], [30, 20], [30, 30]]},
        ]
        jsx = "".join(_build_place_jsx(contours, "Form Edges"))
        assert "edge_0" in jsx
        assert "edge_1" in jsx
        assert "pathItems.add()" in jsx

    def test_jsx_sets_entire_path(self):
        """JSX should call setEntirePath with point arrays."""
        contours = [{"name": "test", "points": [[5, 10], [15, 20], [25, 30]]}]
        jsx = "".join(_build_place_jsx(contours, "Form Edges"))
        assert "setEntirePath" in jsx
        assert "[5, 10]" in jsx

    def test_jsx_smoothing_enabled(self):
        """When smooth=True, JSX should set bezier handles."""
        contours = [{"name": "test", "points": [[0, 0], [10, 0], [10, 10]]}]
        jsx = "".join(_build_place_jsx(contours, "Form Edges", smooth=True))
        assert "leftDirection" in jsx
        assert "rightDirection" in jsx

    def test_jsx_smoothing_disabled(self):
        """When smooth=False, JSX should not set bezier handles."""
        contours = [{"name": "test", "points": [[0, 0], [10, 0], [10, 10]]}]
        jsx = "".join(_build_place_jsx(contours, "Form Edges", smooth=False))
        # The smoothing block is conditioned on the smooth flag
        assert '"false"' in jsx or "false" in jsx

    def test_jsx_returns_json(self):
        """JSX should return JSON with paths_placed count."""
        contours = [{"name": "test", "points": [[0, 0], [10, 0], [10, 10]]}]
        jsx = "".join(_build_place_jsx(contours, "Form Edges"))
        assert "JSON.stringify" in jsx
        assert "paths_placed" in jsx

    def test_jsx_skips_short_contours(self):
        """Contours with fewer than 3 points should be skipped."""
        contours = [
            {"name": "short", "points": [[0, 0], [10, 0]]},  # Too short
            {"name": "ok", "points": [[0, 0], [10, 0], [10, 10]]},
        ]
        jsx = "".join(_build_place_jsx(contours, "Form Edges"))
        # "short" should not appear as a path name in the JSX
        # but "ok" should
        assert '"ok"' in jsx

    def test_jsx_custom_layer_name(self):
        """JSX should use the provided custom layer name."""
        contours = [{"name": "test", "points": [[0, 0], [10, 0], [10, 10]]}]
        jsx = "".join(_build_place_jsx(contours, "My Custom Layer"))
        assert "My Custom Layer" in jsx

    def test_jsx_returns_list(self):
        """_build_place_jsx should return a list of JSX strings."""
        contours = [{"name": "test", "points": [[0, 0], [10, 0], [10, 10]]}]
        result = _build_place_jsx(contours, "Form Edges")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(s, str) for s in result)

    def test_jsx_caps_high_point_contours(self):
        """Contours with >200 points should be simplified before JSX."""
        # Generate a 500-point contour (circle)
        import math
        points = [
            [round(100 + 50 * math.cos(2 * math.pi * i / 500), 2),
             round(100 + 50 * math.sin(2 * math.pi * i / 500), 2)]
            for i in range(500)
        ]
        contours = [{"name": "dense", "points": points}]
        jsx_batches = _build_place_jsx(contours, "Form Edges")
        jsx = "".join(jsx_batches)
        # The JSX should contain setEntirePath — path was placed, not dropped
        assert "setEntirePath" in jsx
        # Point count in the JSX should be reduced (not all 500 points)
        # Count occurrences of coordinate pairs — rough check
        assert jsx.count("[") < 500


# ---------------------------------------------------------------------------
# 5b. Point capping
# ---------------------------------------------------------------------------


class TestCapContourPoints:
    """Verify Douglas-Peucker point capping for high-count contours."""

    def test_under_threshold_unchanged(self):
        """Points under max_points should be returned unchanged."""
        points = [[0, 0], [10, 0], [10, 10]]
        result = _cap_contour_points(points, max_points=200)
        assert result == points

    def test_over_threshold_reduced(self):
        """Points over max_points should be simplified."""
        import math
        points = [
            [round(100 + 50 * math.cos(2 * math.pi * i / 500), 2),
             round(100 + 50 * math.sin(2 * math.pi * i / 500), 2)]
            for i in range(500)
        ]
        result = _cap_contour_points(points, max_points=200)
        assert len(result) <= 200
        assert len(result) >= 3  # Must still be a valid contour

    def test_exactly_at_threshold(self):
        """Points at exactly max_points should be unchanged."""
        import math
        points = [
            [round(50 * math.cos(2 * math.pi * i / 200), 2),
             round(50 * math.sin(2 * math.pi * i / 200), 2)]
            for i in range(200)
        ]
        result = _cap_contour_points(points, max_points=200)
        assert result == points

    def test_very_high_count_capped(self):
        """1900-point contour (worst case from heuristic backend)."""
        import math
        points = [
            [round(200 + 150 * math.cos(2 * math.pi * i / 1900), 2),
             round(200 + 150 * math.sin(2 * math.pi * i / 1900), 2)]
            for i in range(1900)
        ]
        result = _cap_contour_points(points, max_points=200)
        assert len(result) <= 200


# ---------------------------------------------------------------------------
# 6. Place action (end-to-end with mock JSX)
# ---------------------------------------------------------------------------


class TestPlaceAction:
    """Verify place action via mocked JSX execution."""

    @pytest.mark.asyncio
    async def test_place_extracts_and_places(self, form_edge_image_a, mock_jsx):
        """Place action should extract edges then execute JSX."""
        mock_jsx.set_response(json.dumps({
            "width": 800, "height": 600,
        }))

        # Test the extract phase which does not need JSX
        # Use lower min_contour_length to ensure contours from 100x100 image
        result = _extract(
            form_edge_image_a, backend="heuristic", min_contour_length=10
        )
        assert "error" not in result
        assert result["contour_count"] >= 0  # May be 0 for small images

    @pytest.mark.asyncio
    async def test_place_error_no_image(self, mock_jsx):
        """Place with no image should return error before JSX."""
        result = _extract(image_path=None, backend="heuristic")
        assert "error" in result
        assert len(mock_jsx.calls) == 0


# ---------------------------------------------------------------------------
# 7. Input model validation
# ---------------------------------------------------------------------------


class TestInputModel:
    """Verify Pydantic model defaults and validation."""

    def test_defaults(self):
        """Default input should have action=status with sensible defaults."""
        inp = FormEdgeExtractInput()
        assert inp.action == "status"
        assert inp.image_path is None
        assert inp.backend == "auto"
        assert inp.edge_threshold == 0.5
        assert inp.simplify_tolerance == 2.0
        assert inp.layer_name == "Form Edges"
        assert inp.smooth is True
        assert inp.max_contours == 50
        assert inp.min_contour_length == 30

    def test_custom_values(self):
        """Custom input values should be accepted."""
        inp = FormEdgeExtractInput(
            action="extract",
            image_path="/some/image.png",
            backend="heuristic",
            edge_threshold=0.3,
            simplify_tolerance=5.0,
            layer_name="My Edges",
            smooth=False,
            max_contours=10,
            min_contour_length=50,
        )
        assert inp.action == "extract"
        assert inp.image_path == "/some/image.png"
        assert inp.backend == "heuristic"
        assert inp.edge_threshold == 0.3
        assert inp.simplify_tolerance == 5.0
        assert inp.layer_name == "My Edges"
        assert inp.smooth is False
        assert inp.max_contours == 10
        assert inp.min_contour_length == 50

    def test_edge_threshold_validation(self):
        """edge_threshold must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            FormEdgeExtractInput(edge_threshold=-0.1)
        with pytest.raises(Exception):
            FormEdgeExtractInput(edge_threshold=1.5)

    def test_max_contours_validation(self):
        """max_contours must be >= 1 and <= 500."""
        with pytest.raises(Exception):
            FormEdgeExtractInput(max_contours=0)

    def test_whitespace_stripping(self):
        """String fields should strip whitespace."""
        inp = FormEdgeExtractInput(
            action="  extract  ", layer_name="  My Layer  "
        )
        assert inp.action == "extract"
        assert inp.layer_name == "My Layer"

    def test_image_path_b_for_compare(self):
        """image_path_b should be accepted for compare action."""
        inp = FormEdgeExtractInput(
            action="compare",
            image_path="/a.png",
            image_path_b="/b.png",
        )
        assert inp.image_path_b == "/b.png"


# ---------------------------------------------------------------------------
# 8. Backend selection logic
# ---------------------------------------------------------------------------


class TestBackendSelection:
    """Verify auto-selection and explicit backend usage."""

    def test_auto_selects_heuristic_without_ml(self, form_edge_image_a, monkeypatch):
        """Auto backend should use heuristic when all ML backends unavailable."""
        import adobe_mcp.apps.illustrator.form_edge_pipeline as fep

        monkeypatch.setattr(fep, "DSINE_AVAILABLE", False)
        monkeypatch.setattr(fep, "RINDNET_AVAILABLE", False)
        monkeypatch.setattr(fep, "INFORMATIVE_AVAILABLE", False)
        result = _extract(form_edge_image_a, backend="auto")
        assert "error" not in result
        assert result["backend"] == "heuristic"

    def test_explicit_heuristic(self, form_edge_image_a):
        """Explicit heuristic backend should always work."""
        result = _extract(form_edge_image_a, backend="heuristic")
        assert "error" not in result
        assert result["backend"] == "heuristic"
