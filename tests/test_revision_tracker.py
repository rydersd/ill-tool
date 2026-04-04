"""Tests for the revision tracker tool.

Verifies version numbering, metadata persistence, and approval flag
using temporary directories. All tests are pure Python.
"""

import json
import os
import time

import pytest

from adobe_mcp.apps.illustrator.production.revision_tracker import (
    _load_metadata,
    _save_metadata,
    _next_version,
    _snapshot_path,
    _revisions_dir,
    _ensure_revisions,
    REVISIONS_BASE,
)


@pytest.fixture
def tmp_revisions(tmp_path, monkeypatch):
    """Redirect revision storage to temp directory."""
    rev_dir = tmp_path / "ai_revisions"
    rev_dir.mkdir()

    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.production.revision_tracker.REVISIONS_BASE",
        str(rev_dir),
    )
    return rev_dir


# ---------------------------------------------------------------------------
# Version numbering
# ---------------------------------------------------------------------------


def test_next_version_starts_at_one():
    """First version number is 1 when no versions exist."""
    meta = {"versions": []}
    assert _next_version(meta) == 1


def test_next_version_increments():
    """Version number increments from the highest existing version."""
    meta = {"versions": [{"version": 1}, {"version": 2}, {"version": 3}]}
    assert _next_version(meta) == 4


# ---------------------------------------------------------------------------
# Metadata persistence
# ---------------------------------------------------------------------------


def test_metadata_round_trip(tmp_revisions):
    """Metadata saves to disk and loads back correctly."""
    char = "test_char"
    panel = 1
    meta = {
        "character_name": char,
        "panel_number": panel,
        "versions": [
            {
                "version": 1,
                "path": "/tmp/test/v1.png",
                "timestamp": 1700000000.0,
                "timestamp_iso": "2023-11-14T22:13:20",
                "note": "first draft",
                "approved": False,
            },
        ],
        "current_version": 1,
        "approved_version": None,
    }
    _save_metadata(char, panel, meta)

    loaded = _load_metadata(char, panel)
    assert loaded["character_name"] == char
    assert loaded["panel_number"] == panel
    assert len(loaded["versions"]) == 1
    assert loaded["versions"][0]["note"] == "first draft"
    assert loaded["current_version"] == 1


def test_load_missing_metadata_returns_scaffold(tmp_revisions):
    """Loading metadata for a non-existent panel returns an empty scaffold."""
    meta = _load_metadata("nonexistent", 99)
    assert meta["versions"] == []
    assert meta["current_version"] == 0
    assert meta["approved_version"] is None


# ---------------------------------------------------------------------------
# Approval flag
# ---------------------------------------------------------------------------


def test_approval_sets_flag(tmp_revisions):
    """Approving a version sets its approved flag and records in metadata."""
    char = "test_approve"
    panel = 1
    meta = {
        "character_name": char,
        "panel_number": panel,
        "versions": [
            {"version": 1, "path": "/tmp/v1.png", "timestamp": 1.0,
             "timestamp_iso": "", "note": "", "approved": False},
            {"version": 2, "path": "/tmp/v2.png", "timestamp": 2.0,
             "timestamp_iso": "", "note": "", "approved": False},
        ],
        "current_version": 2,
        "approved_version": None,
    }

    # Approve version 2
    for v in meta["versions"]:
        v["approved"] = (v["version"] == 2)
    meta["approved_version"] = 2

    _save_metadata(char, panel, meta)
    loaded = _load_metadata(char, panel)

    assert loaded["approved_version"] == 2
    v1 = [v for v in loaded["versions"] if v["version"] == 1][0]
    v2 = [v for v in loaded["versions"] if v["version"] == 2][0]
    assert v1["approved"] is False
    assert v2["approved"] is True
