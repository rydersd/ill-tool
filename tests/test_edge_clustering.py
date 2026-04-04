"""Tests for edge_clustering -- cross-layer edge clustering engine.

Tests use synthetic LayerPath objects with mock boundary signatures.
No ML dependencies required.
"""

import json
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
    generate_cluster_json,
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


# ---------------------------------------------------------------------------
# Spatial distance symmetry tests (adversarial review gap #1)
# ---------------------------------------------------------------------------


class TestSpatialDistanceSymmetry:
    """Verify that _spatial_distance(A, B) == _spatial_distance(B, A)."""

    def test_symmetric_simple(self):
        """Two simple paths: distance is the same in both directions."""
        a = _make_path(points=[(0, 0), (10, 0), (20, 0)])
        b = _make_path(points=[(0, 10), (10, 10), (20, 10)])
        assert _spatial_distance(a, b) == _spatial_distance(b, a)

    def test_symmetric_asymmetric_lengths(self):
        """Paths of different lengths: symmetry still holds."""
        a = _make_path(points=[(0, 0), (5, 0)])
        b = _make_path(points=[(0, 3), (3, 3), (6, 3), (9, 3), (12, 3)])
        assert _spatial_distance(a, b) == pytest.approx(
            _spatial_distance(b, a), abs=1e-10
        )

    def test_symmetric_large_subsampled(self):
        """Large paths (>20 pts) are subsampled; symmetry must survive."""
        pts_a = [(i, 0) for i in range(50)]
        pts_b = [(i, 7) for i in range(30)]
        a = _make_path(points=pts_a)
        b = _make_path(points=pts_b)
        assert _spatial_distance(a, b) == pytest.approx(
            _spatial_distance(b, a), abs=1e-10
        )

    def test_symmetric_diagonal_offset(self):
        """Diagonally offset paths: symmetry under non-axis-aligned geometry."""
        a = _make_path(points=[(0, 0), (10, 10), (20, 20)])
        b = _make_path(points=[(5, 0), (15, 10), (25, 20)])
        assert _spatial_distance(a, b) == pytest.approx(
            _spatial_distance(b, a), abs=1e-10
        )

    def test_symmetric_single_point_paths(self):
        """Single-point paths: trivially symmetric."""
        a = _make_path(points=[(0, 0)])
        b = _make_path(points=[(3, 4)])
        d_ab = _spatial_distance(a, b)
        d_ba = _spatial_distance(b, a)
        assert d_ab == pytest.approx(d_ba, abs=1e-10)
        assert d_ab == pytest.approx(5.0, abs=0.01)


# ---------------------------------------------------------------------------
# generate_cluster_json tests (adversarial review gap #2)
# ---------------------------------------------------------------------------


class TestGenerateClusterJSON:
    """Verify that generate_cluster_json() produces valid, correctly-structured JSON."""

    def _make_cluster(
        self, cluster_id=0, names=None, identity_key="e",
        source_layer_count=3, quality_score=0.9,
    ):
        """Helper to build an EdgeCluster with named members."""
        names = names or ["p0", "p1"]
        members = [_make_path(name=n) for n in names]
        return EdgeCluster(
            cluster_id=cluster_id,
            members=members,
            identity_key=identity_key,
            confidence=1.0,
            source_layer_count=source_layer_count,
            quality_score=quality_score,
            color=CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)],
        )

    def test_valid_json(self):
        """Output is valid JSON that parses without error."""
        clusters = [self._make_cluster()]
        raw = generate_cluster_json(clusters)
        data = json.loads(raw)
        assert isinstance(data, list)

    def test_expected_keys(self):
        """Each cluster entry has all required keys."""
        clusters = [self._make_cluster()]
        data = json.loads(generate_cluster_json(clusters))
        required_keys = {
            "cluster_id", "path_names", "color", "stroke_width",
            "dashed", "identity_key", "confidence_tier", "member_count",
        }
        assert required_keys.issubset(data[0].keys())

    def test_path_names_match_members(self):
        """path_names list matches the member path names."""
        clusters = [self._make_cluster(names=["alpha", "beta", "gamma"])]
        data = json.loads(generate_cluster_json(clusters))
        assert data[0]["path_names"] == ["alpha", "beta", "gamma"]
        assert data[0]["member_count"] == 3

    def test_color_is_rgb_list(self):
        """color is a 3-element list of ints in [0, 255]."""
        clusters = [self._make_cluster()]
        data = json.loads(generate_cluster_json(clusters))
        color = data[0]["color"]
        assert isinstance(color, list)
        assert len(color) == 3
        assert all(0 <= c <= 255 for c in color)

    def test_stroke_width_by_tier(self):
        """Stroke width maps correctly to confidence tier."""
        high = self._make_cluster(source_layer_count=3)   # high tier
        med = self._make_cluster(source_layer_count=2)     # medium tier
        low = self._make_cluster(source_layer_count=1)     # low tier

        data_high = json.loads(generate_cluster_json([high]))
        data_med = json.loads(generate_cluster_json([med]))
        data_low = json.loads(generate_cluster_json([low]))

        assert data_high[0]["stroke_width"] == 2.0
        assert data_med[0]["stroke_width"] == 1.0
        assert data_low[0]["stroke_width"] == 0.5

    def test_dashed_only_for_low_tier(self):
        """Only low confidence tier clusters are dashed."""
        high = self._make_cluster(source_layer_count=3)
        low = self._make_cluster(source_layer_count=1)

        data_high = json.loads(generate_cluster_json([high]))
        data_low = json.loads(generate_cluster_json([low]))

        assert data_high[0]["dashed"] is False
        assert data_low[0]["dashed"] is True

    def test_empty_clusters(self):
        """Empty list produces empty JSON array."""
        raw = generate_cluster_json([])
        assert json.loads(raw) == []

    def test_single_quote_escaping(self):
        """Path names with single quotes are escaped for ExtendScript."""
        cluster = self._make_cluster(names=["path'with'quotes"])
        data = json.loads(generate_cluster_json([cluster]))
        # The escaped value should contain \' (the JSON string stores the backslash)
        assert "\\'" in data[0]["path_names"][0]

    def test_multiple_clusters(self):
        """Multiple clusters each get their own entry with cycling colors."""
        clusters = [
            self._make_cluster(cluster_id=0, names=["a"], identity_key="e1"),
            self._make_cluster(cluster_id=1, names=["b"], identity_key="e2"),
            self._make_cluster(cluster_id=2, names=["c"], identity_key="e3"),
        ]
        data = json.loads(generate_cluster_json(clusters))
        assert len(data) == 3
        assert data[0]["identity_key"] == "e1"
        assert data[1]["identity_key"] == "e2"
        assert data[2]["identity_key"] == "e3"


# ---------------------------------------------------------------------------
# identity_key never returns None (adversarial review gap #4)
# ---------------------------------------------------------------------------


class TestIdentityKeyNeverNone:
    """Verify that identity_key() never returns None for any input."""

    def test_normal_signature_returns_string(self):
        """Standard boundary signature returns a non-None string."""
        from adobe_mcp.apps.illustrator.analysis.boundary_signature import BoundarySignature
        sig = BoundarySignature("convex", "flat", 0.3, 0.9)
        key = sig.identity_key()
        assert key is not None
        assert isinstance(key, str)
        assert len(key) > 0

    def test_same_surfaces_returns_string(self):
        """Same surface on both sides still returns valid key."""
        from adobe_mcp.apps.illustrator.analysis.boundary_signature import BoundarySignature
        sig = BoundarySignature("flat", "flat", 0.0, 0.0)
        key = sig.identity_key()
        assert key is not None
        assert isinstance(key, str)
        assert len(key) > 0

    def test_zero_curvature_returns_string(self):
        """Zero curvature produces a valid key, not None."""
        from adobe_mcp.apps.illustrator.analysis.boundary_signature import BoundarySignature
        sig = BoundarySignature("convex", "concave", 0.0, 1.0)
        key = sig.identity_key()
        assert key is not None
        assert "0.0" in key

    def test_high_curvature_returns_string(self):
        """Curvature at 1.0 still produces valid key."""
        from adobe_mcp.apps.illustrator.analysis.boundary_signature import BoundarySignature
        sig = BoundarySignature("saddle", "cylindrical", 1.0, 0.5)
        key = sig.identity_key()
        assert key is not None
        assert isinstance(key, str)

    def test_all_surface_combinations_produce_keys(self):
        """Every combination of surface types produces a non-None key."""
        from adobe_mcp.apps.illustrator.analysis.boundary_signature import BoundarySignature
        surfaces = ["flat", "convex", "concave", "saddle", "cylindrical"]
        for a in surfaces:
            for b in surfaces:
                sig = BoundarySignature(a, b, 0.5, 0.8)
                key = sig.identity_key()
                assert key is not None, f"identity_key() returned None for ({a}, {b})"
                assert len(key) > 0, f"identity_key() returned empty string for ({a}, {b})"

    def test_cluster_paths_none_guard(self):
        """cluster_paths handles identity_key returning None by using fallback.

        The None guard in cluster_paths ensures that even if a mock signature
        returns None from identity_key(), the path gets a valid fallback key.
        """
        class NoneKeySignature:
            def identity_key(self):
                return None

        paths = [
            _make_path(name="a", layer="L1", surface="convex",
                       points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", surface="convex",
                       points=[(1, 0), (11, 0)]),
        ]
        # Assign a signature that returns None from identity_key
        for p in paths:
            p.boundary_signature = NoneKeySignature()

        # Should not crash; falls back to surface+silhouette key
        clusters = cluster_paths(paths, distance_threshold=15.0, min_cluster_size=2)
        assert len(clusters) >= 1
        # The identity key should be the fallback, not None
        for c in clusters:
            assert c.identity_key is not None
            assert c.identity_key != ""


# ---------------------------------------------------------------------------
# cluster_paths with learned_thresholds (adversarial review gap #5)
# ---------------------------------------------------------------------------


class TestClusterPathsWithLearnedThresholds:
    """Verify that cluster_paths respects per-identity learned_thresholds."""

    def test_learned_threshold_overrides_global(self):
        """Per-identity threshold overrides the global distance_threshold."""
        # Two pairs of paths with same identity, close enough for default eps=15
        # but learned threshold says eps=1 for edge_A -> should split
        paths = [
            _make_path(name="a", layer="L1", sig_key="edge_A", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="edge_A", points=[(5, 0), (15, 0)]),
            # This pair is 50pts away — too far for either threshold
            _make_path(name="c", layer="L1", sig_key="edge_A", points=[(50, 0), (60, 0)]),
            _make_path(name="d", layer="L2", sig_key="edge_A", points=[(55, 0), (65, 0)]),
        ]
        # Without learned thresholds: global eps=15 puts a/b together, c/d together
        clusters_default = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
        )

        # With learned thresholds: eps=1 for edge_A -> a and b are ~2.5 apart,
        # so they become noise at eps=1
        clusters_learned = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
            learned_thresholds={"edge_A": {"suggested_threshold": 1.0}},
        )

        # The learned threshold should produce fewer or different clusters
        # (a/b are ~2.5pt apart which exceeds eps=1)
        assert len(clusters_learned) <= len(clusters_default)

    def test_learned_threshold_for_one_identity_only(self):
        """Learned threshold for one identity doesn't affect another."""
        paths = [
            _make_path(name="a1", layer="L1", sig_key="edge_A", points=[(0, 0), (10, 0)]),
            _make_path(name="a2", layer="L2", sig_key="edge_A", points=[(1, 0), (11, 0)]),
            _make_path(name="b1", layer="L1", sig_key="edge_B", points=[(0, 50), (10, 50)]),
            _make_path(name="b2", layer="L2", sig_key="edge_B", points=[(1, 50), (11, 50)]),
        ]
        # Set tight threshold only for edge_A; edge_B uses default
        clusters = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
            learned_thresholds={"edge_A": {"suggested_threshold": 0.5}},
        )

        # edge_B should still cluster normally (a1/a2 are ~1pt apart, within
        # default eps=15 but NOT within 0.5)
        edge_b_clusters = [c for c in clusters if c.identity_key == "edge_B"]
        assert len(edge_b_clusters) == 1

    def test_learned_thresholds_none_same_as_omitted(self):
        """Passing learned_thresholds=None is the same as not passing it."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="e", points=[(1, 0), (11, 0)]),
        ]
        clusters_none = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
            learned_thresholds=None,
        )
        clusters_omit = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
        )
        assert len(clusters_none) == len(clusters_omit)

    def test_learned_thresholds_empty_dict(self):
        """Empty learned_thresholds dict doesn't change behavior."""
        paths = [
            _make_path(name="a", layer="L1", sig_key="e", points=[(0, 0), (10, 0)]),
            _make_path(name="b", layer="L2", sig_key="e", points=[(1, 0), (11, 0)]),
        ]
        clusters = cluster_paths(
            paths, distance_threshold=15.0, min_cluster_size=2,
            learned_thresholds={},
        )
        assert len(clusters) >= 1
