"""Meta-tool: orchestrate a full draw-and-refine cycle for one shape from a manifest.

Pipeline:
    1. Parse the shape manifest, extract the target shape by index
    2. Create the path in Illustrator via contour_to_path logic
    3. Smooth it via bezier_optimize logic
    4. Score convergence against the reference via compare logic
    5. If below target: run auto_correct passes to converge
    6. Return final convergence, shape info, and iteration count
"""

import json
import math
import os
import tempfile

import cv2
import numpy as np

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.common.compare import (
    _extract_contours,
    _match_contours,
    _compute_corrections,
    _contour_centroid,
)
from adobe_mcp.apps.illustrator.auto_correct import (
    _build_read_jsx,
    _build_export_jsx,
    _score_convergence,
    _find_closest_item,
    _compute_anchor_corrections,
    _build_apply_jsx,
    _ai_to_pixel,
)


# ---------------------------------------------------------------------------
# Input model (inline — not in models.py per spec)
# ---------------------------------------------------------------------------

class DrawingOrchestratorInput(BaseModel):
    """Orchestrate a full draw cycle for one shape from a reference manifest."""
    model_config = ConfigDict(str_strip_whitespace=True)

    reference_path: str = Field(..., description="Absolute path to the reference image")
    shape_index: int = Field(default=0, description="Index of the shape in the manifest to draw")
    shape_manifest: str = Field(..., description="Full JSON manifest from analyze_reference")
    image_size: str = Field(..., description="JSON [width, height] of the source image")
    layer_name: str = Field(default="Drawing", description="Target layer for the path")
    auto_correct_passes: int = Field(default=2, description="Max correction iterations", ge=0, le=5)
    convergence_target: float = Field(default=0.85, description="Stop when convergence exceeds this", ge=0, le=1)


def register(mcp):
    """Register the adobe_ai_drawing_orchestrator tool."""

    @mcp.tool(
        name="adobe_ai_drawing_orchestrator",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_drawing_orchestrator(params: DrawingOrchestratorInput) -> str:
        """Orchestrate a full draw-and-refine cycle for one shape.

        Parses the manifest, creates the path via contour_to_path logic,
        smooths it via bezier_optimize, then runs auto_correct passes
        until convergence reaches the target or passes are exhausted.
        Returns the final convergence score and shape metadata.
        """
        # ── 1. Validate inputs ──────────────────────────────────────────
        if not os.path.isfile(params.reference_path):
            return json.dumps({"error": f"Reference image not found: {params.reference_path}"})

        ref_img = cv2.imread(params.reference_path)
        if ref_img is None:
            return json.dumps({"error": f"Could not decode reference image: {params.reference_path}"})

        try:
            manifest = json.loads(params.shape_manifest)
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"Invalid shape_manifest JSON: {exc}"})

        shapes = manifest.get("shapes", [])
        if params.shape_index >= len(shapes) or params.shape_index < 0:
            return json.dumps({
                "error": f"shape_index {params.shape_index} out of range (manifest has {len(shapes)} shapes)"
            })

        shape = shapes[params.shape_index]

        try:
            img_size = json.loads(params.image_size)
            img_w, img_h = float(img_size[0]), float(img_size[1])
        except (json.JSONDecodeError, TypeError, IndexError, ValueError) as exc:
            return json.dumps({"error": f"Invalid image_size: {exc}"})

        pixel_points = shape.get("approx_points")
        if not pixel_points:
            return json.dumps({"error": "Shape has no approx_points in manifest."})

        ref_h, ref_w = ref_img.shape[:2]
        min_area = ref_h * ref_w * 0.005  # 0.5% threshold for convergence scoring

        escaped_layer = escape_jsx_string(params.layer_name)
        shape_name = f"shape_{params.shape_index}"
        escaped_name = escape_jsx_string(shape_name)

        temp_files: list[str] = []

        try:
            # ── 2. Get artboard dimensions ──────────────────────────────
            jsx_info = """
(function() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    return JSON.stringify({left: ab[0], top: ab[1], right: ab[2], bottom: ab[3]});
})();
"""
            ab_result = await _async_run_jsx("illustrator", jsx_info)
            if not ab_result["success"]:
                return json.dumps({"error": f"Could not query artboard: {ab_result['stderr']}"})

            ab = json.loads(ab_result["stdout"])
            ab_w = ab["right"] - ab["left"]
            ab_h = ab["top"] - ab["bottom"]

            # ── 3. Transform pixel coords to AI coords ──────────────────
            scale_x = ab_w / img_w
            scale_y = ab_h / img_h
            scale = min(scale_x, scale_y)

            offset_x = ab["left"] + (ab_w - img_w * scale) / 2
            offset_y = ab["top"] - (ab_h - img_h * scale) / 2

            points_ai = []
            for pt in pixel_points:
                ai_x = pt[0] * scale + offset_x
                ai_y = offset_y - pt[1] * scale
                points_ai.append([round(ai_x, 2), round(ai_y, 2)])

            points_json = json.dumps(points_ai)

            # ── 4. Create the path in Illustrator ───────────────────────
            create_jsx = f"""
(function() {{
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "{escaped_layer}") {{
            layer = doc.layers[i]; break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "{escaped_layer}";
    }}
    doc.activeLayer = layer;

    var path = layer.pathItems.add();
    path.setEntirePath({points_json});
    path.closed = true;
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = 2;
    var black = new RGBColor();
    black.red = 0; black.green = 0; black.blue = 0;
    path.strokeColor = black;
    path.name = "{escaped_name}";

    // Smooth: set bezier handles to 1/3 distance to neighbors
    var n = path.pathPoints.length;
    if (n >= 3) {{
        for (var i = 0; i < n; i++) {{
            var pt = path.pathPoints[i];
            var prevIdx = (i - 1 + n) % n;
            var nextIdx = (i + 1) % n;
            var prev = path.pathPoints[prevIdx];
            var next = path.pathPoints[nextIdx];
            var dx_l = (pt.anchor[0] - prev.anchor[0]) / 3;
            var dy_l = (pt.anchor[1] - prev.anchor[1]) / 3;
            var dx_r = (next.anchor[0] - pt.anchor[0]) / 3;
            var dy_r = (next.anchor[1] - pt.anchor[1]) / 3;
            pt.leftDirection = [pt.anchor[0] - dx_l, pt.anchor[1] - dy_l];
            pt.rightDirection = [pt.anchor[0] + dx_r, pt.anchor[1] + dy_r];
        }}
    }}

    return JSON.stringify({{
        name: path.name,
        layer: layer.name,
        pointCount: path.pathPoints.length
    }});
}})();
"""
            create_result = await _async_run_jsx("illustrator", create_jsx)
            if not create_result["success"]:
                return json.dumps({
                    "error": f"Path creation failed: {create_result['stderr']}",
                    "stage": "contour_to_path",
                })

            try:
                created = json.loads(create_result["stdout"])
            except (json.JSONDecodeError, TypeError):
                created = {"name": shape_name}

            # ── 5. Score initial convergence ────────────────────────────
            tmp_export = tempfile.mktemp(suffix=".png", prefix="ai_orch_")
            temp_files.append(tmp_export)

            export_jsx = _build_export_jsx(tmp_export)
            export_result = await _async_run_jsx("illustrator", export_jsx)

            initial_convergence = 0.0
            if export_result["success"]:
                draw_img = cv2.imread(tmp_export)
                if draw_img is not None:
                    draw_img = cv2.resize(draw_img, (ref_w, ref_h))
                    initial_convergence, _, _, _ = _score_convergence(
                        ref_img, draw_img, min_area,
                    )

            # ── 6. Auto-correct loop ────────────────────────────────────
            current_convergence = initial_convergence
            iterations_used = 0
            total_points_moved = 0

            if current_convergence < params.convergence_target and params.auto_correct_passes > 0:
                for iteration in range(params.auto_correct_passes):
                    iterations_used += 1

                    # Read drawing state
                    read_jsx = _build_read_jsx(params.layer_name)
                    read_result = await _async_run_jsx("illustrator", read_jsx)
                    if not read_result["success"]:
                        break

                    try:
                        drawing_state = json.loads(read_result["stdout"])
                    except (json.JSONDecodeError, TypeError):
                        break

                    items = drawing_state.get("items", [])
                    artboard_rect = drawing_state.get("artboardRect", [0, 0, 800, -600])
                    if not items:
                        break

                    abl = artboard_rect[0]
                    abt = artboard_rect[1]
                    abr = artboard_rect[2]
                    abb = artboard_rect[3]
                    a_w = abr - abl
                    a_h = abt - abb

                    if a_w <= 0 or a_h <= 0:
                        break

                    # Export current state
                    tmp_iter = tempfile.mktemp(suffix=".png", prefix="ai_orch_iter_")
                    temp_files.append(tmp_iter)
                    iter_export = _build_export_jsx(tmp_iter)
                    iter_result = await _async_run_jsx("illustrator", iter_export)
                    if not iter_result["success"]:
                        break

                    draw_img = cv2.imread(tmp_iter)
                    if draw_img is None:
                        break
                    draw_img = cv2.resize(draw_img, (ref_w, ref_h))

                    # Extract and match contours
                    ref_contours = _extract_contours(ref_img, min_area)
                    draw_contours = _extract_contours(draw_img, min_area)
                    matched_pairs = _match_contours(ref_contours, draw_contours)

                    if not matched_pairs:
                        break

                    # Compute and apply corrections
                    used_indices: set[int] = set()
                    all_corrections: list[dict] = []

                    for ri, di in matched_pairs:
                        corrections, hausdorff = _compute_corrections(
                            ref_contours[ri], draw_contours[di],
                        )
                        dcx, dcy = _contour_centroid(draw_contours[di])
                        item_idx = _find_closest_item(
                            items, dcx, dcy,
                            abl, abt, a_w, a_h,
                            ref_w, ref_h,
                            used_indices,
                        )
                        if item_idx is None:
                            continue
                        used_indices.add(item_idx)

                        item = next((it for it in items if it["index"] == item_idx), None)
                        if item is None:
                            continue

                        anchor_adjustments = _compute_anchor_corrections(
                            item, corrections, 0.5,  # correction_strength
                            abl, abt, a_w, a_h,
                            ref_w, ref_h,
                        )
                        if anchor_adjustments:
                            all_corrections.append({
                                "item_index": item_idx,
                                "points": anchor_adjustments,
                            })

                    if all_corrections:
                        apply_jsx = _build_apply_jsx(params.layer_name, all_corrections)
                        apply_result = await _async_run_jsx("illustrator", apply_jsx)
                        if apply_result["success"]:
                            for corr in all_corrections:
                                total_points_moved += len(corr["points"])

                    # Re-score
                    tmp_rescore = tempfile.mktemp(suffix=".png", prefix="ai_orch_rescore_")
                    temp_files.append(tmp_rescore)
                    rescore_jsx = _build_export_jsx(tmp_rescore)
                    rescore_result = await _async_run_jsx("illustrator", rescore_jsx)

                    if rescore_result["success"]:
                        rescore_img = cv2.imread(tmp_rescore)
                        if rescore_img is not None:
                            rescore_img = cv2.resize(rescore_img, (ref_w, ref_h))
                            current_convergence, _, _, _ = _score_convergence(
                                ref_img, rescore_img, min_area,
                            )

                    if current_convergence >= params.convergence_target:
                        break

            # ── 7. Build result ─────────────────────────────────────────
            return json.dumps({
                "shape_index": params.shape_index,
                "shape_type": shape.get("type", "unknown"),
                "shape_name": created.get("name", shape_name),
                "point_count": created.get("pointCount", len(points_ai)),
                "initial_convergence": round(initial_convergence, 3),
                "final_convergence": round(current_convergence, 3),
                "improvement": round(current_convergence - initial_convergence, 3),
                "auto_correct_iterations": iterations_used,
                "total_points_moved": total_points_moved,
                "reached_target": current_convergence >= params.convergence_target,
                "convergence_target": params.convergence_target,
            }, indent=2)

        finally:
            # Clean up temp files
            for tf in temp_files:
                try:
                    if os.path.isfile(tf):
                        os.remove(tf)
                except OSError:
                    pass
