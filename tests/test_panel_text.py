"""Tests for the panel text annotation system.

Tests text formatting logic and rig data storage of panel texts.
All tests are pure Python — no JSX or Adobe required.
"""

import json

import pytest

from adobe_mcp.apps.illustrator.storyboard.panel_text import (
    format_panel_text,
    _format_dialogue,
    _format_action,
    _format_sfx,
    _format_note,
    _ensure_panel_texts,
)
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------


def test_format_dialogue_with_speaker():
    """Dialogue with speaker formats as 'SPEAKER: "text"'."""
    result = _format_dialogue("john", "Hello there")
    assert result == 'JOHN: "Hello there"'


def test_format_dialogue_without_speaker():
    """Dialogue without speaker wraps text in quotes only."""
    result = _format_dialogue(None, "Hello there")
    assert result == '"Hello there"'


def test_format_dialogue_speaker_uppercased():
    """Speaker name is always uppercased."""
    result = _format_dialogue("mary jane", "Hi")
    assert result.startswith("MARY JANE:")


def test_format_action():
    """Action text is returned as-is (italic styling is done in JSX)."""
    result = _format_action("Character walks to the door")
    assert result == "Character walks to the door"


def test_format_sfx_uppercase():
    """SFX text is converted to uppercase."""
    result = _format_sfx("boom crash")
    assert result == "BOOM CRASH"


def test_format_sfx_already_uppercase():
    """Already-uppercase SFX text stays unchanged."""
    result = _format_sfx("BANG")
    assert result == "BANG"


def test_format_note():
    """Note text is returned as-is (styling is done in JSX)."""
    result = _format_note("Remember to add background")
    assert result == "Remember to add background"


# ---------------------------------------------------------------------------
# format_panel_text dispatcher
# ---------------------------------------------------------------------------


def test_format_panel_text_dialogue():
    """Dispatcher routes dialogue type correctly."""
    result = format_panel_text("dialogue", "Hello", speaker="bob")
    assert result == 'BOB: "Hello"'


def test_format_panel_text_dialogue_no_speaker():
    """Dialogue without speaker through dispatcher."""
    result = format_panel_text("dialogue", "Hello")
    assert result == '"Hello"'


def test_format_panel_text_action():
    """Dispatcher routes action type correctly."""
    result = format_panel_text("action", "runs fast")
    assert result == "runs fast"


def test_format_panel_text_sfx():
    """Dispatcher routes sfx type correctly."""
    result = format_panel_text("sfx", "whoosh")
    assert result == "WHOOSH"


def test_format_panel_text_note():
    """Dispatcher routes note type correctly."""
    result = format_panel_text("note", "check lighting")
    assert result == "check lighting"


def test_format_panel_text_unknown_type():
    """Unknown text type returns text unchanged."""
    result = format_panel_text("unknown_type", "some text")
    assert result == "some text"


def test_format_panel_text_case_insensitive():
    """Text type matching is case-insensitive."""
    assert format_panel_text("DIALOGUE", "hi", speaker="a") == 'A: "hi"'
    assert format_panel_text("SFX", "bang") == "BANG"
    assert format_panel_text("Action", "walk") == "walk"


def test_format_panel_text_whitespace_stripped():
    """Whitespace around text type is stripped."""
    assert format_panel_text("  sfx  ", "pow") == "POW"


# ---------------------------------------------------------------------------
# _ensure_panel_texts
# ---------------------------------------------------------------------------


def test_ensure_panel_texts_creates_key():
    """Ensure creates panel_texts dict if missing."""
    rig = {"character_name": "test"}
    result = _ensure_panel_texts(rig)
    assert "panel_texts" in result
    assert result["panel_texts"] == {}


def test_ensure_panel_texts_preserves_existing():
    """Ensure does not overwrite existing panel_texts."""
    rig = {"panel_texts": {"1": [{"type": "dialogue", "raw_text": "hi"}]}}
    result = _ensure_panel_texts(rig)
    assert len(result["panel_texts"]["1"]) == 1


# ---------------------------------------------------------------------------
# Rig data storage
# ---------------------------------------------------------------------------


def test_store_panel_text_in_rig(tmp_rig_dir):
    """Panel text data roundtrips through rig save/load."""
    rig = _load_rig("storyboard")
    rig = _ensure_panel_texts(rig)

    formatted = format_panel_text("dialogue", "What happened?", speaker="hero")
    rig["panel_texts"]["1"] = [{
        "type": "dialogue",
        "raw_text": "What happened?",
        "speaker": "hero",
        "formatted": formatted,
    }]
    _save_rig("storyboard", rig)

    loaded = _load_rig("storyboard")
    texts = loaded["panel_texts"]["1"]
    assert len(texts) == 1
    assert texts[0]["type"] == "dialogue"
    assert texts[0]["formatted"] == 'HERO: "What happened?"'


def test_multiple_text_types_per_panel(tmp_rig_dir):
    """Multiple text types can coexist on one panel."""
    rig = _load_rig("storyboard")
    rig = _ensure_panel_texts(rig)

    entries = []
    items = [
        ("dialogue", "Run!", "hero"),
        ("action", "Character sprints away", None),
        ("sfx", "footsteps", None),
        ("note", "show urgency", None),
    ]
    for text_type, text, speaker in items:
        formatted = format_panel_text(text_type, text, speaker=speaker)
        entries.append({
            "type": text_type,
            "raw_text": text,
            "speaker": speaker,
            "formatted": formatted,
        })

    rig["panel_texts"]["3"] = entries
    _save_rig("storyboard", rig)

    loaded = _load_rig("storyboard")
    texts = loaded["panel_texts"]["3"]
    assert len(texts) == 4
    types = {t["type"] for t in texts}
    assert types == {"dialogue", "action", "sfx", "note"}


def test_replace_text_of_same_type(tmp_rig_dir):
    """Setting text of same type replaces the previous entry."""
    rig = _load_rig("storyboard")
    rig = _ensure_panel_texts(rig)

    # Initial dialogue
    rig["panel_texts"]["1"] = [{
        "type": "dialogue",
        "raw_text": "Hello",
        "speaker": "a",
        "formatted": format_panel_text("dialogue", "Hello", speaker="a"),
    }]
    _save_rig("storyboard", rig)

    # Replace dialogue (mimicking tool behavior)
    loaded = _load_rig("storyboard")
    existing = [t for t in loaded["panel_texts"]["1"] if t.get("type") != "dialogue"]
    new_formatted = format_panel_text("dialogue", "Goodbye", speaker="b")
    existing.append({
        "type": "dialogue",
        "raw_text": "Goodbye",
        "speaker": "b",
        "formatted": new_formatted,
    })
    loaded["panel_texts"]["1"] = existing
    _save_rig("storyboard", loaded)

    final = _load_rig("storyboard")
    dialogue_entries = [t for t in final["panel_texts"]["1"] if t["type"] == "dialogue"]
    assert len(dialogue_entries) == 1
    assert dialogue_entries[0]["formatted"] == 'B: "Goodbye"'


def test_clear_panel_text(tmp_rig_dir):
    """Clearing a panel removes all its text entries."""
    rig = _load_rig("storyboard")
    rig = _ensure_panel_texts(rig)
    rig["panel_texts"]["5"] = [{"type": "sfx", "raw_text": "BANG", "formatted": "BANG"}]
    _save_rig("storyboard", rig)

    loaded = _load_rig("storyboard")
    del loaded["panel_texts"]["5"]
    _save_rig("storyboard", loaded)

    final = _load_rig("storyboard")
    assert "5" not in final["panel_texts"]
