"""Analyze a reference image for geometric forms using OpenCV.

Returns measured shapes (vertices, edges, angles, proportions) — not guesses.
Pure Python analysis: no JSX, no Illustrator interaction.
"""

import json
import os

import cv2
import numpy as np

from adobe_mcp.apps.illustrator.models import AiAnalyzeReferenceInput


def _classify_shape(vertex_count: int, width: float, height: float) -> str:
    """Classify a shape by its approximate polygon vertex count and dimensions."""
    if vertex_count == 3:
        return "triangle"
    elif vertex_count == 4:
        # Distinguish square, rectangle, and trapezoid by aspect ratio
        aspect = min(width, height) / max(width, height) if max(width, height) > 0 else 1.0
        if aspect > 0.9:
            return "square"
        elif aspect > 0.4:
            return "rectangle"
        else:
            return "trapezoid"
    elif vertex_count == 5:
        return "pentagon"
    elif vertex_count == 6:
        return "hexagon"
    elif vertex_count == 7:
        return "heptagon"
    elif vertex_count == 8:
        return "octagon"
    else:
        # >8 vertices — likely a circle or ellipse
        return "circle/ellipse"


def _edge_lengths(approx_points: np.ndarray) -> list[float]:
    """Compute edge lengths between consecutive vertices of an approximate polygon."""
    pts = approx_points.reshape(-1, 2)
    n = len(pts)
    lengths = []
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        length = float(np.linalg.norm(p2 - p1))
        lengths.append(round(length, 1))
    return lengths


def _edge_ratios(lengths: list[float]) -> list[float]:
    """Compute ratio of each edge length to the longest edge."""
    max_len = max(lengths) if lengths else 1.0
    if max_len == 0:
        return [0.0] * len(lengths)
    return [round(l / max_len, 2) for l in lengths]


# ---------------------------------------------------------------------------
# Reusable contour extraction at a single threshold pair
# ---------------------------------------------------------------------------

def _analyze_at_thresholds(
    gray_blurred: np.ndarray,
    canny_low: int,
    canny_high: int,
    min_area: float,
    max_contours: int,
    *,
    retrieval_mode: int = cv2.RETR_EXTERNAL,
) -> tuple[list[dict], int, np.ndarray | None, object | None]:
    """Run Canny + findContours + shape analysis at one threshold pair.

    Returns (shapes, total_found, edges_image, hierarchy).
    hierarchy is non-None only when retrieval_mode == RETR_TREE.
    """
    edges = cv2.Canny(gray_blurred, canny_low, canny_high)
    contours, hierarchy = cv2.findContours(edges, retrieval_mode, cv2.CHAIN_APPROX_SIMPLE)
    total_found = len(contours)

    # Filter by minimum area
    indexed_contours = [(i, c) for i, c in enumerate(contours) if cv2.contourArea(c) >= min_area]

    # Sort by area descending, cap at max_contours
    indexed_contours.sort(key=lambda pair: cv2.contourArea(pair[1]), reverse=True)
    indexed_contours = indexed_contours[:max_contours]

    shapes: list[dict] = []
    for new_idx, (orig_idx, contour) in enumerate(indexed_contours):
        arc_len = cv2.arcLength(contour, True)
        epsilon = 0.02 * arc_len
        approx = cv2.approxPolyDP(contour, epsilon, True)
        vertex_count = len(approx)

        rect = cv2.minAreaRect(contour)
        center, (w, h), rotation = rect

        shape_type = _classify_shape(vertex_count, w, h)
        area = cv2.contourArea(contour)
        perimeter = arc_len

        moments = cv2.moments(contour)
        if moments["m00"] != 0:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        else:
            cx, cy = float(center[0]), float(center[1])

        edges_list = _edge_lengths(approx)
        ratios = _edge_ratios(edges_list)
        bx, by, bw, bh = cv2.boundingRect(contour)
        approx_pts = approx.reshape(-1, 2).tolist()

        shape_dict: dict = {
            "index": new_idx,
            "_orig_contour_index": orig_idx,  # kept for hierarchy lookup
            "type": shape_type,
            "vertices": vertex_count,
            "center": [round(cx, 1), round(cy, 1)],
            "width": round(float(w), 1),
            "height": round(float(h), 1),
            "rotation_deg": round(float(rotation), 1),
            "area": int(area),
            "perimeter": round(perimeter, 1),
            "edge_lengths": edges_list,
            "edge_ratios": ratios,
            "bounding_rect": [bx, by, bw, bh],
            "approx_points": approx_pts,
        }
        shapes.append(shape_dict)

    return shapes, total_found, edges, hierarchy


# ---------------------------------------------------------------------------
# Evolution 6 — Multi-scale analysis
# ---------------------------------------------------------------------------

_MULTI_SCALE_THRESHOLDS: list[tuple[int, int, str]] = [
    (30, 90, "bold"),
    (50, 150, "medium"),
    (80, 200, "fine"),
]

_CENTROID_MERGE_DISTANCE = 20.0  # px — shapes within this radius are considered the same


def _centroid_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two [x, y] centroids."""
    return float(np.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2))


def _analyze_multi_scale(
    gray_blurred: np.ndarray,
    min_area: float,
    max_contours: int,
    *,
    retrieval_mode: int = cv2.RETR_EXTERNAL,
) -> tuple[list[dict], int]:
    """Run contour extraction at 3 Canny scales and merge by centroid proximity.

    Shapes appearing at multiple scales are tagged with the *lowest* (boldest) threshold.
    Returns (merged_shapes, total_contours_across_scales).
    """
    merged: list[dict] = []
    total_across_scales = 0

    for low, high, scale_tag in _MULTI_SCALE_THRESHOLDS:
        shapes, total_found, _, _ = _analyze_at_thresholds(
            gray_blurred, low, high, min_area, max_contours,
            retrieval_mode=retrieval_mode,
        )
        total_across_scales += total_found

        for shape in shapes:
            # Check if this shape already exists in merged set (by centroid proximity)
            duplicate = False
            for existing in merged:
                if _centroid_distance(shape["center"], existing["center"]) < _CENTROID_MERGE_DISTANCE:
                    # Already present — keep the boldest (first-seen) scale tag
                    duplicate = True
                    break
            if not duplicate:
                shape["scale"] = scale_tag
                merged.append(shape)

    # Re-index after merge
    for idx, shape in enumerate(merged):
        shape["index"] = idx

    return merged, total_across_scales


# ---------------------------------------------------------------------------
# Evolution 9 — Decomposition with hierarchy and drawing plan
# ---------------------------------------------------------------------------

def _build_decomposition(shapes: list[dict], hierarchy: np.ndarray | None) -> dict:
    """Attach parent/child relationships and produce a drawing plan.

    hierarchy is the OpenCV hierarchy array from RETR_TREE:
        hierarchy[0][i] == [next, prev, first_child, parent]

    Shapes are grouped into layers by nesting depth:
        depth 0 → "background"
        depth 1 → "features"
        depth 2+ → "details"
    """
    if hierarchy is None or len(shapes) == 0:
        return {}

    hier = hierarchy[0]  # shape (N, 4)

    # Build a map from original contour index → shape index for fast lookup
    orig_to_shape: dict[int, int] = {}
    for s in shapes:
        orig_to_shape[s["_orig_contour_index"]] = s["index"]

    # Compute depth for each original contour index present in shapes
    def _depth_of(orig_idx: int) -> int:
        """Walk the parent chain to compute nesting depth."""
        depth = 0
        cur = orig_idx
        while cur >= 0 and cur < len(hier):
            parent = hier[cur][3]
            if parent < 0:
                break
            depth += 1
            cur = parent
        return depth

    # Annotate each shape with parent_index, children, and depth
    for shape in shapes:
        oi = shape["_orig_contour_index"]
        depth = _depth_of(oi)
        shape["depth"] = depth

        # Find parent shape (may not be in our filtered set — walk up until we find one)
        parent_orig = hier[oi][3] if oi < len(hier) else -1
        parent_shape_idx = None
        while parent_orig >= 0:
            if parent_orig in orig_to_shape:
                parent_shape_idx = orig_to_shape[parent_orig]
                break
            parent_orig = hier[parent_orig][3] if parent_orig < len(hier) else -1
        shape["parent_index"] = parent_shape_idx

        # Find direct children that survived filtering
        children: list[int] = []
        first_child = hier[oi][2] if oi < len(hier) else -1
        child = first_child
        visited: set[int] = set()
        while child >= 0 and child not in visited:
            visited.add(child)
            if child in orig_to_shape:
                children.append(orig_to_shape[child])
            child = hier[child][0] if child < len(hier) else -1
        shape["children"] = children

    # Build layer grouping by depth
    layer_names = {0: "background", 1: "features"}
    layer_buckets: dict[str, list[int]] = {}
    for shape in shapes:
        d = shape["depth"]
        layer_name = layer_names.get(d, "details")
        layer_buckets.setdefault(layer_name, []).append(shape["index"])

    # Canonical layer ordering
    ordered_layer_names = ["background", "features", "details"]
    layers = []
    z = 0
    for ln in ordered_layer_names:
        if ln in layer_buckets:
            layers.append({
                "name": ln,
                "shapes": sorted(layer_buckets[ln]),
                "z_order": z,
            })
            z += 1

    # Draw order: largest/outermost first, nested on top
    draw_order = []
    for layer in layers:
        draw_order.extend(layer["shapes"])

    drawing_plan = {
        "layers": layers,
        "draw_order": draw_order,
        "note": "Draw largest/outermost shapes first, nested shapes on top",
    }

    return drawing_plan


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def _analyze_image(params: AiAnalyzeReferenceInput) -> dict:
    """Run the full OpenCV analysis pipeline on the reference image."""
    # Step 1: Load image
    img = cv2.imread(params.image_path)
    if img is None:
        return {"error": f"Could not read image at {params.image_path}"}

    img_h, img_w = img.shape[:2]
    total_area = img_h * img_w
    min_area = (params.min_area_pct / 100.0) * total_area

    # Step 2: Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Step 3: Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Choose retrieval mode — RETR_TREE when decompose is requested
    retrieval_mode = cv2.RETR_TREE if params.decompose else cv2.RETR_EXTERNAL

    # Step 4+: Contour extraction — multi-scale or single-pass
    hierarchy = None
    if params.multi_scale:
        shapes, total_found = _analyze_multi_scale(
            blurred, min_area, params.max_contours,
            retrieval_mode=retrieval_mode,
        )
        # For decompose + multi_scale, we need hierarchy from a single pass
        # Use the medium thresholds as the canonical hierarchy source
        if params.decompose:
            _, _, _, hierarchy = _analyze_at_thresholds(
                blurred, 50, 150, min_area, params.max_contours,
                retrieval_mode=cv2.RETR_TREE,
            )
    else:
        shapes, total_found, _, hierarchy = _analyze_at_thresholds(
            blurred, params.canny_low, params.canny_high,
            min_area, params.max_contours,
            retrieval_mode=retrieval_mode,
        )

    # Build decomposition if requested
    drawing_plan = None
    if params.decompose:
        drawing_plan = _build_decomposition(shapes, hierarchy)

    # Clean internal bookkeeping fields before output
    for shape in shapes:
        shape.pop("_orig_contour_index", None)

    result: dict = {
        "image_size": [img_w, img_h],
        "total_contours_found": total_found,
        "shapes_returned": len(shapes),
        "shapes": shapes,
    }

    if params.multi_scale:
        result["analysis_mode"] = "multi_scale"
        result["scales_used"] = [
            {"thresholds": [low, high], "label": label}
            for low, high, label in _MULTI_SCALE_THRESHOLDS
        ]

    if drawing_plan:
        result["drawing_plan"] = drawing_plan

    return result


def register(mcp):
    """Register the adobe_ai_analyze_reference tool."""

    @mcp.tool(
        name="adobe_ai_analyze_reference",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_analyze_reference(params: AiAnalyzeReferenceInput) -> str:
        """Analyze a reference image with OpenCV to extract measured geometric forms.

        Returns a JSON manifest of detected shapes with vertices, edge lengths,
        proportions, rotation angles, and centroids. Use this to understand the
        precise geometry of a reference before recreating it in Illustrator.
        """
        # Validate image path exists before processing
        if not os.path.isfile(params.image_path):
            return f"Error: Could not read image at {params.image_path}"

        result = _analyze_image(params)

        if "error" in result:
            return f"Error: {result['error']}"

        return json.dumps(result, indent=2)
