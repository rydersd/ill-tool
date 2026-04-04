"""Tests for character expression deltas.

Tests pure Python expression preset lookup and delta application.
"""

import pytest

from adobe_mcp.apps.illustrator.character.character_expression import (
    get_expression_deltas,
    apply_expression_deltas,
    EXPRESSION_PRESETS,
)


# ---------------------------------------------------------------------------
# Expression preset lookup
# ---------------------------------------------------------------------------


def test_all_presets_exist():
    """All six standard expressions should be available."""
    expected = {"neutral", "angry", "surprised", "sad", "happy", "determined"}
    assert set(EXPRESSION_PRESETS.keys()) == expected


def test_neutral_has_zero_deltas():
    """Neutral expression should have all-zero deltas."""
    deltas = get_expression_deltas("neutral")
    assert deltas is not None
    for lm, delta in deltas.items():
        assert delta[0] == 0.0
        assert delta[1] == 0.0


def test_angry_eyebrows_down():
    """Angry expression should move eyebrows downward (negative Y)."""
    deltas = get_expression_deltas("angry")
    assert deltas is not None
    assert deltas["eyebrow_l"][1] < 0
    assert deltas["eyebrow_r"][1] < 0


def test_surprised_eyebrows_up():
    """Surprised expression should raise eyebrows (positive Y)."""
    deltas = get_expression_deltas("surprised")
    assert deltas is not None
    assert deltas["eyebrow_l"][1] > 0
    assert deltas["eyebrow_r"][1] > 0


def test_unknown_expression_returns_none():
    """Requesting a non-existent expression returns None."""
    assert get_expression_deltas("confused") is None


# ---------------------------------------------------------------------------
# Delta application
# ---------------------------------------------------------------------------


def test_apply_deltas_moves_landmarks():
    """Applying deltas should offset landmark positions."""
    landmarks = {
        "eyebrow_l": {"ai": [90, 480]},
        "eyebrow_r": {"ai": [110, 480]},
        "eye_l": {"ai": [90, 470]},
        "eye_r": {"ai": [110, 470]},
        "mouth_center": {"ai": [100, 440]},
    }
    deltas = {
        "eyebrow_l": [0.0, 6.0],
        "eyebrow_r": [0.0, 6.0],
        "eye_l": [0.0, 0.0],
        "eye_r": [0.0, 0.0],
        "mouth_center": [0.0, -4.0],
    }
    result = apply_expression_deltas(landmarks, deltas, scale=1.0)
    # Eyebrow_l Y should have increased by 6
    assert result["landmarks"]["eyebrow_l"]["ai"][1] == pytest.approx(486.0)
    # Mouth should have decreased by 4
    assert result["landmarks"]["mouth_center"]["ai"][1] == pytest.approx(436.0)
    # Eye should be unchanged
    assert result["landmarks"]["eye_l"]["ai"][1] == pytest.approx(470.0)
