"""Tests for the reference library tool.

Verifies add/get/remove roundtrip, tag search, and category filtering.
All tests are pure Python -- no JSX or Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.ml_vision.reference_library import (
    add_reference,
    get_references,
    remove_reference,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_add_get_remove_roundtrip(tmp_path):
    """add_reference then get_references then remove_reference should roundtrip."""
    lib_path = str(tmp_path / "refs.json")

    # Add a reference
    add_result = add_reference(
        category="character",
        name="hero_front",
        image_path="/tmp/hero_front.png",
        tags=["main_character", "front_view"],
        library_path=lib_path,
    )
    assert add_result["added"] == "hero_front"
    assert add_result["category"] == "character"

    # Get it back
    get_result = get_references(category="character", library_path=lib_path)
    assert get_result["count"] == 1
    assert get_result["references"][0]["name"] == "hero_front"

    # Remove it
    remove_result = remove_reference(name="hero_front", library_path=lib_path)
    assert remove_result["removed"] == "hero_front"
    assert remove_result["remaining"] == 0

    # Verify it's gone
    get_result2 = get_references(library_path=lib_path)
    assert get_result2["count"] == 0


def test_tag_search(tmp_path):
    """get_references with tags should filter by matching tags."""
    lib_path = str(tmp_path / "tag_refs.json")

    # Add references with different tags
    add_reference("character", "hero", "/tmp/hero.png", ["main", "front"], library_path=lib_path)
    add_reference("character", "villain", "/tmp/villain.png", ["antagonist", "side"], library_path=lib_path)
    add_reference("prop", "sword", "/tmp/sword.png", ["weapon", "main"], library_path=lib_path)

    # Search by tag "main" (should match hero and sword)
    result = get_references(tags=["main"], library_path=lib_path)
    assert result["count"] == 2
    names = {r["name"] for r in result["references"]}
    assert "hero" in names
    assert "sword" in names
    assert "villain" not in names


def test_category_filtering(tmp_path):
    """get_references with category should only return matching category."""
    lib_path = str(tmp_path / "cat_refs.json")

    add_reference("character", "char1", "/tmp/c1.png", library_path=lib_path)
    add_reference("environment", "env1", "/tmp/e1.png", library_path=lib_path)
    add_reference("prop", "prop1", "/tmp/p1.png", library_path=lib_path)

    # Filter by environment
    result = get_references(category="environment", library_path=lib_path)
    assert result["count"] == 1
    assert result["references"][0]["name"] == "env1"

    # Filter by character
    result2 = get_references(category="character", library_path=lib_path)
    assert result2["count"] == 1
    assert result2["references"][0]["name"] == "char1"
