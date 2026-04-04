"""Shape Recipe Library — save, recall, and place proven path shapes across sessions.

Captures pathItem geometry from Illustrator, normalizes to 0-1 coordinate space,
and stores in a persistent JSON library for reuse. Recipes include full bezier
handle data so placed shapes are exact reproductions, not approximations.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class AiShapeRecipeInput(BaseModel):
    """Save, recall, and place proven shape recipes from the library."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        ...,
        description=(
            "Action: save (capture a pathItem), recall (find recipes by tag), "
            "place (place a recipe in AI), list (show all recipes)"
        ),
    )
    name: Optional[str] = Field(
        default=None,
        description="pathItem name to capture (save) or recipe name to place (place/recall)",
    )
    tags: Optional[str] = Field(
        default=None,
        description="Comma-separated tags for save or search (e.g. 'ear,left,gir')",
    )
    target_x: Optional[float] = Field(
        default=None, description="X position for place action"
    )
    target_y: Optional[float] = Field(
        default=None, description="Y position for place action"
    )
    target_width: Optional[float] = Field(
        default=None,
        description="Target width for place action (scales the recipe)",
    )
    target_height: Optional[float] = Field(
        default=None,
        description="Target height for place action (scales the recipe)",
    )
    library_path: Optional[str] = Field(
        default=None,
        description="Custom path for recipe library JSON file",
    )


# ---------------------------------------------------------------------------
# Default library location
# ---------------------------------------------------------------------------

_DEFAULT_LIBRARY = os.path.expanduser(
    "~/.claude/memory/illustration/shape-recipes.json"
)


# ---------------------------------------------------------------------------
# Library I/O helpers
# ---------------------------------------------------------------------------

def _library_path(params: AiShapeRecipeInput) -> str:
    """Resolve the library file path, preferring the user override."""
    return params.library_path or _DEFAULT_LIBRARY


def _load_library(path: str) -> list[dict]:
    """Load the recipe library from disk, returning an empty list if missing."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Accept both bare list and {"recipes": [...]} wrapper
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "recipes" in data:
        return data["recipes"]
    return []


def _save_library(path: str, recipes: list[dict]) -> None:
    """Persist the recipe library to disk, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(recipes, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# JSX to extract pathItem data (anchors + handles + bounding box)
# ---------------------------------------------------------------------------

_EXTRACT_JSX_TEMPLATE = """
(function() {{
    var doc = app.activeDocument;
    var item = null;
    var targetName = "{escaped_name}";

    // Search all layers for the named pathItem
    for (var l = 0; l < doc.layers.length; l++) {{
        for (var s = 0; s < doc.layers[l].pathItems.length; s++) {{
            if (doc.layers[l].pathItems[s].name === targetName) {{
                item = doc.layers[l].pathItems[s];
                break;
            }}
        }}
        if (item !== null) break;
    }}

    if (item === null) {{
        '\\u007b"error": "pathItem not found: ' + targetName + '"\\u007d';
    }} else {{
        var gb = item.geometricBounds; // [left, top, right, bottom]
        var bboxLeft = gb[0];
        var bboxTop = gb[1];
        var bboxRight = gb[2];
        var bboxBottom = gb[3];
        var bboxW = bboxRight - bboxLeft;
        var bboxH = bboxTop - bboxBottom; // AI Y goes up, top > bottom

        var pts = [];
        for (var i = 0; i < item.pathPoints.length; i++) {{
            var p = item.pathPoints[i];
            pts.push({{
                anchor: [p.anchor[0], p.anchor[1]],
                left: [p.leftDirection[0], p.leftDirection[1]],
                right: [p.rightDirection[0], p.rightDirection[1]]
            }});
        }}

        JSON.stringify({{
            points: pts,
            closed: item.closed,
            bbox_left: bboxLeft,
            bbox_top: bboxTop,
            bbox_width: bboxW,
            bbox_height: bboxH
        }});
    }}
}})();
"""


# ---------------------------------------------------------------------------
# JSX to place a recipe as a new pathItem
# ---------------------------------------------------------------------------

_PLACE_JSX_TEMPLATE = """
(function() {{
    var doc = app.activeDocument;
    var path = doc.pathItems.add();
    var anchors = {anchors_json};
    path.setEntirePath(anchors);
    path.closed = {closed_str};

    // Now set bezier handles per-point
    var lefts = {lefts_json};
    var rights = {rights_json};
    for (var i = 0; i < path.pathPoints.length; i++) {{
        path.pathPoints[i].leftDirection = lefts[i];
        path.pathPoints[i].rightDirection = rights[i];
    }}

    path.name = "{recipe_name}";
    path.filled = false;
    path.stroked = true;
    path.strokeWidth = 1;

    JSON.stringify({{
        placed: "{recipe_name}",
        point_count: path.pathPoints.length,
        bounds: [
            Math.round(path.geometricBounds[0] * 100) / 100,
            Math.round(path.geometricBounds[1] * 100) / 100,
            Math.round(path.geometricBounds[2] * 100) / 100,
            Math.round(path.geometricBounds[3] * 100) / 100
        ]
    }});
}})();
"""


# ---------------------------------------------------------------------------
# Coordinate normalization / denormalization
# ---------------------------------------------------------------------------

def _normalize_point(x: float, y: float, bbox_left: float, bbox_top: float,
                     bbox_w: float, bbox_h: float) -> list[float]:
    """Convert absolute AI coordinates to 0-1 normalized space.

    AI coordinate system: X goes right, Y goes up.
    bbox_top is the highest Y value, bbox_top - bbox_h is the lowest.
    We normalize so (0,0) = top-left of bounding box and (1,1) = bottom-right.
    """
    if bbox_w == 0:
        norm_x = 0.0
    else:
        norm_x = (x - bbox_left) / bbox_w

    if bbox_h == 0:
        norm_y = 0.0
    else:
        # Y is inverted: top of bbox = 0, bottom = 1
        norm_y = (bbox_top - y) / bbox_h

    return [round(norm_x, 6), round(norm_y, 6)]


def _denormalize_point(norm_x: float, norm_y: float,
                       target_x: float, target_y: float,
                       target_w: float, target_h: float) -> list[float]:
    """Convert 0-1 normalized coordinates back to absolute AI coordinates.

    target_x, target_y is the top-left corner of the placement area.
    """
    abs_x = target_x + norm_x * target_w
    # Y is inverted back: norm 0 = target_y (top), norm 1 = target_y - target_h (bottom)
    abs_y = target_y - norm_y * target_h
    return [round(abs_x, 3), round(abs_y, 3)]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp):
    """Register the adobe_ai_shape_recipes tool."""

    @mcp.tool(
        name="adobe_ai_shape_recipes",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_shape_recipes(params: AiShapeRecipeInput) -> str:
        """Save, recall, and place proven shape recipes from the library.

        Actions:
        - save: capture a named pathItem from Illustrator, normalize its
          geometry, and store in the recipe library with tags.
        - recall: search recipes by comma-separated tags, returns matching
          recipe metadata (name, tags, point_count, original dimensions).
        - place: load a recipe by name, scale to target dimensions, and
          create the path in Illustrator at the given position.
        - list: show all recipe names, tags, and point counts.
        """
        lib_path = _library_path(params)

        # ------------------------------------------------------------------
        # SAVE — capture a pathItem from Illustrator
        # ------------------------------------------------------------------
        if params.action == "save":
            if not params.name:
                return "Error: save requires 'name' — the pathItem name to capture from Illustrator."

            escaped = escape_jsx_string(params.name)
            jsx = _EXTRACT_JSX_TEMPLATE.format(escaped_name=escaped)
            result = await _async_run_jsx("illustrator", jsx)

            if not result["success"]:
                return f"Error extracting pathItem: {result['stderr']}"

            try:
                raw = json.loads(result["stdout"])
            except json.JSONDecodeError:
                return f"Error parsing Illustrator response: {result['stdout']}"

            if "error" in raw:
                return f"Error: {raw['error']}"

            bbox_left = raw["bbox_left"]
            bbox_top = raw["bbox_top"]
            bbox_w = raw["bbox_width"]
            bbox_h = raw["bbox_height"]

            if bbox_w == 0 and bbox_h == 0:
                return "Error: pathItem has zero-size bounding box — cannot normalize."

            # Normalize all points to 0-1 space
            normalized_points = []
            for pt in raw["points"]:
                normalized_points.append({
                    "anchor": _normalize_point(
                        pt["anchor"][0], pt["anchor"][1],
                        bbox_left, bbox_top, bbox_w, bbox_h
                    ),
                    "left": _normalize_point(
                        pt["left"][0], pt["left"][1],
                        bbox_left, bbox_top, bbox_w, bbox_h
                    ),
                    "right": _normalize_point(
                        pt["right"][0], pt["right"][1],
                        bbox_left, bbox_top, bbox_w, bbox_h
                    ),
                })

            # Parse tags
            tag_list = []
            if params.tags:
                tag_list = [t.strip() for t in params.tags.split(",") if t.strip()]

            # Build recipe entry
            recipe_name = params.name
            recipe = {
                "name": recipe_name,
                "tags": tag_list,
                "points_normalized": normalized_points,
                "closed": raw["closed"],
                "point_count": len(normalized_points),
                "original_width": round(bbox_w, 3),
                "original_height": round(bbox_h, 3),
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

            # Load existing library, replace if same name exists, else append
            recipes = _load_library(lib_path)
            replaced = False
            for i, existing in enumerate(recipes):
                if existing.get("name") == recipe_name:
                    recipes[i] = recipe
                    replaced = True
                    break
            if not replaced:
                recipes.append(recipe)

            _save_library(lib_path, recipes)

            return json.dumps({
                "saved": recipe_name,
                "tags": tag_list,
                "point_count": len(normalized_points),
                "closed": raw["closed"],
                "original_width": round(bbox_w, 3),
                "original_height": round(bbox_h, 3),
                "library": lib_path,
                "replaced_existing": replaced,
            }, indent=2)

        # ------------------------------------------------------------------
        # RECALL — search recipes by tags
        # ------------------------------------------------------------------
        elif params.action == "recall":
            recipes = _load_library(lib_path)
            if not recipes:
                return "Recipe library is empty."

            # If tags provided, filter by them; otherwise search by name
            if params.tags:
                search_tags = {t.strip().lower() for t in params.tags.split(",") if t.strip()}
                matches = []
                for r in recipes:
                    recipe_tags = {t.lower() for t in r.get("tags", [])}
                    if search_tags & recipe_tags:  # any overlap
                        matches.append(r)
            elif params.name:
                matches = [r for r in recipes if params.name.lower() in r.get("name", "").lower()]
            else:
                matches = recipes

            if not matches:
                return "No recipes matched the search criteria."

            # Return metadata only — not full point data
            summaries = []
            for r in matches:
                summaries.append({
                    "name": r["name"],
                    "tags": r.get("tags", []),
                    "point_count": r.get("point_count", len(r.get("points_normalized", []))),
                    "closed": r.get("closed", True),
                    "original_width": r.get("original_width"),
                    "original_height": r.get("original_height"),
                    "created": r.get("created", "unknown"),
                })

            return json.dumps({
                "matches": len(summaries),
                "recipes": summaries,
            }, indent=2)

        # ------------------------------------------------------------------
        # PLACE — load a recipe and create the path in Illustrator
        # ------------------------------------------------------------------
        elif params.action == "place":
            if not params.name:
                return "Error: place requires 'name' — the recipe name to place."

            recipes = _load_library(lib_path)
            recipe = None
            for r in recipes:
                if r["name"] == params.name:
                    recipe = r
                    break

            if recipe is None:
                return f"Error: recipe '{params.name}' not found in library."

            normalized = recipe["points_normalized"]
            if not normalized:
                return f"Error: recipe '{params.name}' has no point data."

            # Determine target dimensions — use originals if not specified
            tw = params.target_width if params.target_width is not None else recipe.get("original_width", 100)
            th = params.target_height if params.target_height is not None else recipe.get("original_height", 100)
            tx = params.target_x if params.target_x is not None else 100.0
            ty = params.target_y if params.target_y is not None else -100.0  # AI Y: negative = below ruler zero

            # Denormalize all points
            anchors = []
            lefts = []
            rights = []
            for pt in normalized:
                a = _denormalize_point(pt["anchor"][0], pt["anchor"][1], tx, ty, tw, th)
                l = _denormalize_point(pt["left"][0], pt["left"][1], tx, ty, tw, th)
                r = _denormalize_point(pt["right"][0], pt["right"][1], tx, ty, tw, th)
                anchors.append(a)
                lefts.append(l)
                rights.append(r)

            closed_str = "true" if recipe.get("closed", True) else "false"
            escaped_recipe_name = escape_jsx_string(params.name)

            jsx = _PLACE_JSX_TEMPLATE.format(
                anchors_json=json.dumps(anchors),
                lefts_json=json.dumps(lefts),
                rights_json=json.dumps(rights),
                closed_str=closed_str,
                recipe_name=escaped_recipe_name,
            )

            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return f"Error placing recipe: {result['stderr']}"

            return result["stdout"]

        # ------------------------------------------------------------------
        # LIST — show all recipes in the library
        # ------------------------------------------------------------------
        elif params.action == "list":
            recipes = _load_library(lib_path)
            if not recipes:
                return "Recipe library is empty."

            summaries = []
            for r in recipes:
                summaries.append({
                    "name": r["name"],
                    "tags": r.get("tags", []),
                    "point_count": r.get("point_count", len(r.get("points_normalized", []))),
                    "closed": r.get("closed", True),
                    "original_width": r.get("original_width"),
                    "original_height": r.get("original_height"),
                    "created": r.get("created", "unknown"),
                })

            return json.dumps({
                "total_recipes": len(summaries),
                "recipes": summaries,
            }, indent=2)

        else:
            return (
                f"Unknown action: {params.action}. "
                "Valid actions: save, recall, place, list"
            )
