"""Tests for the pipeline runner tool.

Verifies pipeline definition, execution with mocked steps, parameter
overrides, and save/load roundtrip persistence.
All tests are pure Python -- no JSX or Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.pipeline_runner import (
    define_pipeline,
    run_pipeline,
    list_pipelines,
    save_pipeline,
    load_pipeline,
    BUILTIN_PIPELINES,
    _pipelines,
)


# ---------------------------------------------------------------------------
# Cleanup fixture to reset user-defined pipelines between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pipelines():
    """Clear user-defined pipelines before each test."""
    _pipelines.clear()
    yield
    _pipelines.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_define_pipeline_stores_steps():
    """define_pipeline should store steps and return confirmation."""
    steps = [
        {"tool": "segment_parts", "params": {"n_clusters": 5}},
        {"tool": "detect_connections", "params": {}},
        {"tool": "build_hierarchy", "params": {}},
    ]
    result = define_pipeline("my_pipeline", steps)

    assert result["pipeline"] == "my_pipeline"
    assert result["steps"] == 3
    assert "segment_parts" in result["tools"]
    assert "detect_connections" in result["tools"]


def test_run_pipeline_executes_steps():
    """run_pipeline should execute all steps sequentially."""
    steps = [
        {"tool": "step_a", "params": {"x": 1}},
        {"tool": "step_b", "params": {"y": 2}},
    ]
    define_pipeline("test_run", steps)
    result = run_pipeline("test_run")

    assert result["pipeline"] == "test_run"
    assert result["success"] is True
    assert result["steps_run"] == 2
    assert result["steps_total"] == 2
    # Each step should report dispatched
    for step_result in result["results"]:
        assert step_result["success"] is True
        assert step_result["output"]["dispatched"] is True


def test_run_pipeline_with_overrides():
    """run_pipeline should apply parameter overrides by index and tool name."""
    steps = [
        {"tool": "step_a", "params": {"x": 1, "y": 2}},
        {"tool": "step_b", "params": {"z": 3}},
    ]
    define_pipeline("test_override", steps)

    # Override step 0 by index and step_b by tool name
    overrides = {
        "0": {"x": 99},
        "step_b": {"z": 42},
    }
    result = run_pipeline("test_override", overrides)

    assert result["success"] is True
    # Step 0 should have x=99
    assert result["results"][0]["params"]["x"] == 99
    assert result["results"][0]["params"]["y"] == 2  # unchanged
    # Step 1 should have z=42
    assert result["results"][1]["params"]["z"] == 42


def test_save_load_pipeline_roundtrip(tmp_path):
    """save_pipeline then load_pipeline should restore the same pipeline."""
    steps = [
        {"tool": "analyze", "params": {"mode": "fast"}},
        {"tool": "export", "params": {"format": "png"}},
    ]
    define_pipeline("roundtrip_test", steps)

    save_path = str(tmp_path / "pipeline.json")
    save_result = save_pipeline("roundtrip_test", save_path)
    assert save_result["saved"] == save_path
    assert os.path.isfile(save_path)

    # Clear and reload
    _pipelines.clear()
    load_result = load_pipeline(save_path)
    assert load_result["loaded"] == "roundtrip_test"
    assert load_result["steps"] == 2

    # Should be runnable after load
    run_result = run_pipeline("roundtrip_test")
    assert run_result["success"] is True


def test_list_pipelines_includes_builtins():
    """list_pipelines should include built-in pipelines."""
    result = list_pipelines()

    assert result["total"] >= len(BUILTIN_PIPELINES)
    for name in BUILTIN_PIPELINES:
        assert name in result["pipelines"]
        assert result["pipelines"][name]["builtin"] is True
