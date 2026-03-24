"""Tests for the character wizard one-call orchestrator.

Verifies the full pipeline produces a rig with parts, connections,
and hierarchy. Tests graceful error handling and status reporting.
All tests are pure Python -- no JSX or Adobe required.
"""

import json
import os

import cv2
import numpy as np
import pytest

from adobe_mcp.apps.illustrator.character_wizard import (
    run_wizard,
    wizard_status,
    _compute_depth,
    _estimate_symmetry,
    _init_wizard_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session")
def character_image_png():
    """200x300 image with body-like colored regions for wizard testing.

    Creates a simple character: large red torso, two green arms, blue head.
    """
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    path = os.path.join(FIXTURES_DIR, "wizard_character.png")
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    # Head (blue) at top center
    cv2.rectangle(img, (70, 10), (130, 70), (255, 0, 0), -1)
    # Torso (red) in center
    cv2.rectangle(img, (50, 80), (150, 200), (0, 0, 255), -1)
    # Left arm (green)
    cv2.rectangle(img, (10, 90), (45, 180), (0, 255, 0), -1)
    # Right arm (green)
    cv2.rectangle(img, (155, 90), (190, 180), (0, 255, 0), -1)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_wizard_produces_rig_with_parts(character_image_png, tmp_rig_dir):
    """Full wizard run should find parts from the image."""
    result = run_wizard(
        image_path=character_image_png,
        character_name="test_wizard_char",
        auto_label=True,
        n_clusters=4,
        min_area=30,
    )

    assert result["character_name"] == "test_wizard_char"
    assert result["parts_found"] > 0
    assert result["steps_completed"] > 0
    # Segmentation step should succeed
    assert result["steps"]["segmentation"]["completed"] is True


def test_wizard_finds_connections_and_hierarchy(character_image_png, tmp_rig_dir):
    """Wizard should detect connections between parts and build hierarchy."""
    result = run_wizard(
        image_path=character_image_png,
        character_name="test_wizard_hier",
        auto_label=False,
        n_clusters=4,
        min_area=30,
    )

    # Connection detection and hierarchy building should have run
    assert result["steps"]["connection_detection"]["completed"] is True
    assert result["steps"]["hierarchy_building"]["completed"] is True
    assert result["hierarchy_depth"] >= 1


def test_wizard_missing_image_graceful_error(tmp_rig_dir):
    """Wizard with non-existent image path should return error gracefully."""
    result = run_wizard(
        image_path="/nonexistent/fake_image.png",
        character_name="test_wizard_err",
    )

    assert "error" in result
    assert result["parts_found"] == 0
    assert result["hierarchy_depth"] == 0


def test_wizard_status_after_run(character_image_png, tmp_rig_dir):
    """wizard_status should reflect completed steps after a wizard run."""
    # Run wizard first
    run_wizard(
        image_path=character_image_png,
        character_name="test_wizard_status",
        auto_label=True,
        n_clusters=4,
        min_area=30,
    )

    # Check status
    status = wizard_status("test_wizard_status")
    assert status["character_name"] == "test_wizard_status"
    assert status["rig_exists"] is True
    assert status["steps"]["segmentation"] is True
    assert status["parts_count"] > 0


def test_wizard_status_empty_character(tmp_rig_dir):
    """wizard_status for a non-existent character should show empty state."""
    status = wizard_status("nonexistent_char_xyz")
    assert status["rig_exists"] is False
    assert status["parts_count"] == 0
    assert all(v is False for v in status["steps"].values())
