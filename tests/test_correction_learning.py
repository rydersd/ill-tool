"""Tests for the correction learning system.

Tests recording corrections, matching similar features to suggestions,
no-match scenarios, and DWPose joint correction learning.
"""

import json
import math
import os

import pytest

from adobe_mcp.apps.illustrator.analysis.correction_learning import (
    record_correction,
    suggest_from_corrections,
    _load_corrections,
)
from adobe_mcp.apps.illustrator.analysis import correction_learning


# ---------------------------------------------------------------------------
# record_correction
# ---------------------------------------------------------------------------


def test_record_correction(tmp_path):
    """Recording a correction persists it to the storage file."""
    storage = str(tmp_path / "corrections.json")

    result = record_correction(
        correction_type="part_label",
        original="limb",
        corrected="arm",
        context={"area_ratio": 0.15, "aspect_ratio": 3.0, "position_relative_to_root": 0.6},
        storage_path=storage,
    )

    assert result["correction_type"] == "part_label"
    assert result["original"] == "limb"
    assert result["corrected"] == "arm"

    # Verify it was persisted
    corrections = _load_corrections(storage)
    assert len(corrections) == 1
    assert corrections[0]["corrected"] == "arm"


# ---------------------------------------------------------------------------
# suggest_from_corrections — similar features match
# ---------------------------------------------------------------------------


def test_similar_features_suggest_correction(tmp_path):
    """A new part with similar features gets the corrected label."""
    storage = str(tmp_path / "corrections.json")

    # Record a correction for an arm
    record_correction(
        correction_type="part_label",
        original="limb",
        corrected="arm",
        context={"area_ratio": 0.15, "aspect_ratio": 3.0, "position_relative_to_root": 0.6},
        storage_path=storage,
    )

    # Query with very similar features
    result = suggest_from_corrections(
        part_features={"area_ratio": 0.16, "aspect_ratio": 2.9, "position_relative_to_root": 0.62},
        storage_path=storage,
    )

    assert result is not None
    assert result["suggested_label"] == "arm"
    assert result["distance"] < 0.3  # Within threshold


# ---------------------------------------------------------------------------
# suggest_from_corrections — no match
# ---------------------------------------------------------------------------


def test_no_match_returns_none(tmp_path):
    """When features are too different, no suggestion is returned."""
    storage = str(tmp_path / "corrections.json")

    # Record a correction for an arm
    record_correction(
        correction_type="part_label",
        original="limb",
        corrected="arm",
        context={"area_ratio": 0.15, "aspect_ratio": 3.0, "position_relative_to_root": 0.6},
        storage_path=storage,
    )

    # Query with very different features (like a head)
    result = suggest_from_corrections(
        part_features={"area_ratio": 0.8, "aspect_ratio": 1.0, "position_relative_to_root": 0.1},
        storage_path=storage,
    )

    assert result is None


# ===========================================================================
# DWPose joint correction learning
# ===========================================================================


@pytest.fixture()
def dwpose_tmp_dir(tmp_path, monkeypatch):
    """Redirect DWPose corrections storage to a temp directory."""
    corrections_dir = str(tmp_path / "ai_rigs")
    monkeypatch.setattr(
        correction_learning, "_DWPOSE_CORRECTIONS_DIR", corrections_dir
    )
    return corrections_dir


# ---------------------------------------------------------------------------
# store_correction (DWPose)
# ---------------------------------------------------------------------------


class TestStoreCorrection:
    """Tests for store_correction — persisting DWPose joint deltas."""

    def test_stores_single_correction(self, dwpose_tmp_dir):
        """A single correction is saved to the character's file."""
        correction_learning.store_correction(
            character_name="gir",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(105.0, 195.0),
            figure_type="mech",
        )

        path = os.path.join(dwpose_tmp_dir, "gir_corrections.json")
        assert os.path.exists(path)

        with open(path) as f:
            data = json.load(f)

        assert len(data) == 1
        assert data[0]["joint_name"] == "left_shoulder"
        assert data[0]["dwpose_pos"] == [100.0, 200.0]
        assert data[0]["corrected_pos"] == [105.0, 195.0]
        assert data[0]["delta"] == [5.0, -5.0]
        assert data[0]["figure_type"] == "mech"

    def test_stores_multiple_corrections_for_same_character(self, dwpose_tmp_dir):
        """Multiple corrections accumulate in the same character file."""
        correction_learning.store_correction(
            character_name="zaku",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(110.0, 200.0),
        )
        correction_learning.store_correction(
            character_name="zaku",
            joint_name="right_knee",
            dwpose_pos=(150.0, 400.0),
            corrected_pos=(150.0, 410.0),
        )

        data = correction_learning._load_dwpose_corrections("zaku")
        assert len(data) == 2
        assert data[0]["joint_name"] == "left_shoulder"
        assert data[1]["joint_name"] == "right_knee"

    def test_separate_characters_get_separate_files(self, dwpose_tmp_dir):
        """Each character has its own corrections file."""
        correction_learning.store_correction(
            character_name="gir",
            joint_name="head",
            dwpose_pos=(50.0, 50.0),
            corrected_pos=(52.0, 48.0),
        )
        correction_learning.store_correction(
            character_name="zim",
            joint_name="head",
            dwpose_pos=(60.0, 60.0),
            corrected_pos=(58.0, 62.0),
        )

        gir_data = correction_learning._load_dwpose_corrections("gir")
        zim_data = correction_learning._load_dwpose_corrections("zim")
        assert len(gir_data) == 1
        assert len(zim_data) == 1
        assert gir_data[0]["delta"] == [2.0, -2.0]
        assert zim_data[0]["delta"] == [-2.0, 2.0]

    def test_delta_computed_correctly(self, dwpose_tmp_dir):
        """Delta is corrected_pos - dwpose_pos."""
        correction_learning.store_correction(
            character_name="test_char",
            joint_name="left_elbow",
            dwpose_pos=(200.0, 300.0),
            corrected_pos=(180.0, 310.0),
        )

        data = correction_learning._load_dwpose_corrections("test_char")
        assert data[0]["delta"] == [-20.0, 10.0]

    def test_default_figure_type_is_mech(self, dwpose_tmp_dir):
        """Default figure_type is 'mech'."""
        correction_learning.store_correction(
            character_name="default_test",
            joint_name="hip",
            dwpose_pos=(100.0, 100.0),
            corrected_pos=(100.0, 100.0),
        )

        data = correction_learning._load_dwpose_corrections("default_test")
        assert data[0]["figure_type"] == "mech"


# ---------------------------------------------------------------------------
# compute_correction_model
# ---------------------------------------------------------------------------


class TestComputeCorrectionModel:
    """Tests for compute_correction_model — averaging deltas across characters."""

    def test_returns_empty_below_min_samples(self, dwpose_tmp_dir):
        """Returns empty dict when fewer than min_samples corrections exist."""
        correction_learning.store_correction(
            character_name="solo",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(105.0, 200.0),
        )

        model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=2
        )
        assert model == {}

    def test_returns_empty_when_no_directory(self, dwpose_tmp_dir):
        """Returns empty dict when the corrections directory does not exist."""
        model = correction_learning.compute_correction_model(figure_type="mech")
        assert model == {}

    def test_computes_average_delta_across_characters(self, dwpose_tmp_dir):
        """Average delta across multiple characters for the same joint."""
        # Character 1: left_shoulder shifted right by 10
        correction_learning.store_correction(
            character_name="char_a",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(110.0, 200.0),
            figure_type="mech",
        )
        # Character 2: left_shoulder shifted right by 6
        correction_learning.store_correction(
            character_name="char_b",
            joint_name="left_shoulder",
            dwpose_pos=(150.0, 250.0),
            corrected_pos=(156.0, 250.0),
            figure_type="mech",
        )

        model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=2
        )

        assert "left_shoulder" in model
        avg_dx, avg_dy = model["left_shoulder"]
        assert avg_dx == pytest.approx(8.0, abs=0.01)  # (10 + 6) / 2
        assert avg_dy == pytest.approx(0.0, abs=0.01)

    def test_filters_by_figure_type(self, dwpose_tmp_dir):
        """Only corrections matching the figure_type are included."""
        correction_learning.store_correction(
            character_name="mech_char",
            joint_name="hip",
            dwpose_pos=(100.0, 100.0),
            corrected_pos=(100.0, 110.0),
            figure_type="mech",
        )
        correction_learning.store_correction(
            character_name="human_char",
            joint_name="hip",
            dwpose_pos=(100.0, 100.0),
            corrected_pos=(100.0, 90.0),
            figure_type="human",
        )
        # Add a second mech correction to meet min_samples
        correction_learning.store_correction(
            character_name="mech_char2",
            joint_name="hip",
            dwpose_pos=(100.0, 100.0),
            corrected_pos=(100.0, 120.0),
            figure_type="mech",
        )

        mech_model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=2
        )
        assert "hip" in mech_model
        # mech corrections: dy=10 and dy=20 -> avg=15
        assert mech_model["hip"][1] == pytest.approx(15.0, abs=0.01)

        # Human only has 1 sample, so with default min_samples=2 it returns empty
        human_model = correction_learning.compute_correction_model(
            figure_type="human", min_samples=2
        )
        assert human_model == {}

    def test_multiple_joints_in_model(self, dwpose_tmp_dir):
        """Model contains entries for all joints with corrections."""
        correction_learning.store_correction(
            character_name="char_a",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(110.0, 200.0),
        )
        correction_learning.store_correction(
            character_name="char_a",
            joint_name="right_knee",
            dwpose_pos=(200.0, 400.0),
            corrected_pos=(200.0, 410.0),
        )
        correction_learning.store_correction(
            character_name="char_b",
            joint_name="left_shoulder",
            dwpose_pos=(120.0, 220.0),
            corrected_pos=(126.0, 220.0),
        )
        correction_learning.store_correction(
            character_name="char_b",
            joint_name="right_knee",
            dwpose_pos=(180.0, 380.0),
            corrected_pos=(180.0, 396.0),
        )

        model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=2
        )

        assert "left_shoulder" in model
        assert "right_knee" in model
        # left_shoulder: (10, 0) and (6, 0) -> avg (8, 0)
        assert model["left_shoulder"][0] == pytest.approx(8.0, abs=0.01)
        # right_knee: (0, 10) and (0, 16) -> avg (0, 13)
        assert model["right_knee"][1] == pytest.approx(13.0, abs=0.01)

    def test_min_samples_threshold(self, dwpose_tmp_dir):
        """Model requires at least min_samples total corrections."""
        correction_learning.store_correction(
            character_name="only_one",
            joint_name="head",
            dwpose_pos=(50.0, 50.0),
            corrected_pos=(55.0, 50.0),
        )

        # min_samples=3 requires 3 corrections total
        model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=3
        )
        assert model == {}

        # Add two more
        correction_learning.store_correction(
            character_name="second",
            joint_name="head",
            dwpose_pos=(50.0, 50.0),
            corrected_pos=(57.0, 50.0),
        )
        correction_learning.store_correction(
            character_name="third",
            joint_name="head",
            dwpose_pos=(50.0, 50.0),
            corrected_pos=(59.0, 50.0),
        )

        model = correction_learning.compute_correction_model(
            figure_type="mech", min_samples=3
        )
        assert "head" in model
        # (5 + 7 + 9) / 3 = 7.0
        assert model["head"][0] == pytest.approx(7.0, abs=0.01)


# ---------------------------------------------------------------------------
# pre_correct_dwpose
# ---------------------------------------------------------------------------


class TestPreCorrectDwpose:
    """Tests for pre_correct_dwpose — applying learned corrections."""

    def test_returns_unchanged_when_no_model(self, dwpose_tmp_dir):
        """With no stored corrections, joints are returned as-is."""
        joints = {
            "left_shoulder": (100.0, 200.0),
            "right_knee": (150.0, 400.0),
        }

        result = correction_learning.pre_correct_dwpose(joints, figure_type="mech")

        assert result["left_shoulder"] == (100.0, 200.0)
        assert result["right_knee"] == (150.0, 400.0)

    def test_applies_learned_corrections(self, dwpose_tmp_dir):
        """Joints are adjusted by the learned average delta."""
        # Build a model: two characters with left_shoulder corrections
        correction_learning.store_correction(
            character_name="train_a",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(110.0, 195.0),
            figure_type="mech",
        )
        correction_learning.store_correction(
            character_name="train_b",
            joint_name="left_shoulder",
            dwpose_pos=(120.0, 220.0),
            corrected_pos=(130.0, 215.0),
            figure_type="mech",
        )

        # Apply to new DWPose output
        raw_joints = {"left_shoulder": (90.0, 180.0)}
        result = correction_learning.pre_correct_dwpose(
            raw_joints, figure_type="mech"
        )

        # Expected: avg delta = (10, -5) applied to (90, 180) = (100, 175)
        assert result["left_shoulder"][0] == pytest.approx(100.0, abs=0.01)
        assert result["left_shoulder"][1] == pytest.approx(175.0, abs=0.01)

    def test_uncorrected_joints_pass_through(self, dwpose_tmp_dir):
        """Joints without learned corrections are returned unchanged."""
        correction_learning.store_correction(
            character_name="train_a",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(110.0, 200.0),
        )
        correction_learning.store_correction(
            character_name="train_b",
            joint_name="left_shoulder",
            dwpose_pos=(100.0, 200.0),
            corrected_pos=(106.0, 200.0),
        )

        raw_joints = {
            "left_shoulder": (90.0, 180.0),
            "right_ankle": (300.0, 500.0),  # no correction data for this
        }

        result = correction_learning.pre_correct_dwpose(
            raw_joints, figure_type="mech"
        )

        # left_shoulder is corrected
        assert result["left_shoulder"][0] != 90.0
        # right_ankle passes through unchanged
        assert result["right_ankle"] == (300.0, 500.0)

    def test_does_not_modify_original_dict(self, dwpose_tmp_dir):
        """The original dict is not mutated."""
        joints = {"head": (50.0, 50.0)}
        original_copy = dict(joints)

        correction_learning.pre_correct_dwpose(joints, figure_type="mech")

        assert joints == original_copy


# ---------------------------------------------------------------------------
# compare_corrections
# ---------------------------------------------------------------------------


class TestCompareCorrections:
    """Tests for compare_corrections — analyzing DWPose vs corrected positions."""

    def test_basic_comparison(self):
        """Per-joint deltas and distances are computed correctly."""
        original = {
            "left_shoulder": (100.0, 200.0),
            "right_knee": (150.0, 400.0),
        }
        corrected = {
            "left_shoulder": (110.0, 200.0),
            "right_knee": (150.0, 415.0),
        }

        result = correction_learning.compare_corrections(original, corrected)

        pj = result["per_joint"]
        assert pj["left_shoulder"]["delta_x"] == pytest.approx(10.0)
        assert pj["left_shoulder"]["delta_y"] == pytest.approx(0.0)
        assert pj["left_shoulder"]["distance"] == pytest.approx(10.0)

        assert pj["right_knee"]["delta_x"] == pytest.approx(0.0)
        assert pj["right_knee"]["delta_y"] == pytest.approx(15.0)
        assert pj["right_knee"]["distance"] == pytest.approx(15.0)

    def test_summary_statistics(self):
        """Summary contains mean and max deviation with correct values."""
        original = {
            "a": (0.0, 0.0),
            "b": (0.0, 0.0),
        }
        corrected = {
            "a": (3.0, 4.0),   # distance = 5.0
            "b": (5.0, 12.0),  # distance = 13.0
        }

        result = correction_learning.compare_corrections(original, corrected)
        summary = result["summary"]

        assert summary["mean_deviation"] == pytest.approx(9.0, abs=0.01)
        assert summary["max_deviation"] == pytest.approx(13.0, abs=0.01)
        assert summary["max_deviation_joint"] == "b"
        assert summary["total_joints"] == 2
        assert summary["corrected_joints"] == 2

    def test_no_correction_needed(self):
        """When positions match, deviations are zero."""
        joints = {
            "head": (50.0, 50.0),
            "hip": (100.0, 300.0),
        }

        result = correction_learning.compare_corrections(joints, joints)
        summary = result["summary"]

        assert summary["mean_deviation"] == pytest.approx(0.0)
        assert summary["max_deviation"] == pytest.approx(0.0)
        assert summary["corrected_joints"] == 0

    def test_handles_partial_overlap(self):
        """Only joints present in both dicts are compared."""
        original = {
            "left_shoulder": (100.0, 200.0),
            "right_shoulder": (200.0, 200.0),
        }
        corrected = {
            "left_shoulder": (105.0, 200.0),
            "head": (50.0, 50.0),  # not in original
        }

        result = correction_learning.compare_corrections(original, corrected)

        assert "left_shoulder" in result["per_joint"]
        assert "right_shoulder" not in result["per_joint"]
        assert "head" not in result["per_joint"]
        assert result["summary"]["total_joints"] == 1

    def test_direction_degrees(self):
        """Direction is in degrees with 0 = right, 90 = down."""
        original = {"test": (0.0, 0.0)}

        # Move right: direction = 0
        result = correction_learning.compare_corrections(
            original, {"test": (10.0, 0.0)}
        )
        assert result["per_joint"]["test"]["direction_deg"] == pytest.approx(0.0)

        # Move down (positive y in screen coords): direction = 90
        result = correction_learning.compare_corrections(
            original, {"test": (0.0, 10.0)}
        )
        assert result["per_joint"]["test"]["direction_deg"] == pytest.approx(90.0)

        # Move left: direction = 180 or -180
        result = correction_learning.compare_corrections(
            original, {"test": (-10.0, 0.0)}
        )
        assert abs(result["per_joint"]["test"]["direction_deg"]) == pytest.approx(180.0)

    def test_empty_inputs(self):
        """Empty dicts produce empty results."""
        result = correction_learning.compare_corrections({}, {})

        assert result["per_joint"] == {}
        assert result["summary"]["total_joints"] == 0
        assert result["summary"]["mean_deviation"] == 0.0
