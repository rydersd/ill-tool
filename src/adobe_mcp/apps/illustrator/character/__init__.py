"""Character tools -- templates, turnarounds, expressions, sheets."""

import logging as _logging

_log = _logging.getLogger(__name__)


def _safe_register(reg_fn, mcp_ref):
    try:
        reg_fn(mcp_ref)
    except Exception as exc:
        _log.warning("Failed to register %s.%s: %s", reg_fn.__module__, reg_fn.__name__, exc)


def register_character_tools(mcp):
    from adobe_mcp.apps.illustrator.character.character_template import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_turnaround import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_expression import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_sheet_gen import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_wizard import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_3d import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.character_apose import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.multi_character import register as _r; _safe_register(_r, mcp)
    from adobe_mcp.apps.illustrator.character.one_click_character import register as _r; _safe_register(_r, mcp)
