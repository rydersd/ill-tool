"""Test the rig persistence layer (save/load character rigs)."""
import json

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


REQUIRED_KEYS = {"character_name", "joints", "bones", "bindings", "body_part_labels", "poses"}


def test_default_rig(tmp_rig_dir):
    """Loading a non-existent character returns a scaffold with all required keys."""
    rig = _load_rig("test_char")
    assert isinstance(rig, dict)
    assert REQUIRED_KEYS.issubset(rig.keys()), f"Missing keys: {REQUIRED_KEYS - rig.keys()}"
    assert rig["character_name"] == "test_char"
    assert rig["joints"] == {}
    assert rig["bones"] == []
    assert rig["bindings"] == {}
    assert rig["body_part_labels"] == {}
    assert rig["poses"] == {}


def test_save_load_roundtrip(tmp_rig_dir):
    """Save a rig with joints, load it back, verify joints match."""
    rig = _load_rig("hero")
    rig["joints"] = {
        "shoulder_l": {"x": 100, "y": -200},
        "elbow_l": {"x": 120, "y": -280},
    }
    _save_rig("hero", rig)

    loaded = _load_rig("hero")
    assert loaded["joints"] == rig["joints"]
    assert loaded["character_name"] == "hero"


def test_overwrite(tmp_rig_dir):
    """Saving twice overwrites: latest data is what gets loaded."""
    rig = _load_rig("bot")
    rig["joints"] = {"head": {"x": 50, "y": -50}}
    _save_rig("bot", rig)

    # Modify and save again
    rig["joints"]["head"] = {"x": 75, "y": -75}
    rig["joints"]["neck"] = {"x": 75, "y": -100}
    _save_rig("bot", rig)

    loaded = _load_rig("bot")
    assert loaded["joints"]["head"] == {"x": 75, "y": -75}
    assert "neck" in loaded["joints"]


def test_separate_characters(tmp_rig_dir):
    """Two characters saved independently remain isolated."""
    rig_a = _load_rig("char_a")
    rig_a["joints"] = {"head": {"x": 10, "y": -10}}
    _save_rig("char_a", rig_a)

    rig_b = _load_rig("char_b")
    rig_b["joints"] = {"tail": {"x": 200, "y": -300}}
    _save_rig("char_b", rig_b)

    loaded_a = _load_rig("char_a")
    loaded_b = _load_rig("char_b")

    assert "head" in loaded_a["joints"]
    assert "tail" not in loaded_a["joints"]

    assert "tail" in loaded_b["joints"]
    assert "head" not in loaded_b["joints"]


def test_file_written_to_disk(tmp_rig_dir):
    """Verify the JSON file actually exists on disk after save."""
    rig = _load_rig("persisted")
    rig["bones"] = [{"from": "shoulder_l", "to": "elbow_l"}]
    _save_rig("persisted", rig)

    # Check file exists and is valid JSON
    rig_file = tmp_rig_dir / "persisted.json"
    assert rig_file.exists()
    data = json.loads(rig_file.read_text())
    assert data["bones"] == [{"from": "shoulder_l", "to": "elbow_l"}]
