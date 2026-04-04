"""Tests for the context-aware smart dispatcher tool.

Verifies context-based suggestions, usage logging, frequency statistics,
and pattern learning — all pure Python, no Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.pipeline.smart_dispatcher import (
    suggest,
    log_use,
    get_stats,
    learn_pattern,
    _load_storage,
    _save_storage,
    CONTEXT_RULES,
)


# ---------------------------------------------------------------------------
# Fixture — isolated storage directory
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Redirect dispatcher storage to a temp directory so tests don't
    pollute the real ~/.claude/memory/illustration/ path.
    """
    storage_dir = str(tmp_path / "illustration")
    os.makedirs(storage_dir, exist_ok=True)
    storage_file = os.path.join(storage_dir, "tool_usage.json")

    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.pipeline.smart_dispatcher.STORAGE_DIR", storage_dir
    )
    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.pipeline.smart_dispatcher.STORAGE_FILE", storage_file
    )
    return storage_file


# ---------------------------------------------------------------------------
# test_suggest_empty_doc: empty doc → suggest setup tools
# ---------------------------------------------------------------------------


def test_suggest_empty_doc():
    """An empty document context suggests setup-oriented tools."""
    result = suggest(json.dumps({"empty_document": True}))

    assert "error" not in result
    assert len(result["suggestions"]) > 0
    assert "empty_document" in result["matched_rules"]

    # Should include the tools from the empty_document rule
    expected = CONTEXT_RULES["empty_document"]
    for tool in expected:
        assert tool in result["suggestions"], (
            f"Expected '{tool}' in suggestions for empty document"
        )


def test_suggest_no_context():
    """No context at all defaults to empty document suggestions."""
    result = suggest(None)

    assert "error" not in result
    assert len(result["suggestions"]) > 0
    assert "empty_document" in result["matched_rules"]


# ---------------------------------------------------------------------------
# test_suggest_with_reference: has reference → suggest tracing tools
# ---------------------------------------------------------------------------


def test_suggest_with_reference():
    """Document with a reference image suggests tracing-related tools."""
    result = suggest(json.dumps({"has_reference_image": True}))

    assert "error" not in result
    assert "has_reference_image" in result["matched_rules"]

    expected = CONTEXT_RULES["has_reference_image"]
    for tool in expected:
        assert tool in result["suggestions"]


def test_suggest_multiple_flags():
    """Multiple context flags combine their suggestions without duplicates."""
    result = suggest(json.dumps({
        "has_reference_image": True,
        "has_trace_layer": True,
    }))

    assert "has_reference_image" in result["matched_rules"]
    assert "has_trace_layer" in result["matched_rules"]

    # Should have tools from both rules
    all_expected = set(CONTEXT_RULES["has_reference_image"] + CONTEXT_RULES["has_trace_layer"])
    for tool in all_expected:
        assert tool in result["suggestions"]

    # No duplicates
    assert len(result["suggestions"]) == len(set(result["suggestions"]))


# ---------------------------------------------------------------------------
# test_log_and_stats: log 5 uses → stats reflect counts
# ---------------------------------------------------------------------------


def test_log_and_stats(isolated_storage):
    """Logging 5 tool uses produces accurate statistics."""
    # Log a mix of tools
    log_use("trace_workflow.setup", isolated_storage)
    log_use("analyze_reference", isolated_storage)
    log_use("trace_workflow.setup", isolated_storage)
    log_use("auto_trace", isolated_storage)
    log_use("trace_workflow.setup", isolated_storage)

    stats = get_stats(isolated_storage)

    assert stats["total_invocations"] == 5
    assert stats["unique_tools"] == 3

    # Frequency should reflect actual counts
    assert stats["frequency"]["trace_workflow.setup"] == 3
    assert stats["frequency"]["analyze_reference"] == 1
    assert stats["frequency"]["auto_trace"] == 1


def test_log_records_timestamp(isolated_storage):
    """Each log entry includes a timestamp."""
    result = log_use("test_tool", isolated_storage)

    assert result["logged"] is True
    assert result["tool_name"] == "test_tool"
    assert result["total_entries"] == 1

    # Verify the entry in storage
    storage = _load_storage(isolated_storage)
    assert len(storage["usage_log"]) == 1
    entry = storage["usage_log"][0]
    assert "timestamp" in entry
    assert "iso_time" in entry
    assert entry["tool_name"] == "test_tool"


def test_stats_empty(isolated_storage):
    """Stats on an empty log return sensible defaults."""
    stats = get_stats(isolated_storage)

    assert stats["total_invocations"] == 0
    assert stats["unique_tools"] == 0
    assert stats["most_used"] is None
    assert stats["least_used"] is None


# ---------------------------------------------------------------------------
# test_frequency_ranking: most used tool ranked first
# ---------------------------------------------------------------------------


def test_frequency_ranking(isolated_storage):
    """The most frequently used tool is ranked first in statistics."""
    # Log tools with different frequencies
    for _ in range(5):
        log_use("tool_a", isolated_storage)
    for _ in range(3):
        log_use("tool_b", isolated_storage)
    for _ in range(1):
        log_use("tool_c", isolated_storage)

    stats = get_stats(isolated_storage)

    assert stats["most_used"]["tool"] == "tool_a"
    assert stats["most_used"]["count"] == 5
    assert stats["least_used"]["tool"] == "tool_c"
    assert stats["least_used"]["count"] == 1

    # Frequency dict keys should be in descending order
    freq_list = list(stats["frequency"].items())
    for i in range(len(freq_list) - 1):
        assert freq_list[i][1] >= freq_list[i + 1][1], (
            f"{freq_list[i][0]} ({freq_list[i][1]}) should be >= "
            f"{freq_list[i + 1][0]} ({freq_list[i + 1][1]})"
        )


# ---------------------------------------------------------------------------
# test_learn_pattern: teach pattern → pattern suggested after trigger
# ---------------------------------------------------------------------------


def test_learn_pattern(isolated_storage):
    """Teaching a pattern stores it and it appears in suggestions after trigger."""
    # Teach a pattern: when user does setup, they usually trace then export
    result = learn_pattern(
        "setup_trace_export",
        json.dumps(["trace_workflow.setup", "auto_trace", "export_trace"]),
        isolated_storage,
    )

    assert result["learned"] is True
    assert result["pattern_name"] == "setup_trace_export"
    assert result["trigger_tool"] == "trace_workflow.setup"
    assert result["total_patterns"] == 1

    # Log the trigger tool
    log_use("trace_workflow.setup", isolated_storage)

    # Now suggest should include the pattern continuation
    # We need to patch storage so suggest reads the same file
    import adobe_mcp.apps.illustrator.pipeline.smart_dispatcher as sd
    original_load = sd._load_storage

    def _patched_load(path=None):
        return original_load(isolated_storage)

    sd._load_storage = _patched_load
    try:
        suggestion = suggest(json.dumps({"has_reference_image": True}))
        assert len(suggestion["pattern_suggestions"]) >= 1

        pattern_match = suggestion["pattern_suggestions"][0]
        assert pattern_match["pattern"] == "setup_trace_export"
        assert pattern_match["next_tool"] == "auto_trace"
    finally:
        sd._load_storage = original_load


# ---------------------------------------------------------------------------
# test_suggest_form_edge_rules: new form edge context rules
# ---------------------------------------------------------------------------


def test_suggest_wants_form_structure():
    """Context flag wants_form_structure suggests form edge tools."""
    result = suggest(json.dumps({"wants_form_structure": True}))

    assert "error" not in result
    assert "wants_form_structure" in result["matched_rules"]

    expected = CONTEXT_RULES["wants_form_structure"]
    for tool in expected:
        assert tool in result["suggestions"]


def test_suggest_wants_shadow_free_reference():
    """Context flag wants_shadow_free_reference suggests normal reference tools."""
    result = suggest(json.dumps({"wants_shadow_free_reference": True}))

    assert "error" not in result
    assert "wants_shadow_free_reference" in result["matched_rules"]
    assert "normal_reference" in result["suggestions"]
    assert "form_edge_extract" in result["suggestions"]


def test_suggest_no_3d_reconstruction():
    """When 3D reconstruction is unavailable, suggest form edge alternatives."""
    result = suggest(json.dumps({"no_3d_reconstruction": True}))

    assert "error" not in result
    assert "no_3d_reconstruction" in result["matched_rules"]
    assert "form_edge_extract" in result["suggestions"]
    assert "normal_reference" in result["suggestions"]


def test_suggest_form_vs_shadow_analysis():
    """Requesting form vs shadow analysis suggests the right combination."""
    result = suggest(json.dumps({"wants_form_vs_shadow_analysis": True}))

    assert "error" not in result
    assert "wants_form_vs_shadow_analysis" in result["matched_rules"]
    assert "normal_reference" in result["suggestions"]
    assert "form_edge_extract" in result["suggestions"]
    assert "tonal_analyzer" in result["suggestions"]


def test_suggest_form_edge_with_reference_image():
    """Combining form edge flags with reference image produces no duplicates."""
    result = suggest(json.dumps({
        "has_reference_image": True,
        "wants_form_structure": True,
    }))

    assert "has_reference_image" in result["matched_rules"]
    assert "wants_form_structure" in result["matched_rules"]

    # No duplicates
    assert len(result["suggestions"]) == len(set(result["suggestions"]))


def test_learn_pattern_invalid_sequence(isolated_storage):
    """Learning with fewer than 2 tools returns an error."""
    result = learn_pattern(
        "too_short",
        json.dumps(["single_tool"]),
        isolated_storage,
    )
    assert "error" in result
    assert "at least 2" in result["error"]


def test_learn_pattern_invalid_json(isolated_storage):
    """Learning with invalid JSON returns an error."""
    result = learn_pattern(
        "bad_json",
        "not valid json [",
        isolated_storage,
    )
    assert "error" in result
