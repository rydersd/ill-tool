"""Map 2D skeleton landmarks to 3D mesh vertices.

Provides pure-Python functions for:
- Orthographic projection of 3D vertices to 2D
- Finding the nearest mesh vertex to a given 2D landmark point

These operations enable mapping a 2D character skeleton (from body-part
labeling or pose estimation) onto a 3D mesh for rigging.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiMeshToRigInput(BaseModel):
    """Map 2D skeleton landmarks to 3D mesh vertices."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: map_skeleton, status"
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    vertices_3d: Optional[list[list[float]]] = Field(
        default=None,
        description="3D mesh vertices as list of [x, y, z]",
    )
    landmarks_2d: Optional[dict[str, list[float]]] = Field(
        default=None,
        description="Named 2D landmarks, e.g. {'hip': [100, 200], 'knee': [120, 350]}",
    )
    camera_matrix: Optional[list[list[float]]] = Field(
        default=None,
        description="3x3 camera matrix for orthographic projection (optional, uses identity if None)",
    )


# ---------------------------------------------------------------------------
# Projection and nearest-vertex search
# ---------------------------------------------------------------------------


def project_3d_to_2d(
    vertices_3d: list[list[float]],
    camera_matrix: Optional[list[list[float]]] = None,
) -> list[list[float]]:
    """Orthographic projection of 3D vertices to 2D.

    Uses a simple orthographic projection: drop Z coordinate, then
    apply a 2x3 sub-matrix of the camera matrix for translation/scale.

    If no camera_matrix is given, uses identity (x,y pass through):
        [[1, 0, 0],
         [0, 1, 0],
         [0, 0, 1]]

    For a proper orthographic projection with a 3x3 matrix:
        u = m00*x + m01*y + m02*z
        v = m10*x + m11*y + m12*z

    Args:
        vertices_3d: list of [x, y, z] vertices
        camera_matrix: optional 3x3 matrix (only first 2 rows used for projection)

    Returns:
        list of [u, v] projected 2D points
    """
    if not vertices_3d:
        return []

    if camera_matrix is None:
        # Identity orthographic: just take x, y
        return [[v[0], v[1]] for v in vertices_3d]

    # Use first two rows of the camera matrix for projection
    # u = m[0][0]*x + m[0][1]*y + m[0][2]*z
    # v = m[1][0]*x + m[1][1]*y + m[1][2]*z
    result = []
    for v in vertices_3d:
        x, y, z = v[0], v[1], v[2]
        u = camera_matrix[0][0] * x + camera_matrix[0][1] * y + camera_matrix[0][2] * z
        v_coord = camera_matrix[1][0] * x + camera_matrix[1][1] * y + camera_matrix[1][2] * z
        result.append([round(u, 6), round(v_coord, 6)])

    return result


def find_nearest_vertex(
    point_2d: list[float],
    vertices_2d_projection: list[list[float]],
) -> int:
    """Find the nearest projected vertex to a 2D landmark point.

    Uses Euclidean distance to find the closest match.

    Args:
        point_2d: [x, y] landmark position
        vertices_2d_projection: list of [x, y] projected vertex positions

    Returns:
        Index of the nearest vertex

    Raises:
        ValueError: if vertices_2d_projection is empty
    """
    if not vertices_2d_projection:
        raise ValueError("vertices_2d_projection must not be empty")

    best_idx = 0
    best_dist_sq = float("inf")
    px, py = point_2d[0], point_2d[1]

    for i, v in enumerate(vertices_2d_projection):
        dx = v[0] - px
        dy = v[1] - py
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_idx = i

    return best_idx


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_mesh_to_rig tool."""

    @mcp.tool(
        name="adobe_ai_mesh_to_rig",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_mesh_to_rig(params: AiMeshToRigInput) -> str:
        """Map 2D skeleton landmarks to the nearest 3D mesh vertices.

        Actions:
        - map_skeleton: project 3D vertices to 2D, then map each landmark
          to the nearest vertex
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            rig = _load_rig(params.character_name)
            has_joints = bool(rig.get("joints"))
            return json.dumps({
                "action": "status",
                "character_name": params.character_name,
                "has_skeleton": has_joints,
                "joint_count": len(rig.get("joints", {})),
                "supported_actions": ["map_skeleton", "status"],
            }, indent=2)

        # ── map_skeleton ────────────────────────────────────────────
        if action == "map_skeleton":
            if not params.vertices_3d:
                return json.dumps({
                    "error": "vertices_3d is required for map_skeleton",
                })
            if not params.landmarks_2d:
                return json.dumps({
                    "error": "landmarks_2d is required for map_skeleton",
                })

            # Project 3D → 2D
            projected = project_3d_to_2d(
                params.vertices_3d,
                params.camera_matrix,
            )

            # Map each landmark to nearest vertex
            mapping = {}
            for name, point in params.landmarks_2d.items():
                idx = find_nearest_vertex(point, projected)
                mapping[name] = {
                    "vertex_index": idx,
                    "vertex_3d": params.vertices_3d[idx],
                    "projected_2d": projected[idx],
                    "landmark_2d": point,
                    "distance": round(
                        math.sqrt(
                            (projected[idx][0] - point[0]) ** 2
                            + (projected[idx][1] - point[1]) ** 2
                        ),
                        4,
                    ),
                }

            return json.dumps({
                "action": "map_skeleton",
                "character_name": params.character_name,
                "vertex_count": len(params.vertices_3d),
                "landmark_count": len(params.landmarks_2d),
                "mapping": mapping,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["map_skeleton", "status"],
        })
