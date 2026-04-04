"""Correction learning from user feedback.

Two correction systems:

1. **Label corrections** — Records user corrections to CV analysis part
   labels and uses shape context to suggest labels for future similar parts.
   Storage: ~/.claude/memory/illustration/corrections.json

2. **DWPose joint corrections** — Records user corrections to DWPose skeleton
   predictions. When the user moves a joint from the predicted position to the
   correct position, the delta is stored per character. After corrections on 2+
   figures, the system pre-applies predicted corrections to future DWPose output.
   Storage: /tmp/ai_rigs/{character_name}_corrections.json
"""

import json
import math
import os
import statistics
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.path_validation import validate_safe_path

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCorrectionLearningInput(BaseModel):
    """Learn from user corrections to improve future analysis."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: record_correction, suggest_from_corrections",
    )
    correction_type: Optional[str] = Field(
        default=None,
        description="Type: part_label, connection, hierarchy, joint_type",
    )
    original: Optional[str] = Field(
        default=None, description="Original label/value"
    )
    corrected: Optional[str] = Field(
        default=None, description="Corrected label/value"
    )
    context: Optional[dict] = Field(
        default=None,
        description="Shape context: area_ratio, aspect_ratio, position_relative_to_root",
    )
    part_features: Optional[dict] = Field(
        default=None,
        description="Features of a new part to get suggestions for",
    )
    storage_path: Optional[str] = Field(
        default=None, description="Custom storage path for corrections file"
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

VALID_CORRECTION_TYPES = {"part_label", "connection", "hierarchy", "joint_type", "projection_delta"}


def _default_corrections_path() -> str:
    """Return the default corrections file path."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "memory", "illustration", "corrections.json")


def _load_corrections(storage_path: str | None = None) -> list[dict]:
    """Load corrections from disk."""
    path = storage_path or _default_corrections_path()
    path = validate_safe_path(path)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_corrections(corrections: list[dict], storage_path: str | None = None) -> None:
    """Save corrections to disk."""
    path = storage_path or _default_corrections_path()
    path = validate_safe_path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(corrections, f, indent=2)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def record_correction(
    correction_type: str,
    original: str,
    corrected: str,
    context: dict,
    storage_path: str | None = None,
) -> dict:
    """Store a user correction with shape context.

    Args:
        correction_type: one of part_label, connection, hierarchy, joint_type
        original: the original label/value
        corrected: the corrected label/value
        context: shape features dict (area_ratio, aspect_ratio, position_relative_to_root)
        storage_path: optional custom path for the corrections file

    Returns:
        The stored correction dict.

    Raises:
        ValueError: if correction_type is invalid.
    """
    if correction_type not in VALID_CORRECTION_TYPES:
        raise ValueError(
            f"Invalid correction type '{correction_type}'. "
            f"Valid types: {sorted(VALID_CORRECTION_TYPES)}"
        )

    correction = {
        "correction_type": correction_type,
        "original": original,
        "corrected": corrected,
        "context": context,
    }

    corrections = _load_corrections(storage_path)
    corrections.append(correction)
    # Cap to most recent 1000 entries to prevent unbounded file growth
    if len(corrections) > 1000:
        corrections = corrections[-1000:]
    _save_corrections(corrections, storage_path)

    return correction


def _feature_distance(features_a: dict, features_b: dict) -> float:
    """Compute distance between two feature dicts.

    Compares area_ratio, aspect_ratio, and position_relative_to_root
    with equal weighting. Missing keys contribute 0 distance.

    Returns:
        Euclidean distance across normalized feature dimensions.
    """
    dims = ["area_ratio", "aspect_ratio", "position_relative_to_root"]
    sum_sq = 0.0
    for dim in dims:
        a = features_a.get(dim, 0.0)
        b = features_b.get(dim, 0.0)
        sum_sq += (a - b) ** 2
    return math.sqrt(sum_sq)


def suggest_from_corrections(
    part_features: dict,
    storage_path: str | None = None,
    max_distance: float = 0.3,
) -> dict | None:
    """Suggest a label based on stored corrections with similar features.

    Finds the correction whose context features are closest to the given
    part features (within max_distance).

    Args:
        part_features: shape features of the new part
        storage_path: optional custom corrections file path
        max_distance: maximum feature distance to consider a match

    Returns:
        {"suggested_label": str, "distance": float, "from_correction": dict}
        or None if no match is close enough.
    """
    corrections = _load_corrections(storage_path)
    if not corrections:
        return None

    best_match = None
    best_distance = float("inf")

    for correction in corrections:
        ctx = correction.get("context", {})
        dist = _feature_distance(part_features, ctx)
        if dist < best_distance:
            best_distance = dist
            best_match = correction

    if best_match is None or best_distance > max_distance:
        return None

    return {
        "suggested_label": best_match["corrected"],
        "distance": round(best_distance, 4),
        "from_correction": best_match,
    }


# ---------------------------------------------------------------------------
# DWPose joint correction learning
# ---------------------------------------------------------------------------

_DWPOSE_CORRECTIONS_DIR = "/tmp/ai_rigs"


def _dwpose_corrections_path(character_name: str) -> str:
    """Return storage path for a character's DWPose corrections.

    Sanitizes character_name by removing path traversal characters
    (``/``, ``\\``, ``..``) to prevent directory traversal attacks.
    """
    # Strip path traversal components from character_name
    sanitized = character_name.replace("/", "").replace("\\", "").replace("..", "")
    if not sanitized:
        raise ValueError(f"Invalid character_name after sanitization: {character_name!r}")
    path = os.path.join(_DWPOSE_CORRECTIONS_DIR, f"{sanitized}_corrections.json")
    return validate_safe_path(path)


def _load_dwpose_corrections(character_name: str) -> list[dict]:
    """Load stored DWPose corrections for a character."""
    path = _dwpose_corrections_path(character_name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_dwpose_corrections(character_name: str, corrections: list[dict]) -> None:
    """Save DWPose corrections for a character."""
    os.makedirs(_DWPOSE_CORRECTIONS_DIR, exist_ok=True)
    path = _dwpose_corrections_path(character_name)
    with open(path, "w") as f:
        json.dump(corrections, f, indent=2)


def store_correction(
    character_name: str,
    joint_name: str,
    dwpose_pos: tuple[float, float],
    corrected_pos: tuple[float, float],
    figure_type: str = "mech",
) -> None:
    """Store a single joint correction for learning.

    When a user moves a joint from the DWPose-predicted position to the
    correct position, this function records the delta so the system can
    learn systematic biases in DWPose predictions for this figure type.

    Saves to /tmp/ai_rigs/{character_name}_corrections.json

    Args:
        character_name: Identifier for the character (e.g. "gir", "zaku").
        joint_name: Name of the joint (e.g. "left_shoulder", "right_knee").
        dwpose_pos: The (x, y) position DWPose predicted.
        corrected_pos: The (x, y) position the user corrected it to.
        figure_type: Category of figure, e.g. "mech", "human", "creature".
    """
    delta_x = corrected_pos[0] - dwpose_pos[0]
    delta_y = corrected_pos[1] - dwpose_pos[1]

    correction = {
        "joint_name": joint_name,
        "dwpose_pos": list(dwpose_pos),
        "corrected_pos": list(corrected_pos),
        "delta": [delta_x, delta_y],
        "figure_type": figure_type,
    }

    corrections = _load_dwpose_corrections(character_name)
    corrections.append(correction)
    _save_dwpose_corrections(character_name, corrections)


def compute_correction_model(
    figure_type: str = "mech",
    min_samples: int = 2,
) -> dict[str, tuple[float, float]]:
    """Compute average correction vectors per joint type.

    Scans all correction files in /tmp/ai_rigs/ for the given figure type,
    groups corrections by joint name, and computes the mean delta (dx, dy)
    for each joint across all characters.

    This model captures systematic DWPose biases -- for example, if DWPose
    consistently places mech shoulders too high, the model will contain a
    downward correction vector for "left_shoulder" and "right_shoulder".

    Args:
        figure_type: Category to filter corrections by (e.g. "mech").
        min_samples: Minimum number of correction samples (across distinct
            characters) required before producing a model. Returns empty
            dict if fewer than min_samples corrections exist for the type.

    Returns:
        Dict mapping joint_name to (avg_dx, avg_dy) correction vector.
        Returns empty dict if fewer than min_samples corrections exist.
    """
    # Collect all corrections for the figure type across all characters
    joint_deltas: dict[str, list[tuple[float, float]]] = {}
    total_corrections = 0

    if not os.path.isdir(_DWPOSE_CORRECTIONS_DIR):
        return {}

    for filename in os.listdir(_DWPOSE_CORRECTIONS_DIR):
        if not filename.endswith("_corrections.json"):
            continue
        filepath = os.path.join(_DWPOSE_CORRECTIONS_DIR, filename)
        with open(filepath) as f:
            corrections = json.load(f)

        for c in corrections:
            if c.get("figure_type") != figure_type:
                continue
            jname = c["joint_name"]
            delta = c["delta"]
            if jname not in joint_deltas:
                joint_deltas[jname] = []
            joint_deltas[jname].append((delta[0], delta[1]))
            total_corrections += 1

    if total_corrections < min_samples:
        return {}

    # Compute mean delta per joint
    model: dict[str, tuple[float, float]] = {}
    for jname, deltas in joint_deltas.items():
        avg_dx = statistics.mean(d[0] for d in deltas)
        avg_dy = statistics.mean(d[1] for d in deltas)
        model[jname] = (avg_dx, avg_dy)

    return model


def pre_correct_dwpose(
    dwpose_joints: dict[str, tuple[float, float]],
    figure_type: str = "mech",
) -> dict[str, tuple[float, float]]:
    """Apply learned corrections to raw DWPose output.

    Loads the correction model for the given figure type and applies the
    average delta to each joint that has a learned correction. Joints
    without learned corrections are returned unchanged.

    This is the main consumer-facing function: feed it raw DWPose joint
    positions and get back improved positions based on prior user feedback.

    Args:
        dwpose_joints: Dict mapping joint_name to (x, y) position from DWPose.
        figure_type: Category of figure to load corrections for.

    Returns:
        Dict mapping joint_name to corrected (x, y) position.
        If no correction model exists, returns joints unchanged.
    """
    model = compute_correction_model(figure_type)

    if not model:
        return dict(dwpose_joints)

    corrected: dict[str, tuple[float, float]] = {}
    for jname, pos in dwpose_joints.items():
        if jname in model:
            dx, dy = model[jname]
            corrected[jname] = (pos[0] + dx, pos[1] + dy)
        else:
            corrected[jname] = pos

    return corrected


# ---------------------------------------------------------------------------
# Projection delta learning (Phase 4 feedback loop)
# ---------------------------------------------------------------------------

PROJECTION_CORRECTIONS_PATH = os.path.expanduser(
    "~/.claude/memory/illustration/projection_corrections.json"
)


def _load_projection_corrections(path: str | None = None) -> list[dict]:
    """Load projection correction deltas from disk."""
    p = path or PROJECTION_CORRECTIONS_PATH
    p = validate_safe_path(p)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return []


def _save_projection_corrections(
    corrections: list[dict], path: str | None = None
) -> None:
    """Save projection correction deltas to disk."""
    p = path or PROJECTION_CORRECTIONS_PATH
    p = validate_safe_path(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(corrections, f, indent=2)


def store_projection_delta(
    face_group_label: str,
    projected_contour: list,
    reference_contour: list,
    displacement_vectors: list,
    mesh_source: str,
    image_hash: str,
    score_before: float,
    score_after: float,
    path: str | None = None,
) -> dict:
    """Store a projection delta for a face group.

    Appends to projection_corrections.json.
    Each entry follows the schema:
    {
        "correction_type": "projection_delta",
        "face_group_label": "front_face",
        "projected_contour": [[x,y], ...],
        "reference_contour": [[x,y], ...],
        "displacement_vectors": [[dx,dy], ...],
        "mesh_source": "trellis_v2",
        "image_hash": "abc123",
        "score_before": 0.3,
        "score_after": 0.6,
    }

    Args:
        face_group_label: Which face group this correction applies to.
        projected_contour: Where the mesh projected to, as [[x,y], ...].
        reference_contour: Where it should have been, as [[x,y], ...].
        displacement_vectors: Per-point correction vectors [[dx,dy], ...].
        mesh_source: Which reconstructor produced the mesh.
        image_hash: Identity hash of the reference image.
        score_before: Pixel deviation score before correction.
        score_after: Pixel deviation score after correction.
        path: Optional custom storage path.

    Returns:
        The stored correction entry dict.
    """
    entry = {
        "correction_type": "projection_delta",
        "face_group_label": face_group_label,
        "projected_contour": projected_contour,
        "reference_contour": reference_contour,
        "displacement_vectors": displacement_vectors,
        "mesh_source": mesh_source,
        "image_hash": image_hash,
        "score_before": score_before,
        "score_after": score_after,
    }

    corrections = _load_projection_corrections(path)
    corrections.append(entry)
    # Cap to most recent 1000 entries to prevent unbounded file growth
    if len(corrections) > 1000:
        corrections = corrections[-1000:]
    _save_projection_corrections(corrections, path)

    return entry


def pre_correct_projection(
    projected_contours: list,
    face_group_labels: list[str],
    image_hash: str | None = None,
    path: str | None = None,
) -> list:
    """Apply stored projection deltas to new projected contours.

    For each face group label, find matching stored deltas.
    Compute mean displacement vector across all matching entries.
    Weight: 1.0 for same image_hash, 0.3 for different image.
    Apply weighted mean displacement to each point in the contour.

    Args:
        projected_contours: List of contour arrays, each [[x,y], ...].
        face_group_labels: List of face group label strings, one per contour.
        image_hash: Optional hash of the current reference image for
            weighting stored deltas (exact match = 1.0, different = 0.3).
        path: Optional custom storage path.

    Returns:
        List of corrected contour arrays, same structure as input.
        Contours with no matching stored deltas are returned unchanged.
    """
    stored = _load_projection_corrections(path)
    if not stored:
        return list(projected_contours)

    corrected_contours = []
    for contour, label in zip(projected_contours, face_group_labels):
        # Find all stored deltas matching this face group label
        matching = [s for s in stored if s.get("face_group_label") == label]

        if not matching:
            corrected_contours.append(contour)
            continue

        # Compute weighted mean displacement vectors across all matches.
        # Each matching entry has displacement_vectors [[dx,dy], ...].
        # We need to average them, weighted by image hash similarity.
        num_points = len(contour)

        # Accumulate weighted sums
        weighted_dx = [0.0] * num_points
        weighted_dy = [0.0] * num_points
        total_weight = 0.0

        for entry in matching:
            disp = entry.get("displacement_vectors", [])
            # Only use entries whose displacement vector length matches
            if len(disp) != num_points:
                continue

            # Weight: 1.0 for same image_hash, 0.3 for different
            if image_hash and entry.get("image_hash") == image_hash:
                w = 1.0
            else:
                w = 0.3

            for i in range(num_points):
                weighted_dx[i] += w * disp[i][0]
                weighted_dy[i] += w * disp[i][1]
            total_weight += w

        if total_weight == 0.0:
            corrected_contours.append(contour)
            continue

        # Apply weighted mean displacement
        corrected = []
        for i, pt in enumerate(contour):
            mean_dx = weighted_dx[i] / total_weight
            mean_dy = weighted_dy[i] / total_weight
            corrected.append([pt[0] + mean_dx, pt[1] + mean_dy])

        corrected_contours.append(corrected)

    return corrected_contours


def compare_corrections(
    original: dict[str, tuple[float, float]],
    corrected: dict[str, tuple[float, float]],
) -> dict:
    """Compare original DWPose positions to user-corrected positions.

    Provides per-joint analysis of how much each joint was moved, in what
    direction, and summary statistics across all joints. Useful for
    understanding the magnitude and pattern of DWPose errors.

    Args:
        original: Dict mapping joint_name to original (x, y) from DWPose.
        corrected: Dict mapping joint_name to corrected (x, y) from user.

    Returns:
        Dict with:
        - "per_joint": dict mapping joint_name to {delta_x, delta_y, distance, direction_deg}
        - "summary": {mean_deviation, max_deviation, max_deviation_joint, total_joints, corrected_joints}
    """
    per_joint: dict[str, dict] = {}
    distances: list[float] = []

    # Only compare joints present in both dicts
    common_joints = set(original.keys()) & set(corrected.keys())

    for jname in sorted(common_joints):
        ox, oy = original[jname]
        cx, cy = corrected[jname]
        dx = cx - ox
        dy = cy - oy
        dist = math.sqrt(dx * dx + dy * dy)
        # Direction in degrees, 0 = right, 90 = down (screen coords)
        direction = math.degrees(math.atan2(dy, dx))

        per_joint[jname] = {
            "delta_x": round(dx, 4),
            "delta_y": round(dy, 4),
            "distance": round(dist, 4),
            "direction_deg": round(direction, 2),
        }
        distances.append(dist)

    # Summary statistics
    corrected_joints = sum(1 for d in distances if d > 0.0001)
    summary: dict = {
        "total_joints": len(common_joints),
        "corrected_joints": corrected_joints,
    }

    if distances:
        summary["mean_deviation"] = round(statistics.mean(distances), 4)
        summary["max_deviation"] = round(max(distances), 4)
        # Find which joint had the max deviation
        max_dist = max(distances)
        for jname, info in per_joint.items():
            if abs(info["distance"] - max_dist) < 0.0001:
                summary["max_deviation_joint"] = jname
                break
    else:
        summary["mean_deviation"] = 0.0
        summary["max_deviation"] = 0.0
        summary["max_deviation_joint"] = None

    return {
        "per_joint": per_joint,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_correction_learning tool."""

    @mcp.tool(
        name="adobe_ai_correction_learning",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_correction_learning(params: AiCorrectionLearningInput) -> str:
        """Learn from user corrections to improve future analysis.

        Actions:
        - record_correction: store a correction with shape context
        - suggest_from_corrections: get suggestions for a new part
        """
        action = params.action.lower().strip()

        if action == "record_correction":
            if (
                not params.correction_type
                or params.original is None
                or params.corrected is None
                or params.context is None
            ):
                return json.dumps({
                    "error": "record_correction requires correction_type, original, corrected, context"
                })
            try:
                result = record_correction(
                    params.correction_type,
                    params.original,
                    params.corrected,
                    params.context,
                    params.storage_path,
                )
            except ValueError as e:
                return json.dumps({"error": str(e)})
            return json.dumps({"action": "record_correction", "correction": result})

        elif action == "suggest_from_corrections":
            if params.part_features is None:
                return json.dumps({
                    "error": "suggest_from_corrections requires part_features"
                })
            result = suggest_from_corrections(
                params.part_features, params.storage_path
            )
            if result is None:
                return json.dumps({
                    "action": "suggest_from_corrections",
                    "suggestion": None,
                    "message": "No matching corrections found",
                })
            return json.dumps({
                "action": "suggest_from_corrections",
                "suggestion": result,
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["record_correction", "suggest_from_corrections"],
            })
