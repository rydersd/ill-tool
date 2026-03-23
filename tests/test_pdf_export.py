"""Tests for the pdf_export tool.

Tests data collection logic and layout calculation.
Cannot test actual PDF generation without Illustrator, so we focus
on the pure-Python pipeline stages.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.pdf_export import (
    _collect_panel_data,
    _calc_layout_params,
    _build_annotation_jsx,
)
from adobe_mcp.apps.illustrator.models import AiPdfExportInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rig_with_panels(panel_count: int = 3) -> dict:
    """Create a rig dict with storyboard panels and notes."""
    panels = []
    for i in range(1, panel_count + 1):
        panels.append({
            "number": i,
            "description": f"Panel {i} action",
            "camera": "medium" if i % 2 else "close_up",
            "duration_frames": 24 * i,
            "artboard_index": i - 1,
            "dialogue": f"Speaker: Line {i}",
        })

    return {
        "storyboard": {"panels": panels},
        "production_notes": {
            "1": [{"type": "direction", "note": "Pan right", "priority": "high"}],
            "2": [{"type": "vfx", "note": "Explosion", "priority": "normal"}],
        },
        "timeline": {"fps": 24},
    }


# ---------------------------------------------------------------------------
# _collect_panel_data
# ---------------------------------------------------------------------------


def test_collect_all_data():
    """Collecting with all flags True returns all fields."""
    rig = _make_rig_with_panels(2)
    params = AiPdfExportInput(
        output_path="/tmp/test.pdf",
        include_descriptions=True,
        include_dialogue=True,
        include_camera=True,
        include_timing=True,
        include_notes=True,
    )

    data = _collect_panel_data(rig, params)
    assert len(data) == 2

    # Panel 1 should have all fields
    p1 = data[0]
    assert p1["description"] == "Panel 1 action"
    assert p1["dialogue"] == "Speaker: Line 1"
    assert p1["camera"] == "medium"
    assert p1["duration_frames"] == 24
    assert p1["start_frame"] == 0
    assert len(p1["notes"]) == 1
    assert p1["notes"][0]["note"] == "Pan right"


def test_collect_excludes_disabled_fields():
    """Disabling flags omits those fields from collected data."""
    rig = _make_rig_with_panels(1)
    params = AiPdfExportInput(
        output_path="/tmp/test.pdf",
        include_descriptions=False,
        include_dialogue=False,
        include_camera=False,
        include_timing=True,
        include_notes=False,
    )

    data = _collect_panel_data(rig, params)
    p1 = data[0]

    assert "description" not in p1
    assert "dialogue" not in p1
    assert "camera" not in p1
    assert "notes" not in p1
    # Timing should still be present
    assert "duration_frames" in p1
    assert "start_frame" in p1


# ---------------------------------------------------------------------------
# _calc_layout_params
# ---------------------------------------------------------------------------


def test_layout_panels_grid():
    """Panels layout returns a grid configuration."""
    params = _calc_layout_params("panels", 6)
    assert params["mode"] == "panels"
    assert params["columns"] == 2
    assert params["rows"] == 3
    assert params["panels_per_page"] == 6


def test_layout_list_single():
    """List layout returns one panel per page."""
    params = _calc_layout_params("list", 4)
    assert params["mode"] == "list"
    assert params["panels_per_page"] == 1
    assert params["annotation_area_height"] == 200


def test_layout_presentation():
    """Presentation layout returns large panel mode."""
    params = _calc_layout_params("presentation", 4)
    assert params["mode"] == "presentation"
    assert params["panels_per_page"] == 1
