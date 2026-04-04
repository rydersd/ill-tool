"""Animation tools -- poses, keyframes, motion paths, physics."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_animation_tools(mcp):
    from adobe_mcp.apps.illustrator.animation.pose_snapshot import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.pose_interpolate import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.pose_from_image import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.pose_library_generic import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.quick_pose import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.batch_pose import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.onion_skin import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.motion_path import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.motion_path_from_hierarchy import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.secondary_motion import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.physics_hints import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.timing_curves import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.anticipation_markers import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.keyframe_timeline import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.animation_flipbook import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.animation.motion_range_from_shape import register as _r; _safe_register(_r, mcp)
