"""Premiere Pro tools — 6 tools split by feature.

Registration chain:
    apps/__init__.py -> premiere/__init__.py -> {project, sequence, media, timeline, export, effects}.py
"""

from adobe_mcp.apps.premiere.project import register as _reg_project
from adobe_mcp.apps.premiere.sequence import register as _reg_sequence
from adobe_mcp.apps.premiere.media import register as _reg_media
from adobe_mcp.apps.premiere.timeline import register as _reg_timeline
from adobe_mcp.apps.premiere.export import register as _reg_export
from adobe_mcp.apps.premiere.effects import register as _reg_effects


def register_premiere_tools(mcp):
    """Register all 6 Premiere Pro tools."""
    _reg_project(mcp)
    _reg_sequence(mcp)
    _reg_media(mcp)
    _reg_timeline(mcp)
    _reg_export(mcp)
    _reg_effects(mcp)
