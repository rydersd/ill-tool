"""Context Intelligence — smart context compression and capability hinting.

This module reduces LLM context consumption by:
1. Compressing tool responses to essential information
2. Providing a pre-summarized "context card" the LLM can request instead of
   re-querying document state
3. Suggesting next actions based on current state (reducing trial-and-error)

The context card pattern: instead of the LLM holding 500 tokens of state
from prior tool calls, it makes one cheap call to adobe_context and gets
a 100-token summary with relevant capability hints.
"""

from __future__ import annotations

import json
from typing import Any

from adobe_mcp.state import session


def compress_response(app: str, action: str, raw_result: str, max_tokens: int = 100) -> str:
    """Compress a tool response to essential information + state summary.

    Instead of returning 200+ tokens of JSON, returns ~50 tokens:
    - Action confirmation (what happened)
    - Key metrics (count, name, size)
    - State summary suffix from session state

    Args:
        app: The Adobe app name
        action: What the tool did (e.g., "created rectangle", "applied filter")
        raw_result: The full tool output
        max_tokens: Approximate max token budget for the response
    """
    # Try to extract key data from JSON responses
    key_data = {}
    try:
        data = json.loads(raw_result)
        if isinstance(data, dict):
            # Extract only the most useful fields
            priority_keys = ["name", "count", "width", "height", "path", "format",
                           "layers", "result", "success", "error"]
            for k in priority_keys:
                if k in data:
                    key_data[k] = data[k]
    except (json.JSONDecodeError, TypeError):
        pass

    # Build compact response
    parts = [action]
    if key_data:
        summary_items = []
        for k, v in key_data.items():
            if isinstance(v, (list, dict)):
                summary_items.append(f"{k}={len(v)}")
            elif isinstance(v, str) and len(v) > 30:
                summary_items.append(f"{k}={v[:27]}...")
            else:
                summary_items.append(f"{k}={v}")
        if summary_items:
            parts.append("(" + ", ".join(summary_items[:5]) + ")")

    # Append session state
    state = session.app(app)
    if state.action_count > 0:
        parts.append(f"[{state.summary()}]")

    return " ".join(parts)


def context_card(app: str | None = None) -> str:
    """Generate a compact context card — everything the LLM needs to know in ~100 tokens.

    This replaces the pattern of re-querying state after every tool call.
    The LLM calls adobe_context once and gets:
    - Active documents and their state
    - Recent actions summary
    - Suggested next actions based on current state
    - Available capabilities relevant to the current context
    """
    lines = []

    if app:
        state = session.app(app)
        if state.action_count == 0:
            return f"No activity in {app} this session. Start with adobe_open_file or a new_document tool."
        lines.append(f"=== {app.upper()} CONTEXT ===")
        lines.append(state.summary())
        if state.layers:
            lines.append(f"Layers: {', '.join(state.layers[-10:])}")
        if state.custom:
            for k, v in list(state.custom.items())[:5]:
                lines.append(f"  {k}: {v}")

        # Suggest next actions based on state
        suggestions = _suggest_actions(app, state)
        if suggestions:
            lines.append("Suggested next:")
            for s in suggestions[:3]:
                lines.append(f"  -> {s}")
    else:
        # All apps summary
        active_apps = [(name, st) for name, st in session._apps.items() if st.action_count > 0]
        if not active_apps:
            return "No session activity. Use adobe_list_apps to check running apps, then open or create a document."

        lines.append("=== SESSION CONTEXT ===")
        for name, state in active_apps:
            lines.append(f"[{name}] {state.summary()}")

        lines.append(f"\nTotal: {len(session.history)} operations across {len(active_apps)} apps")

        # Suggest based on overall state
        if len(active_apps) > 1:
            lines.append("Tip: Use adobe_pipeline to chain operations across apps")
        if len(session.history) > 5:
            lines.append("Tip: Use adobe_workflow(action='save') to save this sequence for replay")

    return "\n".join(lines)


def _suggest_actions(app: str, state: Any) -> list[str]:
    """Suggest next actions based on current app state."""
    suggestions = []

    if not state.active_doc:
        suggestions.append(f"Open a file or create a new document")
        return suggestions

    if app == "illustrator":
        if not state.layers or len(state.layers) < 2:
            suggestions.append("Create layers to organize your artwork")
        if state.action_count > 3 and "export" not in state.last_action:
            suggestions.append("Export your work (adobe_ai_export)")
        if state.layers:
            suggestions.append("Use adobe_ai_inspect to review the scene graph")
        suggestions.append("Try adobe_jsx_snippets for advanced effects (gradients, grids, scatter)")

    elif app == "photoshop":
        if state.action_count > 0:
            suggestions.append("Use adobe_preview to see current state visually")
        suggestions.append("Try adobe_jsx_snippets for effects (halftone, vignette, duotone)")
        if state.layers and len(state.layers) > 3:
            suggestions.append("Consider grouping layers (adobe_ps_groups)")

    elif app == "aftereffects":
        suggestions.append("Add expressions for dynamic motion (adobe_ae_expression)")
        suggestions.append("Use ae_wiggle_expression snippet for organic movement")
        if state.action_count > 2:
            suggestions.append("Render a preview (adobe_ae_render)")

    elif app == "premierepro":
        suggestions.append("Add media to sequence (adobe_pr_media)")
        suggestions.append("Apply effects (adobe_pr_effects)")
        if state.action_count > 2:
            suggestions.append("Export sequence (adobe_pr_export)")

    return suggestions
