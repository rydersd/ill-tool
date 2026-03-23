"""Shared rig file I/O for character rigging tools.

All character data (joints, bones, bindings, poses) is stored in a JSON
rig file at /tmp/ai_rigs/{character_name}.json so it persists across
tool calls and sessions.
"""

import json
import os


def _rig_path(character_name: str) -> str:
    """Return the filesystem path for a character's rig file."""
    return f"/tmp/ai_rigs/{character_name}.json"


def _load_rig(character_name: str) -> dict:
    """Load a character rig from disk, or return an empty scaffold."""
    path = _rig_path(character_name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "character_name": character_name,
        "joints": {},
        "bones": [],
        "bindings": {},
        "body_part_labels": {},
        "poses": {},
        "landmarks": {},
        "axes": {},
        "transform": None,
        "image_source": None,
        "image_size": None,
        "view_angle": 0,
        "light_direction": None,
    }


def _save_rig(character_name: str, rig: dict) -> None:
    """Persist a character rig to disk, creating directories as needed."""
    path = _rig_path(character_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rig, f, indent=2)
