"""Tests for cluster threshold learning.

Tests recording cluster corrections, learning thresholds from
accept/split/reject/slider_adjust feedback, convergence tracking,
and cluster event parsing in the interaction ingest pipeline.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.analysis import correction_learning
from adobe_mcp.apps.illustrator.analysis.correction_learning import (
    record_cluster_correction,
    learn_cluster_thresholds,
    get_convergence_signal,
)
from adobe_mcp.apps.illustrator.interaction_ingest import _compute_cluster_stats


# ---------------------------------------------------------------------------
# Fixture: redirect CLUSTER_CORRECTIONS_PATH to tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture()
def cluster_tmp(tmp_path, monkeypatch):
    """Redirect cluster corrections storage to a temp file."""
    tmp_file = tmp_path / "cluster_corrections.json"
    monkeypatch.setattr(
        correction_learning, "CLUSTER_CORRECTIONS_PATH", tmp_file
    )
    return tmp_file


# ---------------------------------------------------------------------------
# Helper to build a context dict
# ---------------------------------------------------------------------------


def _ctx(distance_threshold=8.0, confidence=0.7, member_count=3,
         source_layers=2, quality_score=0.8):
    return {
        "member_count": member_count,
        "source_layers": source_layers,
        "distance_threshold": distance_threshold,
        "confidence": confidence,
        "quality_score": quality_score,
    }


# ===========================================================================
# record_cluster_correction
# ===========================================================================


class TestRecordClusterCorrection:
    """Tests for recording cluster corrections to disk."""

    def test_record_cluster_correction(self, cluster_tmp):
        """Records an accept correction and verifies the file format."""
        result = record_cluster_correction(
            action="accept",
            identity_key="cylindrical|flat|0.3",
            context=_ctx(distance_threshold=8.0, confidence=0.7),
        )

        assert result["action"] == "accept"
        assert result["identity_key"] == "cylindrical|flat|0.3"
        assert "timestamp" in result
        assert result["context"]["distance_threshold"] == 8.0

        # Verify file written with correct format
        data = json.loads(cluster_tmp.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["action"] == "accept"

    def test_record_multiple_corrections(self, cluster_tmp):
        """Records accept + split + reject, all stored in order."""
        record_cluster_correction("accept", "key_a", _ctx(distance_threshold=8.0))
        record_cluster_correction("split", "key_a", _ctx(distance_threshold=12.0))
        record_cluster_correction("reject", "key_b", _ctx(confidence=0.2))

        data = json.loads(cluster_tmp.read_text())
        assert len(data) == 3
        assert data[0]["action"] == "accept"
        assert data[1]["action"] == "split"
        assert data[2]["action"] == "reject"
        assert data[2]["identity_key"] == "key_b"

    def test_corrections_capped_at_2000(self, cluster_tmp):
        """Writing 2100 entries keeps only the last 2000."""
        # Pre-seed with 2100 entries via direct file write for speed
        entries = [
            {
                "action": "accept",
                "identity_key": f"key_{i}",
                "context": _ctx(),
                "timestamp": f"2026-01-01T00:00:{i:02d}",
            }
            for i in range(2100)
        ]
        cluster_tmp.parent.mkdir(parents=True, exist_ok=True)
        cluster_tmp.write_text(json.dumps(entries))

        # Record one more — should trigger cap
        record_cluster_correction("accept", "latest", _ctx())

        data = json.loads(cluster_tmp.read_text())
        assert len(data) == 2000
        # The oldest entries should be trimmed, latest should be present
        assert data[-1]["identity_key"] == "latest"


# ===========================================================================
# learn_cluster_thresholds
# ===========================================================================


class TestLearnClusterThresholds:
    """Tests for computing learned thresholds from corrections."""

    def test_learn_thresholds_accept_only(self, cluster_tmp):
        """All accepts at d=8 -> suggested_threshold = 8.0."""
        corrections = [
            {"action": "accept", "identity_key": "flat_int",
             "context": {"distance_threshold": 8.0, "confidence": 0.7},
             "timestamp": "2026-04-04T10:00:00"},
            {"action": "accept", "identity_key": "flat_int",
             "context": {"distance_threshold": 8.0, "confidence": 0.8},
             "timestamp": "2026-04-04T10:01:00"},
            {"action": "accept", "identity_key": "flat_int",
             "context": {"distance_threshold": 8.0, "confidence": 0.9},
             "timestamp": "2026-04-04T10:02:00"},
        ]

        result = learn_cluster_thresholds(corrections)

        assert "flat_int" in result
        assert result["flat_int"]["suggested_threshold"] == 8.0
        assert result["flat_int"]["accept_rate"] == 1.0
        assert result["flat_int"]["sample_count"] == 3

    def test_learn_thresholds_split_caps(self, cluster_tmp):
        """Accepts at d=10 + split at d=6 -> threshold capped below 6."""
        corrections = [
            {"action": "accept", "identity_key": "cyl_sil",
             "context": {"distance_threshold": 10.0}, "timestamp": "2026-04-04T10:00:00"},
            {"action": "accept", "identity_key": "cyl_sil",
             "context": {"distance_threshold": 10.0}, "timestamp": "2026-04-04T10:01:00"},
            {"action": "split", "identity_key": "cyl_sil",
             "context": {"distance_threshold": 6.0}, "timestamp": "2026-04-04T10:02:00"},
        ]

        result = learn_cluster_thresholds(corrections)

        assert "cyl_sil" in result
        # Split at 6 -> cap at 6 * 0.8 = 4.8
        assert result["cyl_sil"]["suggested_threshold"] == 4.8

    def test_learn_thresholds_slider_overrides(self, cluster_tmp):
        """Slider adjust is the strongest signal, overriding accepts/splits."""
        corrections = [
            {"action": "accept", "identity_key": "key_x",
             "context": {"distance_threshold": 8.0}, "timestamp": "2026-04-04T10:00:00"},
            {"action": "split", "identity_key": "key_x",
             "context": {"distance_threshold": 12.0}, "timestamp": "2026-04-04T10:01:00"},
            {"action": "slider_adjust", "identity_key": "key_x",
             "context": {"distance_threshold": 5.0}, "timestamp": "2026-04-04T10:02:00"},
        ]

        result = learn_cluster_thresholds(corrections)

        assert "key_x" in result
        # Slider adjust at 5.0 overrides everything
        assert result["key_x"]["suggested_threshold"] == 5.0

    def test_learn_thresholds_reject_confidence(self, cluster_tmp):
        """Rejects at conf=0.3 -> reject_below_confidence = 0.3."""
        corrections = [
            {"action": "accept", "identity_key": "key_r",
             "context": {"distance_threshold": 8.0, "confidence": 0.8},
             "timestamp": "2026-04-04T10:00:00"},
            {"action": "reject", "identity_key": "key_r",
             "context": {"distance_threshold": 8.0, "confidence": 0.3},
             "timestamp": "2026-04-04T10:01:00"},
        ]

        result = learn_cluster_thresholds(corrections)

        assert "key_r" in result
        assert result["key_r"]["reject_below_confidence"] == 0.3

    def test_learn_thresholds_empty(self, cluster_tmp):
        """No corrections -> empty dict."""
        result = learn_cluster_thresholds([])
        assert result == {}

    def test_accept_rate_per_identity(self, cluster_tmp):
        """Different identity keys have different accept rates."""
        corrections = [
            # Key A: 3 accepts, 1 reject -> 0.75
            {"action": "accept", "identity_key": "key_a",
             "context": {"distance_threshold": 8.0}, "timestamp": "2026-04-04T10:00:00"},
            {"action": "accept", "identity_key": "key_a",
             "context": {"distance_threshold": 8.0}, "timestamp": "2026-04-04T10:01:00"},
            {"action": "accept", "identity_key": "key_a",
             "context": {"distance_threshold": 8.0}, "timestamp": "2026-04-04T10:02:00"},
            {"action": "reject", "identity_key": "key_a",
             "context": {"distance_threshold": 8.0, "confidence": 0.2},
             "timestamp": "2026-04-04T10:03:00"},
            # Key B: 1 accept, 1 split -> 0.5
            {"action": "accept", "identity_key": "key_b",
             "context": {"distance_threshold": 8.0}, "timestamp": "2026-04-04T10:04:00"},
            {"action": "split", "identity_key": "key_b",
             "context": {"distance_threshold": 10.0}, "timestamp": "2026-04-04T10:05:00"},
        ]

        result = learn_cluster_thresholds(corrections)

        assert result["key_a"]["accept_rate"] == 0.75
        assert result["key_a"]["sample_count"] == 4
        assert result["key_b"]["accept_rate"] == 0.5
        assert result["key_b"]["sample_count"] == 2


# ===========================================================================
# get_convergence_signal
# ===========================================================================


class TestConvergenceSignal:
    """Tests for convergence tracking across sessions."""

    def test_convergence_not_converged(self, cluster_tmp):
        """Mixed accept/reject ratios -> converged=False."""
        corrections = [
            # Day 1: 2 accept, 1 reject -> 0.67
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-01T10:00:00"},
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-01T10:01:00"},
            {"action": "reject", "identity_key": "k", "context": {},
             "timestamp": "2026-04-01T10:02:00"},
            # Day 2: 3 accept, 1 split -> 0.75
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-02T10:00:00"},
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-02T10:01:00"},
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-02T10:02:00"},
            {"action": "split", "identity_key": "k", "context": {},
             "timestamp": "2026-04-02T10:03:00"},
            # Day 3: all accept -> 1.0
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-03T10:00:00"},
        ]

        result = get_convergence_signal(corrections)

        assert result["converged"] is False
        assert result["total_sessions"] == 3
        assert len(result["recent_ratios"]) == 3

    def test_convergence_converged(self, cluster_tmp):
        """3+ sessions all >0.95 accept rate -> converged=True."""
        corrections = []
        # 4 sessions, each with 20 accepts and 0 rejects
        for day in range(1, 5):
            for i in range(20):
                corrections.append({
                    "action": "accept", "identity_key": "k", "context": {},
                    "timestamp": f"2026-04-{day:02d}T10:{i:02d}:00",
                })

        result = get_convergence_signal(corrections)

        assert result["converged"] is True
        assert result["accept_all_ratio"] == 1.0
        assert result["total_sessions"] == 4
        assert all(r == 1.0 for r in result["recent_ratios"])

    def test_convergence_no_data(self, cluster_tmp):
        """Empty corrections -> sensible defaults."""
        result = get_convergence_signal([])

        assert result["accept_all_ratio"] == 0.0
        assert result["total_sessions"] == 0
        assert result["converged"] is False
        assert result["recent_ratios"] == []

    def test_convergence_from_disk(self, cluster_tmp):
        """Loads from CLUSTER_CORRECTIONS_PATH when no arg passed."""
        # No file exists yet -> should return defaults
        result = get_convergence_signal()
        assert result["total_sessions"] == 0

        # Write some data and verify it loads
        corrections = [
            {"action": "accept", "identity_key": "k", "context": {},
             "timestamp": "2026-04-04T10:00:00"},
        ]
        cluster_tmp.parent.mkdir(parents=True, exist_ok=True)
        cluster_tmp.write_text(json.dumps(corrections))

        result = get_convergence_signal()
        assert result["total_sessions"] == 1


# ===========================================================================
# _compute_cluster_stats (interaction_ingest)
# ===========================================================================


class TestComputeClusterStats:
    """Tests for cluster event parsing in interaction ingest."""

    def test_cluster_events_counted(self):
        """Cluster events are correctly counted and grouped by action."""
        entries = [
            {"action": "cluster_accept", "panel": "edge_cluster"},
            {"action": "cluster_accept", "panel": "edge_cluster"},
            {"action": "cluster_split", "panel": "edge_cluster"},
            {"action": "cluster_reject", "panel": "edge_cluster"},
            {"action": "reclassify", "panel": "shapeaverager"},  # not a cluster event
        ]

        stats = _compute_cluster_stats(entries)

        assert stats["count"] == 4
        assert stats["by_action"]["cluster_accept"] == 2
        assert stats["by_action"]["cluster_split"] == 1
        assert stats["by_action"]["cluster_reject"] == 1

    def test_no_cluster_events(self):
        """No cluster events -> count 0."""
        entries = [
            {"action": "reclassify", "panel": "shapeaverager"},
            {"action": "confirm", "panel": "shapeaverager"},
        ]

        stats = _compute_cluster_stats(entries)

        assert stats["count"] == 0
        assert "by_action" not in stats

    def test_empty_entries(self):
        """Empty list -> count 0."""
        stats = _compute_cluster_stats([])
        assert stats["count"] == 0

    def test_cluster_slider_adjust(self):
        """slider_adjust events are parsed correctly."""
        entries = [
            {"action": "cluster_slider_adjust", "panel": "edge_cluster"},
            {"action": "cluster_accept_all", "panel": "edge_cluster"},
        ]

        stats = _compute_cluster_stats(entries)

        assert stats["count"] == 2
        assert stats["by_action"]["cluster_slider_adjust"] == 1
        assert stats["by_action"]["cluster_accept_all"] == 1
