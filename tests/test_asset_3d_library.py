"""Tests for the paired 2D+3D asset library tool.

Verifies save/load roundtrip, search, and list —
all pure Python, no Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.threed.asset_3d_library import (
    save_asset_metadata,
    load_asset_metadata,
    search_assets,
    list_all_assets,
    VALID_ASSET_TYPES,
)


# ---------------------------------------------------------------------------
# Fixture — isolated index file
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_index(tmp_path):
    """Create an isolated index path for each test."""
    return str(tmp_path / "assets" / "index.json")


# ---------------------------------------------------------------------------
# test_save_load_roundtrip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundtrip:
    """Save an asset and load it back."""

    def test_save_and_load(self, isolated_index):
        """Saving an asset and loading it returns the same data."""
        save_result = save_asset_metadata(
            name="hero_character",
            asset_type="character",
            paths_2d=["/art/hero.ai", "/art/hero.svg"],
            paths_3d=["/models/hero.obj", "/models/hero.fbx"],
            rig_path="/rigs/hero_rig.json",
            tags=["hero", "main", "human"],
            index_path=isolated_index,
        )

        assert save_result["saved"] == "hero_character"
        assert save_result["asset_type"] == "character"
        assert save_result["paths_2d_count"] == 2
        assert save_result["paths_3d_count"] == 2
        assert save_result["has_rig"] is True
        assert save_result["tag_count"] == 3

        # Load it back
        loaded = load_asset_metadata("hero_character", index_path=isolated_index)

        assert loaded["name"] == "hero_character"
        assert loaded["asset_type"] == "character"
        assert len(loaded["paths_2d"]) == 2
        assert len(loaded["paths_3d"]) == 2
        assert loaded["rig_path"] == "/rigs/hero_rig.json"
        assert "hero" in loaded["tags"]

    def test_load_nonexistent(self, isolated_index):
        """Loading a non-existent asset returns an error."""
        result = load_asset_metadata("does_not_exist", index_path=isolated_index)
        assert "error" in result

    def test_update_preserves_created(self, isolated_index):
        """Updating an asset preserves the original creation timestamp."""
        save_asset_metadata(
            name="prop",
            asset_type="prop",
            tags=["v1"],
            index_path=isolated_index,
        )
        first = load_asset_metadata("prop", index_path=isolated_index)
        created_first = first["created"]

        # Update with new tags
        save_asset_metadata(
            name="prop",
            asset_type="prop",
            tags=["v2"],
            index_path=isolated_index,
        )
        second = load_asset_metadata("prop", index_path=isolated_index)

        assert second["created"] == created_first
        assert "v2" in second["tags"]


# ---------------------------------------------------------------------------
# test_search_assets
# ---------------------------------------------------------------------------


class TestSearchAssets:
    """Search assets by name and tag."""

    def test_search_by_name(self, isolated_index):
        """Search matches asset name substring."""
        save_asset_metadata(name="dragon_red", asset_type="creature", index_path=isolated_index)
        save_asset_metadata(name="dragon_blue", asset_type="creature", index_path=isolated_index)
        save_asset_metadata(name="sword", asset_type="prop", index_path=isolated_index)

        result = search_assets("dragon", index_path=isolated_index)
        assert result["result_count"] == 2
        names = [r["name"] for r in result["results"]]
        assert "dragon_red" in names
        assert "dragon_blue" in names

    def test_search_by_tag(self, isolated_index):
        """Search matches tags."""
        save_asset_metadata(
            name="tree_oak",
            asset_type="environment",
            tags=["vegetation", "deciduous"],
            index_path=isolated_index,
        )
        save_asset_metadata(
            name="rock_big",
            asset_type="environment",
            tags=["terrain"],
            index_path=isolated_index,
        )

        result = search_assets("vegetation", index_path=isolated_index)
        assert result["result_count"] == 1
        assert result["results"][0]["name"] == "tree_oak"

    def test_search_filter_by_type(self, isolated_index):
        """Type filter narrows search results."""
        save_asset_metadata(name="hero", asset_type="character", index_path=isolated_index)
        save_asset_metadata(name="heroic_sword", asset_type="prop", index_path=isolated_index)

        # Both match 'hero', but filter to props only
        result = search_assets("hero", asset_type="prop", index_path=isolated_index)
        assert result["result_count"] == 1
        assert result["results"][0]["name"] == "heroic_sword"


# ---------------------------------------------------------------------------
# test_list_all_assets
# ---------------------------------------------------------------------------


class TestListAllAssets:
    """List all assets in the library."""

    def test_list_empty(self, isolated_index):
        """Empty library returns zero assets."""
        result = list_all_assets(index_path=isolated_index)
        assert result["total"] == 0
        assert result["assets"] == []

    def test_list_multiple(self, isolated_index):
        """Library with multiple assets lists them all with type counts."""
        save_asset_metadata(name="char_a", asset_type="character", index_path=isolated_index)
        save_asset_metadata(name="char_b", asset_type="character", index_path=isolated_index)
        save_asset_metadata(name="prop_a", asset_type="prop", index_path=isolated_index)

        result = list_all_assets(index_path=isolated_index)
        assert result["total"] == 3
        assert result["type_counts"]["character"] == 2
        assert result["type_counts"]["prop"] == 1
