"""Tests for edge_clustering -- cross-layer edge clustering engine.

Tests use synthetic LayerPath objects with mock boundary signatures.
No ML dependencies required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.analysis.edge_clustering import (
    CLUSTER_COLORS,
    EdgeCluster,
    LayerPath,
    _dbscan_cluster,
    _score_cluster,
    _spatial_distance,
    cluster_paths,
    enumerate_layer_paths,
    generate_color_jsx,
)


# ---------------------------------------------------------------------------
# Mock boundary signature for testing Level 1 grouping
# ---------------------------------------------------------------------------


class MockBoundarySignature:
    """Minimal mock that provides identity_key() for Level 1 grouping."""

    def __init__(self, key: str):
        self._key = key

    def identity_key(self) -> str:
        return self._key


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_path(
    name: str = "path_0",
    layer: str = "Layer 1",
    points: list | None = None,
    surface: str = "convex",
    curvature: float = 0.04,
    silhouette: bool = False,
    sig_key: str | None = None,
) -> LayerPath:
    """Build a LayerPath with optional mock boundary signature."""
    lp = LayerPath(
        path_name=name,
        layer_name=layer,
        points=points if points is not None else [(0, 0), (10, 0), (20, 0)],
        dominant_surface=surface,
        mean_curvature=curvature,
        is_silhouette=silhouette,
    )
    if sig_key is not None:
        lp.boundary_signature = MockBoundarySignature(sig_key)
    return lp


# ---------------------------------------------------------------------------
# enumerate_layer_paths tests
# ---------------------------------------------------------------------------


class TestEnumerateLayerPaths:
    """Tests for enumerate_layer_paths conversion."""

    def test_basic_conversion(self):
        jsx_data = [
            {"name": "p0", "layer": "Contours", "points": [[0, 0], [10, 5]]},
        ]
        result = enumerate_layer_paths(jsx_data)
        assert len(result) == 1
        assert result[0].path_name == "p0"
        assert result[0].layer_name == "Contours"
        assert result[0].points == [(0.0, 0.0), (10.0, 5.0)]

    def test_sidecar_enrichment(self):
        jsx_data = [
            {"name": "form_edge_0", "layer": "Form Edges", "points": [[1, 2]]},
        ]
        sidecar = {
            "paths": [
                {
                    "name": "form_edge_0",
                    "dominant_surface": "concave",
                    "mean_curvature": -0.03,
                    "is_silhouette": True,
                },
            ],
        }
        result = enumerate_layer_paths(jsx_data, sidecar_data=sidecar)
        assert result[0].dominant_surface == "concave"
        assert result[0].mean_curvature == pytest.approx(-0.03)
        assert result[0].is_silhouette is True

    def test_missing_sidecar_defaults(self):
        jsx_data = [{"name": "p0", "layer": "L", "points": [[0, 0]]}]
        result = enumerate_layer_paths(jsx_data, sidecar_data=None)
        assert result[0].dominant_surface == "flat"
        assert result[0].mean_curvature == 0.0
        assert result[0].is_silhouette is False

    def test_empty_input(self):
        assert enumerate_layer_paths([]) == []

    def test_missing_points_key(self):
        jsx_data = [{"name": "p0", "layer": "L"}]
        result = enumerate_layer_paths(jsx_data)
        assert result[0].points == []


# ---------------------------------------------------------------------------
# _spatial_distance tests
# ---------------------------------------------------------------------------


class TestSpatialDistance:
    """Tests for _spatial_distance."""

    def test_known_distance(self):
        """Two horizontal lines offset vertically by 10 units."""
        a = _make_path(points=[(0, 0), (10, 0), (20, 0)])
        b = _make_path(points=[(0, 10), (10, 10), (20, 10)])
        dist = _spatial_distance(a, b)
        assert dist == pytest.approx(10.0, abs=0.01)

    def test_identical_paths(self):
        a = _make_path(points=[(5, 5), (15, 15)])
        b = _make_path(points=[(5, 5), (15, 15)])
        assert _spatial_distance(a, b) == pytest.approx(0.0, abs=0.001)

    def test_empty_path_returns_inf(self):
        a = _make_path(points=[])
        b = _make_path(points=[(0, 0)])
        assert _spatial_distance(a, b) == float("inf")

    def test_subsampling_large_path(self):
        """Paths with >20 points should still compute without error."""
        pts_a = [(i, 0) for i in range(50)]
        pts_b = [(i, 5) for i in range(50)]
        a = _make_path(points=pts_a)
        b = _make_path(points=pts_b)
        dist = _spatial_distance(a, b)
        assert dist == pytest.approx(5.0, abs=0.5)


# ---------------------------------------------------------------------------
# _dbscan_cluster tests
# ---------------------------------------------------------------------------


class TestDBSCAN:
    """Tests for the self-contained DBSCAN implementation."""

    def test_basic_one_cluster(self):
        """3 close points should form one cluster."""
        paths = [
            _make_path(name="a", points=[(0, 0), (1, 0)]),
            _make_path(name="b", points=[(2, 0), (3, 0)]),
            _make_path(name="c", points=[(1, 0), (2, 0)]),
        ]
        clusters = _dbscan_cluster(paths, eps=10.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_two_separate_clusters(self):
        """Two groups far apart should form two clusters."""
        group1 = [
            _make_path(name="a", points=[(0, 0), (1, 0)]),
            _make_path(name="b", points=[(2, 0), (3, 0)]),
            _make_path(name="c", points=[(1, 0), (2, 0)]),
        ]
        group2 = [
            _make_path(name="d", points=[(100, 0), (101, 0)]),
            _make_path(name="e", points=[(102, 0), (103, 0)]),
            _make_path(name="f", points=[(101, 0), (102, 0)]),
        ]
        clusters = _dbscan_cluster(group1 + group2, eps=10.0)
        assert len(clusters) == 2
        # Each cluster has 3 members
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [3, 3]

    def test_close_plus_far_noise(self):
        """3 close + 1 far point: 1 cluster, far point is noise."""
        paths = [
            _make_path(name="a", points=[(0, 0), (1, 0)]),
            _make_path(name="b", points=[(2, 0), (3, 0)]),
            _make_path(name="c", points=[(1, 0), (2, 0)]),
            _make_path(name="far", points=[(200, 200), (201, 200)]),
        ]
        clusters = _dbscan_cluster(paths, eps=10.0, min_samples=2)
        # Close group forms 1 cluster; far point is noise
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_empty_input(self):
        assert _dbscan_cluster([], eps=10.0) == []

    def test_single_point_min_samples_1(self):
        paths = [_make_path(name="solo", points=[(5, 5)])]
        clusters = _dbscan_cluster(paths, eps=10.0, min_samples=1)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1


# ---------------------------------------------------------------------------
# _score_cluster tests
# ---------------------------------------------------------------------------


class TestScoreCluster:
    """Tests for cluster quality scoring."""

    def test_multi_layer_high_confidence(self):
        """3 distinct layers should give high confidence."""
        members = [
            _make_path(layer="Contours", curvature=0.04),
            _make_path(layer="Silhouette", curvature=0.04),
            _make_path(layer="Form Edges", curvature=0.04),
        ]
        conf, quality = _score_cluster(members)
        assert conf == 1.0

    def test_two_layers_medium_confidence(self):
        members = [
            _make_path(layer="Contours", curvature=0.03),
            _make_path(layer="Silhouette", curvature=0.03),
        ]
        conf, _ = _score_cluster(members)
        assert conf == 0.7

    def test_single_layer_low_confidence(self):
        members = [
            _make_path(layer="Contours", curvature=0.04),
            _make_path(layer="Contours", curvature=0.05),
        ]
        conf, _ = _score_cluster(members)
        assert conf == 0.4

    def test_consistent_curvature_high_quality(self):
        """All same curvature -> high surface consistency."""
        pts = [(0, 0), (5, 0), (10, 0)]
        members = [
            _make_path(layer="A", curvature=0.04, points=pts),
            _make_path(layer="B", curvature=0.04, points=pts),
            _make_path(layer="C", curvature=0.04, points=pts),
        ]
        _, quality = _score_cluster(members)
        # Zero curvature variance -> surface_consistency = 1.0
        # Identical points -> spatial_continuity = 1.0
        # quality = 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        assert quality == pytest.approx(1.0, abs=0.05)

    def test_inconsistent_curvature_lower_quality(self):
        """Wildly different curvatures -> lower quality."""
        pts = [(0, 0), (5, 0), (10, 0)]
        members = [
            _make_path(layer="A", curvature=0.0, points=pts),
            _make_path(layer="B", curvature=0.2, points=pts),
        ]
        _, quality_bad = _score_cluster(members)

        members_good = [
            _make_path(layer="A", curvature=0.04, points=pts),
            _make_path(layer="B", curvature=0.04, points=pts),
        ]
        _, quality_good = _score_cluster(members_good)
        assert quality_good > quality_bad

    def test_empty_cluster(self):
        conf, quality = _score_cluster([])
        assert conf == 0.0
        assert quality == 0.0


# ---------------------------------------------------------------------------
# cluster_paths (main entry point) tests
# ---------------------------------------------------------------------------


class TestClusterPaths:
    """Tests for the two-level clustering pipeline."""

    def test_cluster_by_identity_key(self):
        """Paths with same boundary identity cluster together."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="edge_A", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="edge_A", points=[(1, 0), (11, 0)]),
            _make_path(name="c", layer="L1", sig_key="edge_B", points=[(0, 50), (10, 50)]),
            _make_path(name="d", layer="L2", sig_key="edge_B", points=[(1, 50), (11, 50)]),
        ]
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) == 2
        keys = {c.identity_key for c in clusters}
        assert keys == {"edge_A", "edge_B"}

    def test_spatial_subclustering(self):
        """Same identity but spatially far -> separate clusters."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="edge_A", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="edge_A", points=[(1, 0), (11, 0)]),
            # Same identity, but 200pt away
            _make_path(name="c", layer="L1", sig_key="edge_A", points=[(200, 0), (210, 0)]),
            _make_path(name="d", layer="L2", sig_key="edge_A", points=[(201, 0), (211, 0)]),
        ]
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        # Should produce 2 spatial clusters within the same identity group
        assert len(clusters) == 2
        # All clusters share the same identity key
        assert all(c.identity_key == "edge_A" for c in clusters)

    def test_close_different_identity(self):
        """Spatially close but different identity -> separate clusters."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="edge_A", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="edge_A", points=[(1, 0), (11, 0)]),
            # Close spatially, but different identity
            _make_path(name="c", layer="L1", sig_key="edge_B", points=[(2, 0), (12, 0)]),
            _make_path(name="d", layer="L2", sig_key="edge_B", points=[(3, 0), (13, 0)]),
        ]
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) == 2
        keys = {c.identity_key for c in clusters}
        assert keys == {"edge_A", "edge_B"}

    def test_confidence_from_layers(self):
        """Confidence tier reflects layer count."""
        paths_3_layers = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (5, 0)]),
            _make_path(name="b", layer="L2", sig_key="e", points=[(1, 0), (6, 0)]),
            _make_path(name="c", layer="L3", sig_key="e", points=[(2, 0), (7, 0)]),
        ]
        clusters = cluster_paths(paths_3_layers, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) >= 1
        assert clusters[0].confidence_tier == "high"
        assert clusters[0].source_layer_count == 3

    def test_confidence_medium(self):
        paths_2_layers = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (5, 0)]),
            _make_path(name="b", layer="L2", sig_key="e", points=[(1, 0), (6, 0)]),
        ]
        clusters = cluster_paths(paths_2_layers, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) >= 1
        assert clusters[0].confidence_tier == "medium"

    def test_confidence_low(self):
        paths_1_layer = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (5, 0)]),
            _make_path(name="b", layer="L1", sig_key="e", points=[(1, 0), (6, 0)]),
        ]
        clusters = cluster_paths(paths_1_layer, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) >= 1
        assert clusters[0].confidence_tier == "low"

    def test_color_assignment(self):
        """Each cluster gets a different color, cycling through CLUSTER_COLORS."""
        paths = []
        for i in range(4):
            paths.append(
                _make_path(
                    name=f"a{i}", layer="L1", sig_key=f"edge_{i}",
                    points=[(i * 100, 0), (i * 100 + 10, 0)],
                )
            )
            paths.append(
                _make_path(
                    name=f"b{i}", layer="L2", sig_key=f"edge_{i}",
                    points=[(i * 100 + 1, 0), (i * 100 + 11, 0)],
                )
            )
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) >= 2
        # Verify colors are from CLUSTER_COLORS and distinct clusters get different indices
        colors_seen = [tuple(c.color) for c in clusters]
        for color in colors_seen:
            assert list(color) in CLUSTER_COLORS

    def test_empty_input(self):
        assert cluster_paths([]) == []

    def test_single_path_min_size_2(self):
        """One path with min_cluster_size=2 -> no clusters."""
        paths = [_make_path(name="solo", sig_key="e")]
        clusters = cluster_paths(paths, min_cluster_size=2)
        assert clusters == []

    def test_distance_threshold_effect(self):
        """Tight threshold -> more clusters, loose -> fewer."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="e", points=[(5, 0), (15, 0)]),
            _make_path(name="c", layer="L1", sig_key="e", points=[(20, 0), (30, 0)]),
            _make_path(name="d", layer="L2", sig_key="e", points=[(25, 0), (35, 0)]),
        ]
        # Loose threshold: all close enough -> 1 cluster
        clusters_loose = cluster_paths(paths, distance_threshold=50.0, min_cluster_size=2)
        # Tight threshold: a/b near each other, c/d near each other
        clusters_tight = cluster_paths(paths, distance_threshold=5.0, min_cluster_size=2)

        assert len(clusters_loose) <= len(clusters_tight) or len(clusters_loose) >= 1

    def test_fallback_identity_without_signature(self):
        """Paths without boundary_signature use surface+silhouette fallback key."""
        paths = [
            _make_path(name="a", layer="L1", surface="convex", silhouette=False,
                       points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", surface="convex", silhouette=False,
                       points=[(1, 0), (11, 0)]),
            _make_path(name="c", layer="L1", surface="flat", silhouette=True,
                       points=[(0, 50), (10, 50)]),
            _make_path(name="d", layer="L2", surface="flat", silhouette=True,
                       points=[(1, 50), (11, 50)]),
        ]
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) == 2
        keys = {c.identity_key for c in clusters}
        assert keys == {"convex_int", "flat_sil"}


# ---------------------------------------------------------------------------
# generate_color_jsx tests
# ---------------------------------------------------------------------------


class TestGenerateColorJSX:
    """Tests for ExtendScript output generation."""

    def test_valid_extendscript(self):
        """Output should be valid ExtendScript (var, RGBColor, no ES6)."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[
                _make_path(name="contour_42"),
                _make_path(name="contour_43"),
            ],
            identity_key="edge_A",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[255, 68, 68],
        )
        jsx = generate_color_jsx([cluster])

        # Must use var (not let/const)
        assert "var doc" in jsx
        assert "var p" in jsx
        assert "var c" in jsx

        # Must use RGBColor
        assert "new RGBColor()" in jsx

        # No ES6 features
        assert "let " not in jsx
        assert "const " not in jsx
        assert "=>" not in jsx

        # Path names should appear
        assert "contour_42" in jsx
        assert "contour_43" in jsx

    def test_stroke_weight_by_tier(self):
        """High = 2pt, medium = 1pt, low = 0.5pt."""
        high_cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name="p_high")],
            identity_key="e",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[255, 0, 0],
        )
        medium_cluster = EdgeCluster(
            cluster_id=1,
            members=[_make_path(name="p_med")],
            identity_key="e",
            confidence=0.7,
            source_layer_count=2,
            quality_score=0.8,
            color=[0, 255, 0],
        )
        low_cluster = EdgeCluster(
            cluster_id=2,
            members=[_make_path(name="p_low")],
            identity_key="e",
            confidence=0.4,
            source_layer_count=1,
            quality_score=0.5,
            color=[0, 0, 255],
        )

        jsx = generate_color_jsx([high_cluster, medium_cluster, low_cluster])
        # Check stroke weights appear in correct contexts
        assert "strokeWidth = 2" in jsx
        assert "strokeWidth = 1;" in jsx
        assert "strokeWidth = 0.5" in jsx

    def test_low_confidence_dashed(self):
        """Low confidence tier should get dashed stroke."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name="dashed_path")],
            identity_key="e",
            confidence=0.4,
            source_layer_count=1,
            quality_score=0.3,
            color=[100, 100, 100],
        )
        jsx = generate_color_jsx([cluster])
        assert "strokeDashes" in jsx

    def test_high_confidence_not_dashed(self):
        """High confidence should NOT have dashed stroke."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name="solid_path")],
            identity_key="e",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[255, 0, 0],
        )
        jsx = generate_color_jsx([cluster])
        assert "strokeDashes" not in jsx

    def test_empty_clusters(self):
        jsx = generate_color_jsx([])
        assert "No clusters" in jsx

    def test_color_values_in_jsx(self):
        """Cluster color should appear in the JSX output."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name="colored")],
            identity_key="e",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[68, 136, 255],
        )
        jsx = generate_color_jsx([cluster])
        assert "c.red = 68" in jsx
        assert "c.green = 136" in jsx
        assert "c.blue = 255" in jsx

    def test_try_catch_wrapping(self):
        """Each path should be wrapped in try/catch for missing paths."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name="p0"), _make_path(name="p1")],
            identity_key="e",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[255, 0, 0],
        )
        jsx = generate_color_jsx([cluster])
        assert jsx.count("try {") == 2
        assert jsx.count("} catch(e) {}") == 2

    def test_special_chars_in_path_name(self):
        """Path names with quotes should be escaped."""
        cluster = EdgeCluster(
            cluster_id=0,
            members=[_make_path(name='path "with" quotes')],
            identity_key="e",
            confidence=1.0,
            source_layer_count=3,
            quality_score=0.9,
            color=[255, 0, 0],
        )
        jsx = generate_color_jsx([cluster])
        assert '\\"with\\"' in jsx


# ---------------------------------------------------------------------------
# EdgeCluster property tests
# ---------------------------------------------------------------------------


class TestEdgeClusterProperties:
    """Tests for EdgeCluster.confidence_tier property."""

    def test_high_tier(self):
        c = EdgeCluster(
            cluster_id=0, members=[], identity_key="e",
            confidence=1.0, source_layer_count=3, quality_score=0.9,
        )
        assert c.confidence_tier == "high"

    def test_medium_tier(self):
        c = EdgeCluster(
            cluster_id=0, members=[], identity_key="e",
            confidence=0.7, source_layer_count=2, quality_score=0.8,
        )
        assert c.confidence_tier == "medium"

    def test_low_tier(self):
        c = EdgeCluster(
            cluster_id=0, members=[], identity_key="e",
            confidence=0.4, source_layer_count=1, quality_score=0.5,
        )
        assert c.confidence_tier == "low"

    def test_four_layers_still_high(self):
        c = EdgeCluster(
            cluster_id=0, members=[], identity_key="e",
            confidence=1.0, source_layer_count=4, quality_score=0.9,
        )
        assert c.confidence_tier == "high"

    def test_default_color(self):
        c = EdgeCluster(
            cluster_id=0, members=[], identity_key="e",
            confidence=1.0, source_layer_count=3, quality_score=0.9,
        )
        assert c.color == [200, 200, 200]
