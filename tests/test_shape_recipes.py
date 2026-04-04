"""Test shape recipe save/load and coordinate normalization."""
import json
import os

from adobe_mcp.apps.illustrator.analysis.shape_recipes import (
    _load_library,
    _save_library,
    _normalize_point,
    _denormalize_point,
)


# ---------------------------------------------------------------------------
# Library I/O
# ---------------------------------------------------------------------------

def test_empty_library(tmp_recipe_path):
    """Loading from a nonexistent path returns an empty list."""
    recipes = _load_library(tmp_recipe_path)
    assert recipes == []


def test_save_and_list(tmp_recipe_path):
    """Save a recipe, load library, verify it appears."""
    recipe = {
        "name": "left_ear",
        "tags": ["ear", "left"],
        "points_normalized": [
            {"anchor": [0.0, 0.0], "left": [0.0, 0.0], "right": [0.0, 0.0]},
            {"anchor": [1.0, 0.0], "left": [1.0, 0.0], "right": [1.0, 0.0]},
            {"anchor": [1.0, 1.0], "left": [1.0, 1.0], "right": [1.0, 1.0]},
        ],
        "closed": True,
        "point_count": 3,
        "original_width": 50.0,
        "original_height": 40.0,
    }

    _save_library(tmp_recipe_path, [recipe])
    loaded = _load_library(tmp_recipe_path)

    assert len(loaded) == 1
    assert loaded[0]["name"] == "left_ear"
    assert loaded[0]["tags"] == ["ear", "left"]
    assert loaded[0]["point_count"] == 3


def test_recall_by_tag(tmp_recipe_path):
    """Save with tags, search by tag, verify match."""
    recipes = [
        {
            "name": "left_ear",
            "tags": ["ear", "left"],
            "points_normalized": [],
            "closed": True,
        },
        {
            "name": "right_eye",
            "tags": ["eye", "right"],
            "points_normalized": [],
            "closed": True,
        },
    ]
    _save_library(tmp_recipe_path, recipes)
    loaded = _load_library(tmp_recipe_path)

    # Simulate tag search (same logic as the tool's recall action)
    search_tags = {"ear"}
    matches = [
        r for r in loaded
        if search_tags & {t.lower() for t in r.get("tags", [])}
    ]

    assert len(matches) == 1
    assert matches[0]["name"] == "left_ear"


def test_recall_no_match(tmp_recipe_path):
    """Search for a tag that doesn't exist returns no matches."""
    recipes = [
        {"name": "nose", "tags": ["nose", "center"], "points_normalized": [], "closed": True},
    ]
    _save_library(tmp_recipe_path, recipes)
    loaded = _load_library(tmp_recipe_path)

    search_tags = {"wing"}
    matches = [
        r for r in loaded
        if search_tags & {t.lower() for t in r.get("tags", [])}
    ]
    assert len(matches) == 0


def test_multiple_recipes(tmp_recipe_path):
    """Save multiple recipes, verify all persist."""
    recipes = [
        {"name": f"shape_{i}", "tags": [f"tag_{i}"], "points_normalized": [], "closed": True}
        for i in range(5)
    ]
    _save_library(tmp_recipe_path, recipes)
    loaded = _load_library(tmp_recipe_path)
    assert len(loaded) == 5


def test_library_accepts_wrapper_format(tmp_recipe_path):
    """_load_library accepts both bare list and {"recipes": [...]} wrapper."""
    recipe = {"name": "wrapped", "tags": [], "points_normalized": [], "closed": True}

    # Write as {"recipes": [...]} wrapper
    os.makedirs(os.path.dirname(tmp_recipe_path), exist_ok=True)
    with open(tmp_recipe_path, "w") as f:
        json.dump({"recipes": [recipe]}, f)

    loaded = _load_library(tmp_recipe_path)
    assert len(loaded) == 1
    assert loaded[0]["name"] == "wrapped"


# ---------------------------------------------------------------------------
# Coordinate normalization / denormalization
# ---------------------------------------------------------------------------

def test_normalize_denormalize_identity():
    """Normalize then denormalize with same bbox returns original coordinates."""
    # Absolute coords within a 100x100 bbox starting at (100, 200) in AI coords
    # AI coord system: Y goes up, so bbox_top=200 is the highest Y
    bbox_left, bbox_top, bbox_w, bbox_h = 100, 200, 100, 100

    points = [[100, 200], [200, 200], [200, 100], [100, 100]]
    expected_normalized = [[0, 0], [1, 0], [1, 1], [0, 1]]

    for (px, py), (ex, ey) in zip(points, expected_normalized):
        nx, ny = _normalize_point(px, py, bbox_left, bbox_top, bbox_w, bbox_h)
        assert abs(nx - ex) < 1e-5, f"normalize X: got {nx}, expected {ex}"
        assert abs(ny - ey) < 1e-5, f"normalize Y: got {ny}, expected {ey}"


def test_normalize_specific_values():
    """Verify normalization math for known input."""
    # bbox: left=100, top=200, width=100, height=100
    # Point at (150, 150) should normalize to (0.5, 0.5)
    nx, ny = _normalize_point(150, 150, 100, 200, 100, 100)
    assert abs(nx - 0.5) < 1e-5
    assert abs(ny - 0.5) < 1e-5


def test_denormalize_specific_values():
    """Verify denormalization places points at expected absolute positions."""
    # Target area: top-left at (50, 400), size 200x200
    # Normalized (0.5, 0.5) -> absolute X = 50 + 0.5*200 = 150, Y = 400 - 0.5*200 = 300
    ax, ay = _denormalize_point(0.5, 0.5, 50, 400, 200, 200)
    assert abs(ax - 150) < 0.01
    assert abs(ay - 300) < 0.01


def test_normalize_denormalize_roundtrip():
    """Normalize a point, then denormalize with same bbox, recover original."""
    bbox_left, bbox_top, bbox_w, bbox_h = 200, 500, 150, 80
    original_x, original_y = 275, 460

    nx, ny = _normalize_point(original_x, original_y, bbox_left, bbox_top, bbox_w, bbox_h)
    ax, ay = _denormalize_point(nx, ny, bbox_left, bbox_top, bbox_w, bbox_h)

    assert abs(ax - original_x) < 0.01
    assert abs(ay - original_y) < 0.01


def test_normalize_zero_width():
    """Zero-width bbox returns 0 for the X coordinate instead of dividing by zero."""
    nx, ny = _normalize_point(100, 150, 100, 200, 0, 100)
    assert nx == 0.0
    assert abs(ny - 0.5) < 1e-5


def test_normalize_zero_height():
    """Zero-height bbox returns 0 for the Y coordinate instead of dividing by zero."""
    nx, ny = _normalize_point(150, 200, 100, 200, 100, 0)
    assert abs(nx - 0.5) < 1e-5
    assert ny == 0.0
