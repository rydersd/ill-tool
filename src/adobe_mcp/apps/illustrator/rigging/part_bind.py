"""Bind body part labels to skeleton bones for pose-driven movement.

When a bone rotates (via joint_rotate), all paths with body part labels
bound to that bone will move/rotate together. This tool manages the
binding associations stored in the rig file.

auto_bind uses the rig's joint positions and body part labels to
automatically match each labeled part to the nearest bone based on
path center proximity to bone parent/child joints.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPartBindInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _bone_center(bone: dict, joints: dict) -> tuple:
    """Return the midpoint of a bone based on its parent/child joint positions.

    Returns (cx, cy) or None if joints are missing.
    """
    parent = joints.get(bone["parent_joint"])
    child = joints.get(bone["child_joint"])
    if not parent or not child:
        return None
    return (
        (parent["x"] + child["x"]) / 2,
        (parent["y"] + child["y"]) / 2,
    )


def register(mcp):
    """Register the adobe_ai_part_bind tool."""

    @mcp.tool(
        name="adobe_ai_part_bind",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_part_bind(params: AiPartBindInput) -> str:
        """Bind body part labels to skeleton bones for pose-driven deformation.

        Actions:
        - bind: Associate a body part label with a bone name.
        - unbind: Remove a binding association.
        - auto_bind: Automatically match each body part label to the nearest
          bone based on path center proximity.
        - list: Show current bindings.
        """
        rig = _load_rig(params.character_name)
        action = params.action.lower()

        # ── BIND ─────────────────────────────────────────────────
        if action == "bind":
            if not params.part_name:
                return json.dumps({"error": "part_name is required for bind action"})
            if not params.bone_name:
                return json.dumps({"error": "bone_name is required for bind action"})

            # Verify the bone exists in the rig
            bone_names = [b["name"] for b in rig.get("bones", [])]
            if params.bone_name not in bone_names:
                return json.dumps({
                    "error": f"Bone '{params.bone_name}' not found in rig. Available: {bone_names}",
                    "character": params.character_name,
                })

            # Add part_name to the bone's binding list
            bindings = rig.get("bindings", {})
            if params.bone_name not in bindings:
                bindings[params.bone_name] = []
            if params.part_name not in bindings[params.bone_name]:
                bindings[params.bone_name].append(params.part_name)
            rig["bindings"] = bindings
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "bind",
                "part": params.part_name,
                "bone": params.bone_name,
                "character": params.character_name,
            })

        # ── UNBIND ───────────────────────────────────────────────
        elif action == "unbind":
            if not params.part_name:
                return json.dumps({"error": "part_name is required for unbind action"})

            bindings = rig.get("bindings", {})
            unbound_from = None

            # Search all bones for this part and remove it
            for bone_name, parts in bindings.items():
                if params.part_name in parts:
                    parts.remove(params.part_name)
                    unbound_from = bone_name
                    # Clean up empty binding lists
                    if not parts:
                        del bindings[bone_name]
                    break

            rig["bindings"] = bindings
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "unbind",
                "part": params.part_name,
                "was_bound_to": unbound_from,
                "character": params.character_name,
            })

        # ── LIST ─────────────────────────────────────────────────
        elif action == "list":
            bindings = rig.get("bindings", {})
            total_parts = sum(len(parts) for parts in bindings.values())

            return json.dumps({
                "action": "list",
                "character": params.character_name,
                "bindings": bindings,
                "bone_count": len(bindings),
                "total_bound_parts": total_parts,
            }, indent=2)

        # ── AUTO_BIND ────────────────────────────────────────────
        elif action == "auto_bind":
            joints = rig.get("joints", {})
            bones = rig.get("bones", [])
            body_part_labels = rig.get("body_part_labels", {})

            if not bones:
                return json.dumps({
                    "error": "No bones found. Run skeleton_build first.",
                    "character": params.character_name,
                })

            if not body_part_labels:
                return json.dumps({
                    "error": "No body part labels found. Run body_part_label first.",
                    "character": params.character_name,
                })

            # Get path center positions from Illustrator for distance calculations
            jsx = """
(function() {
    var doc = app.activeDocument;
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Drawing") {
            layer = doc.layers[i];
            break;
        }
    }
    if (!layer) {
        return JSON.stringify({error: "No Drawing layer found"});
    }

    var items = {};
    for (var i = 0; i < layer.pathItems.length; i++) {
        var p = layer.pathItems[i];
        var b = p.geometricBounds;
        var cx = (b[0] + b[2]) / 2;
        var cy = (b[1] + b[3]) / 2;
        var name = p.name || ("path_" + i);
        items[name] = {center_x: cx, center_y: cy};
    }
    return JSON.stringify({items: items});
})();
"""
            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({
                    "error": f"Failed to query Drawing layer: {result['stderr']}",
                    "character": params.character_name,
                })

            try:
                data = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({
                    "error": f"Bad response from Illustrator: {result['stdout']}",
                    "character": params.character_name,
                })

            if "error" in data:
                return json.dumps(data)

            path_centers = data["items"]

            # For each body part label, find the bone whose parent/child joints
            # are closest to the labeled path's center
            new_bindings = {}
            binding_details = {}

            for item_name, body_part in body_part_labels.items():
                # Get the path's center from AI
                center = path_centers.get(item_name)
                if not center:
                    # Path not found on Drawing layer, skip
                    continue

                cx = center["center_x"]
                cy = center["center_y"]

                # Find nearest bone by comparing to bone midpoints
                best_bone = None
                best_dist = float("inf")

                for bone in bones:
                    bone_mid = _bone_center(bone, joints)
                    if bone_mid is None:
                        continue
                    d = _distance(cx, cy, bone_mid[0], bone_mid[1])
                    if d < best_dist:
                        best_dist = d
                        best_bone = bone["name"]

                if best_bone:
                    if best_bone not in new_bindings:
                        new_bindings[best_bone] = []
                    if item_name not in new_bindings[best_bone]:
                        new_bindings[best_bone].append(item_name)
                    binding_details[item_name] = {
                        "body_part": body_part,
                        "bound_to": best_bone,
                        "distance": round(best_dist, 1),
                    }

            rig["bindings"] = new_bindings
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "auto_bind",
                "character": params.character_name,
                "bindings": new_bindings,
                "details": binding_details,
                "total_bound": len(binding_details),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}. Use bind, unbind, auto_bind, or list.",
            })
