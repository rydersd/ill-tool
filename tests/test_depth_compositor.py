"""Tests for the depth compositor tool.

Verifies depth sorting, z-index assignment, and status reporting.
All tests are pure Python — no 3D deps required.
"""

import pytest

from adobe_mcp.apps.illustrator.depth_compositor import (
    assign_z_index,
    sort_by_depth,
)


# ---------------------------------------------------------------------------
# Depth sorting
# ---------------------------------------------------------------------------


def test_sort_by_depth_ascending():
    """Parts should be sorted near-to-far (ascending depth)."""
    parts = ["arm", "head", "background", "torso"]
    depths = [2.0, 1.0, 10.0, 3.0]

    result = sort_by_depth(parts, depths)

    assert result == ["head", "arm", "torso", "background"]


def test_sort_by_depth_already_sorted():
    """Already-sorted parts remain in order."""
    parts = ["near", "mid", "far"]
    depths = [1.0, 5.0, 10.0]

    result = sort_by_depth(parts, depths)

    assert result == ["near", "mid", "far"]


def test_sort_by_depth_mismatched_lengths():
    """Mismatched lengths raise ValueError."""
    with pytest.raises(ValueError, match="same length"):
        sort_by_depth(["a", "b"], [1.0])


# ---------------------------------------------------------------------------
# Z-index assignment
# ---------------------------------------------------------------------------


def test_assign_z_index_nearest_gets_highest():
    """Nearest object (first in depth_order) gets the highest z-index."""
    parts = ["a", "b", "c"]
    depth_order = ["a", "b", "c"]  # a is nearest

    z_map = assign_z_index(parts, depth_order, z_start=0, z_step=10)

    # Nearest (a) should have highest z-index
    assert z_map["a"] > z_map["b"] > z_map["c"]
    # Check specific values: a=20, b=10, c=0
    assert z_map["a"] == 20
    assert z_map["b"] == 10
    assert z_map["c"] == 0


def test_assign_z_index_custom_start_and_step():
    """Custom z_start and z_step are respected."""
    parts = ["front", "back"]
    depth_order = ["front", "back"]

    z_map = assign_z_index(parts, depth_order, z_start=100, z_step=50)

    # front (nearest) gets highest: 100 + (2-1-0)*50 = 150
    assert z_map["front"] == 150
    # back (farthest) gets lowest: 100 + (2-1-1)*50 = 100
    assert z_map["back"] == 100


def test_assign_z_index_single_part():
    """Single part gets z_start value."""
    z_map = assign_z_index(["only"], ["only"], z_start=0, z_step=10)
    assert z_map["only"] == 0
