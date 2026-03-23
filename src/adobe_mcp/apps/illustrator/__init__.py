"""Illustrator tools — 18 tools split by feature.

Registration chain:
    apps/__init__.py -> illustrator/__init__.py -> {new_document, shapes, text, paths, export, layers, modify, inspect, image_trace, analyze_reference, reference_underlay, vtrace, anchor_edit, silhouette, auto_correct, proportion_grid, style_transfer, shape_recipes}.py
"""

from adobe_mcp.apps.illustrator.new_document import register as _reg_new_document
from adobe_mcp.apps.illustrator.shapes import register as _reg_shapes
from adobe_mcp.apps.illustrator.text import register as _reg_text
from adobe_mcp.apps.illustrator.paths import register as _reg_paths
from adobe_mcp.apps.illustrator.export import register as _reg_export
from adobe_mcp.apps.illustrator.layers import register as _reg_layers
from adobe_mcp.apps.illustrator.modify import register as _reg_modify
from adobe_mcp.apps.illustrator.inspect import register as _reg_inspect
from adobe_mcp.apps.illustrator.image_trace import register as _reg_image_trace
from adobe_mcp.apps.illustrator.analyze_reference import register as _reg_analyze_reference
from adobe_mcp.apps.illustrator.reference_underlay import register as _reg_reference_underlay
from adobe_mcp.apps.illustrator.vtrace import register as _reg_vtrace
from adobe_mcp.apps.illustrator.anchor_edit import register as _reg_anchor_edit
from adobe_mcp.apps.illustrator.silhouette import register as _reg_silhouette
from adobe_mcp.apps.illustrator.auto_correct import register as _reg_auto_correct
from adobe_mcp.apps.illustrator.proportion_grid import register as _reg_proportion_grid
from adobe_mcp.apps.illustrator.style_transfer import register as _reg_style_transfer
from adobe_mcp.apps.illustrator.shape_recipes import register as _reg_shape_recipes


def register_illustrator_tools(mcp):
    """Register all 18 Illustrator tools."""
    _reg_new_document(mcp)
    _reg_shapes(mcp)
    _reg_text(mcp)
    _reg_paths(mcp)
    _reg_export(mcp)
    _reg_layers(mcp)
    _reg_modify(mcp)
    _reg_inspect(mcp)
    _reg_image_trace(mcp)
    _reg_analyze_reference(mcp)
    _reg_reference_underlay(mcp)
    _reg_vtrace(mcp)
    _reg_anchor_edit(mcp)
    _reg_silhouette(mcp)
    _reg_auto_correct(mcp)
    _reg_proportion_grid(mcp)
    _reg_style_transfer(mcp)
    _reg_shape_recipes(mcp)
