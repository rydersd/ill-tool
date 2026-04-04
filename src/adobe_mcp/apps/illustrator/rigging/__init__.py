"""Rigging tools -- skeleton, joints, IK, constraints, hierarchy."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_rigging_tools(mcp):
    from adobe_mcp.apps.illustrator.rigging.skeleton_annotate import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.skeleton_build import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.body_part_label import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.part_bind import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.joint_rotate import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.joint_geometry import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.ik_solver import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.ik_chain_auto import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.rig_controllers import register as _r; _safe_register(_r, mcp)
    # rig_data has no register function (pure data module)
    from adobe_mcp.apps.illustrator.rigging.constraint_system import register as _r; _safe_register(_r, mcp)
    # constraint_solver has no register function (pure solver module)
    from adobe_mcp.apps.illustrator.rigging.chain_detector import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.connection_detector import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.hierarchy_builder import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.hierarchy_templates import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.template_matcher import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.object_hierarchy import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.part_segmenter import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.rigging.part_questioner import register as _r; _safe_register(_r, mcp)
