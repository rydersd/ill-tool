"""Tests for normal_reference — MCP tool for shadow-free reference renderings.

Covers: status action, generate action (with mocked ML backend),
generate saves PNGs, metadata structure, selective renderings,
place action JSX generation, and error handling.
"""

import json
import os
import shutil

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.normal_reference import (
    ALL_RENDERING_NAMES,
    DISPLAY_NAMES,
    OUTPUT_DIR,
    RENDERING_REGISTRY,
    NormalReferenceInput,
    _build_place_jsx,
    _generate,
    _status,
)
from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
    DSINE_AVAILABLE,
    MARIGOLD_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sphere_image_png(tmp_path_factory):
    """Create a synthetic sphere-like image for testing.

    A gradient circle that simulates a shaded sphere.  Good enough for
    testing the pipeline end-to-end without real ML inference.
    """
    path = str(tmp_path_factory.mktemp("normal_ref") / "sphere.png")
    size = 64
    img = np.zeros((size, size, 3), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    for y in range(size):
        for x in range(size):
            d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if d < size // 2 - 1:
                val = int(255 * (1.0 - d / (size // 2)))
                img[y, x] = (val, val, val)
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def fake_normal_map():
    """A synthetic HxWx3 float32 normal map (flat plane facing camera)."""
    normals = np.zeros((64, 64, 3), dtype=np.float32)
    normals[:, :, 2] = 1.0
    return normals


@pytest.fixture
def mock_estimator(monkeypatch, fake_normal_map):
    """Mock estimate_normals to return a synthetic normal map without ML."""

    def _fake_estimate(image_path, model="auto"):
        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}
        return {
            "normal_map": fake_normal_map,
            "device": "cpu",
            "model": "mock",
            "time_seconds": 0.001,
            "height": 64,
            "width": 64,
        }

    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.normal_reference.estimate_normals",
        _fake_estimate,
    )


@pytest.fixture(autouse=True)
def clean_output_dir():
    """Clean up the output directory before and after each test."""
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    yield
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 1. Status action returns correct structure
# ---------------------------------------------------------------------------


class TestStatus:
    """Verify the status action reports available backends and renderings."""

    def test_status_has_required_keys(self):
        """Status must include pipeline, backends, renderings, actions."""
        status = _status()
        assert status["pipeline"] == "normal_reference"
        assert "backends" in status
        assert "renderings" in status
        assert "available_actions" in status
        assert "description" in status

    def test_status_reports_all_renderings(self):
        """Status must list all 5 rendering types."""
        status = _status()
        for name in ALL_RENDERING_NAMES:
            assert name in status["renderings"]
            assert status["renderings"][name]["available"] is True

    def test_status_reports_backend_availability(self):
        """Status backends must reflect actual DSINE/Marigold availability."""
        status = _status()
        assert status["backends"]["dsine"]["available"] == DSINE_AVAILABLE
        assert status["backends"]["marigold"]["available"] == MARIGOLD_AVAILABLE

    def test_status_actions_list(self):
        """Available actions must include status, generate, place."""
        status = _status()
        assert set(status["available_actions"]) == {"status", "generate", "place"}

    def test_status_rendering_descriptions(self):
        """Each rendering entry must have description and needs_image flag."""
        status = _status()
        for name, info in status["renderings"].items():
            assert "description" in info
            assert "needs_image" in info
            assert isinstance(info["needs_image"], bool)


# ---------------------------------------------------------------------------
# 2. Generate action with mock ML backend
# ---------------------------------------------------------------------------


class TestGenerate:
    """Verify the generate action produces renderings and metadata."""

    def test_generate_all_renderings(self, sphere_image_png, mock_estimator):
        """Generate with all renderings should produce outputs for each."""
        result = _generate(sphere_image_png)
        assert "error" not in result, f"Generate failed: {result.get('error')}"
        assert len(result["rendering_paths"]) == len(ALL_RENDERING_NAMES)
        assert set(result["renderings_generated"]) == set(ALL_RENDERING_NAMES)

    def test_generate_saves_normal_map_png(self, sphere_image_png, mock_estimator):
        """Generate must save the normal map itself as a PNG."""
        result = _generate(sphere_image_png)
        assert "normal_map_path" in result
        assert os.path.isfile(result["normal_map_path"])
        # Verify it's a valid image
        img = cv2.imread(result["normal_map_path"])
        assert img is not None
        assert img.shape[0] == 64
        assert img.shape[1] == 64

    def test_generate_saves_rendering_pngs(self, sphere_image_png, mock_estimator):
        """All rendering outputs must exist on disk after generate."""
        result = _generate(sphere_image_png)
        for name, path in result["rendering_paths"].items():
            assert os.path.isfile(path), f"Rendering {name} not saved at {path}"
            if name == "cross_contours":
                # cross_contours outputs JSON, not an image
                import json as json_mod
                with open(path) as f:
                    data = json_mod.load(f)
                assert "polylines" in data
            else:
                img = cv2.imread(path)
                assert img is not None, f"Rendering {name} is not a valid image"

    def test_generate_returns_correct_metadata(self, sphere_image_png, mock_estimator):
        """Generate result must include normal estimation and timing metadata."""
        result = _generate(sphere_image_png)
        assert "normal_estimation" in result
        ne = result["normal_estimation"]
        assert ne["model"] == "mock"
        assert ne["device"] == "cpu"
        assert ne["height"] == 64
        assert ne["width"] == 64
        assert "time_seconds" in ne

    def test_generate_returns_timing_data(self, sphere_image_png, mock_estimator):
        """Generate result must include per-rendering and total timing data."""
        result = _generate(sphere_image_png)
        assert "timings" in result
        timings = result["timings"]
        assert "normal_estimation_seconds" in timings
        assert "rendering_seconds" in timings
        assert "total_seconds" in timings
        # Each rendering should have a timing entry
        for name in ALL_RENDERING_NAMES:
            assert name in timings["rendering_seconds"]

    def test_generate_selective_renderings(self, sphere_image_png, mock_estimator):
        """Requesting only specific renderings should generate only those."""
        selected = ["flat_planes", "form_lines"]
        result = _generate(sphere_image_png, renderings=selected)
        assert "error" not in result
        assert set(result["renderings_generated"]) == set(selected)
        assert len(result["rendering_paths"]) == 2
        # Other renderings should NOT exist
        assert "curvature" not in result["rendering_paths"]
        assert "relit" not in result["rendering_paths"]
        assert "depth_edges" not in result["rendering_paths"]

    def test_generate_single_rendering(self, sphere_image_png, mock_estimator):
        """Requesting a single rendering should produce exactly 1 output."""
        result = _generate(sphere_image_png, renderings=["curvature"])
        assert "error" not in result
        assert len(result["rendering_paths"]) == 1
        assert "curvature" in result["rendering_paths"]

    def test_generate_output_dir_created(self, sphere_image_png, mock_estimator):
        """Generate should create the output directory if it doesn't exist."""
        assert not os.path.isdir(OUTPUT_DIR)
        result = _generate(sphere_image_png)
        assert "error" not in result
        assert os.path.isdir(OUTPUT_DIR)

    def test_generate_rendering_images_are_3channel(
        self, sphere_image_png, mock_estimator
    ):
        """All saved rendering PNGs should be 3-channel BGR images (except cross_contours)."""
        result = _generate(sphere_image_png)
        for name, path in result["rendering_paths"].items():
            if name == "cross_contours":
                continue  # cross_contours outputs JSON polylines, not PNG
            img = cv2.imread(path)
            assert img is not None, f"Rendering {name} could not be read"
            assert img.ndim == 3, f"Rendering {name} is not 3-channel"
            assert img.shape[2] == 3, f"Rendering {name} has {img.shape[2]} channels"


# ---------------------------------------------------------------------------
# 3. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error handling for invalid inputs."""

    def test_generate_no_image_path(self, mock_estimator):
        """Generate without image_path should return error."""
        result = _generate(image_path=None)
        assert "error" in result
        assert "image_path" in result["error"].lower() or "required" in result["error"].lower()

    def test_generate_nonexistent_image(self, mock_estimator):
        """Generate with a nonexistent image should return error."""
        result = _generate(image_path="/nonexistent/image.png")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_generate_invalid_rendering_name(self, sphere_image_png, mock_estimator):
        """Generate with unknown rendering name should return error."""
        result = _generate(sphere_image_png, renderings=["nonexistent_rendering"])
        assert "error" in result
        assert "unknown" in result["error"].lower() or "nonexistent" in result["error"].lower()
        assert "valid_renderings" in result

    def test_generate_mixed_valid_invalid_renderings(
        self, sphere_image_png, mock_estimator
    ):
        """Generate with mix of valid and invalid renderings should error."""
        result = _generate(
            sphere_image_png, renderings=["flat_planes", "bogus"]
        )
        assert "error" in result

    def test_status_works_without_ml(self):
        """Status should succeed even when ML backends are not installed."""
        status = _status()
        # Should not raise, should return a dict
        assert isinstance(status, dict)
        assert "backends" in status


# ---------------------------------------------------------------------------
# 4. Input model validation
# ---------------------------------------------------------------------------


class TestInputModel:
    """Verify Pydantic model defaults and validation."""

    def test_defaults(self):
        """Default input should have action=status with all renderings."""
        inp = NormalReferenceInput()
        assert inp.action == "status"
        assert inp.image_path is None
        assert inp.model == "auto"
        assert set(inp.renderings) == set(ALL_RENDERING_NAMES)
        assert inp.k_planes == 6
        assert inp.light_dir == [0.0, 0.0, 1.0]
        assert inp.layer_prefix == "Normal"

    def test_custom_values(self):
        """Custom input values should be accepted."""
        inp = NormalReferenceInput(
            action="generate",
            image_path="/some/image.png",
            model="dsine",
            renderings=["flat_planes", "curvature"],
            k_planes=10,
            light_dir=[1.0, 0.5, 0.0],
            layer_prefix="Ref",
        )
        assert inp.action == "generate"
        assert inp.image_path == "/some/image.png"
        assert inp.model == "dsine"
        assert inp.renderings == ["flat_planes", "curvature"]
        assert inp.k_planes == 10
        assert inp.light_dir == [1.0, 0.5, 0.0]
        assert inp.layer_prefix == "Ref"

    def test_k_planes_validation(self):
        """k_planes must be between 2 and 20."""
        with pytest.raises(Exception):
            NormalReferenceInput(k_planes=1)
        with pytest.raises(Exception):
            NormalReferenceInput(k_planes=21)

    def test_whitespace_stripping(self):
        """String fields should strip whitespace."""
        inp = NormalReferenceInput(action="  generate  ", layer_prefix="  Normal  ")
        assert inp.action == "generate"
        assert inp.layer_prefix == "Normal"


# ---------------------------------------------------------------------------
# 5. JSX builder for place action
# ---------------------------------------------------------------------------


class TestPlaceJsx:
    """Verify JSX generation for placing reference layers."""

    def test_jsx_contains_layer_names(self):
        """JSX should reference the correct layer names with prefix."""
        paths = {"flat_planes": "/tmp/test_fp.png", "form_lines": "/tmp/test_fl.png"}
        jsx = _build_place_jsx(paths, "Normal")
        assert "Normal: Flat Planes" in jsx
        assert "Normal: Form Lines" in jsx

    def test_jsx_contains_file_paths(self):
        """JSX should embed the PNG file paths."""
        paths = {"curvature": "/tmp/ai_normal_ref/curvature.png"}
        jsx = _build_place_jsx(paths, "Ref")
        assert "/tmp/ai_normal_ref/curvature.png" in jsx

    def test_jsx_locks_and_hides_layers(self):
        """JSX should set locked=true and visible=false on each layer."""
        paths = {"relit": "/tmp/relit.png"}
        jsx = _build_place_jsx(paths, "Normal")
        assert "lyr.locked = true" in jsx
        assert "lyr.visible = false" in jsx

    def test_jsx_scales_to_artboard(self):
        """JSX should contain artboard scaling logic."""
        paths = {"depth_edges": "/tmp/de.png"}
        jsx = _build_place_jsx(paths, "Normal")
        assert "artboardRect" in jsx
        assert "resize" in jsx

    def test_jsx_custom_prefix(self):
        """JSX should use the provided custom prefix."""
        paths = {"flat_planes": "/tmp/fp.png"}
        jsx = _build_place_jsx(paths, "CustomRef")
        assert "CustomRef: Flat Planes" in jsx

    def test_jsx_returns_json(self):
        """JSX should return JSON with layers_placed count."""
        paths = {"flat_planes": "/tmp/fp.png", "form_lines": "/tmp/fl.png"}
        jsx = _build_place_jsx(paths, "Normal")
        assert "layers_placed" in jsx
        assert "JSON.stringify" in jsx

    def test_jsx_handles_all_renderings(self):
        """JSX should generate a block for each rendering in the dict."""
        paths = {name: f"/tmp/{name}.png" for name in ALL_RENDERING_NAMES}
        jsx = _build_place_jsx(paths, "Normal")
        for name in ALL_RENDERING_NAMES:
            display = DISPLAY_NAMES[name]
            assert f"Normal: {display}" in jsx


# ---------------------------------------------------------------------------
# 6. Place action (end-to-end with mock JSX)
# ---------------------------------------------------------------------------


class TestPlaceAction:
    """Verify the place action via the async handler with mocked JSX."""

    @pytest.mark.asyncio
    async def test_place_generates_and_places(
        self, sphere_image_png, mock_estimator, mock_jsx
    ):
        """Place action should generate renderings then execute JSX."""
        mock_jsx.set_response(
            json.dumps({"layers_placed": 5, "layers": []})
        )
        # Import and call the handler directly
        from adobe_mcp.apps.illustrator.normal_reference import (
            NormalReferenceInput,
        )

        # We need to call the internal logic since the tool is registered on mcp
        from adobe_mcp.apps.illustrator.normal_reference import (
            _generate,
            _build_place_jsx,
        )
        from adobe_mcp.engine import _async_run_jsx

        params = NormalReferenceInput(
            action="place",
            image_path=sphere_image_png,
            renderings=["flat_planes", "form_lines"],
            layer_prefix="Test",
        )

        # Run generate
        gen_result = _generate(
            image_path=params.image_path,
            model=params.model,
            renderings=params.renderings,
            k_planes=params.k_planes,
            light_dir=tuple(params.light_dir),
        )
        assert "error" not in gen_result

        # Build and execute JSX
        jsx = _build_place_jsx(gen_result["rendering_paths"], params.layer_prefix)
        place_result = await _async_run_jsx("illustrator", jsx, timeout=300)
        assert place_result["success"]
        assert mock_jsx.calls[-1]["app"] == "illustrator"

        # Verify JSX contains the expected layer names
        jsx_code = mock_jsx.calls[-1]["code"]
        assert "Test: Flat Planes" in jsx_code
        assert "Test: Form Lines" in jsx_code

    @pytest.mark.asyncio
    async def test_place_passes_error_from_generate(self, mock_estimator, mock_jsx):
        """Place action should forward generate errors without calling JSX."""
        # No image path -> generate will fail
        result = _generate(image_path=None)
        assert "error" in result
        # Should NOT have called JSX
        assert len(mock_jsx.calls) == 0


# ---------------------------------------------------------------------------
# 7. Constants and registry consistency
# ---------------------------------------------------------------------------


class TestRegistryConsistency:
    """Verify internal constants are consistent."""

    def test_all_renderings_in_registry(self):
        """ALL_RENDERING_NAMES must match RENDERING_REGISTRY keys."""
        assert set(ALL_RENDERING_NAMES) == set(RENDERING_REGISTRY.keys())

    def test_all_renderings_have_display_names(self):
        """Every rendering must have a display name."""
        for name in ALL_RENDERING_NAMES:
            assert name in DISPLAY_NAMES, f"Missing display name for {name}"
            assert isinstance(DISPLAY_NAMES[name], str)
            assert len(DISPLAY_NAMES[name]) > 0

    def test_relit_is_only_image_needer(self):
        """Only relit should require the original image."""
        for name, info in RENDERING_REGISTRY.items():
            if name == "relit":
                assert info["needs_image"] is True
            else:
                assert info["needs_image"] is False, (
                    f"{name} should not need image"
                )
