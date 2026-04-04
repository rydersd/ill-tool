"""Build a connected bone structure from annotated skeleton joints.

Reads joint positions from the rig file and creates named bones (parent->child
joint pairs). For the "biped" preset, generates standard spine, arm, and leg
bone chains from whatever joints are present.

When show_bones is True, draws each bone as a line and each joint as a circle
on a "Skeleton" layer in Illustrator so the artist can see the hierarchy.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiSkeletonBuildInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# Standard biped bone definitions: (bone_name, parent_joint, child_joint)
_BIPED_BONES = [
    # Spine chain
    ("spine_lower", "spine_base", "spine_mid"),
    ("spine_upper", "spine_mid", "spine_top"),
    ("spine_neck", "spine_top", "neck"),
    ("neck_head", "neck", "head"),
    # Left arm chain
    ("upper_arm_l", "shoulder_l", "elbow_l"),
    ("forearm_l", "elbow_l", "wrist_l"),
    # Right arm chain
    ("upper_arm_r", "shoulder_r", "elbow_r"),
    ("forearm_r", "elbow_r", "wrist_r"),
    # Left leg chain
    ("upper_leg_l", "hip_l", "knee_l"),
    ("lower_leg_l", "knee_l", "ankle_l"),
    # Right leg chain
    ("upper_leg_r", "hip_r", "knee_r"),
    ("lower_leg_r", "knee_r", "ankle_r"),
]


def register(mcp):
    """Register the adobe_ai_skeleton_build tool."""

    @mcp.tool(
        name="adobe_ai_skeleton_build",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_skeleton_build(params: AiSkeletonBuildInput) -> str:
        """Build a connected bone structure from annotated joints.

        For the 'biped' preset, creates standard spine, arm, and leg bones
        from whichever joints are present. Missing joints are skipped.
        If show_bones is True, draws bone lines and joint circles on a
        Skeleton layer in Illustrator.
        """
        rig = _load_rig(params.character_name)
        joints = rig.get("joints", {})

        if not joints:
            return json.dumps({
                "error": "No joints found. Run skeleton_annotate first.",
                "character": params.character_name,
            })

        # Build bone list from preset
        if params.preset == "biped":
            bone_defs = _BIPED_BONES
        elif params.preset == "quadruped":
            # Quadruped uses same structure but adds front/back distinction.
            # For now, use biped bones as a foundation — quadruped-specific
            # joints (e.g. spine_base_tail, paw_*) can be added later.
            bone_defs = _BIPED_BONES
        elif params.preset == "custom":
            # Custom keeps whatever bones already exist in the rig
            bone_defs = [
                (b["name"], b["parent_joint"], b["child_joint"])
                for b in rig.get("bones", [])
            ]
        else:
            return json.dumps({
                "error": f"Unknown preset: {params.preset}. Use biped, quadruped, or custom.",
            })

        # Filter to only bones where both parent and child joints exist
        built_bones = []
        skipped_bones = []
        for bone_name, parent_joint, child_joint in bone_defs:
            if parent_joint in joints and child_joint in joints:
                built_bones.append({
                    "name": bone_name,
                    "parent_joint": parent_joint,
                    "child_joint": child_joint,
                })
            else:
                missing = []
                if parent_joint not in joints:
                    missing.append(parent_joint)
                if child_joint not in joints:
                    missing.append(child_joint)
                skipped_bones.append({
                    "name": bone_name,
                    "missing_joints": missing,
                })

        rig["bones"] = built_bones
        _save_rig(params.character_name, rig)

        # Draw bones and joints on Skeleton layer if requested
        draw_result = None
        if params.show_bones and built_bones:
            # Build JSX to draw bone lines and joint circles
            bone_draw_parts = []
            joint_radius = 4

            # Draw each bone as a line
            for bone in built_bones:
                parent = joints[bone["parent_joint"]]
                child = joints[bone["child_joint"]]
                escaped_name = escape_jsx_string(bone["name"])
                bone_draw_parts.append(f"""
    var bone_{bone["name"].replace("-", "_")} = layer.pathItems.add();
    bone_{bone["name"].replace("-", "_")}.setEntirePath([
        [{parent["x"]}, {parent["y"]}],
        [{child["x"]}, {child["y"]}]
    ]);
    bone_{bone["name"].replace("-", "_")}.filled = false;
    bone_{bone["name"].replace("-", "_")}.stroked = true;
    bone_{bone["name"].replace("-", "_")}.strokeWidth = 2;
    bone_{bone["name"].replace("-", "_")}.strokeColor = boneColor;
    bone_{bone["name"].replace("-", "_")}.name = "bone_{escaped_name}";
""")

            # Draw joint circles at each unique joint position
            drawn_joints = set()
            for bone in built_bones:
                for jname in [bone["parent_joint"], bone["child_joint"]]:
                    if jname not in drawn_joints:
                        drawn_joints.add(jname)
                        jpos = joints[jname]
                        escaped_jname = escape_jsx_string(jname)
                        bone_draw_parts.append(f"""
    var jm_{jname.replace("-", "_")} = layer.pathItems.ellipse(
        {jpos["y"] + joint_radius}, {jpos["x"] - joint_radius},
        {joint_radius * 2}, {joint_radius * 2}
    );
    jm_{jname.replace("-", "_")}.fillColor = jointColor;
    jm_{jname.replace("-", "_")}.stroked = false;
    jm_{jname.replace("-", "_")}.name = "joint_{escaped_jname}";
""")

            draw_jsx = "\n".join(bone_draw_parts)

            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Remove existing skeleton visualization
    var layer = null;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Skeleton") {{
            layer = doc.layers[i];
            // Clear old bone/joint items
            for (var j = layer.pageItems.length - 1; j >= 0; j--) {{
                var n = layer.pageItems[j].name;
                if (n.indexOf("bone_") === 0 || n.indexOf("joint_") === 0) {{
                    layer.pageItems[j].remove();
                }}
            }}
            break;
        }}
    }}
    if (!layer) {{
        layer = doc.layers.add();
        layer.name = "Skeleton";
    }}
    doc.activeLayer = layer;

    // Bone line color
    var boneColor = new RGBColor();
    boneColor.red = {params.bone_color_r};
    boneColor.green = {params.bone_color_g};
    boneColor.blue = {params.bone_color_b};

    // Joint circle color (brighter version of bone color)
    var jointColor = new RGBColor();
    jointColor.red = Math.min(255, {params.bone_color_r} + 80);
    jointColor.green = Math.min(255, {params.bone_color_g} + 80);
    jointColor.blue = Math.min(255, {params.bone_color_b} + 80);

{draw_jsx}

    return JSON.stringify({{
        bones_drawn: {len(built_bones)},
        joints_drawn: {len(drawn_joints)}
    }});
}})();
"""
            draw_result = await _async_run_jsx("illustrator", jsx)

        response = {
            "action": "build",
            "preset": params.preset,
            "bones_built": len(built_bones),
            "bones": [b["name"] for b in built_bones],
            "skipped": skipped_bones if skipped_bones else None,
            "character": params.character_name,
        }

        if draw_result:
            response["visualization"] = {
                "drawn": draw_result["success"],
                "error": draw_result.get("stderr") if not draw_result["success"] else None,
            }

        return json.dumps(response, indent=2)
