"""Ingest CEP panel interaction logs for correction learning.

Reads JSONL files from ~/Library/Application Support/illtool/interactions/
and feeds reclassification events into the correction_learning system.
"""

import json
from pathlib import Path

from adobe_mcp.apps.illustrator.models import AiInteractionIngestInput


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, skipping malformed lines."""
    entries = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return entries


def _compute_reclassification_stats(entries: list[dict]) -> dict:
    """Compute statistics from reclassification events."""
    reclassifications = [e for e in entries if e.get("action") == "reclassify"]
    if not reclassifications:
        return {"count": 0, "transitions": {}}

    transitions: dict[str, int] = {}
    for entry in reclassifications:
        before = (entry.get("before") or {}).get("shape", "unknown")
        after = (entry.get("after") or {}).get("shape", "unknown")
        key = f"{before} -> {after}"
        transitions[key] = transitions.get(key, 0) + 1

    return {
        "count": len(reclassifications),
        "transitions": transitions,
    }


def register(mcp):
    """Register the adobe_ai_interaction_ingest tool."""

    @mcp.tool(
        name="adobe_ai_interaction_ingest",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_interaction_ingest(params: AiInteractionIngestInput) -> str:
        """Read and analyze CEP panel interaction logs.

        Reads JSONL files from /tmp/illtool_interactions/, computes
        reclassification statistics, and returns a summary.
        """
        log_dir = Path(params.log_dir).expanduser()
        if not log_dir.exists():
            return json.dumps({"error": "Log directory not found", "path": str(log_dir)})

        # Find matching JSONL files
        pattern = f"{params.panel_name}_*.jsonl" if params.panel_name else "*.jsonl"
        files = sorted(log_dir.glob(pattern))

        if not files:
            return json.dumps({"files_found": 0, "note": "No interaction logs found"})

        # Read all entries
        all_entries: list[dict] = []
        for f in files:
            all_entries.extend(_read_jsonl(f))

        # Filter by date range if specified
        if params.since_date:
            all_entries = [
                e for e in all_entries
                if e.get("timestamp", "") >= params.since_date
            ]

        # Compute statistics
        by_action: dict[str, int] = {}
        for entry in all_entries:
            action = entry.get("action", "unknown")
            by_action[action] = by_action.get(action, 0) + 1

        reclassification_stats = _compute_reclassification_stats(all_entries)

        by_panel: dict[str, int] = {}
        for entry in all_entries:
            panel = entry.get("panel", "unknown")
            by_panel[panel] = by_panel.get(panel, 0) + 1

        return json.dumps({
            "files_read": len(files),
            "total_events": len(all_entries),
            "by_action": by_action,
            "by_panel": by_panel,
            "reclassification_stats": reclassification_stats,
        }, indent=2)
