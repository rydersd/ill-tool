"""Tests for pose interpolation math.

Tests _interpolate_joints, _interpolate_path_states, and _lerp directly
without Illustrator interaction.
"""

import pytest

from adobe_mcp.apps.illustrator.animation.pose_interpolate import (
    _lerp,
    _interpolate_joints,
    _interpolate_path_states,
)


# ---------------------------------------------------------------------------
# _lerp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a,b,t,expected", [
    (0, 100, 0.5, 50.0),
    (0, 100, 0.0, 0.0),
    (0, 100, 1.0, 100.0),
    (-50, 50, 0.5, 0.0),
    (10, 10, 0.5, 10.0),
])
def test_lerp(a, b, t, expected):
    assert _lerp(a, b, t) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Midpoint joints
# ---------------------------------------------------------------------------


def test_midpoint_joints():
    """Interpolating at t=0.5 between two joint positions gives the midpoint."""
    joints_a = {"head": {"x": 0, "y": 0}, "hand": {"x": 100, "y": 200}}
    joints_b = {"head": {"x": 100, "y": 100}, "hand": {"x": 200, "y": 0}}

    result = _interpolate_joints(joints_a, joints_b, t=0.5)

    assert result["head"]["x"] == pytest.approx(50.0)
    assert result["head"]["y"] == pytest.approx(50.0)
    assert result["hand"]["x"] == pytest.approx(150.0)
    assert result["hand"]["y"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# t=0 → equals pose_a
# ---------------------------------------------------------------------------


def test_t_zero():
    """At t=0, interpolated joints equal pose_a."""
    joints_a = {"head": {"x": 10, "y": 20}, "foot": {"x": 30, "y": 40}}
    joints_b = {"head": {"x": 90, "y": 80}, "foot": {"x": 70, "y": 60}}

    result = _interpolate_joints(joints_a, joints_b, t=0.0)

    assert result["head"]["x"] == pytest.approx(10.0)
    assert result["head"]["y"] == pytest.approx(20.0)
    assert result["foot"]["x"] == pytest.approx(30.0)
    assert result["foot"]["y"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# t=1 → equals pose_b
# ---------------------------------------------------------------------------


def test_t_one():
    """At t=1, interpolated joints equal pose_b."""
    joints_a = {"head": {"x": 10, "y": 20}}
    joints_b = {"head": {"x": 90, "y": 80}}

    result = _interpolate_joints(joints_a, joints_b, t=1.0)

    assert result["head"]["x"] == pytest.approx(90.0)
    assert result["head"]["y"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Path point interpolation
# ---------------------------------------------------------------------------


def test_path_points_interpolation():
    """Path anchor points interpolate correctly at t=0.5."""
    states_a = {
        "arm": {
            "points": [[0, 0], [100, 0]],
            "handles": [
                {"left": [0, 0], "right": [10, 0]},
                {"left": [90, 0], "right": [100, 0]},
            ],
            "closed": False,
        }
    }
    states_b = {
        "arm": {
            "points": [[100, 100], [200, 100]],
            "handles": [
                {"left": [100, 100], "right": [110, 100]},
                {"left": [190, 100], "right": [200, 100]},
            ],
            "closed": False,
        }
    }

    result = _interpolate_path_states(states_a, states_b, t=0.5)

    assert "arm" in result
    pts = result["arm"]["points"]
    assert pts[0][0] == pytest.approx(50.0)
    assert pts[0][1] == pytest.approx(50.0)
    assert pts[1][0] == pytest.approx(150.0)
    assert pts[1][1] == pytest.approx(50.0)


def test_path_handles_interpolation():
    """Bezier handles interpolate between the two poses."""
    states_a = {
        "curve": {
            "points": [[0, 0]],
            "handles": [{"left": [0, 0], "right": [20, 0]}],
            "closed": False,
        }
    }
    states_b = {
        "curve": {
            "points": [[100, 100]],
            "handles": [{"left": [80, 100], "right": [120, 100]}],
            "closed": False,
        }
    }

    result = _interpolate_path_states(states_a, states_b, t=0.5)

    handles = result["curve"]["handles"]
    assert handles[0]["left"][0] == pytest.approx(40.0)
    assert handles[0]["right"][0] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# Joint only in one pose — fallback behavior
# ---------------------------------------------------------------------------


def test_joint_only_in_a():
    """Joint present only in pose_a is taken as-is."""
    joints_a = {"head": {"x": 10, "y": 20}, "tail": {"x": 99, "y": 88}}
    joints_b = {"head": {"x": 90, "y": 80}}

    result = _interpolate_joints(joints_a, joints_b, t=0.5)
    # "tail" only in a → taken from a
    assert result["tail"]["x"] == 99
    assert result["tail"]["y"] == 88


def test_joint_only_in_b():
    """Joint present only in pose_b is taken as-is."""
    joints_a = {"head": {"x": 10, "y": 20}}
    joints_b = {"head": {"x": 90, "y": 80}, "tail": {"x": 77, "y": 66}}

    result = _interpolate_joints(joints_a, joints_b, t=0.5)
    assert result["tail"]["x"] == 77
    assert result["tail"]["y"] == 66


# ---------------------------------------------------------------------------
# Path with mismatched point counts falls back
# ---------------------------------------------------------------------------


def test_mismatched_point_count_fallback():
    """Paths with different point counts fall back to the closer pose."""
    states_a = {
        "shape": {
            "points": [[0, 0], [10, 10]],
            "handles": [],
            "closed": False,
        }
    }
    states_b = {
        "shape": {
            "points": [[0, 0], [10, 10], [20, 20]],  # 3 points vs 2
            "handles": [],
            "closed": False,
        }
    }

    # t < 0.5 → use a
    result_a = _interpolate_path_states(states_a, states_b, t=0.3)
    assert len(result_a["shape"]["points"]) == 2  # from a

    # t >= 0.5 → use b
    result_b = _interpolate_path_states(states_a, states_b, t=0.7)
    assert len(result_b["shape"]["points"]) == 3  # from b
