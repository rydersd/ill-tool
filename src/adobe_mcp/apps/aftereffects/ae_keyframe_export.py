"""Export character rig keyframe timelines to After Effects keyframes.

Reads pose data from the Illustrator rig, computes rotation and position
deltas for each body part relative to the rest pose, and sets AE keyframes
on the corresponding layers. Supports easing (linear, ease_in, ease_out,
ease_in_out) via AE's KeyframeEase API.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeKeyframeExportInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


def _compute_bone_angle(joint_pos: dict, parent_pos: dict) -> float:
    """Compute the angle of a bone from parent to child joint in degrees.

    Uses atan2 to calculate the angle of the vector from parent_pos to
    joint_pos, measured counter-clockwise from the positive X axis.

    Args:
        joint_pos: Dict with 'x' and 'y' for the child joint.
        parent_pos: Dict with 'x' and 'y' for the parent joint.

    Returns:
        Angle in degrees.
    """
    dx = joint_pos.get("x", 0) - parent_pos.get("x", 0)
    dy = joint_pos.get("y", 0) - parent_pos.get("y", 0)
    return math.degrees(math.atan2(dy, dx))


def _compute_pose_transforms(
    rig: dict,
    pose_name: str,
    rest_joints: dict,
) -> dict[str, dict]:
    """Compute rotation and position deltas for a pose relative to rest.

    For each body part binding, compares the joint positions in the given
    pose against the rest pose positions. Calculates:
    - rotation: Angle change of each bone
    - position: Position offset of the joint

    Args:
        rig: The full rig dict.
        pose_name: Name of the pose in rig["poses"].
        rest_joints: The rest-pose joint positions dict.

    Returns:
        Dict mapping body_part_name -> {rotation: float, position: [x, y]}
    """
    poses = rig.get("poses", {})
    pose_data = poses.get(pose_name, {})
    pose_joints = pose_data.get("joints", {})
    bones = rig.get("bones", [])
    bindings = rig.get("bindings", {})

    # Build bone parent map: child_joint -> parent_joint
    joint_parent = {}
    for bone in bones:
        if len(bone) >= 2:
            joint_parent[bone[1]] = bone[0]

    transforms = {}
    for part_name, joint_name in bindings.items():
        # Get rest and pose positions for this joint
        rest_pos = rest_joints.get(joint_name, {"x": 0, "y": 0})
        pose_pos = pose_joints.get(joint_name, rest_pos)

        # Compute rotation delta using the parent bone angle
        rotation = 0.0
        parent_joint = joint_parent.get(joint_name)
        if parent_joint:
            rest_parent = rest_joints.get(parent_joint, {"x": 0, "y": 0})
            pose_parent = pose_joints.get(parent_joint, rest_parent)

            rest_angle = _compute_bone_angle(rest_pos, rest_parent)
            pose_angle = _compute_bone_angle(pose_pos, pose_parent)
            rotation = pose_angle - rest_angle

        # Compute position delta
        pos_dx = pose_pos.get("x", 0) - rest_pos.get("x", 0)
        pos_dy = pose_pos.get("y", 0) - rest_pos.get("y", 0)

        transforms[part_name] = {
            "rotation": rotation,
            "position": [pose_pos.get("x", 0), pose_pos.get("y", 0)],
            "position_delta": [pos_dx, pos_dy],
        }

    return transforms


def _build_keyframe_jsx(
    comp_name: str,
    fps: float,
    keyframe_data: list[dict],
    easing: str,
) -> str:
    """Build JSX to set rotation and position keyframes on character layers.

    Args:
        comp_name: Target AE composition name.
        fps: Frame rate for time conversion.
        keyframe_data: List of dicts, each with:
            - frame: Frame number
            - transforms: dict of part_name -> {rotation, position_delta}
        easing: Easing type: linear, ease_in, ease_out, ease_in_out

    Returns:
        JSX code string.
    """
    comp_sel = ae_comp_selector(comp_name)

    # Build per-layer keyframe setting blocks
    keyframe_blocks = []
    for kf in keyframe_data:
        frame = kf["frame"]
        time_sec = frame / fps
        transforms = kf.get("transforms", {})

        for part_name, xform in transforms.items():
            layer_name = escape_jsx_string(part_name)
            rotation = xform.get("rotation", 0)
            pos_delta = xform.get("position_delta", [0, 0])

            keyframe_blocks.append(f"""
try {{
    var lyr = comp.layer("{layer_name}");
    if (lyr) {{
        // Set rotation keyframe
        var rotProp = lyr.property("Transform").property("Rotation");
        rotProp.setValueAtTime({time_sec}, {rotation});
        keyframesSet++;

        // Set position keyframe if there is movement
        if ({abs(pos_delta[0])} > 0.01 || {abs(pos_delta[1])} > 0.01) {{
            var posProp = lyr.property("Transform").property("Position");
            var basePos = posProp.valueAtTime(0, false);
            posProp.setValueAtTime({time_sec}, [basePos[0] + {pos_delta[0]}, basePos[1] + {pos_delta[1]}]);
            keyframesSet++;
        }}

        if (layersAnimated.indexOf("{layer_name}") === -1) {{
            layersAnimated.push("{layer_name}");
        }}
    }}
}} catch(e) {{
    errors.push({{ layer: "{layer_name}", frame: {frame}, error: e.toString() }});
}}
""")

    keyframes_block = "\n".join(keyframe_blocks)

    # Build easing application JSX
    # After all keyframes are set, apply easing to each keyframed property
    easing_jsx = ""
    if easing != "linear":
        # Map easing type to KeyframeEase parameters
        # influence: 0-100 (how much the ease curve affects the value)
        # speed: typically 0 for smooth ease
        if easing == "ease_in":
            ease_in_influence = 33
            ease_out_influence = 0
        elif easing == "ease_out":
            ease_in_influence = 0
            ease_out_influence = 33
        else:  # ease_in_out
            ease_in_influence = 33
            ease_out_influence = 33

        easing_jsx = f"""
// Apply easing to all keyframed layers
for (var li = 0; li < layersAnimated.length; li++) {{
    try {{
        var easeLyr = comp.layer(layersAnimated[li]);
        var props = ["Rotation", "Position"];
        for (var pi = 0; pi < props.length; pi++) {{
            try {{
                var easeProp = easeLyr.property("Transform").property(props[pi]);
                if (easeProp.numKeys > 0) {{
                    for (var ki = 1; ki <= easeProp.numKeys; ki++) {{
                        var numDims = easeProp.value instanceof Array ? easeProp.value.length : 1;
                        var easeInArr = [];
                        var easeOutArr = [];
                        for (var di = 0; di < numDims; di++) {{
                            easeInArr.push(new KeyframeEase(0, {ease_in_influence}));
                            easeOutArr.push(new KeyframeEase(0, {ease_out_influence}));
                        }}
                        easeProp.setTemporalEaseAtKey(ki, easeInArr, easeOutArr);
                    }}
                }}
            }} catch(easeErr) {{}}
        }}
    }} catch(e) {{}}
}}
"""

    return f"""
// -- Export keyframe timeline to AE keyframes --
var keyframesSet = 0;
var layersAnimated = [];
var errors = [];

{comp_sel}

if (!comp) {{
    JSON.stringify({{ error: "Composition not found" }});
}} else {{
    // Set keyframes on each layer at each frame
    {keyframes_block}

    // Apply easing
    {easing_jsx}

    var result = {{
        comp: comp.name,
        keyframesSet: keyframesSet,
        layersAnimated: layersAnimated,
        easing: "{easing}"
    }};
    if (errors.length > 0) result.errors = errors;

    JSON.stringify(result, null, 2);
}}
"""


def register(mcp):
    """Register the adobe_ae_keyframe_export tool."""

    @mcp.tool(
        name="adobe_ae_keyframe_export",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ae_keyframe_export(params: AeKeyframeExportInput) -> str:
        """Export a keyframe timeline from the character rig to After Effects keyframes.

        Reads pose data and keyframe timeline from the Illustrator rig, computes
        rotation and position deltas for each body part relative to the rest pose,
        and sets keyframes on the matching AE layers with optional easing.
        """
        # Load the rig
        rig = _load_rig(params.character_name)

        if not rig.get("poses"):
            return json.dumps({
                "error": f"No poses found for character '{params.character_name}'. "
                         "Use adobe_ai_pose tools to create poses first."
            })

        # Determine the target comp
        comp_name = params.comp_name
        if not comp_name:
            ae_mapping = rig.get("ae_mapping", {})
            comp_name = ae_mapping.get("comp_name")

        if not comp_name:
            return json.dumps({
                "error": "No comp_name specified and no AE mapping found in rig. "
                         "Either provide comp_name or run adobe_ae_comp_from_character first."
            })

        # Get the rest pose joint positions as the baseline
        rest_joints = rig.get("joints", {})

        # Get the keyframe timeline from the rig
        # Timeline format: list of {frame: int, pose: str, easing: str}
        timeline = rig.get("timeline", [])

        if not timeline:
            # If no explicit timeline, create keyframes from all poses
            # spaced evenly across the composition
            poses = rig.get("poses", {})
            pose_names = list(poses.keys())
            if not pose_names:
                return json.dumps({"error": "No poses or timeline data in rig."})

            # Space poses evenly, 24 frames apart by default
            fps = 24.0
            timeline = []
            for i, pose_name in enumerate(pose_names):
                timeline.append({
                    "frame": i * 24,
                    "pose": pose_name,
                    "easing": "ease_in_out",
                })
        else:
            fps = 24.0

        # Try to get fps from rig AE config or mapping
        ae_mapping = rig.get("ae_mapping", {})
        # The comp's actual fps will be used for time conversion
        stored_fps = rig.get("ae_config", {}).get("fps")
        if stored_fps:
            fps = stored_fps

        # Compute transforms for each keyframe
        keyframe_data = []
        for kf in timeline:
            pose_name = kf.get("pose", "")
            frame = kf.get("frame", 0)

            if pose_name not in rig.get("poses", {}):
                continue

            transforms = _compute_pose_transforms(rig, pose_name, rest_joints)
            keyframe_data.append({
                "frame": frame,
                "transforms": transforms,
            })

        if not keyframe_data:
            return json.dumps({"error": "No valid keyframe data could be computed."})

        # Determine easing from the method param or timeline data
        easing = "ease_in_out"
        if params.method == "expression":
            easing = "linear"  # Expressions handle their own easing

        # Build and execute the JSX
        jsx = _build_keyframe_jsx(comp_name, fps, keyframe_data, easing)
        result = await _async_run_jsx("aftereffects", jsx)

        if not result["success"]:
            return f"Error: {result['stderr']}"

        return result["stdout"]
