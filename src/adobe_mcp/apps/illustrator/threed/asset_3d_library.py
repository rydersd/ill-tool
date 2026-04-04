"""Paired 2D+3D asset storage — save, load, and search assets.

Maintains a JSON index of assets with both 2D and 3D file references,
rig paths, tags, and metadata. Assets are stored in a persistent index
file for cross-session retrieval.

Pure Python — no JSX or Adobe required.
"""

import json
import os
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiAsset3dLibraryInput(BaseModel):
    """Manage paired 2D+3D asset library."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: save_asset, load_asset, list_assets, status",
    )
    name: Optional[str] = Field(
        default=None,
        description="Asset name (required for save/load)",
    )
    asset_type: Optional[str] = Field(
        default=None,
        description="Asset type: character, prop, environment, effect",
    )
    paths_2d: Optional[list[str]] = Field(
        default=None,
        description="List of 2D file paths (AI, SVG, PNG, etc.)",
    )
    paths_3d: Optional[list[str]] = Field(
        default=None,
        description="List of 3D file paths (OBJ, FBX, USDZ, etc.)",
    )
    rig_path: Optional[str] = Field(
        default=None,
        description="Path to rig definition file",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="Searchable tags for the asset",
    )
    query: Optional[str] = Field(
        default=None,
        description="Search query for list/search (matches name and tags)",
    )
    index_path: Optional[str] = Field(
        default=None,
        description="Override path for the index JSON file",
    )


# ---------------------------------------------------------------------------
# Default index path
# ---------------------------------------------------------------------------

DEFAULT_INDEX_PATH = os.path.expanduser(
    "~/.claude/memory/illustration/assets/index.json"
)

VALID_ASSET_TYPES = {"character", "prop", "environment", "effect", "vehicle", "creature"}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def _load_index(index_path: str) -> dict:
    """Load the asset index from disk, creating an empty one if missing.

    Returns:
        dict mapping asset names to their metadata.
    """
    if os.path.isfile(index_path):
        with open(index_path, "r") as f:
            return json.load(f)
    return {}


def _save_index(index: dict, index_path: str) -> None:
    """Write the asset index to disk, creating directories as needed."""
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def save_asset_metadata(
    name: str,
    asset_type: str,
    paths_2d: Optional[list[str]] = None,
    paths_3d: Optional[list[str]] = None,
    rig_path: Optional[str] = None,
    tags: Optional[list[str]] = None,
    index_path: Optional[str] = None,
) -> dict:
    """Save asset metadata to the JSON index.

    Creates or updates an asset entry with 2D/3D paths, rig reference,
    and tags. Existing entries with the same name are overwritten.

    Args:
        name: unique asset identifier.
        asset_type: one of VALID_ASSET_TYPES.
        paths_2d: list of 2D file paths.
        paths_3d: list of 3D file paths.
        rig_path: optional rig definition path.
        tags: searchable tags.
        index_path: override for index file location.

    Returns:
        dict confirming the save with asset metadata.
    """
    if not name or not name.strip():
        return {"error": "Asset name is required"}

    idx_path = index_path or DEFAULT_INDEX_PATH
    index = _load_index(idx_path)

    entry = {
        "name": name.strip(),
        "asset_type": asset_type or "prop",
        "paths_2d": paths_2d or [],
        "paths_3d": paths_3d or [],
        "rig_path": rig_path,
        "tags": [t.lower() for t in (tags or [])],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Preserve original creation date if updating
    existing = index.get(name.strip())
    if existing and "created" in existing:
        entry["created"] = existing["created"]

    index[name.strip()] = entry
    _save_index(index, idx_path)

    return {
        "saved": name.strip(),
        "asset_type": entry["asset_type"],
        "paths_2d_count": len(entry["paths_2d"]),
        "paths_3d_count": len(entry["paths_3d"]),
        "has_rig": bool(rig_path),
        "tag_count": len(entry["tags"]),
        "index_path": idx_path,
    }


def load_asset_metadata(
    name: str,
    index_path: Optional[str] = None,
) -> dict:
    """Load asset metadata by name.

    Args:
        name: asset name to look up.
        index_path: override for index file location.

    Returns:
        dict with asset metadata or error.
    """
    if not name or not name.strip():
        return {"error": "Asset name is required"}

    idx_path = index_path or DEFAULT_INDEX_PATH
    index = _load_index(idx_path)

    entry = index.get(name.strip())
    if entry is None:
        return {
            "error": f"Asset '{name}' not found",
            "available": sorted(index.keys())[:20],
        }

    return entry


def search_assets(
    query: str,
    asset_type: Optional[str] = None,
    index_path: Optional[str] = None,
) -> dict:
    """Search assets by name or tag, optionally filtered by type.

    Performs case-insensitive substring matching against asset names
    and tags. If asset_type is provided, results are filtered.

    Args:
        query: search string to match against names and tags.
        asset_type: optional filter by asset type.
        index_path: override for index file location.

    Returns:
        dict with matching assets and result count.
    """
    idx_path = index_path or DEFAULT_INDEX_PATH
    index = _load_index(idx_path)

    query_lower = query.lower().strip() if query else ""
    matches = []

    for asset_name, entry in index.items():
        # Filter by type if specified
        if asset_type and entry.get("asset_type") != asset_type:
            continue

        # Match against name
        name_match = query_lower in asset_name.lower()

        # Match against tags
        tag_match = any(query_lower in tag for tag in entry.get("tags", []))

        if name_match or tag_match or not query_lower:
            matches.append({
                "name": entry.get("name", asset_name),
                "asset_type": entry.get("asset_type", "unknown"),
                "paths_2d_count": len(entry.get("paths_2d", [])),
                "paths_3d_count": len(entry.get("paths_3d", [])),
                "has_rig": bool(entry.get("rig_path")),
                "tags": entry.get("tags", []),
            })

    return {
        "query": query,
        "asset_type_filter": asset_type,
        "result_count": len(matches),
        "results": matches,
    }


def list_all_assets(index_path: Optional[str] = None) -> dict:
    """List all assets in the index.

    Args:
        index_path: override for index file location.

    Returns:
        dict with all assets summarized.
    """
    idx_path = index_path or DEFAULT_INDEX_PATH
    index = _load_index(idx_path)

    assets = []
    type_counts = {}

    for asset_name, entry in index.items():
        atype = entry.get("asset_type", "unknown")
        type_counts[atype] = type_counts.get(atype, 0) + 1
        assets.append({
            "name": entry.get("name", asset_name),
            "asset_type": atype,
            "has_2d": len(entry.get("paths_2d", [])) > 0,
            "has_3d": len(entry.get("paths_3d", [])) > 0,
            "has_rig": bool(entry.get("rig_path")),
        })

    return {
        "total": len(assets),
        "type_counts": type_counts,
        "assets": assets,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_asset_3d_library tool."""

    @mcp.tool(
        name="adobe_ai_asset_3d_library",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_asset_3d_library(params: AiAsset3dLibraryInput) -> str:
        """Manage paired 2D+3D asset library.

        Actions:
        - save_asset: store asset metadata with 2D/3D paths
        - load_asset: retrieve asset by name
        - list_assets: list or search all assets
        - status: show library configuration
        """
        action = params.action.lower().strip()
        idx_path = params.index_path or DEFAULT_INDEX_PATH

        if action == "status":
            index = _load_index(idx_path)
            return json.dumps({
                "action": "status",
                "tool": "asset_3d_library",
                "index_path": idx_path,
                "asset_count": len(index),
                "valid_types": sorted(VALID_ASSET_TYPES),
                "ready": True,
            }, indent=2)

        elif action == "save_asset":
            if not params.name:
                return json.dumps({"error": "save_asset requires a name"})
            result = save_asset_metadata(
                name=params.name,
                asset_type=params.asset_type or "prop",
                paths_2d=params.paths_2d,
                paths_3d=params.paths_3d,
                rig_path=params.rig_path,
                tags=params.tags,
                index_path=idx_path,
            )
            return json.dumps(result, indent=2)

        elif action == "load_asset":
            if not params.name:
                return json.dumps({"error": "load_asset requires a name"})
            result = load_asset_metadata(params.name, index_path=idx_path)
            return json.dumps(result, indent=2)

        elif action == "list_assets":
            if params.query:
                result = search_assets(
                    query=params.query,
                    asset_type=params.asset_type,
                    index_path=idx_path,
                )
            else:
                result = list_all_assets(index_path=idx_path)
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["save_asset", "load_asset", "list_assets", "status"],
            })
