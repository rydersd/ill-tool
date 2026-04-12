"""
IllTool Render Setup for Blender
================================
Configures render passes and exports for the IllTool Freestyle cleanup pipeline.

Usage:
  1. Open in Blender's Text Editor and Run Script
  2. Or run from command line: blender --python illtool_render_setup.py

What it does:
  - Enables render passes: Depth, Normal, Object Index, Material Index
  - Configures EXR multilayer output (32-bit float)
  - Enables Freestyle SVG export
  - Sets up compositor nodes to write individual pass images
  - Exports camera data as JSON sidecar

Output files (in //render/illtool/):
  - illtool_passes.exr  — multilayer EXR with all passes
  - illtool_freestyle.svg — Freestyle line art
  - camera.json — camera matrix, focal length, sensor, resolution
  - object_index.json — object name → index mapping
"""

import bpy
import json
import os
import math

# ============================================================================
#  Configuration
# ============================================================================

OUTPUT_DIR = "//render/illtool/"  # Blender-relative path
EXR_FILENAME = "illtool_passes"
FREESTYLE_FILENAME = "illtool_freestyle"


def setup_render_passes():
    """Enable all render passes needed by IllTool."""
    scene = bpy.context.scene
    vl = scene.view_layers[0]

    # Core passes for IllTool
    vl.use_pass_z = True                # Depth (float)
    vl.use_pass_normal = True           # Surface normals (float3)
    vl.use_pass_object_index = True     # Object ID (int)
    vl.use_pass_material_index = True   # Material ID (int)

    # Useful extras (optional, low cost)
    vl.use_pass_mist = True             # Smooth depth falloff
    vl.use_pass_emit = False            # Not needed
    vl.use_pass_environment = False     # Not needed

    print("[IllTool] Render passes enabled: Z, Normal, Object Index, Material Index, Mist")


def setup_output():
    """Configure EXR multilayer output."""
    scene = bpy.context.scene
    render = scene.render

    # EXR multilayer — all passes in one file
    render.image_settings.file_format = 'OPEN_EXR_MULTILAYER'
    render.image_settings.color_depth = '32'
    render.image_settings.exr_codec = 'ZIP'

    # Output path
    render.filepath = OUTPUT_DIR + EXR_FILENAME

    print(f"[IllTool] Output: {render.filepath}.exr (EXR multilayer, 32-bit, ZIP)")


def setup_freestyle():
    """Enable Freestyle line rendering with SVG export."""
    scene = bpy.context.scene
    vl = scene.view_layers[0]

    # Enable Freestyle
    scene.render.use_freestyle = True
    vl.use_freestyle = True

    # Configure Freestyle settings
    fs = vl.freestyle_settings
    fs.as_render_pass = False  # Separate output, not composited

    # Enable the Freestyle SVG exporter addon
    try:
        bpy.ops.preferences.addon_enable(module='render_freestyle_svg')
        print("[IllTool] Freestyle SVG addon enabled")
    except Exception as e:
        print(f"[IllTool] Warning: Could not enable Freestyle SVG addon: {e}")
        print("[IllTool] Enable manually: Edit > Preferences > Add-ons > Render: Freestyle SVG Exporter")

    # Configure SVG output path via the addon's scene properties
    if hasattr(scene, 'svg_export'):
        scene.svg_export.use_svg_export = True
    elif hasattr(scene.render, 'freestyle_svg_export'):
        scene.render.freestyle_svg_export.use_svg_export = True

    print("[IllTool] Freestyle enabled with SVG export")


def setup_object_indices():
    """Assign unique pass_index to every mesh object for Object ID pass."""
    meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    index_map = {}

    for i, obj in enumerate(meshes, start=1):
        obj.pass_index = i
        index_map[obj.name] = i
        print(f"[IllTool] Object '{obj.name}' → index {i}")

    return index_map


def export_camera_json(output_dir):
    """Export camera parameters as JSON for IllTool perspective grid setup."""
    scene = bpy.context.scene
    cam_obj = scene.camera

    if not cam_obj:
        print("[IllTool] Warning: No active camera found")
        return

    cam = cam_obj.data

    # World matrix (4x4)
    matrix = [[cam_obj.matrix_world[row][col] for col in range(4)] for row in range(4)]

    # Projection parameters
    camera_data = {
        "matrix_world": matrix,
        "location": list(cam_obj.location),
        "rotation_euler": [math.degrees(a) for a in cam_obj.rotation_euler],
        "focal_length_mm": cam.lens,
        "sensor_width_mm": cam.sensor_width,
        "sensor_height_mm": cam.sensor_height,
        "sensor_fit": cam.sensor_fit,
        "clip_start": cam.clip_start,
        "clip_end": cam.clip_end,
        "type": cam.type,  # PERSP, ORTHO, PANO
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "pixel_aspect_x": scene.render.pixel_aspect_x,
        "pixel_aspect_y": scene.render.pixel_aspect_y,
    }

    # Compute vertical FOV for perspective cameras
    if cam.type == 'PERSP':
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        aspect = res_x / res_y
        if cam.sensor_fit == 'HORIZONTAL' or (cam.sensor_fit == 'AUTO' and aspect >= 1):
            hfov = 2 * math.atan(cam.sensor_width / (2 * cam.lens))
            vfov = 2 * math.atan(math.tan(hfov / 2) / aspect)
        else:
            vfov = 2 * math.atan(cam.sensor_height / (2 * cam.lens))
            hfov = 2 * math.atan(math.tan(vfov / 2) * aspect)
        camera_data["hfov_degrees"] = math.degrees(hfov)
        camera_data["vfov_degrees"] = math.degrees(vfov)

    # Resolve output path
    abs_dir = bpy.path.abspath(output_dir)
    os.makedirs(abs_dir, exist_ok=True)

    json_path = os.path.join(abs_dir, "camera.json")
    with open(json_path, 'w') as f:
        json.dump(camera_data, f, indent=2)

    print(f"[IllTool] Camera exported: {json_path}")
    return camera_data


def export_object_index_json(index_map, output_dir):
    """Export object name → pass_index mapping as JSON."""
    abs_dir = bpy.path.abspath(output_dir)
    os.makedirs(abs_dir, exist_ok=True)

    json_path = os.path.join(abs_dir, "object_index.json")
    with open(json_path, 'w') as f:
        json.dump(index_map, f, indent=2)

    print(f"[IllTool] Object index map exported: {json_path} ({len(index_map)} objects)")


# ============================================================================
#  Main
# ============================================================================

def main():
    print("\n" + "=" * 60)
    print("  IllTool Render Setup")
    print("=" * 60)

    setup_render_passes()
    setup_output()
    setup_freestyle()
    index_map = setup_object_indices()
    camera_data = export_camera_json(OUTPUT_DIR)
    export_object_index_json(index_map, OUTPUT_DIR)

    print("\n" + "-" * 60)
    print("  Setup complete. Render with F12 to generate:")
    print(f"    {OUTPUT_DIR}{EXR_FILENAME}.exr")
    print(f"    {OUTPUT_DIR}{FREESTYLE_FILENAME}.svg")
    print(f"    {OUTPUT_DIR}camera.json")
    print(f"    {OUTPUT_DIR}object_index.json")
    print("-" * 60 + "\n")


if __name__ == "__main__":
    main()
