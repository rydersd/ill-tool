"""Track drawing progress across correction iterations.

Convergence history, per-shape improvement tracking, plateau detection,
and efficiency metrics. Pairs with the compare_drawing tool to give the
LLM a clear picture of whether iterative corrections are converging or
spinning their wheels.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class ProgressInput(BaseModel):
    """Track drawing progress — convergence history, plateau detection, efficiency metrics."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = Field(
        default="status",
        description="Action: record (add score), status (get history), reset (clear), plateau_check",
    )
    convergence_score: Optional[float] = Field(
        default=None,
        description="Convergence score to record (for record action)",
        ge=0,
        le=1,
    )
    shape_scores: Optional[str] = Field(
        default=None,
        description="JSON object of shape_name: hausdorff_dist for per-shape tracking",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier (auto-generated if omitted)",
    )
    project_dir: Optional[str] = Field(
        default=None,
        description="Project directory for storing progress file",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROGRESS_FILENAME = ".line-art-progress.json"
_PLATEAU_WINDOW = 3
_PLATEAU_THRESHOLD = 0.02


def _progress_path(project_dir: Optional[str]) -> str:
    """Return the absolute path to the progress JSON file."""
    base = project_dir if project_dir and os.path.isdir(project_dir) else "/tmp"
    return os.path.join(base, _PROGRESS_FILENAME)


def _load_progress(path: str) -> dict:
    """Load the progress file, returning an empty structure if missing or corrupt."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_progress(path: str, data: dict) -> None:
    """Atomically write the progress file (write-then-rename)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _auto_session_id() -> str:
    """Generate a session id from the current date."""
    return f"session-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"


def _parse_shape_scores(raw: Optional[str]) -> dict:
    """Parse the shape_scores JSON string into a dict, returning {} on failure."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): float(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _compute_improvement_rate(history: list[float]) -> float:
    """Average convergence gain per iteration across the full history."""
    if len(history) < 2:
        return 0.0
    total_gain = history[-1] - history[0]
    return round(total_gain / (len(history) - 1), 4)


def _detect_plateau(history: list[float]) -> bool:
    """True if the last PLATEAU_WINDOW scores are within PLATEAU_THRESHOLD of each other."""
    if len(history) < _PLATEAU_WINDOW:
        return False
    window = history[-_PLATEAU_WINDOW:]
    return (max(window) - min(window)) <= _PLATEAU_THRESHOLD


def _shape_analysis(iterations: list[dict]) -> tuple[list[str], list[str]]:
    """Classify shapes as improving or stuck based on the last few iterations.

    Returns (improving, stuck) lists of shape names.
    """
    if len(iterations) < 2:
        # Not enough data to judge
        all_shapes = set()
        for it in iterations:
            all_shapes.update(it.get("shape_scores", {}).keys())
        return sorted(all_shapes), []

    improving: list[str] = []
    stuck: list[str] = []

    # Gather all shape names seen across iterations
    all_shapes: set[str] = set()
    for it in iterations:
        all_shapes.update(it.get("shape_scores", {}).keys())

    for shape in sorted(all_shapes):
        # Collect the Hausdorff distances for this shape across iterations
        scores = []
        for it in iterations:
            s = it.get("shape_scores", {}).get(shape)
            if s is not None:
                scores.append(s)

        if len(scores) < 2:
            improving.append(shape)
            continue

        # Check last PLATEAU_WINDOW entries for stagnation
        recent = scores[-_PLATEAU_WINDOW:] if len(scores) >= _PLATEAU_WINDOW else scores
        if len(recent) >= 2 and (max(recent) - min(recent)) <= 1.0:
            # Hausdorff hasn't moved by more than 1px — stuck
            stuck.append(shape)
        elif scores[-1] < scores[-2]:
            # Distance is decreasing — improving
            improving.append(shape)
        else:
            stuck.append(shape)

    return improving, stuck


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _action_record(params: ProgressInput) -> str:
    """Record a new iteration's convergence score and shape scores."""
    if params.convergence_score is None:
        return json.dumps({"error": "convergence_score is required for the record action"})

    path = _progress_path(params.project_dir)
    data = _load_progress(path)

    # Initialise if empty
    if not data:
        data = {
            "session_id": params.session_id or _auto_session_id(),
            "started": _now_iso(),
            "iterations": [],
        }
    elif params.session_id and data.get("session_id") != params.session_id:
        # New session requested — reset
        data = {
            "session_id": params.session_id,
            "started": _now_iso(),
            "iterations": [],
        }

    shape_scores = _parse_shape_scores(params.shape_scores)

    entry = {
        "timestamp": _now_iso(),
        "convergence": round(params.convergence_score, 4),
        "shape_scores": shape_scores,
        "total_shapes": len(shape_scores),
        "total_anchors": sum(1 for _ in shape_scores.values()),
    }
    data["iterations"].append(entry)
    _save_progress(path, data)

    # Build summary
    iteration_num = len(data["iterations"])
    delta_str = ""
    if iteration_num >= 2:
        prev = data["iterations"][-2]["convergence"]
        delta = round(params.convergence_score - prev, 4)
        sign = "+" if delta >= 0 else ""
        delta_str = f" ({sign}{delta} from previous)"

    summary = {
        "message": f"Iteration {iteration_num}: convergence {params.convergence_score}{delta_str}",
        "iteration": iteration_num,
        "convergence": params.convergence_score,
        "session_id": data["session_id"],
        "file": path,
    }
    return json.dumps(summary)


def _action_status(params: ProgressInput) -> str:
    """Return full convergence history with computed deltas and shape analysis."""
    path = _progress_path(params.project_dir)
    data = _load_progress(path)

    if not data or not data.get("iterations"):
        return json.dumps({
            "message": "No progress recorded yet. Use action='record' to start tracking.",
            "iteration_count": 0,
        })

    iterations = data["iterations"]
    history = [it["convergence"] for it in iterations]
    improving, stuck = _shape_analysis(iterations)

    result = {
        "session_id": data.get("session_id", "unknown"),
        "started": data.get("started"),
        "iteration_count": len(iterations),
        "current_convergence": history[-1],
        "best_convergence": max(history),
        "improvement_rate": _compute_improvement_rate(history),
        "history": history,
        "is_plateau": _detect_plateau(history),
        "shapes_improving": improving,
        "shapes_stuck": stuck,
        "file": path,
    }
    return json.dumps(result)


def _action_plateau_check(params: ProgressInput) -> str:
    """Check for convergence plateau and per-shape stagnation."""
    path = _progress_path(params.project_dir)
    data = _load_progress(path)

    if not data or not data.get("iterations"):
        return json.dumps({
            "plateau": False,
            "message": "No progress data — nothing to check.",
        })

    iterations = data["iterations"]
    history = [it["convergence"] for it in iterations]
    is_plateau = _detect_plateau(history)
    improving, stuck = _shape_analysis(iterations)

    result: dict = {
        "plateau": is_plateau,
        "current_convergence": history[-1],
        "window": history[-_PLATEAU_WINDOW:] if len(history) >= _PLATEAU_WINDOW else history,
        "shapes_stuck": stuck,
        "shapes_improving": improving,
    }

    suggestions: list[str] = []
    if is_plateau:
        score = history[-1]
        suggestions.append(
            f"Plateau detected at {score:.2f}. Consider: "
            "adjust correction_strength, try different simplification, "
            "or accept current quality."
        )
    if stuck:
        suggestions.append(
            f"Shapes stalled ({', '.join(stuck)}): try redrawing these "
            "shapes from scratch or adjusting their anchor points manually."
        )

    if suggestions:
        result["suggestions"] = suggestions
    else:
        result["message"] = "No plateau detected — convergence is still improving."

    return json.dumps(result)


def _action_reset(params: ProgressInput) -> str:
    """Delete or reset the progress file."""
    path = _progress_path(params.project_dir)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as exc:
            return json.dumps({"error": f"Could not remove progress file: {exc}"})

    return json.dumps({
        "message": "Progress data reset.",
        "file": path,
    })


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------

_ACTIONS = {
    "record": _action_record,
    "status": _action_status,
    "plateau_check": _action_plateau_check,
    "reset": _action_reset,
}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_progress_tool(mcp):
    """Register the adobe_drawing_progress tool."""

    @mcp.tool(
        name="adobe_drawing_progress",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_drawing_progress(params: ProgressInput) -> str:
        """Track drawing progress across correction iterations.

        Records convergence scores, detects plateaus, and tracks per-shape
        improvement. Use alongside adobe_ai_compare_drawing to know when
        iterative corrections are converging, stalling, or done.

        Actions:
          record         — log a new convergence score (requires convergence_score)
          status         — view full history with improvement metrics
          plateau_check  — detect if convergence has stalled
          reset          — clear all progress data
        """
        action = params.action.lower().strip()
        handler = _ACTIONS.get(action)
        if handler is None:
            return json.dumps({
                "error": f"Unknown action '{action}'. Valid actions: {', '.join(sorted(_ACTIONS))}",
            })
        return handler(params)
