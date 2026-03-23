"""Tests for interactive drawing session manager.

Verifies session creation, convergence tracking, plateau detection,
and status reporting.
All tests are pure Python — no JSX or Adobe required.
"""

import os
import json

import pytest

from adobe_mcp.apps.illustrator.drawing_session import (
    start_session,
    next_shape,
    record_iteration,
    session_status,
    end_session,
    advance_shape,
    SESSION_DIR,
    _save_session,
)


@pytest.fixture(autouse=True)
def clean_session_dir(tmp_path, monkeypatch):
    """Redirect session storage to a temp directory."""
    test_dir = str(tmp_path / "sessions")
    os.makedirs(test_dir, exist_ok=True)
    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.drawing_session.SESSION_DIR", test_dir
    )
    # Also patch the module-level reference used by _session_path
    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.drawing_session._session_path",
        lambda sid: os.path.join(test_dir, f"{sid}.json"),
    )


# ---------------------------------------------------------------------------
# Start creates session
# ---------------------------------------------------------------------------


def test_start_creates_session():
    """Starting a session returns a valid session ID and initial state."""
    result = start_session("hero", reference_path="/tmp/ref.png")

    assert "session_id" in result
    assert result["character_name"] == "hero"
    assert result["shape_count"] > 0
    assert result["status"] == "active"

    # Session should be loadable
    status = session_status(result["session_id"])
    assert status["status"] == "active"
    assert status["shapes_completed_count"] == 0


# ---------------------------------------------------------------------------
# Record tracks history and plateau detected
# ---------------------------------------------------------------------------


def test_record_tracks_history_and_plateau():
    """Recording iterations tracks convergence and detects plateau."""
    result = start_session("hero")
    sid = result["session_id"]

    # Record several iterations with diminishing improvement
    scores = [0.50, 0.55, 0.56, 0.565, 0.567]
    plateau_detected = False

    for score in scores:
        rec = record_iteration(
            sid, score,
            plateau_threshold=0.02,
            plateau_count=3,
        )
        if rec.get("plateau_warning"):
            plateau_detected = True

    # After 3 iterations with < 2% improvement, plateau should be detected
    assert plateau_detected, "Plateau should be detected after minimal improvement"


# ---------------------------------------------------------------------------
# Status reports correctly
# ---------------------------------------------------------------------------


def test_status_reports_correctly():
    """Session status reflects shapes done, current shape, and iteration count."""
    result = start_session("hero", shapes=[
        {"name": "body", "axis": "vertical", "priority": 1, "suggested_points": 6},
        {"name": "head", "axis": "vertical", "priority": 2, "suggested_points": 8},
        {"name": "arm", "axis": "horizontal", "priority": 3, "suggested_points": 6},
    ])
    sid = result["session_id"]

    # Record some iterations on first shape
    record_iteration(sid, 0.3)
    record_iteration(sid, 0.5)

    # Advance to next shape
    advance_shape(sid)

    status = session_status(sid)

    assert status["shapes_total"] == 3
    assert "body" in status["shapes_completed"]
    assert status["shapes_completed_count"] == 1
    assert status["current_shape"] == "head"
    assert status["total_iterations"] == 2
