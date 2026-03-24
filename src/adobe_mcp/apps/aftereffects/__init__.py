"""After Effects tools — 12 tools split by feature.

Registration chain:
    apps/__init__.py -> aftereffects/__init__.py -> {comp, layer, property, expression, effect, render, gen_render,
        ae_comp_from_character, ae_puppet_pins, ae_keyframe_export, ae_expression_gen, ae_animatic_export}.py
"""

from adobe_mcp.apps.aftereffects.comp import register as _reg_comp
from adobe_mcp.apps.aftereffects.layer import register as _reg_layer
from adobe_mcp.apps.aftereffects.property import register as _reg_property
from adobe_mcp.apps.aftereffects.expression import register as _reg_expression
from adobe_mcp.apps.aftereffects.effect import register as _reg_effect
from adobe_mcp.apps.aftereffects.render import register as _reg_render
from adobe_mcp.apps.aftereffects.gen_render import register as _reg_gen_render

# Character animation pipeline — bridges Illustrator rigs to AE
from adobe_mcp.apps.aftereffects.ae_comp_from_character import register as _reg_comp_from_char
from adobe_mcp.apps.aftereffects.ae_puppet_pins import register as _reg_puppet_pins
from adobe_mcp.apps.aftereffects.ae_keyframe_export import register as _reg_keyframe_export
from adobe_mcp.apps.aftereffects.ae_expression_gen import register as _reg_expression_gen
from adobe_mcp.apps.aftereffects.ae_animatic_export import register as _reg_animatic_export


def register_aftereffects_tools(mcp):
    """Register all 12 After Effects tools."""
    _reg_comp(mcp)
    _reg_layer(mcp)
    _reg_property(mcp)
    _reg_expression(mcp)
    _reg_effect(mcp)
    _reg_render(mcp)
    _reg_gen_render(mcp)

    # Character animation pipeline
    _reg_comp_from_char(mcp)
    _reg_puppet_pins(mcp)
    _reg_keyframe_export(mcp)
    _reg_expression_gen(mcp)
    _reg_animatic_export(mcp)
