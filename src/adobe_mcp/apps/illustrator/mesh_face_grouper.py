"""Mesh face grouping by normals for 3D-to-2D illustration pipeline.

Groups mesh faces by their normal direction, extracts face group boundaries,
and projects them to 2D contours for vectorization.

Works with raw vertex/face data (pure Python) or trimesh meshes.
"""

import json
import math
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.path_validation import validate_safe_path

# Reuse 3D math from existing module — do NOT reimplement
from adobe_mcp.apps.illustrator.form_3d_projection import (
    orthographic_project,
    rotation_matrix_x,
    rotation_matrix_y,
    rotation_matrix_z,
)

# Optional trimesh for mesh I/O
try:
    import trimesh

    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class MeshFaceGrouperInput(BaseModel):
    """Group mesh faces by normal direction for 3D-to-2D illustration."""

    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: group, classify, project, status",
    )
    mesh_path: Optional[str] = Field(
        default=None, description="Path to OBJ mesh file"
    )
    angle_threshold: float = Field(
        default=15.0,
        description="Angle threshold in degrees — faces within this angle are grouped together",
    )
    max_groups: int = Field(
        default=12,
        description="Maximum number of groups — triggers hierarchy merge if exceeded",
    )
    camera_yaw: float = Field(
        default=0.0, description="Camera yaw angle in degrees for projection"
    )
    camera_pitch: float = Field(
        default=0.0, description="Camera pitch angle in degrees for projection"
    )


# ---------------------------------------------------------------------------
# Core geometry functions (pure Python + numpy)
# ---------------------------------------------------------------------------


def compute_face_normal(
    v0: np.ndarray, v1: np.ndarray, v2: np.ndarray
) -> np.ndarray:
    """Compute the unit normal of a triangle defined by three vertices.

    Uses cross product of edge vectors (v1-v0) x (v2-v0), then normalizes.
    Returns zero vector for degenerate triangles (collinear or coincident vertices).

    Args:
        v0, v1, v2: 3D points as numpy arrays or lists.

    Returns:
        Unit normal vector as numpy array (3,). Zero vector if degenerate.
    """
    v0 = np.asarray(v0, dtype=np.float64)
    v1 = np.asarray(v1, dtype=np.float64)
    v2 = np.asarray(v2, dtype=np.float64)

    edge1 = v1 - v0
    edge2 = v2 - v0
    cross = np.cross(edge1, edge2)
    length = np.linalg.norm(cross)

    if length < 1e-12:
        # Degenerate triangle — return zero vector
        return np.zeros(3, dtype=np.float64)

    return cross / length


def load_mesh_from_obj(obj_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse an OBJ file into vertices and faces arrays.

    Reads 'v x y z' lines as vertices and 'f v1 v2 v3' lines as faces.
    Handles face definitions with vertex indices only (no normals/texcoords).
    Also handles 'f v1/vt1 v2/vt2 v3/vt3' and 'f v1/vt1/vn1 ...' formats
    by extracting only the vertex index (first number before any slash).

    Args:
        obj_path: Path to the OBJ file.

    Returns:
        Tuple of (vertices, faces):
        - vertices: np.ndarray shape (N, 3), dtype float64
        - faces: np.ndarray shape (M, 3), dtype int32, 0-indexed
    """
    vertices = []
    faces = []

    obj_path = validate_safe_path(obj_path)
    with open(obj_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parts = stripped.split()
            if parts[0] == "v" and len(parts) >= 4:
                # Vertex line: v x y z [w]
                vertices.append(
                    [float(parts[1]), float(parts[2]), float(parts[3])]
                )
            elif parts[0] == "f" and len(parts) >= 4:
                # Face line: f v1 v2 v3 ... (possibly with /vt/vn)
                # Extract vertex indices (first number before any /)
                face_verts = []
                valid_face = True
                for token in parts[1:4]:
                    # Handle v, v/vt, v/vt/vn, v//vn formats
                    idx_str = token.split("/")[0]
                    # OBJ indices are 1-based, convert to 0-based
                    idx = int(idx_str) - 1
                    if idx < 0 or idx >= len(vertices):
                        valid_face = False
                        break
                    face_verts.append(idx)
                if valid_face:
                    faces.append(face_verts)

    verts_array = np.array(vertices, dtype=np.float64) if vertices else np.empty((0, 3), dtype=np.float64)
    faces_array = np.array(faces, dtype=np.int32) if faces else np.empty((0, 3), dtype=np.int32)

    return verts_array, faces_array


def group_faces_by_normal(
    vertices: np.ndarray,
    faces: np.ndarray,
    angle_threshold: float = 15.0,
    max_groups: int = 12,
) -> list[dict]:
    """Group mesh faces by their normal direction.

    Iterates over faces, assigning each to the first existing group whose
    mean normal is within angle_threshold degrees. Creates a new group if
    no match is found. Runs hierarchy merge if group count exceeds max_groups.

    Args:
        vertices: Nx3 array of vertex positions.
        faces: Mx3 array of face vertex indices (0-indexed).
        angle_threshold: Maximum angle in degrees between a face normal
            and a group's mean normal for the face to join that group.
        max_groups: Maximum number of groups before hierarchy merge triggers.

    Returns:
        List of FaceGroup dicts, each with:
        - group_id: int
        - face_indices: list[int]
        - mean_normal: [nx, ny, nz]
        - face_count: int
    """
    if len(faces) == 0:
        return []

    threshold_rad = math.radians(angle_threshold)

    # Compute normal for every face
    normals = np.zeros((len(faces), 3), dtype=np.float64)
    for i, face in enumerate(faces):
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        normals[i] = compute_face_normal(v0, v1, v2)

    # Greedy clustering: assign each face to the first group within threshold
    # groups: list of (mean_normal_sum, normal_count, face_indices)
    group_data: list[tuple[np.ndarray, int, list[int]]] = []

    for face_idx in range(len(faces)):
        face_normal = normals[face_idx]
        # Skip degenerate faces (zero normal)
        if np.linalg.norm(face_normal) < 1e-12:
            continue

        assigned = False
        for g_idx, (normal_sum, count, indices) in enumerate(group_data):
            # Compute mean normal of the group
            mean_normal = normal_sum / np.linalg.norm(normal_sum)
            # Angle between face normal and group mean — no abs(),
            # so opposite-facing normals (e.g., +Z vs -Z) stay in separate groups
            dot = np.clip(np.dot(face_normal, mean_normal), -1.0, 1.0)
            angle = math.acos(dot)

            if angle <= threshold_rad:
                normal_sum += face_normal
                group_data[g_idx] = (normal_sum, count + 1, indices)
                indices.append(face_idx)
                assigned = True
                break

        if not assigned:
            group_data.append(
                (face_normal.copy(), 1, [face_idx])
            )

    # Build result list
    groups = []
    for g_idx, (normal_sum, count, indices) in enumerate(group_data):
        norm_len = np.linalg.norm(normal_sum)
        if norm_len > 1e-12:
            mean_normal = (normal_sum / norm_len).tolist()
        else:
            mean_normal = [0.0, 0.0, 0.0]

        groups.append({
            "group_id": g_idx,
            "face_indices": indices,
            "mean_normal": [round(n, 6) for n in mean_normal],
            "face_count": len(indices),
        })

    # Hierarchy merge if too many groups
    if len(groups) > max_groups:
        groups = _merge_small_groups(groups, faces, max_groups, vertices)

    return groups


def _merge_small_groups(
    groups: list[dict],
    faces: np.ndarray,
    max_groups: int,
    vertices: np.ndarray,
) -> list[dict]:
    """Merge groups until count is within max_groups.

    Strategy:
    1. First pass: merge small groups (< 5% of total faces) into their
       most-similar neighbor by normal direction.
    2. If still over max_groups, force-merge the two most similar groups
       (by dot product of mean normals), regardless of size.
    3. Repeat until num_groups <= max_groups.

    Args:
        groups: List of group dicts from group_faces_by_normal.
        faces: Mx3 face array for boundary computation.
        max_groups: Target maximum group count.
        vertices: Nx3 vertex array for normal recomputation.

    Returns:
        Merged list of group dicts with renumbered group_ids.
    """
    total_faces = sum(g["face_count"] for g in groups)
    small_threshold = max(1, int(total_faces * 0.05))

    def _recompute_normal(group: dict) -> None:
        """Recompute mean normal from all faces in a group."""
        normal_sum = np.zeros(3, dtype=np.float64)
        for fi in group["face_indices"]:
            face = faces[fi]
            n = compute_face_normal(
                vertices[face[0]], vertices[face[1]], vertices[face[2]]
            )
            normal_sum += n
        norm_len = np.linalg.norm(normal_sum)
        if norm_len > 1e-12:
            group["mean_normal"] = [
                round(v, 6) for v in (normal_sum / norm_len).tolist()
            ]

    def _merge_pair(groups: list[dict], src_idx: int, dst_idx: int) -> list[dict]:
        """Merge group at src_idx into group at dst_idx, return updated list."""
        dst = groups[dst_idx]
        src = groups[src_idx]
        dst["face_indices"].extend(src["face_indices"])
        dst["face_count"] = len(dst["face_indices"])
        _recompute_normal(dst)
        # Remove source
        return [g for i, g in enumerate(groups) if i != src_idx]

    # Phase 1: merge small groups into most-similar neighbor
    changed = True
    while len(groups) > max_groups and changed:
        changed = False
        groups.sort(key=lambda g: g["face_count"])

        for i, group in enumerate(groups):
            if group["face_count"] >= small_threshold:
                continue
            if len(groups) <= max_groups:
                break

            # Find most similar neighbor
            best_target = None
            best_similarity = -2.0
            group_normal = np.array(group["mean_normal"])
            for j, candidate in enumerate(groups):
                if j == i:
                    continue
                dot = np.dot(group_normal, np.array(candidate["mean_normal"]))
                if dot > best_similarity:
                    best_similarity = dot
                    best_target = j

            if best_target is not None:
                groups = _merge_pair(groups, i, best_target if best_target < i else best_target - 1)
                # Adjust: _merge_pair removes index i, which shifts indices above i down by 1
                changed = True
                break  # restart loop after structural change

    # Phase 2: force-merge most similar pair regardless of size
    while len(groups) > max_groups:
        best_i, best_j = 0, 1
        best_sim = -2.0
        for i in range(len(groups)):
            ni = np.array(groups[i]["mean_normal"])
            for j in range(i + 1, len(groups)):
                nj = np.array(groups[j]["mean_normal"])
                dot = np.dot(ni, nj)
                if dot > best_sim:
                    best_sim = dot
                    best_i, best_j = i, j
        # Merge smaller into larger
        if groups[best_i]["face_count"] <= groups[best_j]["face_count"]:
            groups = _merge_pair(groups, best_i, best_j - 1 if best_i < best_j else best_j)
        else:
            groups = _merge_pair(groups, best_j, best_i)

    # Renumber group IDs
    for idx, group in enumerate(groups):
        group["group_id"] = idx

    return groups


def extract_group_boundary(
    vertices: np.ndarray,
    faces: np.ndarray,
    group_face_indices: list[int],
) -> list[list[np.ndarray]]:
    """Extract boundary edges of a face group as ordered 3D polygons.

    A boundary edge appears exactly once in the group (not shared with
    another face in the same group). Edges are then chained into closed
    polygon loops.

    Args:
        vertices: Nx3 vertex array.
        faces: Mx3 face array.
        group_face_indices: List of face indices in this group.

    Returns:
        List of boundary loops, each a list of 3D vertex positions (np.ndarray).
        Empty list if no boundary edges found.
    """
    if not group_face_indices:
        return []

    # Build edge counts — an edge is identified by a sorted tuple of vertex indices
    edge_count: dict[tuple[int, int], int] = {}
    # Also track directed edges for ordering
    directed_edges: list[tuple[int, int]] = []

    for fi in group_face_indices:
        face = faces[fi]
        # Three edges per triangle
        edges = [
            (int(face[0]), int(face[1])),
            (int(face[1]), int(face[2])),
            (int(face[2]), int(face[0])),
        ]
        for e in edges:
            key = (min(e[0], e[1]), max(e[0], e[1]))
            edge_count[key] = edge_count.get(key, 0) + 1

    # Boundary edges appear exactly once
    boundary_edges_set = {k for k, v in edge_count.items() if v == 1}
    if not boundary_edges_set:
        return []

    # Build adjacency for boundary vertices
    adjacency: dict[int, list[int]] = {}
    for a, b in boundary_edges_set:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    # Chain boundary edges into closed loops
    visited_edges: set[tuple[int, int]] = set()
    loops: list[list[np.ndarray]] = []

    for start_vertex in adjacency:
        # Try to start a loop from each unvisited boundary vertex
        if all(
            (min(start_vertex, n), max(start_vertex, n)) in visited_edges
            for n in adjacency[start_vertex]
        ):
            continue

        loop_vertices = [start_vertex]
        current = start_vertex

        while True:
            neighbors = adjacency.get(current, [])
            next_vertex = None
            for n in neighbors:
                edge_key = (min(current, n), max(current, n))
                if edge_key not in visited_edges:
                    next_vertex = n
                    visited_edges.add(edge_key)
                    break

            if next_vertex is None:
                break

            if next_vertex == start_vertex:
                # Closed the loop
                break

            loop_vertices.append(next_vertex)
            current = next_vertex

        if len(loop_vertices) >= 3:
            loops.append([vertices[vi].copy() for vi in loop_vertices])

    return loops


def project_group_boundaries(
    groups: list[dict],
    vertices: np.ndarray,
    faces: np.ndarray,
    camera_yaw: float = 0.0,
    camera_pitch: float = 0.0,
) -> list[list[list[tuple[float, float]]]]:
    """Project face group boundaries to 2D contours.

    For each group, extracts boundary loops, rotates them by camera
    yaw/pitch, and projects to 2D via orthographic projection.

    Args:
        groups: List of group dicts from group_faces_by_normal.
        vertices: Nx3 vertex array.
        faces: Mx3 face array.
        camera_yaw: Camera yaw angle in degrees.
        camera_pitch: Camera pitch angle in degrees.

    Returns:
        List of contour sets, one per group. Each contour set is a list of
        boundary loops, each loop a list of (x, y) tuples.
    """
    # Build camera rotation matrix: yaw around Y, then pitch around X
    yaw_rad = math.radians(camera_yaw)
    pitch_rad = math.radians(camera_pitch)
    rot = rotation_matrix_x(pitch_rad) @ rotation_matrix_y(yaw_rad)

    all_contours = []
    for group in groups:
        boundaries = extract_group_boundary(
            vertices, faces, group["face_indices"]
        )
        group_contours = []
        for loop_3d in boundaries:
            contour_2d = []
            for pt in loop_3d:
                # Rotate by camera
                rotated = rot @ np.asarray(pt, dtype=np.float64)
                # Project to 2D (drop Z)
                x, y = orthographic_project(rotated)
                contour_2d.append((round(x, 4), round(y, 4)))
            group_contours.append(contour_2d)
        all_contours.append(group_contours)

    return all_contours


def classify_face_groups(groups: list[dict]) -> dict[int, str]:
    """Classify each face group by its dominant normal direction.

    Labels are based on which axis component is largest in the mean normal:
    - Largest +Y component -> "top_face"
    - Largest -Y component -> "bottom_face"
    - Largest +Z component -> "front_face"
    - Largest -Z component -> "back_face"
    - Largest +X component -> "right_face"
    - Largest -X component -> "left_face"

    Args:
        groups: List of group dicts with 'mean_normal' field.

    Returns:
        Dict mapping group_id to label string.
    """
    labels: dict[int, str] = {}

    for group in groups:
        normal = group["mean_normal"]
        nx, ny, nz = normal[0], normal[1], normal[2]

        # Find dominant axis by absolute value
        abs_components = [abs(nx), abs(ny), abs(nz)]
        max_idx = abs_components.index(max(abs_components))

        if max_idx == 0:
            # X-axis dominant
            labels[group["group_id"]] = "right_face" if nx > 0 else "left_face"
        elif max_idx == 1:
            # Y-axis dominant
            labels[group["group_id"]] = "top_face" if ny > 0 else "bottom_face"
        else:
            # Z-axis dominant
            labels[group["group_id"]] = "front_face" if nz > 0 else "back_face"

    return labels


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_mesh_face_grouper tool."""

    @mcp.tool(
        name="adobe_ai_mesh_face_grouper",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_mesh_face_grouper(
        params: MeshFaceGrouperInput,
    ) -> str:
        """Group mesh faces by normal direction for 3D-to-2D illustration.

        Actions:
        - group: Load mesh, group faces by normal direction, return groups.
        - classify: Group + classify each group (top/front/side/bottom/back).
        - project: Group + project boundaries to 2D contours.
        - status: Report trimesh availability and tool info.
        """
        action = params.action.lower().strip()

        if action == "status":
            status = {
                "tool": "mesh_face_grouper",
                "description": "Groups mesh faces by normal direction for 3D-to-2D illustration",
                "trimesh_available": TRIMESH_AVAILABLE,
                "supported_formats": ["obj"],
                "default_angle_threshold": 15.0,
                "default_max_groups": 12,
            }
            return json.dumps(status, indent=2)

        # All other actions require a mesh file
        if not params.mesh_path:
            return json.dumps({"error": "mesh_path required for this action"})

        # Load mesh
        try:
            vertices, faces = load_mesh_from_obj(params.mesh_path)
        except FileNotFoundError:
            return json.dumps({"error": f"Mesh file not found: {params.mesh_path}"})
        except Exception as exc:
            return json.dumps({"error": f"Failed to load mesh: {exc}"})

        if len(faces) == 0:
            return json.dumps({
                "groups": [],
                "vertex_count": len(vertices),
                "face_count": 0,
                "note": "Mesh has no faces",
            })

        # Group faces by normal
        groups = group_faces_by_normal(
            vertices, faces, params.angle_threshold, params.max_groups
        )

        if action == "group":
            return json.dumps({
                "groups": groups,
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "group_count": len(groups),
            }, indent=2)

        elif action == "classify":
            labels = classify_face_groups(groups)
            # Attach labels to groups
            for group in groups:
                group["label"] = labels.get(group["group_id"], "unknown")
            return json.dumps({
                "groups": groups,
                "labels": labels,
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "group_count": len(groups),
            }, indent=2)

        elif action == "project":
            contours = project_group_boundaries(
                groups, vertices, faces,
                params.camera_yaw, params.camera_pitch,
            )
            labels = classify_face_groups(groups)
            result = {
                "contours": [],
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "group_count": len(groups),
                "camera_yaw": params.camera_yaw,
                "camera_pitch": params.camera_pitch,
            }
            for i, group in enumerate(groups):
                # Convert numpy arrays in contours to plain lists
                group_contours = contours[i] if i < len(contours) else []
                result["contours"].append({
                    "group_id": group["group_id"],
                    "label": labels.get(group["group_id"], "unknown"),
                    "boundaries": [
                        [list(pt) for pt in loop]
                        for loop in group_contours
                    ],
                })
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["group", "classify", "project", "status"],
            })
