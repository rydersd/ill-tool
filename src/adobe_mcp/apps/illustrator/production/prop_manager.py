"""Manage props that characters interact with in storyboard panels.

Props are stored in the rig file under `props`.  Each prop tracks which
panels it appears in, its position, and optional joint attachment data
so the prop follows character movement automatically.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPropManagerInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _ensure_props(rig: dict) -> dict:
    """Ensure the rig has a props structure."""
    if "props" not in rig:
        rig["props"] = {}
    return rig


def register(mcp):
    """Register the adobe_ai_prop_manager tool."""

    @mcp.tool(
        name="adobe_ai_prop_manager",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_prop_manager(params: AiPropManagerInput) -> str:
        """Create, place, remove, list, or attach props to character joints.

        Props are reusable assets (sword, cup, hat) that can be placed in
        specific panels and optionally bound to a character joint so they
        follow pose changes.
        """
        character_name = params.character_name or "character"
        rig = _load_rig(character_name)
        rig = _ensure_props(rig)

        action = params.action.lower().strip()

        # ── create ──────────────────────────────────────────────────
        if action == "create":
            prop_name = params.prop_name
            if prop_name in rig["props"]:
                return json.dumps({
                    "error": f"Prop '{prop_name}' already exists.",
                    "hint": "Use a different name or remove the existing prop first.",
                })

            prop_data = {
                "panels": [],
                "prop_path": params.prop_path or "",
                "attached_to": None,
            }

            rig["props"][prop_name] = prop_data
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "create",
                "prop_name": prop_name,
                "prop_path": prop_data["prop_path"],
                "total_props": len(rig["props"]),
            }, indent=2)

        # ── place ───────────────────────────────────────────────────
        elif action == "place":
            prop_name = params.prop_name
            if prop_name not in rig["props"]:
                return json.dumps({
                    "error": f"Prop '{prop_name}' not found. Create it first.",
                    "available_props": list(rig["props"].keys()),
                })

            if params.panel_number is None:
                return json.dumps({
                    "error": "panel_number is required for place action.",
                })

            panel_num = params.panel_number
            prop = rig["props"][prop_name]
            x = params.x if params.x is not None else 0
            y = params.y if params.y is not None else 0

            # Build placement entry
            placement = {
                "panel": panel_num,
                "x": x,
                "y": y,
            }

            # Remove any existing placement for this panel, then add
            prop["panels"] = [
                p for p in prop["panels"]
                if (p if isinstance(p, int) else p.get("panel")) != panel_num
            ]
            prop["panels"].append(placement)
            # Sort by panel number for clean ordering
            prop["panels"].sort(
                key=lambda p: p if isinstance(p, int) else p.get("panel", 0)
            )

            _save_rig(character_name, rig)

            # Draw prop indicator in Illustrator
            escaped_name = escape_jsx_string(prop_name)
            jsx = f"""
(function() {{
    var doc = app.activeDocument;

    // Find or create Props layer
    var propsLayer;
    try {{
        propsLayer = doc.layers.getByName("Props");
    }} catch(e) {{
        propsLayer = doc.layers.add();
        propsLayer.name = "Props";
    }}

    // Draw a small marker for the prop
    var marker = propsLayer.pathItems.rectangle(
        {y}, {x}, 20, 20
    );
    marker.name = "prop_{escaped_name}_panel_{panel_num}";
    marker.filled = true;
    var markerColor = new RGBColor();
    markerColor.red = 180; markerColor.green = 100; markerColor.blue = 255;
    marker.fillColor = markerColor;
    marker.stroked = true;
    marker.strokeWidth = 1;

    // Label
    var label = propsLayer.textFrames.add();
    label.contents = "{escaped_name}";
    label.position = [{x}, {y} + 14];
    label.textRange.characterAttributes.size = 8;

    return JSON.stringify({{
        prop: "{escaped_name}",
        panel: {panel_num},
        x: {x},
        y: {y}
    }});
}})();
"""
            result = await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "place",
                "prop_name": prop_name,
                "panel_number": panel_num,
                "position": {"x": x, "y": y},
                "jsx_success": result.get("success", False),
            }, indent=2)

        # ── remove ──────────────────────────────────────────────────
        elif action == "remove":
            prop_name = params.prop_name
            if prop_name not in rig["props"]:
                return json.dumps({
                    "error": f"Prop '{prop_name}' not found.",
                    "available_props": list(rig["props"].keys()),
                })

            if params.panel_number is not None:
                # Remove from a specific panel only
                panel_num = params.panel_number
                prop = rig["props"][prop_name]
                before_count = len(prop["panels"])
                prop["panels"] = [
                    p for p in prop["panels"]
                    if (p if isinstance(p, int) else p.get("panel")) != panel_num
                ]
                removed = before_count - len(prop["panels"])

                _save_rig(character_name, rig)
                return json.dumps({
                    "action": "remove",
                    "prop_name": prop_name,
                    "panel_number": panel_num,
                    "removed": removed > 0,
                    "remaining_panels": len(prop["panels"]),
                }, indent=2)
            else:
                # Remove the prop entirely
                del rig["props"][prop_name]
                _save_rig(character_name, rig)
                return json.dumps({
                    "action": "remove",
                    "prop_name": prop_name,
                    "removed_entirely": True,
                    "total_props": len(rig["props"]),
                }, indent=2)

        # ── list ────────────────────────────────────────────────────
        elif action == "list":
            props_list = []
            for name, data in rig["props"].items():
                panel_nums = []
                for p in data.get("panels", []):
                    if isinstance(p, int):
                        panel_nums.append(p)
                    elif isinstance(p, dict):
                        panel_nums.append(p.get("panel", 0))
                props_list.append({
                    "name": name,
                    "panels": panel_nums,
                    "prop_path": data.get("prop_path", ""),
                    "attached_to": data.get("attached_to"),
                })

            return json.dumps({
                "action": "list",
                "props": props_list,
                "total_props": len(props_list),
            }, indent=2)

        # ── attach_to_joint ─────────────────────────────────────────
        elif action == "attach_to_joint":
            prop_name = params.prop_name
            if prop_name not in rig["props"]:
                return json.dumps({
                    "error": f"Prop '{prop_name}' not found.",
                    "available_props": list(rig["props"].keys()),
                })

            if not params.joint_name:
                return json.dumps({
                    "error": "joint_name is required for attach_to_joint action.",
                })

            attachment = {
                "character": character_name,
                "joint": params.joint_name,
            }
            rig["props"][prop_name]["attached_to"] = attachment
            _save_rig(character_name, rig)

            return json.dumps({
                "action": "attach_to_joint",
                "prop_name": prop_name,
                "attached_to": attachment,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "place", "remove", "list", "attach_to_joint"],
            })
