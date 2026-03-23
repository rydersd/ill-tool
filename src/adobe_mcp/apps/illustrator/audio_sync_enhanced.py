"""Enhanced audio sync with waveform analysis.

Analyzes WAV audio files to detect speech boundaries and silence gaps,
suggests panel cut points, and applies markers to the keyframe timeline.

Pure Python implementation using numpy for audio analysis.
"""

import json
import math
import struct
import wave
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiAudioSyncEnhancedInput(BaseModel):
    """Analyze audio waveform for speech boundaries and panel cuts."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: analyze_audio, suggest_cuts, apply_markers"
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    audio_path: Optional[str] = Field(
        default=None, description="Path to WAV audio file"
    )
    silence_threshold_db: float = Field(
        default=-30.0,
        description="Silence threshold in dB (below this is silence)",
    )
    min_silence_ms: int = Field(
        default=500,
        description="Minimum silence duration in ms to count as a gap",
        ge=100,
    )
    fps: int = Field(default=24, description="Frames per second for timecode", ge=1)
    panel_durations_json: Optional[str] = Field(
        default=None,
        description="JSON array of panel durations in frames (for suggest_cuts)",
    )


# ---------------------------------------------------------------------------
# Audio analysis functions
# ---------------------------------------------------------------------------


def read_wav_data(audio_path: str) -> dict:
    """Read a WAV file and return audio data as numpy array.

    Returns: {samples: np.array, sample_rate: int, channels: int, duration_s: float}
    """
    with wave.open(audio_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert raw bytes to numpy array
    if sample_width == 1:
        dtype = np.uint8
    elif sample_width == 2:
        dtype = np.int16
    elif sample_width == 4:
        dtype = np.int32
    else:
        dtype = np.int16

    samples = np.frombuffer(raw, dtype=dtype).astype(np.float64)

    # If stereo, mix to mono
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    # Normalize to [-1, 1]
    max_val = np.iinfo(dtype).max if dtype != np.float64 else 1.0
    if isinstance(max_val, (int, np.integer)):
        samples = samples / float(max_val)

    duration_s = n_frames / sample_rate

    return {
        "samples": samples,
        "sample_rate": sample_rate,
        "channels": n_channels,
        "duration_s": round(duration_s, 3),
        "total_samples": len(samples),
    }


def compute_rms_envelope(samples: np.ndarray, sample_rate: int,
                          window_ms: int = 20) -> tuple[np.ndarray, float]:
    """Compute RMS envelope of audio signal.

    Returns (rms_values, window_duration_s)
    """
    window_size = max(1, int(sample_rate * window_ms / 1000))
    n_windows = len(samples) // window_size

    if n_windows == 0:
        return np.array([0.0]), window_ms / 1000

    # Reshape into windows and compute RMS per window
    truncated = samples[:n_windows * window_size]
    windowed = truncated.reshape(n_windows, window_size)
    rms = np.sqrt(np.mean(windowed ** 2, axis=1))

    return rms, window_ms / 1000


def rms_to_db(rms: np.ndarray) -> np.ndarray:
    """Convert RMS values to decibels."""
    # Avoid log(0) by clamping to small positive value
    safe_rms = np.maximum(rms, 1e-10)
    return 20 * np.log10(safe_rms)


def detect_silence_gaps(
    rms_db: np.ndarray,
    threshold_db: float,
    window_duration_s: float,
    min_silence_ms: int,
) -> list[dict]:
    """Detect silence gaps in the audio.

    Returns list of {start_s, end_s, duration_s} for each silence gap.
    """
    is_silence = rms_db < threshold_db
    min_windows = max(1, int((min_silence_ms / 1000) / window_duration_s))

    gaps = []
    gap_start = None
    gap_length = 0

    for i, silent in enumerate(is_silence):
        if silent:
            if gap_start is None:
                gap_start = i
            gap_length += 1
        else:
            if gap_start is not None and gap_length >= min_windows:
                start_s = gap_start * window_duration_s
                end_s = (gap_start + gap_length) * window_duration_s
                gaps.append({
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "duration_s": round(end_s - start_s, 3),
                })
            gap_start = None
            gap_length = 0

    # Handle trailing silence
    if gap_start is not None and gap_length >= min_windows:
        start_s = gap_start * window_duration_s
        end_s = (gap_start + gap_length) * window_duration_s
        gaps.append({
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "duration_s": round(end_s - start_s, 3),
        })

    return gaps


def detect_speech_segments(
    rms_db: np.ndarray,
    threshold_db: float,
    window_duration_s: float,
) -> list[dict]:
    """Detect speech segments (non-silence regions).

    Returns list of {start_s, end_s, duration_s} for each speech segment.
    """
    is_speech = rms_db >= threshold_db
    segments = []
    seg_start = None

    for i, speaking in enumerate(is_speech):
        if speaking:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                start_s = seg_start * window_duration_s
                end_s = i * window_duration_s
                segments.append({
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "duration_s": round(end_s - start_s, 3),
                })
                seg_start = None

    # Handle trailing speech
    if seg_start is not None:
        start_s = seg_start * window_duration_s
        end_s = len(rms_db) * window_duration_s
        segments.append({
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "duration_s": round(end_s - start_s, 3),
        })

    return segments


def suggest_cut_points(
    silence_gaps: list[dict],
    panel_durations_frames: list[int],
    fps: int,
) -> list[dict]:
    """Suggest panel cut points based on silence gaps.

    Aligns panel boundaries to the nearest silence gap midpoint.
    """
    if not silence_gaps or not panel_durations_frames:
        return []

    # Compute cumulative panel boundaries in seconds
    cumulative = []
    total = 0
    for dur in panel_durations_frames:
        total += dur
        cumulative.append(total / fps)

    cuts = []
    for boundary_s in cumulative[:-1]:  # skip last (end of sequence)
        # Find nearest silence gap to this boundary
        best_gap = None
        best_dist = float("inf")
        for gap in silence_gaps:
            gap_mid = (gap["start_s"] + gap["end_s"]) / 2
            dist = abs(gap_mid - boundary_s)
            if dist < best_dist:
                best_dist = dist
                best_gap = gap

        if best_gap:
            suggested_s = (best_gap["start_s"] + best_gap["end_s"]) / 2
            cuts.append({
                "original_boundary_s": round(boundary_s, 3),
                "suggested_cut_s": round(suggested_s, 3),
                "gap_start_s": best_gap["start_s"],
                "gap_end_s": best_gap["end_s"],
                "adjustment_s": round(suggested_s - boundary_s, 3),
            })

    return cuts


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_audio_sync_enhanced tool."""

    @mcp.tool(
        name="adobe_ai_audio_sync_enhanced",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_audio_sync_enhanced(params: AiAudioSyncEnhancedInput) -> str:
        """Analyze audio waveform for speech boundaries and panel cuts.

        Actions:
        - analyze_audio: read WAV, detect silence gaps and speech segments
        - suggest_cuts: suggest panel cut points at silence gaps
        - apply_markers: write markers to keyframe timeline
        """
        action = params.action.lower().strip()
        char = params.character_name

        # ── analyze_audio ────────────────────────────────────────────
        if action == "analyze_audio":
            if not params.audio_path:
                return json.dumps({"error": "analyze_audio requires audio_path"})

            import os
            if not os.path.exists(params.audio_path):
                return json.dumps({"error": f"Audio file not found: {params.audio_path}"})

            wav_data = read_wav_data(params.audio_path)
            rms, window_s = compute_rms_envelope(wav_data["samples"], wav_data["sample_rate"])
            rms_db = rms_to_db(rms)

            silence_gaps = detect_silence_gaps(
                rms_db, params.silence_threshold_db, window_s, params.min_silence_ms,
            )
            speech_segments = detect_speech_segments(
                rms_db, params.silence_threshold_db, window_s,
            )

            # Store analysis results in rig
            rig = _load_rig(char)
            rig["audio_analysis"] = {
                "path": params.audio_path,
                "duration_s": wav_data["duration_s"],
                "sample_rate": wav_data["sample_rate"],
                "silence_gaps": silence_gaps,
                "speech_segments": speech_segments,
            }
            _save_rig(char, rig)

            return json.dumps({
                "action": "analyze_audio",
                "audio_path": params.audio_path,
                "duration_s": wav_data["duration_s"],
                "sample_rate": wav_data["sample_rate"],
                "silence_gap_count": len(silence_gaps),
                "silence_gaps": silence_gaps,
                "speech_segment_count": len(speech_segments),
                "speech_segments": speech_segments,
            }, indent=2)

        # ── suggest_cuts ─────────────────────────────────────────────
        elif action == "suggest_cuts":
            rig = _load_rig(char)
            analysis = rig.get("audio_analysis")

            if not analysis:
                return json.dumps({
                    "error": "No audio analysis found. Run analyze_audio first.",
                })

            # Get panel durations
            if params.panel_durations_json:
                try:
                    durations = json.loads(params.panel_durations_json)
                except json.JSONDecodeError:
                    return json.dumps({"error": "Invalid panel_durations_json"})
            else:
                # Fall back to storyboard panel durations
                panels = rig.get("storyboard", {}).get("panels", [])
                durations = [p.get("duration_frames", 24) for p in
                             sorted(panels, key=lambda p: p.get("number", 0))]

            if not durations:
                return json.dumps({
                    "error": "No panel durations available. Provide panel_durations_json or create storyboard panels.",
                })

            cuts = suggest_cut_points(
                analysis["silence_gaps"], durations, params.fps,
            )

            return json.dumps({
                "action": "suggest_cuts",
                "cut_count": len(cuts),
                "cuts": cuts,
                "fps": params.fps,
            }, indent=2)

        # ── apply_markers ────────────────────────────────────────────
        elif action == "apply_markers":
            rig = _load_rig(char)
            analysis = rig.get("audio_analysis")

            if not analysis:
                return json.dumps({
                    "error": "No audio analysis found. Run analyze_audio first.",
                })

            # Write silence gap markers to the timeline
            if "timeline" not in rig:
                rig["timeline"] = {"fps": params.fps, "duration_frames": 120}
            if "audio_markers" not in rig:
                rig["audio_markers"] = []

            markers = []
            for gap in analysis["silence_gaps"]:
                frame = int(gap["start_s"] * params.fps)
                marker = {
                    "frame": frame,
                    "type": "silence_gap",
                    "start_s": gap["start_s"],
                    "duration_s": gap["duration_s"],
                }
                markers.append(marker)

            for seg in analysis["speech_segments"]:
                frame = int(seg["start_s"] * params.fps)
                marker = {
                    "frame": frame,
                    "type": "speech_start",
                    "start_s": seg["start_s"],
                    "duration_s": seg["duration_s"],
                }
                markers.append(marker)

            markers.sort(key=lambda m: m["frame"])
            rig["audio_markers"] = markers
            _save_rig(char, rig)

            return json.dumps({
                "action": "apply_markers",
                "markers_written": len(markers),
                "markers": markers,
                "fps": params.fps,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["analyze_audio", "suggest_cuts", "apply_markers"],
            })
