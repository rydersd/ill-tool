import json

import pytest
from pathlib import Path

from adobe_mcp.apps.illustrator.interaction_ingest import (
    _read_jsonl,
    _compute_reclassification_stats,
)


@pytest.fixture
def sample_jsonl(tmp_path):
    """Create a sample JSONL log file."""
    entries = [
        {"timestamp": "2026-04-04T15:00:00", "panel": "shapeaverager", "action": "reclassify",
         "before": {"shape": "arc"}, "after": {"shape": "lshape", "confidence": 0.8}},
        {"timestamp": "2026-04-04T15:01:00", "panel": "shapeaverager", "action": "confirm",
         "before": {"shape": "lshape", "confidence": 0.8}, "after": None},
        {"timestamp": "2026-04-04T15:02:00", "panel": "smartmerge", "action": "merge",
         "before": None, "after": {"mergedCount": 3}},
        {"timestamp": "2026-04-04T15:03:00", "panel": "shapeaverager", "action": "reclassify",
         "before": {"shape": "line"}, "after": {"shape": "arc", "confidence": 0.6}},
    ]
    f = tmp_path / "shapeaverager_20260404.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in entries))

    f2 = tmp_path / "smartmerge_20260404.jsonl"
    f2.write_text(json.dumps(entries[2]))

    return tmp_path


class TestReadJsonl:
    def test_reads_valid_entries(self, sample_jsonl):
        entries = _read_jsonl(sample_jsonl / "shapeaverager_20260404.jsonl")
        assert len(entries) == 4

    def test_missing_file(self, tmp_path):
        entries = _read_jsonl(tmp_path / "nonexistent.jsonl")
        assert entries == []

    def test_malformed_lines(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text('{"good": 1}\nnot json\n{"also_good": 2}\n')
        entries = _read_jsonl(f)
        assert len(entries) == 2


class TestReclassificationStats:
    def test_counts_transitions(self, sample_jsonl):
        entries = _read_jsonl(sample_jsonl / "shapeaverager_20260404.jsonl")
        stats = _compute_reclassification_stats(entries)
        assert stats["count"] == 2
        assert "arc -> lshape" in stats["transitions"]
        assert "line -> arc" in stats["transitions"]

    def test_empty_entries(self):
        stats = _compute_reclassification_stats([])
        assert stats["count"] == 0

    def test_no_reclassifications(self):
        entries = [{"action": "confirm"}, {"action": "merge"}]
        stats = _compute_reclassification_stats(entries)
        assert stats["count"] == 0


class TestDateFiltering:
    def test_filters_by_date(self, sample_jsonl):
        entries = _read_jsonl(sample_jsonl / "shapeaverager_20260404.jsonl")
        filtered = [e for e in entries if e.get("timestamp", "") >= "2026-04-04T15:02:00"]
        assert len(filtered) == 2


class TestPanelFiltering:
    def test_glob_pattern(self, sample_jsonl):
        """panel_name should filter to matching files only."""
        pattern = "smartmerge_*.jsonl"
        files = list(sample_jsonl.glob(pattern))
        assert len(files) == 1


class TestEdgeCases:
    def test_empty_jsonl_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        entries = _read_jsonl(f)
        assert entries == []

    def test_reclassification_missing_before_after(self):
        entries = [{"action": "reclassify"}]
        stats = _compute_reclassification_stats(entries)
        assert stats["count"] == 1
        assert "unknown -> unknown" in stats["transitions"]

    def test_single_line_file(self, tmp_path):
        f = tmp_path / "single.jsonl"
        f.write_text('{"action": "confirm", "panel": "shapeaverager"}\n')
        entries = _read_jsonl(f)
        assert len(entries) == 1
