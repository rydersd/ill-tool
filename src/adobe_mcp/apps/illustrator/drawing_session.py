"""Interactive draw session manager — tracks state across the draw-preview-adjust loop.

Manages session lifecycle: start, iterate on shapes, track convergence,
detect plateaus, and end with a summary.

Pure Python — no JSX or Adobe required.
Storage: /tmp/ai_draw_sessions/{session_id}.json
"""

import json
import os
import time
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiDrawingSessionInput(BaseModel):
    """Manage an interactive drawing session."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: start, next_shape, record, status, end",
    )
    character_name: str = Field(
        default="character", description="Character identifier"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID (returned by start)",
    )
    reference_path: Optional[str] = Field(
        default=None,
        description="Path to reference image (for start)",
    )
    convergence_score: Optional[float] = Field(
        default=None,
        description="Convergence score for current iteration (0-1)",
        ge=0, le=1,
    )
    shapes: Optional[list[dict]] = Field(
        default=None,
        description="Shape hierarchy for the session (for start)",
    )
    plateau_threshold: float = Field(
        default=0.02,
        description="Minimum improvement to avoid plateau detection",
        ge=0, le=1,
    )
    plateau_count: int = Field(
        default=3,
        description="Iterations with < threshold improvement to trigger plateau",
        ge=2, le=10,
    )


# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------


SESSION_DIR = "/tmp/ai_draw_sessions"


def _session_path(session_id: str) -> str:
    """Get the file path for a session."""
    return os.path.join(SESSION_DIR, f"{session_id}.json")


def _load_session(session_id: str) -> Optional[dict]:
    """Load a session from disk."""
    path = _session_path(session_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _save_session(session_id: str, data: dict) -> None:
    """Save a session to disk."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    path = _session_path(session_id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Default shape hierarchy (largest/outermost first)
# ---------------------------------------------------------------------------

DEFAULT_SHAPES = [
    {"name": "body_mass", "axis": "vertical", "priority": 1, "suggested_points": 6},
    {"name": "torso", "axis": "vertical", "priority": 2, "suggested_points": 8},
    {"name": "head", "axis": "vertical", "priority": 3, "suggested_points": 8},
    {"name": "arm_left", "axis": "horizontal", "priority": 4, "suggested_points": 6},
    {"name": "arm_right", "axis": "horizontal", "priority": 5, "suggested_points": 6},
    {"name": "leg_left", "axis": "vertical", "priority": 6, "suggested_points": 6},
    {"name": "leg_right", "axis": "vertical", "priority": 7, "suggested_points": 6},
    {"name": "hand_left", "axis": "any", "priority": 8, "suggested_points": 10},
    {"name": "hand_right", "axis": "any", "priority": 9, "suggested_points": 10},
    {"name": "foot_left", "axis": "horizontal", "priority": 10, "suggested_points": 6},
    {"name": "foot_right", "axis": "horizontal", "priority": 11, "suggested_points": 6},
]


# ---------------------------------------------------------------------------
# Session lifecycle functions
# ---------------------------------------------------------------------------


def start_session(
    character_name: str,
    reference_path: Optional[str] = None,
    shapes: Optional[list[dict]] = None,
) -> dict:
    """Initialize a new drawing session.

    Returns session state with ID, shape queue, and initial status.
    """
    session_id = str(uuid.uuid4())[:12]
    shape_list = shapes if shapes else list(DEFAULT_SHAPES)

    # Sort by priority (lowest first = draw first = largest/outermost)
    shape_list.sort(key=lambda s: s.get("priority", 99))

    session = {
        "session_id": session_id,
        "character_name": character_name,
        "reference_path": reference_path,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "shapes": shape_list,
        "shapes_completed": [],
        "current_shape_index": 0,
        "iteration_count": 0,
        "convergence_history": {},
        "status": "active",
    }

    _save_session(session_id, session)

    return {
        "session_id": session_id,
        "character_name": character_name,
        "shape_count": len(shape_list),
        "first_shape": shape_list[0]["name"] if shape_list else None,
        "status": "active",
    }


def next_shape(session_id: str) -> dict:
    """Determine the next shape to draw based on the hierarchy.

    Returns the shape spec or a completion message if all shapes are done.
    """
    session = _load_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    idx = session.get("current_shape_index", 0)
    shapes = session.get("shapes", [])

    if idx >= len(shapes):
        return {
            "session_id": session_id,
            "complete": True,
            "shapes_completed": len(session.get("shapes_completed", [])),
            "message": "All shapes have been drawn.",
        }

    shape = shapes[idx]
    return {
        "session_id": session_id,
        "complete": False,
        "shape_index": idx,
        "shape": shape,
        "remaining": len(shapes) - idx,
    }


def record_iteration(
    session_id: str,
    convergence_score: float,
    plateau_threshold: float = 0.02,
    plateau_count: int = 3,
) -> dict:
    """Record a convergence score for the current shape iteration.

    Tracks history and detects plateau (N iterations with < threshold improvement).

    Returns iteration result with plateau warning if detected.
    """
    session = _load_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    idx = session.get("current_shape_index", 0)
    shapes = session.get("shapes", [])
    if idx >= len(shapes):
        return {"error": "No active shape to record against"}

    shape_name = shapes[idx]["name"]
    session["iteration_count"] = session.get("iteration_count", 0) + 1

    # Initialize convergence history for this shape
    if shape_name not in session["convergence_history"]:
        session["convergence_history"][shape_name] = []

    history = session["convergence_history"][shape_name]
    history.append({
        "iteration": len(history) + 1,
        "score": convergence_score,
        "timestamp": time.strftime("%H:%M:%S"),
    })

    # Detect plateau: last N iterations all improved less than threshold
    plateau_warning = False
    if len(history) >= plateau_count:
        recent = history[-plateau_count:]
        improvements = []
        for j in range(1, len(recent)):
            improvement = recent[j]["score"] - recent[j - 1]["score"]
            improvements.append(improvement)
        if all(imp < plateau_threshold for imp in improvements):
            plateau_warning = True

    _save_session(session_id, session)

    result = {
        "session_id": session_id,
        "shape": shape_name,
        "iteration": len(history),
        "score": convergence_score,
        "plateau_warning": plateau_warning,
    }

    if plateau_warning:
        result["suggestion"] = (
            f"Convergence has plateaued for '{shape_name}' "
            f"(< {plateau_threshold * 100:.0f}% improvement over last "
            f"{plateau_count} iterations). Consider moving to the next shape."
        )

    return result


def advance_shape(session_id: str) -> dict:
    """Move to the next shape in the queue, marking current as complete."""
    session = _load_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    idx = session.get("current_shape_index", 0)
    shapes = session.get("shapes", [])

    if idx < len(shapes):
        completed_name = shapes[idx]["name"]
        session["shapes_completed"].append(completed_name)
        session["current_shape_index"] = idx + 1

    _save_session(session_id, session)

    return next_shape(session_id)


def session_status(session_id: str) -> dict:
    """Get the current status of a drawing session.

    Returns shapes done, current shape, convergence history, and plateau warnings.
    """
    session = _load_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    idx = session.get("current_shape_index", 0)
    shapes = session.get("shapes", [])
    current_shape = shapes[idx]["name"] if idx < len(shapes) else None

    # Current shape's convergence history
    current_history = []
    if current_shape and current_shape in session["convergence_history"]:
        current_history = session["convergence_history"][current_shape]

    return {
        "session_id": session_id,
        "character_name": session.get("character_name", ""),
        "status": session.get("status", "active"),
        "started_at": session.get("started_at", ""),
        "shapes_total": len(shapes),
        "shapes_completed": session.get("shapes_completed", []),
        "shapes_completed_count": len(session.get("shapes_completed", [])),
        "current_shape": current_shape,
        "current_shape_index": idx,
        "total_iterations": session.get("iteration_count", 0),
        "current_convergence_history": current_history,
    }


def end_session(session_id: str) -> dict:
    """End a drawing session, save final state, and log learnings.

    Returns a summary of the session.
    """
    session = _load_session(session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    session["status"] = "completed"
    session["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Compute per-shape summary
    shape_summaries = []
    for shape in session.get("shapes", []):
        name = shape["name"]
        history = session["convergence_history"].get(name, [])
        completed = name in session.get("shapes_completed", [])
        best_score = max((h["score"] for h in history), default=0)
        shape_summaries.append({
            "name": name,
            "completed": completed,
            "iterations": len(history),
            "best_score": best_score,
        })

    # Learnings: shapes with most iterations might need more practice
    learnings = []
    for summary in sorted(shape_summaries, key=lambda s: s["iterations"], reverse=True):
        if summary["iterations"] > 5:
            learnings.append(
                f"'{summary['name']}' took {summary['iterations']} iterations — "
                f"consider practicing this shape separately."
            )

    session["learnings"] = learnings
    _save_session(session_id, session)

    return {
        "session_id": session_id,
        "status": "completed",
        "started_at": session.get("started_at", ""),
        "ended_at": session["ended_at"],
        "total_iterations": session.get("iteration_count", 0),
        "shapes_completed": session.get("shapes_completed", []),
        "shape_summaries": shape_summaries,
        "learnings": learnings,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_drawing_session tool."""

    @mcp.tool(
        name="adobe_ai_drawing_session",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_drawing_session(params: AiDrawingSessionInput) -> str:
        """Manage an interactive drawing session.

        Actions:
        - start: begin a new session
        - next_shape: get the next shape to draw
        - record: record a convergence score
        - status: get session status
        - end: end the session with summary
        """
        action = params.action.lower().strip()

        if action == "start":
            result = start_session(
                character_name=params.character_name,
                reference_path=params.reference_path,
                shapes=params.shapes,
            )
            return json.dumps(result, indent=2)

        elif action == "next_shape":
            if not params.session_id:
                return json.dumps({"error": "session_id required"})
            result = next_shape(params.session_id)
            return json.dumps(result, indent=2)

        elif action == "record":
            if not params.session_id:
                return json.dumps({"error": "session_id required"})
            if params.convergence_score is None:
                return json.dumps({"error": "convergence_score required"})
            result = record_iteration(
                session_id=params.session_id,
                convergence_score=params.convergence_score,
                plateau_threshold=params.plateau_threshold,
                plateau_count=params.plateau_count,
            )
            return json.dumps(result, indent=2)

        elif action == "advance":
            if not params.session_id:
                return json.dumps({"error": "session_id required"})
            result = advance_shape(params.session_id)
            return json.dumps(result, indent=2)

        elif action == "status":
            if not params.session_id:
                return json.dumps({"error": "session_id required"})
            result = session_status(params.session_id)
            return json.dumps(result, indent=2)

        elif action == "end":
            if not params.session_id:
                return json.dumps({"error": "session_id required"})
            result = end_session(params.session_id)
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["start", "next_shape", "record", "advance", "status", "end"],
            })
