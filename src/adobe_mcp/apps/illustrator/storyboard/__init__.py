"""Storyboard tools -- panels, scenes, shots, staging."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_storyboard_tools(mcp):
    from adobe_mcp.apps.illustrator.storyboard.storyboard_panel import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.storyboard_template import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.storyboard_from_script import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.storyboard_to_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.scene_manager import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.scene_composition import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.scene_graph import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.shot_list_gen import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.beat_sheet import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.panel_composer import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.panel_text import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.staging_system import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.storyboard.dialogue_layout import register as _r; _safe_register(_r, mcp)
