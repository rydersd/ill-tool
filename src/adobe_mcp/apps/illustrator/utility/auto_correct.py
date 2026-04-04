"""Closed-loop auto-correction: compare drawing vs reference then apply anchor point adjustments.

Combines compare_drawing's contour analysis with direct JSX anchor-point
manipulation to nudge pathItems toward a reference image automatically.

Pipeline:
    A. Read pathItems from the drawing layer via JSX
    B. Export artboard + run OpenCV contour comparison
    C. Map pixel-space correction vectors to Illustrator coordinates
    D. Apply damped corrections via JSX
    E. Re-score (loop if max_iterations > 1)
"""

import json
import math
import os
import tempfile

import cv2
import numpy as np

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiAutoCorrectInput
from adobe_mcp.apps.common.compare import (
    _extract_contours,
    _match_contours,
    _compute_corrections,
    _contour_centroid,
    _resample_contour,
)
from adobe_mcp.apps.illustrator.ml_vision.pixel_deviation_scorer import (
    load_calibration,
    score_pixel_deviation,
)


# ---------------------------------------------------------------------------
# Coordinate transform helpers
# ---------------------------------------------------------------------------


def _ai_to_pixel(
    ai_x: float,
    ai_y: float,
    ab_left: float,
    ab_top: float,
    ab_width: float,
    ab_height: float,
    img_width: int,
    img_height: int,
) -> tuple[float, float]:
    """Convert Illustrator artboard coordinates to pixel coordinates.

    AI coordinate system: origin at top-left of artboard, Y increases upward.
    Pixel coordinates: origin at top-left, Y increases downward.
    """
    px = (ai_x - ab_left) / ab_width * img_width
    py = (ab_top - ai_y) / ab_height * img_height
    return px, py


def _pixel_to_ai(
    px: float,
    py: float,
    ab_left: float,
    ab_top: float,
    ab_width: float,
    ab_height: float,
    img_width: int,
    img_height: int,
) -> tuple[float, float]:
    """Convert pixel coordinates back to Illustrator artboard coordinates."""
    ai_x = px / img_width * ab_width + ab_left
    ai_y = ab_top - py / img_height * ab_height
    return ai_x, ai_y


# ---------------------------------------------------------------------------
# Phase A: Read drawing state from Illustrator
# ---------------------------------------------------------------------------


def _build_read_jsx(layer_name: str) -> str:
    """Build JSX that reads all pathItems on the named layer and returns JSON."""
    escaped = escape_jsx_string(layer_name)
    return f"""
(function() {{
    var doc = app.activeDocument;
    var layer = doc.layers.getByName("{escaped}");
    var items = [];
    for (var i = 0; i < layer.pathItems.length; i++) {{
        var pi = layer.pathItems[i];
        var points = [];
        for (var j = 0; j < pi.pathPoints.length; j++) {{
            var pp = pi.pathPoints[j];
            points.push({{
                anchor: [pp.anchor[0], pp.anchor[1]],
                leftDirection: [pp.leftDirection[0], pp.leftDirection[1]],
                rightDirection: [pp.rightDirection[0], pp.rightDirection[1]]
            }});
        }}
        items.push({{
            index: i,
            name: pi.name,
            bounds: [pi.geometricBounds[0], pi.geometricBounds[1],
                     pi.geometricBounds[2], pi.geometricBounds[3]],
            center: [(pi.geometricBounds[0] + pi.geometricBounds[2]) / 2,
                      (pi.geometricBounds[1] + pi.geometricBounds[3]) / 2],
            area: Math.abs((pi.geometricBounds[2] - pi.geometricBounds[0]) *
                           (pi.geometricBounds[1] - pi.geometricBounds[3])),
            pointCount: pi.pathPoints.length,
            points: points
        }});
    }}
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var abRect = doc.artboards[abIdx].artboardRect;
    return JSON.stringify({{items: items, artboardRect: [abRect[0], abRect[1], abRect[2], abRect[3]]}});
}})();
"""


# ---------------------------------------------------------------------------
# Phase B: Export artboard as PNG
# ---------------------------------------------------------------------------


def _build_export_jsx(export_path: str) -> str:
    """Build JSX that exports the active artboard as a PNG24."""
    escaped = escape_jsx_string(export_path)
    return f"""
(function() {{
    var doc = app.activeDocument;
    var opts = new ExportOptionsPNG24();
    opts.horizontalScale = 100;
    opts.verticalScale = 100;
    opts.transparency = false;
    opts.antiAliasing = true;
    opts.artBoardClipping = true;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    doc.artboards.setActiveArtboardIndex(abIdx);
    doc.exportFile(new File("{escaped}"), ExportType.PNG24, opts);
    return "exported";
}})();
"""


# ---------------------------------------------------------------------------
# Phase C: Map OpenCV corrections to AI path items
# ---------------------------------------------------------------------------


def _find_closest_item(
    items: list[dict],
    target_px: float,
    target_py: float,
    ab_left: float,
    ab_top: float,
    ab_width: float,
    ab_height: float,
    img_width: int,
    img_height: int,
    used_indices: set[int],
) -> int | None:
    """Find the AI pathItem whose center is closest to a pixel-space point.

    Returns the item index, or None if no items remain.
    """
    best_idx: int | None = None
    best_dist = float("inf")

    for item in items:
        idx = item["index"]
        if idx in used_indices:
            continue
        # Convert AI center to pixel space
        ai_cx, ai_cy = item["center"]
        px, py = _ai_to_pixel(
            ai_cx, ai_cy, ab_left, ab_top, ab_width, ab_height,
            img_width, img_height,
        )
        dist = math.hypot(px - target_px, py - target_py)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    return best_idx


def _compute_anchor_corrections(
    item: dict,
    correction_vectors: list[dict],
    correction_strength: float,
    ab_left: float,
    ab_top: float,
    ab_width: float,
    ab_height: float,
    img_width: int,
    img_height: int,
    num_nearest: int = 4,
) -> list[dict]:
    """Compute new anchor positions for a single pathItem using nearby correction vectors.

    For each anchor point on the AI item:
    1. Convert the anchor to pixel space
    2. Find the K nearest correction vector sample points
    3. Average their dx/dy displacements
    4. Apply damped correction
    5. Convert back to AI space

    Returns a list of dicts with idx, x, y, old_x, old_y for the JSX applicator.
    """
    # Build an array of correction sample points in pixel space.
    # correction_vectors is the output of _compute_corrections: list of {idx, dx, dy}
    # These corrections are defined along the resampled contour. We need to know
    # where those sample points sit in pixel space. Since _compute_corrections
    # returns displacement vectors (ref - draw), we pair them with the resampled
    # drawing contour positions. We reconstruct positions from the draw contour
    # later. For now, we use the item's anchor points as proxies.
    #
    # Since we don't have explicit pixel positions for correction vectors, we
    # distribute them evenly around the item's bounding box perimeter and
    # interpolate. This is a practical approximation that works well for the
    # closed-loop correction use case.

    points = item["points"]
    if not points or not correction_vectors:
        return []

    # Convert all correction vectors into a spatial lookup: we distribute them
    # evenly along a parameterized path around the item's bounding box.
    n_corrections = len(correction_vectors)

    adjusted: list[dict] = []
    total_points = len(points)

    for pt_idx, pt in enumerate(points):
        old_ax, old_ay = pt["anchor"]

        # Convert anchor to pixel space
        px, py = _ai_to_pixel(
            old_ax, old_ay, ab_left, ab_top, ab_width, ab_height,
            img_width, img_height,
        )

        # Map this point's parametric position (fraction along the path) to
        # the closest correction vector indices
        t = pt_idx / max(total_points, 1)
        center_idx = int(t * n_corrections) % n_corrections

        # Gather the K nearest correction vectors by index proximity
        half_k = num_nearest // 2
        indices = [
            (center_idx + offset) % n_corrections
            for offset in range(-half_k, half_k + 1)
        ]
        # Remove duplicates while preserving order
        seen: set[int] = set()
        unique_indices: list[int] = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                unique_indices.append(i)

        # Average the correction vectors
        avg_dx = sum(correction_vectors[i]["dx"] for i in unique_indices) / len(unique_indices)
        avg_dy = sum(correction_vectors[i]["dy"] for i in unique_indices) / len(unique_indices)

        # Apply damped correction in pixel space
        new_px = px + correction_strength * avg_dx
        new_py = py + correction_strength * avg_dy

        # Convert back to AI coordinates
        new_ax, new_ay = _pixel_to_ai(
            new_px, new_py, ab_left, ab_top, ab_width, ab_height,
            img_width, img_height,
        )

        adjusted.append({
            "idx": pt_idx,
            "x": round(new_ax, 4),
            "y": round(new_ay, 4),
            "old_x": round(old_ax, 4),
            "old_y": round(old_ay, 4),
        })

    return adjusted


# ---------------------------------------------------------------------------
# Phase D: Build JSX to apply corrections
# ---------------------------------------------------------------------------


def _build_apply_jsx(layer_name: str, corrections: list[dict]) -> str:
    """Build JSX that applies anchor point corrections to pathItems.

    Each entry in corrections has:
        item_index: int  — index of the pathItem on the layer
        points: list of {idx, x, y, old_x, old_y}
    """
    escaped_layer = escape_jsx_string(layer_name)
    corrections_json = json.dumps(corrections)

    return f"""
(function() {{
    var doc = app.activeDocument;
    var layer = doc.layers.getByName("{escaped_layer}");
    var corrections = {corrections_json};
    var totalMoved = 0;
    for (var c = 0; c < corrections.length; c++) {{
        var corr = corrections[c];
        var pi = layer.pathItems[corr.item_index];
        for (var p = 0; p < corr.points.length; p++) {{
            var pt = corr.points[p];
            var oldAnchor = pi.pathPoints[pt.idx].anchor;
            var dx = pt.x - oldAnchor[0];
            var dy = pt.y - oldAnchor[1];
            pi.pathPoints[pt.idx].anchor = [pt.x, pt.y];
            // Translate handles by the same delta to preserve curve shape
            pi.pathPoints[pt.idx].leftDirection = [
                pi.pathPoints[pt.idx].leftDirection[0] + dx,
                pi.pathPoints[pt.idx].leftDirection[1] + dy
            ];
            pi.pathPoints[pt.idx].rightDirection = [
                pi.pathPoints[pt.idx].rightDirection[0] + dx,
                pi.pathPoints[pt.idx].rightDirection[1] + dy
            ];
            totalMoved++;
        }}
    }}
    return JSON.stringify({{adjusted: corrections.length, totalMoved: totalMoved}});
}})();
"""


# ---------------------------------------------------------------------------
# Phase E: Convergence scoring
# ---------------------------------------------------------------------------


def _score_convergence(
    ref_img: np.ndarray,
    draw_img: np.ndarray,
    min_area: float,
) -> tuple[float, int, int, int]:
    """Compute convergence score between reference and drawing images.

    If calibration data exists (from pixel_deviation_scorer), uses
    Hausdorff-based mean contour distance for more accurate scoring.
    Falls back to the original pixel-similarity + match-ratio blend
    when no calibration file is present.

    Returns (convergence, matched_count, ref_count, draw_count).
    """
    ref_contours = _extract_contours(ref_img, min_area)
    draw_contours = _extract_contours(draw_img, min_area)
    matched_pairs = _match_contours(ref_contours, draw_contours)

    # Check for calibration data — if present, use Hausdorff-based scoring
    calibration = load_calibration()
    if calibration is not None:
        # Convert OpenCV contours (Nx1x2) to Nx2 arrays for the scorer
        ref_arrays = [c.reshape(-1, 2).astype(np.float64) for c in ref_contours]
        draw_arrays = [c.reshape(-1, 2).astype(np.float64) for c in draw_contours]

        # Use calibrated reference_scale if stored, otherwise auto-compute
        cal_scale = calibration.get("reference_scale")
        result = score_pixel_deviation(ref_arrays, draw_arrays, reference_scale=cal_scale)

        convergence = result["score"]
        return convergence, result["matched_pairs"], len(ref_contours), len(draw_contours)

    # Fallback: original pixel-similarity + match-ratio scoring
    gray_ref = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
    gray_draw = cv2.cvtColor(draw_img, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_ref, gray_draw)
    pixel_similarity = 1.0 - (float(np.mean(diff)) / 255.0)

    match_ratio = len(matched_pairs) / max(len(ref_contours), 1)
    convergence = 0.5 * pixel_similarity + 0.5 * match_ratio

    return convergence, len(matched_pairs), len(ref_contours), len(draw_contours)


# ---------------------------------------------------------------------------
# Overlay drawing
# ---------------------------------------------------------------------------


def _draw_correction_overlay(
    ref_img: np.ndarray,
    draw_img: np.ndarray,
    label: str,
    convergence: float,
) -> np.ndarray:
    """Create a blended overlay showing ref vs drawing with convergence label."""
    overlay = cv2.addWeighted(ref_img, 0.5, draw_img, 0.5, 0)
    text = f"{label} convergence: {convergence:.3f}"
    cv2.putText(
        overlay, text, (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
    )
    return overlay


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_auto_correct tool."""

    @mcp.tool(
        name="adobe_ai_auto_correct",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_auto_correct(params: AiAutoCorrectInput) -> str:
        """Compare drawing layer against a reference image and auto-correct anchor points.

        Runs a closed-loop pipeline: read pathItems, export artboard, extract
        contours via OpenCV, compute correction vectors, then apply damped
        anchor-point adjustments via JSX. Supports multiple iterations to
        converge toward the reference.
        """
        # ── Validate reference image ─────────────────────────────────
        if not os.path.isfile(params.reference_path):
            return json.dumps({"error": f"Reference image not found: {params.reference_path}"})

        ref_img = cv2.imread(params.reference_path)
        if ref_img is None:
            return json.dumps({"error": f"Could not decode reference image: {params.reference_path}"})

        img_height, img_width = ref_img.shape[:2]
        img_area = img_height * img_width
        min_area = img_area * (params.min_area_pct / 100.0)

        # Track temp files for cleanup
        temp_files: list[str] = []

        # Track metrics across iterations
        before_convergence: float | None = None
        after_convergence: float = 0.0
        total_shapes_adjusted = 0
        total_points_moved = 0
        largest_correction_px = 0.0
        iterations_run = 0

        try:
            for iteration in range(params.max_iterations):
                iterations_run += 1

                # ── Phase A: Read drawing state via JSX ──────────────
                read_jsx = _build_read_jsx(params.drawing_layer)
                read_result = await _async_run_jsx("illustrator", read_jsx)
                if not read_result["success"]:
                    return json.dumps({
                        "error": f"Failed to read drawing layer: {read_result.get('stderr', 'Unknown error')}",
                        "iteration": iteration,
                    })

                try:
                    drawing_state = json.loads(read_result["stdout"])
                except (json.JSONDecodeError, TypeError):
                    return json.dumps({
                        "error": f"Invalid JSON from drawing layer read: {read_result.get('stdout', '')}",
                        "iteration": iteration,
                    })

                items = drawing_state.get("items", [])
                artboard_rect = drawing_state.get("artboardRect", [0, 0, 800, -600])

                if not items:
                    return json.dumps({
                        "error": f"No pathItems found on layer '{params.drawing_layer}'",
                        "iteration": iteration,
                    })

                # Parse artboard geometry
                ab_left = artboard_rect[0]
                ab_top = artboard_rect[1]
                ab_right = artboard_rect[2]
                ab_bottom = artboard_rect[3]
                ab_width = ab_right - ab_left
                ab_height = ab_top - ab_bottom  # positive because top > bottom in AI

                if ab_width <= 0 or ab_height <= 0:
                    return json.dumps({
                        "error": f"Invalid artboard dimensions: {artboard_rect}",
                        "iteration": iteration,
                    })

                # ── Phase B: Export artboard as PNG ───────────────────
                tmp_export = tempfile.mktemp(suffix=".png", prefix="ai_autocorr_")
                temp_files.append(tmp_export)

                export_jsx = _build_export_jsx(tmp_export)
                export_result = await _async_run_jsx("illustrator", export_jsx)
                if not export_result["success"]:
                    return json.dumps({
                        "error": f"Failed to export artboard: {export_result.get('stderr', 'Unknown error')}",
                        "iteration": iteration,
                    })

                draw_img = cv2.imread(tmp_export)
                if draw_img is None:
                    return json.dumps({
                        "error": f"Could not decode exported artboard: {tmp_export}",
                        "iteration": iteration,
                    })

                # Resize drawing to match reference dimensions
                draw_img = cv2.resize(draw_img, (img_width, img_height))

                # ── Score before correction (first iteration only) ───
                if before_convergence is None:
                    before_convergence, _, _, _ = _score_convergence(
                        ref_img, draw_img, min_area,
                    )

                # ── Extract and match contours ───────────────────────
                ref_contours = _extract_contours(ref_img, min_area)
                draw_contours = _extract_contours(draw_img, min_area)
                matched_pairs = _match_contours(ref_contours, draw_contours)

                if not matched_pairs:
                    # Nothing to correct — no contour matches found
                    after_convergence, _, _, _ = _score_convergence(
                        ref_img, draw_img, min_area,
                    )
                    break

                # ── Phase C: Map corrections to AI pathItems ─────────
                used_item_indices: set[int] = set()
                all_corrections: list[dict] = []
                iter_largest_px = 0.0

                for ri, di in matched_pairs:
                    # Compute correction vectors in pixel space
                    corrections, hausdorff = _compute_corrections(
                        ref_contours[ri], draw_contours[di],
                    )

                    # Find the AI pathItem closest to this drawing contour's centroid
                    dcx, dcy = _contour_centroid(draw_contours[di])
                    item_idx = _find_closest_item(
                        items, dcx, dcy,
                        ab_left, ab_top, ab_width, ab_height,
                        img_width, img_height,
                        used_item_indices,
                    )

                    if item_idx is None:
                        continue

                    used_item_indices.add(item_idx)

                    # Get the actual item dict by index
                    item = next((it for it in items if it["index"] == item_idx), None)
                    if item is None:
                        continue

                    # Compute per-anchor corrections
                    anchor_adjustments = _compute_anchor_corrections(
                        item, corrections, params.correction_strength,
                        ab_left, ab_top, ab_width, ab_height,
                        img_width, img_height,
                    )

                    if not anchor_adjustments:
                        continue

                    # Track largest correction in pixels for this iteration
                    for adj in anchor_adjustments:
                        old_px, old_py = _ai_to_pixel(
                            adj["old_x"], adj["old_y"],
                            ab_left, ab_top, ab_width, ab_height,
                            img_width, img_height,
                        )
                        new_px, new_py = _ai_to_pixel(
                            adj["x"], adj["y"],
                            ab_left, ab_top, ab_width, ab_height,
                            img_width, img_height,
                        )
                        corr_dist = math.hypot(new_px - old_px, new_py - old_py)
                        if corr_dist > iter_largest_px:
                            iter_largest_px = corr_dist

                    all_corrections.append({
                        "item_index": item_idx,
                        "points": anchor_adjustments,
                    })

                if iter_largest_px > largest_correction_px:
                    largest_correction_px = iter_largest_px

                # ── Phase D: Apply corrections via JSX ───────────────
                if all_corrections:
                    apply_jsx = _build_apply_jsx(params.drawing_layer, all_corrections)
                    apply_result = await _async_run_jsx("illustrator", apply_jsx)
                    if not apply_result["success"]:
                        return json.dumps({
                            "error": f"Failed to apply corrections: {apply_result.get('stderr', 'Unknown error')}",
                            "iteration": iteration,
                        })

                    # Tally metrics
                    total_shapes_adjusted += len(all_corrections)
                    for corr in all_corrections:
                        total_points_moved += len(corr["points"])

                # ── Phase E: Re-score after correction ───────────────
                # Re-export to get the updated artboard image
                tmp_rescore = tempfile.mktemp(suffix=".png", prefix="ai_autocorr_rescore_")
                temp_files.append(tmp_rescore)

                rescore_jsx = _build_export_jsx(tmp_rescore)
                rescore_result = await _async_run_jsx("illustrator", rescore_jsx)
                if rescore_result["success"]:
                    rescore_img = cv2.imread(tmp_rescore)
                    if rescore_img is not None:
                        rescore_img = cv2.resize(rescore_img, (img_width, img_height))
                        after_convergence, _, _, _ = _score_convergence(
                            ref_img, rescore_img, min_area,
                        )
                    else:
                        # Could not read re-scored image; use pre-correction score
                        after_convergence, _, _, _ = _score_convergence(
                            ref_img, draw_img, min_area,
                        )
                else:
                    after_convergence, _, _, _ = _score_convergence(
                        ref_img, draw_img, min_area,
                    )

                # Check if we've reached the convergence target
                if after_convergence >= params.convergence_target:
                    break

            # ── Generate final overlay ───────────────────────────────
            overlay_path = tempfile.mktemp(suffix="_autocorrect_overlay.png", prefix="ai_")

            # Re-export one final time for the overlay (reuse the last rescore if available)
            final_draw = None
            for tf in reversed(temp_files):
                if os.path.isfile(tf):
                    final_draw = cv2.imread(tf)
                    if final_draw is not None:
                        final_draw = cv2.resize(final_draw, (img_width, img_height))
                        break

            if final_draw is not None:
                overlay = _draw_correction_overlay(
                    ref_img, final_draw, "After", after_convergence,
                )
                cv2.imwrite(overlay_path, overlay)
            else:
                overlay_path = ""

            # ── Build result payload ─────────────────────────────────
            improvement = (after_convergence - (before_convergence or 0.0))

            payload = {
                "iterations_run": iterations_run,
                "before_convergence": round(before_convergence or 0.0, 3),
                "after_convergence": round(after_convergence, 3),
                "improvement": round(improvement, 3),
                "shapes_adjusted": total_shapes_adjusted,
                "total_points_moved": total_points_moved,
                "largest_correction_px": round(largest_correction_px, 1),
                "reached_target": after_convergence >= params.convergence_target,
                "overlay_path": overlay_path,
            }

            return json.dumps(payload)

        finally:
            # ── Clean up temp files ──────────────────────────────────
            for tf in temp_files:
                try:
                    if os.path.isfile(tf):
                        os.remove(tf)
                except OSError:
                    pass
