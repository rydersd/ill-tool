"""Revision tracking for storyboard panels.

Saves panel snapshots, tracks versions, compares old vs new, restores
previous versions, and marks versions as approved.

Storage: /tmp/ai_revisions/{character_name}/panel_{N}/v{version}.png + metadata JSON
"""

import json
import os
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiRevisionTrackerInput(BaseModel):
    """Save panel snapshots, track versions, compare, restore, approve."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: snapshot, list_versions, compare, restore, approve"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    panel_number: int = Field(default=1, description="Target panel number", ge=1)
    version: Optional[int] = Field(
        default=None, description="Version number (for compare, restore, approve)"
    )
    compare_version: Optional[int] = Field(
        default=None, description="Second version for comparison"
    )
    note: Optional[str] = Field(
        default=None, description="Revision note / comment"
    )


# ---------------------------------------------------------------------------
# Revision storage helpers
# ---------------------------------------------------------------------------

REVISIONS_BASE = "/tmp/ai_revisions"


def _revisions_dir(character_name: str, panel_number: int) -> str:
    """Return the directory for a panel's revisions."""
    return os.path.join(REVISIONS_BASE, character_name, f"panel_{panel_number}")


def _metadata_path(character_name: str, panel_number: int) -> str:
    """Return the path to the metadata JSON for a panel."""
    return os.path.join(_revisions_dir(character_name, panel_number), "metadata.json")


def _load_metadata(character_name: str, panel_number: int) -> dict:
    """Load metadata for a panel's revisions, or return empty scaffold."""
    path = _metadata_path(character_name, panel_number)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "character_name": character_name,
        "panel_number": panel_number,
        "versions": [],
        "current_version": 0,
        "approved_version": None,
    }


def _save_metadata(character_name: str, panel_number: int, metadata: dict) -> None:
    """Save metadata to disk."""
    rev_dir = _revisions_dir(character_name, panel_number)
    os.makedirs(rev_dir, exist_ok=True)
    path = _metadata_path(character_name, panel_number)
    with open(path, "w") as f:
        json.dump(metadata, f, indent=2)


def _next_version(metadata: dict) -> int:
    """Get the next version number."""
    versions = metadata.get("versions", [])
    if not versions:
        return 1
    return max(v.get("version", 0) for v in versions) + 1


def _snapshot_path(character_name: str, panel_number: int, version: int) -> str:
    """Return the path for a version's snapshot PNG."""
    return os.path.join(
        _revisions_dir(character_name, panel_number), f"v{version}.png"
    )


def _ensure_revisions(rig: dict) -> dict:
    """Ensure the rig has a revisions tracking structure."""
    if "revisions" not in rig:
        rig["revisions"] = {}
    return rig


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_revision_tracker tool."""

    @mcp.tool(
        name="adobe_ai_revision_tracker",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_revision_tracker(params: AiRevisionTrackerInput) -> str:
        """Save panel snapshots, track versions, compare old vs new.

        Actions:
        - snapshot: export current panel as PNG to versioned folder
        - list_versions: show all versions with timestamps
        - compare: return side-by-side info for two versions
        - restore: set a previous version as current
        - approve: mark a version as approved
        """
        action = params.action.lower().strip()
        char = params.character_name
        panel = params.panel_number

        meta = _load_metadata(char, panel)

        # ── snapshot ─────────────────────────────────────────────────
        if action == "snapshot":
            version = _next_version(meta)
            snap_path = _snapshot_path(char, panel, version)
            os.makedirs(os.path.dirname(snap_path), exist_ok=True)

            # Create a placeholder snapshot file (actual export would use JSX)
            # In a real workflow, JSX exports the artboard; here we record the path
            with open(snap_path, "wb") as f:
                f.write(b"PNG_PLACEHOLDER")

            version_entry = {
                "version": version,
                "path": snap_path,
                "timestamp": time.time(),
                "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note": params.note or "",
                "approved": False,
            }
            meta["versions"].append(version_entry)
            meta["current_version"] = version
            _save_metadata(char, panel, meta)

            # Track in rig
            rig = _load_rig(char)
            rig = _ensure_revisions(rig)
            panel_key = str(panel)
            rig["revisions"][panel_key] = {
                "current_version": version,
                "total_versions": len(meta["versions"]),
            }
            _save_rig(char, rig)

            return json.dumps({
                "action": "snapshot",
                "panel_number": panel,
                "version": version,
                "path": snap_path,
                "total_versions": len(meta["versions"]),
            }, indent=2)

        # ── list_versions ────────────────────────────────────────────
        elif action == "list_versions":
            return json.dumps({
                "action": "list_versions",
                "panel_number": panel,
                "current_version": meta["current_version"],
                "approved_version": meta.get("approved_version"),
                "versions": meta["versions"],
                "total": len(meta["versions"]),
            }, indent=2)

        # ── compare ──────────────────────────────────────────────────
        elif action == "compare":
            v_a = params.version
            v_b = params.compare_version

            if v_a is None or v_b is None:
                return json.dumps({
                    "error": "compare requires both 'version' and 'compare_version'",
                })

            entry_a = None
            entry_b = None
            for v in meta["versions"]:
                if v["version"] == v_a:
                    entry_a = v
                if v["version"] == v_b:
                    entry_b = v

            if entry_a is None:
                return json.dumps({"error": f"Version {v_a} not found"})
            if entry_b is None:
                return json.dumps({"error": f"Version {v_b} not found"})

            return json.dumps({
                "action": "compare",
                "panel_number": panel,
                "version_a": entry_a,
                "version_b": entry_b,
                "time_delta_seconds": round(
                    abs(entry_b["timestamp"] - entry_a["timestamp"]), 1
                ),
            }, indent=2)

        # ── restore ──────────────────────────────────────────────────
        elif action == "restore":
            if params.version is None:
                return json.dumps({"error": "restore requires 'version'"})

            target = None
            for v in meta["versions"]:
                if v["version"] == params.version:
                    target = v
                    break

            if target is None:
                available = [v["version"] for v in meta["versions"]]
                return json.dumps({
                    "error": f"Version {params.version} not found",
                    "available_versions": available,
                })

            meta["current_version"] = params.version
            _save_metadata(char, panel, meta)

            return json.dumps({
                "action": "restore",
                "panel_number": panel,
                "restored_version": params.version,
                "path": target["path"],
            }, indent=2)

        # ── approve ──────────────────────────────────────────────────
        elif action == "approve":
            version_to_approve = params.version or meta["current_version"]

            target = None
            for v in meta["versions"]:
                if v["version"] == version_to_approve:
                    target = v
                    break

            if target is None:
                return json.dumps({
                    "error": f"Version {version_to_approve} not found",
                })

            # Mark this version as approved, unmark others
            for v in meta["versions"]:
                v["approved"] = (v["version"] == version_to_approve)

            meta["approved_version"] = version_to_approve
            _save_metadata(char, panel, meta)

            return json.dumps({
                "action": "approve",
                "panel_number": panel,
                "approved_version": version_to_approve,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["snapshot", "list_versions", "compare", "restore", "approve"],
            })
