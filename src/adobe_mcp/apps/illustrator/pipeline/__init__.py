"""Pipeline tools -- orchestration, dispatch, spatial processing."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_pipeline_tools(mcp):
    from adobe_mcp.apps.illustrator.pipeline.pipeline_runner import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.pipeline.smart_dispatcher import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.pipeline.spatial_pipeline import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.pipeline.drawing_spinup_bridge import register as _r; _safe_register(_r, mcp)
