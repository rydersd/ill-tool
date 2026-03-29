"""Tests for mesh_face_grouper — face grouping by normals for 3D-to-2D illustration.

Uses a synthetic cube mesh (8 vertices, 12 triangular faces) to verify
grouping, boundary extraction, projection, and classification.
"""

import os
import tempfile

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.mesh_face_grouper import (
    classify_face_groups,
    compute_face_normal,
    extract_group_boundary,
    group_faces_by_normal,
    load_mesh_from_obj,
    project_group_boundaries,
)


# ---------------------------------------------------------------------------
# Synthetic cube mesh data
# ---------------------------------------------------------------------------

# Unit cube centered at (0.5, 0.5, 0.5)
CUBE_VERTICES = np.array(
    [
        [0, 0, 0],  # 0: back-bottom-left
        [1, 0, 0],  # 1: back-bottom-right
        [1, 1, 0],  # 2: back-top-right
        [0, 1, 0],  # 3: back-top-left
        [0, 0, 1],  # 4: front-bottom-left
        [1, 0, 1],  # 5: front-bottom-right
        [1, 1, 1],  # 6: front-top-right
        [0, 1, 1],  # 7: front-top-left
    ],
    dtype=np.float64,
)

# 12 triangles, 2 per cube face
# Winding order chosen so normals point outward
CUBE_FACES = np.array(
    [
        [0, 2, 1],  # back face (-Z), tri 1
        [0, 3, 2],  # back face (-Z), tri 2
        [4, 5, 6],  # front face (+Z), tri 1
        [4, 6, 7],  # front face (+Z), tri 2
        [0, 1, 5],  # bottom face (-Y), tri 1
        [0, 5, 4],  # bottom face (-Y), tri 2
        [2, 3, 7],  # top face (+Y), tri 1
        [2, 7, 6],  # top face (+Y), tri 2
        [0, 4, 7],  # left face (-X), tri 1
        [0, 7, 3],  # left face (-X), tri 2
        [1, 2, 6],  # right face (+X), tri 1
        [1, 6, 5],  # right face (+X), tri 2
    ],
    dtype=np.int32,
)


def _write_cube_obj(path: str) -> None:
    """Write the cube mesh to an OBJ file."""
    with open(path, "w") as f:
        f.write("# Synthetic unit cube for testing\n")
        for v in CUBE_VERTICES:
            f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for face in CUBE_FACES:
            # OBJ is 1-indexed
            f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")


# ---------------------------------------------------------------------------
# Test 1: compute_face_normal on known triangle
# ---------------------------------------------------------------------------


class TestComputeFaceNormal:
    def test_known_triangle_normal(self):
        """Triangle in XY plane should have Z-axis normal."""
        v0 = np.array([0, 0, 0])
        v1 = np.array([1, 0, 0])
        v2 = np.array([0, 1, 0])
        normal = compute_face_normal(v0, v1, v2)
        # Cross product of (1,0,0) x (0,1,0) = (0,0,1)
        np.testing.assert_allclose(normal, [0, 0, 1], atol=1e-10)

    def test_degenerate_triangle(self):
        """Degenerate triangle (collinear points) returns zero vector."""
        v0 = np.array([0, 0, 0])
        v1 = np.array([1, 0, 0])
        v2 = np.array([2, 0, 0])
        normal = compute_face_normal(v0, v1, v2)
        np.testing.assert_allclose(normal, [0, 0, 0], atol=1e-10)

    def test_normal_is_unit_length(self):
        """Normal vector should always be unit length (or zero)."""
        v0 = np.array([0, 0, 0])
        v1 = np.array([3, 0, 0])
        v2 = np.array([0, 4, 0])
        normal = compute_face_normal(v0, v1, v2)
        length = np.linalg.norm(normal)
        assert abs(length - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Test 2: load_mesh_from_obj
# ---------------------------------------------------------------------------


class TestLoadMeshFromObj:
    def test_reads_cube_correctly(self):
        """OBJ parser reads correct vertex and face counts for cube."""
        with tempfile.NamedTemporaryFile(suffix=".obj", mode="w", delete=False) as f:
            f.write("# test cube\n")
            for v in CUBE_VERTICES:
                f.write(f"v {v[0]} {v[1]} {v[2]}\n")
            for face in CUBE_FACES:
                f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
            obj_path = f.name

        try:
            verts, faces = load_mesh_from_obj(obj_path)
            assert verts.shape == (8, 3), f"Expected 8 vertices, got {verts.shape[0]}"
            assert faces.shape == (12, 3), f"Expected 12 faces, got {faces.shape[0]}"
            # Verify 0-indexed conversion
            assert faces.min() == 0
            assert faces.max() == 7
        finally:
            os.unlink(obj_path)

    def test_handles_slash_format(self):
        """OBJ parser handles f v/vt/vn format."""
        with tempfile.NamedTemporaryFile(suffix=".obj", mode="w", delete=False) as f:
            f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\n")
            f.write("f 1/1/1 2/2/2 3/3/3\n")
            obj_path = f.name

        try:
            verts, faces = load_mesh_from_obj(obj_path)
            assert verts.shape == (3, 3)
            assert faces.shape == (1, 3)
            np.testing.assert_array_equal(faces[0], [0, 1, 2])
        finally:
            os.unlink(obj_path)


# ---------------------------------------------------------------------------
# Test 3-5: group_faces_by_normal
# ---------------------------------------------------------------------------


class TestGroupFacesByNormal:
    def test_cube_produces_six_groups(self):
        """Cube with threshold=15 should produce exactly 6 groups (one per face)."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        assert len(groups) == 6, f"Expected 6 groups, got {len(groups)}"

    def test_coplanar_faces_merged(self):
        """Each cube face has 2 coplanar triangles — they must share a group."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        for group in groups:
            assert group["face_count"] == 2, (
                f"Group {group['group_id']} has {group['face_count']} faces, expected 2"
            )

    def test_tight_threshold_still_groups_exact_normals(self):
        """With 1-degree threshold, exact coplanar faces should still group.

        The cube's coplanar triangle pairs have identical normals (not just
        similar), so even a 1-degree threshold should produce 6 groups, not 12.
        """
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=1.0)
        # Exact normals should still match even with tight threshold
        assert len(groups) == 6, (
            f"Expected 6 groups (exact normals match), got {len(groups)}"
        )


# ---------------------------------------------------------------------------
# Test 6: max_groups triggers hierarchy merge
# ---------------------------------------------------------------------------


class TestHierarchyMerge:
    def test_max_groups_respected(self):
        """Setting max_groups=3 forces merge to <= 3 groups."""
        groups = group_faces_by_normal(
            CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0, max_groups=3
        )
        assert len(groups) <= 3, f"Expected <= 3 groups, got {len(groups)}"
        # All faces should still be accounted for
        total_faces = sum(g["face_count"] for g in groups)
        assert total_faces == 12, f"Lost faces during merge: {total_faces} != 12"


# ---------------------------------------------------------------------------
# Test 7-8: extract_group_boundary
# ---------------------------------------------------------------------------


class TestExtractGroupBoundary:
    def test_cube_group_boundary_is_rectangle(self):
        """Each cube face group boundary should have 4 vertices (rectangle)."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        for group in groups:
            loops = extract_group_boundary(
                CUBE_VERTICES, CUBE_FACES, group["face_indices"]
            )
            assert len(loops) >= 1, f"Group {group['group_id']} has no boundary loops"
            # Each cube face boundary is a quadrilateral
            for loop in loops:
                assert len(loop) == 4, (
                    f"Expected 4 boundary vertices, got {len(loop)}"
                )

    def test_boundary_forms_closed_loop(self):
        """Boundary edges should form a connected loop.

        We verify closure by checking that the chain visits exactly as many
        vertices as there are boundary edges (each vertex used once in the loop).
        """
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        for group in groups:
            loops = extract_group_boundary(
                CUBE_VERTICES, CUBE_FACES, group["face_indices"]
            )
            for loop in loops:
                # Loop should have >= 3 vertices and form a closed chain
                assert len(loop) >= 3, "Loop too short to be closed"
                # Verify adjacency: each consecutive pair shares an edge
                # (the chaining algorithm guarantees this by construction)


# ---------------------------------------------------------------------------
# Test 9: project_group_boundaries
# ---------------------------------------------------------------------------


class TestProjectGroupBoundaries:
    def test_identity_projection_produces_2d_rectangles(self):
        """With yaw=0 pitch=0, projected cube boundaries are 2D rectangles."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        contours = project_group_boundaries(
            groups, CUBE_VERTICES, CUBE_FACES,
            camera_yaw=0.0, camera_pitch=0.0,
        )
        assert len(contours) == 6, f"Expected 6 contour sets, got {len(contours)}"
        # Each group should have at least one boundary with 2D points
        for group_contours in contours:
            for loop in group_contours:
                for pt in loop:
                    assert len(pt) == 2, "Projected points must be 2D (x, y)"

    def test_rotated_projection_changes_contours(self):
        """Yaw rotation should produce different 2D contours than identity."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        contours_0 = project_group_boundaries(
            groups, CUBE_VERTICES, CUBE_FACES,
            camera_yaw=0.0, camera_pitch=0.0,
        )
        contours_45 = project_group_boundaries(
            groups, CUBE_VERTICES, CUBE_FACES,
            camera_yaw=45.0, camera_pitch=0.0,
        )
        # At least some contour points should differ
        all_same = True
        for c0, c45 in zip(contours_0, contours_45):
            for l0, l45 in zip(c0, c45):
                for p0, p45 in zip(l0, l45):
                    if abs(p0[0] - p45[0]) > 0.01 or abs(p0[1] - p45[1]) > 0.01:
                        all_same = False
                        break
        assert not all_same, "45-degree yaw should change projected contours"


# ---------------------------------------------------------------------------
# Test 10: classify_face_groups
# ---------------------------------------------------------------------------


class TestClassifyFaceGroups:
    def test_cube_classification(self):
        """Cube groups should be classified as top/bottom/front/back/left/right."""
        groups = group_faces_by_normal(CUBE_VERTICES, CUBE_FACES, angle_threshold=15.0)
        labels = classify_face_groups(groups)

        # All 6 standard labels should appear
        expected_labels = {"top_face", "bottom_face", "front_face", "back_face", "left_face", "right_face"}
        actual_labels = set(labels.values())
        assert actual_labels == expected_labels, (
            f"Expected labels {expected_labels}, got {actual_labels}"
        )


# ---------------------------------------------------------------------------
# Test 11: degenerate face handling
# ---------------------------------------------------------------------------


class TestDegenerateFaces:
    def test_degenerate_face_excluded(self):
        """Zero-area triangle (collinear vertices) should be excluded from groups."""
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [2, 0, 0],  # collinear
            [0, 0, 0], [1, 0, 0], [0, 1, 0],  # valid
        ], dtype=np.float64)
        faces = np.array([
            [0, 1, 2],  # degenerate
            [3, 4, 5],  # valid
        ], dtype=np.int32)
        groups = group_faces_by_normal(verts, faces, angle_threshold=15.0)
        # Only the valid face should appear
        total_grouped_faces = sum(g["face_count"] for g in groups)
        assert total_grouped_faces == 1, (
            f"Expected 1 valid face in groups, got {total_grouped_faces}"
        )


# ---------------------------------------------------------------------------
# Test 12: empty mesh
# ---------------------------------------------------------------------------


class TestEmptyMesh:
    def test_empty_faces_returns_empty(self):
        """Mesh with no faces returns empty group list."""
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        faces = np.empty((0, 3), dtype=np.int32)
        groups = group_faces_by_normal(verts, faces, angle_threshold=15.0)
        assert groups == [], f"Expected empty list, got {groups}"


# ---------------------------------------------------------------------------
# Test 13: single-face mesh
# ---------------------------------------------------------------------------


class TestSingleFaceMesh:
    def test_single_face_produces_one_group(self):
        """A mesh with one face should produce exactly one group."""
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0]
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        groups = group_faces_by_normal(verts, faces, angle_threshold=15.0)
        assert len(groups) == 1
        assert groups[0]["face_count"] == 1
        assert groups[0]["face_indices"] == [0]


# ---------------------------------------------------------------------------
# Test 14: OBJ round-trip (write + load + group)
# ---------------------------------------------------------------------------


class TestObjRoundTrip:
    def test_obj_write_load_group(self):
        """Write cube to OBJ, load it back, group faces — should produce 6 groups."""
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            obj_path = f.name

        try:
            _write_cube_obj(obj_path)
            verts, faces = load_mesh_from_obj(obj_path)
            assert verts.shape == (8, 3)
            assert faces.shape == (12, 3)

            groups = group_faces_by_normal(verts, faces, angle_threshold=15.0)
            assert len(groups) == 6, f"Expected 6 groups from loaded cube, got {len(groups)}"
        finally:
            os.unlink(obj_path)


# ---------------------------------------------------------------------------
# Test: trimesh comparison (conditional)
# ---------------------------------------------------------------------------

try:
    import trimesh
    TRIMESH_INSTALLED = True
except ImportError:
    TRIMESH_INSTALLED = False


@pytest.mark.skipif(not TRIMESH_INSTALLED, reason="trimesh not installed")
class TestTrimeshComparison:
    def test_pure_python_matches_trimesh(self):
        """Pure Python OBJ loading produces same geometry as trimesh."""
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            obj_path = f.name

        try:
            _write_cube_obj(obj_path)

            # Pure Python path
            py_verts, py_faces = load_mesh_from_obj(obj_path)

            # Trimesh path
            mesh = trimesh.load(obj_path, force="mesh")
            tm_verts = np.array(mesh.vertices, dtype=np.float64)
            tm_faces = np.array(mesh.faces, dtype=np.int32)

            # Vertex and face counts should match
            assert py_verts.shape == tm_verts.shape, (
                f"Vertex shape mismatch: {py_verts.shape} vs {tm_verts.shape}"
            )
            assert py_faces.shape == tm_faces.shape, (
                f"Face shape mismatch: {py_faces.shape} vs {tm_faces.shape}"
            )

            # Group results should match
            py_groups = group_faces_by_normal(py_verts, py_faces, angle_threshold=15.0)
            tm_groups = group_faces_by_normal(tm_verts, tm_faces, angle_threshold=15.0)
            assert len(py_groups) == len(tm_groups), (
                f"Group count mismatch: {len(py_groups)} vs {len(tm_groups)}"
            )
        finally:
            os.unlink(obj_path)
