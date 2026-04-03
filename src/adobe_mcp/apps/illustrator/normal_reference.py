"""Generate shadow-free reference renderings from predicted surface normals.

Chains two existing modules:
1. ml_backends.normal_estimator — predicts surface normals from an image (DSINE)
2. normal_renderings — generates 5 shadow-free renderings from a normal map

Actions:
- status: Report which normal estimation backends + rendering functions are available.
- generate: Predict normals, generate renderings, save PNGs.  No Illustrator.
- place: Run generate (if needed), then place renderings as locked hidden
  reference layers in the active Illustrator document.
"""

import json
import os
import time
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
    estimate_normals,
    ml_status,
)
from adobe_mcp.apps.illustrator.normal_renderings import (
    curvature_map,
    depth_discontinuities,
    flat_planes,
    form_lines,
    relit_reference,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = "/tmp/ai_normal_ref"

# Mapping from user-facing name to rendering function + description
RENDERING_REGISTRY = {
    "flat_planes": {
        "description": "K-means clustering of normal directions — reveals major structural planes",
        "needs_image": False,
    },
    "form_lines": {
        "description": "Sobel edge detection on normal channels — pure form edges, no shadows",
        "needs_image": False,
    },
    "curvature": {
        "description": "Gaussian curvature approximation — convex/concave surface structure",
        "needs_image": False,
    },
    "relit": {
        "description": "Synthetic relighting via dot(normal, light) — shadow-free clean reference",
        "needs_image": True,
    },
    "depth_edges": {
        "description": "Depth/occlusion boundary detection from normal discontinuities",
        "needs_image": False,
    },
}

# Human-readable display names for layer titles
DISPLAY_NAMES = {
    "flat_planes": "Flat Planes",
    "form_lines": "Form Lines",
    "curvature": "Curvature",
    "relit": "Relit",
    "depth_edges": "Depth Edges",
}

ALL_RENDERING_NAMES = list(RENDERING_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class NormalReferenceInput(BaseModel):
    """Control the normal-reference rendering pipeline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="status",
        description=(
            "Action: status | generate | place. "
            "status = report available backends and renderings. "
            "generate = predict normals + save rendering PNGs (no Illustrator). "
            "place = generate + place as locked hidden reference layers."
        ),
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Absolute path to reference image (PNG/JPG). Required for generate/place.",
    )
    model: str = Field(
        default="auto",
        description="Normal estimation backend: auto | dsine | marigold.",
    )
    renderings: list[str] = Field(
        default=ALL_RENDERING_NAMES,
        description=(
            "Which renderings to generate. Options: "
            "flat_planes, form_lines, curvature, relit, depth_edges."
        ),
    )
    k_planes: int = Field(
        default=6,
        description="Number of plane clusters for flat_planes rendering.",
        ge=2,
        le=20,
    )
    light_dir: list[float] = Field(
        default=[0.0, 0.0, 1.0],
        description="Light direction [x, y, z] for relit rendering.",
    )
    layer_prefix: str = Field(
        default="Normal",
        description="Prefix for layer names in Illustrator (e.g. 'Normal: Flat Planes').",
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _status() -> dict:
    """Report which backends and rendering functions are available."""
    backends = ml_status()

    rendering_info = {}
    for name, info in RENDERING_REGISTRY.items():
        rendering_info[name] = {
            "available": True,  # Pure numpy/OpenCV, always available
            "description": info["description"],
            "needs_image": info["needs_image"],
        }

    return {
        "pipeline": "normal_reference",
        "description": (
            "Generate shadow-free reference renderings from predicted surface normals. "
            "Predicts normals from a single image, then generates multiple "
            "visualization layers useful for constructive drawing."
        ),
        "backends": backends,
        "renderings": rendering_info,
        "available_actions": ["status", "generate", "place"],
        "output_dir": OUTPUT_DIR,
    }


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def _generate(
    image_path: str,
    model: str = "auto",
    renderings: list[str] | None = None,
    k_planes: int = 6,
    light_dir: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> dict:
    """Predict normals from image, generate requested renderings, save as PNGs.

    Args:
        image_path: Absolute path to input image.
        model: Normal estimation backend.
        renderings: List of rendering names to generate (default: all).
        k_planes: Number of clusters for flat_planes.
        light_dir: Light direction for relit rendering.

    Returns:
        Dict with normal_map_path, rendering_paths, metadata, timings.
        Contains "error" key on failure.
    """
    if not image_path:
        return {"error": "image_path is required for generate action."}

    if not os.path.isfile(image_path):
        return {"error": f"Image file not found: {image_path}"}

    if renderings is None:
        renderings = ALL_RENDERING_NAMES

    # Validate rendering names
    invalid = [r for r in renderings if r not in RENDERING_REGISTRY]
    if invalid:
        return {
            "error": f"Unknown rendering(s): {invalid}",
            "valid_renderings": ALL_RENDERING_NAMES,
        }

    t_start = time.time()

    # --- Step 1: Estimate normals ---
    t_normals_start = time.time()
    result = estimate_normals(image_path, model=model)
    t_normals = time.time() - t_normals_start

    if "error" in result:
        return result  # Pass through error + install hints

    normal_map = result["normal_map"]  # HxWx3 float32
    h, w = normal_map.shape[:2]

    # --- Step 2: Load original image for renderings that need it ---
    original_image = None
    if any(RENDERING_REGISTRY[r]["needs_image"] for r in renderings):
        original_image = cv2.imread(image_path)
        if original_image is None:
            return {"error": f"Failed to read image for relighting: {image_path}"}
        # Resize to match normal map if needed
        if original_image.shape[:2] != (h, w):
            original_image = cv2.resize(original_image, (w, h))

    # --- Step 3: Create output directory ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Save the normal map itself as a PNG (useful for debugging)
    # Remap from [-1, 1] to [0, 255]
    normal_vis = ((normal_map + 1.0) * 0.5 * 255.0).clip(0, 255).astype(np.uint8)
    normal_map_path = os.path.join(OUTPUT_DIR, "normal_map.png")
    cv2.imwrite(normal_map_path, normal_vis)

    # --- Step 4: Generate each requested rendering ---
    rendering_paths = {}
    rendering_timings = {}

    for name in renderings:
        t_r = time.time()

        if name == "flat_planes":
            img = flat_planes(normal_map, k=k_planes)
        elif name == "form_lines":
            img = form_lines(normal_map)
            # Convert single-channel to 3-channel for consistent PNG output
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif name == "curvature":
            curv = curvature_map(normal_map)
            # Visualize: normalize to [0, 255], signed -> diverging colormap
            abs_max = max(np.abs(curv).max(), 1e-8)
            normalized = ((curv / abs_max) + 1.0) * 0.5  # [0, 1]
            gray = (normalized * 255).clip(0, 255).astype(np.uint8)
            img = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
        elif name == "relit":
            light_tuple = tuple(light_dir[:3]) if len(light_dir) >= 3 else (0.0, 0.0, 1.0)
            img = relit_reference(original_image, normal_map, light_dir=light_tuple)
        elif name == "depth_edges":
            img = depth_discontinuities(normal_map)
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        out_path = os.path.join(OUTPUT_DIR, f"{name}.png")
        cv2.imwrite(out_path, img)
        rendering_paths[name] = out_path
        rendering_timings[name] = round(time.time() - t_r, 3)

    t_total = round(time.time() - t_start, 3)

    return {
        "normal_map_path": normal_map_path,
        "rendering_paths": rendering_paths,
        "renderings_generated": list(rendering_paths.keys()),
        "normal_estimation": {
            "model": result.get("model", model),
            "device": result.get("device", "unknown"),
            "time_seconds": round(t_normals, 3),
            "height": h,
            "width": w,
        },
        "timings": {
            "normal_estimation_seconds": round(t_normals, 3),
            "rendering_seconds": rendering_timings,
            "total_seconds": t_total,
        },
    }


# ---------------------------------------------------------------------------
# JSX builder for placing reference layers
# ---------------------------------------------------------------------------


def _build_place_jsx(
    rendering_paths: dict[str, str],
    layer_prefix: str,
) -> str:
    """Build JSX to place rendering PNGs as locked, hidden reference layers.

    Each rendering gets its own layer named "{prefix}: {Display Name}".
    The layer is placed at the bottom of the stack, locked, and hidden.

    Args:
        rendering_paths: Mapping of rendering name to PNG file path.
        layer_prefix: Prefix for layer names.

    Returns:
        JSX string for execution in Illustrator.
    """
    from adobe_mcp.jsx.templates import escape_jsx_string

    escaped_prefix = escape_jsx_string(layer_prefix)

    # Build per-rendering placement blocks
    place_blocks = []
    for name, path in rendering_paths.items():
        display_name = DISPLAY_NAMES.get(name, name)
        escaped_path = escape_jsx_string(path)
        layer_name = f"{escaped_prefix}: {display_name}"

        place_blocks.append(f"""
        (function() {{
            var layerName = "{layer_name}";
            var filePath = "{escaped_path}";

            // Find or create the layer
            var lyr = null;
            for (var i = 0; i < doc.layers.length; i++) {{
                if (doc.layers[i].name === layerName) {{
                    lyr = doc.layers[i];
                    break;
                }}
            }}
            if (!lyr) {{
                lyr = doc.layers.add();
                lyr.name = layerName;
            }}

            // Unlock and clear existing items
            lyr.locked = false;
            lyr.visible = true;
            while (lyr.pageItems.length > 0) {{
                lyr.pageItems[0].remove();
            }}

            // Move layer to bottom of stack
            if (doc.layers.length > 1) {{
                lyr.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
            }}

            // Place image
            doc.activeLayer = lyr;
            var placed = lyr.placedItems.add();
            placed.file = new File(filePath);
            placed.embed();

            // Re-acquire after embed
            var imgItem = lyr.pageItems[lyr.pageItems.length - 1];

            // Scale to fit artboard
            var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
            var abW = abRect[2] - abRect[0];
            var abH = abRect[1] - abRect[3];
            var imgW = imgItem.width;
            var imgH = imgItem.height;
            var scale = Math.min(abW / imgW, abH / imgH) * 100;
            imgItem.resize(scale, scale);

            // Center on artboard
            imgItem.position = [
                abRect[0] + (abW - imgItem.width) / 2,
                abRect[1] - (abH - imgItem.height) / 2
            ];

            // Lock and hide the layer
            lyr.opacity = 50;
            lyr.locked = true;
            lyr.visible = false;

            placed_layers.push({{
                name: layerName,
                scale: Math.round(scale * 100) / 100,
                locked: true,
                visible: false
            }});
        }})();
""")

    jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var placed_layers = [];

    {"".join(place_blocks)}

    return JSON.stringify({{
        layers_placed: placed_layers.length,
        layers: placed_layers
    }});
}})();
"""
    return jsx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_normal_reference tool."""

    @mcp.tool(
        name="adobe_ai_normal_reference",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_normal_reference(
        params: NormalReferenceInput,
    ) -> str:
        """Generate shadow-free reference renderings from predicted surface normals.

        Predicts per-pixel surface normals from a reference image, then generates
        multiple visualization layers useful for constructive drawing:
        - flat_planes: K-means clustered plane regions
        - form_lines: Pure form edges (no shadow contamination)
        - curvature: Gaussian curvature heatmap (convex/concave)
        - relit: Shadow-free relighting under custom light direction
        - depth_edges: Occlusion/depth boundary detection

        Actions:
        - status: Report available ML backends and rendering functions
        - generate: Predict normals + save rendering PNGs to disk
        - place: Generate + place as locked, hidden reference layers in Illustrator
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        # --- status ---
        if action == "status":
            return json.dumps(_status(), indent=2)

        # --- generate ---
        elif action == "generate":
            result = _generate(
                image_path=params.image_path,
                model=params.model,
                renderings=params.renderings,
                k_planes=params.k_planes,
                light_dir=tuple(params.light_dir),
            )
            return json.dumps(result, indent=2)

        # --- place ---
        elif action == "place":
            # Run generate first
            gen_result = _generate(
                image_path=params.image_path,
                model=params.model,
                renderings=params.renderings,
                k_planes=params.k_planes,
                light_dir=tuple(params.light_dir),
            )

            if "error" in gen_result:
                return json.dumps(gen_result, indent=2)

            # Build and execute JSX to place renderings
            jsx = _build_place_jsx(
                gen_result["rendering_paths"],
                params.layer_prefix,
            )
            place_result = await _async_run_jsx("illustrator", jsx, timeout=300)

            if not place_result["success"]:
                return json.dumps({
                    "error": f"Failed to place reference layers: {place_result['stderr']}",
                    "generate_result": gen_result,
                }, indent=2)

            try:
                placed = json.loads(place_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                placed = {"raw": place_result["stdout"]}

            return json.dumps({
                "layers_placed": placed.get("layers_placed", 0),
                "layers": placed.get("layers", []),
                "rendering_paths": gen_result["rendering_paths"],
                "normal_map_path": gen_result["normal_map_path"],
                "normal_estimation": gen_result["normal_estimation"],
                "timings": gen_result["timings"],
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "generate", "place"],
            })
