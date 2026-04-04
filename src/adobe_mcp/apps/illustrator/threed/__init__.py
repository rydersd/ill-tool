"""3D tools -- reconstruction, mesh, depth, camera, multiview."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_threed_tools(mcp):
    from adobe_mcp.apps.illustrator.threed.reconstruct_3d_quick import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.reconstruct_3d_quality import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.reconstruct_3d_trellis import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.refine_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.mesh_to_rig import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.mesh_face_grouper import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.depth_compositor import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.camera_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.multiview_synthesis import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.feedback_loop_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.form_3d_projection import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.asset_3d_library import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.pose_preview_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.turnaround_from_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.threed.perspective_from_3d import register as _r; _safe_register(_r, mcp)
