"""Closed-loop 3D-to-2D feedback system.

Wires spatial_pipeline, pixel_deviation_scorer, path_gradient_approx,
and correction_learning into a self-correcting cycle where projection
errors become correction signals for future reconstructions.

Each run:
1. Project mesh faces to 2D
2. Score against reference image
3. Compute corrections and optimize paths
4. Store projection deltas for future use

Future runs benefit: stored deltas are pre-applied to initial projections.
"""

import hashlib
import json
import os
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.threed.mesh_face_grouper import (
    load_mesh_from_obj,
    group_faces_by_normal,
    project_group_boundaries,
    classify_face_groups,
)
from adobe_mcp.apps.illustrator.ml_vision.path_gradient_approx import (
    rasterize_contours,
    compute_loss,
    optimize_paths_approx,
)
from adobe_mcp.apps.illustrator.analysis.correction_learning import (
    store_projection_delta,
    pre_correct_projection,
    _load_projection_corrections,
    PROJECTION_CORRECTIONS_PATH,
)
from adobe_mcp.apps.illustrator.path_validation import validate_safe_path


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class FeedbackLoop3DInput(BaseModel):
    """Control the closed-loop 3D-to-2D feedback system."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="run_cycle",
        description=(
            "Action: run_cycle, status, clear_deltas. "
            "run_cycle = run the feedback loop. "
            "status = report module availability. "
            "clear_deltas = remove stored projection deltas."
        ),
    )
    reference_path: Optional[str] = Field(
        default=None,
        description="Path to reference image (required for run_cycle)",
    )
    mesh_path: Optional[str] = Field(
        default=None,
        description="Path to OBJ mesh file (required for run_cycle)",
    )
    max_rounds: int = Field(
        default=5,
        description="Maximum correction rounds",
    )
    convergence_target: float = Field(
        default=0.7,
        description="Stop when score >= this value",
    )
    min_improvement: float = Field(
        default=0.02,
        description="Stop if round-over-round improvement < this (plateau)",
    )
    damping: float = Field(
        default=0.3,
        description="Damping factor for correction application (0=no correction, 1=full)",
    )
    angle_threshold: float = Field(
        default=15.0,
        description="Face grouping angle threshold in degrees",
    )
    camera_yaw: float = Field(
        default=0.0,
        description="Camera yaw angle in degrees for 2D projection",
    )
    camera_pitch: float = Field(
        default=0.0,
        description="Camera pitch angle in degrees for 2D projection",
    )
    scoring_method: str = Field(
        default="auto",
        description=(
            "Scoring method: 'mesh_projection' (3D mesh → 2D, requires OBJ), "
            "'form_edge' (normal-map form edges as ground truth, requires reference image), "
            "'auto' (selects best available: form_edge if DSINE available, "
            "mesh_projection if mesh provided, heuristic otherwise)."
        ),
    )
    delta_storage_path: Optional[str] = Field(
        default=None,
        description="Custom path for projection delta storage (testing)",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_image_hash(image_path: str) -> str:
    """Compute SHA-256 hash of a reference image file for cross-image weighting."""
    safe_path = validate_safe_path(image_path)
    sha256 = hashlib.sha256()
    with open(safe_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _extract_reference_contours(reference_gray: np.ndarray) -> list[np.ndarray]:
    """Extract contours from a grayscale reference image.

    Uses Canny edge detection + contour finding, filtering out
    very small contours (< 1% of image area).

    Args:
        reference_gray: Grayscale float32 image [0, 1].

    Returns:
        List of Nx2 float64 contour arrays.
    """
    # Convert to uint8 for OpenCV processing
    gray_u8 = (reference_gray * 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(gray_u8, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter out tiny contours (noise)
    img_area = reference_gray.shape[0] * reference_gray.shape[1]
    min_area = img_area * 0.01
    valid = []
    for c in contours:
        if cv2.contourArea(c) >= min_area:
            # Reshape from (N, 1, 2) to (N, 2)
            valid.append(c.reshape(-1, 2).astype(np.float64))
    return valid


def _match_by_centroid(
    projected: list[np.ndarray],
    reference: list[np.ndarray],
) -> list[tuple[int, int]]:
    """Match projected contours to reference contours by nearest centroid.

    Greedy matching: each projected contour is matched to the closest
    unmatched reference contour by centroid Euclidean distance.

    Args:
        projected: List of projected Nx2 contour arrays.
        reference: List of reference Mx2 contour arrays.

    Returns:
        List of (proj_idx, ref_idx) pairs.
    """
    if not projected or not reference:
        return []

    proj_centroids = [np.mean(c, axis=0) for c in projected]
    ref_centroids = [np.mean(c, axis=0) for c in reference]

    used_ref: set[int] = set()
    matched: list[tuple[int, int]] = []

    for pi, pc in enumerate(proj_centroids):
        best_ri: int | None = None
        best_dist = float("inf")
        for ri, rc in enumerate(ref_centroids):
            if ri in used_ref:
                continue
            d = float(np.linalg.norm(pc - rc))
            if d < best_dist:
                best_dist = d
                best_ri = ri
        if best_ri is not None:
            matched.append((pi, best_ri))
            used_ref.add(best_ri)

    return matched


def _compute_displacements(
    projected: np.ndarray,
    reference: np.ndarray,
) -> np.ndarray:
    """Compute per-point displacement from projected to nearest reference point.

    For each point in the projected contour, finds the nearest point
    on the reference contour and computes the displacement vector.

    Args:
        projected: Nx2 projected contour points.
        reference: Mx2 reference contour points.

    Returns:
        Nx2 displacement array (reference_point - projected_point).
    """
    # For each projected point, find nearest reference point
    displacements = np.zeros_like(projected)
    for i, pp in enumerate(projected):
        # Euclidean distance to all reference points
        dists = np.linalg.norm(reference - pp, axis=1)
        nearest_idx = int(np.argmin(dists))
        displacements[i] = reference[nearest_idx] - pp
    return displacements


# ---------------------------------------------------------------------------
# Core feedback loop
# ---------------------------------------------------------------------------


class FeedbackLoop3D:
    """Self-correcting 3D-to-2D feedback loop.

    Runs iterative correction rounds where projection errors become
    displacement signals, damped and applied to converge projected
    contours toward the reference image.
    """

    def __init__(self, delta_storage_path: str | None = None):
        """Initialize feedback loop.

        Args:
            delta_storage_path: Custom path for projection delta JSON storage.
                Defaults to the standard PROJECTION_CORRECTIONS_PATH.
        """
        self.delta_storage_path = delta_storage_path

    def run_cycle(
        self,
        reference_path: str,
        mesh_path: str | None = None,
        max_rounds: int = 5,
        convergence_target: float = 0.7,
        min_improvement: float = 0.02,
        damping: float = 0.3,
        angle_threshold: float = 15.0,
        camera_yaw: float = 0.0,
        camera_pitch: float = 0.0,
        scoring_method: str = "auto",
    ) -> dict:
        """Run the complete feedback cycle.

        ROUND 1 (naive projection):
          1. Load mesh (mesh_path is required)
          2. Group faces by normals via mesh_face_grouper
          3. Classify face groups
          4. Project face boundaries to 2D
          5. Apply any stored projection deltas (pre_correct_projection)
          6. Load reference image as grayscale float32 [0,1]
          7. Rasterize projected contours
          8. Score: compute_loss(rasterized, reference)

        ROUND 2..N (correction):
          1. For each projected contour, find nearest reference contour
          2. Match projected vs reference contours by nearest centroid
          3. For each matched pair, compute per-point displacement
          4. Apply damped corrections: new_point = old + damping * displacement
          5. Run path_gradient_approx optimization (20 iterations)
          6. Re-score
          7. Check termination conditions

        Args:
            reference_path: Path to the reference image.
            mesh_path: Path to OBJ mesh file. Required (no reconstruction fallback).
            max_rounds: Maximum number of correction rounds.
            convergence_target: Stop if score >= this value.
            min_improvement: Stop if improvement < this (plateau).
            damping: Fraction of displacement to apply each round (0-1).
            angle_threshold: Face grouping angle threshold in degrees.
            camera_yaw: Camera yaw for projection.
            camera_pitch: Camera pitch for projection.

        Returns:
            Dict with:
                rounds_run, scores_per_round, best_score, best_round,
                deltas_stored, face_groups_corrected, convergence_reason
        """
        # Resolve scoring method
        resolved_method = self._resolve_scoring_method(
            scoring_method, mesh_path, reference_path,
        )

        # Route to form_edge scoring if selected
        if resolved_method == "form_edge":
            return self._run_form_edge_cycle(
                reference_path=reference_path,
                max_rounds=max_rounds,
                convergence_target=convergence_target,
                min_improvement=min_improvement,
                damping=damping,
            )

        # Validate inputs for mesh_projection path
        if not mesh_path or not os.path.isfile(mesh_path):
            return {"error": f"mesh_path is required and must exist: {mesh_path}"}
        if not reference_path or not os.path.isfile(reference_path):
            return {"error": f"reference_path is required and must exist: {reference_path}"}

        # Path traversal validation
        try:
            mesh_path = validate_safe_path(mesh_path)
            reference_path = validate_safe_path(reference_path)
        except ValueError as exc:
            return {"error": f"Path validation failed: {exc}"}

        # Load mesh
        try:
            vertices, faces = load_mesh_from_obj(mesh_path)
        except Exception as exc:
            return {"error": f"Failed to load mesh: {exc}"}

        if len(faces) == 0:
            return {"error": "Mesh has no faces"}

        # Group faces by normal direction
        groups = group_faces_by_normal(vertices, faces, angle_threshold)

        # Classify and label groups
        labels = classify_face_groups(groups)

        # Project face group boundaries to 2D contours
        all_contours_3d = project_group_boundaries(
            groups, vertices, faces, camera_yaw, camera_pitch
        )

        # Build flat list of projected contours (primary boundary per group)
        # and corresponding labels for pre-correction lookup
        projected_contours: list[np.ndarray] = []
        contour_labels: list[str] = []

        for i, group in enumerate(groups):
            group_contours = all_contours_3d[i] if i < len(all_contours_3d) else []
            if group_contours and len(group_contours[0]) > 0:
                # Convert to Nx2 float64 numpy array
                contour_pts = np.array(group_contours[0], dtype=np.float64)
                # Ensure 2D — project_group_boundaries returns (x, y) tuples
                if contour_pts.ndim == 1:
                    contour_pts = contour_pts.reshape(-1, 2)
                projected_contours.append(contour_pts)
                contour_labels.append(labels.get(group["group_id"], "unknown"))

        if not projected_contours:
            return {"error": "No valid contours extracted from mesh face groups"}

        # Compute image hash for delta weighting
        image_hash = _compute_image_hash(reference_path)

        # Apply stored projection deltas to initial contours (learning from past runs)
        contours_as_lists = [c.tolist() for c in projected_contours]
        pre_corrected = pre_correct_projection(
            contours_as_lists,
            contour_labels,
            image_hash=image_hash,
            path=self.delta_storage_path,
        )
        # Convert back to numpy arrays
        projected_contours = [np.array(c, dtype=np.float64) for c in pre_corrected]

        # Load reference image as grayscale float32 [0, 1]
        ref_img = cv2.imread(reference_path, cv2.IMREAD_GRAYSCALE)
        if ref_img is None:
            return {"error": f"Could not read reference image: {reference_path}"}
        reference_float = ref_img.astype(np.float32) / 255.0
        canvas_size = reference_float.shape[:2]  # (H, W)

        # Normalize contours to reference image coordinate space
        # The projected contours from mesh_face_grouper are in orthographic
        # projection space. We need to scale them to fit the canvas.
        projected_contours = self._normalize_to_canvas(
            projected_contours, canvas_size
        )

        # --- ROUND 1: Naive projection score ---
        rasterized = rasterize_contours(
            [c.astype(np.int32) for c in projected_contours],
            canvas_size,
        )
        initial_score = 1.0 - compute_loss(rasterized, reference_float)

        scores_per_round = [initial_score]
        best_score = initial_score
        best_round = 0
        best_contours = [c.copy() for c in projected_contours]
        convergence_reason = "max_rounds"

        # Check if round 1 already meets target
        if initial_score >= convergence_target:
            convergence_reason = "target"
            # Store deltas even for good first-round scores
            deltas_stored = self._store_deltas(
                projected_contours, projected_contours,
                contour_labels, image_hash,
                initial_score, initial_score,
            )
            return {
                "rounds_run": 1,
                "scores_per_round": [round(s, 6) for s in scores_per_round],
                "best_score": round(best_score, 6),
                "best_round": best_round,
                "deltas_stored": deltas_stored,
                "face_groups_corrected": len(projected_contours),
                "convergence_reason": convergence_reason,
            }

        # Extract reference contours for matching
        ref_contours = _extract_reference_contours(reference_float)

        # --- ROUNDS 2..N: Correction loop ---
        current_contours = [c.copy() for c in projected_contours]
        prev_score = initial_score

        for round_num in range(1, max_rounds):
            # Step 1: Match projected contours to reference contours by centroid
            matches = _match_by_centroid(current_contours, ref_contours)

            if not matches:
                # No matches possible; try gradient optimization anyway
                optimized, opt_stats = optimize_paths_approx(
                    current_contours,
                    reference_float,
                    iterations=20,
                    lr=1.0,
                    epsilon=0.5,
                )
                current_contours = optimized
            else:
                # Step 2-3: Compute per-point displacements for matched pairs
                for pi, ri in matches:
                    displacements = _compute_displacements(
                        current_contours[pi], ref_contours[ri]
                    )
                    # Step 4: Apply damped corrections
                    current_contours[pi] = (
                        current_contours[pi] + damping * displacements
                    )

                # Step 5: Run path gradient optimization (20 iterations)
                optimized, opt_stats = optimize_paths_approx(
                    current_contours,
                    reference_float,
                    iterations=20,
                    lr=1.0,
                    epsilon=0.5,
                )
                current_contours = optimized

            # Step 6: Re-score
            rasterized = rasterize_contours(
                [c.astype(np.int32) for c in current_contours],
                canvas_size,
            )
            current_score = 1.0 - compute_loss(rasterized, reference_float)
            scores_per_round.append(current_score)

            # Track best
            if current_score > best_score:
                best_score = current_score
                best_round = round_num
                best_contours = [c.copy() for c in current_contours]

            # Step 7: Check termination conditions
            improvement = current_score - prev_score

            if current_score >= convergence_target:
                convergence_reason = "target"
                break

            if improvement < min_improvement and improvement >= 0:
                convergence_reason = "plateau"
                break

            if current_score < prev_score:
                convergence_reason = "diverging"
                break

            prev_score = current_score

        # Store projection deltas from best round
        deltas_stored = False
        if convergence_reason != "diverging":
            deltas_stored = self._store_deltas(
                projected_contours, best_contours,
                contour_labels, image_hash,
                initial_score, best_score,
            )

        return {
            "rounds_run": len(scores_per_round),
            "scores_per_round": [round(s, 6) for s in scores_per_round],
            "best_score": round(best_score, 6),
            "best_round": best_round,
            "deltas_stored": deltas_stored,
            "face_groups_corrected": len(projected_contours),
            "convergence_reason": convergence_reason,
        }

    @staticmethod
    def _resolve_scoring_method(
        scoring_method: str,
        mesh_path: str | None,
        reference_path: str | None,
    ) -> str:
        """Resolve 'auto' scoring method to a concrete method.

        Selection priority for 'auto':
        1. mesh_projection if mesh_path is provided (user explicitly supplied mesh)
        2. form_edge if only reference_path is available (mesh-free alternative)

        The explicit method names ('mesh_projection', 'form_edge') bypass
        auto-selection entirely.

        Args:
            scoring_method: User-specified method or 'auto'.
            mesh_path: Path to OBJ mesh (may be None).
            reference_path: Path to reference image (may be None).

        Returns:
            Resolved method string: 'form_edge' or 'mesh_projection'.
        """
        if scoring_method == "mesh_projection":
            return "mesh_projection"
        if scoring_method == "form_edge":
            return "form_edge"

        # auto: prefer mesh_projection when mesh is provided (user intent),
        # fall back to form_edge when no mesh is available
        if mesh_path and os.path.isfile(mesh_path):
            return "mesh_projection"

        # No mesh available — use form_edge (heuristic always available)
        return "form_edge"

    def _run_form_edge_cycle(
        self,
        reference_path: str,
        max_rounds: int = 5,
        convergence_target: float = 0.7,
        min_improvement: float = 0.02,
        damping: float = 0.3,
    ) -> dict:
        """Run feedback cycle using form edge extraction as ground truth.

        Instead of 3D mesh projection, uses form edge extraction on the
        reference image to produce ground-truth contours.  Then runs the
        same iterative correction loop (match, displace, optimize, score).

        This path does NOT require a mesh file -- only the reference image.

        Args:
            reference_path: Path to reference image.
            max_rounds: Maximum correction rounds.
            convergence_target: Stop when score >= this.
            min_improvement: Stop on plateau.
            damping: Correction damping factor.

        Returns:
            Same result dict structure as run_cycle.
        """
        from adobe_mcp.apps.illustrator.form_edge_pipeline import (
            extract_form_edges,
            edge_mask_to_contours,
        )

        # Validate reference
        if not reference_path or not os.path.isfile(reference_path):
            return {"error": f"reference_path is required and must exist: {reference_path}"}

        try:
            reference_path = validate_safe_path(reference_path)
        except ValueError as exc:
            return {"error": f"Path validation failed: {exc}"}

        # Extract form edges as ground truth
        edge_result = extract_form_edges(reference_path, backend="auto")
        if "error" in edge_result:
            return {"error": f"Form edge extraction failed: {edge_result['error']}"}

        form_mask = edge_result["form_edges"]
        backend_used = edge_result.get("backend", "auto")

        # Load reference image as grayscale float32 for scoring
        ref_img = cv2.imread(reference_path, cv2.IMREAD_GRAYSCALE)
        if ref_img is None:
            return {"error": f"Could not read reference image: {reference_path}"}
        reference_float = ref_img.astype(np.float32) / 255.0
        canvas_size = reference_float.shape[:2]  # (H, W)

        # Convert form edge mask directly to contours using edge_mask_to_contours
        # (the mask is already edges -- don't run Canny again via _extract_reference_contours)
        contour_dicts = edge_mask_to_contours(
            form_mask, simplify_tolerance=1.0, min_length=5, max_contours=50,
        )

        # Also try standard contour extraction from the reference image itself
        # as a fallback when the form edge mask has too few pixels for contouring
        ref_contours: list[np.ndarray] = []
        for cd in contour_dicts:
            pts = np.array(cd["points"], dtype=np.float64)
            if pts.ndim == 2 and pts.shape[0] >= 3:
                ref_contours.append(pts)

        if not ref_contours:
            # Fallback: extract from the reference image directly
            ref_contours = _extract_reference_contours(reference_float)

        if not ref_contours:
            return {
                "error": "No reference contours found from form edges or reference image.",
                "backend": backend_used,
            }

        # Initial projected contours = reference contours (starting point)
        projected_contours = [c.copy() for c in ref_contours]

        # Rasterize initial state for scoring
        rasterized = rasterize_contours(
            [c.astype(np.int32) for c in projected_contours],
            canvas_size,
        )
        initial_score = 1.0 - compute_loss(rasterized, reference_float)

        scores_per_round = [initial_score]
        best_score = initial_score
        best_round = 0
        convergence_reason = "max_rounds"

        if initial_score >= convergence_target:
            convergence_reason = "target"
            return {
                "rounds_run": 1,
                "scores_per_round": [round(s, 6) for s in scores_per_round],
                "best_score": round(best_score, 6),
                "best_round": best_round,
                "deltas_stored": False,
                "face_groups_corrected": len(projected_contours),
                "convergence_reason": convergence_reason,
                "scoring_method": "form_edge",
                "backend": backend_used,
            }

        # Correction loop
        current_contours = [c.copy() for c in projected_contours]
        prev_score = initial_score

        for round_num in range(1, max_rounds):
            # Match current contours to reference
            matches = _match_by_centroid(current_contours, ref_contours)

            if matches:
                for pi, ri in matches:
                    displacements = _compute_displacements(
                        current_contours[pi], ref_contours[ri]
                    )
                    current_contours[pi] = (
                        current_contours[pi] + damping * displacements
                    )

            # Optimize paths
            optimized, _ = optimize_paths_approx(
                current_contours,
                reference_float,
                iterations=20,
                lr=1.0,
                epsilon=0.5,
            )
            current_contours = optimized

            # Re-score
            rasterized = rasterize_contours(
                [c.astype(np.int32) for c in current_contours],
                canvas_size,
            )
            current_score = 1.0 - compute_loss(rasterized, reference_float)
            scores_per_round.append(current_score)

            if current_score > best_score:
                best_score = current_score
                best_round = round_num

            # Check termination
            improvement = current_score - prev_score

            if current_score >= convergence_target:
                convergence_reason = "target"
                break

            if improvement < min_improvement and improvement >= 0:
                convergence_reason = "plateau"
                break

            if current_score < prev_score:
                convergence_reason = "diverging"
                break

            prev_score = current_score

        return {
            "rounds_run": len(scores_per_round),
            "scores_per_round": [round(s, 6) for s in scores_per_round],
            "best_score": round(best_score, 6),
            "best_round": best_round,
            "deltas_stored": False,
            "face_groups_corrected": len(projected_contours),
            "convergence_reason": convergence_reason,
            "scoring_method": "form_edge",
            "backend": backend_used,
        }

    def _normalize_to_canvas(
        self,
        contours: list[np.ndarray],
        canvas_size: tuple[int, int],
    ) -> list[np.ndarray]:
        """Scale projected contours to fit within canvas bounds.

        Centers and scales contours so they occupy ~80% of the canvas,
        leaving margins for displacement corrections.

        Args:
            contours: List of Nx2 float64 contour arrays.
            canvas_size: (height, width) of the target canvas.

        Returns:
            Normalized contours, same structure.
        """
        if not contours:
            return contours

        # Concatenate all points to find bounding box
        all_pts = np.concatenate(contours, axis=0)
        if len(all_pts) == 0:
            return contours

        mins = all_pts.min(axis=0)
        maxs = all_pts.max(axis=0)
        ranges = maxs - mins

        h, w = canvas_size
        # Avoid division by zero for degenerate meshes
        scale_x = (w * 0.8) / max(ranges[0], 1e-6)
        scale_y = (h * 0.8) / max(ranges[1], 1e-6)
        scale = min(scale_x, scale_y)

        # Center in canvas
        center = (mins + maxs) / 2.0
        canvas_center = np.array([w / 2.0, h / 2.0])

        normalized = []
        for c in contours:
            shifted = (c - center) * scale + canvas_center
            normalized.append(shifted)
        return normalized

    def _store_deltas(
        self,
        original_contours: list[np.ndarray],
        corrected_contours: list[np.ndarray],
        labels: list[str],
        image_hash: str,
        score_before: float,
        score_after: float,
    ) -> bool:
        """Store projection deltas for each face group.

        Computes per-point displacement vectors between original and
        corrected contours, then stores via correction_learning.

        Args:
            original_contours: Pre-correction contours (Nx2 arrays).
            corrected_contours: Post-correction contours (same shape).
            labels: Face group labels corresponding to each contour.
            image_hash: Reference image SHA-256 hash.
            score_before: Score before correction.
            score_after: Score after correction.

        Returns:
            True if deltas were stored, False if nothing to store.
        """
        stored_any = False
        for orig, corrected, label in zip(
            original_contours, corrected_contours, labels
        ):
            displacement = corrected - orig
            # Only store if there is meaningful displacement (> 0.001 px)
            max_disp = float(np.max(np.abs(displacement)))
            if max_disp < 0.001:
                continue

            store_projection_delta(
                face_group_label=label,
                projected_contour=orig.tolist(),
                reference_contour=corrected.tolist(),
                displacement_vectors=displacement.tolist(),
                mesh_source="trellis_v2",
                image_hash=image_hash,
                score_before=score_before,
                score_after=score_after,
                path=self.delta_storage_path,
            )
            stored_any = True
        return stored_any

    @staticmethod
    def status() -> dict:
        """Report availability of modules used by the feedback loop."""
        # Check path_gradient_approx (always available — pure Python)
        path_grad_available = True
        try:
            from adobe_mcp.apps.illustrator.ml_vision.path_gradient_approx import (
                optimize_paths_approx as _,
            )
        except ImportError:
            path_grad_available = False

        # Check diffvg (optional)
        diffvg_available = False
        try:
            import diffvg as _dv  # noqa: F401
            diffvg_available = True
        except ImportError:
            pass

        # Check mesh_face_grouper
        face_grouper_available = True
        try:
            from adobe_mcp.apps.illustrator.threed.mesh_face_grouper import (
                group_faces_by_normal as _,
            )
        except ImportError:
            face_grouper_available = False

        # Check correction_learning
        correction_available = True
        try:
            from adobe_mcp.apps.illustrator.analysis.correction_learning import (
                store_projection_delta as _,
                pre_correct_projection as _pc,
            )
        except ImportError:
            correction_available = False

        # Check form_edge_pipeline (always available — heuristic backend)
        form_edge_available = True
        dsine_available = False
        try:
            from adobe_mcp.apps.illustrator.form_edge_pipeline import (
                DSINE_AVAILABLE as _dsine,
            )
            dsine_available = _dsine
        except ImportError:
            form_edge_available = False

        return {
            "feedback_loop_3d": "available",
            "modules": {
                "path_gradient_approx": path_grad_available,
                "diffvg": diffvg_available,
                "mesh_face_grouper": face_grouper_available,
                "correction_learning": correction_available,
                "form_edge_pipeline": form_edge_available,
                "dsine": dsine_available,
            },
            "scoring_methods": {
                "mesh_projection": {
                    "available": face_grouper_available,
                    "description": "3D mesh → 2D projection + Hausdorff scoring",
                },
                "form_edge": {
                    "available": form_edge_available,
                    "description": (
                        "Normal-map form edges as ground truth "
                        f"({'DSINE' if dsine_available else 'heuristic'} backend)"
                    ),
                },
                "auto": {
                    "description": "Selects best available method automatically",
                },
            },
            "description": (
                "Closed-loop 3D-to-2D feedback system. "
                "Projects mesh -> scores against reference -> "
                "corrects iteratively -> stores learned deltas. "
                "Supports form_edge scoring as mesh-free alternative."
            ),
        }

    @staticmethod
    def clear_deltas(path: str | None = None) -> dict:
        """Remove stored projection deltas.

        Args:
            path: Custom delta file path. Defaults to PROJECTION_CORRECTIONS_PATH.

        Returns:
            Dict with status and number of entries cleared.
        """
        target = path or PROJECTION_CORRECTIONS_PATH

        # Validate path before any file operations to prevent arbitrary deletion
        try:
            target = validate_safe_path(target)
        except ValueError as exc:
            return {"cleared": 0, "message": f"Path validation failed: {exc}"}

        if not os.path.isfile(target):
            return {"cleared": 0, "message": "No delta file found"}

        # Count entries before clearing
        try:
            with open(target) as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 0
        except (json.JSONDecodeError, OSError):
            count = 0

        os.remove(target)
        return {"cleared": count, "message": f"Removed {count} stored deltas"}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_feedback_loop_3d tool."""

    @mcp.tool(
        name="adobe_ai_feedback_loop_3d",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_feedback_loop_3d(
        params: FeedbackLoop3DInput,
    ) -> str:
        """Closed-loop 3D-to-2D feedback system.

        Projects mesh faces to 2D, scores against reference image,
        computes corrections, optimizes paths, and stores learned
        projection deltas for future runs.

        Actions:
        - run_cycle: Run the full feedback loop
        - status: Report module availability
        - clear_deltas: Remove stored projection deltas
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(FeedbackLoop3D.status(), indent=2)

        elif action == "clear_deltas":
            result = FeedbackLoop3D.clear_deltas(params.delta_storage_path)
            return json.dumps(result, indent=2)

        elif action == "run_cycle":
            if not params.reference_path:
                return json.dumps({"error": "reference_path is required for run_cycle"})
            # mesh_path is only required for mesh_projection scoring
            if params.scoring_method == "mesh_projection" and not params.mesh_path:
                return json.dumps({"error": "mesh_path is required when scoring_method='mesh_projection'"})
            # For auto/form_edge, mesh_path is optional
            if params.scoring_method not in ("form_edge", "auto") and not params.mesh_path:
                return json.dumps({"error": "mesh_path is required for run_cycle"})

            loop = FeedbackLoop3D(delta_storage_path=params.delta_storage_path)
            result = loop.run_cycle(
                reference_path=params.reference_path,
                mesh_path=params.mesh_path,
                max_rounds=params.max_rounds,
                convergence_target=params.convergence_target,
                min_improvement=params.min_improvement,
                damping=params.damping,
                angle_threshold=params.angle_threshold,
                camera_yaw=params.camera_yaw,
                camera_pitch=params.camera_pitch,
                scoring_method=params.scoring_method,
            )
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["run_cycle", "status", "clear_deltas"],
            })
