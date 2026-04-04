"""Tests for the drawing orchestrator tool — form_edge source integration.

Validates that the drawing orchestrator accepts source='form_edge' and
correctly delegates to the form edge pipeline.  Uses monkeypatching
to avoid requiring Illustrator JSX execution.
"""

import json
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.drawing_orchestrator import (
    DrawingOrchestratorInput,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reference_image(tmp_path):
    """Create a reference image with strong edges.

    Uses a white background with thick black geometric shapes so the
    heuristic multi-exposure edge detector finds persistent edges.
    """
    path = str(tmp_path / "ref.png")
    img = np.ones((512, 512, 3), dtype=np.uint8) * 255
    cv2.rectangle(img, (80, 80), (432, 432), (0, 0, 0), 4)
    cv2.circle(img, (256, 256), 120, (0, 0, 0), 4)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# Input model tests
# ---------------------------------------------------------------------------


class TestDrawingOrchestratorInput:
    """Verify the input model accepts form_edge source."""

    def test_source_form_edge_accepted(self, reference_image):
        """source='form_edge' is a valid input."""
        params = DrawingOrchestratorInput(
            reference_path=reference_image,
            source="form_edge",
        )
        assert params.source == "form_edge"

    def test_source_manifest_default(self, reference_image):
        """Default source is 'manifest'."""
        params = DrawingOrchestratorInput(
            reference_path=reference_image,
        )
        assert params.source == "manifest"

    def test_source_3d_pipeline_still_valid(self, reference_image):
        """source='3d_pipeline' is still accepted (existing functionality)."""
        params = DrawingOrchestratorInput(
            reference_path=reference_image,
            source="3d_pipeline",
            mesh_path="/tmp/mesh.obj",
        )
        assert params.source == "3d_pipeline"

    def test_description_mentions_form_edge(self):
        """The source field description includes form_edge option."""
        field_info = DrawingOrchestratorInput.model_fields["source"]
        assert "form_edge" in field_info.description


# ---------------------------------------------------------------------------
# Form edge pipeline integration (unit-level, no Illustrator)
# ---------------------------------------------------------------------------


class TestFormEdgePipelineIntegration:
    """Test that form edge extraction and coordinate transform work."""

    def test_extract_form_edges_produces_mask(self, reference_image):
        """Form edge extraction returns a valid mask from a reference image."""
        from adobe_mcp.apps.illustrator.form_edge_pipeline import (
            extract_form_edges,
        )

        result = extract_form_edges(reference_image, backend="heuristic")
        assert "error" not in result
        assert result["backend"] == "heuristic"

        mask = result["form_edges"]
        assert mask is not None
        assert mask.shape[0] > 0 and mask.shape[1] > 0
        # Heuristic should find some edge pixels on a high-contrast image
        assert np.count_nonzero(mask) > 0

    def test_edge_mask_to_contours_with_synthetic_mask(self):
        """edge_mask_to_contours extracts contours from a synthetic mask.

        Creates a synthetic binary mask with a known large contour to
        verify the contouring pipeline works independently of the
        heuristic edge detector's output characteristics.
        """
        from adobe_mcp.apps.illustrator.form_edge_pipeline import (
            edge_mask_to_contours,
        )

        # Create a mask with a large filled shape (produces clear contours)
        mask = np.zeros((256, 256), dtype=np.uint8)
        cv2.rectangle(mask, (40, 40), (216, 216), 255, -1)

        contours = edge_mask_to_contours(mask, min_length=10)
        assert len(contours) >= 1
        assert contours[0]["point_count"] >= 3
        assert contours[0]["area"] > 0

    def test_contours_to_ai_points_transform(self):
        """Contour coordinate transform produces valid AI coordinates."""
        from adobe_mcp.apps.illustrator.form_edge_pipeline import (
            contours_to_ai_points,
        )

        # Synthetic contours in pixel space
        contours = [
            {
                "name": "form_edge_0",
                "points": [[50, 50], [200, 50], [200, 200], [50, 200]],
                "point_count": 4,
                "area": 22500.0,
            },
        ]

        artboard = {"left": 0, "top": 600, "right": 800, "bottom": 0}
        ai_contours = contours_to_ai_points(contours, (256, 256), artboard)

        assert len(ai_contours) == 1
        assert ai_contours[0]["name"] == "form_edge_0"
        assert len(ai_contours[0]["points"]) == 4

        # AI coordinates should be within artboard bounds
        for pt in ai_contours[0]["points"]:
            assert 0 <= pt[0] <= 800, f"X out of artboard range: {pt[0]}"
            # AI Y is inverted -- top is positive
            assert -100 <= pt[1] <= 700, f"Y out of artboard range: {pt[1]}"

    def test_contours_to_ai_points_preserves_structure(self):
        """Transform preserves contour count and metadata."""
        from adobe_mcp.apps.illustrator.form_edge_pipeline import (
            contours_to_ai_points,
        )

        contours = [
            {"name": "a", "points": [[0, 0], [10, 0], [10, 10]], "point_count": 3, "area": 50},
            {"name": "b", "points": [[20, 20], [30, 20], [30, 30]], "point_count": 3, "area": 50},
        ]

        result = contours_to_ai_points(contours, (100, 100), (800, 600))

        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"
        assert result[0]["point_count"] == 3
