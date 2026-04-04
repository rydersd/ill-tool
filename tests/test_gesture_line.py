"""Tests for gesture line handle computation.

Tests the pure Python compute_gesture_handles function directly —
verifies handle directions, lengths, and edge cases.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.drawing.gesture_line import compute_gesture_handles


# ---------------------------------------------------------------------------
# Handle direction for 3-point chain
# ---------------------------------------------------------------------------


def test_middle_handle_direction():
    """Middle point handles should align along the prev→next direction."""
    # Horizontal chain: [0,0] → [100,0] → [200,0]
    points = [[0, 0], [100, 0], [200, 0]]
    handles = compute_gesture_handles(points, strength=0.33)

    assert len(handles) == 3

    # Middle point (index 1) handles should be horizontal
    mid = handles[1]
    # handle_out should be to the right of the anchor
    assert mid["handle_out"][0] > mid["anchor"][0]
    assert mid["handle_out"][1] == pytest.approx(0.0, abs=0.01)
    # handle_in should be to the left of the anchor
    assert mid["handle_in"][0] < mid["anchor"][0]
    assert mid["handle_in"][1] == pytest.approx(0.0, abs=0.01)


def test_first_point_no_in_handle():
    """First point's in-handle should equal its anchor (no incoming curve)."""
    points = [[0, 0], [100, 0], [200, 0]]
    handles = compute_gesture_handles(points, strength=0.33)
    first = handles[0]
    assert first["handle_in"] == first["anchor"]


def test_last_point_no_out_handle():
    """Last point's out-handle should equal its anchor (no outgoing curve)."""
    points = [[0, 0], [100, 0], [200, 0]]
    handles = compute_gesture_handles(points, strength=0.33)
    last = handles[-1]
    assert last["handle_out"] == last["anchor"]


def test_vertical_chain_direction():
    """Vertical chain: handles should aim vertically, not horizontally."""
    points = [[100, 0], [100, 100], [100, 200]]
    handles = compute_gesture_handles(points, strength=0.33)

    mid = handles[1]
    # Direction is vertical (prev→next = [100,0]→[100,200], direction = [0, 1])
    # handle_out Y should be above anchor, X unchanged
    assert mid["handle_out"][0] == pytest.approx(100.0, abs=0.01)
    assert mid["handle_out"][1] > mid["anchor"][1]
    # handle_in Y should be below anchor
    assert mid["handle_in"][0] == pytest.approx(100.0, abs=0.01)
    assert mid["handle_in"][1] < mid["anchor"][1]


def test_handle_strength_scales_length():
    """Increasing handle_strength should proportionally increase handle distance."""
    points = [[0, 0], [100, 0], [200, 0]]

    handles_low = compute_gesture_handles(points, strength=0.2)
    handles_high = compute_gesture_handles(points, strength=0.5)

    # Out-handle distance from anchor should be greater with higher strength
    dist_low = abs(handles_low[0]["handle_out"][0] - handles_low[0]["anchor"][0])
    dist_high = abs(handles_high[0]["handle_out"][0] - handles_high[0]["anchor"][0])

    assert dist_high > dist_low
    # Ratio should be approximately 0.5/0.2 = 2.5
    assert dist_high / dist_low == pytest.approx(2.5, abs=0.1)
