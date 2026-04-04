"""Tests for batch export orchestrator.

Verifies manifest contains expected categories, output dir structure,
and format list filters output.
All tests are pure Python — no JSX or Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.production.batch_export_all import (
    export_all,
    export_manifest,
    ALL_FORMATS,
)


# ---------------------------------------------------------------------------
# Manifest contains expected categories
# ---------------------------------------------------------------------------


def test_manifest_contains_expected_categories(tmp_path):
    """Full export manifest has entries for all default format categories."""
    rig = {
        "character_name": "hero",
        "storyboard": {
            "panels": [
                {"number": 1, "duration_frames": 24, "description": "Intro"},
                {"number": 2, "duration_frames": 48, "description": "Action"},
            ],
        },
    }

    output_dir = str(tmp_path / "export")
    manifest = export_all(rig, output_dir)

    # Should have entries for all default formats
    for fmt in ALL_FORMATS:
        assert fmt in manifest["exports"], f"Missing export category: {fmt}"

    assert manifest["panel_count"] == 2
    assert manifest["project"] == "Storyboard"


# ---------------------------------------------------------------------------
# Output dir structure
# ---------------------------------------------------------------------------


def test_output_dir_structure(tmp_path):
    """Export creates the expected subdirectory structure."""
    rig = {
        "character_name": "hero",
        "storyboard": {"panels": [{"number": 1, "duration_frames": 24}]},
    }

    output_dir = str(tmp_path / "export")
    export_all(rig, output_dir)

    # Check subdirectories
    assert os.path.isdir(os.path.join(output_dir, "panels"))
    assert os.path.isdir(os.path.join(output_dir, "pdf"))
    assert os.path.isdir(os.path.join(output_dir, "data"))
    assert os.path.isdir(os.path.join(output_dir, "ae"))

    # Manifest should be written
    assert os.path.isfile(os.path.join(output_dir, "manifest.json"))


# ---------------------------------------------------------------------------
# Format list filters output
# ---------------------------------------------------------------------------


def test_format_list_filters_output(tmp_path):
    """Specifying a format subset only exports those formats."""
    rig = {
        "character_name": "hero",
        "storyboard": {"panels": [{"number": 1, "duration_frames": 24}]},
    }

    output_dir = str(tmp_path / "export")
    manifest = export_all(rig, output_dir, formats=["json", "edl"])

    assert "json" in manifest["exports"]
    assert "edl" in manifest["exports"]
    assert "png" not in manifest["exports"]
    assert "pdf" not in manifest["exports"]
    assert "ae_jsx" not in manifest["exports"]
    assert manifest["formats"] == ["json", "edl"]
