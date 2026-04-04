"""Tests for surface_classifier — sidecar loading and path-level surface queries.

Tests use synthetic sidecar JSON (no ML dependencies required).
"""

import json
import os
import tempfile

import pytest

from adobe_mcp.apps.illustrator.surface_classifier import (
    PathSurfaceInfo,
    SidecarData,
    find_sidecar,
    load_sidecar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SIDECAR = {
    "image_hash": "abc123",
    "timestamp": "2026-04-04T15:00:00+00:00",
    "paths": [
        {
            "name": "form_edge_0",
            "layer": "Form Edges",
            "dominant_surface": "convex",
            "mean_curvature": 0.04,
            "is_silhouette": False,
            "mean_depth_facing": 0.85,
            "anchor_count": 12,
        },
        {
            "name": "form_edge_1",
            "layer": "Form Edges",
            "dominant_surface": "flat",
            "mean_curvature": 0.001,
            "is_silhouette": False,
            "mean_depth_facing": 0.95,
            "anchor_count": 8,
        },
        {
            "name": "form_edge_2",
            "layer": "Form Edges",
            "dominant_surface": "concave",
            "mean_curvature": -0.03,
            "is_silhouette": True,
            "mean_depth_facing": 0.2,
            "anchor_count": 20,
        },
        {
            "name": "form_edge_3",
            "layer": "Form Edges",
            "dominant_surface": "saddle",
            "mean_curvature": 0.02,
            "is_silhouette": False,
            "mean_depth_facing": 0.7,
            "anchor_count": 15,
        },
        {
            "name": "form_edge_4",
            "layer": "Form Edges",
            "dominant_surface": "cylindrical",
            "mean_curvature": 0.01,
            "is_silhouette": False,
            "mean_depth_facing": 0.9,
            "anchor_count": 10,
        },
        {
            "name": "form_edge_5",
            "layer": "Form Edges",
            "dominant_surface": "convex",
            "mean_curvature": 0.05,
            "is_silhouette": False,
            "mean_depth_facing": 0.88,
            "anchor_count": 6,
        },
    ],
}


@pytest.fixture()
def sidecar_file(tmp_path):
    """Write a valid sidecar JSON to a temp file and return the path."""
    path = tmp_path / "test_doc_normals.json"
    path.write_text(json.dumps(VALID_SIDECAR))
    return path


@pytest.fixture()
def sidecar_data():
    """Pre-built SidecarData for query tests."""
    paths = []
    for p in VALID_SIDECAR["paths"]:
        paths.append(
            PathSurfaceInfo(
                name=p["name"],
                layer=p["layer"],
                dominant_surface=p["dominant_surface"],
                mean_curvature=p["mean_curvature"],
                is_silhouette=p["is_silhouette"],
                mean_depth_facing=p["mean_depth_facing"],
                anchor_count=p["anchor_count"],
            )
        )
    return SidecarData(image_hash="abc123", paths=paths)


# ---------------------------------------------------------------------------
# load_sidecar tests
# ---------------------------------------------------------------------------


class TestLoadSidecar:
    """Tests for load_sidecar function."""

    def test_valid_json_returns_sidecar_data(self, sidecar_file):
        result = load_sidecar(sidecar_file)
        assert result is not None
        assert isinstance(result, SidecarData)
        assert result.image_hash == "abc123"
        assert len(result.paths) == 6

    def test_valid_json_path_fields(self, sidecar_file):
        result = load_sidecar(sidecar_file)
        assert result is not None
        p0 = result.paths[0]
        assert p0.name == "form_edge_0"
        assert p0.layer == "Form Edges"
        assert p0.dominant_surface == "convex"
        assert p0.mean_curvature == 0.04
        assert p0.is_silhouette is False
        assert p0.mean_depth_facing == 0.85
        assert p0.anchor_count == 12

    def test_missing_file_returns_none(self, tmp_path):
        result = load_sidecar(tmp_path / "nonexistent.json")
        assert result is None

    def test_invalid_json_returns_none(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{{not valid json")
        result = load_sidecar(bad_file)
        assert result is None

    def test_empty_json_returns_empty_paths(self, tmp_path):
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("{}")
        result = load_sidecar(empty_file)
        assert result is not None
        assert result.image_hash == ""
        assert result.paths == []

    def test_string_path_accepted(self, sidecar_file):
        result = load_sidecar(str(sidecar_file))
        assert result is not None
        assert len(result.paths) == 6


# ---------------------------------------------------------------------------
# SidecarData.get_path tests
# ---------------------------------------------------------------------------


class TestGetPath:
    """Tests for SidecarData.get_path method."""

    def test_existing_name(self, sidecar_data):
        result = sidecar_data.get_path("form_edge_0")
        assert result is not None
        assert result.name == "form_edge_0"
        assert result.dominant_surface == "convex"

    def test_missing_name_returns_none(self, sidecar_data):
        result = sidecar_data.get_path("nonexistent")
        assert result is None

    def test_each_path_findable(self, sidecar_data):
        for i in range(6):
            result = sidecar_data.get_path(f"form_edge_{i}")
            assert result is not None


# ---------------------------------------------------------------------------
# SidecarData.paths_on_surface tests
# ---------------------------------------------------------------------------


class TestPathsOnSurface:
    """Tests for SidecarData.paths_on_surface method."""

    def test_convex_filter(self, sidecar_data):
        convex = sidecar_data.paths_on_surface("convex")
        assert len(convex) == 2
        assert all(p.dominant_surface == "convex" for p in convex)

    def test_flat_filter(self, sidecar_data):
        flat = sidecar_data.paths_on_surface("flat")
        assert len(flat) == 1
        assert flat[0].name == "form_edge_1"

    def test_concave_filter(self, sidecar_data):
        concave = sidecar_data.paths_on_surface("concave")
        assert len(concave) == 1
        assert concave[0].name == "form_edge_2"

    def test_saddle_filter(self, sidecar_data):
        saddle = sidecar_data.paths_on_surface("saddle")
        assert len(saddle) == 1
        assert saddle[0].name == "form_edge_3"

    def test_cylindrical_filter(self, sidecar_data):
        cylindrical = sidecar_data.paths_on_surface("cylindrical")
        assert len(cylindrical) == 1
        assert cylindrical[0].name == "form_edge_4"

    def test_unknown_surface_returns_empty(self, sidecar_data):
        result = sidecar_data.paths_on_surface("nonexistent_type")
        assert result == []


# ---------------------------------------------------------------------------
# SidecarData.surface_similarity tests
# ---------------------------------------------------------------------------


class TestSurfaceSimilarity:
    """Tests for SidecarData.surface_similarity method."""

    def test_same_type_similar_curvature(self, sidecar_data):
        # form_edge_0 (convex, 0.04) vs form_edge_5 (convex, 0.05)
        score = sidecar_data.surface_similarity("form_edge_0", "form_edge_5")
        # Same type = 0.7 base, curvature diff = 0.01 -> bonus = 0.3 - 0.1 = 0.2
        assert score == pytest.approx(0.9, abs=0.01)

    def test_same_type_different_curvature(self, sidecar_data):
        # Both convex but different curvature magnitudes
        score = sidecar_data.surface_similarity("form_edge_0", "form_edge_5")
        assert score > 0.7  # At least the type match base

    def test_different_type(self, sidecar_data):
        # convex vs flat
        score = sidecar_data.surface_similarity("form_edge_0", "form_edge_1")
        assert score < 0.7  # No type match base

    def test_completely_different(self, sidecar_data):
        # convex (0.04) vs concave (-0.03)
        score = sidecar_data.surface_similarity("form_edge_0", "form_edge_2")
        # Different type = 0.0 base, curvature diff = 0.07 -> bonus = max(0, 0.3 - 0.7) = 0
        assert score == pytest.approx(0.0, abs=0.01)

    def test_unknown_path_returns_neutral(self, sidecar_data):
        score = sidecar_data.surface_similarity("form_edge_0", "nonexistent")
        assert score == 0.5

    def test_both_unknown_returns_neutral(self, sidecar_data):
        score = sidecar_data.surface_similarity("missing_a", "missing_b")
        assert score == 0.5

    def test_identical_path(self, sidecar_data):
        # Same path compared with itself
        score = sidecar_data.surface_similarity("form_edge_0", "form_edge_0")
        assert score == 1.0


# ---------------------------------------------------------------------------
# SidecarData.suggest_shape_type tests
# ---------------------------------------------------------------------------


class TestSuggestShapeType:
    """Tests for SidecarData.suggest_shape_type method."""

    def test_flat_suggests_line(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("form_edge_1")
        assert result == "line"

    def test_convex_suggests_arc(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("form_edge_0")
        assert result == "arc"

    def test_concave_suggests_arc(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("form_edge_2")
        assert result == "arc"

    def test_saddle_suggests_scurve(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("form_edge_3")
        assert result == "scurve"

    def test_cylindrical_suggests_arc(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("form_edge_4")
        assert result == "arc"

    def test_unknown_path_returns_none(self, sidecar_data):
        result = sidecar_data.suggest_shape_type("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# find_sidecar tests
# ---------------------------------------------------------------------------


class TestFindSidecar:
    """Tests for find_sidecar function."""

    def test_finds_existing_sidecar(self, tmp_path):
        sidecar = tmp_path / "mydoc_normals.json"
        sidecar.write_text("{}")
        result = find_sidecar("mydoc", cache_dir=tmp_path)
        assert result is not None
        assert result == sidecar

    def test_returns_none_for_missing(self, tmp_path):
        result = find_sidecar("nonexistent", cache_dir=tmp_path)
        assert result is None

    def test_returns_none_for_missing_dir(self):
        result = find_sidecar("doc", cache_dir="/tmp/nonexistent_dir_12345")
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests — end-to-end schema validation
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_load_sidecar_from_form_edge_schema(self, tmp_path):
        """Validate the actual schema form_edge_extract would produce."""
        real_schema = {
            "image_hash": "abc123def456",
            "timestamp": "2026-04-04T15:00:00+00:00",
            "paths": [{
                "name": "form_edge_0",
                "layer": "Form Edges",
                "dominant_surface": "convex",
                "mean_curvature": 0.04,
                "is_silhouette": False,
                "mean_depth_facing": 0.85,
                "anchor_count": 12,
            }],
        }
        path = tmp_path / "test_normals.json"
        path.write_text(json.dumps(real_schema))
        result = load_sidecar(path)
        assert result is not None
        assert result.paths[0].dominant_surface == "convex"
        assert result.paths[0].mean_curvature == pytest.approx(0.04)

    def test_missing_fields_use_defaults(self, tmp_path):
        """Missing fields should get defaults, not crash."""
        minimal = {"image_hash": "x", "paths": [{"name": "p0"}]}
        path = tmp_path / "minimal.json"
        path.write_text(json.dumps(minimal))
        result = load_sidecar(path)
        assert result.paths[0].dominant_surface == "flat"
        assert result.paths[0].mean_curvature == 0.0
        assert result.paths[0].anchor_count == 0
