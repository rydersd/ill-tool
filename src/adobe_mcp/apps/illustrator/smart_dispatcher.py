"""Context-aware command dispatcher — suggests next tools based on document state.

Tracks tool usage patterns over time and learns named sequences so the
system can predict what the user wants to do next.  All state is persisted
to ~/.claude/memory/illustration/tool_usage.json.

Pure Python — no JSX or Adobe required.
"""

import json
import os
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class SmartDispatcherInput(BaseModel):
    """Control the smart command dispatcher."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="suggest",
        description="Action: suggest, log_use, get_stats, learn_pattern",
    )
    context: Optional[str] = Field(
        default=None,
        description="JSON document state for suggest action",
    )
    tool_name: Optional[str] = Field(
        default=None, description="Tool name for log_use"
    )
    pattern_name: Optional[str] = Field(
        default=None, description="Pattern name for learn_pattern"
    )
    pattern_sequence: Optional[str] = Field(
        default=None,
        description="JSON array of tool names for learn_pattern",
    )


# ---------------------------------------------------------------------------
# Context-based suggestion rules
# ---------------------------------------------------------------------------


CONTEXT_RULES: dict[str, list[str]] = {
    "has_reference_image": [
        "trace_workflow.setup",
        "analyze_reference",
        "character_wizard",
    ],
    "has_trace_layer": [
        "auto_trace",
        "draw_on_axis",
        "quick_pose",
    ],
    "has_rig": [
        "joint_rotate",
        "pose_snapshot",
        "smart_export",
    ],
    "has_storyboard": [
        "panel_composer",
        "batch_export_all",
        "animatic_preview",
    ],
    "empty_document": [
        "new_document",
        "trace_workflow.setup",
        "storyboard_template",
    ],
}


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


STORAGE_DIR = os.path.expanduser("~/.claude/memory/illustration")
STORAGE_FILE = os.path.join(STORAGE_DIR, "tool_usage.json")


def _load_storage(storage_path: Optional[str] = None) -> dict:
    """Load the tool usage storage from disk, or return an empty scaffold."""
    path = storage_path or STORAGE_FILE
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {
        "usage_log": [],
        "patterns": {},
    }


def _save_storage(data: dict, storage_path: Optional[str] = None) -> None:
    """Persist tool usage data to disk."""
    path = storage_path or STORAGE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Action implementations (all pure Python, testable)
# ---------------------------------------------------------------------------


def suggest(context_json: Optional[str]) -> dict:
    """Suggest next tools based on document context and learned patterns.

    Parses the context JSON for flags like has_reference_image, has_trace_layer,
    etc., then returns matching tool suggestions.  Also checks recent usage
    against learned patterns to suggest pattern continuations.
    """
    if not context_json:
        # No context — assume empty document
        context = {"empty_document": True}
    else:
        try:
            context = json.loads(context_json)
        except (json.JSONDecodeError, TypeError):
            return {"error": f"Invalid context JSON: {context_json}"}

    suggestions = []
    matched_rules = []

    # Match context flags to rules
    for flag, tools in CONTEXT_RULES.items():
        if context.get(flag):
            matched_rules.append(flag)
            for tool in tools:
                if tool not in suggestions:
                    suggestions.append(tool)

    # Check learned patterns against recent usage
    storage = _load_storage()
    pattern_suggestions = []
    if storage["usage_log"]:
        last_tool = storage["usage_log"][-1].get("tool_name", "")
        for pattern_name, sequence in storage.get("patterns", {}).items():
            if len(sequence) >= 2 and sequence[0] == last_tool:
                pattern_suggestions.append({
                    "pattern": pattern_name,
                    "next_tool": sequence[1],
                    "full_sequence": sequence,
                })

    return {
        "suggestions": suggestions,
        "matched_rules": matched_rules,
        "pattern_suggestions": pattern_suggestions,
        "context_flags": list(context.keys()),
    }


def log_use(tool_name: str, storage_path: Optional[str] = None) -> dict:
    """Record a tool invocation with timestamp."""
    if not tool_name:
        return {"error": "tool_name is required"}

    storage = _load_storage(storage_path)
    entry = {
        "tool_name": tool_name,
        "timestamp": time.time(),
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    storage["usage_log"].append(entry)
    _save_storage(storage, storage_path)

    return {
        "logged": True,
        "tool_name": tool_name,
        "total_entries": len(storage["usage_log"]),
    }


def get_stats(storage_path: Optional[str] = None) -> dict:
    """Return tool usage frequency, most/least used, and detected patterns."""
    storage = _load_storage(storage_path)
    log = storage["usage_log"]

    if not log:
        return {
            "total_invocations": 0,
            "unique_tools": 0,
            "frequency": {},
            "most_used": None,
            "least_used": None,
            "learned_patterns": list(storage.get("patterns", {}).keys()),
        }

    # Count frequency
    freq: dict[str, int] = {}
    for entry in log:
        name = entry.get("tool_name", "unknown")
        freq[name] = freq.get(name, 0) + 1

    # Sort by frequency (most used first)
    sorted_tools = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    most_used = sorted_tools[0] if sorted_tools else None
    least_used = sorted_tools[-1] if sorted_tools else None

    # Detect common sequences (pairs that appear 2+ times)
    detected_sequences = {}
    for i in range(len(log) - 1):
        pair = (log[i].get("tool_name", ""), log[i + 1].get("tool_name", ""))
        key = f"{pair[0]} -> {pair[1]}"
        detected_sequences[key] = detected_sequences.get(key, 0) + 1
    common_sequences = {k: v for k, v in detected_sequences.items() if v >= 2}

    return {
        "total_invocations": len(log),
        "unique_tools": len(freq),
        "frequency": dict(sorted_tools),
        "most_used": {"tool": most_used[0], "count": most_used[1]} if most_used else None,
        "least_used": {"tool": least_used[0], "count": least_used[1]} if least_used else None,
        "common_sequences": common_sequences,
        "learned_patterns": list(storage.get("patterns", {}).keys()),
    }


def learn_pattern(
    pattern_name: str,
    pattern_sequence_json: str,
    storage_path: Optional[str] = None,
) -> dict:
    """Teach a named tool sequence pattern.

    When the first tool in the sequence is used, the dispatcher will
    suggest the next tool in the pattern.
    """
    if not pattern_name:
        return {"error": "pattern_name is required"}
    if not pattern_sequence_json:
        return {"error": "pattern_sequence is required"}

    try:
        sequence = json.loads(pattern_sequence_json)
    except (json.JSONDecodeError, TypeError):
        return {"error": f"Invalid pattern_sequence JSON: {pattern_sequence_json}"}

    if not isinstance(sequence, list) or len(sequence) < 2:
        return {"error": "Pattern sequence must be a JSON array with at least 2 tool names"}

    storage = _load_storage(storage_path)
    storage["patterns"][pattern_name] = sequence
    _save_storage(storage, storage_path)

    return {
        "learned": True,
        "pattern_name": pattern_name,
        "sequence": sequence,
        "trigger_tool": sequence[0],
        "total_patterns": len(storage["patterns"]),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_smart_dispatcher tool."""

    @mcp.tool(
        name="adobe_ai_smart_dispatcher",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_smart_dispatcher(params: SmartDispatcherInput) -> str:
        """Context-aware command dispatcher — suggests tools based on document state,
        tracks usage patterns, and learns custom sequences.

        Actions:
        - suggest: Given document context, suggest next tools to use
        - log_use: Record a tool invocation for pattern tracking
        - get_stats: Return usage frequency and detected patterns
        - learn_pattern: Teach a named tool sequence
        """
        action = params.action.lower().strip()

        if action == "suggest":
            return json.dumps(suggest(params.context), indent=2)

        elif action == "log_use":
            if not params.tool_name:
                return json.dumps({"error": "tool_name required for log_use action"})
            return json.dumps(log_use(params.tool_name), indent=2)

        elif action == "get_stats":
            return json.dumps(get_stats(), indent=2)

        elif action == "learn_pattern":
            if not params.pattern_name:
                return json.dumps({"error": "pattern_name required for learn_pattern action"})
            if not params.pattern_sequence:
                return json.dumps({"error": "pattern_sequence required for learn_pattern action"})
            return json.dumps(
                learn_pattern(params.pattern_name, params.pattern_sequence),
                indent=2,
            )

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["suggest", "log_use", "get_stats", "learn_pattern"],
            })
