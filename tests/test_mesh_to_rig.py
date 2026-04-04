"""Tests for the mesh-to-rig mapping tool.

Verifies nearest vertex search, orthographic projection math,
and status reporting.
All tests are pure Python — no 3D deps required.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.threed.mesh_to_rig import (
    find_nearest_vertex,
    project_3d_to_2d,
)


# ---------------------------------------------------------------------------
# Nearest vertex search
# ---------------------------------------------------------------------------


def test_find_nearest_vertex_exact_match():
    """Find vertex that exactly matches the query point."""
    vertices_2d = [[0, 0], [10, 10], [20, 20], [30, 30]]
    # Query point is exactly vertex 2
    result = find_nearest_vertex([20, 20], vertices_2d)
    assert result == 2


def test_find_nearest_vertex_closest():
    """Find the closest vertex to a point between vertices."""
    vertices_2d = [[0, 0], [100, 0], [100, 100], [0, 100]]
    # Query point is near vertex 1 (100, 0)
    result = find_nearest_vertex([95, 5], vertices_2d)
    assert result == 1

    # Query point is near vertex 3 (0, 100)
    result = find_nearest_vertex([3, 97], vertices_2d)
    assert result == 3


def test_find_nearest_vertex_empty_raises():
    """Empty vertices list raises ValueError."""
    with pytest.raises(ValueError, match="must not be empty"):
        find_nearest_vertex([0, 0], [])


# ---------------------------------------------------------------------------
# Orthographic projection
# ---------------------------------------------------------------------------


def test_orthographic_projection_identity():
    """Identity projection (no camera matrix) keeps x,y and drops z."""
    vertices_3d = [
        [10, 20, 30],
        [40, 50, 60],
        [0, 0, 0],
    ]

    projected = project_3d_to_2d(vertices_3d)

    assert len(projected) == 3
    # With identity projection, x and y pass through
    assert projected[0] == [10, 20]
    assert projected[1] == [40, 50]
    assert projected[2] == [0, 0]


def test_orthographic_projection_with_camera_matrix():
    """Custom camera matrix transforms 3D coords to 2D correctly."""
    vertices_3d = [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
    ]

    # Scale X by 2, swap Y and Z
    camera_matrix = [
        [2, 0, 0],   # u = 2*x + 0*y + 0*z
        [0, 0, 1],   # v = 0*x + 0*y + 1*z
        [0, 0, 0],   # (unused third row)
    ]

    projected = project_3d_to_2d(vertices_3d, camera_matrix)

    assert len(projected) == 3
    # Vertex [1,0,0]: u = 2*1 = 2, v = 0*0 + 0*0 + 1*0 = 0
    assert projected[0] == [2, 0]
    # Vertex [0,1,0]: u = 2*0 = 0, v = 0
    assert projected[1] == [0, 0]
    # Vertex [0,0,1]: u = 0, v = 1
    assert projected[2] == [0, 1]


def test_orthographic_projection_empty():
    """Empty vertex list returns empty result."""
    assert project_3d_to_2d([]) == []
