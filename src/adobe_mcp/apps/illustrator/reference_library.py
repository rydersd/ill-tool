"""Manage reference images per character/environment/prop.

Provides a persistent library of reference images organized by category
and searchable by tags. References are stored in a JSON file and can be
filtered by category, tags, or both.

Pure Python implementation.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiReferenceLibraryInput(BaseModel):
    """Manage reference images for illustration projects."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: add_reference, get_references, remove_reference",
    )
    category: Optional[str] = Field(
        default=None,
        description="Category: character, environment, prop, pose, expression",
    )
    name: Optional[str] = Field(
        default=None,
        description="Unique name for the reference",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="Path to the reference image file",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="Tags for searching/filtering references",
    )
    library_path: Optional[str] = Field(
        default=None,
        description="Override default library JSON path",
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"character", "environment", "prop", "pose", "expression"}

_DEFAULT_LIBRARY_PATH = os.path.expanduser(
    "~/.claude/memory/illustration/references.json"
)


# ---------------------------------------------------------------------------
# Internal storage
# ---------------------------------------------------------------------------


def _get_library_path(override: Optional[str] = None) -> str:
    """Return the library file path, using override if provided."""
    return override if override else _DEFAULT_LIBRARY_PATH


def _load_library(path: str) -> dict:
    """Load the reference library from disk.

    Returns a dict mapping reference names to their metadata.
    """
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {"references": {}}


def _save_library(path: str, library: dict) -> None:
    """Save the reference library to disk."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(library, f, indent=2)


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def add_reference(
    category: str,
    name: str,
    image_path: str,
    tags: Optional[list[str]] = None,
    library_path: Optional[str] = None,
) -> dict:
    """Add a reference image to the library.

    Args:
        category: one of character, environment, prop, pose, expression
        name: unique identifier for this reference
        image_path: path to the image file
        tags: optional list of searchable tags
        library_path: override default library storage path

    Returns:
        Confirmation dict with the added reference details.
    """
    if category not in VALID_CATEGORIES:
        return {
            "error": f"Invalid category: '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
        }
    if not name:
        return {"error": "Reference name is required"}
    if not image_path:
        return {"error": "Image path is required"}

    path = _get_library_path(library_path)
    library = _load_library(path)

    reference = {
        "name": name,
        "category": category,
        "image_path": image_path,
        "tags": tags or [],
    }

    library["references"][name] = reference
    _save_library(path, library)

    return {
        "added": name,
        "category": category,
        "image_path": image_path,
        "tags": tags or [],
        "total_references": len(library["references"]),
    }


def get_references(
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    library_path: Optional[str] = None,
) -> dict:
    """Search the reference library by category and/or tags.

    Both filters are applied together (AND logic). If neither is
    specified, all references are returned.

    Args:
        category: filter by category
        tags: filter by tags (any match)
        library_path: override default library storage path

    Returns:
        Dict with matching references and count.
    """
    path = _get_library_path(library_path)
    library = _load_library(path)

    results = []
    for ref in library.get("references", {}).values():
        # Category filter
        if category and ref.get("category") != category:
            continue
        # Tag filter (match any provided tag)
        if tags:
            ref_tags = set(ref.get("tags", []))
            search_tags = set(tags)
            if not ref_tags.intersection(search_tags):
                continue
        results.append(ref)

    return {
        "references": results,
        "count": len(results),
        "filters": {
            "category": category,
            "tags": tags,
        },
    }


def remove_reference(
    name: str,
    library_path: Optional[str] = None,
) -> dict:
    """Remove a reference from the library.

    Args:
        name: reference identifier to remove
        library_path: override default library storage path

    Returns:
        Confirmation dict or error if not found.
    """
    if not name:
        return {"error": "Reference name is required"}

    path = _get_library_path(library_path)
    library = _load_library(path)

    if name not in library.get("references", {}):
        return {"error": f"Reference '{name}' not found"}

    removed = library["references"].pop(name)
    _save_library(path, library)

    return {
        "removed": name,
        "category": removed.get("category"),
        "remaining": len(library["references"]),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_reference_library tool."""

    @mcp.tool(
        name="adobe_ai_reference_library",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_reference_library(params: AiReferenceLibraryInput) -> str:
        """Manage reference images per character/environment/prop.

        Actions:
        - add_reference: add an image to the library with category and tags
        - get_references: search by category and/or tags
        - remove_reference: remove a reference by name
        """
        action = params.action.lower().strip()

        if action == "add_reference":
            if not params.category or not params.name or not params.image_path:
                return json.dumps({"error": "add_reference requires category, name, and image_path"})
            result = add_reference(
                category=params.category,
                name=params.name,
                image_path=params.image_path,
                tags=params.tags,
                library_path=params.library_path,
            )
            return json.dumps(result)

        elif action == "get_references":
            result = get_references(
                category=params.category,
                tags=params.tags,
                library_path=params.library_path,
            )
            return json.dumps(result)

        elif action == "remove_reference":
            if not params.name:
                return json.dumps({"error": "remove_reference requires name"})
            result = remove_reference(
                name=params.name,
                library_path=params.library_path,
            )
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
