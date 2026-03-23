"""Tests for project dashboard generation.

Verifies dashboard_data returns expected keys, HTML contains project name,
and panel count matches.
All tests are pure Python — no JSX or Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.project_dashboard import (
    dashboard_data,
    generate_dashboard,
)


# ---------------------------------------------------------------------------
# dashboard_data returns expected keys
# ---------------------------------------------------------------------------


def test_dashboard_data_returns_expected_keys():
    """dashboard_data produces all required top-level keys."""
    rig = {
        "character_name": "hero",
        "storyboard": {
            "panels": [
                {"number": 1, "description": "Opening", "duration_frames": 24},
            ],
        },
    }

    data = dashboard_data(rig)

    expected_keys = {"project", "characters", "panels", "timeline", "color_script", "exports"}
    assert expected_keys.issubset(data.keys()), (
        f"Missing keys: {expected_keys - data.keys()}"
    )

    # Project sub-keys
    assert "name" in data["project"]
    assert "character" in data["project"]

    # Timeline sub-keys
    assert "fps" in data["timeline"]
    assert "total_frames" in data["timeline"]
    assert "total_seconds" in data["timeline"]


# ---------------------------------------------------------------------------
# HTML contains project name
# ---------------------------------------------------------------------------


def test_html_contains_project_name():
    """Generated HTML includes the project/character name."""
    rig = {
        "character_name": "Aria",
        "project_name": "Moonlit Adventure",
        "storyboard": {"panels": []},
    }

    html = generate_dashboard(rig)

    assert "Moonlit Adventure" in html, "HTML should contain the project name"
    assert "Aria" in html, "HTML should contain the character name"
    assert "<html" in html, "Output should be valid HTML"
    assert "<style>" in html, "HTML should contain inline styles"


# ---------------------------------------------------------------------------
# Panel count matches
# ---------------------------------------------------------------------------


def test_panel_count_matches():
    """Dashboard data panel count matches the number of panels in the rig."""
    panels = [
        {"number": 1, "description": "Shot A", "duration_frames": 24},
        {"number": 2, "description": "Shot B", "duration_frames": 48},
        {"number": 3, "description": "Shot C", "duration_frames": 36},
    ]
    rig = {
        "character_name": "hero",
        "storyboard": {"panels": panels},
    }

    data = dashboard_data(rig)

    assert data["panels"]["count"] == 3
    assert len(data["panels"]["list"]) == 3

    # Timeline should reflect total frames
    assert data["timeline"]["total_frames"] == 24 + 48 + 36
