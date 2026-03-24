"""Test the progress tracker logic (convergence history, plateau detection)."""
import json
import os

from adobe_mcp.apps.common.progress import (
    _load_progress,
    _save_progress,
    _detect_plateau,
    _compute_improvement_rate,
    _parse_shape_scores,
    _PLATEAU_WINDOW,
    _PLATEAU_THRESHOLD,
    ProgressInput,
    _action_record,
    _action_status,
    _action_plateau_check,
)


def _write_progress(path: str, session_id: str, scores: list[float]) -> None:
    """Helper: write a progress file with the given convergence scores."""
    iterations = []
    for score in scores:
        iterations.append({
            "timestamp": "2026-01-01T00:00:00",
            "convergence": round(score, 4),
            "shape_scores": {},
            "total_shapes": 0,
            "total_anchors": 0,
        })
    data = {
        "session_id": session_id,
        "started": "2026-01-01T00:00:00",
        "iterations": iterations,
    }
    _save_progress(path, data)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def test_record_creates_file(tmp_progress_file):
    """Recording a score creates the progress file on disk."""
    assert not os.path.exists(tmp_progress_file)

    params = ProgressInput(
        action="record",
        convergence_score=0.5,
        project_dir=os.path.dirname(tmp_progress_file),
    )
    result_json = _action_record(params)
    result = json.loads(result_json)

    assert "error" not in result
    assert result["iteration"] == 1
    assert result["convergence"] == 0.5
    # File now exists
    assert os.path.isfile(
        os.path.join(os.path.dirname(tmp_progress_file), ".line-art-progress.json")
    )


def test_multiple_records(tmp_progress_file):
    """Writing 3 entries produces 3 iterations in the progress data."""
    project_dir = os.path.dirname(tmp_progress_file)

    for score in [0.4, 0.6, 0.8]:
        params = ProgressInput(
            action="record",
            convergence_score=score,
            project_dir=project_dir,
        )
        _action_record(params)

    # Read back via status action
    status_params = ProgressInput(action="status", project_dir=project_dir)
    result = json.loads(_action_status(status_params))

    assert result["iteration_count"] == 3
    assert result["history"] == [0.4, 0.6, 0.8]


# ---------------------------------------------------------------------------
# Plateau detection (unit-level, no file I/O)
# ---------------------------------------------------------------------------

def test_plateau_detection_unit():
    """Scores within PLATEAU_THRESHOLD trigger plateau."""
    # 3 scores within 0.02 of each other
    assert _detect_plateau([0.70, 0.71, 0.71]) is True


def test_no_plateau_unit():
    """Scores with clear improvement do not trigger plateau."""
    assert _detect_plateau([0.50, 0.65, 0.80]) is False


def test_plateau_needs_minimum_window():
    """Fewer than PLATEAU_WINDOW entries never trigger plateau."""
    assert _detect_plateau([0.70, 0.71]) is False
    assert _detect_plateau([0.70]) is False
    assert _detect_plateau([]) is False


# ---------------------------------------------------------------------------
# Plateau detection via file (integration-level)
# ---------------------------------------------------------------------------

def test_plateau_detection_via_file(tmp_progress_file):
    """Write 3 stagnant entries, verify plateau_check detects it."""
    project_dir = os.path.dirname(tmp_progress_file)
    _write_progress(
        os.path.join(project_dir, ".line-art-progress.json"),
        "test-session",
        [0.70, 0.71, 0.71],
    )

    params = ProgressInput(action="plateau_check", project_dir=project_dir)
    result = json.loads(_action_plateau_check(params))
    assert result["plateau"] is True


def test_no_plateau_via_file(tmp_progress_file):
    """Write 3 improving entries, verify no plateau."""
    project_dir = os.path.dirname(tmp_progress_file)
    _write_progress(
        os.path.join(project_dir, ".line-art-progress.json"),
        "test-session",
        [0.50, 0.65, 0.80],
    )

    params = ProgressInput(action="plateau_check", project_dir=project_dir)
    result = json.loads(_action_plateau_check(params))
    assert result["plateau"] is False


# ---------------------------------------------------------------------------
# Improvement rate
# ---------------------------------------------------------------------------

def test_improvement_rate():
    """Verify improvement rate calculation: (last - first) / (n - 1)."""
    rate = _compute_improvement_rate([0.20, 0.40, 0.60])
    assert abs(rate - 0.2) < 0.001


def test_improvement_rate_single():
    """Single entry yields zero improvement rate."""
    assert _compute_improvement_rate([0.5]) == 0.0


def test_improvement_rate_empty():
    """Empty history yields zero improvement rate."""
    assert _compute_improvement_rate([]) == 0.0


# ---------------------------------------------------------------------------
# Shape score parsing
# ---------------------------------------------------------------------------

def test_parse_shape_scores_valid():
    """Valid JSON object is parsed into {str: float} dict."""
    result = _parse_shape_scores('{"head": 5.2, "body": 3.1}')
    assert result == {"head": 5.2, "body": 3.1}


def test_parse_shape_scores_invalid():
    """Invalid JSON returns empty dict instead of raising."""
    assert _parse_shape_scores("not json") == {}
    assert _parse_shape_scores(None) == {}
    assert _parse_shape_scores("") == {}


# ---------------------------------------------------------------------------
# Load from missing file
# ---------------------------------------------------------------------------

def test_load_missing_file(tmp_progress_file):
    """Loading from a non-existent path returns empty dict."""
    data = _load_progress(tmp_progress_file)
    assert data == {}
