"""Illustrator tools — 69 tools split by feature.

Registration chain:
    apps/__init__.py -> illustrator/__init__.py -> {new_document, shapes, text, paths, export, layers, modify, inspect, image_trace, analyze_reference, reference_underlay, vtrace, anchor_edit, silhouette, auto_correct, proportion_grid, style_transfer, shape_recipes, contour_to_path, smart_shape, bezier_optimize, curve_fit, artboard_from_ref, path_boolean, symmetry, layer_auto_organize, group_and_name, color_sampler, stroke_profiles, path_offset, path_weld, snap_to_grid, undo_checkpoint, reference_crop, drawing_orchestrator, skeleton_annotate, body_part_label, skeleton_build, part_bind, joint_rotate, pose_snapshot, pose_interpolate, ik_solver, onion_skin, character_template, pose_from_image, keyframe_timeline, motion_path, storyboard_panel, scene_manager, background_layer, multi_character, shot_list_gen, beat_sheet, production_notes, continuity_check, asset_registry, pdf_export, animatic_preview, prop_manager, lighting_notation, transition_planner, audio_sync, sequence_assembler, rig_controllers, storyboard_template, panel_text, camera_notation, character_turnaround}.py
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
from adobe_mcp.apps.illustrator.contour_to_path import register as _reg_contour_to_path
from adobe_mcp.apps.illustrator.smart_shape import register as _reg_smart_shape
from adobe_mcp.apps.illustrator.bezier_optimize import register as _reg_bezier_optimize
from adobe_mcp.apps.illustrator.curve_fit import register as _reg_curve_fit
from adobe_mcp.apps.illustrator.artboard_from_ref import register as _reg_artboard_from_ref
from adobe_mcp.apps.illustrator.path_boolean import register as _reg_path_boolean
from adobe_mcp.apps.illustrator.symmetry import register as _reg_symmetry
from adobe_mcp.apps.illustrator.layer_auto_organize import register as _reg_layer_auto_organize
from adobe_mcp.apps.illustrator.group_and_name import register as _reg_group_and_name
from adobe_mcp.apps.illustrator.color_sampler import register as _reg_color_sampler
from adobe_mcp.apps.illustrator.stroke_profiles import register as _reg_stroke_profiles
from adobe_mcp.apps.illustrator.path_offset import register as _reg_path_offset
from adobe_mcp.apps.illustrator.path_weld import register as _reg_path_weld
from adobe_mcp.apps.illustrator.snap_to_grid import register as _reg_snap_to_grid
from adobe_mcp.apps.illustrator.undo_checkpoint import register as _reg_undo_checkpoint
from adobe_mcp.apps.illustrator.reference_crop import register as _reg_reference_crop
from adobe_mcp.apps.illustrator.drawing_orchestrator import register as _reg_drawing_orchestrator
from adobe_mcp.apps.illustrator.skeleton_annotate import register as _reg_skeleton_annotate
from adobe_mcp.apps.illustrator.body_part_label import register as _reg_body_part_label
from adobe_mcp.apps.illustrator.skeleton_build import register as _reg_skeleton_build
from adobe_mcp.apps.illustrator.part_bind import register as _reg_part_bind
from adobe_mcp.apps.illustrator.joint_rotate import register as _reg_joint_rotate
from adobe_mcp.apps.illustrator.pose_snapshot import register as _reg_pose_snapshot
from adobe_mcp.apps.illustrator.pose_interpolate import register as _reg_pose_interpolate
from adobe_mcp.apps.illustrator.ik_solver import register as _reg_ik_solver
from adobe_mcp.apps.illustrator.onion_skin import register as _reg_onion_skin
from adobe_mcp.apps.illustrator.character_template import register as _reg_character_template
from adobe_mcp.apps.illustrator.pose_from_image import register as _reg_pose_from_image
from adobe_mcp.apps.illustrator.keyframe_timeline import register as _reg_keyframe_timeline
from adobe_mcp.apps.illustrator.motion_path import register as _reg_motion_path
from adobe_mcp.apps.illustrator.storyboard_panel import register as _reg_storyboard_panel
from adobe_mcp.apps.illustrator.scene_manager import register as _reg_scene_manager
from adobe_mcp.apps.illustrator.background_layer import register as _reg_background_layer
from adobe_mcp.apps.illustrator.multi_character import register as _reg_multi_character
from adobe_mcp.apps.illustrator.shot_list_gen import register as _reg_shot_list_gen
from adobe_mcp.apps.illustrator.beat_sheet import register as _reg_beat_sheet
from adobe_mcp.apps.illustrator.production_notes import register as _reg_production_notes
from adobe_mcp.apps.illustrator.continuity_check import register as _reg_continuity_check
from adobe_mcp.apps.illustrator.asset_registry import register as _reg_asset_registry
from adobe_mcp.apps.illustrator.pdf_export import register as _reg_pdf_export
from adobe_mcp.apps.illustrator.animatic_preview import register as _reg_animatic_preview
from adobe_mcp.apps.illustrator.prop_manager import register as _reg_prop_manager
from adobe_mcp.apps.illustrator.lighting_notation import register as _reg_lighting_notation
from adobe_mcp.apps.illustrator.transition_planner import register as _reg_transition_planner
from adobe_mcp.apps.illustrator.audio_sync import register as _reg_audio_sync
from adobe_mcp.apps.illustrator.sequence_assembler import register as _reg_sequence_assembler
from adobe_mcp.apps.illustrator.rig_controllers import register as _reg_rig_controllers
from adobe_mcp.apps.illustrator.storyboard_template import register as _reg_storyboard_template
from adobe_mcp.apps.illustrator.panel_text import register as _reg_panel_text
from adobe_mcp.apps.illustrator.camera_notation import register as _reg_camera_notation
from adobe_mcp.apps.illustrator.character_turnaround import register as _reg_character_turnaround


def register_illustrator_tools(mcp):
    """Register all 69 Illustrator tools."""
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
    _reg_contour_to_path(mcp)
    _reg_smart_shape(mcp)
    _reg_bezier_optimize(mcp)
    _reg_curve_fit(mcp)
    _reg_artboard_from_ref(mcp)
    _reg_path_boolean(mcp)
    _reg_symmetry(mcp)
    _reg_layer_auto_organize(mcp)
    _reg_group_and_name(mcp)
    _reg_color_sampler(mcp)
    _reg_stroke_profiles(mcp)
    _reg_path_offset(mcp)
    _reg_path_weld(mcp)
    _reg_snap_to_grid(mcp)
    _reg_undo_checkpoint(mcp)
    _reg_reference_crop(mcp)
    _reg_drawing_orchestrator(mcp)
    _reg_skeleton_annotate(mcp)
    _reg_body_part_label(mcp)
    _reg_skeleton_build(mcp)
    _reg_part_bind(mcp)
    _reg_joint_rotate(mcp)
    _reg_pose_snapshot(mcp)
    _reg_pose_interpolate(mcp)
    _reg_ik_solver(mcp)
    _reg_onion_skin(mcp)
    _reg_character_template(mcp)
    _reg_pose_from_image(mcp)
    _reg_keyframe_timeline(mcp)
    _reg_motion_path(mcp)
    _reg_storyboard_panel(mcp)
    _reg_scene_manager(mcp)
    _reg_background_layer(mcp)
    _reg_multi_character(mcp)
    _reg_shot_list_gen(mcp)
    _reg_beat_sheet(mcp)
    _reg_production_notes(mcp)
    _reg_continuity_check(mcp)
    _reg_asset_registry(mcp)
    _reg_pdf_export(mcp)
    _reg_animatic_preview(mcp)
    _reg_prop_manager(mcp)
    _reg_lighting_notation(mcp)
    _reg_transition_planner(mcp)
    _reg_audio_sync(mcp)
    _reg_sequence_assembler(mcp)
    _reg_rig_controllers(mcp)
    _reg_storyboard_template(mcp)
    _reg_panel_text(mcp)
    _reg_camera_notation(mcp)
    _reg_character_turnaround(mcp)
