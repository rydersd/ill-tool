"""Utility tools -- correction, debugging, symmetry, templates, bridges."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_utility_tools(mcp):
    from adobe_mcp.apps.illustrator.utility.auto_correct import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.visual_debugger import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.batch_rig import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.deformation_zones import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.weight_zones import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.part_size_ranker import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.relationship_types import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.symmetry import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.symmetry_detector import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.template_inheritance import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.template_scaling import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.template_library_search import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.sketch2anim_bridge import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.animated_drawings_bridge import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.dwpose_delta_extractor import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.utility.style_guide import register as _r; _safe_register(_r, mcp)
