"""Hausdorff-based pixel deviation scorer for evaluator calibration.

Replaces subjective 0-1 scoring (which had 20x calibration error) with
geometric distance measurement between contour sets. Scores are based on
mean point-to-contour distance normalized by reference scale.

Scoring formula:
    score = max(0.0, 1.0 - (overall_mean_deviation / reference_scale))

Where reference_scale defaults to the diagonal of the reference image
bounding box if not provided explicitly.
"""

import json
import math
import os
from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Default calibration path
# ---------------------------------------------------------------------------

DEFAULT_CALIBRATION_PATH = os.path.expanduser(
    "~/.claude/memory/illustration/evaluator_calibration.json"
)


# ---------------------------------------------------------------------------
# Input model (matches cv_confidence.py pattern)
# ---------------------------------------------------------------------------


class PixelDeviationInput(BaseModel):
    """Input for pixel deviation scoring."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference_contours: list[list[list[float]]] = Field(
        ...,
        description=(
            "Reference contours as list of Nx2 arrays "
            "(each contour is [[x,y], [x,y], ...])"
        ),
    )
    test_contours: list[list[list[float]]] = Field(
        ...,
        description=(
            "Test/generated contours as list of Nx2 arrays "
            "(each contour is [[x,y], [x,y], ...])"
        ),
    )
    reference_scale: Optional[float] = Field(
        default=None,
        description=(
            "Scale for normalization (e.g., image diagonal in pixels). "
            "If None, computed from reference contour bounding box."
        ),
    )


# ---------------------------------------------------------------------------
# Core distance functions
# ---------------------------------------------------------------------------


def hausdorff_distance(contour_a: np.ndarray, contour_b: np.ndarray) -> float:
    """Compute directed Hausdorff distance from contour_a to contour_b.

    For every point in A, finds the nearest point in B, then returns the
    maximum of those nearest-point distances. This measures the worst-case
    deviation of A from B.

    Args:
        contour_a: Nx2 array of (x, y) pixel coordinates.
        contour_b: Mx2 array of (x, y) pixel coordinates.

    Returns:
        Directed Hausdorff distance (float). Returns 0.0 for empty inputs.
    """
    if contour_a.size == 0 or contour_b.size == 0:
        return 0.0

    # Ensure 2D shape
    a = np.atleast_2d(contour_a).astype(np.float64)
    b = np.atleast_2d(contour_b).astype(np.float64)

    # Compute pairwise squared distances using broadcasting
    # a[:, None, :] is (N, 1, 2), b[None, :, :] is (1, M, 2)
    diff = a[:, None, :] - b[None, :, :]
    sq_dists = np.sum(diff ** 2, axis=2)  # (N, M)

    # For each point in A, find distance to nearest point in B
    min_dists_a = np.sqrt(np.min(sq_dists, axis=1))  # (N,)

    return float(np.max(min_dists_a))


def mean_contour_distance(contour_a: np.ndarray, contour_b: np.ndarray) -> float:
    """Compute mean point-to-contour distance from A to B.

    For every point in A, finds the nearest point in B, then returns the
    average of those nearest-point distances. More robust than Hausdorff
    for overall shape comparison since it is not dominated by outliers.

    Args:
        contour_a: Nx2 array of (x, y) pixel coordinates.
        contour_b: Mx2 array of (x, y) pixel coordinates.

    Returns:
        Mean nearest-point distance (float). Returns 0.0 for empty inputs.
    """
    if contour_a.size == 0 or contour_b.size == 0:
        return 0.0

    a = np.atleast_2d(contour_a).astype(np.float64)
    b = np.atleast_2d(contour_b).astype(np.float64)

    diff = a[:, None, :] - b[None, :, :]
    sq_dists = np.sum(diff ** 2, axis=2)

    min_dists_a = np.sqrt(np.min(sq_dists, axis=1))

    return float(np.mean(min_dists_a))


# ---------------------------------------------------------------------------
# Contour matching by centroid proximity
# ---------------------------------------------------------------------------


def _contour_centroid(contour: np.ndarray) -> tuple[float, float]:
    """Compute centroid of a contour (mean of points)."""
    c = np.atleast_2d(contour).astype(np.float64)
    return float(np.mean(c[:, 0])), float(np.mean(c[:, 1]))


def _match_contours_by_centroid(
    ref_contours: list[np.ndarray],
    test_contours: list[np.ndarray],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Match reference contours to test contours by nearest centroid.

    Each reference contour is matched to the closest unmatched test contour.
    Greedy nearest-centroid matching.

    Returns:
        (matched_pairs, unmatched_ref_indices, unmatched_test_indices)
    """
    if not ref_contours or not test_contours:
        unmatched_ref = list(range(len(ref_contours)))
        unmatched_test = list(range(len(test_contours)))
        return [], unmatched_ref, unmatched_test

    ref_centroids = [_contour_centroid(c) for c in ref_contours]
    test_centroids = [_contour_centroid(c) for c in test_contours]

    used_test: set[int] = set()
    matched: list[tuple[int, int]] = []

    # Build distance matrix for greedy matching
    for ri, (rx, ry) in enumerate(ref_centroids):
        best_ti: int | None = None
        best_dist = float("inf")
        for ti, (tx, ty) in enumerate(test_centroids):
            if ti in used_test:
                continue
            d = math.hypot(rx - tx, ry - ty)
            if d < best_dist:
                best_dist = d
                best_ti = ti
        if best_ti is not None:
            matched.append((ri, best_ti))
            used_test.add(best_ti)

    unmatched_ref = [i for i in range(len(ref_contours)) if i not in {m[0] for m in matched}]
    unmatched_test = [i for i in range(len(test_contours)) if i not in used_test]

    return matched, unmatched_ref, unmatched_test


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_pixel_deviation(
    reference_contours: list[np.ndarray],
    test_contours: list[np.ndarray],
    reference_scale: float | None = None,
) -> dict:
    """Score pixel deviation between reference and test contour sets.

    Matches contours by nearest centroid, computes mean_contour_distance
    for each matched pair, and produces a normalized 0-1 score.

    Score formula:
        score = max(0.0, 1.0 - (overall_mean_deviation / reference_scale))

    Args:
        reference_contours: List of Nx2 numpy arrays (reference contour points).
        test_contours: List of Mx2 numpy arrays (test/generated contour points).
        reference_scale: Normalization denominator. If None, computed from
            the diagonal of the bounding box of all reference points.

    Returns:
        Dict with keys:
            score: float 0.0-1.0 (1.0 = identical, 0.0 = completely off)
            mean_deviation: float (average pixel distance across all pairs)
            max_deviation: float (worst-case Hausdorff across all pairs)
            matched_pairs: int (number of successfully matched contour pairs)
            unmatched_ref: int (reference contours with no test match)
            unmatched_test: int (test contours with no reference match)
    """
    # Handle empty inputs gracefully
    if not reference_contours and not test_contours:
        return {
            "score": 1.0,
            "mean_deviation": 0.0,
            "max_deviation": 0.0,
            "matched_pairs": 0,
            "unmatched_ref": 0,
            "unmatched_test": 0,
        }

    if not reference_contours or not test_contours:
        return {
            "score": 0.0,
            "mean_deviation": float("inf"),
            "max_deviation": float("inf"),
            "matched_pairs": 0,
            "unmatched_ref": len(reference_contours),
            "unmatched_test": len(test_contours),
        }

    # Compute reference scale from bounding box diagonal if not provided
    if reference_scale is None or reference_scale <= 0:
        all_ref_pts = np.concatenate(
            [np.atleast_2d(c) for c in reference_contours], axis=0
        )
        x_min, y_min = all_ref_pts.min(axis=0)
        x_max, y_max = all_ref_pts.max(axis=0)
        reference_scale = math.hypot(x_max - x_min, y_max - y_min)
        # Guard against degenerate case (all points identical)
        if reference_scale < 1e-6:
            reference_scale = 1.0

    # Match contours by centroid
    matched, unmatched_r, unmatched_t = _match_contours_by_centroid(
        reference_contours, test_contours
    )

    if not matched:
        return {
            "score": 0.0,
            "mean_deviation": float("inf"),
            "max_deviation": float("inf"),
            "matched_pairs": 0,
            "unmatched_ref": len(reference_contours),
            "unmatched_test": len(test_contours),
        }

    # Compute distances for each matched pair
    mean_devs: list[float] = []
    max_devs: list[float] = []

    for ri, ti in matched:
        ref_c = np.atleast_2d(reference_contours[ri]).astype(np.float64)
        test_c = np.atleast_2d(test_contours[ti]).astype(np.float64)

        # Bidirectional mean distance (average of A->B and B->A)
        mean_ab = mean_contour_distance(ref_c, test_c)
        mean_ba = mean_contour_distance(test_c, ref_c)
        mean_dev = (mean_ab + mean_ba) / 2.0
        mean_devs.append(mean_dev)

        # Symmetric Hausdorff = max of both directed distances
        haus_ab = hausdorff_distance(ref_c, test_c)
        haus_ba = hausdorff_distance(test_c, ref_c)
        max_devs.append(max(haus_ab, haus_ba))

    overall_mean = float(np.mean(mean_devs))
    overall_max = float(np.max(max_devs))

    # Score: higher = better, 0-1 range
    score = max(0.0, 1.0 - (overall_mean / reference_scale))

    return {
        "score": round(score, 6),
        "mean_deviation": round(overall_mean, 4),
        "max_deviation": round(overall_max, 4),
        "matched_pairs": len(matched),
        "unmatched_ref": len(unmatched_r),
        "unmatched_test": len(unmatched_t),
    }


# ---------------------------------------------------------------------------
# Calibration persistence
# ---------------------------------------------------------------------------


def save_calibration(calibration_data: dict, path: str | None = None) -> str:
    """Save calibration data to JSON file.

    Args:
        calibration_data: Dict of calibration values to persist.
        path: File path. Defaults to DEFAULT_CALIBRATION_PATH.

    Returns:
        The path the file was written to.
    """
    out_path = path or DEFAULT_CALIBRATION_PATH
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(calibration_data, f, indent=2)
    return out_path


def load_calibration(path: str | None = None) -> dict | None:
    """Load calibration data from JSON file.

    Args:
        path: File path. Defaults to DEFAULT_CALIBRATION_PATH.

    Returns:
        Calibration dict, or None if file does not exist.
    """
    in_path = path or DEFAULT_CALIBRATION_PATH
    if not os.path.isfile(in_path):
        return None
    with open(in_path) as f:
        return json.load(f)
