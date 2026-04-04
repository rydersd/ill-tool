"""Core Illustrator tools -- document, paths, layers, shapes, text, editing."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_core_tools(mcp):
    from adobe_mcp.apps.illustrator.core.new_document import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.shapes import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.text import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.paths import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.layers import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.modify import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.inspect import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.image_trace import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.anchor_edit import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.path_boolean import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.snap_to_grid import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.undo_checkpoint import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.path_offset import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.path_weld import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.group_and_name import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.layer_auto_organize import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.color_sampler import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.stroke_profiles import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.smart_shape import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.bezier_optimize import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.core.curve_fit import register as _r; _safe_register(_r, mcp)
