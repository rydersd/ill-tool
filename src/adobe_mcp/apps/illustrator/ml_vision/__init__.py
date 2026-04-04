"""ML/Vision tools -- reference analysis, tracing, vectorization, segmentation."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_ml_vision_tools(mcp):
    from adobe_mcp.apps.illustrator.ml_vision.analyze_reference import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.reference_underlay import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.reference_crop import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.reference_library import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.vtrace import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.trace_workflow import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.vectorize_ml import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.landmark_ml import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.segment_ml import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.diffvg_correct import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.ml_vision.artboard_from_ref import register as _r; _safe_register(_r, mcp)
    # pixel_deviation_scorer has no register function (pure utility)
    # path_gradient_approx has no register function (pure utility)
