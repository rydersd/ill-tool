"""End-to-end 3D-to-2D spatial drawing pipeline.

Chains: reference image -> 3D reconstruction -> face grouping ->
2D projection -> contour placement -> scoring.

This is the orchestrator for the spatial AI drawing approach.
It replaces the direct-coordinate method (which scored 0-0.3/10)
with a geometry-driven pipeline that projects real 3D surfaces.

Actions:
- status: Report pipeline stage availability (TRELLIS, trimesh, etc.)
- preview: Load mesh -> group -> project -> classify (JSON only, no Illustrator)
- run_from_mesh: Like preview but also places paths in Illustrator
- run_pipeline: Full end-to-end from reference image through reconstruction
"""

import json
import os
import time
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.reconstruct_3d_trellis import (
    validate_trellis_output,
    estimate_mesh_complexity,
    ML_AVAILABLE as TRELLIS_ML_AVAILABLE,
    _reconstruct,
)

# Check if TRELLIS pipeline itself is available (not just torch/trimesh)
try:
    from adobe_mcp.apps.illustrator.reconstruct_3d_trellis import (
        TRELLIS_AVAILABLE,
    )
except ImportError:
    TRELLIS_AVAILABLE = False

from adobe_mcp.apps.illustrator.mesh_face_grouper import (
    load_mesh_from_obj,
    group_faces_by_normal,
    extract_group_boundary,
    project_group_boundaries,
    classify_face_groups,
    TRIMESH_AVAILABLE,
)
from adobe_mcp.apps.illustrator.contour_to_path import _from_face_group_boundary


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class SpatialPipelineInput(BaseModel):
    """Control the 3D-to-2D spatial drawing pipeline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="status",
        description=(
            "Action: run_pipeline, run_from_mesh, preview, status. "
            "run_pipeline = full end-to-end from image. "
            "run_from_mesh = skip reconstruction, use existing OBJ. "
            "preview = JSON-only preview (no Illustrator interaction). "
            "status = report available pipeline stages."
        ),
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Path to reference image (required for run_pipeline)",
    )
    mesh_path: Optional[str] = Field(
        default=None,
        description="Path to OBJ mesh file (required for run_from_mesh/preview, optional for run_pipeline)",
    )
    layer_name: str = Field(
        default="3D Pipeline",
        description="Illustrator layer name for output paths",
    )
    angle_threshold: float = Field(
        default=15.0,
        description="Face grouping angle threshold in degrees",
    )
    max_groups: int = Field(
        default=12,
        description="Maximum face groups before hierarchy merge",
    )
    camera_yaw: float = Field(
        default=0.0,
        description="Camera yaw angle in degrees for 2D projection",
    )
    camera_pitch: float = Field(
        default=0.0,
        description="Camera pitch angle in degrees for 2D projection",
    )
    resolution: int = Field(
        default=512,
        description="TRELLIS reconstruction resolution (256, 384, or 512)",
    )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def _pipeline_status() -> dict:
    """Report which pipeline stages are available."""
    return {
        "pipeline": "spatial_3d_to_2d",
        "description": (
            "End-to-end 3D-to-2D spatial drawing pipeline: "
            "reference image -> 3D reconstruction -> face grouping -> "
            "2D projection -> contour placement"
        ),
        "stages": {
            "reconstruction": {
                "available": TRELLIS_ML_AVAILABLE,
                "trellis_available": TRELLIS_AVAILABLE,
                "description": "TRELLIS.2 single-image 3D reconstruction",
            },
            "face_grouping": {
                "available": True,  # Pure Python, always available
                "trimesh_available": TRIMESH_AVAILABLE,
                "description": "Group mesh faces by normal direction",
            },
            "projection": {
                "available": True,  # Pure Python, always available
                "description": "Project 3D face group boundaries to 2D contours",
            },
            "path_placement": {
                "available": True,  # Requires Illustrator at runtime
                "description": "Place 2D contours as Illustrator paths",
            },
        },
        "available_actions": _available_actions(),
    }


def _available_actions() -> list[str]:
    """Return list of actions that can run given current dependencies."""
    actions = ["status", "preview", "run_from_mesh"]
    if TRELLIS_ML_AVAILABLE and TRELLIS_AVAILABLE:
        actions.append("run_pipeline")
    return actions


def _preview_mesh(
    mesh_path: str,
    angle_threshold: float,
    max_groups: int,
    camera_yaw: float,
    camera_pitch: float,
) -> dict:
    """Load mesh, group faces, project to 2D, classify -- return JSON.

    This is the core pipeline logic shared by preview and run_from_mesh.
    No Illustrator interaction.

    Args:
        mesh_path: Path to OBJ mesh file.
        angle_threshold: Angle threshold for face grouping.
        max_groups: Maximum number of face groups.
        camera_yaw: Camera yaw for projection.
        camera_pitch: Camera pitch for projection.

    Returns:
        Dict with groups, classification, contours, and metadata.
        Contains "error" key on failure.
    """
    if not mesh_path:
        return {"error": "mesh_path is required"}

    if not os.path.isfile(mesh_path):
        return {"error": f"Mesh file not found: {mesh_path}"}

    # Load mesh
    try:
        vertices, faces = load_mesh_from_obj(mesh_path)
    except Exception as exc:
        return {"error": f"Failed to load mesh: {exc}"}

    if len(faces) == 0:
        return {
            "error": "Mesh has no faces",
            "vertex_count": len(vertices),
            "face_count": 0,
        }

    # Group faces by normal direction
    groups = group_faces_by_normal(
        vertices, faces, angle_threshold, max_groups
    )

    # Project boundaries to 2D
    contours = project_group_boundaries(
        groups, vertices, faces, camera_yaw, camera_pitch
    )

    # Classify groups (top/front/side/etc)
    labels = classify_face_groups(groups)

    # Build result with contours flattened to serializable format
    group_results = []
    for i, group in enumerate(groups):
        group_contours = contours[i] if i < len(contours) else []
        # Use the first (largest) boundary loop as the primary contour
        primary_contour = []
        if group_contours:
            primary_contour = [list(pt) for pt in group_contours[0]]

        group_results.append({
            "group_id": group["group_id"],
            "label": labels.get(group["group_id"], "unknown"),
            "face_count": group["face_count"],
            "contour": primary_contour,
            "boundary_count": len(group_contours),
        })

    return {
        "groups": group_results,
        "total_groups": len(groups),
        "classification": labels,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "camera_yaw": camera_yaw,
        "camera_pitch": camera_pitch,
        "angle_threshold": angle_threshold,
    }


def _build_path_placement_jsx(
    shape_dicts: list[dict],
    layer_name: str,
) -> str:
    """Build JSX to place multiple paths from shape dicts in Illustrator.

    Each shape dict has "name" and "approx_points" keys. Creates all paths
    on the specified layer.

    Args:
        shape_dicts: List of shape dicts from _from_face_group_boundary.
        layer_name: Illustrator layer name.

    Returns:
        JSX string for execution.
    """
    from adobe_mcp.jsx.templates import escape_jsx_string

    escaped_layer = escape_jsx_string(layer_name)

    # Build points arrays for all shapes
    paths_code = []
    for shape in shape_dicts:
        points = shape.get("approx_points", [])
        if not points:
            continue
        name = escape_jsx_string(shape.get("name", "group"))
        points_json = json.dumps(points)
        paths_code.append(f"""
        (function() {{
            var path = layer.pathItems.add();
            path.setEntirePath({points_json});
            path.closed = true;
            path.filled = false;
            path.stroked = true;
            path.strokeWidth = 1.5;
            var black = new RGBColor();
            black.red = 0; black.green = 0; black.blue = 0;
            path.strokeColor = black;
            path.name = "{name}";
            placed.push({{ name: path.name, points: path.pathPoints.length }});
        }})();
""")

    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i];
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}
    doc.activeLayer = layer;

    var placed = [];
    {"".join(paths_code)}
    return JSON.stringify({{ paths_placed: placed.length, paths: placed, layer: layer.name }});
}})();
"""
    return jsx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_spatial_pipeline tool."""

    @mcp.tool(
        name="adobe_ai_spatial_pipeline",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_spatial_pipeline(
        params: SpatialPipelineInput,
    ) -> str:
        """End-to-end 3D-to-2D spatial drawing pipeline.

        Chains: reference image -> 3D reconstruction -> face grouping ->
        2D projection -> contour placement in Illustrator.

        Actions:
        - status: Report pipeline stage availability
        - preview: Load mesh -> group -> project -> classify (JSON only)
        - run_from_mesh: Preview + place paths in Illustrator
        - run_pipeline: Full end-to-end from reference image

        This replaces direct coordinate placement (scored 0-0.3/10) with
        a geometry-driven pipeline that projects real 3D surfaces.
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        # --- status ---
        if action == "status":
            return json.dumps(_pipeline_status(), indent=2)

        # --- preview (JSON only, no Illustrator) ---
        elif action == "preview":
            if not params.mesh_path:
                return json.dumps({"error": "mesh_path is required for preview action"})
            result = _preview_mesh(
                params.mesh_path,
                params.angle_threshold,
                params.max_groups,
                params.camera_yaw,
                params.camera_pitch,
            )
            return json.dumps(result, indent=2)

        # --- run_from_mesh (preview + Illustrator placement) ---
        elif action == "run_from_mesh":
            if not params.mesh_path:
                return json.dumps({"error": "mesh_path is required for run_from_mesh action"})

            # Run preview to get group data
            preview = _preview_mesh(
                params.mesh_path,
                params.angle_threshold,
                params.max_groups,
                params.camera_yaw,
                params.camera_pitch,
            )
            if "error" in preview:
                return json.dumps(preview, indent=2)

            # Query artboard dimensions from Illustrator
            jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({width: ab[2] - ab[0], height: ab[1] - ab[3]});
})();
"""
            ab_result = await _async_run_jsx("illustrator", jsx_info)
            if not ab_result["success"]:
                return json.dumps({
                    "error": f"Could not query artboard: {ab_result['stderr']}",
                    "preview": preview,
                })

            try:
                artboard_dims = json.loads(ab_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({
                    "error": f"Bad artboard response: {ab_result['stdout']}",
                    "preview": preview,
                })

            # Convert each group contour to shape dict via adapter
            shape_dicts = []
            for group in preview["groups"]:
                if not group["contour"]:
                    continue
                # Convert contour [[x,y], ...] back to list of tuples
                boundary = [(pt[0], pt[1]) for pt in group["contour"]]
                shape = _from_face_group_boundary(
                    boundary, group["label"], artboard_dims
                )
                if shape["approx_points"]:
                    shape_dicts.append(shape)

            if not shape_dicts:
                return json.dumps({
                    "error": "No valid contours to place",
                    "preview": preview,
                })

            # Build and execute JSX to place all paths
            jsx = _build_path_placement_jsx(shape_dicts, params.layer_name)
            place_result = await _async_run_jsx("illustrator", jsx)

            if not place_result["success"]:
                return json.dumps({
                    "error": f"Path placement failed: {place_result['stderr']}",
                    "shape_dicts": shape_dicts,
                    "preview": preview,
                })

            try:
                placed = json.loads(place_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                placed = {"raw": place_result["stdout"]}

            return json.dumps({
                "groups_placed": len(shape_dicts),
                "paths_created": placed.get("paths_placed", 0),
                "layer_name": placed.get("layer", params.layer_name),
                "classification": preview["classification"],
                "total_groups": preview["total_groups"],
                "vertex_count": preview["vertex_count"],
                "face_count": preview["face_count"],
            }, indent=2)

        # --- run_pipeline (full end-to-end from image) ---
        elif action == "run_pipeline":
            if not params.image_path:
                return json.dumps({
                    "error": "image_path is required for run_pipeline action",
                })

            if not TRELLIS_ML_AVAILABLE:
                return json.dumps({
                    "error": (
                        "ML dependencies not installed. Cannot run full pipeline. "
                        "Use run_from_mesh with a pre-existing OBJ mesh instead."
                    ),
                    "install_hint": 'Install with: uv pip install -e ".[ml-trellis]"',
                })

            if not TRELLIS_AVAILABLE:
                return json.dumps({
                    "error": (
                        "TRELLIS.2 not installed. Cannot run full pipeline. "
                        "Use run_from_mesh with a pre-existing OBJ mesh instead."
                    ),
                    "install_hint": (
                        "Install from: https://github.com/microsoft/TRELLIS\n"
                        "Clone the repo and add to PYTHONPATH."
                    ),
                })

            if not os.path.isfile(params.image_path):
                return json.dumps({
                    "error": f"Image file not found: {params.image_path}",
                })

            # Step 1: Reconstruct 3D mesh from image
            mesh_path = params.mesh_path  # Use provided mesh path or generate
            reconstruction_meta = None

            if not mesh_path:
                recon_result = _reconstruct(
                    params.image_path,
                    output_path=None,
                    resolution=params.resolution,
                    fmt="obj",
                )
                if "error" in recon_result:
                    return json.dumps({
                        "error": f"Reconstruction failed: {recon_result['error']}",
                        "stage": "reconstruction",
                    })
                mesh_path = recon_result["mesh_path"]
                reconstruction_meta = {
                    "vertex_count": recon_result["vertex_count"],
                    "face_count": recon_result["face_count"],
                    "reconstruction_time_seconds": recon_result.get(
                        "reconstruction_time_seconds"
                    ),
                }

            # Step 2: Run the same logic as run_from_mesh
            # Re-use the action handler by calling preview + placement
            preview = _preview_mesh(
                mesh_path,
                params.angle_threshold,
                params.max_groups,
                params.camera_yaw,
                params.camera_pitch,
            )
            if "error" in preview:
                return json.dumps({
                    **preview,
                    "stage": "face_grouping",
                    "reconstruction": reconstruction_meta,
                }, indent=2)

            # Query artboard dimensions from Illustrator
            jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({width: ab[2] - ab[0], height: ab[1] - ab[3]});
})();
"""
            ab_result = await _async_run_jsx("illustrator", jsx_info)
            if not ab_result["success"]:
                return json.dumps({
                    "error": f"Could not query artboard: {ab_result['stderr']}",
                    "preview": preview,
                    "reconstruction": reconstruction_meta,
                })

            try:
                artboard_dims = json.loads(ab_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({
                    "error": f"Bad artboard response: {ab_result['stdout']}",
                    "preview": preview,
                    "reconstruction": reconstruction_meta,
                })

            # Convert contours to shape dicts
            shape_dicts = []
            for group in preview["groups"]:
                if not group["contour"]:
                    continue
                boundary = [(pt[0], pt[1]) for pt in group["contour"]]
                shape = _from_face_group_boundary(
                    boundary, group["label"], artboard_dims
                )
                if shape["approx_points"]:
                    shape_dicts.append(shape)

            if not shape_dicts:
                return json.dumps({
                    "error": "No valid contours to place after reconstruction",
                    "preview": preview,
                    "reconstruction": reconstruction_meta,
                })

            # Place paths in Illustrator
            jsx = _build_path_placement_jsx(shape_dicts, params.layer_name)
            place_result = await _async_run_jsx("illustrator", jsx)

            if not place_result["success"]:
                return json.dumps({
                    "error": f"Path placement failed: {place_result['stderr']}",
                    "shape_dicts_count": len(shape_dicts),
                    "preview": preview,
                    "reconstruction": reconstruction_meta,
                })

            try:
                placed = json.loads(place_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                placed = {"raw": place_result["stdout"]}

            return json.dumps({
                "groups_placed": len(shape_dicts),
                "paths_created": placed.get("paths_placed", 0),
                "layer_name": placed.get("layer", params.layer_name),
                "classification": preview["classification"],
                "total_groups": preview["total_groups"],
                "reconstruction": reconstruction_meta,
                "mesh_path": mesh_path,
                "vertex_count": preview["vertex_count"],
                "face_count": preview["face_count"],
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "preview", "run_from_mesh", "run_pipeline"],
            })
