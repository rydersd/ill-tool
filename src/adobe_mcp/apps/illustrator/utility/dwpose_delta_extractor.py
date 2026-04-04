"""DWPose delta extractor — extract joint correction deltas from Illustrator layers.

Reads DWPose skeleton predictions from an ML layer and user-corrected joints
from a correction layer, computes per-joint displacement deltas, and stores
them via correction_learning for future pre-correction of DWPose output.

Tier 1 (top): Pure Python delta extraction logic.
Tier 2 (bottom): MCP tool registration with JSX bridge.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.analysis.correction_learning import (
    store_correction,
    compute_correction_model,
)


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class DwposeDeltaExtractorInput(BaseModel):
    """Extract DWPose correction deltas from Illustrator layers."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: extract_deltas, status",
    )
    ml_layer_name: str = Field(
        default="ML Test - DWPose -RB",
        description="Name of the layer with DWPose skeleton path items",
    )
    corrected_layer_name: str = Field(
        default="",
        description="Name of the layer with user-corrected skeleton path items",
    )
    character_name: str = Field(
        default="",
        description="Name for the character (e.g. 'right_mech', 'left_mech')",
    )
    character_type: str = Field(
        default="mech",
        description="Type of character: mech, human, creature",
    )


# ---------------------------------------------------------------------------
# JSX builders
# ---------------------------------------------------------------------------


def _build_read_joints_jsx(layer_name: str) -> str:
    """Build JSX to read all path item anchor positions from a layer.

    Reads the first anchor point of each path item on the specified layer
    as a joint position. Returns a JSON array of {x, y, index} objects.
    """
    escaped = escape_jsx_string(layer_name)
    return f"""(function() {{
    var doc = app.activeDocument;
    var layer;
    try {{
        layer = doc.layers.getByName("{escaped}");
    }} catch(e) {{
        return JSON.stringify({{error: "Layer not found: {escaped}"}});
    }}
    var joints = [];
    for (var i = 0; i < layer.pathItems.length; i++) {{
        var pi = layer.pathItems[i];
        if (pi.pathPoints.length > 0) {{
            var pp = pi.pathPoints[0];
            joints.push({{
                x: pp.anchor[0],
                y: pp.anchor[1],
                index: i,
                name: pi.name || ("joint_" + i)
            }});
        }}
    }}
    return JSON.stringify({{joints: joints, count: joints.length}});
}})();"""


# ---------------------------------------------------------------------------
# Pure Python delta computation
# ---------------------------------------------------------------------------


def match_joints_by_proximity(
    ml_joints: list[dict],
    corrected_joints: list[dict],
    threshold: float = 50.0,
) -> list[tuple[dict, dict]]:
    """Match ML joints to corrected joints by nearest-neighbor proximity.

    For each ML joint, find the closest corrected joint within threshold
    distance. Each corrected joint is matched at most once.

    Args:
        ml_joints: List of dicts with 'x', 'y' keys from the ML layer.
        corrected_joints: List of dicts with 'x', 'y' keys from the
            corrected layer.
        threshold: Maximum pixel distance to consider a match.

    Returns:
        List of (ml_joint, corrected_joint) tuples for matched pairs.
    """
    if not ml_joints or not corrected_joints:
        return []

    used_corrected = set()
    matches = []

    for ml_j in ml_joints:
        best_dist = float("inf")
        best_idx = -1

        for ci, corr_j in enumerate(corrected_joints):
            if ci in used_corrected:
                continue
            dx = ml_j["x"] - corr_j["x"]
            dy = ml_j["y"] - corr_j["y"]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < best_dist:
                best_dist = dist
                best_idx = ci

        if best_idx >= 0 and best_dist <= threshold:
            used_corrected.add(best_idx)
            matches.append((ml_j, corrected_joints[best_idx]))

    return matches


def compute_deltas(
    matches: list[tuple[dict, dict]],
) -> list[dict]:
    """Compute per-joint displacement deltas from matched pairs.

    Args:
        matches: List of (ml_joint, corrected_joint) tuples.

    Returns:
        List of dicts with joint_index, delta_x, delta_y, magnitude.
    """
    deltas = []
    for ml_j, corr_j in matches:
        dx = corr_j["x"] - ml_j["x"]
        dy = corr_j["y"] - ml_j["y"]
        magnitude = math.sqrt(dx * dx + dy * dy)
        deltas.append({
            "joint_index": ml_j.get("index", 0),
            "joint_name": ml_j.get("name", f"joint_{ml_j.get('index', 0)}"),
            "ml_pos": [ml_j["x"], ml_j["y"]],
            "corrected_pos": [corr_j["x"], corr_j["y"]],
            "delta_x": dx,
            "delta_y": dy,
            "magnitude": round(magnitude, 4),
        })
    return deltas


def store_deltas_via_correction_learning(
    deltas: list[dict],
    character_name: str,
    character_type: str = "mech",
) -> int:
    """Store computed deltas via correction_learning.store_correction().

    Each delta is stored as a DWPose joint correction so the system can
    learn systematic biases for this character type.

    Args:
        deltas: List of delta dicts from compute_deltas().
        character_name: Identifier for the character.
        character_type: Category of figure (mech, human, creature).

    Returns:
        Number of corrections stored.
    """
    stored = 0
    for d in deltas:
        store_correction(
            character_name=character_name,
            joint_name=d["joint_name"],
            dwpose_pos=(d["ml_pos"][0], d["ml_pos"][1]),
            corrected_pos=(d["corrected_pos"][0], d["corrected_pos"][1]),
            figure_type=character_type,
        )
        stored += 1
    return stored


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_dwpose_delta_extractor tool."""

    @mcp.tool(
        name="adobe_ai_dwpose_delta_extractor",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_dwpose_delta_extractor(
        params: DwposeDeltaExtractorInput,
    ) -> str:
        """Extract DWPose correction deltas from Illustrator layers.

        Actions:
        - extract_deltas: Read joints from ML and corrected layers,
          compute deltas, store via correction_learning.
        - status: Report whether stored corrections exist for this
          character type.
        """
        action = params.action.lower().strip()

        if action == "extract_deltas":
            if not params.corrected_layer_name:
                return json.dumps({
                    "error": "extract_deltas requires corrected_layer_name"
                })
            if not params.character_name:
                return json.dumps({
                    "error": "extract_deltas requires character_name"
                })

            # Read joints from both layers via JSX
            ml_jsx = _build_read_joints_jsx(params.ml_layer_name)
            ml_result = await _async_run_jsx("illustrator", ml_jsx)
            if not ml_result.get("success"):
                return json.dumps({
                    "error": f"Failed to read ML layer: {ml_result.get('error', 'unknown')}"
                })

            ml_data = json.loads(ml_result.get("value", "{}"))
            if "error" in ml_data:
                return json.dumps(ml_data)

            corr_jsx = _build_read_joints_jsx(params.corrected_layer_name)
            corr_result = await _async_run_jsx("illustrator", corr_jsx)
            if not corr_result.get("success"):
                return json.dumps({
                    "error": f"Failed to read corrected layer: {corr_result.get('error', 'unknown')}"
                })

            corr_data = json.loads(corr_result.get("value", "{}"))
            if "error" in corr_data:
                return json.dumps(corr_data)

            ml_joints = ml_data.get("joints", [])
            corr_joints = corr_data.get("joints", [])

            if not ml_joints:
                return json.dumps({
                    "error": "No joints found on ML layer",
                    "ml_layer": params.ml_layer_name,
                })
            if not corr_joints:
                return json.dumps({
                    "error": "No joints found on corrected layer",
                    "corrected_layer": params.corrected_layer_name,
                })

            # Match joints and compute deltas
            matches = match_joints_by_proximity(ml_joints, corr_joints)
            deltas = compute_deltas(matches)

            # Store via correction_learning
            corrections_stored = store_deltas_via_correction_learning(
                deltas, params.character_name, params.character_type
            )

            # Find largest corrections for reporting
            sorted_deltas = sorted(deltas, key=lambda d: d["magnitude"], reverse=True)
            largest = [
                (d["joint_index"], d["magnitude"])
                for d in sorted_deltas[:5]
            ]

            return json.dumps({
                "action": "extract_deltas",
                "joints_found": {
                    "ml_layer": len(ml_joints),
                    "corrected_layer": len(corr_joints),
                },
                "joints_matched": len(matches),
                "corrections_stored": corrections_stored,
                "largest_corrections": largest,
                "character_name": params.character_name,
                "character_type": params.character_type,
            })

        elif action == "status":
            character_type = params.character_type or "mech"
            model = compute_correction_model(character_type, min_samples=1)
            has_corrections = len(model) > 0

            return json.dumps({
                "action": "status",
                "character_type": character_type,
                "has_corrections": has_corrections,
                "joints_with_corrections": len(model),
                "joint_names": sorted(model.keys()) if model else [],
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["extract_deltas", "status"],
            })
