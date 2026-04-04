"""Illustrator tools -- 200 modules organized into 15 subdirectories.

Registration chain:
    apps/__init__.py -> illustrator/__init__.py -> {subdir}/__init__.py -> module.register(mcp)

Subdirectories:
    core/           22 tools  -- document, paths, layers, shapes, text, editing
    drawing/        19 tools  -- orchestration, construction, contours, form analysis
    rigging/        20 files  -- skeleton, joints, IK, constraints, hierarchy
    analysis/       12 tools  -- learning, detection, classification, style
    character/       9 tools  -- templates, turnarounds, expressions, sheets
    animation/      16 tools  -- poses, keyframes, motion paths, physics
    storyboard/     13 tools  -- panels, scenes, shots, staging
    production/     17 tools  -- notes, continuity, assets, audio, dashboard
    pipeline/        4 tools  -- orchestration, dispatch, spatial processing
    export_formats/ 11 tools  -- PDF, Spine, Rive, Lottie, Live2D, USDZ, OTIO, EDL
    ml_vision/      13 files  -- reference analysis, tracing, vectorization, segmentation
    threed/         15 tools  -- reconstruction, mesh, depth, camera, multiview
    ui/             10 tools  -- action lines, camera, color, thumbnails, transitions
    utility/        16 tools  -- correction, debugging, symmetry, templates, bridges
    ml_backends/     3 files  -- normal estimation, edge classification, informative drawing (no MCP tools)

Root-level shared modules (not moved):
    models.py, server.py, coordinate_transforms.py, path_validation.py,
    surface_classifier.py, normal_renderings.py, interaction_ingest.py,
    form_edge_pipeline.py
"""

from adobe_mcp.apps.illustrator.core import register_core_tools
from adobe_mcp.apps.illustrator.drawing import register_drawing_tools
from adobe_mcp.apps.illustrator.rigging import register_rigging_tools
from adobe_mcp.apps.illustrator.analysis import register_analysis_tools
from adobe_mcp.apps.illustrator.character import register_character_tools
from adobe_mcp.apps.illustrator.animation import register_animation_tools
from adobe_mcp.apps.illustrator.storyboard import register_storyboard_tools
from adobe_mcp.apps.illustrator.production import register_production_tools
from adobe_mcp.apps.illustrator.pipeline import register_pipeline_tools
from adobe_mcp.apps.illustrator.export_formats import register_export_formats_tools
from adobe_mcp.apps.illustrator.ml_vision import register_ml_vision_tools
from adobe_mcp.apps.illustrator.threed import register_threed_tools
from adobe_mcp.apps.illustrator.ui import register_ui_tools
from adobe_mcp.apps.illustrator.utility import register_utility_tools

# Root-level shared module that has a register function
from adobe_mcp.apps.illustrator.interaction_ingest import register as _reg_interaction_ingest


def register_illustrator_tools(mcp):
    """Register all Illustrator tools.

    Each subdirectory's register function wraps individual registrations
    in try/except so one broken tool doesn't prevent the rest from loading.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    register_core_tools(mcp)
    register_drawing_tools(mcp)
    register_rigging_tools(mcp)
    register_analysis_tools(mcp)
    register_character_tools(mcp)
    register_animation_tools(mcp)
    register_storyboard_tools(mcp)
    register_production_tools(mcp)
    register_pipeline_tools(mcp)
    register_export_formats_tools(mcp)
    register_ml_vision_tools(mcp)
    register_threed_tools(mcp)
    register_ui_tools(mcp)
    register_utility_tools(mcp)

    # Root-level module with register function
    try:
        _reg_interaction_ingest(mcp)
    except Exception as exc:
        _log.warning("Failed to register interaction_ingest: %s", exc)
