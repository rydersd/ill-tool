"""Generate AE expressions for procedural bone-driven character animation.

Creates After Effects expressions that add organic motion to character layers:
- rotation: Oscillating rotation (wiggle-based or sinusoidal)
- position: Follow-through / overlap animation with configurable delay
- wiggle: Organic random movement on any property
- loopOut: Cycle keyframe animation seamlessly

Expressions are applied to layer properties in the target composition,
referencing the character rig's joint/bone structure for correct targeting.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.aftereffects._helpers import ae_comp_selector
from adobe_mcp.apps.aftereffects.models import AeExpressionGenInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig


# Expression templates for each type of procedural animation.
# Each template is a valid AE expression (JavaScript) that references
# the layer hierarchy via thisComp.layer() and transform properties.

_EXPRESSION_TEMPLATES = {
    "rotation": {
        # Organic oscillating rotation: combines wiggle with a sine-based
        # secondary motion for natural-feeling movement
        "expression": (
            "// Organic rotation for {joint_name}\n"
            "var freq = {freq};\n"
            "var amp = {amp};\n"
            "wiggle(freq, amp)"
        ),
        "property": "Rotation",
        "defaults": {"freq": 2, "amp": 15},
    },
    "position": {
        # Follow-through / overlap: the layer follows its parent with a
        # configurable time delay, creating drag and overlap motion
        "expression": (
            "// Follow-through for {joint_name}\n"
            "var delay = {delay};\n"
            "var parentLayer = thisComp.layer(\"{parent_layer}\");\n"
            "parentLayer.transform.position.valueAtTime(time - delay)"
        ),
        "property": "Position",
        "defaults": {"delay": 0.1},
    },
    "wiggle": {
        # General-purpose organic wiggle: adds randomized movement
        # to any property for liveliness
        "expression": (
            "// Wiggle for {joint_name}\n"
            "var freq = {freq};\n"
            "var amp = {amp};\n"
            "wiggle(freq, amp)"
        ),
        "property": "Position",
        "defaults": {"freq": 3, "amp": 5},
    },
    "loopOut": {
        # Seamless keyframe looping: cycles all keyframes on the property
        "expression": (
            "// Loop keyframes for {joint_name}\n"
            "loopOut(\"cycle\")"
        ),
        "property": "Rotation",
        "defaults": {},
    },
}


def _build_expression_jsx(
    comp_name: str,
    layer_expressions: list[dict],
) -> str:
    """Build JSX to apply expressions to character layers.

    Args:
        comp_name: Target AE composition.
        layer_expressions: List of dicts with:
            - layer_name: AE layer name
            - property_name: Property to apply expression to (e.g. "Rotation")
            - expression: The expression code string

    Returns:
        JSX code string.
    """
    comp_sel = ae_comp_selector(comp_name)

    apply_blocks = []
    for le in layer_expressions:
        layer_name = escape_jsx_string(le["layer_name"])
        prop_name = escape_jsx_string(le["property_name"])
        # Escape the expression for embedding in a JSX string literal
        expr = (
            le["expression"]
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "")
        )

        apply_blocks.append(f"""
try {{
    var lyr = comp.layer("{layer_name}");
    if (lyr) {{
        var prop = lyr.property("Transform").property("{prop_name}");
        prop.expression = "{expr}";
        applied.push({{ layer: "{layer_name}", property: "{prop_name}" }});
    }} else {{
        notFound.push("{layer_name}");
    }}
}} catch(e) {{
    errors.push({{ layer: "{layer_name}", property: "{prop_name}", error: e.toString() }});
}}
""")

    apply_block = "\n".join(apply_blocks)

    return f"""
// -- Apply expressions to character layers --
var applied = [];
var notFound = [];
var errors = [];

{comp_sel}

if (!comp) {{
    JSON.stringify({{ error: "Composition not found" }});
}} else {{
    {apply_block}

    var result = {{
        comp: comp.name,
        expressionsApplied: applied
    }};
    if (notFound.length > 0) result.notFound = notFound;
    if (errors.length > 0) result.errors = errors;

    JSON.stringify(result, null, 2);
}}
"""


def _generate_expressions_for_rig(
    rig: dict,
    expression_type: str,
    joint_name: str | None,
) -> list[dict]:
    """Generate expression configs for character layers based on rig data.

    If joint_name is specified, generates an expression only for the layer
    bound to that joint. Otherwise, generates expressions for all bound
    layers (with appropriate defaults based on their position in the
    skeletal hierarchy).

    Args:
        rig: The character rig dict.
        expression_type: One of "rotation", "position", "wiggle", "loopOut".
        joint_name: Specific joint to target, or None for all joints.

    Returns:
        List of dicts with layer_name, property_name, and expression.
    """
    template_info = _EXPRESSION_TEMPLATES.get(expression_type)
    if not template_info:
        return []

    bindings = rig.get("bindings", {})
    bones = rig.get("bones", [])

    # Build parent map for follow-through expressions
    joint_parent = {}
    for bone in bones:
        if len(bone) >= 2:
            joint_parent[bone[1]] = bone[0]

    # Invert bindings to find which part owns which joint
    joint_to_part = {}
    for part_name, jname in bindings.items():
        joint_to_part[jname] = part_name

    # Determine which joints to process
    if joint_name:
        target_joints = {joint_name} if joint_name in joint_to_part or joint_name in bindings.values() else set()
    else:
        target_joints = set(bindings.values())

    expressions = []
    for jname in target_joints:
        part_name = joint_to_part.get(jname)
        if not part_name:
            continue

        # Get the parent layer name for follow-through expressions
        parent_joint = joint_parent.get(jname)
        parent_layer = joint_to_part.get(parent_joint, part_name) if parent_joint else part_name

        # Build template parameters
        tmpl_params = dict(template_info["defaults"])
        tmpl_params["joint_name"] = jname
        tmpl_params["parent_layer"] = parent_layer

        # Scale amplitude based on hierarchy depth (extremities move more)
        depth = 0
        walk_joint = jname
        while walk_joint in joint_parent:
            walk_joint = joint_parent[walk_joint]
            depth += 1

        # Extremities (deeper in hierarchy) get slightly larger amplitude
        if "amp" in tmpl_params:
            tmpl_params["amp"] = tmpl_params["amp"] + (depth * 2)
        if "delay" in tmpl_params:
            tmpl_params["delay"] = round(tmpl_params["delay"] + (depth * 0.05), 3)

        # Format the expression template
        expr = template_info["expression"].format(**tmpl_params)

        expressions.append({
            "layer_name": part_name,
            "property_name": template_info["property"],
            "expression": expr,
        })

    return expressions


def register(mcp):
    """Register the adobe_ae_expression_gen tool."""

    @mcp.tool(
        name="adobe_ae_expression_gen",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ae_expression_gen(params: AeExpressionGenInput) -> str:
        """Generate and apply AE expressions for procedural bone-driven animation.

        Creates After Effects expressions that add organic motion to character
        layers based on the rig's joint/bone structure:
        - rotation: Wiggle-based oscillating rotation
        - position: Follow-through with configurable delay
        - wiggle: Organic random movement
        - loopOut: Seamless keyframe cycling

        Expressions are automatically scaled based on the joint's depth in the
        skeletal hierarchy (extremities get more movement).
        """
        # Validate expression type
        valid_types = list(_EXPRESSION_TEMPLATES.keys())
        if params.expression_type not in valid_types:
            return json.dumps({
                "error": f"Invalid expression_type '{params.expression_type}'. "
                         f"Must be one of: {', '.join(valid_types)}"
            })

        # Load the rig
        rig = _load_rig(params.character_name)

        if not rig.get("bindings"):
            return json.dumps({
                "error": f"No bindings found for character '{params.character_name}'. "
                         "Use adobe_ai_bind tool to bind body parts to joints first."
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

        # Generate expression configs from the rig data
        layer_expressions = _generate_expressions_for_rig(
            rig,
            params.expression_type,
            params.joint_name,
        )

        if not layer_expressions:
            target = f"joint '{params.joint_name}'" if params.joint_name else "any joints"
            return json.dumps({
                "error": f"No expressions could be generated for {target}. "
                         "Check that joints are bound to body parts in the rig."
            })

        # Build and execute the JSX
        jsx = _build_expression_jsx(comp_name, layer_expressions)
        result = await _async_run_jsx("aftereffects", jsx)

        if not result["success"]:
            return f"Error: {result['stderr']}"

        return result["stdout"]
