"""Tests for projection delta functions in correction_learning.

Tests store_projection_delta(), pre_correct_projection(), weighted averaging,
cross-image generalization, and edge cases.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.correction_learning import (
    store_projection_delta,
    pre_correct_projection,
    _load_projection_corrections,
    _save_projection_corrections,
    VALID_CORRECTION_TYPES,
)


# ---------------------------------------------------------------------------
# store_projection_delta
# ---------------------------------------------------------------------------


class TestStoreProjectionDelta:
    """Tests for storing projection deltas."""

    def test_persists_all_schema_fields(self, tmp_path):
        """All schema fields are persisted to JSON."""
        path = str(tmp_path / "proj.json")
        entry = store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[10, 20], [30, 40]],
            reference_contour=[[15, 25], [35, 45]],
            displacement_vectors=[[5, 5], [5, 5]],
            mesh_source="trellis_v2",
            image_hash="abc123",
            score_before=0.3,
            score_after=0.6,
            path=path,
        )

        assert entry["correction_type"] == "projection_delta"
        assert entry["face_group_label"] == "front_face"
        assert entry["projected_contour"] == [[10, 20], [30, 40]]
        assert entry["reference_contour"] == [[15, 25], [35, 45]]
        assert entry["displacement_vectors"] == [[5, 5], [5, 5]]
        assert entry["mesh_source"] == "trellis_v2"
        assert entry["image_hash"] == "abc123"
        assert entry["score_before"] == 0.3
        assert entry["score_after"] == 0.6

        # Verify persisted to disk
        stored = _load_projection_corrections(path)
        assert len(stored) == 1
        assert stored[0]["face_group_label"] == "front_face"

    def test_creates_parent_directory_if_missing(self, tmp_path):
        """Store creates parent directories when they don't exist."""
        path = str(tmp_path / "deep" / "nested" / "proj.json")
        store_projection_delta(
            face_group_label="top_face",
            projected_contour=[[0, 0]],
            reference_contour=[[1, 1]],
            displacement_vectors=[[1, 1]],
            mesh_source="test",
            image_hash="hash1",
            score_before=0.2,
            score_after=0.5,
            path=path,
        )
        assert os.path.exists(path)

    def test_multiple_stores_accumulate(self, tmp_path):
        """Multiple store calls append entries, not overwrite."""
        path = str(tmp_path / "proj.json")

        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[10, 20]],
            reference_contour=[[15, 25]],
            displacement_vectors=[[5, 5]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.6,
            path=path,
        )
        store_projection_delta(
            face_group_label="side_face",
            projected_contour=[[50, 60]],
            reference_contour=[[55, 65]],
            displacement_vectors=[[5, 5]],
            mesh_source="trellis_v2",
            image_hash="hash2",
            score_before=0.2,
            score_after=0.5,
            path=path,
        )

        stored = _load_projection_corrections(path)
        assert len(stored) == 2
        labels = {s["face_group_label"] for s in stored}
        assert labels == {"front_face", "side_face"}

    def test_projection_delta_in_valid_types(self):
        """projection_delta is in the VALID_CORRECTION_TYPES set."""
        assert "projection_delta" in VALID_CORRECTION_TYPES


# ---------------------------------------------------------------------------
# pre_correct_projection
# ---------------------------------------------------------------------------


class TestPreCorrectProjection:
    """Tests for applying stored projection deltas to new contours."""

    def test_shifts_contours_by_stored_displacement(self, tmp_path):
        """Stored displacement vectors are applied to new contours."""
        path = str(tmp_path / "proj.json")

        # Store a delta: front_face shifted by [5, 10] per point
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[100, 200], [300, 400]],
            reference_contour=[[105, 210], [305, 410]],
            displacement_vectors=[[5, 10], [5, 10]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.6,
            path=path,
        )

        # Apply to new contour with same face group label
        result = pre_correct_projection(
            projected_contours=[[[50, 60], [70, 80]]],
            face_group_labels=["front_face"],
            image_hash="hash1",
            path=path,
        )

        # With same image_hash (weight=1.0), displacement should be exactly [5, 10]
        assert len(result) == 1
        assert abs(result[0][0][0] - 55.0) < 0.01
        assert abs(result[0][0][1] - 70.0) < 0.01
        assert abs(result[0][1][0] - 75.0) < 0.01
        assert abs(result[0][1][1] - 90.0) < 0.01

    def test_multiple_deltas_average_correctly(self, tmp_path):
        """Multiple stored deltas for the same label are averaged."""
        path = str(tmp_path / "proj.json")

        # Store two deltas for front_face
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[10, 0]],
            displacement_vectors=[[10, 0]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.5,
            path=path,
        )
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[20, 0]],
            displacement_vectors=[[20, 0]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.7,
            path=path,
        )

        # Both have same hash, weight=1.0 each
        # Mean displacement: (10+20)/2 = 15
        result = pre_correct_projection(
            projected_contours=[[[100, 100]]],
            face_group_labels=["front_face"],
            image_hash="hash1",
            path=path,
        )

        assert abs(result[0][0][0] - 115.0) < 0.01
        assert abs(result[0][0][1] - 100.0) < 0.01

    def test_cross_image_weight(self, tmp_path):
        """Same hash gets weight 1.0, different hash gets weight 0.3."""
        path = str(tmp_path / "proj.json")

        # Store delta with hash "A"
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[10, 0]],
            displacement_vectors=[[10, 0]],
            mesh_source="trellis_v2",
            image_hash="A",
            score_before=0.3,
            score_after=0.5,
            path=path,
        )

        # Query with different hash "B" -- weight should be 0.3
        # Weighted mean: (0.3 * 10) / 0.3 = 10 (only one entry, so mean is same)
        result = pre_correct_projection(
            projected_contours=[[[100, 100]]],
            face_group_labels=["front_face"],
            image_hash="B",
            path=path,
        )

        # Single entry: displacement is 10 regardless of weight (mean of one = itself)
        assert abs(result[0][0][0] - 110.0) < 0.01

    def test_cross_image_weight_two_entries(self, tmp_path):
        """Weighted mean correctly blends same-hash and different-hash entries."""
        path = str(tmp_path / "proj.json")

        # Entry 1: hash "A", displacement [10, 0]
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[10, 0]],
            displacement_vectors=[[10, 0]],
            mesh_source="trellis_v2",
            image_hash="A",
            score_before=0.3,
            score_after=0.5,
            path=path,
        )
        # Entry 2: hash "B", displacement [30, 0]
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[30, 0]],
            displacement_vectors=[[30, 0]],
            mesh_source="trellis_v2",
            image_hash="B",
            score_before=0.2,
            score_after=0.6,
            path=path,
        )

        # Query with hash "A": entry 1 gets weight 1.0, entry 2 gets weight 0.3
        # Weighted mean: (1.0*10 + 0.3*30) / (1.0 + 0.3) = (10 + 9) / 1.3 = 19/1.3 ~= 14.615
        result = pre_correct_projection(
            projected_contours=[[[100, 100]]],
            face_group_labels=["front_face"],
            image_hash="A",
            path=path,
        )

        expected_dx = (1.0 * 10 + 0.3 * 30) / (1.0 + 0.3)
        assert abs(result[0][0][0] - (100 + expected_dx)) < 0.01

    def test_empty_delta_store_returns_unchanged(self, tmp_path):
        """With no stored deltas, contours are returned unchanged."""
        path = str(tmp_path / "proj.json")
        contours = [[[10, 20], [30, 40]]]
        result = pre_correct_projection(
            projected_contours=contours,
            face_group_labels=["front_face"],
            path=path,
        )
        assert result == contours

    def test_invalid_face_group_label_returns_unchanged(self, tmp_path):
        """Unknown face group label returns contour unchanged."""
        path = str(tmp_path / "proj.json")

        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[10, 10]],
            displacement_vectors=[[10, 10]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.6,
            path=path,
        )

        # Query with a label that has no stored deltas
        contours = [[[50, 50]]]
        result = pre_correct_projection(
            projected_contours=contours,
            face_group_labels=["nonexistent_face"],
            path=path,
        )
        assert result == contours

    def test_round_trip_store_load_precorrect(self, tmp_path):
        """Round-trip: store -> load -> pre-correct produces expected shift."""
        path = str(tmp_path / "proj.json")

        displacement = [[3.5, -2.0], [7.0, 1.5]]
        store_projection_delta(
            face_group_label="top_face",
            projected_contour=[[0, 0], [10, 10]],
            reference_contour=[[3.5, -2.0], [17.0, 11.5]],
            displacement_vectors=displacement,
            mesh_source="trellis_v2",
            image_hash="round_trip",
            score_before=0.2,
            score_after=0.8,
            path=path,
        )

        # Load and verify file exists
        loaded = _load_projection_corrections(path)
        assert len(loaded) == 1

        # Pre-correct with same hash
        result = pre_correct_projection(
            projected_contours=[[[100, 200], [300, 400]]],
            face_group_labels=["top_face"],
            image_hash="round_trip",
            path=path,
        )

        assert abs(result[0][0][0] - 103.5) < 0.01
        assert abs(result[0][0][1] - 198.0) < 0.01
        assert abs(result[0][1][0] - 307.0) < 0.01
        assert abs(result[0][1][1] - 401.5) < 0.01

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        """Loading from a nonexistent file returns empty list."""
        path = str(tmp_path / "does_not_exist.json")
        result = _load_projection_corrections(path)
        assert result == []

    def test_projection_deltas_independent_from_dwpose(self, tmp_path, monkeypatch):
        """Projection deltas use separate storage from DWPose corrections."""
        proj_path = str(tmp_path / "proj.json")
        dwpose_dir = str(tmp_path / "dwpose")
        monkeypatch.setattr(
            "adobe_mcp.apps.illustrator.correction_learning._DWPOSE_CORRECTIONS_DIR",
            dwpose_dir,
        )

        # Store a projection delta
        store_projection_delta(
            face_group_label="front_face",
            projected_contour=[[0, 0]],
            reference_contour=[[5, 5]],
            displacement_vectors=[[5, 5]],
            mesh_source="trellis_v2",
            image_hash="hash1",
            score_before=0.3,
            score_after=0.6,
            path=proj_path,
        )

        # Store a DWPose correction
        from adobe_mcp.apps.illustrator.correction_learning import store_correction
        store_correction(
            character_name="test_char",
            joint_name="shoulder",
            dwpose_pos=(100, 200),
            corrected_pos=(110, 195),
            figure_type="mech",
        )

        # Verify they are independent files
        proj_data = _load_projection_corrections(proj_path)
        assert len(proj_data) == 1
        assert proj_data[0]["correction_type"] == "projection_delta"

        from adobe_mcp.apps.illustrator.correction_learning import _load_dwpose_corrections
        dwpose_data = _load_dwpose_corrections("test_char")
        assert len(dwpose_data) == 1
        assert "joint_name" in dwpose_data[0]
        # No cross-contamination
        assert "face_group_label" not in dwpose_data[0]
