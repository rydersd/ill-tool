"""Generate shadow-free reference renderings from predicted surface normals.

Chains two existing modules:
1. ml_backends.normal_estimator — predicts surface normals from an image (DSINE)
2. normal_renderings — generates 5 shadow-free renderings from a normal map

Actions:
- status: Report which normal estimation backends + rendering functions are available.
- generate: Predict normals, generate renderings, save PNGs.  No Illustrator.
- place: Run generate (if needed), then place renderings as locked hidden
  reference layers in the active Illustrator document.

Integration with existing tools:
- form_lines rendering feeds into adobe_ai_contour_scanner as shadow-free
  edge reference for contour labeling.
- flat_planes rendering feeds into adobe_ai_tonal_analyzer as a clean
  plane-segmentation reference for tonal region analysis.
- Extracted form edges (via form_edge_extract) can be placed as vector
  paths using adobe_ai_contour_to_path.
- The normal map saved by this tool (normal_map.png / normal_map.npy) can
  be reused by adobe_ai_form_edge_extract to skip redundant DSINE inference.
"""

import json
import os
import tempfile
import time
from collections.abc import Sequence
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
    estimate_normals,
    ml_status,
)
from adobe_mcp.apps.illustrator.path_validation import (
    validate_image_path_size,
    validate_image_size,
    validate_safe_path,
)
from adobe_mcp.apps.illustrator.normal_renderings import (
    ambient_occlusion_approx,
    cross_contour_field,
    curvature_line_weight,
    curvature_map,
    depth_discontinuities,
    depth_facing_map,
    flat_planes,
    form_lines,
    form_vs_material_boundaries,
    principal_curvatures,
    relit_reference,
    ridge_valley_map,
    silhouette_contours,
    surface_flow_field,
    surface_type_map,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = os.path.join(tempfile.gettempdir(), f"ai_normal_ref_{os.getuid()}")

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
    "principal_curvatures": {
        "description": "Per-pixel principal curvatures (H, kappa1, kappa2) from shape operator eigendecomposition",
        "needs_image": False,
    },
    "surface_type": {
        "description": "Per-pixel surface classification: flat/convex/concave/saddle/cylindrical",
        "needs_image": False,
    },
    "ridge_valley": {
        "description": "Ridge and valley detection from mean curvature — convex ridges vs concave valleys",
        "needs_image": False,
    },
    "silhouette": {
        "description": "Silhouette contour extraction where surface is near-perpendicular to view",
        "needs_image": False,
    },
    "depth_facing": {
        "description": "Front-facing intensity map from normal z-component — camera-facing = bright",
        "needs_image": False,
    },
    "surface_flow": {
        "description": "Principal curvature direction vectors — shows surface flow field",
        "needs_image": False,
    },
    "ambient_occlusion": {
        "description": "Approximate ambient occlusion from local normal variance — crevice/corner darkness",
        "needs_image": False,
    },
    "form_material_boundaries": {
        "description": "Separate normal discontinuities into form boundaries (geometry) vs material boundaries (paint/decal)",
        "needs_image": False,
    },
    "cross_contours": {
        "description": "Cross-contour streamlines perpendicular to max curvature — returns polylines, not image",
        "needs_image": False,
        "returns_polylines": True,
    },
    "line_weight": {
        "description": "Per-pixel adaptive line weight from curvature + silhouette (0=thin, 1=thick)",
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
    "principal_curvatures": "Principal Curvatures",
    "surface_type": "Surface Type",
    "ridge_valley": "Ridge Valley",
    "silhouette": "Silhouette",
    "depth_facing": "Depth Facing",
    "surface_flow": "Surface Flow",
    "ambient_occlusion": "Ambient Occlusion",
    "form_material_boundaries": "Form Material Boundaries",
    "cross_contours": "Cross Contours",
    "line_weight": "Line Weight",
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
            "flat_planes, form_lines, curvature, relit, depth_edges, "
            "principal_curvatures, surface_type, ridge_valley, silhouette, "
            "depth_facing, surface_flow, ambient_occlusion, "
            "form_material_boundaries, cross_contours, line_weight."
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
        "recommended_next_tools": [
            "adobe_ai_contour_scanner — use form_lines rendering as reference",
            "adobe_ai_tonal_analyzer — use flat_planes rendering as reference",
            "adobe_ai_contour_to_path — place extracted form edges as paths",
        ],
    }


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def _generate(
    image_path: str,
    model: str = "auto",
    renderings: list[str] | None = None,
    k_planes: int = 6,
    light_dir: Sequence[float] = (0.0, 0.0, 1.0),
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

    # Validate path and image dimensions before expensive inference
    try:
        image_path = validate_safe_path(image_path)
    except ValueError as exc:
        return {"error": f"Path validation failed: {exc}"}

    try:
        validate_image_path_size(image_path)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception:
        pass  # PIL may not recognize all formats; let estimator try

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
        try:
            validate_image_size(original_image)
        except ValueError as exc:
            return {"error": str(exc)}
        # Resize to match normal map if needed
        if original_image.shape[:2] != (h, w):
            original_image = cv2.resize(original_image, (w, h))

    # --- Step 3: Create output directory ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Save the normal map itself as a PNG (useful for debugging)
    # Remap from [-1, 1] to [0, 255].  The model outputs RGB (x,y,z = R,G,B)
    # but cv2.imwrite expects BGR, so convert before saving.
    normal_vis = ((normal_map + 1.0) * 0.5 * 255.0).clip(0, 255).astype(np.uint8)
    normal_vis_bgr = cv2.cvtColor(normal_vis, cv2.COLOR_RGB2BGR)
    normal_map_path = os.path.join(OUTPUT_DIR, "normal_map.png")
    cv2.imwrite(normal_map_path, normal_vis_bgr)

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
        elif name == "principal_curvatures":
            pc = principal_curvatures(normal_map)
            # Visualize mean curvature H (channel 0) with diverging colormap
            H = pc[:, :, 0]
            abs_max = max(np.abs(H).max(), 1e-8)
            normalized = ((H / abs_max) + 1.0) * 0.5
            gray = (normalized * 255).clip(0, 255).astype(np.uint8)
            img = cv2.applyColorMap(gray, cv2.COLORMAP_TWILIGHT_SHIFTED)
        elif name == "surface_type":
            stype = surface_type_map(normal_map)
            # Color palette: flat=gray, convex=green, concave=red, saddle=blue, cylindrical=yellow
            palette = np.array([
                [128, 128, 128],  # 0 = flat (gray)
                [60, 180, 60],    # 1 = convex (green)
                [60, 60, 200],    # 2 = concave (red in BGR)
                [200, 100, 60],   # 3 = saddle (blue in BGR)
                [30, 200, 200],   # 4 = cylindrical (yellow in BGR)
            ], dtype=np.uint8)
            img = palette[stype]
        elif name == "ridge_valley":
            rv = ridge_valley_map(normal_map)
            # Channel 0 = ridges (red), channel 1 = valleys (blue)
            img = np.zeros((*rv.shape[:2], 3), dtype=np.uint8)
            img[:, :, 2] = rv[:, :, 0]  # ridges -> red channel (BGR)
            img[:, :, 0] = rv[:, :, 1]  # valleys -> blue channel (BGR)
        elif name == "silhouette":
            img = silhouette_contours(normal_map)
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif name == "depth_facing":
            facing = depth_facing_map(normal_map)
            gray = (facing * 255).clip(0, 255).astype(np.uint8)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        elif name == "surface_flow":
            flow = surface_flow_field(normal_map)
            # Visualize direction 1 as hue (angle), magnitude as value
            dx = flow[:, :, 0].astype(np.float64)
            dy = flow[:, :, 1].astype(np.float64)
            angle = (np.arctan2(dy, dx) + np.pi) / (2 * np.pi)  # [0, 1]
            mag = np.sqrt(dx ** 2 + dy ** 2)
            mag_norm = np.clip(mag / max(mag.max(), 1e-8), 0, 1)
            hsv = np.zeros((*flow.shape[:2], 3), dtype=np.uint8)
            hsv[:, :, 0] = (angle * 179).astype(np.uint8)
            hsv[:, :, 1] = 200
            hsv[:, :, 2] = (mag_norm * 255).astype(np.uint8)
            img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        elif name == "ambient_occlusion":
            ao = ambient_occlusion_approx(normal_map)
            gray = (ao * 255).clip(0, 255).astype(np.uint8)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        elif name == "form_material_boundaries":
            fb = form_vs_material_boundaries(normal_map)
            # Channel 0 = form (green), channel 1 = material (magenta)
            img = np.zeros((*fb.shape[:2], 3), dtype=np.uint8)
            img[:, :, 1] = fb[:, :, 0]  # form -> green (BGR)
            img[:, :, 0] = fb[:, :, 1]  # material -> blue (BGR)
            img[:, :, 2] = fb[:, :, 1]  # material -> red (BGR) = magenta
        elif name == "cross_contours":
            # Returns polylines, not an image — save as JSON instead of PNG
            polylines = cross_contour_field(normal_map)
            out_path = os.path.join(OUTPUT_DIR, f"{name}.json")
            import json as json_mod
            with open(out_path, "w") as f:
                json_mod.dump({"polylines": polylines, "count": len(polylines)}, f)
            rendering_paths[name] = out_path
            rendering_timings[name] = round(time.time() - t_r, 3)
            continue  # Skip the common PNG write path below
        elif name == "line_weight":
            lw = curvature_line_weight(normal_map)
            gray = (lw * 255).clip(0, 255).astype(np.uint8)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

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
            var baseName = "{layer_name}";
            var filePath = "{escaped_path}";

            // Find existing layer by name — if it has items that don't
            // belong to this tool, create a new layer with a numbered suffix
            // instead of destructively clearing user content.
            var lyr = null;
            var existingLyr = null;
            for (var i = 0; i < doc.layers.length; i++) {{
                if (doc.layers[i].name === baseName) {{
                    existingLyr = doc.layers[i];
                    break;
                }}
            }}

            if (existingLyr) {{
                // Check if all existing items belong to this tool (name
                // starts with "{escaped_prefix}:")
                var hasUserContent = false;
                existingLyr.locked = false;
                existingLyr.visible = true;
                for (var j = 0; j < existingLyr.pageItems.length; j++) {{
                    var itemName = existingLyr.pageItems[j].name;
                    if (itemName.indexOf("{escaped_prefix}:") !== 0) {{
                        hasUserContent = true;
                        break;
                    }}
                }}

                if (hasUserContent) {{
                    // Layer has user content — create a new numbered layer
                    var suffix = 2;
                    var newName = baseName + " " + suffix;
                    var nameExists = true;
                    while (nameExists) {{
                        nameExists = false;
                        for (var k = 0; k < doc.layers.length; k++) {{
                            if (doc.layers[k].name === newName) {{
                                nameExists = true;
                                suffix++;
                                newName = baseName + " " + suffix;
                                break;
                            }}
                        }}
                    }}
                    lyr = doc.layers.add();
                    lyr.name = newName;
                }} else {{
                    // Layer only has our tool's items — safe to clear and reuse
                    lyr = existingLyr;
                    while (lyr.pageItems.length > 0) {{
                        lyr.pageItems[0].remove();
                    }}
                }}
            }}

            if (!lyr) {{
                lyr = doc.layers.add();
                lyr.name = baseName;
            }}

            // Move layer to bottom of stack
            if (doc.layers.length > 1) {{
                lyr.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
            }}

            // Place image and embed.  After embed() the placed item becomes
            // a rasterItem — use lyr.rasterItems to get a reliable reference.
            doc.activeLayer = lyr;
            var placed = lyr.placedItems.add();
            placed.file = new File(filePath);
            placed.embed();

            // After embed, the placed item is converted to a rasterItem.
            // Grab the last rasterItem which is the one we just embedded.
            var imgItem = lyr.rasterItems[lyr.rasterItems.length - 1];

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

            // Name the item for future identification
            imgItem.name = "{escaped_prefix}: {display_name}";

            // Lock and hide the layer
            lyr.opacity = 50;
            lyr.locked = true;
            lyr.visible = false;

            placed_layers.push({{
                name: lyr.name,
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
