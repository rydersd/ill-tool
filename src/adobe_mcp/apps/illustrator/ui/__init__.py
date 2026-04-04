"""UI tools -- action lines, camera, color, thumbnails, transitions."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_ui_tools(mcp):
    from adobe_mcp.apps.illustrator.ui.action_lines import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.camera_expressions import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.camera_notation import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.color_script import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.aspect_adapter import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.thumbnail_grid import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.thumbnail_promote import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.transition_planner import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.transition_validator import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ui.background_layer import register as _r; _safe_register(_r, mcp)
