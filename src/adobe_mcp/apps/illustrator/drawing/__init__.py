"""Drawing tools -- orchestration, construction, contours, form analysis."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_drawing_tools(mcp):
    from adobe_mcp.apps.illustrator.drawing.drawing_orchestrator import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.drawing_session import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.construction_draw import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.gesture_line import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.contour_to_path import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.contour_scanner import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.contour_labeler import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.contour_nesting import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.form_edge_extract import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.form_volume import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.line_weight import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.negative_space import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.proportion_check import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.proportion_grid import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.silhouette import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.tonal_analyzer import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.cross_section import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.shading_inference import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.normal_reference import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.drawing.surface_extract import register as _r; _safe_register(_r, mcp)
