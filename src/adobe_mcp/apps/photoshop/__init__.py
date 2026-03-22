"""Photoshop tools — 13 tools split by feature.

Registration chain:
    apps/__init__.py -> photoshop/__init__.py -> {new_document, layers, groups, selections, transforms, filters, adjustments, text, export, batch, actions, smart_objects, inspect}.py
"""

from adobe_mcp.apps.photoshop.new_document import register as _reg_new_document
from adobe_mcp.apps.photoshop.layers import register as _reg_layers
from adobe_mcp.apps.photoshop.groups import register as _reg_groups
from adobe_mcp.apps.photoshop.selections import register as _reg_selections
from adobe_mcp.apps.photoshop.transforms import register as _reg_transforms
from adobe_mcp.apps.photoshop.filters import register as _reg_filters
from adobe_mcp.apps.photoshop.adjustments import register as _reg_adjustments
from adobe_mcp.apps.photoshop.text import register as _reg_text
from adobe_mcp.apps.photoshop.export import register as _reg_export
from adobe_mcp.apps.photoshop.batch import register as _reg_batch
from adobe_mcp.apps.photoshop.actions import register as _reg_actions
from adobe_mcp.apps.photoshop.smart_objects import register as _reg_smart_objects
from adobe_mcp.apps.photoshop.inspect import register as _reg_inspect


def register_photoshop_tools(mcp):
    """Register all 13 Photoshop tools."""
    _reg_new_document(mcp)
    _reg_layers(mcp)
    _reg_groups(mcp)
    _reg_selections(mcp)
    _reg_transforms(mcp)
    _reg_filters(mcp)
    _reg_adjustments(mcp)
    _reg_text(mcp)
    _reg_export(mcp)
    _reg_batch(mcp)
    _reg_actions(mcp)
    _reg_smart_objects(mcp)
    _reg_inspect(mcp)
