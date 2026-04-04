"""USDZ export for 3D mesh data.

Generates USD ASCII text for simple meshes (vertices + faces) using
pure Python.  When trimesh is available, can convert OBJ files to USDZ.

3D dependencies (trimesh) are gracefully optional.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Graceful import for optional 3D dependency
try:
    import trimesh as _trimesh
except ImportError:
    _trimesh = None


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiExportUsdzInput(BaseModel):
    """USDZ export from mesh data or OBJ file."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: export, status"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    mesh_data: Optional[dict] = Field(
        default=None,
        description="Mesh data with 'vertices' (list of [x,y,z]) and 'faces' (list of vertex-index lists)",
    )
    obj_path: Optional[str] = Field(
        default=None, description="Path to OBJ file for trimesh-based conversion"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output file path (auto-generated if None)"
    )


# ---------------------------------------------------------------------------
# Pure Python USDA generation
# ---------------------------------------------------------------------------


def generate_usda_text(mesh_data: dict) -> str:
    """Generate USD ASCII text for a simple mesh.

    Args:
        mesh_data: dict with 'vertices' (list of [x,y,z]) and
                   'faces' (list of vertex-index lists, e.g. [[0,1,2], [2,3,0]])

    Returns:
        USDA-formatted string describing the mesh.

    Raises:
        ValueError: if mesh_data is missing required keys or has invalid data.
    """
    if not mesh_data:
        raise ValueError("mesh_data must be provided")

    vertices = mesh_data.get("vertices")
    faces = mesh_data.get("faces")

    if not vertices or not isinstance(vertices, list):
        raise ValueError("mesh_data must contain a non-empty 'vertices' list")
    if not faces or not isinstance(faces, list):
        raise ValueError("mesh_data must contain a non-empty 'faces' list")

    # Validate vertex format: each must be a list/tuple of 3 numbers
    for i, v in enumerate(vertices):
        if not isinstance(v, (list, tuple)) or len(v) != 3:
            raise ValueError(f"Vertex {i} must be [x, y, z], got {v}")

    # Validate face format: each must reference valid vertex indices
    n_verts = len(vertices)
    for i, face in enumerate(faces):
        if not isinstance(face, (list, tuple)) or len(face) < 3:
            raise ValueError(f"Face {i} must have at least 3 vertex indices")
        for idx in face:
            if not isinstance(idx, int) or idx < 0 or idx >= n_verts:
                raise ValueError(
                    f"Face {i} has invalid vertex index {idx} "
                    f"(valid range: 0-{n_verts - 1})"
                )

    # Build USDA text
    mesh_name = mesh_data.get("name", "ExportedMesh")

    # Format vertex positions
    vert_strs = [f"({v[0]}, {v[1]}, {v[2]})" for v in vertices]
    points_str = ", ".join(vert_strs)

    # Face vertex counts and indices
    face_counts = [len(f) for f in faces]
    face_counts_str = ", ".join(str(c) for c in face_counts)

    face_indices = []
    for face in faces:
        face_indices.extend(face)
    face_indices_str = ", ".join(str(idx) for idx in face_indices)

    usda = f'''#usda 1.0
(
    defaultPrim = "{mesh_name}"
    upAxis = "Y"
    metersPerUnit = 0.01
)

def Xform "{mesh_name}" (
    kind = "component"
)
{{
    def Mesh "{mesh_name}_Mesh"
    {{
        int[] faceVertexCounts = [{face_counts_str}]
        int[] faceVertexIndices = [{face_indices_str}]
        point3f[] points = [{points_str}]
        uniform token subdivisionScheme = "none"
    }}
}}
'''
    return usda


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_export_usdz tool."""

    @mcp.tool(
        name="adobe_ai_export_usdz",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_export_usdz(params: AiExportUsdzInput) -> str:
        """Export 3D mesh data as USDZ.

        Actions:
        - export: generate USDA text from mesh data, or convert OBJ via trimesh
        - status: check availability of 3D export features
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "trimesh_available": _trimesh is not None,
                "pure_python_usda": True,
                "supported_actions": ["export", "status"],
            }, indent=2)

        # ── export ──────────────────────────────────────────────────
        if action == "export":
            # Route 1: Pure Python USDA from mesh_data
            if params.mesh_data:
                try:
                    usda_text = generate_usda_text(params.mesh_data)
                except ValueError as exc:
                    return json.dumps({"error": str(exc)})

                out_path = params.output_path or f"/tmp/ai_export/{params.character_name}.usda"
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w") as f:
                    f.write(usda_text)

                return json.dumps({
                    "action": "export",
                    "format": "usda",
                    "output_path": out_path,
                    "vertex_count": len(params.mesh_data["vertices"]),
                    "face_count": len(params.mesh_data["faces"]),
                }, indent=2)

            # Route 2: OBJ → USDZ via trimesh (optional dep)
            if params.obj_path:
                if _trimesh is None:
                    return json.dumps({
                        "error": "trimesh is required for OBJ→USDZ conversion",
                        "hint": "pip install trimesh",
                    })

                if not os.path.exists(params.obj_path):
                    return json.dumps({
                        "error": f"OBJ file not found: {params.obj_path}",
                    })

                mesh = _trimesh.load(params.obj_path)
                out_path = params.output_path or f"/tmp/ai_export/{params.character_name}.usdz"
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                mesh.export(out_path, file_type="usdz")

                return json.dumps({
                    "action": "export",
                    "format": "usdz",
                    "output_path": out_path,
                    "source": params.obj_path,
                }, indent=2)

            return json.dumps({
                "error": "Provide either mesh_data or obj_path for export",
            })

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["export", "status"],
        })
