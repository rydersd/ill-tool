"""Map skeleton joints to AE layer anchor points and parent chains.

Sets each body part layer's anchor point to its controlling joint position,
then parents layers according to the bone hierarchy (e.g. forearm -> upper_arm
-> torso). This enables rotation-based character animation where each layer
pivots around its joint.

Note: True puppet pins are difficult to create via ExtendScript. The anchor-
point-at-joint + layer parenting approach produces the same rotational
control and is fully scriptable.
"""

import json
import math

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AePuppetPinsInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _build_layer_setup_jsx(comp_name: str, layer_configs: list[dict]) -> str:
    """Build JSX to set anchor points and parent chains for character layers.

    For each layer config, the script:
    1. Finds the layer by name in the target composition
    2. Sets its anchor point to the joint position
    3. Adjusts position to compensate for the anchor point change

    After all anchor points are set, a second pass establishes parenting.
    Parenting must happen after all anchor points are configured because
    AE recalculates child positions relative to the parent's anchor point.

    Args:
        comp_name: Name of the AE composition containing the character.
        layer_configs: List of dicts with keys:
            - layer_name: AE layer name
            - joint_x, joint_y: Joint position in comp coordinates
            - parent_layer: Name of the parent layer (or None)

    Returns:
        JSX code string ready for execution in After Effects.
    """
    comp_sel = ae_comp_selector(comp_name)

    # Build the anchor point + position offset JSX for each layer
    anchor_jsx_parts = []
    parent_jsx_parts = []

    for cfg in layer_configs:
        layer_name = escape_jsx_string(cfg["layer_name"])
        jx = cfg["joint_x"]
        jy = cfg["joint_y"]

        # Set anchor point and adjust position to keep the layer in place visually
        anchor_jsx_parts.append(f"""
try {{
    var lyr = comp.layer("{layer_name}");
    if (lyr) {{
        // Calculate the delta between new and old anchor points
        var oldAnchor = lyr.property("Transform").property("Anchor Point").value;
        var oldPos = lyr.property("Transform").property("Position").value;

        // Set anchor point to the joint position (in layer-local coordinates)
        lyr.property("Transform").property("Anchor Point").setValue([{jx}, {jy}]);

        // Offset position to compensate so the layer doesn't visually jump
        var dx = {jx} - oldAnchor[0];
        var dy = {jy} - oldAnchor[1];
        lyr.property("Transform").property("Position").setValue([oldPos[0] + dx, oldPos[1] + dy]);

        configured.push({{ layer: "{layer_name}", anchorPoint: [{jx}, {jy}] }});
    }} else {{
        notFound.push("{layer_name}");
    }}
}} catch(e) {{
    errors.push({{ layer: "{layer_name}", error: e.toString() }});
}}
""")

        # Set up parenting if specified
        if cfg.get("parent_layer"):
            parent_name = escape_jsx_string(cfg["parent_layer"])
            parent_jsx_parts.append(f"""
try {{
    var child = comp.layer("{layer_name}");
    var parent = comp.layer("{parent_name}");
    if (child && parent) {{
        child.parent = parent;
        parentChain.push({{ child: "{layer_name}", parent: "{parent_name}" }});
    }}
}} catch(e) {{
    parentErrors.push({{ child: "{layer_name}", parent: "{parent_name}", error: e.toString() }});
}}
""")

    anchors_block = "\n".join(anchor_jsx_parts)
    parents_block = "\n".join(parent_jsx_parts)

    return f"""
// -- Set anchor points at joint positions and establish parent chain --
var configured = [];
var notFound = [];
var errors = [];
var parentChain = [];
var parentErrors = [];

{comp_sel}

if (!comp) {{
    JSON.stringify({{ error: "Composition not found" }});
}} else {{
    // Pass 1: Set anchor points at joint positions
    {anchors_block}

    // Pass 2: Establish parent chain (after all anchors are set)
    {parents_block}

    var result = {{
        comp: comp.name,
        configured: configured,
        parentChain: parentChain
    }};
    if (notFound.length > 0) result.notFound = notFound;
    if (errors.length > 0) result.errors = errors;
    if (parentErrors.length > 0) result.parentErrors = parentErrors;

    JSON.stringify(result, null, 2);
}}
"""


def _build_layer_configs_from_rig(rig: dict) -> list[dict]:
    """Derive layer anchor/parent configs from the rig's joints and bones.

    Maps each binding (body_part -> joint) to a layer config with the joint's
    position as the anchor point. Uses the bone hierarchy to determine parent
    layers: if joint A connects to joint B via a bone, and body_part_X is
    bound to joint A while body_part_Y is bound to joint B, then the layer
    for body_part_X parents to body_part_Y (the parent in the skeletal chain).

    Returns:
        List of layer config dicts for _build_layer_setup_jsx.
    """
    joints = rig.get("joints", {})
    bones = rig.get("bones", [])
    bindings = rig.get("bindings", {})

    # Invert bindings: joint_name -> body_part_name
    joint_to_part = {}
    for part_name, joint_name in bindings.items():
        joint_to_part[joint_name] = part_name

    # Build a parent map from bones: for each bone [jointA, jointB],
    # jointB is the child of jointA (convention: first joint is parent)
    joint_parent = {}
    for bone in bones:
        if len(bone) >= 2:
            parent_joint = bone[0]
            child_joint = bone[1]
            joint_parent[child_joint] = parent_joint

    configs = []
    for part_name, joint_name in bindings.items():
        joint_data = joints.get(joint_name, {})
        jx = joint_data.get("x", 0)
        jy = joint_data.get("y", 0)

        # Determine the parent layer by walking up the bone hierarchy
        parent_layer = None
        parent_joint = joint_parent.get(joint_name)
        if parent_joint and parent_joint in joint_to_part:
            parent_layer = joint_to_part[parent_joint]

        configs.append({
            "layer_name": part_name,
            "joint_x": jx,
            "joint_y": jy,
            "parent_layer": parent_layer,
        })

    return configs


def register(mcp):
    """Register the adobe_ae_puppet_pins tool."""

    @mcp.tool(
        name="adobe_ae_puppet_pins",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ae_puppet_pins(params: AePuppetPinsInput) -> str:
        """Map skeleton joint positions to AE layer anchor points and parent chains.

        For each body part layer in the character composition:
        - Sets the anchor point to the controlling joint position (so rotation
          pivots around the joint)
        - Parents layers according to the bone hierarchy (forearm -> upper_arm
          -> torso, etc.)

        This enables transform-based character animation where rotating a parent
        layer cascades through the skeletal chain.
        """
        # Load the rig to get joint positions and bone hierarchy
        rig = _load_rig(params.character_name)

        if not rig.get("joints"):
            return json.dumps({
                "error": f"No joints found for character '{params.character_name}'. "
                         "Use adobe_ai_skeleton tools to create joints first."
            })

        if not rig.get("bindings"):
            return json.dumps({
                "error": f"No bindings found for character '{params.character_name}'. "
                         "Use adobe_ai_bind tool to bind body parts to joints first."
            })

        # Determine which comp to target
        comp_name = params.comp_name
        if not comp_name:
            # Try to get it from the AE mapping stored during comp creation
            ae_mapping = rig.get("ae_mapping", {})
            comp_name = ae_mapping.get("comp_name")

        if not comp_name:
            return json.dumps({
                "error": "No comp_name specified and no AE mapping found in rig. "
                         "Either provide comp_name or run adobe_ae_comp_from_character first."
            })

        # Build layer configs from the rig's skeletal data
        layer_configs = _build_layer_configs_from_rig(rig)

        if not layer_configs:
            return json.dumps({
                "error": "No layer configurations could be derived from rig bindings."
            })

        # Build and execute the JSX
        jsx = _build_layer_setup_jsx(comp_name, layer_configs)
        result = await _async_run_jsx("aftereffects", jsx)

        if not result["success"]:
            return f"Error: {result['stderr']}"

        # Store the pin stiffness preference in the rig for reference
        rig.setdefault("ae_config", {})["pin_stiffness"] = params.pin_stiffness
        _save_rig(params.character_name, rig)

        return result["stdout"]
