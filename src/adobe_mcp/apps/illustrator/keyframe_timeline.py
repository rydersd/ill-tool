"""Manage a keyframe timeline stored in the character rig file.

Keyframes map frame numbers to named poses with easing curves.
The timeline metadata (fps, duration) is stored alongside keyframes
so downstream tools can compute timing information.
"""

import json

from adobe_mcp.apps.illustrator.models import AiKeyframeTimelineInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


def _ensure_timeline(rig: dict) -> dict:
    """Ensure the rig has timeline and keyframes structures."""
    if "timeline" not in rig:
        rig["timeline"] = {"fps": 24, "duration_frames": 120}
    if "keyframes" not in rig:
        rig["keyframes"] = []
    return rig


def _timing_info(rig: dict) -> dict:
    """Compute timing metadata from the timeline settings."""
    timeline = rig.get("timeline", {"fps": 24, "duration_frames": 120})
    fps = timeline.get("fps", 24)
    duration_frames = timeline.get("duration_frames", 120)
    spf = round(1.0 / fps, 4) if fps > 0 else 0
    total_seconds = round(duration_frames / fps, 3) if fps > 0 else 0
    return {
        "fps": fps,
        "duration_frames": duration_frames,
        "seconds_per_frame": spf,
        "total_duration_seconds": total_seconds,
    }


def register(mcp):
    """Register the adobe_ai_keyframe_timeline tool."""

    @mcp.tool(
        name="adobe_ai_keyframe_timeline",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_keyframe_timeline(params: AiKeyframeTimelineInput) -> str:
        """Manage animation keyframes on a per-character timeline.

        Supports adding/removing keyframes at specific frame numbers,
        listing all keyframes with computed timing, clearing all keyframes,
        and adjusting timeline settings (FPS, total duration).
        """
        rig = _load_rig(params.character_name)
        rig = _ensure_timeline(rig)

        action = params.action.lower().strip()

        # ── add_keyframe ────────────────────────────────────────────────
        if action == "add_keyframe":
            if params.frame is None:
                return json.dumps({"error": "frame is required for add_keyframe"})
            if not params.pose_name:
                return json.dumps({"error": "pose_name is required for add_keyframe"})

            # Validate that the pose exists in the rig
            poses = rig.get("poses", {})
            if params.pose_name not in poses:
                available = list(poses.keys()) if poses else []
                return json.dumps({
                    "error": f"Pose '{params.pose_name}' not found in rig.",
                    "available_poses": available,
                    "hint": "Use pose_snapshot with action='capture' to save a pose first.",
                })

            # Validate frame is within duration
            duration = rig["timeline"].get("duration_frames", 120)
            if params.frame > duration:
                return json.dumps({
                    "error": f"Frame {params.frame} exceeds timeline duration ({duration} frames).",
                    "hint": "Use set_duration to extend the timeline first.",
                })

            # Remove any existing keyframe at this frame
            rig["keyframes"] = [
                kf for kf in rig["keyframes"] if kf.get("frame") != params.frame
            ]

            # Add the new keyframe
            keyframe = {
                "frame": params.frame,
                "pose_name": params.pose_name,
                "easing": params.easing,
            }
            rig["keyframes"].append(keyframe)

            # Sort keyframes by frame number for clean ordering
            rig["keyframes"].sort(key=lambda kf: kf.get("frame", 0))

            _save_rig(params.character_name, rig)

            timing = _timing_info(rig)
            fps = timing["fps"]
            frame_seconds = round(params.frame / fps, 3) if fps > 0 else 0

            return json.dumps({
                "action": "add_keyframe",
                "keyframe": keyframe,
                "time_seconds": frame_seconds,
                "total_keyframes": len(rig["keyframes"]),
                "timing": timing,
            }, indent=2)

        # ── remove_keyframe ─────────────────────────────────────────────
        elif action == "remove_keyframe":
            if params.frame is None:
                return json.dumps({"error": "frame is required for remove_keyframe"})

            original_count = len(rig["keyframes"])
            rig["keyframes"] = [
                kf for kf in rig["keyframes"] if kf.get("frame") != params.frame
            ]
            removed = original_count - len(rig["keyframes"])

            if removed == 0:
                return json.dumps({
                    "action": "remove_keyframe",
                    "frame": params.frame,
                    "removed": False,
                    "message": f"No keyframe found at frame {params.frame}.",
                })

            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "remove_keyframe",
                "frame": params.frame,
                "removed": True,
                "remaining_keyframes": len(rig["keyframes"]),
                "timing": _timing_info(rig),
            }, indent=2)

        # ── list ────────────────────────────────────────────────────────
        elif action == "list":
            timing = _timing_info(rig)
            fps = timing["fps"]

            # Enrich keyframes with computed time-in-seconds
            enriched = []
            for kf in rig["keyframes"]:
                frame = kf.get("frame", 0)
                enriched.append({
                    "frame": frame,
                    "pose_name": kf.get("pose_name", ""),
                    "easing": kf.get("easing", "linear"),
                    "time_seconds": round(frame / fps, 3) if fps > 0 else 0,
                })

            return json.dumps({
                "action": "list",
                "character_name": params.character_name,
                "keyframes": enriched,
                "total_keyframes": len(enriched),
                "timing": timing,
            }, indent=2)

        # ── clear ───────────────────────────────────────────────────────
        elif action == "clear":
            cleared_count = len(rig["keyframes"])
            rig["keyframes"] = []
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "clear",
                "cleared_keyframes": cleared_count,
                "timing": _timing_info(rig),
            }, indent=2)

        # ── set_fps ─────────────────────────────────────────────────────
        elif action == "set_fps":
            if params.fps is None:
                return json.dumps({"error": "fps is required for set_fps"})

            old_fps = rig["timeline"].get("fps", 24)
            rig["timeline"]["fps"] = params.fps
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "set_fps",
                "old_fps": old_fps,
                "new_fps": params.fps,
                "timing": _timing_info(rig),
            }, indent=2)

        # ── set_duration ────────────────────────────────────────────────
        elif action == "set_duration":
            if params.duration_frames is None:
                return json.dumps({"error": "duration_frames is required for set_duration"})

            old_duration = rig["timeline"].get("duration_frames", 120)
            rig["timeline"]["duration_frames"] = params.duration_frames
            _save_rig(params.character_name, rig)

            # Warn about keyframes past the new duration
            out_of_range = [
                kf for kf in rig["keyframes"]
                if kf.get("frame", 0) > params.duration_frames
            ]
            warnings = []
            if out_of_range:
                warnings.append(
                    f"{len(out_of_range)} keyframe(s) exist beyond the new duration "
                    f"({params.duration_frames} frames). They will not be removed "
                    "automatically — use remove_keyframe to clean up."
                )

            return json.dumps({
                "action": "set_duration",
                "old_duration_frames": old_duration,
                "new_duration_frames": params.duration_frames,
                "timing": _timing_info(rig),
                "warnings": warnings,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": [
                    "add_keyframe", "remove_keyframe", "list", "clear",
                    "set_fps", "set_duration",
                ],
            })
