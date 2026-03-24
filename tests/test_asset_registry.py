"""Tests for the asset_registry tool.

Tests CRUD operations, filtered listing (by_panel, by_asset),
and summary aggregation using _load_rig/_save_rig with
the tmp_rig_dir fixture.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.asset_registry import (
    _ensure_assets,
    _find_asset,
    _get_assets_for_panel,
    _get_panels_for_asset,
    _build_summary,
)
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# _ensure_assets
# ---------------------------------------------------------------------------


def test_ensure_assets_creates_list():
    """_ensure_assets adds an empty list if missing."""
    rig = {"character_name": "test"}
    result = _ensure_assets(rig)
    assert "assets" in result
    assert result["assets"] == []


# ---------------------------------------------------------------------------
# Register and retrieve assets
# ---------------------------------------------------------------------------


def test_register_asset(tmp_rig_dir):
    """Registering an asset stores it in the rig."""
    char = "test_asset_reg"
    rig = _load_rig(char)
    rig = _ensure_assets(rig)

    rig["assets"].append({
        "type": "character",
        "name": "gir",
        "panels": [1, 3],
    })
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    assert len(reloaded["assets"]) == 1
    assert reloaded["assets"][0]["name"] == "gir"
    assert reloaded["assets"][0]["panels"] == [1, 3]


def test_register_adds_panel_to_existing(tmp_rig_dir):
    """Registering same asset for a new panel appends the panel number."""
    char = "test_asset_panel"
    rig = _load_rig(char)
    rig = _ensure_assets(rig)
    rig["assets"].append({
        "type": "character",
        "name": "zim",
        "panels": [1],
    })
    _save_rig(char, rig)

    # Add panel 5
    reloaded = _load_rig(char)
    idx = _find_asset(reloaded["assets"], "character", "zim")
    assert idx is not None
    reloaded["assets"][idx]["panels"].append(5)
    reloaded["assets"][idx]["panels"].sort()
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert final["assets"][0]["panels"] == [1, 5]


def test_remove_asset(tmp_rig_dir):
    """Removing an asset removes it from the list."""
    char = "test_asset_rm"
    rig = _load_rig(char)
    rig = _ensure_assets(rig)
    rig["assets"].append({"type": "prop", "name": "sword", "panels": [2]})
    rig["assets"].append({"type": "character", "name": "dib", "panels": [1, 2]})
    _save_rig(char, rig)

    reloaded = _load_rig(char)
    reloaded["assets"] = [
        a for a in reloaded["assets"] if a.get("name") != "sword"
    ]
    _save_rig(char, reloaded)

    final = _load_rig(char)
    assert len(final["assets"]) == 1
    assert final["assets"][0]["name"] == "dib"


# ---------------------------------------------------------------------------
# Filtered listing
# ---------------------------------------------------------------------------


def test_list_by_panel():
    """_get_assets_for_panel returns only assets appearing in that panel."""
    assets = [
        {"type": "character", "name": "gir", "panels": [1, 2, 3]},
        {"type": "prop", "name": "taco", "panels": [2, 4]},
        {"type": "background", "name": "city", "panels": [1]},
    ]

    panel_2 = _get_assets_for_panel(assets, 2)
    names = [a["name"] for a in panel_2]
    assert "gir" in names
    assert "taco" in names
    assert "city" not in names


def test_list_by_asset():
    """_get_panels_for_asset returns the full asset record."""
    assets = [
        {"type": "character", "name": "gir", "panels": [1, 2, 3]},
        {"type": "prop", "name": "taco", "panels": [2, 4]},
    ]

    result = _get_panels_for_asset(assets, "taco")
    assert result is not None
    assert result["panels"] == [2, 4]
    assert result["type"] == "prop"

    # Non-existent asset
    result_none = _get_panels_for_asset(assets, "nonexistent")
    assert result_none is None


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------


def test_build_summary():
    """_build_summary produces correct type counts and panel usage."""
    assets = [
        {"type": "character", "name": "gir", "panels": [1, 2, 3, 5]},
        {"type": "character", "name": "zim", "panels": [1, 2]},
        {"type": "prop", "name": "taco", "panels": [2]},
        {"type": "background", "name": "city", "panels": [1, 2, 3]},
    ]

    summary = _build_summary(assets)

    assert summary["total_assets"] == 4
    assert summary["type_counts"]["character"] == 2
    assert summary["type_counts"]["prop"] == 1
    assert summary["type_counts"]["background"] == 1

    # Panel 2 should have all 4 assets
    assert len(summary["panel_usage"][2]) == 4

    # Panel 5 should have only gir
    assert summary["panel_usage"][5] == ["gir"]

    # Panels used should include 1, 2, 3, 5
    assert sorted(summary["panels_used"]) == [1, 2, 3, 5]
