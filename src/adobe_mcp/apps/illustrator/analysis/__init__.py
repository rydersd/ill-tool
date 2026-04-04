"""Analysis tools -- learning, detection, classification, style."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_analysis_tools(mcp):
    from adobe_mcp.apps.illustrator.analysis.correction_learning import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.active_learning import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.failure_detection import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.cross_object_patterns import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.cv_confidence import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.interaction_zones import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.lod_system import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.style_transfer import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.shape_recipes import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.color_region_cluster import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.landmark_axis import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.object_classifier import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.analysis.edge_clustering import register as _r; _safe_register(_r, mcp)
