"""Tests for the landmark-and-axis drawing system.

Tests pure Python geometry functions directly — no Adobe app required.
Covers: axis computation, axis-relative transforms, perspective foreshortening,
occlusion inference, coordinate transform persistence, rig schema, and
integration with synthetic images.
"""

import json
import math
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.analysis.landmark_axis import (
    axis_to_ai,
    ai_to_axis,
    batch_axis_to_ai,
    compute_axis_from_landmarks,
    compute_axis_from_pca,
    compute_transform,
    detect_landmarks_from_image,
    infer_occluded_landmarks,
    perspective_cross_width,
    pixel_to_ai,
    ai_to_pixel,
    reflect_landmark_across_midline,
    SYMMETRY_PAIRS,
    MIDLINE_LANDMARKS,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Axis computation (8 tests)
# ---------------------------------------------------------------------------


class TestAxisComputation:
    def test_axis_horizontal(self):
        """Same Y -> angle = 0 degrees."""
        axis = compute_axis_from_landmarks([0, 0], [100, 0])
        assert axis["angle_deg"] == pytest.approx(0.0)
        assert axis["length"] == pytest.approx(100.0)

    def test_axis_vertical(self):
        """Same X, Y increases -> angle = 90 degrees (AI Y-up)."""
        axis = compute_axis_from_landmarks([0, 0], [0, 100])
        assert axis["angle_deg"] == pytest.approx(90.0)

    def test_axis_45_degrees(self):
        """Diagonal at 45 degrees."""
        axis = compute_axis_from_landmarks([0, 0], [100, 100])
        assert axis["angle_deg"] == pytest.approx(45.0)

    def test_axis_length(self):
        """Verify length = sqrt(dx^2 + dy^2)."""
        axis = compute_axis_from_landmarks([10, 20], [40, 60])
        expected = math.sqrt(30**2 + 40**2)
        assert axis["length"] == pytest.approx(expected, abs=0.01)

    def test_axis_direction_unit(self):
        """Direction vector has magnitude 1."""
        axis = compute_axis_from_landmarks([0, 0], [3, 4])
        dx, dy = axis["direction"]
        mag = math.sqrt(dx**2 + dy**2)
        assert mag == pytest.approx(1.0, abs=0.001)

    def test_axis_normal_perpendicular(self):
        """Normal is perpendicular to direction (dot product = 0)."""
        axis = compute_axis_from_landmarks([10, 20], [50, 80])
        dx, dy = axis["direction"]
        nx, ny = axis["normal"]
        dot = dx * nx + dy * ny
        assert dot == pytest.approx(0.0, abs=0.001)

    def test_axis_pca_horizontal(self):
        """Points along X axis -> PCA angle approximately 0 or 180."""
        points = [[0, 0], [10, 0], [20, 0], [30, 0], [40, 0]]
        axis = compute_axis_from_pca(points)
        # PCA orients toward Y-negative; for horizontal points, angle should be ~0 or ~180
        assert abs(axis["angle_deg"]) < 5 or abs(abs(axis["angle_deg"]) - 180) < 5

    def test_axis_pca_diagonal(self):
        """Points along 45-degree line -> PCA angle approximately -45 (Y-negative preference)."""
        # Points going from top-left to bottom-right in AI coords (x+, y-)
        points = [[0, 0], [10, -10], [20, -20], [30, -30], [40, -40]]
        axis = compute_axis_from_pca(points)
        # With Y-negative preference, angle should be near -45
        assert axis["angle_deg"] == pytest.approx(-45.0, abs=5.0)


# ---------------------------------------------------------------------------
# Axis-relative transforms (10 tests)
# ---------------------------------------------------------------------------


class TestAxisTransforms:
    def test_along_zero(self):
        """(0, 0) maps to the axis origin."""
        origin = [100, 200]
        result = axis_to_ai(origin, 0, 0.0, 0.0, 100, 50)
        assert result[0] == pytest.approx(100.0)
        assert result[1] == pytest.approx(200.0)

    def test_along_100(self):
        """(1.0, 0) maps to the axis endpoint for a horizontal axis."""
        origin = [0, 0]
        result = axis_to_ai(origin, 0, 1.0, 0.0, 100, 50)
        assert result[0] == pytest.approx(100.0)
        assert result[1] == pytest.approx(0.0)

    def test_along_50(self):
        """(0.5, 0) maps to the midpoint."""
        origin = [0, 0]
        result = axis_to_ai(origin, 0, 0.5, 0.0, 200, 50)
        assert result[0] == pytest.approx(100.0)
        assert result[1] == pytest.approx(0.0)

    def test_across_positive(self):
        """Positive across shifts perpendicular CCW (left of axis direction)."""
        origin = [0, 0]
        # Horizontal axis (angle=0), positive across = Y+ direction
        result = axis_to_ai(origin, 0, 0.0, 1.0, 100, 50)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(50.0)  # 1.0 * 50 cross_width

    def test_across_negative(self):
        """Negative across shifts perpendicular CW (right of axis direction)."""
        origin = [0, 0]
        result = axis_to_ai(origin, 0, 0.0, -1.0, 100, 50)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(-50.0)

    def test_rotated_axis(self):
        """45-degree axis: (1.0, 0) should be at origin + [cos45*L, sin45*L]."""
        origin = [0, 0]
        angle = math.radians(45)
        L = 100
        result = axis_to_ai(origin, angle, 1.0, 0.0, L, 50)
        expected_x = L * math.cos(angle)
        expected_y = L * math.sin(angle)
        assert result[0] == pytest.approx(expected_x, abs=0.1)
        assert result[1] == pytest.approx(expected_y, abs=0.1)

    def test_beyond_100(self):
        """(1.5, 0) extends past the endpoint."""
        origin = [0, 0]
        result = axis_to_ai(origin, 0, 1.5, 0.0, 100, 50)
        assert result[0] == pytest.approx(150.0)

    def test_negative_along(self):
        """(-0.25, 0) is before the origin."""
        origin = [100, 0]
        result = axis_to_ai(origin, 0, -0.25, 0.0, 100, 50)
        assert result[0] == pytest.approx(75.0)

    def test_round_trip(self):
        """axis_to_ai then ai_to_axis should return the original percentages."""
        origin = [50, 100]
        angle = math.radians(30)
        length = 200
        cross_w = 80
        along_pct = 0.65
        across_pct = 0.3

        ai_pt = axis_to_ai(origin, angle, along_pct, across_pct, length, cross_w)
        recovered = ai_to_axis(ai_pt, origin, angle, length, cross_w)

        assert recovered[0] == pytest.approx(along_pct, abs=0.01)
        assert recovered[1] == pytest.approx(across_pct, abs=0.01)

    def test_batch(self):
        """Batch converts multiple points correctly."""
        axis_def = compute_axis_from_landmarks([0, 0], [100, 0])
        points = [[0, 0], [0.5, 0], [1.0, 0], [0.5, 0.5]]
        result = batch_axis_to_ai(axis_def, points, 50)

        assert len(result) == 4
        assert result[0][0] == pytest.approx(0.0, abs=0.1)
        assert result[1][0] == pytest.approx(50.0, abs=0.1)
        assert result[2][0] == pytest.approx(100.0, abs=0.1)
        # Last point: along=0.5 -> x=50, across=0.5 -> y=25
        assert result[3][0] == pytest.approx(50.0, abs=0.1)
        assert result[3][1] == pytest.approx(25.0, abs=0.1)


# ---------------------------------------------------------------------------
# Perspective (5 tests)
# ---------------------------------------------------------------------------


class TestPerspective:
    def test_front_symmetric(self):
        """0-degree view -> near == far == base width."""
        base = 100
        near = perspective_cross_width(base, 0, "near")
        far = perspective_cross_width(base, 0, "far")
        assert near == pytest.approx(base)
        assert far == pytest.approx(base)

    def test_side_far_collapses(self):
        """90-degree view -> far width collapses to ~0."""
        far = perspective_cross_width(100, 90, "far")
        assert far == pytest.approx(0.0, abs=0.5)

    def test_quarter_near_wider(self):
        """30-degree view -> near > far."""
        near = perspective_cross_width(100, 30, "near")
        far = perspective_cross_width(100, 30, "far")
        assert near > far

    def test_specific_values(self):
        """Verify against manual cos() computation."""
        base = 80
        angle = 45
        near = perspective_cross_width(base, angle, "near")
        far = perspective_cross_width(base, angle, "far")
        expected_near = base * math.cos(math.radians(angle / 2))
        expected_far = base * math.cos(math.radians(angle))
        assert near == pytest.approx(expected_near, abs=0.01)
        assert far == pytest.approx(expected_far, abs=0.01)

    def test_asymmetric_draw(self):
        """When near != far, positive across uses near width, negative uses far."""
        origin = [0, 0]
        angle = 0  # horizontal axis
        # Positive across (left side) should use near_cross_width
        pt_pos = axis_to_ai(origin, angle, 0.5, 0.5, 100, 50,
                            near_cross_width=40, far_cross_width=20)
        # Negative across (right side) should use far_cross_width
        pt_neg = axis_to_ai(origin, angle, 0.5, -0.5, 100, 50,
                            near_cross_width=40, far_cross_width=20)
        # positive: across_dist = 0.5 * 40 = 20
        assert pt_pos[1] == pytest.approx(20.0, abs=0.1)
        # negative: across_dist = -0.5 * 20 = -10
        assert pt_neg[1] == pytest.approx(-10.0, abs=0.1)


# ---------------------------------------------------------------------------
# Occlusion inference (5 tests)
# ---------------------------------------------------------------------------


class TestOcclusion:
    def _make_visible(self, names_and_positions):
        """Helper to build visible_landmarks dict."""
        return {
            name: {"ai": pos, "type": "structural"}
            for name, pos in names_and_positions.items()
        }

    def test_infer_front_mirror(self):
        """0-degree view -> simple X mirror across midline."""
        visible = self._make_visible({
            "chin": [100, 200],
            "shoulder_r": [130, 180],
        })
        inferred = infer_occluded_landmarks(visible, 0, symmetric=True)
        assert "shoulder_l" in inferred
        # Midline = chin x = 100. shoulder_r is at 130, so dx=30. Reflected = 100-30 = 70.
        assert inferred["shoulder_l"]["ai"][0] == pytest.approx(70.0, abs=0.1)
        assert inferred["shoulder_l"]["ai"][1] == pytest.approx(180.0)

    def test_infer_quarter_foreshorten(self):
        """30-degree view -> reflection is foreshortened by cos(30)."""
        visible = self._make_visible({
            "chin": [100, 200],
            "shoulder_r": [130, 180],
        })
        inferred = infer_occluded_landmarks(visible, 30, symmetric=True)
        assert "shoulder_l" in inferred
        # dx = 30, foreshorten = cos(30deg) = ~0.866
        expected_x = 100 - 30 * math.cos(math.radians(30))
        assert inferred["shoulder_l"]["ai"][0] == pytest.approx(expected_x, abs=0.1)

    def test_midline_not_reflected(self):
        """Midline landmarks (chin, neck) are not reflected — they have no partner."""
        visible = self._make_visible({
            "chin": [100, 200],
            "neck": [100, 190],
        })
        inferred = infer_occluded_landmarks(visible, 0, symmetric=True)
        # Chin and neck are midline landmarks, not in SYMMETRY_PAIRS
        assert "chin" not in inferred
        assert "neck" not in inferred

    def test_no_infer_when_visible(self):
        """When both partners are visible, no inference needed."""
        visible = self._make_visible({
            "chin": [100, 200],
            "shoulder_l": [70, 180],
            "shoulder_r": [130, 180],
        })
        inferred = infer_occluded_landmarks(visible, 0, symmetric=True)
        # Both shoulders visible -> neither inferred
        assert "shoulder_l" not in inferred
        assert "shoulder_r" not in inferred

    def test_inferred_flag(self):
        """All inferred landmarks have 'inferred': True."""
        visible = self._make_visible({
            "chin": [100, 200],
            "shoulder_r": [130, 180],
            "hip_r": [120, 150],
        })
        inferred = infer_occluded_landmarks(visible, 0, symmetric=True)
        for name, data in inferred.items():
            assert data["inferred"] is True, f"{name} missing inferred flag"


# ---------------------------------------------------------------------------
# Transform persistence (3 tests)
# ---------------------------------------------------------------------------


class TestTransformPersistence:
    def test_compute_persist_transform(self, tmp_rig_dir):
        """Save transform to rig and load it back — values match."""
        transform = compute_transform(800, 600, 0, 600, 800, 0)
        rig = _load_rig("xform_test")
        rig["transform"] = transform
        _save_rig("xform_test", rig)

        loaded = _load_rig("xform_test")
        assert loaded["transform"]["scale"] == pytest.approx(transform["scale"])
        assert loaded["transform"]["offset_x"] == pytest.approx(transform["offset_x"])
        assert loaded["transform"]["offset_y"] == pytest.approx(transform["offset_y"])

    def test_pixel_ai_roundtrip(self, tmp_rig_dir):
        """Convert pixel->AI->pixel and verify round trip."""
        transform = compute_transform(800, 600, 0, 600, 800, 0)
        px_x, px_y = 400, 300
        ai_x, ai_y = pixel_to_ai(px_x, px_y, transform)
        recovered_px = ai_to_pixel(ai_x, ai_y, transform)
        assert recovered_px[0] == pytest.approx(px_x, abs=0.01)
        assert recovered_px[1] == pytest.approx(px_y, abs=0.01)

    def test_centering(self, tmp_rig_dir):
        """Small image on big artboard -> offset is nonzero (centering)."""
        # 100x100 image on 800x600 artboard -> scale limited by height
        transform = compute_transform(100, 100, 0, 600, 800, 0)
        # Scale = min(800/100, 600/100) = min(8, 6) = 6
        assert transform["scale"] == pytest.approx(6.0)
        # X offset: (800 - 100*6) / 2 = 100
        assert transform["offset_x"] == pytest.approx(100.0)
        # Y offset: 600 - (600 - 100*6) / 2 = 600 - 0 = 600
        # ab_top - (ab_h - img_h * scale) / 2 = 600 - (600 - 600) / 2 = 600
        assert transform["offset_y"] == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Rig schema (3 tests)
# ---------------------------------------------------------------------------


class TestRigSchema:
    def test_default_has_landmarks(self, tmp_rig_dir):
        """New rig scaffold includes landmarks and axes keys."""
        rig = _load_rig("schema_test")
        assert "landmarks" in rig
        assert "axes" in rig
        assert rig["landmarks"] == {}
        assert rig["axes"] == {}

    def test_save_load_landmarks(self, tmp_rig_dir):
        """Persist landmarks to rig file and reload."""
        rig = _load_rig("lm_persist")
        rig["landmarks"]["head_top"] = {"ai": [100, 500], "type": "structural"}
        rig["landmarks"]["chin"] = {"ai": [100, 450], "type": "structural"}
        _save_rig("lm_persist", rig)

        loaded = _load_rig("lm_persist")
        assert loaded["landmarks"]["head_top"]["ai"] == [100, 500]
        assert loaded["landmarks"]["chin"]["type"] == "structural"

    def test_backward_compat(self, tmp_rig_dir):
        """Old rig without landmarks key -> setdefault adds it."""
        rig = _load_rig("old_rig")
        # Simulate old rig by removing new keys
        del rig["landmarks"]
        del rig["axes"]
        _save_rig("old_rig", rig)

        # Load and use setdefault (as the tool code does)
        loaded = _load_rig("old_rig")
        loaded.setdefault("landmarks", {})
        loaded.setdefault("axes", {})
        assert loaded["landmarks"] == {}
        assert loaded["axes"] == {}


# ---------------------------------------------------------------------------
# Integration (2 tests)
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.fixture
    def synthetic_character_png(self, tmp_path):
        """Create a synthetic character-like silhouette (tall rectangle) on white bg."""
        path = str(tmp_path / "synthetic_char.png")
        # 200x400 image with a tall dark shape centered (character-like)
        img = np.full((400, 200, 3), 255, dtype=np.uint8)  # white bg
        # Draw a dark "body" rectangle, narrower at top (head), wider at middle
        cv2.rectangle(img, (70, 10), (130, 60), (30, 30, 30), -1)   # head
        cv2.rectangle(img, (50, 60), (150, 250), (30, 30, 30), -1)  # torso
        cv2.rectangle(img, (60, 250), (90, 380), (30, 30, 30), -1)  # left leg
        cv2.rectangle(img, (110, 250), (140, 380), (30, 30, 30), -1) # right leg
        cv2.imwrite(path, img)
        return path

    def test_detect_from_synthetic(self, synthetic_character_png):
        """White shape on dark bg -> verify landmarks detected."""
        result = detect_landmarks_from_image(synthetic_character_png)
        assert "error" not in result
        assert len(result["landmarks"]) > 0
        assert result["image_size"] == [200, 400]
        # Should have head_top and feet_bottom at minimum
        assert "head_top" in result["landmarks"]
        assert "feet_bottom" in result["landmarks"]
        # head_top should be near top of image, feet_bottom near bottom
        head_y = result["landmarks"]["head_top"]["px"][1]
        feet_y = result["landmarks"]["feet_bottom"]["px"][1]
        assert head_y < feet_y  # pixel coords: Y increases downward

    def test_draw_on_axis_batch(self):
        """Define axis from landmarks, draw rectangle as axis-relative points, verify rotated coords."""
        # Setup: vertical axis from (100, 0) to (100, -200) (downward in AI)
        axis_def = compute_axis_from_landmarks([100, 0], [100, -200])
        # Rectangle: 4 corners in axis-relative coordinates
        # along: 0->1 spans the axis, across: -0.5 to 0.5 spans cross_width
        rect_points = [
            [0.0, -0.5],   # origin, right side
            [0.0, 0.5],    # origin, left side
            [1.0, 0.5],    # endpoint, left side
            [1.0, -0.5],   # endpoint, right side
        ]
        cross_w = 60
        ai_pts = batch_axis_to_ai(axis_def, rect_points, cross_w)

        # Axis is vertical-down: angle = -90 deg, direction = (0, -1), normal = (1, 0)
        # cos(-90) = 0, sin(-90) = -1
        #
        # Point [0, -0.5]: across_dist = -0.5 * 60 = -30
        #   dx = 0*0 - (-30)*(-1) = -30,  dy = 0*(-1) + (-30)*0 = 0
        #   result = (100-30, 0) = (70, 0)
        #
        # Point [0, 0.5]: across_dist = 0.5 * 60 = 30
        #   dx = 0 - 30*(-1) = 30,  dy = 0 + 30*0 = 0
        #   result = (130, 0)
        #
        # Point [1.0, 0.5]: along_dist = 200, across_dist = 30
        #   dx = 200*0 - 30*(-1) = 30,  dy = 200*(-1) + 30*0 = -200
        #   result = (130, -200)
        #
        # Point [1.0, -0.5]: along_dist = 200, across_dist = -30
        #   dx = 200*0 - (-30)*(-1) = -30,  dy = 200*(-1) + (-30)*0 = -200
        #   result = (70, -200)

        assert len(ai_pts) == 4
        assert ai_pts[0][0] == pytest.approx(70.0, abs=1.0)
        assert ai_pts[0][1] == pytest.approx(0.0, abs=1.0)
        assert ai_pts[1][0] == pytest.approx(130.0, abs=1.0)
        assert ai_pts[1][1] == pytest.approx(0.0, abs=1.0)
        assert ai_pts[2][0] == pytest.approx(130.0, abs=1.0)
        assert ai_pts[2][1] == pytest.approx(-200.0, abs=1.0)
        assert ai_pts[3][0] == pytest.approx(70.0, abs=1.0)
        assert ai_pts[3][1] == pytest.approx(-200.0, abs=1.0)
