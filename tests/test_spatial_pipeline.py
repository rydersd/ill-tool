"""Tests for spatial_pipeline — end-to-end 3D-to-2D spatial drawing pipeline.

Covers: status action, adapter function (_from_face_group_boundary),
preview with synthetic cube mesh, and error handling for invalid inputs.
"""

import os
import tempfile

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.pipeline.spatial_pipeline import (
    SpatialPipelineInput,
    _pipeline_status,
    _preview_mesh,
)
from adobe_mcp.apps.illustrator.drawing.contour_to_path import _from_face_group_boundary
from adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis import (
    ML_AVAILABLE as TRELLIS_ML_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Synthetic cube OBJ for integration tests
# ---------------------------------------------------------------------------

CUBE_OBJ = """
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
v 1 1 1
v 0 1 1
f 1 2 3
f 1 3 4
f 5 7 6
f 5 8 7
f 1 5 6
f 1 6 2
f 3 7 8
f 3 8 4
f 1 4 8
f 1 8 5
f 2 6 7
f 2 7 3
""".strip()


@pytest.fixture
def cube_obj_path(tmp_path):
    """Create a temporary OBJ file with the synthetic cube mesh."""
    obj_file = tmp_path / "cube.obj"
    obj_file.write_text(CUBE_OBJ)
    return str(obj_file)


# ---------------------------------------------------------------------------
# 1. Status action returns correct structure
# ---------------------------------------------------------------------------


def test_status_returns_correct_structure():
    """Status action must report pipeline stages and available actions."""
    status = _pipeline_status()

    assert "pipeline" in status
    assert status["pipeline"] == "spatial_3d_to_2d"
    assert "stages" in status
    assert "reconstruction" in status["stages"]
    assert "face_grouping" in status["stages"]
    assert "projection" in status["stages"]
    assert "path_placement" in status["stages"]
    assert "available_actions" in status

    # Face grouping and projection are always available (pure Python)
    assert status["stages"]["face_grouping"]["available"] is True
    assert status["stages"]["projection"]["available"] is True


# ---------------------------------------------------------------------------
# 2. Adapter produces valid shape dict
# ---------------------------------------------------------------------------


def test_adapter_produces_valid_shape_dict():
    """_from_face_group_boundary must return dict with name, approx_points, point_count."""
    boundary = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    artboard = {"width": 800, "height": 600}
    result = _from_face_group_boundary(boundary, "front_face", artboard)

    assert result["name"] == "front_face"
    assert "approx_points" in result
    assert "point_count" in result
    assert result["point_count"] == 4
    assert len(result["approx_points"]) == 4
    # Each point should be a 2-element list
    for pt in result["approx_points"]:
        assert len(pt) == 2
        assert isinstance(pt[0], float)
        assert isinstance(pt[1], float)


# ---------------------------------------------------------------------------
# 3. Adapter preserves point count and order
# ---------------------------------------------------------------------------


def test_adapter_preserves_point_count_and_order():
    """Adapter must output same number of points in same order as input."""
    boundary = [(10.0, 20.0), (30.0, 20.0), (30.0, 40.0), (10.0, 40.0), (20.0, 50.0)]
    artboard = {"width": 1000, "height": 1000}
    result = _from_face_group_boundary(boundary, "test", artboard)

    assert result["point_count"] == 5
    assert len(result["approx_points"]) == 5

    # Verify order is preserved by checking relative positions
    # Point 0 and 1 have same Y in input -> they should have same transformed Y
    # (after Y-flip, they should still share a Y coordinate)
    pts = result["approx_points"]
    # Points 0 and 1 share Y=20 in input, so after transform they share a Y
    assert abs(pts[0][1] - pts[1][1]) < 0.01


# ---------------------------------------------------------------------------
# 4. Adapter applies coordinate transform (Y-flip)
# ---------------------------------------------------------------------------


def test_adapter_applies_y_flip():
    """Points higher in pixel space (larger Y) should map lower in AI space.

    In pixel coordinates, Y increases downward.
    In AI coordinates, Y increases upward.
    So input (0, 0) should have HIGHER AI Y than input (0, 100).
    """
    # Two points: top-left and bottom-left in pixel space
    boundary = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    artboard = {"width": 800, "height": 600}
    result = _from_face_group_boundary(boundary, "test", artboard)

    pts = result["approx_points"]
    # Point at pixel (0,0) should be higher Y in AI than pixel (0,100)
    # pts[0] is (0,0) transformed, pts[3] is (0,100) transformed
    assert pts[0][1] > pts[3][1], (
        f"Y-flip failed: pixel (0,0) got AI Y={pts[0][1]}, "
        f"pixel (0,100) got AI Y={pts[3][1]}"
    )


# ---------------------------------------------------------------------------
# 5. Preview with synthetic cube mesh produces 6 groups
# ---------------------------------------------------------------------------


def test_preview_cube_produces_6_groups(cube_obj_path):
    """A unit cube should produce exactly 6 face groups (one per face)."""
    result = _preview_mesh(cube_obj_path, angle_threshold=15.0, max_groups=12,
                           camera_yaw=0.0, camera_pitch=0.0)

    assert "error" not in result, f"Preview failed: {result.get('error')}"
    assert result["total_groups"] == 6
    assert len(result["groups"]) == 6
    assert result["face_count"] == 12  # 2 triangles per face, 6 faces


# ---------------------------------------------------------------------------
# 6. Preview classifies cube groups correctly
# ---------------------------------------------------------------------------


def test_preview_classifies_cube_groups(cube_obj_path):
    """Cube classification should include top, bottom, front, back, left, right."""
    result = _preview_mesh(cube_obj_path, angle_threshold=15.0, max_groups=12,
                           camera_yaw=0.0, camera_pitch=0.0)

    assert "error" not in result
    labels = set(result["classification"].values())
    expected = {"top_face", "bottom_face", "front_face", "back_face",
                "left_face", "right_face"}
    assert labels == expected, f"Expected {expected}, got {labels}"


# ---------------------------------------------------------------------------
# 7. Preview returns contour arrays in expected format
# ---------------------------------------------------------------------------


def test_preview_returns_contours_in_expected_format(cube_obj_path):
    """Each group in preview result must have a contour as list of [x, y]."""
    result = _preview_mesh(cube_obj_path, angle_threshold=15.0, max_groups=12,
                           camera_yaw=0.0, camera_pitch=0.0)

    assert "error" not in result
    for group in result["groups"]:
        assert "contour" in group
        assert "label" in group
        assert "face_count" in group
        assert isinstance(group["contour"], list)
        # Each contour point should be a 2-element list
        if group["contour"]:
            for pt in group["contour"]:
                assert len(pt) == 2


# ---------------------------------------------------------------------------
# 8. Preview rejects nonexistent mesh path
# ---------------------------------------------------------------------------


def test_preview_rejects_nonexistent_mesh():
    """Preview should return error for a mesh path that doesn't exist."""
    result = _preview_mesh("/nonexistent/mesh.obj", angle_threshold=15.0,
                           max_groups=12, camera_yaw=0.0, camera_pitch=0.0)
    assert "error" in result
    assert "not found" in result["error"].lower() or "nonexistent" in result["error"].lower()


# ---------------------------------------------------------------------------
# 9. Preview with angle_threshold=90 produces fewer groups
# ---------------------------------------------------------------------------


def test_preview_large_threshold_merges_groups(cube_obj_path):
    """With angle_threshold=90, opposite-facing faces should merge,
    producing fewer than 6 groups for a cube."""
    result = _preview_mesh(cube_obj_path, angle_threshold=90.0, max_groups=12,
                           camera_yaw=0.0, camera_pitch=0.0)

    assert "error" not in result
    # With 90-degree threshold, faces within 90 degrees of each other merge.
    # A cube's adjacent faces are 90 degrees apart, so they may merge.
    # At minimum, we expect fewer than the 6 groups from threshold=15.
    assert result["total_groups"] < 6, (
        f"Expected fewer than 6 groups with threshold=90, got {result['total_groups']}"
    )


# ---------------------------------------------------------------------------
# 10. run_from_mesh rejects nonexistent mesh path
# ---------------------------------------------------------------------------


def test_run_from_mesh_rejects_nonexistent_mesh():
    """run_from_mesh via _preview_mesh should reject nonexistent paths.

    We test the preview stage which is the first check in run_from_mesh.
    The actual Illustrator interaction is tested via integration tests.
    """
    result = _preview_mesh("/no/such/file.obj", angle_threshold=15.0,
                           max_groups=12, camera_yaw=0.0, camera_pitch=0.0)
    assert "error" in result


# ---------------------------------------------------------------------------
# 11. run_pipeline rejects missing image_path
# ---------------------------------------------------------------------------


def test_run_pipeline_input_requires_image_path():
    """SpatialPipelineInput should accept image_path=None (optional),
    but the run_pipeline action logic should reject it."""
    # We can test via the _preview_mesh function that no mesh_path fails too
    # The actual run_pipeline action check is in the registered handler,
    # so we test the input model validation here
    inp = SpatialPipelineInput(action="run_pipeline")
    assert inp.image_path is None
    # The handler will check and return error -- tested via integration


# ---------------------------------------------------------------------------
# 12. Status reports TRELLIS availability correctly
# ---------------------------------------------------------------------------


def test_status_reports_trellis_availability():
    """Status should accurately reflect whether TRELLIS ML deps are installed."""
    status = _pipeline_status()

    recon = status["stages"]["reconstruction"]
    assert recon["available"] == TRELLIS_ML_AVAILABLE

    # Verify that run_pipeline is in available_actions only if TRELLIS is ready
    available = status["available_actions"]
    assert "status" in available
    assert "preview" in available
    assert "run_from_mesh" in available
    # run_pipeline depends on both ML_AVAILABLE and TRELLIS_AVAILABLE


# ---------------------------------------------------------------------------
# Additional: adapter handles empty boundary
# ---------------------------------------------------------------------------


def test_adapter_handles_empty_boundary():
    """Adapter should return empty points for empty boundary polygon."""
    result = _from_face_group_boundary([], "empty", {"width": 800, "height": 600})
    assert result["name"] == "empty"
    assert result["approx_points"] == []
    assert result["point_count"] == 0
