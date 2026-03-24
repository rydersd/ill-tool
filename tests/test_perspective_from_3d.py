"""Tests for the perspective from 3D tool.

Verifies error computation, classification, and report generation —
all pure Python, no 3D engine required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.perspective_from_3d import (
    compute_perspective_error,
    classify_error,
    generate_correction_report,
)


# ---------------------------------------------------------------------------
# test_compute_perspective_error
# ---------------------------------------------------------------------------


class TestComputePerspectiveError:
    """Per-point Euclidean distance between drawing and rendered points."""

    def test_identical_points(self):
        """Identical point sets produce zero error everywhere."""
        points = [[10, 20], [30, 40], [50, 60]]
        result = compute_perspective_error(points, points)

        assert result["point_count"] == 3
        assert all(e == 0.0 for e in result["errors"])
        assert result["mean_error"] == 0.0
        assert result["max_error"] == 0.0

    def test_known_distance(self):
        """A 3-4-5 triangle displacement gives error of 5.0."""
        drawing = [[0, 0]]
        rendered = [[3, 4]]

        result = compute_perspective_error(drawing, rendered)

        assert result["point_count"] == 1
        assert result["errors"][0] == pytest.approx(5.0, abs=0.01)
        assert result["mean_error"] == pytest.approx(5.0, abs=0.01)

    def test_multiple_points_mean(self):
        """Mean error is the average of individual errors."""
        drawing = [[0, 0], [10, 0]]
        rendered = [[3, 4], [10, 0]]

        result = compute_perspective_error(drawing, rendered)

        # Point 0: distance 5.0, Point 1: distance 0.0
        assert result["errors"][0] == pytest.approx(5.0, abs=0.01)
        assert result["errors"][1] == pytest.approx(0.0, abs=0.01)
        assert result["mean_error"] == pytest.approx(2.5, abs=0.01)
        assert result["max_error"] == pytest.approx(5.0, abs=0.01)

    def test_mismatched_lengths(self):
        """Only overlapping points are compared when lists differ in length."""
        drawing = [[0, 0], [10, 10], [20, 20]]
        rendered = [[1, 1]]

        result = compute_perspective_error(drawing, rendered)

        assert result["point_count"] == 1
        assert len(result["errors"]) == 1

    def test_empty_lists(self):
        """Empty point lists return an error."""
        result = compute_perspective_error([], [[1, 2]])
        assert "error" in result


# ---------------------------------------------------------------------------
# test_classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Classify errors as minor or major based on threshold."""

    def test_below_threshold_minor(self):
        """Errors below threshold are classified as minor."""
        errors = [1.0, 2.0, 4.9]
        result = classify_error(errors, threshold=5.0)

        assert result == ["minor", "minor", "minor"]

    def test_above_threshold_major(self):
        """Errors above threshold are classified as major."""
        errors = [5.1, 10.0, 20.0]
        result = classify_error(errors, threshold=5.0)

        assert result == ["major", "major", "major"]

    def test_exact_threshold_minor(self):
        """Error exactly at threshold is classified as minor."""
        result = classify_error([5.0], threshold=5.0)
        assert result == ["minor"]

    def test_mixed_classifications(self):
        """A mix of errors produces a mix of classifications."""
        errors = [2.0, 8.0, 3.0, 15.0]
        result = classify_error(errors, threshold=5.0)

        assert result == ["minor", "major", "minor", "major"]


# ---------------------------------------------------------------------------
# test_generate_correction_report
# ---------------------------------------------------------------------------


class TestGenerateCorrectionReport:
    """Structured report of perspective corrections needed."""

    def test_all_minor_report(self):
        """All minor errors produce an 'accurate' summary."""
        errors = [1.0, 2.0, 3.0]
        classifications = ["minor", "minor", "minor"]

        report = generate_correction_report(errors, classifications)

        assert report["major_count"] == 0
        assert report["minor_count"] == 3
        assert report["total_points"] == 3
        assert "accurate" in report["summary"].lower()

    def test_with_labels(self):
        """Point labels appear in report details."""
        errors = [2.0, 10.0]
        classifications = ["minor", "major"]
        labels = ["left_eye", "chin"]

        report = generate_correction_report(errors, classifications, point_labels=labels)

        # Find chin entry (should be first since sorted by error magnitude)
        point_names = [p["label"] for p in report["points"]]
        assert "chin" in point_names
        assert "left_eye" in point_names

        # Sorted by error (worst first)
        assert report["points"][0]["error_px"] >= report["points"][1]["error_px"]

    def test_report_sorted_worst_first(self):
        """Points in the report are sorted by error magnitude, worst first."""
        errors = [1.0, 15.0, 5.0, 20.0]
        classifications = ["minor", "major", "minor", "major"]

        report = generate_correction_report(errors, classifications)

        error_values = [p["error_px"] for p in report["points"]]
        for i in range(len(error_values) - 1):
            assert error_values[i] >= error_values[i + 1]

    def test_empty_report(self):
        """Empty errors produce a 'no points' summary."""
        report = generate_correction_report([], [])

        assert report["major_count"] == 0
        assert report["minor_count"] == 0
        assert len(report["points"]) == 0
