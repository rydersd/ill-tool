"""MCP tool for surface-region boundary extraction from reference images.

Click on a surface region (flat, convex, concave, saddle, cylindrical) in a
reference image, flood-fill the connected region of the same type, extract
boundary contours, and place as vector paths in Illustrator.

Actions:
- click_extract: Click a point, flood-fill the same-type region, extract boundary.
- region_extract: Extract all surface type boundaries within a rectangular ROI.
- type_extract: Extract ALL regions of a given surface type name.

Depends on:
- normal_renderings.surface_type_map for classification
- form_edge_pipeline.{edge_mask_to_contours, contours_to_ai_points} for vectorization
- form_edge_extract._build_place_jsx for Illustrator placement
- ml_backends.normal_estimator (DSINE) for normal map prediction
"""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.form_edge_pipeline import (
    contours_to_ai_points,
    edge_mask_to_contours,
)
from adobe_mcp.apps.illustrator.normal_renderings import surface_type_map
from adobe_mcp.apps.illustrator.surface_classifier import SURFACE_TYPE_NAMES
from adobe_mcp.apps.illustrator.drawing.form_edge_extract import (
    _build_place_jsx,
    OUTPUT_DIR,
)

# ---------------------------------------------------------------------------
# ML backend availability
# ---------------------------------------------------------------------------

try:
    from adobe_mcp.apps.illustrator.ml_backends.normal_estimator import (
        estimate_normals,
        DSINE_AVAILABLE,
    )
except ImportError:
    DSINE_AVAILABLE = False

    def estimate_normals(image_path: str, model: str = "auto") -> dict:
        """Stub when ML backend is not importable."""
        return {
            "error": "ml_backends.normal_estimator not available.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }


# Reverse lookup: surface type name -> integer value
_SURFACE_NAME_TO_INT = {name: val for val, name in SURFACE_TYPE_NAMES.items()}


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class SurfaceExtractInput(BaseModel):
    """Control surface region extraction and placement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="click_extract",
        description=(
            "Action: click_extract | region_extract | type_extract. "
            "click_extract = flood-fill connected region at click point. "
            "region_extract = extract all boundaries in a rectangular ROI. "
            "type_extract = extract ALL regions of a named surface type."
        ),
    )
    image_path: str = Field(
        default="",
        description="Absolute path to reference image (PNG/JPG).",
    )
    click_x: float = Field(
        default=0,
        description="Pixel X coordinate for click_extract.",
    )
    click_y: float = Field(
        default=0,
        description="Pixel Y coordinate for click_extract.",
    )
    region: list[float] = Field(
        default_factory=list,
        description="[x1, y1, x2, y2] bounding box for region_extract.",
    )
    surface_type: str = Field(
        default="",
        description='Surface type name for type_extract: "flat"|"convex"|"concave"|"cylindrical"|"saddle".',
    )
    layer_name: str = Field(
        default="Surface Extract",
        description="Illustrator layer name for placed paths.",
    )
    simplify_tolerance: float = Field(
        default=2.0,
        description="Douglas-Peucker simplification tolerance in pixels.",
        ge=0.0,
    )
    min_contour_length: int = Field(
        default=20,
        description="Minimum contour arc length in pixels.",
        ge=1,
    )
    max_contours: int = Field(
        default=50,
        description="Maximum number of contours to extract.",
        ge=1,
        le=500,
    )
    match_placed_item: bool = Field(
        default=True,
        description=(
            "When True, query for a PlacedItem on a 'ref' or 'Reference' layer "
            "and use its bounds for coordinate scaling."
        ),
    )
    save_debug: bool = Field(
        default=False,
        description="Save debug images (flood mask, surface type map) to output dir.",
    )


# ---------------------------------------------------------------------------
# Surface type map caching
# ---------------------------------------------------------------------------


def _cache_path_for(image_path: str) -> Path:
    """Return the path where the cached surface type map .npy would live."""
    basename = os.path.splitext(os.path.basename(image_path))[0]
    return Path(OUTPUT_DIR) / f"{basename}_surface_type_map.npy"


def _normal_map_cache_path_for(image_path: str) -> Path:
    """Return the path where the cached normal map .npy would live."""
    basename = os.path.splitext(os.path.basename(image_path))[0]
    return Path(OUTPUT_DIR) / f"{basename}_normal_map.npy"


def _get_surface_type_map(image_path: str) -> dict:
    """Load or compute the surface type map for an image.

    Checks for cached .npy first.  If not found, runs DSINE normal
    estimation, computes the surface type map, and caches both.

    Returns:
        Dict with keys:
        - ``surface_type_map``: HxW uint8 array with values 0-4.
        - ``normal_map``: HxWx3 float32 normal map (if computed).
        - ``image_size``: (width, height) tuple.
        - ``cached``: True if loaded from cache.
        - ``time_seconds``: float.
        On failure, returns dict with ``error`` key.
    """
    t0 = time.time()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.chmod(OUTPUT_DIR, 0o700)

    stype_cache = _cache_path_for(image_path)
    nmap_cache = _normal_map_cache_path_for(image_path)

    # Try loading from cache
    if stype_cache.exists() and nmap_cache.exists():
        try:
            stype_map = np.load(str(stype_cache))
            normal_map = np.load(str(nmap_cache))
            h, w = stype_map.shape[:2]
            return {
                "surface_type_map": stype_map,
                "normal_map": normal_map,
                "image_size": (w, h),
                "cached": True,
                "time_seconds": round(time.time() - t0, 4),
            }
        except Exception:
            pass  # Cache corrupt, recompute

    # Need to compute — check DSINE availability
    if not DSINE_AVAILABLE:
        return {
            "error": "DSINE not available. Surface type map requires normal estimation.",
            "install_hint": 'Install with: uv pip install -e ".[ml-form-edge]"',
        }

    # Run DSINE
    result = estimate_normals(image_path, model="dsine")
    if "error" in result:
        return result

    normal_map = result["normal_map"]  # HxWx3 float32

    # Compute surface type map
    stype_map = surface_type_map(normal_map)

    # Cache both
    try:
        np.save(str(stype_cache), stype_map)
        np.save(str(nmap_cache), normal_map)
    except Exception:
        pass  # Cache write failure is non-fatal

    h, w = stype_map.shape[:2]
    return {
        "surface_type_map": stype_map,
        "normal_map": normal_map,
        "image_size": (w, h),
        "cached": False,
        "time_seconds": round(time.time() - t0, 4),
    }


# ---------------------------------------------------------------------------
# click_extract: flood-fill connected region at click point
# ---------------------------------------------------------------------------


def _click_extract(
    stype_map: np.ndarray,
    click_x: int,
    click_y: int,
    simplify_tolerance: float,
    min_contour_length: int,
    max_contours: int,
    save_debug: bool,
) -> dict:
    """Flood-fill the surface type region at (click_x, click_y) and extract boundary contours.

    Args:
        stype_map: HxW uint8 surface type map (values 0-4).
        click_x: Pixel X coordinate of the click.
        click_y: Pixel Y coordinate of the click.
        simplify_tolerance: Douglas-Peucker epsilon.
        min_contour_length: Minimum arc length filter.
        max_contours: Maximum contour count.
        save_debug: Whether to save debug images.

    Returns:
        Dict with contours, surface type info, and metadata.
        Contains "error" key on failure.
    """
    h, w = stype_map.shape[:2]

    # Validate click is inside image bounds
    if click_x < 0 or click_x >= w or click_y < 0 or click_y >= h:
        return {
            "error": (
                f"Click point ({click_x}, {click_y}) is outside image bounds "
                f"(0-{w - 1}, 0-{h - 1})."
            ),
        }

    # Get the surface type value at the click point
    surface_val = int(stype_map[click_y, click_x])
    surface_name = SURFACE_TYPE_NAMES.get(surface_val, f"unknown_{surface_val}")

    # Flood-fill from the click point to find the connected region of the
    # same surface type.  We use FLOODFILL_MASK_ONLY so the original map
    # is not modified.
    flood_input = stype_map.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(
        flood_input,
        mask,
        (click_x, click_y),
        255,
        loDiff=0,
        upDiff=0,
        flags=cv2.FLOODFILL_MASK_ONLY,
    )
    # Strip the 1-pixel border added by floodFill
    region_mask = mask[1:-1, 1:-1] * 255

    # Check that we actually filled something
    filled_pixels = int(np.count_nonzero(region_mask))
    if filled_pixels == 0:
        return {
            "error": f"Flood fill from ({click_x}, {click_y}) produced an empty region.",
            "surface_type": surface_name,
            "surface_value": surface_val,
        }

    # Save debug images if requested
    debug_paths = {}
    if save_debug:
        debug_dir = os.path.join(OUTPUT_DIR, "normal_maps")
        os.makedirs(debug_dir, exist_ok=True)
        flood_path = os.path.join(debug_dir, "flood_mask.png")
        cv2.imwrite(flood_path, region_mask)
        debug_paths["flood_mask"] = flood_path

        # Also save a colored version of the surface type map for context
        stype_vis = _colorize_surface_type_map(stype_map)
        stype_vis_path = os.path.join(debug_dir, "surface_type_map.png")
        cv2.imwrite(stype_vis_path, stype_vis)
        debug_paths["surface_type_map"] = stype_vis_path

    # Find contours on the flood-filled region mask
    contours = edge_mask_to_contours(
        region_mask,
        simplify_tolerance=simplify_tolerance,
        min_length=min_contour_length,
        max_contours=max_contours,
    )

    # Rename contours to reflect the surface type
    for i, c in enumerate(contours):
        c["name"] = f"{surface_name}_{i}"

    return {
        "contours": contours,
        "contour_count": len(contours),
        "surface_type": surface_name,
        "surface_value": surface_val,
        "filled_pixels": filled_pixels,
        "click_point": [click_x, click_y],
        "debug_paths": debug_paths if debug_paths else None,
    }


# ---------------------------------------------------------------------------
# type_extract: extract ALL regions of a given surface type
# ---------------------------------------------------------------------------


def _type_extract(
    stype_map: np.ndarray,
    surface_type: str,
    simplify_tolerance: float,
    min_contour_length: int,
    max_contours: int,
    save_debug: bool,
) -> dict:
    """Create a binary mask for the requested surface type and extract contours.

    Args:
        stype_map: HxW uint8 surface type map (values 0-4).
        surface_type: Surface type name ("flat", "convex", etc.).
        simplify_tolerance: Douglas-Peucker epsilon.
        min_contour_length: Minimum arc length filter.
        max_contours: Maximum contour count.
        save_debug: Whether to save debug images.

    Returns:
        Dict with contours and metadata. Contains "error" key on failure.
    """
    type_val = _SURFACE_NAME_TO_INT.get(surface_type.lower().strip())
    if type_val is None:
        return {
            "error": f"Unknown surface type: '{surface_type}'",
            "valid_types": list(_SURFACE_NAME_TO_INT.keys()),
        }

    # Create binary mask where the surface type matches
    type_mask = (stype_map == type_val).astype(np.uint8) * 255

    masked_pixels = int(np.count_nonzero(type_mask))
    if masked_pixels == 0:
        return {
            "error": f"No pixels of type '{surface_type}' found in the surface type map.",
            "surface_type": surface_type,
            "surface_value": type_val,
        }

    # Save debug images if requested
    debug_paths = {}
    if save_debug:
        debug_dir = os.path.join(OUTPUT_DIR, "normal_maps")
        os.makedirs(debug_dir, exist_ok=True)
        type_mask_path = os.path.join(debug_dir, f"type_mask_{surface_type}.png")
        cv2.imwrite(type_mask_path, type_mask)
        debug_paths["type_mask"] = type_mask_path

    # Find contours on the type mask
    contours = edge_mask_to_contours(
        type_mask,
        simplify_tolerance=simplify_tolerance,
        min_length=min_contour_length,
        max_contours=max_contours,
    )

    # Rename contours
    for i, c in enumerate(contours):
        c["name"] = f"{surface_type}_{i}"

    return {
        "contours": contours,
        "contour_count": len(contours),
        "surface_type": surface_type,
        "surface_value": type_val,
        "masked_pixels": masked_pixels,
        "debug_paths": debug_paths if debug_paths else None,
    }


# ---------------------------------------------------------------------------
# region_extract: extract all surface type boundaries in a rectangular ROI
# ---------------------------------------------------------------------------


def _region_extract(
    stype_map: np.ndarray,
    region: list[float],
    simplify_tolerance: float,
    min_contour_length: int,
    max_contours: int,
    save_debug: bool,
) -> dict:
    """Extract all surface type boundaries within a rectangular region.

    Runs edge detection (Canny) on the surface type map within the ROI
    to find boundaries between different surface types.

    Args:
        stype_map: HxW uint8 surface type map (values 0-4).
        region: [x1, y1, x2, y2] bounding box in pixel coords.
        simplify_tolerance: Douglas-Peucker epsilon.
        min_contour_length: Minimum arc length filter.
        max_contours: Maximum contour count.
        save_debug: Whether to save debug images.

    Returns:
        Dict with contours and metadata. Contains "error" key on failure.
    """
    if len(region) != 4:
        return {"error": "region must be [x1, y1, x2, y2] (4 values)."}

    h, w = stype_map.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in region]

    # Clamp to image bounds
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))

    if x2 <= x1 or y2 <= y1:
        return {
            "error": f"Invalid region after clamping: [{x1}, {y1}, {x2}, {y2}]",
        }

    # Crop the surface type map to the ROI
    roi = stype_map[y1:y2, x1:x2].copy()

    # Scale the surface type values to spread across 0-255 for better edge
    # detection (original values are 0-4, which Canny would barely see)
    roi_scaled = (roi.astype(np.float32) * (255.0 / max(4, roi.max()))).astype(np.uint8)

    # Detect edges between different surface types using Canny
    edges = cv2.Canny(roi_scaled, 30, 100)

    # Morphological close to connect nearby edge fragments
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    edge_pixels = int(np.count_nonzero(edges))
    if edge_pixels == 0:
        return {
            "error": "No surface type boundaries found in the specified region.",
            "region": [x1, y1, x2, y2],
        }

    # Save debug images if requested
    debug_paths = {}
    if save_debug:
        debug_dir = os.path.join(OUTPUT_DIR, "normal_maps")
        os.makedirs(debug_dir, exist_ok=True)
        edges_path = os.path.join(debug_dir, "region_edges.png")
        cv2.imwrite(edges_path, edges)
        debug_paths["region_edges"] = edges_path

    # Find contours on the edge mask
    contours = edge_mask_to_contours(
        edges,
        simplify_tolerance=simplify_tolerance,
        min_length=min_contour_length,
        max_contours=max_contours,
    )

    # Offset contour points back to full-image coordinates
    for c in contours:
        c["points"] = [[pt[0] + x1, pt[1] + y1] for pt in c["points"]]

    # Rename contours
    for i, c in enumerate(contours):
        c["name"] = f"region_boundary_{i}"

    return {
        "contours": contours,
        "contour_count": len(contours),
        "region": [x1, y1, x2, y2],
        "edge_pixels": edge_pixels,
        "debug_paths": debug_paths if debug_paths else None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _colorize_surface_type_map(stype_map: np.ndarray) -> np.ndarray:
    """Create a colored visualization of the surface type map.

    Color scheme:
        0 = flat        -> gray
        1 = convex      -> red
        2 = concave     -> blue
        3 = saddle       -> green
        4 = cylindrical -> yellow

    Args:
        stype_map: HxW uint8 surface type map (values 0-4).

    Returns:
        HxWx3 uint8 BGR image.
    """
    palette = np.array([
        [128, 128, 128],  # flat = gray
        [0, 0, 220],      # convex = red (BGR)
        [220, 0, 0],      # concave = blue (BGR)
        [0, 180, 0],      # saddle = green
        [0, 220, 220],    # cylindrical = yellow (BGR)
    ], dtype=np.uint8)

    # Clamp values to valid range
    clamped = np.clip(stype_map, 0, 4)
    return palette[clamped]


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_surface_extract tool."""

    @mcp.tool(
        name="adobe_ai_surface_extract",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_surface_extract(
        params: SurfaceExtractInput,
    ) -> str:
        """Extract vector contours along surface region boundaries.

        Click on a surface region in a reference image to flood-fill and
        extract the boundary contour, or extract all regions of a specific
        surface type, or extract all surface boundaries within a region.

        Surface types: flat, convex, concave, saddle, cylindrical.

        Actions:
        - click_extract: Click a point, flood-fill same-type region, extract boundary
        - region_extract: Extract all surface boundaries in a rectangular ROI
        - type_extract: Extract ALL regions of a named surface type
        """
        from adobe_mcp.engine import _async_run_jsx

        action = params.action.lower().strip()

        # --- Validate image_path (required for all actions) ---
        if not params.image_path:
            return json.dumps({"error": "image_path is required."})

        if not os.path.isfile(params.image_path):
            return json.dumps({"error": f"Image not found: {params.image_path}"})

        # --- Load or compute surface type map ---
        stype_result = _get_surface_type_map(params.image_path)
        if "error" in stype_result:
            return json.dumps(stype_result, indent=2)

        stype_map = stype_result["surface_type_map"]
        image_size = stype_result["image_size"]  # (w, h)
        map_time = stype_result["time_seconds"]
        was_cached = stype_result["cached"]

        t0 = time.time()

        # --- Dispatch to action handler ---
        if action == "click_extract":
            cx = int(round(params.click_x))
            cy = int(round(params.click_y))
            extract_result = _click_extract(
                stype_map, cx, cy,
                params.simplify_tolerance,
                params.min_contour_length,
                params.max_contours,
                params.save_debug,
            )

        elif action == "type_extract":
            if not params.surface_type:
                return json.dumps({
                    "error": "surface_type is required for type_extract action.",
                    "valid_types": list(_SURFACE_NAME_TO_INT.keys()),
                })
            extract_result = _type_extract(
                stype_map,
                params.surface_type,
                params.simplify_tolerance,
                params.min_contour_length,
                params.max_contours,
                params.save_debug,
            )

        elif action == "region_extract":
            if not params.region or len(params.region) != 4:
                return json.dumps({
                    "error": "region must be [x1, y1, x2, y2] for region_extract.",
                })
            extract_result = _region_extract(
                stype_map,
                params.region,
                params.simplify_tolerance,
                params.min_contour_length,
                params.max_contours,
                params.save_debug,
            )

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["click_extract", "region_extract", "type_extract"],
            })

        if "error" in extract_result:
            return json.dumps(extract_result, indent=2)

        contours = extract_result["contours"]
        if not contours:
            return json.dumps({
                "warning": "No contours met the minimum length/count criteria.",
                "surface_info": {
                    k: v for k, v in extract_result.items() if k != "contours"
                },
            })

        # --- Query artboard and PlacedItem bounds from Illustrator ---
        jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
        ab_result = await _async_run_jsx("illustrator", jsx_info)
        if not ab_result["success"]:
            return json.dumps({
                "error": f"Could not query artboard: {ab_result.get('stderr', '')}",
                "contours": contours,
            })

        try:
            artboard = json.loads(ab_result["stdout"])
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "error": f"Bad artboard response: {ab_result.get('stdout', '')}",
                "contours": contours,
            })

        # --- PlacedItem bounds query (reuse pattern from form_edge_extract) ---
        target_bounds = artboard
        placed_item_matched = False

        if params.match_placed_item:
            jsx_placed = """
(function() {
    var doc = app.activeDocument;
    var refNames = ["ref", "Ref", "reference", "Reference"];
    for (var n = 0; n < refNames.length; n++) {
        try {
            var layer = doc.layers.getByName(refNames[n]);
        } catch(e) { continue; }
        for (var i = 0; i < layer.placedItems.length; i++) {
            var pi = layer.placedItems[i];
            var gb = pi.geometricBounds;
            return JSON.stringify({
                found: true,
                left: gb[0], top: gb[1], right: gb[2], bottom: gb[3],
                layer: layer.name, name: pi.name || ""
            });
        }
        for (var j = 0; j < layer.rasterItems.length; j++) {
            var ri = layer.rasterItems[j];
            var rb = ri.geometricBounds;
            return JSON.stringify({
                found: true,
                left: rb[0], top: rb[1], right: rb[2], bottom: rb[3],
                layer: layer.name, name: ri.name || ""
            });
        }
    }
    return JSON.stringify({found: false});
})();
"""
            pi_result = await _async_run_jsx("illustrator", jsx_placed)
            if pi_result["success"]:
                try:
                    pi_data = json.loads(pi_result["stdout"])
                    if pi_data.get("found"):
                        target_bounds = {
                            "left": pi_data["left"],
                            "top": pi_data["top"],
                            "right": pi_data["right"],
                            "bottom": pi_data["bottom"],
                        }
                        placed_item_matched = True
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass  # Fall back to artboard bounds

        # --- Transform contours to AI coordinates ---
        coord_margin = 1.0 if placed_item_matched else 0.95
        ai_contours = contours_to_ai_points(
            contours, image_size, target_bounds, margin=coord_margin,
        )

        # --- Build and execute JSX for path placement ---
        jsx_batches = _build_place_jsx(
            ai_contours, params.layer_name, smooth=True,
        )

        total_placed = 0
        all_paths: list[dict] = []
        last_layer = params.layer_name
        batch_errors: list[str] = []

        for batch_idx, jsx in enumerate(jsx_batches):
            place_result = await _async_run_jsx("illustrator", jsx)

            if not place_result["success"]:
                batch_errors.append(
                    f"Batch {batch_idx}: {place_result.get('stderr', 'unknown error')}"
                )
                continue

            try:
                batch_data = json.loads(place_result["stdout"])
                total_placed += batch_data.get("paths_placed", 0)
                all_paths.extend(batch_data.get("paths", []))
                last_layer = batch_data.get("layer", last_layer)
            except (json.JSONDecodeError, TypeError):
                batch_errors.append(f"Batch {batch_idx}: bad JSON response")

        if total_placed == 0 and batch_errors:
            return json.dumps({
                "error": f"Path placement failed: {'; '.join(batch_errors)}",
                "contour_count": len(ai_contours),
                "jsx_batches": len(jsx_batches),
            })

        t1 = time.time()

        # --- Build response ---
        response = {
            "action": action,
            "paths_placed": total_placed,
            "paths": all_paths,
            "layer_name": last_layer,
            "contour_count": len(ai_contours),
            "image_size": list(image_size),
            "surface_type_map_cached": was_cached,
            "timings": {
                "surface_map_seconds": map_time,
                "extract_and_place_seconds": round(t1 - t0, 4),
                "total_seconds": round(map_time + (t1 - t0), 4),
            },
        }

        # Include action-specific metadata
        if "surface_type" in extract_result:
            response["surface_type"] = extract_result["surface_type"]
        if "surface_value" in extract_result:
            response["surface_value"] = extract_result["surface_value"]
        if "filled_pixels" in extract_result:
            response["filled_pixels"] = extract_result["filled_pixels"]
        if "click_point" in extract_result:
            response["click_point"] = extract_result["click_point"]
        if "region" in extract_result:
            response["region"] = extract_result["region"]
        if "masked_pixels" in extract_result:
            response["masked_pixels"] = extract_result["masked_pixels"]

        if placed_item_matched:
            response["coordinate_source"] = "placed_item"
        if len(jsx_batches) > 1:
            response["jsx_batches"] = len(jsx_batches)
        if batch_errors:
            response["batch_errors"] = batch_errors
        if extract_result.get("debug_paths"):
            response["debug_paths"] = extract_result["debug_paths"]

        return json.dumps(response, indent=2, default=_json_default)
