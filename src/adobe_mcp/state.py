"""Server-side session state — persists document context between tool calls.

Instead of each tool returning a full state dump (consuming ~500 tokens per call),
tools update the session state and return a compact confirmation. The LLM can query
state explicitly via adobe_session_state when it needs full context.

This dramatically reduces per-call token consumption: a 7-step VOID pipeline goes
from ~3,500 tokens of accumulated state to ~700 tokens of compact confirmations.

Architecture:
    - One global SessionState instance per MCP server process
    - Each app gets its own namespace within the state (ps, ai, ae, etc.)
    - Tools call state.record() after successful execution
    - State provides summary() for compact tool responses
    - State provides full_state() for explicit state queries
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    """Per-app document state tracked across tool calls."""
    active_doc: str | None = None
    doc_path: str | None = None
    doc_size: tuple[float, float] | None = None
    color_mode: str | None = None
    layers: list[str] = field(default_factory=list)
    selections: list[str] = field(default_factory=list)
    artboards: list[str] = field(default_factory=list)
    last_action: str = ""
    last_action_time: float = 0.0
    action_count: int = 0
    custom: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """One-line compact summary for tool response suffixes."""
        parts = []
        if self.active_doc:
            parts.append(f"doc={self.active_doc}")
        if self.doc_size:
            parts.append(f"size={self.doc_size[0]:.0f}x{self.doc_size[1]:.0f}")
        if self.layers:
            parts.append(f"layers={len(self.layers)}")
        if self.artboards:
            parts.append(f"artboards={len(self.artboards)}")
        if self.last_action:
            parts.append(f"last={self.last_action}")
        parts.append(f"ops={self.action_count}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Full serializable state for explicit queries."""
        return {
            "active_doc": self.active_doc,
            "doc_path": self.doc_path,
            "doc_size": list(self.doc_size) if self.doc_size else None,
            "color_mode": self.color_mode,
            "layers": self.layers,
            "selections": self.selections,
            "artboards": self.artboards,
            "last_action": self.last_action,
            "action_count": self.action_count,
            "custom": self.custom,
        }


class SessionState:
    """Global session state manager. One per MCP server process.

    Usage from tools:
        from adobe_mcp.state import session

        # After a successful tool call:
        session.record("illustrator", "created rectangle 'bg'",
                        layers=["bg", "fg"], doc="poster.ai")

        # Append to tool response:
        return f"Rectangle created. [{session.app('illustrator').summary()}]"

        # Full state query:
        return session.full_state()
    """

    def __init__(self) -> None:
        self._apps: dict[str, AppState] = {}
        self._history: list[dict[str, Any]] = []
        self._start_time: float = time.time()

    def app(self, app_name: str) -> AppState:
        """Get or create the state namespace for an app."""
        if app_name not in self._apps:
            self._apps[app_name] = AppState()
        return self._apps[app_name]

    def record(
        self,
        app_name: str,
        action: str,
        *,
        doc: str | None = None,
        doc_path: str | None = None,
        doc_size: tuple[float, float] | None = None,
        color_mode: str | None = None,
        layers: list[str] | None = None,
        add_layer: str | None = None,
        remove_layer: str | None = None,
        artboards: list[str] | None = None,
        selections: list[str] | None = None,
        custom: dict[str, Any] | None = None,
    ) -> AppState:
        """Record a tool action and update app state.

        Only updates fields that are explicitly passed (non-None).
        Returns the updated AppState for chaining.
        """
        state = self.app(app_name)
        state.last_action = action
        state.last_action_time = time.time()
        state.action_count += 1

        if doc is not None:
            state.active_doc = doc
        if doc_path is not None:
            state.doc_path = doc_path
        if doc_size is not None:
            state.doc_size = doc_size
        if color_mode is not None:
            state.color_mode = color_mode
        if layers is not None:
            state.layers = layers
        if add_layer is not None and add_layer not in state.layers:
            state.layers.append(add_layer)
        if remove_layer is not None and remove_layer in state.layers:
            state.layers.remove(remove_layer)
        if artboards is not None:
            state.artboards = artboards
        if selections is not None:
            state.selections = selections
        if custom is not None:
            state.custom.update(custom)

        # Record in history for batch/workflow reporting
        self._history.append({
            "app": app_name,
            "action": action,
            "time": state.last_action_time,
        })

        return state

    def summary(self) -> str:
        """Compact multi-app summary for cross-app state queries."""
        if not self._apps:
            return "No session state yet — no tools have been executed."
        parts = []
        for app_name, state in self._apps.items():
            if state.action_count > 0:
                parts.append(f"[{app_name}] {state.summary()}")
        elapsed = time.time() - self._start_time
        parts.append(f"Session: {len(self._history)} total ops, {elapsed:.0f}s elapsed")
        return "\n".join(parts)

    def full_state(self) -> str:
        """Full JSON state for explicit queries — all apps, all details."""
        data = {
            "apps": {name: st.to_dict() for name, st in self._apps.items() if st.action_count > 0},
            "history_count": len(self._history),
            "recent_history": self._history[-10:],  # Last 10 actions
            "session_elapsed_seconds": round(time.time() - self._start_time, 1),
        }
        return json.dumps(data, indent=2)

    def reset(self, app_name: str | None = None) -> None:
        """Reset state for a specific app, or all apps if None."""
        if app_name:
            if app_name in self._apps:
                self._apps[app_name] = AppState()
        else:
            self._apps.clear()
            self._history.clear()
            self._start_time = time.time()

    @property
    def history(self) -> list[dict[str, Any]]:
        """Read-only access to action history."""
        return list(self._history)


# ── Global singleton ──────────────────────────────────────────────────
# One state instance per MCP server process. Imported by tools:
#   from adobe_mcp.state import session
session = SessionState()
