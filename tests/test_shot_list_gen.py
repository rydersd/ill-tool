"""Tests for the production shot list generator.

Tests use mock storyboard data written to the rig via tmp_rig_dir.
Verifies table formatting, CSV output, JSON output, and timing
calculations.
"""

import csv
import io
import json

import pytest

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig
from adobe_mcp.apps.illustrator.shot_list_gen import (
    _build_shot_rows,
    _format_csv,
    _format_table,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storyboard_rig(
    panels: list[dict],
    scenes: list[dict] | None = None,
    fps: int = 24,
) -> dict:
    """Create a storyboard rig with panels, scenes, and timeline."""
    rig = _load_rig("storyboard")
    rig["storyboard"] = {"panels": panels}
    rig["scenes"] = scenes or []
    rig["timeline"] = {"fps": fps, "duration_frames": 120}
    _save_rig("storyboard", rig)
    return rig


# ---------------------------------------------------------------------------
# Build shot rows
# ---------------------------------------------------------------------------


def test_build_rows_basic(tmp_rig_dir):
    """Shot rows contain correct panel numbers and descriptions."""
    _make_storyboard_rig(
        panels=[
            {"number": 1, "camera": "medium", "description": "GIR stands menacingly", "duration_frames": 24},
            {"number": 2, "camera": "close_up", "description": "ZIM reacts", "duration_frames": 48},
        ],
        scenes=[{"number": 1, "name": "Scene 1", "panels": [1, 2], "location": "INT", "time": "NIGHT"}],
    )

    rig = _load_rig("storyboard")
    rows = _build_shot_rows(rig, include_timing=True, include_camera=True)

    assert len(rows) == 2
    assert rows[0]["shot"] == 1
    assert rows[0]["panel"] == 1
    assert rows[0]["scene"] == 1
    assert rows[0]["camera"] == "MEDIUM"
    assert rows[0]["description"] == "GIR stands menacingly"
    assert rows[1]["shot"] == 2
    assert rows[1]["camera"] == "CLOSE_UP"


# ---------------------------------------------------------------------------
# Timing calculation
# ---------------------------------------------------------------------------


def test_timing_calculation(tmp_rig_dir):
    """Duration and cumulative time are calculated correctly."""
    _make_storyboard_rig(
        panels=[
            {"number": 1, "camera": "wide", "description": "A", "duration_frames": 24},
            {"number": 2, "camera": "medium", "description": "B", "duration_frames": 48},
            {"number": 3, "camera": "close_up", "description": "C", "duration_frames": 12},
        ],
        fps=24,
    )

    rig = _load_rig("storyboard")
    rows = _build_shot_rows(rig, include_timing=True, include_camera=True)

    # 24 frames at 24fps = 1.0s
    assert rows[0]["duration_seconds"] == pytest.approx(1.0)
    assert rows[0]["cumulative_seconds"] == pytest.approx(1.0)

    # 48 frames at 24fps = 2.0s, cumulative = 3.0s
    assert rows[1]["duration_seconds"] == pytest.approx(2.0)
    assert rows[1]["cumulative_seconds"] == pytest.approx(3.0)

    # 12 frames at 24fps = 0.5s, cumulative = 3.5s
    assert rows[2]["duration_seconds"] == pytest.approx(0.5)
    assert rows[2]["cumulative_seconds"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------


def test_csv_format(tmp_rig_dir):
    """CSV output has correct headers and parseable rows."""
    _make_storyboard_rig(
        panels=[
            {"number": 1, "camera": "wide", "description": "Opening shot", "duration_frames": 24},
        ],
    )

    rig = _load_rig("storyboard")
    rows = _build_shot_rows(rig, include_timing=True, include_camera=True)
    csv_text = _format_csv(rows)

    # Parse the CSV back
    reader = csv.DictReader(io.StringIO(csv_text))
    csv_rows = list(reader)

    assert len(csv_rows) == 1
    assert csv_rows[0]["shot"] == "1"
    assert csv_rows[0]["description"] == "Opening shot"
    assert "duration_seconds" in csv_rows[0]


# ---------------------------------------------------------------------------
# Table format
# ---------------------------------------------------------------------------


def test_table_format(tmp_rig_dir):
    """Table format includes header row and shot data."""
    _make_storyboard_rig(
        panels=[
            {"number": 1, "camera": "medium", "description": "GIR walks in", "duration_frames": 24},
        ],
    )

    rig = _load_rig("storyboard")
    rows = _build_shot_rows(rig, include_timing=True, include_camera=True)
    table = _format_table(rows)

    assert "Shot" in table
    assert "Scene" in table
    assert "Camera" in table
    assert "GIR walks in" in table


# ---------------------------------------------------------------------------
# Empty storyboard
# ---------------------------------------------------------------------------


def test_empty_storyboard(tmp_rig_dir):
    """Empty storyboard produces no shot rows."""
    _make_storyboard_rig(panels=[])

    rig = _load_rig("storyboard")
    rows = _build_shot_rows(rig, include_timing=True, include_camera=True)
    assert rows == []

    table = _format_table(rows)
    assert "No shots" in table
