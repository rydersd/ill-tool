"""TRELLIS.2 single-image 3D reconstruction (optional dependency).

Uses Microsoft TRELLIS.2 (4B params) to reconstruct a 3D mesh from a single
reference image. Handles sharp mechanical features well.

Falls back gracefully when ML dependencies are not installed.
"""

import json
import os
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Graceful ML dependency import
# ---------------------------------------------------------------------------

try:
    import torch
    import trimesh

    # TRELLIS.2 may not be pip-installable -- handle import failure separately
    try:
        from trellis.pipelines import TrellisImageTo3DPipeline

        TRELLIS_AVAILABLE = True
    except ImportError:
        TRELLIS_AVAILABLE = False

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    TRELLIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Module-level model cache (loaded once, reused across calls)
# ---------------------------------------------------------------------------

_cached_pipeline = None


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class ReconstructTrellisInput(BaseModel):
    """Control TRELLIS.2 single-image 3D reconstruction."""

    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, reconstruct, validate",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to input reference image"
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Where to save output mesh (defaults to temp dir)",
    )
    resolution: int = Field(
        default=512,
        description="Reconstruction resolution: 256, 384, or 512",
    )
    format: str = Field(
        default="obj",
        description="Output format: obj or glb",
    )


# ---------------------------------------------------------------------------
# Pure Python helpers (always available)
# ---------------------------------------------------------------------------


def validate_trellis_output(mesh_path: str) -> dict:
    """Check that a mesh file is valid and return structural metadata.

    Performs format-specific validation:
    - OBJ: counts vertex ('v ') and face ('f ') lines
    - GLB: checks for glTF magic bytes (0x46546C67)

    Args:
        mesh_path: Path to the mesh file (OBJ or GLB).

    Returns:
        Dict with keys: valid, format, vertex_count (OBJ), face_count (OBJ),
        file_size_bytes, and error (if invalid).
    """
    if not mesh_path:
        return {"valid": False, "error": "No path provided"}

    if not os.path.isfile(mesh_path):
        return {"valid": False, "error": f"File not found: {mesh_path}"}

    file_size = os.path.getsize(mesh_path)
    if file_size == 0:
        return {"valid": False, "error": "File is empty"}

    ext = os.path.splitext(mesh_path)[1].lower()
    result = {
        "valid": True,
        "path": mesh_path,
        "file_size_bytes": file_size,
        "format": ext.lstrip("."),
    }

    if ext == ".obj":
        vertex_count = 0
        face_count = 0
        try:
            with open(mesh_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("v "):
                        vertex_count += 1
                    elif stripped.startswith("f "):
                        face_count += 1
        except Exception as exc:
            return {"valid": False, "error": f"Cannot read OBJ: {exc}"}

        if vertex_count == 0:
            return {"valid": False, "error": "OBJ file has no vertices"}

        result["vertex_count"] = vertex_count
        result["face_count"] = face_count

    elif ext == ".glb":
        try:
            with open(mesh_path, "rb") as f:
                magic = f.read(4)
            if magic != b"glTF":
                return {
                    "valid": False,
                    "error": "Not a valid GLB file (missing glTF magic)",
                }
        except Exception as exc:
            return {"valid": False, "error": f"Cannot read GLB: {exc}"}

        result["has_gltf_magic"] = True

    else:
        return {
            "valid": False,
            "error": f"Unsupported format: {ext}. Expected .obj or .glb",
        }

    return result


def estimate_mesh_complexity(mesh_path: str) -> dict:
    """Analyze mesh quality by parsing the OBJ file directly.

    Computes vertex count, face count, bounding box (from 'v ' lines),
    and assigns a quality tier:
    - high:    >= 50,000 vertices
    - medium:  >= 10,000 vertices
    - low:     >=  1,000 vertices
    - preview: <  1,000 vertices

    Args:
        mesh_path: Path to an OBJ mesh file.

    Returns:
        Dict with vertex_count, face_count, quality_tier, bounding_box.
    """
    if not mesh_path or not os.path.isfile(mesh_path):
        return {"error": f"File not found: {mesh_path}"}

    vertex_count = 0
    face_count = 0
    # Track bounding box min/max across all vertices
    x_min = y_min = z_min = float("inf")
    x_max = y_max = z_max = float("-inf")

    try:
        with open(mesh_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("v "):
                    parts = stripped.split()
                    if len(parts) >= 4:
                        x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                        x_min, x_max = min(x_min, x), max(x_max, x)
                        y_min, y_max = min(y_min, y), max(y_max, y)
                        z_min, z_max = min(z_min, z), max(z_max, z)
                        vertex_count += 1
                elif stripped.startswith("f "):
                    face_count += 1
    except Exception as exc:
        return {"error": f"Cannot read OBJ: {exc}"}

    if vertex_count == 0:
        return {"error": "OBJ file has no vertices"}

    # Assign quality tier based on vertex count
    if vertex_count >= 50_000:
        quality_tier = "high"
    elif vertex_count >= 10_000:
        quality_tier = "medium"
    elif vertex_count >= 1_000:
        quality_tier = "low"
    else:
        quality_tier = "preview"

    return {
        "vertex_count": vertex_count,
        "face_count": face_count,
        "quality_tier": quality_tier,
        "bounding_box": {
            "min": [x_min, y_min, z_min],
            "max": [x_max, y_max, z_max],
            "size": [x_max - x_min, y_max - y_min, z_max - z_min],
        },
    }


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------


def _ml_status() -> dict:
    """Return availability status for TRELLIS.2 reconstruction."""
    status = {
        "ml_available": ML_AVAILABLE,
        "trellis_available": TRELLIS_AVAILABLE,
        "tool": "TRELLIS.2 single-image 3D reconstruction",
        "supported_formats": ["obj", "glb"],
        "supported_resolutions": [256, 384, 512],
    }
    if ML_AVAILABLE:
        status["torch_version"] = torch.__version__
        if torch.cuda.is_available():
            status["device"] = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            status["device"] = "mps"
        else:
            status["device"] = "cpu"
        status["model_loaded"] = _cached_pipeline is not None
    else:
        status["install_hint"] = (
            "Install ML dependencies with: uv pip install -e \".[ml-trellis]\""
        )
        status["required_packages"] = ["torch", "trimesh"]
        status["device"] = "unavailable"

    if not TRELLIS_AVAILABLE and ML_AVAILABLE:
        status["trellis_install_hint"] = (
            "TRELLIS.2 not installed. Install from: "
            "https://github.com/microsoft/TRELLIS\n"
            "Clone the repo and add to PYTHONPATH, or pip install "
            "trellis-3d if available."
        )

    return status


# ---------------------------------------------------------------------------
# ML reconstruction (only when dependencies available)
# ---------------------------------------------------------------------------


def _reconstruct(
    image_path: str,
    output_path: Optional[str],
    resolution: int,
    fmt: str,
) -> dict:
    """Run TRELLIS.2 reconstruction on a reference image.

    Requires ML dependencies (torch, trimesh) and the TRELLIS.2 package.

    Steps:
    1. Load image, optionally remove background (via rembg if available)
    2. Initialize TRELLIS pipeline (cached after first load)
    3. Run reconstruction at the specified resolution
    4. Extract mesh (Flexicubes first, marching cubes fallback)
    5. Save as OBJ or GLB via trimesh
    6. Return metadata: path, vertex/face counts, bounding box, timing

    Args:
        image_path: Path to the reference image.
        output_path: Where to save the mesh. Defaults to temp directory.
        resolution: Reconstruction resolution (256, 384, or 512).
        fmt: Output format ('obj' or 'glb').

    Returns:
        Dict with mesh_path, vertex_count, face_count, bounding_box,
        reconstruction_time_seconds, device_used -- or error dict.
    """
    if not ML_AVAILABLE:
        return {
            "error": "ML dependencies not installed. Cannot reconstruct.",
            "install_hint": "Install with: uv pip install -e \".[ml-trellis]\"",
            "required_packages": ["torch", "trimesh"],
        }

    if not TRELLIS_AVAILABLE:
        return {
            "error": (
                "TRELLIS.2 not installed. Install from: "
                "https://github.com/microsoft/TRELLIS\n"
                "Clone the repo and add to PYTHONPATH, or pip install "
                "trellis-3d if available."
            ),
        }

    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    if fmt not in ("obj", "glb"):
        return {"error": f"Unsupported format: {fmt}. Use 'obj' or 'glb'."}

    if resolution not in (256, 384, 512):
        return {
            "error": f"Unsupported resolution: {resolution}. Use 256, 384, or 512."
        }

    try:
        from PIL import Image

        t0 = time.time()

        # --- 1. Load image and optionally remove background ----------------
        img = Image.open(image_path).convert("RGBA")
        try:
            from rembg import remove as rembg_remove

            img = rembg_remove(img)
        except ImportError:
            pass  # rembg is optional; skip background removal

        # --- 2. Initialize TRELLIS pipeline (cache for reuse) --------------
        global _cached_pipeline
        if _cached_pipeline is None:
            _cached_pipeline = TrellisImageTo3DPipeline.from_pretrained(
                "microsoft/TRELLIS-image-large"
            )
            # Move to best available device
            if torch.cuda.is_available():
                _cached_pipeline = _cached_pipeline.cuda()

        device_used = "cuda" if torch.cuda.is_available() else (
            "mps" if (hasattr(torch.backends, "mps")
                      and torch.backends.mps.is_available())
            else "cpu"
        )

        # --- 3. Run reconstruction ----------------------------------------
        outputs = _cached_pipeline.run(
            img,
            seed=42,
        )

        # --- 4. Extract mesh (Flexicubes preferred, marching cubes fallback)
        try:
            mesh_out = _cached_pipeline.run_flexicubes(
                outputs,
                resolution=resolution,
            )
        except Exception:
            mesh_out = _cached_pipeline.run_marching_cubes(
                outputs,
                resolution=resolution,
            )

        # --- 5. Save via trimesh ------------------------------------------
        if output_path is None:
            import tempfile

            output_dir = tempfile.mkdtemp(prefix="trellis_")
            output_path = os.path.join(output_dir, f"reconstruction.{fmt}")

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # mesh_out is expected to be a trimesh-compatible object or dict
        if isinstance(mesh_out, trimesh.Trimesh):
            mesh = mesh_out
        elif hasattr(mesh_out, "vertices") and hasattr(mesh_out, "faces"):
            mesh = trimesh.Trimesh(
                vertices=mesh_out.vertices,
                faces=mesh_out.faces,
            )
        else:
            # Try extracting from dict-like output
            mesh = trimesh.Trimesh(
                vertices=mesh_out["vertices"],
                faces=mesh_out["faces"],
            )

        mesh.export(output_path)

        t1 = time.time()

        # --- 6. Compute metadata ------------------------------------------
        bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]

        return {
            "mesh_path": output_path,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "bounding_box": {
                "min": bounds[0].tolist(),
                "max": bounds[1].tolist(),
                "size": (bounds[1] - bounds[0]).tolist(),
            },
            "reconstruction_time_seconds": round(t1 - t0, 2),
            "device_used": device_used,
        }

    except Exception as exc:
        return {"error": f"Reconstruction failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_reconstruct_3d_trellis tool."""

    @mcp.tool(
        name="adobe_ai_reconstruct_3d_trellis",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_reconstruct_3d_trellis(
        params: ReconstructTrellisInput,
    ) -> str:
        """TRELLIS.2 single-image 3D reconstruction (4B params).

        Reconstructs a 3D mesh from a single reference image using
        Microsoft TRELLIS.2.  Handles sharp mechanical features well.

        Actions:
        - status: Check ML/TRELLIS dependency availability and device info
        - reconstruct: Generate OBJ/GLB mesh from a reference image
        - validate: Validate an existing mesh file (OBJ or GLB)

        Requires optional dependencies (torch, trimesh, trellis). Install with:
            uv pip install -e ".[ml-trellis]"

        TRELLIS.2 itself may need manual install:
            https://github.com/microsoft/TRELLIS
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_ml_status(), indent=2)

        elif action == "validate":
            if not params.image_path and not params.output_path:
                return json.dumps({
                    "error": "Provide output_path (mesh file) to validate.",
                })
            # Validate the mesh at output_path (or image_path used as mesh path)
            mesh_to_validate = params.output_path or params.image_path
            result = validate_trellis_output(mesh_to_validate)
            if result.get("valid"):
                complexity = estimate_mesh_complexity(mesh_to_validate)
                if "error" not in complexity:
                    result["complexity"] = complexity
            return json.dumps(result, indent=2)

        elif action == "reconstruct":
            if not params.image_path:
                return json.dumps({
                    "error": "image_path is required for reconstruct action.",
                })
            result = _reconstruct(
                params.image_path,
                params.output_path,
                params.resolution,
                params.format,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "reconstruct", "validate"],
            })
