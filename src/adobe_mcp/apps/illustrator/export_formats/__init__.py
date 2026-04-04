"""Export format tools -- PDF, Spine, Rive, Lottie, Live2D, USDZ, OTIO, EDL."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_export_formats_tools(mcp):
    from adobe_mcp.apps.illustrator.export_formats.pdf_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.spine_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.rive_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.lottie_workflow import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.live2d_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.otio_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.export_usdz import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.format_hub import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.smart_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.template_export import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.export_formats.edl_export import register as _r; _safe_register(_r, mcp)
