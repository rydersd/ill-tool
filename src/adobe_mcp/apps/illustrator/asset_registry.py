"""Track assets (characters, props, backgrounds) used per storyboard panel.

Data lives in the rig file under `assets` as a list of dicts:
  {"type": "character", "name": "gir", "panels": [1, 2, 3, 5]}

Provides CRUD plus two filtered views (by_panel, by_asset) and an
aggregated summary.
"""

import json

from adobe_mcp.apps.illustrator.models import AiAssetRegistryInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


VALID_ASSET_TYPES = {"character", "prop", "background", "effect"}


def _ensure_assets(rig: dict) -> dict:
    """Ensure the rig has an assets list."""
    if "assets" not in rig:
        rig["assets"] = []
    return rig


def _find_asset(assets: list[dict], asset_type: str, asset_name: str) -> int | None:
    """Find asset index by type and name, or None."""
    for i, a in enumerate(assets):
        if a.get("type") == asset_type and a.get("name") == asset_name:
            return i
    return None


def _get_assets_for_panel(assets: list[dict], panel_number: int) -> list[dict]:
    """Return all assets that appear in a given panel."""
    return [
        {"type": a["type"], "name": a["name"]}
        for a in assets
        if panel_number in a.get("panels", [])
    ]


def _get_panels_for_asset(assets: list[dict], asset_name: str) -> dict | None:
    """Return the asset record for a given name, or None."""
    for a in assets:
        if a.get("name") == asset_name:
            return a
    return None


def _build_summary(assets: list[dict]) -> dict:
    """Build an aggregated summary of all tracked assets."""
    by_type: dict[str, list[str]] = {}
    panel_usage: dict[int, list[str]] = {}

    for asset in assets:
        atype = asset.get("type", "unknown")
        aname = asset.get("name", "unnamed")

        if atype not in by_type:
            by_type[atype] = []
        by_type[atype].append(aname)

        for pnum in asset.get("panels", []):
            if pnum not in panel_usage:
                panel_usage[pnum] = []
            panel_usage[pnum].append(aname)

    # Sort panel usage by panel number
    sorted_panel_usage = {
        k: v for k, v in sorted(panel_usage.items(), key=lambda x: x[0])
    }

    return {
        "total_assets": len(assets),
        "by_type": {k: sorted(v) for k, v in sorted(by_type.items())},
        "type_counts": {k: len(v) for k, v in sorted(by_type.items())},
        "panel_usage": sorted_panel_usage,
        "panels_used": sorted(panel_usage.keys()),
    }


def register(mcp):
    """Register the adobe_ai_asset_registry tool."""

    @mcp.tool(
        name="adobe_ai_asset_registry",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_asset_registry(params: AiAssetRegistryInput) -> str:
        """Track characters, props, and backgrounds used per storyboard panel.

        Actions:
        - register: add an asset to a panel
        - remove: remove an asset from a panel (or entirely)
        - list: list all tracked assets
        - list_by_panel: show assets used in a specific panel
        - list_by_asset: show which panels use a specific asset
        - summary: aggregated overview of all assets and panel usage
        """
        character_name = "storyboard"
        rig = _load_rig(character_name)
        rig = _ensure_assets(rig)

        action = params.action.lower().strip()

        # ── register ─────────────────────────────────────────────
        if action == "register":
            if not params.asset_type or not params.asset_name:
                return json.dumps({
                    "error": "asset_type and asset_name are required for register.",
                })

            asset_type = params.asset_type.lower().strip()
            if asset_type not in VALID_ASSET_TYPES:
                return json.dumps({
                    "error": f"Invalid asset_type: {asset_type}",
                    "valid_types": sorted(VALID_ASSET_TYPES),
                })

            if params.panel_number is None:
                return json.dumps({
                    "error": "panel_number is required for register.",
                })

            idx = _find_asset(rig["assets"], asset_type, params.asset_name)
            if idx is not None:
                # Asset exists -- add panel if not already listed
                if params.panel_number not in rig["assets"][idx]["panels"]:
                    rig["assets"][idx]["panels"].append(params.panel_number)
                    rig["assets"][idx]["panels"].sort()
            else:
                # Create new asset entry
                rig["assets"].append({
                    "type": asset_type,
                    "name": params.asset_name,
                    "panels": [params.panel_number],
                })

            _save_rig(character_name, rig)

            return json.dumps({
                "action": "register",
                "asset_type": asset_type,
                "asset_name": params.asset_name,
                "panel": params.panel_number,
                "all_panels": rig["assets"][
                    _find_asset(rig["assets"], asset_type, params.asset_name)
                ]["panels"],
            }, indent=2)

        # ── remove ───────────────────────────────────────────────
        elif action == "remove":
            if not params.asset_name:
                return json.dumps({
                    "error": "asset_name is required for remove.",
                })

            # Find the asset by name (type-agnostic search if type not given)
            removed = False
            for i, a in enumerate(rig["assets"]):
                name_match = a.get("name") == params.asset_name
                type_match = (
                    params.asset_type is None
                    or a.get("type") == params.asset_type.lower().strip()
                )
                if name_match and type_match:
                    if params.panel_number is not None:
                        # Remove just this panel from the asset
                        panels = a.get("panels", [])
                        if params.panel_number in panels:
                            panels.remove(params.panel_number)
                            removed = True
                        # If no panels left, remove the asset entirely
                        if not panels:
                            rig["assets"].pop(i)
                    else:
                        # Remove the entire asset
                        rig["assets"].pop(i)
                        removed = True
                    break

            if not removed:
                return json.dumps({
                    "error": f"Asset '{params.asset_name}' not found.",
                })

            _save_rig(character_name, rig)
            return json.dumps({
                "action": "remove",
                "asset_name": params.asset_name,
                "panel": params.panel_number,
                "total_assets": len(rig["assets"]),
            }, indent=2)

        # ── list ─────────────────────────────────────────────────
        elif action == "list":
            return json.dumps({
                "action": "list",
                "assets": rig["assets"],
                "total": len(rig["assets"]),
            }, indent=2)

        # ── list_by_panel ────────────────────────────────────────
        elif action == "list_by_panel":
            if params.panel_number is None:
                return json.dumps({
                    "error": "panel_number is required for list_by_panel.",
                })

            panel_assets = _get_assets_for_panel(
                rig["assets"], params.panel_number,
            )
            return json.dumps({
                "action": "list_by_panel",
                "panel": params.panel_number,
                "assets": panel_assets,
                "count": len(panel_assets),
            }, indent=2)

        # ── list_by_asset ────────────────────────────────────────
        elif action == "list_by_asset":
            if not params.asset_name:
                return json.dumps({
                    "error": "asset_name is required for list_by_asset.",
                })

            asset = _get_panels_for_asset(rig["assets"], params.asset_name)
            if asset is None:
                return json.dumps({
                    "error": f"Asset '{params.asset_name}' not found.",
                })

            return json.dumps({
                "action": "list_by_asset",
                "asset": asset,
            }, indent=2)

        # ── summary ──────────────────────────────────────────────
        elif action == "summary":
            summary = _build_summary(rig["assets"])
            return json.dumps({
                "action": "summary",
                **summary,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": [
                    "register", "remove", "list",
                    "list_by_panel", "list_by_asset", "summary",
                ],
            })
