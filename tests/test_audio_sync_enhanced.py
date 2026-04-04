"""Tests for the enhanced audio sync tool.

Verifies silence detection on synthetic audio (sine wave + silence gaps).
All tests are pure Python using numpy to generate test signals.
"""

import math
import os
import struct
import tempfile
import wave

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.production.audio_sync_enhanced import (
    compute_rms_envelope,
    rms_to_db,
    detect_silence_gaps,
    detect_speech_segments,
    suggest_cut_points,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic audio generation
# ---------------------------------------------------------------------------


def _generate_wav(path, sample_rate, duration_s, segments):
    """Generate a WAV file with alternating tone/silence segments.

    segments: list of (duration_s, is_tone) tuples.
    is_tone=True → 440Hz sine at ~0.5 amplitude
    is_tone=False → silence (zeros)
    """
    samples = []
    for seg_dur, is_tone in segments:
        n_samples = int(sample_rate * seg_dur)
        if is_tone:
            t = np.linspace(0, seg_dur, n_samples, endpoint=False)
            signal = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        else:
            signal = np.zeros(n_samples, dtype=np.int16)
        samples.append(signal)

    all_samples = np.concatenate(samples)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(all_samples.tobytes())

    return path


@pytest.fixture
def tone_silence_wav(tmp_path):
    """WAV with: 1s tone, 1s silence, 1s tone, 0.5s silence, 0.5s tone."""
    path = str(tmp_path / "test_audio.wav")
    segments = [
        (1.0, True),   # 0.0 - 1.0: tone
        (1.0, False),  # 1.0 - 2.0: silence
        (1.0, True),   # 2.0 - 3.0: tone
        (0.5, False),  # 3.0 - 3.5: silence
        (0.5, True),   # 3.5 - 4.0: tone
    ]
    return _generate_wav(path, 44100, 4.0, segments)


# ---------------------------------------------------------------------------
# RMS envelope
# ---------------------------------------------------------------------------


def test_rms_envelope_shape():
    """RMS envelope has fewer samples than input (windowed)."""
    samples = np.random.randn(44100).astype(np.float64)  # 1 second at 44.1kHz
    rms, window_s = compute_rms_envelope(samples, 44100, window_ms=20)
    # 1 second / 20ms windows = 50 windows
    assert len(rms) == 50
    assert window_s == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# Silence detection
# ---------------------------------------------------------------------------


def test_detect_silence_in_synthetic_audio(tone_silence_wav):
    """Detects silence gaps in a synthetic tone+silence WAV file."""
    from adobe_mcp.apps.illustrator.production.audio_sync_enhanced import read_wav_data

    wav = read_wav_data(tone_silence_wav)
    rms, win_s = compute_rms_envelope(wav["samples"], wav["sample_rate"], window_ms=20)
    rms_db = rms_to_db(rms)

    gaps = detect_silence_gaps(rms_db, threshold_db=-20.0, window_duration_s=win_s, min_silence_ms=400)

    # Should detect at least the 1-second silence gap (might detect the 0.5s one too)
    assert len(gaps) >= 1
    # The first gap should start around 1.0s
    assert gaps[0]["start_s"] == pytest.approx(1.0, abs=0.1)
    assert gaps[0]["duration_s"] >= 0.4


def test_detect_speech_segments(tone_silence_wav):
    """Detects speech/tone segments between silence gaps."""
    from adobe_mcp.apps.illustrator.production.audio_sync_enhanced import read_wav_data

    wav = read_wav_data(tone_silence_wav)
    rms, win_s = compute_rms_envelope(wav["samples"], wav["sample_rate"], window_ms=20)
    rms_db = rms_to_db(rms)

    segments = detect_speech_segments(rms_db, threshold_db=-20.0, window_duration_s=win_s)

    # Should detect at least 2 speech segments (the two 1s tones)
    assert len(segments) >= 2
    # First segment starts near 0.0
    assert segments[0]["start_s"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# Cut point suggestions
# ---------------------------------------------------------------------------


def test_suggest_cuts_aligns_to_silence():
    """Cut suggestions align to silence gap midpoints."""
    silence_gaps = [
        {"start_s": 2.0, "end_s": 3.0, "duration_s": 1.0},
        {"start_s": 5.0, "end_s": 5.5, "duration_s": 0.5},
    ]
    # Two panels of 48 frames each at 24fps = 2s each
    # Boundary at 2s should snap to the gap at 2.0-3.0
    cuts = suggest_cut_points(silence_gaps, [48, 48, 48], fps=24)

    assert len(cuts) == 2  # 2 boundaries between 3 panels
    # First cut should be near the first silence gap midpoint (2.5s)
    assert cuts[0]["suggested_cut_s"] == pytest.approx(2.5, abs=0.01)


def test_suggest_cuts_empty_gaps():
    """No cuts suggested when there are no silence gaps."""
    cuts = suggest_cut_points([], [48, 48], fps=24)
    assert len(cuts) == 0
