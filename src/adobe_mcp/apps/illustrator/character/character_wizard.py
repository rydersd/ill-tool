"""One-call character creation wizard.

Orchestrates the full pipeline: reference segmentation -> connection
detection -> hierarchy building -> classification -> pivot inference.
Returns a complete rig summary from a single function call.

Pure Python orchestrator -- chains existing tools together.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCharacterWizardInput(BaseModel):
    """One-call character creation from a reference image."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="run_wizard",
        description="Action: run_wizard, wizard_status",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Path to the reference image (required for run_wizard)",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    auto_label: bool = Field(
        default=True,
        description="Auto-classify object type and suggest template",
    )
    n_clusters: int = Field(
        default=5,
        description="Number of color clusters for segmentation",
        ge=2,
        le=20,
    )
    min_area: int = Field(
        default=50,
        description="Minimum pixel area for a part to be included",
        ge=1,
    )


# ---------------------------------------------------------------------------
# Wizard step tracking
# ---------------------------------------------------------------------------

_STEPS = [
    "segmentation",
    "connection_detection",
    "hierarchy_building",
    "classification",
    "pivot_inference",
    "rig_storage",
]


def _init_wizard_state() -> dict:
    """Create a fresh wizard state tracker."""
    return {step: {"completed": False, "result": None, "error": None} for step in _STEPS}


# ---------------------------------------------------------------------------
# Pure Python orchestrator
# ---------------------------------------------------------------------------


def run_wizard(
    image_path: str,
    character_name: str = "character",
    auto_label: bool = True,
    n_clusters: int = 5,
    min_area: int = 50,
) -> dict:
    """Run the full character creation pipeline.

    Steps:
        1. segment_by_color + extract_parts -> get parts
        2. detect_connections -> find joints between parts
        3. build_hierarchy -> build parent-child tree
        4. (if auto_label) classify_object -> suggest type, apply template
        5. auto_pivots -> set pivot data on rig joints
        6. Store everything in rig file

    Args:
        image_path: path to the reference image
        character_name: identifier for the rig
        auto_label: whether to auto-classify object type
        n_clusters: number of color clusters for segmentation
        min_area: minimum pixel area for a part

    Returns:
        Summary dict with parts_found, connections, hierarchy_depth,
        suggested_type, and step status.
    """
    # Lazy imports to avoid circular dependencies and allow mocking
    from adobe_mcp.apps.illustrator.rigging.part_segmenter import segment_by_color, extract_parts
    from adobe_mcp.apps.illustrator.rigging.connection_detector import detect_connections
    from adobe_mcp.apps.illustrator.rigging.hierarchy_builder import build_hierarchy
    from adobe_mcp.apps.illustrator.analysis.object_classifier import classify_object
    from adobe_mcp.apps.illustrator.rigging.object_hierarchy import auto_pivots

    state = _init_wizard_state()

    # Validate image exists
    if not image_path or not os.path.isfile(image_path):
        return {
            "error": f"Image not found: {image_path}",
            "steps": state,
            "parts_found": 0,
            "connections": 0,
            "hierarchy_depth": 0,
            "suggested_type": None,
        }

    # Load or create rig
    rig = _load_rig(character_name)
    rig["image_source"] = image_path

    # Step 1: Segmentation
    try:
        import cv2
        labeled_image, centers = segment_by_color(image_path, n_clusters=n_clusters)
        original_image = cv2.imread(image_path)
        parts = extract_parts(labeled_image, original_image, min_area=min_area)
        state["segmentation"]["completed"] = True
        state["segmentation"]["result"] = {"parts_count": len(parts)}
    except Exception as exc:
        state["segmentation"]["error"] = str(exc)
        return _build_summary(state, rig, character_name, parts=[], connections=[], hierarchy=None)

    if not parts:
        state["segmentation"]["error"] = "No parts found in image"
        return _build_summary(state, rig, character_name, parts=[], connections=[], hierarchy=None)

    # Step 2: Connection detection
    try:
        connection_result = detect_connections(parts, image_path)
        connections = connection_result.get("connections", [])
        state["connection_detection"]["completed"] = True
        state["connection_detection"]["result"] = {"connections_count": len(connections)}
    except Exception as exc:
        state["connection_detection"]["error"] = str(exc)
        connections = []

    # Step 3: Hierarchy building
    hierarchy = None
    try:
        hierarchy = build_hierarchy(parts, connections)
        state["hierarchy_building"]["completed"] = True
        depth = _compute_depth(hierarchy)
        state["hierarchy_building"]["result"] = {
            "root": hierarchy.get("root"),
            "depth": depth,
        }
    except Exception as exc:
        state["hierarchy_building"]["error"] = str(exc)

    # Step 4: Classification (optional)
    suggested_type = None
    if auto_label:
        try:
            # Build symmetry info from parts arrangement
            symmetry_info = _estimate_symmetry(parts)
            classifications = classify_object(parts, symmetry_info)
            if classifications:
                suggested_type = classifications[0].get("name", "abstract")
            state["classification"]["completed"] = True
            state["classification"]["result"] = {
                "suggested_type": suggested_type,
                "top_matches": classifications[:3] if classifications else [],
            }
        except Exception as exc:
            state["classification"]["error"] = str(exc)
    else:
        state["classification"]["result"] = {"skipped": True}

    # Step 5: Pivot inference
    try:
        # Store parts and connections in rig for auto_pivots to use
        _store_parts_in_rig(rig, parts, connections, hierarchy)
        pivots = auto_pivots(rig)
        state["pivot_inference"]["completed"] = True
        state["pivot_inference"]["result"] = {"pivots_added": len(pivots)}
    except Exception as exc:
        state["pivot_inference"]["error"] = str(exc)

    # Step 6: Store rig
    try:
        if suggested_type:
            rig["object_type"] = suggested_type
        _save_rig(character_name, rig)
        state["rig_storage"]["completed"] = True
        state["rig_storage"]["result"] = {"character_name": character_name}
    except Exception as exc:
        state["rig_storage"]["error"] = str(exc)

    return _build_summary(state, rig, character_name, parts, connections, hierarchy)


def wizard_status(character_name: str) -> dict:
    """Check what wizard steps have been completed for a character.

    Loads the rig file and inspects which data has been populated
    to determine what steps are complete.

    Returns:
        Dict with step completion booleans and rig metadata.
    """
    rig = _load_rig(character_name)

    has_image = bool(rig.get("image_source"))
    has_joints = bool(rig.get("joints"))
    has_bones = bool(rig.get("bones"))
    has_landmarks = bool(rig.get("landmarks"))
    has_type = bool(rig.get("object_type"))
    has_parts = bool(rig.get("wizard_parts"))

    return {
        "character_name": character_name,
        "rig_exists": has_image or has_joints or has_bones,
        "steps": {
            "segmentation": has_parts,
            "connection_detection": bool(rig.get("wizard_connections")),
            "hierarchy_building": bool(rig.get("wizard_hierarchy")),
            "classification": has_type,
            "pivot_inference": has_landmarks,
            "rig_storage": has_image or has_joints,
        },
        "parts_count": len(rig.get("wizard_parts", [])),
        "joints_count": len(rig.get("joints", {})),
        "object_type": rig.get("object_type"),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_depth(hierarchy: Optional[dict]) -> int:
    """Compute the maximum depth of the hierarchy tree."""
    if not hierarchy or not hierarchy.get("nodes"):
        return 0

    nodes = {n["name"]: n for n in hierarchy["nodes"]}
    root_name = hierarchy.get("root")
    if not root_name or root_name not in nodes:
        return 0

    def _depth(name: str) -> int:
        node = nodes.get(name)
        if not node or not node.get("children"):
            return 1
        return 1 + max(_depth(child) for child in node["children"])

    return _depth(root_name)


def _estimate_symmetry(parts: list[dict]) -> dict:
    """Estimate bilateral symmetry from part arrangement.

    Simple heuristic: if parts exist on both sides of the center,
    bilateral symmetry is likely.
    """
    if not parts:
        return {"bilateral": {"detected": False}, "radial": {"detected": False}}

    # Find center x from all parts
    xs = [p.get("centroid", [0, 0])[0] for p in parts if p.get("centroid")]
    if not xs:
        return {"bilateral": {"detected": False}, "radial": {"detected": False}}

    center_x = sum(xs) / len(xs)
    left_count = sum(1 for x in xs if x < center_x - 5)
    right_count = sum(1 for x in xs if x > center_x + 5)

    bilateral_detected = left_count > 0 and right_count > 0
    confidence = min(left_count, right_count) / max(max(left_count, right_count), 1)

    return {
        "bilateral": {"detected": bilateral_detected, "confidence": round(confidence, 2)},
        "radial": {"detected": False},
    }


def _store_parts_in_rig(
    rig: dict,
    parts: list[dict],
    connections: list[dict],
    hierarchy: Optional[dict],
) -> None:
    """Store wizard data into the rig for later inspection and pivot inference.

    Converts parts into joints and bones so auto_pivots can find them.
    """
    rig["wizard_parts"] = parts
    rig["wizard_connections"] = connections
    rig["wizard_hierarchy"] = hierarchy

    # Create joints from part centroids
    for part in parts:
        name = part.get("name", "")
        centroid = part.get("centroid", [0, 0])
        rig["joints"][name] = {
            "position": centroid,
            "area": part.get("area", 0),
        }

    # Create bones from connections
    bones = []
    for conn in connections:
        if conn.get("type") in ("joint", "adjacent"):
            bones.append({
                "name": f"{conn['part_a']}_to_{conn['part_b']}",
                "parent_joint": conn["part_a"],
                "child_joint": conn["part_b"],
                "position": conn.get("position"),
            })
    rig["bones"] = bones


def _build_summary(
    state: dict,
    rig: dict,
    character_name: str,
    parts: list,
    connections: list,
    hierarchy: Optional[dict],
) -> dict:
    """Assemble the wizard result summary."""
    completed_steps = sum(1 for s in state.values() if s.get("completed"))
    failed_steps = [name for name, s in state.items() if s.get("error")]

    return {
        "character_name": character_name,
        "parts_found": len(parts),
        "connections": len(connections),
        "hierarchy_depth": _compute_depth(hierarchy) if hierarchy else 0,
        "suggested_type": rig.get("object_type"),
        "steps_completed": completed_steps,
        "steps_total": len(_STEPS),
        "steps": state,
        "errors": failed_steps,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_wizard tool."""

    @mcp.tool(
        name="adobe_ai_character_wizard",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_wizard(params: AiCharacterWizardInput) -> str:
        """One-call character creation from a reference image.

        Chains segmentation, connection detection, hierarchy building,
        classification, and pivot inference into a single wizard call.
        """
        action = params.action.lower().strip()

        if action == "run_wizard":
            if not params.image_path:
                return json.dumps({"error": "image_path is required for run_wizard"})
            result = run_wizard(
                image_path=params.image_path,
                character_name=params.character_name,
                auto_label=params.auto_label,
                n_clusters=params.n_clusters,
                min_area=params.min_area,
            )
            return json.dumps(result)

        elif action == "wizard_status":
            result = wizard_status(params.character_name)
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}. Use run_wizard or wizard_status."})
