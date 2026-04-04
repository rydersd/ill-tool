"""Assign semantic body part labels to Illustrator path items and groups.

Labels are stored in the rig file at /tmp/ai_rigs/{character_name}.json
under the body_part_labels dict, mapping pathItem/group names to body part
identifiers (head, upper_arm_l, torso, etc.).

auto_label uses JSX to get all pathItem centers from the Drawing layer,
then assigns each to the nearest skeleton joint's body part.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiBodyPartLabelInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# Mapping from joint name to the body part it controls.
# Multiple joints can map to the same body part (e.g., spine_top and neck
# both relate to the torso region).
_JOINT_TO_BODY_PART = {
    "head": "head",
    "neck": "head",
    "spine_top": "torso",
    "spine_mid": "torso",
    "spine_base": "torso",
    "shoulder_l": "upper_arm_l",
    "elbow_l": "forearm_l",
    "wrist_l": "hand_l",
    "shoulder_r": "upper_arm_r",
    "elbow_r": "forearm_r",
    "wrist_r": "hand_r",
    "hip_l": "upper_leg_l",
    "knee_l": "lower_leg_l",
    "ankle_l": "foot_l",
    "hip_r": "upper_leg_r",
    "knee_r": "lower_leg_r",
    "ankle_r": "foot_r",
}


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def register(mcp):
    """Register the adobe_ai_body_part_label tool."""

    @mcp.tool(
        name="adobe_ai_body_part_label",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_body_part_label(params: AiBodyPartLabelInput) -> str:
        """Assign semantic body part labels to path items or groups.

        Actions:
        - label: Manually assign a body_part label to an item/group name.
        - auto_label: For each pathItem on the Drawing layer, find the nearest
          skeleton joint and assign the corresponding body part label.
        - list: Show current label assignments.
        """
        rig = _load_rig(params.character_name)
        action = params.action.lower()

        # ── LABEL ────────────────────────────────────────────────
        if action == "label":
            if not params.item_name:
                return json.dumps({"error": "item_name is required for label action"})
            if not params.body_part:
                return json.dumps({"error": "body_part is required for label action"})

            rig["body_part_labels"][params.item_name] = params.body_part
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "label",
                "item": params.item_name,
                "body_part": params.body_part,
                "character": params.character_name,
            })

        # ── LIST ─────────────────────────────────────────────────
        elif action == "list":
            return json.dumps({
                "action": "list",
                "character": params.character_name,
                "body_part_labels": rig.get("body_part_labels", {}),
                "count": len(rig.get("body_part_labels", {})),
            }, indent=2)

        # ── AUTO_LABEL ───────────────────────────────────────────
        elif action == "auto_label":
            joints = rig.get("joints", {})
            if not joints:
                return json.dumps({
                    "error": "No joints found in rig. Run skeleton_annotate first.",
                    "character": params.character_name,
                })

            # Get all pathItem names and their center coordinates from the Drawing layer
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

    var items = [];
    for (var i = 0; i < layer.pathItems.length; i++) {
        var p = layer.pathItems[i];
        var b = p.geometricBounds;  // [left, top, right, bottom]
        var cx = (b[0] + b[2]) / 2;
        var cy = (b[1] + b[3]) / 2;
        items.push({
            name: p.name || ("path_" + i),
            index: i,
            center_x: cx,
            center_y: cy
        });
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

            path_items = data["items"]
            if not path_items:
                return json.dumps({
                    "action": "auto_label",
                    "labeled": 0,
                    "message": "No pathItems found on Drawing layer",
                    "character": params.character_name,
                })

            # For each path, find the nearest joint and assign the
            # corresponding body part label
            assignments = {}
            for item in path_items:
                item_cx = item["center_x"]
                item_cy = item["center_y"]
                item_name = item["name"]

                nearest_joint = None
                nearest_dist = float("inf")

                for jname, jpos in joints.items():
                    d = _distance(item_cx, item_cy, jpos["x"], jpos["y"])
                    if d < nearest_dist:
                        nearest_dist = d
                        nearest_joint = jname

                if nearest_joint:
                    body_part = _JOINT_TO_BODY_PART.get(nearest_joint, nearest_joint)
                    rig["body_part_labels"][item_name] = body_part
                    assignments[item_name] = {
                        "body_part": body_part,
                        "nearest_joint": nearest_joint,
                        "distance": round(nearest_dist, 1),
                    }

            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "auto_label",
                "labeled": len(assignments),
                "assignments": assignments,
                "character": params.character_name,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}. Use label, auto_label, or list.",
            })
