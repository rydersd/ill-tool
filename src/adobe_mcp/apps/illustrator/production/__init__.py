"""Production tools -- notes, continuity, assets, audio, dashboard."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_production_tools(mcp):
    from adobe_mcp.apps.illustrator.production.production_notes import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.continuity_check import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.continuity_enhanced import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.director_markup import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.revision_tracker import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.asset_registry import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.asset_versioning import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.batch_export_all import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.project_dashboard import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.project_dashboard_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.animatic_preview import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.audio_sync import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.audio_sync_enhanced import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.sequence_assembler import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.prop_manager import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.lighting_notation import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.production.environment import register as _r; _safe_register(_r, mcp)
