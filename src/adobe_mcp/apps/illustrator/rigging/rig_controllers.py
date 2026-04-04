"""Create visual control handles at skeleton joint positions for intuitive posing.

Controllers are interactive shapes (circles, diamonds, squares) placed on a
dedicated "Controllers" layer. When the user drags a controller in Illustrator,
the `update` action reads its new position and syncs the joint data in the rig,
enabling pose-by-dragging workflows.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiRigControllersInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _controller_name(joint_name: str) -> str:
    """Return the AI item name for a controller handle."""
    return f"ctrl_{joint_name}"


def _build_controller_list(joints: dict, style: str, size: float) -> list[dict]:
    """Build a list of controller descriptors from joint data.

    Each descriptor has: name, joint_name, x, y, style, size.
    """
    controllers = []
    for joint_name, pos in joints.items():
        controllers.append({
            "name": _controller_name(joint_name),
            "joint_name": joint_name,
            "x": pos["x"],
            "y": pos["y"],
            "style": style,
            "size": size,
        })
    return controllers


def _map_controllers_to_joints(controller_positions: dict, rig: dict) -> dict:
    """Map controller position updates back to joint positions in the rig.

    Args:
        controller_positions: dict of {ctrl_name: {"x": ..., "y": ...}}
        rig: the current rig dict

    Returns:
        dict of updated joint names to new positions.
    """
    updated = {}
    joints = rig.get("joints", {})
    for ctrl_name, pos in controller_positions.items():
        # Strip the "ctrl_" prefix to get the joint name
        if ctrl_name.startswith("ctrl_"):
            joint_name = ctrl_name[5:]
        else:
            joint_name = ctrl_name

        if joint_name in joints:
            joints[joint_name] = {"x": pos["x"], "y": pos["y"]}
            updated[joint_name] = {"x": pos["x"], "y": pos["y"]}

    rig["joints"] = joints
    return updated


# ---------------------------------------------------------------------------
# JSX builders
# ---------------------------------------------------------------------------


def _jsx_shape_code(style: str, size: float, x: float, y: float,
                    r: int, g: int, b: int) -> str:
    """Return JSX code fragment that creates a controller shape.

    The shape is created relative to the current layer.
    Caller wraps this in the layer/document context.
    """
    half = size / 2.0

    if style == "diamond":
        # Rotated square (diamond) — 4 anchor points
        return f"""
        var pts = [
            [{x}, {y - half}],
            [{x + half}, {y}],
            [{x}, {y + half}],
            [{x - half}, {y}]
        ];
        var shape = ctrlLayer.pathItems.add();
        shape.setEntirePath(pts);
        shape.closed = true;
        """
    elif style == "square":
        return f"""
        var shape = ctrlLayer.pathItems.rectangle(
            {y + half}, {x - half}, {size}, {size}
        );
        """
    else:
        # Default: circle (ellipse)
        return f"""
        var shape = ctrlLayer.pathItems.ellipse(
            {y + half}, {x - half}, {size}, {size}
        );
        """


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_rig_controllers tool."""

    @mcp.tool(
        name="adobe_ai_rig_controllers",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_rig_controllers(params: AiRigControllersInput) -> str:
        """Create, update, clear, or list visual control handles on skeleton joints.

        Controllers are interactive shapes placed at each joint position on a
        dedicated 'Controllers' layer. Drag them in Illustrator and run 'update'
        to sync positions back to the rig.
        """
        rig = _load_rig(params.character_name)
        action = params.action.lower().strip()

        # ── create ────────────────────────────────────────────────────
        if action == "create":
            joints = rig.get("joints", {})
            if not joints:
                return json.dumps({
                    "error": "No joints in rig. Build a skeleton first with "
                             "adobe_ai_skeleton_build.",
                })

            controllers = _build_controller_list(
                joints, params.controller_style, params.controller_size
            )

            # Build JSX to create/clear the Controllers layer and add shapes
            ctrl_items_js = json.dumps(controllers)
            r, g, b = params.color_r, params.color_g, params.color_b
            show_labels = "true" if params.show_labels else "false"

            jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Remove existing Controllers layer if present
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Controllers") {{
            doc.layers[i].remove();
            break;
        }}
    }}

    // Create Controllers layer
    var ctrlLayer = doc.layers.add();
    ctrlLayer.name = "Controllers";

    // Position it: above Skeleton, below Drawing
    // Try to place after Drawing layer if it exists
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Drawing") {{
            ctrlLayer.move(doc.layers[i], ElementPlacement.PLACEAFTER);
            break;
        }}
    }}

    var items = {ctrl_items_js};
    var created = [];
    var clr = new RGBColor();
    clr.red = {r}; clr.green = {g}; clr.blue = {b};

    for (var c = 0; c < items.length; c++) {{
        var info = items[c];
        var x = info.x;
        var y = info.y;
        var sz = info.size;
        var half = sz / 2;
        var style = info.style;
        var shape;

        if (style === "diamond") {{
            shape = ctrlLayer.pathItems.add();
            shape.setEntirePath([
                [x, y - half], [x + half, y],
                [x, y + half], [x - half, y]
            ]);
            shape.closed = true;
        }} else if (style === "square") {{
            shape = ctrlLayer.pathItems.rectangle(y + half, x - half, sz, sz);
        }} else {{
            shape = ctrlLayer.pathItems.ellipse(y + half, x - half, sz, sz);
        }}

        shape.name = info.name;
        shape.filled = true;
        shape.fillColor = clr;
        shape.stroked = true;
        shape.strokeWidth = 1;
        var strokeClr = new RGBColor();
        strokeClr.red = Math.min(255, {r} + 40);
        strokeClr.green = Math.min(255, {g} + 40);
        strokeClr.blue = Math.min(255, {b} + 40);
        shape.strokeColor = strokeClr;

        // Optional label
        if ({show_labels}) {{
            var label = ctrlLayer.textFrames.add();
            label.contents = info.joint_name;
            label.name = info.name + "_label";
            label.position = [x + half + 4, y + 4];
            label.textRange.characterAttributes.size = 7;
            var textClr = new RGBColor();
            textClr.red = 80; textClr.green = 80; textClr.blue = 80;
            label.textRange.characterAttributes.fillColor = textClr;
        }}

        created.push(info.name);
    }}

    return JSON.stringify({{
        created: created,
        count: created.length
    }});
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            # Store controller names in rig
            rig["controllers"] = [c["name"] for c in controllers]
            _save_rig(params.character_name, rig)

            try:
                jsx_data = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                jsx_data = {"count": len(controllers)}

            return json.dumps({
                "action": "create",
                "controllers": controllers,
                "total": len(controllers),
                "style": params.controller_style,
                "size": params.controller_size,
            }, indent=2)

        # ── update ────────────────────────────────────────────────────
        elif action == "update":
            ctrl_names = rig.get("controllers", [])
            if not ctrl_names:
                return json.dumps({
                    "error": "No controllers found. Run create first.",
                })

            # Read current positions of controller shapes from AI
            names_js = json.dumps(ctrl_names)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var names = {names_js};
    var positions = {{}};
    var errors = [];

    for (var i = 0; i < names.length; i++) {{
        var n = names[i];
        var found = false;
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{
                var item = doc.layers[l].pathItems.getByName(n);
                if (item) {{
                    var b = item.geometricBounds;
                    positions[n] = {{
                        x: (b[0] + b[2]) / 2,
                        y: (b[1] + b[3]) / 2
                    }};
                    found = true;
                    break;
                }}
            }} catch(e) {{}}
        }}
        if (!found) errors.push(n);
    }}

    return JSON.stringify({{positions: positions, errors: errors}});
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            try:
                jsx_data = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"error": "Failed to parse controller positions"})

            positions = jsx_data.get("positions", {})
            updated = _map_controllers_to_joints(positions, rig)
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "update",
                "updated_joints": updated,
                "errors": jsx_data.get("errors", []),
            }, indent=2)

        # ── clear ─────────────────────────────────────────────────────
        elif action == "clear":
            jsx = """(function() {
    var doc = app.activeDocument;
    var removed = false;
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === "Controllers") {
            doc.layers[i].remove();
            removed = true;
            break;
        }
    }
    return JSON.stringify({removed: removed});
})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            rig.pop("controllers", None)
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "clear",
                "removed": True,
            })

        # ── list ──────────────────────────────────────────────────────
        elif action == "list":
            ctrl_names = rig.get("controllers", [])
            joints = rig.get("joints", {})

            controller_details = []
            for name in ctrl_names:
                joint_name = name[5:] if name.startswith("ctrl_") else name
                pos = joints.get(joint_name, {})
                controller_details.append({
                    "name": name,
                    "joint_name": joint_name,
                    "x": pos.get("x"),
                    "y": pos.get("y"),
                })

            return json.dumps({
                "action": "list",
                "controllers": controller_details,
                "total": len(controller_details),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "update", "clear", "list"],
            })
