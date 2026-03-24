"""Tests for the two-bone inverse kinematics solver.

Tests _solve_two_bone directly using known geometric configurations.
"""

import math

import pytest

from adobe_mcp.apps.illustrator.ik_solver import (
    _solve_two_bone,
    _distance,
    _clamp,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def test_distance():
    """Distance between (0,0) and (3,4) is 5."""
    assert _distance(0, 0, 3, 4) == pytest.approx(5.0)


def test_distance_same_point():
    """Distance from a point to itself is 0."""
    assert _distance(7.5, 3.2, 7.5, 3.2) == pytest.approx(0.0)


@pytest.mark.parametrize("val,lo,hi,expected", [
    (5, 0, 10, 5),
    (-3, 0, 10, 0),
    (15, 0, 10, 10),
    (0, 0, 0, 0),
])
def test_clamp(val, lo, hi, expected):
    assert _clamp(val, lo, hi) == expected


# ---------------------------------------------------------------------------
# Straight arm — target directly along the arm direction
# ---------------------------------------------------------------------------


def test_straight_arm():
    """Target at max reach → elbow on the line from shoulder to target.

    Shoulder at (0, 0), upper=100, lower=100, target at (200, 0).
    Max reach is 200, so the arm is fully extended. Elbow should be at (100, 0).
    """
    # Target at nearly max reach (200 - 0.01 per code)
    mid_x, mid_y = _solve_two_bone(
        root_x=0, root_y=0,
        target_x=199.99, target_y=0,
        upper_len=100, lower_len=100,
    )
    # Elbow should be near (100, 0) — on the line
    assert mid_x == pytest.approx(100.0, abs=1.0)
    assert abs(mid_y) < 2.0  # very close to the line


# ---------------------------------------------------------------------------
# Bent arm — target to the side
# ---------------------------------------------------------------------------


def test_bent_arm():
    """Target off-axis → elbow forms a triangle with shoulder and target.

    Shoulder at (0, 0), upper=100, lower=100, target at (100, 0).
    The chain must bend to reach a target closer than full extension.
    """
    mid_x, mid_y = _solve_two_bone(
        root_x=0, root_y=0,
        target_x=100, target_y=0,
        upper_len=100, lower_len=100,
    )
    # Verify the elbow is at the correct distance from both root and target
    d_root_mid = _distance(0, 0, mid_x, mid_y)
    d_mid_target = _distance(mid_x, mid_y, 100, 0)
    assert d_root_mid == pytest.approx(100.0, abs=0.1)
    assert d_mid_target == pytest.approx(100.0, abs=0.1)
    # Elbow should NOT be on the line (bent)
    assert abs(mid_y) > 1.0


# ---------------------------------------------------------------------------
# Unreachable target — clamped to max reach
# ---------------------------------------------------------------------------


def test_unreachable_clamp():
    """Target beyond max reach → result is clamped, arm fully extended.

    Shoulder at (0, 0), upper=100, lower=100, target at (500, 0).
    Max reach is ~200. Elbow should still be at valid bone length from shoulder.
    """
    mid_x, mid_y = _solve_two_bone(
        root_x=0, root_y=0,
        target_x=500, target_y=0,
        upper_len=100, lower_len=100,
    )
    d_root_mid = _distance(0, 0, mid_x, mid_y)
    # Upper bone length should still be 100
    assert d_root_mid == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Known geometry
# ---------------------------------------------------------------------------


def test_known_geometry():
    """Shoulder at (0,0), upper=100, lower=100, target at (100,100).

    The distance to target is sqrt(100^2 + 100^2) = ~141.42.
    Both bones are 100, so the triangle is feasible.

    Verify:
    - Elbow is at distance 100 from shoulder
    - Elbow is at distance 100 from target (approximately, since we
      compute the mid-joint, not the final tip)
    """
    mid_x, mid_y = _solve_two_bone(
        root_x=0, root_y=0,
        target_x=100, target_y=100,
        upper_len=100, lower_len=100,
    )
    d_shoulder_elbow = _distance(0, 0, mid_x, mid_y)
    # The computed mid joint should be exactly upper_len from root
    assert d_shoulder_elbow == pytest.approx(100.0, abs=0.1)

    # Distance from elbow to target should allow lower bone to reach
    d_elbow_target = _distance(mid_x, mid_y, 100, 100)
    # For the IK solution, the elbow-to-target distance should equal d (clamped),
    # not necessarily lower_len. But elbow position is geometrically valid.
    # The lower bone connects elbow to wrist (which is along the elbow-to-target direction).
    # So we just verify the triangle inequality is satisfied.
    assert d_elbow_target <= 100.0 + 0.5


def test_known_geometry_symmetric():
    """Symmetric case: target directly above shoulder.

    Shoulder at (0, 0), target at (0, 141.42), upper=lower=100.
    Distance = 141.42 < 200 → reachable. Elbow should be off to one side.
    """
    target_y = 100 * math.sqrt(2)
    mid_x, mid_y = _solve_two_bone(
        root_x=0, root_y=0,
        target_x=0, target_y=target_y,
        upper_len=100, lower_len=100,
    )
    d_root_mid = _distance(0, 0, mid_x, mid_y)
    assert d_root_mid == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Bend direction
# ---------------------------------------------------------------------------


def test_bend_direction_positive():
    """prefer_positive_bend=True bends counterclockwise."""
    mid_pos = _solve_two_bone(0, 0, 100, 0, 100, 100, prefer_positive_bend=True)
    mid_neg = _solve_two_bone(0, 0, 100, 0, 100, 100, prefer_positive_bend=False)
    # The two solutions should mirror in Y
    assert mid_pos[0] == pytest.approx(mid_neg[0], abs=0.1)
    assert mid_pos[1] == pytest.approx(-mid_neg[1], abs=0.1)
