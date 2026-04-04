"""Tests for the DWPose delta extractor module.

Tests delta computation, joint matching, storage round-trips,
edge cases (missing/empty layers), and status reporting.
"""

import json
import math
import os

import pytest

from adobe_mcp.apps.illustrator.dwpose_delta_extractor import (
    match_joints_by_proximity,
    compute_deltas,
    store_deltas_via_correction_learning,
)
from adobe_mcp.apps.illustrator.correction_learning import (
    compute_correction_model,
    _load_dwpose_corrections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _joint(x, y, index=0, name=None):
    """Create a joint dict matching JSX output format."""
    return {
        "x": x,
        "y": y,
        "index": index,
        "name": name or f"joint_{index}",
    }


# ---------------------------------------------------------------------------
# match_joints_by_proximity
# ---------------------------------------------------------------------------


class TestMatchJointsByProximity:
    """Tests for nearest-neighbor joint matching."""

    def test_exact_match(self):
        """Joints at identical positions match perfectly."""
        ml = [_joint(100, 200, 0), _joint(300, 400, 1)]
        corr = [_joint(100, 200, 0), _joint(300, 400, 1)]
        matches = match_joints_by_proximity(ml, corr)
        assert len(matches) == 2

    def test_nearby_match(self):
        """Joints within threshold distance are matched."""
        ml = [_joint(100, 200, 0)]
        corr = [_joint(110, 195, 0)]
        matches = match_joints_by_proximity(ml, corr, threshold=50.0)
        assert len(matches) == 1
        assert matches[0][0]["x"] == 100
        assert matches[0][1]["x"] == 110

    def test_beyond_threshold_no_match(self):
        """Joints beyond threshold distance are not matched."""
        ml = [_joint(100, 200, 0)]
        corr = [_joint(500, 500, 0)]
        matches = match_joints_by_proximity(ml, corr, threshold=50.0)
        assert len(matches) == 0

    def test_empty_ml_joints(self):
        """Empty ML joints list returns empty matches."""
        matches = match_joints_by_proximity([], [_joint(100, 200, 0)])
        assert matches == []

    def test_empty_corrected_joints(self):
        """Empty corrected joints list returns empty matches."""
        matches = match_joints_by_proximity([_joint(100, 200, 0)], [])
        assert matches == []

    def test_partial_match(self):
        """When some ML joints have no nearby corrected joint, only matching pairs returned."""
        ml = [_joint(100, 200, 0), _joint(900, 900, 1)]
        corr = [_joint(105, 205, 0)]
        matches = match_joints_by_proximity(ml, corr, threshold=50.0)
        assert len(matches) == 1
        assert matches[0][0]["index"] == 0


# ---------------------------------------------------------------------------
# compute_deltas
# ---------------------------------------------------------------------------


class TestComputeDeltas:
    """Tests for per-joint delta computation."""

    def test_known_delta(self):
        """ML [100,200] + corrected [110,195] produces delta [10,-5]."""
        ml = _joint(100, 200, 0, "shoulder")
        corr = _joint(110, 195, 0, "shoulder")
        deltas = compute_deltas([(ml, corr)])
        assert len(deltas) == 1
        assert deltas[0]["delta_x"] == 10
        assert deltas[0]["delta_y"] == -5
        expected_mag = math.sqrt(10**2 + 5**2)
        assert abs(deltas[0]["magnitude"] - expected_mag) < 0.01

    def test_zero_delta(self):
        """Identical positions produce zero delta."""
        ml = _joint(100, 200, 0)
        corr = _joint(100, 200, 0)
        deltas = compute_deltas([(ml, corr)])
        assert deltas[0]["delta_x"] == 0
        assert deltas[0]["delta_y"] == 0
        assert deltas[0]["magnitude"] == 0.0

    def test_joint_name_preserved(self):
        """Joint name from ML joint is preserved in delta output."""
        ml = _joint(100, 200, 0, "left_knee")
        corr = _joint(105, 210, 0, "corrected_knee")
        deltas = compute_deltas([(ml, corr)])
        assert deltas[0]["joint_name"] == "left_knee"


# ---------------------------------------------------------------------------
# Storage round-trip via correction_learning
# ---------------------------------------------------------------------------


class TestStorageRoundTrip:
    """Tests that deltas persist through correction_learning."""

    def test_store_and_retrieve(self, tmp_path, monkeypatch):
        """Stored deltas appear in correction_learning's model."""
        # Point correction_learning at temp directory
        corrections_dir = str(tmp_path)
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            corrections_dir,
        )

        ml = _joint(100, 200, 0, "shoulder")
        corr = _joint(110, 195, 0, "shoulder")
        deltas = compute_deltas([(ml, corr)])

        stored = store_deltas_via_correction_learning(
            deltas, "test_mech", "mech"
        )
        assert stored == 1

        # Verify via correction_learning's API
        model = compute_correction_model("mech", min_samples=1)
        assert "shoulder" in model
        assert abs(model["shoulder"][0] - 10.0) < 0.01
        assert abs(model["shoulder"][1] - (-5.0)) < 0.01

    def test_multiple_extractions_accumulate(self, tmp_path, monkeypatch):
        """Multiple extractions for the same character accumulate, not overwrite."""
        corrections_dir = str(tmp_path)
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            corrections_dir,
        )

        # First extraction
        deltas1 = compute_deltas([
            (_joint(100, 200, 0, "shoulder"), _joint(110, 200, 0, "shoulder")),
        ])
        store_deltas_via_correction_learning(deltas1, "mech_a", "mech")

        # Second extraction for same character
        deltas2 = compute_deltas([
            (_joint(100, 200, 0, "shoulder"), _joint(120, 200, 0, "shoulder")),
        ])
        store_deltas_via_correction_learning(deltas2, "mech_a", "mech")

        # Both corrections should be stored
        corrections = _load_dwpose_corrections("mech_a")
        assert len(corrections) == 2

        # Model should average: (10 + 20) / 2 = 15
        model = compute_correction_model("mech", min_samples=1)
        assert abs(model["shoulder"][0] - 15.0) < 0.01

    def test_character_type_stored_correctly(self, tmp_path, monkeypatch):
        """Character type is preserved in stored corrections."""
        corrections_dir = str(tmp_path)
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            corrections_dir,
        )

        deltas = compute_deltas([
            (_joint(100, 200, 0, "joint_0"), _joint(110, 210, 0, "joint_0")),
        ])
        store_deltas_via_correction_learning(deltas, "creature_a", "creature")

        corrections = _load_dwpose_corrections("creature_a")
        assert corrections[0]["figure_type"] == "creature"

        # Querying for "mech" type should return empty
        model_mech = compute_correction_model("mech", min_samples=1)
        assert len(model_mech) == 0

        # Querying for "creature" type should return the correction
        model_creature = compute_correction_model("creature", min_samples=1)
        assert "joint_0" in model_creature

    def test_status_no_corrections(self, tmp_path, monkeypatch):
        """Status reports correctly when no corrections exist."""
        corrections_dir = str(tmp_path)
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            corrections_dir,
        )

        model = compute_correction_model("mech", min_samples=1)
        assert len(model) == 0

    def test_handles_empty_deltas(self, tmp_path, monkeypatch):
        """Storing empty deltas list stores nothing."""
        corrections_dir = str(tmp_path)
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            corrections_dir,
        )

        stored = store_deltas_via_correction_learning([], "test_mech", "mech")
        assert stored == 0
