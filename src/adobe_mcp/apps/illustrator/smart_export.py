"""Export everything After Effects needs in one call.

Prepares a complete AE import package: rig JSON (joints, hierarchy,
pivots, constraints, poses, timeline), panel PNGs (if storyboard
exists), and an AE import JSX script that sets up the comp with
layers, hierarchy, and keyframes.

Pure Python implementation.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rig_data import _load_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiSmartExportInput(BaseModel):
    """Export everything AE needs in one call."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: prepare_ae_export, export_manifest",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for the rig",
    )
    output_dir: str = Field(
        default="/tmp/ae_export",
        description="Directory for exported files",
    )


# ---------------------------------------------------------------------------
# AE import JSX generator
# ---------------------------------------------------------------------------


def _generate_ae_jsx(rig: dict, rig_json_path: str) -> str:
    """Generate ExtendScript for After Effects to import the rig.

    Creates a comp, adds layers from the AI file, sets up the hierarchy
    from the rig data, and applies any saved keyframes.

    Args:
        rig: character rig dict
        rig_json_path: path to the exported rig JSON

    Returns:
        JSX code string for AE import.
    """
    character_name = rig.get("character_name", "character")
    image_source = rig.get("image_source", "")
    joints = rig.get("joints", {})
    bones = rig.get("bones", [])
    poses = rig.get("poses", {})

    jsx_lines = [
        '// Auto-generated AE import script',
        f'// Character: {character_name}',
        '',
        '(function() {',
        '    app.beginUndoGroup("Import Character Rig");',
        '',
        f'    var compName = "{character_name}_comp";',
        '    var comp = app.project.items.addComp(compName, 1920, 1080, 1, 5, 24);',
        '',
    ]

    # Import AI file as footage
    if image_source:
        jsx_lines.extend([
            f'    // Import source file',
            f'    var aiFile = new File("{image_source}");',
            '    if (aiFile.exists) {',
            '        var importOpts = new ImportOptions(aiFile);',
            '        importOpts.importAs = ImportAsType.COMP_CROPPED_LAYERS;',
            '        var imported = app.project.importFile(importOpts);',
            '    }',
            '',
        ])

    # Create null objects for each joint
    for joint_name, joint_data in joints.items():
        pos = joint_data.get("position", [0, 0])
        x = pos[0] if len(pos) > 0 else 0
        y = pos[1] if len(pos) > 1 else 0
        jsx_lines.extend([
            f'    // Joint: {joint_name}',
            f'    var null_{joint_name.replace("-", "_")} = comp.layers.addNull();',
            f'    null_{joint_name.replace("-", "_")}.name = "{joint_name}";',
            f'    null_{joint_name.replace("-", "_")}.position.setValue([{x}, {y}]);',
            '',
        ])

    # Set up parenting from bones
    for bone in bones:
        parent = bone.get("parent_joint", "")
        child = bone.get("child_joint", "")
        if parent and child:
            p_var = f'null_{parent.replace("-", "_")}'
            c_var = f'null_{child.replace("-", "_")}'
            jsx_lines.extend([
                f'    // Bone: {parent} -> {child}',
                f'    try {{ {c_var}.parent = {p_var}; }} catch(e) {{}}',
                '',
            ])

    # Apply keyframes from poses
    if poses:
        jsx_lines.append('    // Keyframes from saved poses')
        for frame_idx, (pose_name, pose_data) in enumerate(poses.items()):
            time_val = frame_idx * 1.0  # 1 second per pose
            if isinstance(pose_data, dict):
                for joint_name, angle in pose_data.items():
                    if isinstance(angle, (int, float)):
                        var_name = f'null_{joint_name.replace("-", "_")}'
                        jsx_lines.extend([
                            f'    try {{',
                            f'        {var_name}.rotation.setValueAtTime({time_val}, {angle});',
                            f'    }} catch(e) {{}}',
                        ])

    jsx_lines.extend([
        '',
        '    app.endUndoGroup();',
        '})();',
    ])

    return '\n'.join(jsx_lines)


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def prepare_ae_export(rig: dict, output_dir: str) -> dict:
    """Export everything AE needs: rig JSON, import JSX, and manifest.

    Steps:
        1. Create the output directory
        2. Export rig as JSON (joints, hierarchy, pivots, constraints, poses, timeline)
        3. Generate an AE import script (JSX)
        4. Write manifest listing all exported files

    Args:
        rig: character rig dict
        output_dir: directory for exported files

    Returns:
        Manifest dict listing all exported files and metadata.
    """
    character_name = rig.get("character_name", "character")
    os.makedirs(output_dir, exist_ok=True)

    manifest_files = []

    # 1. Export rig JSON
    rig_json_path = os.path.join(output_dir, f"{character_name}_rig.json")
    rig_export = {
        "character_name": character_name,
        "joints": rig.get("joints", {}),
        "bones": rig.get("bones", []),
        "landmarks": rig.get("landmarks", {}),
        "axes": rig.get("axes", {}),
        "bindings": rig.get("bindings", {}),
        "poses": rig.get("poses", {}),
        "image_source": rig.get("image_source"),
        "image_size": rig.get("image_size"),
        "object_type": rig.get("object_type"),
    }
    with open(rig_json_path, "w") as f:
        json.dump(rig_export, f, indent=2)
    manifest_files.append({
        "type": "rig_json",
        "path": rig_json_path,
        "description": "Character rig data (joints, hierarchy, pivots, poses)",
    })

    # 2. Generate AE import JSX
    jsx_path = os.path.join(output_dir, f"{character_name}_ae_import.jsx")
    jsx_code = _generate_ae_jsx(rig, rig_json_path)
    with open(jsx_path, "w") as f:
        f.write(jsx_code)
    manifest_files.append({
        "type": "ae_import_jsx",
        "path": jsx_path,
        "description": "After Effects import script",
    })

    # 3. Check for storyboard panels to export
    flipbook = rig.get("flipbook")
    if flipbook:
        panels_note = os.path.join(output_dir, f"{character_name}_panels.txt")
        with open(panels_note, "w") as f:
            f.write(f"Flipbook with {flipbook.get('frame_count', 0)} frames\n")
            for ab in flipbook.get("artboards", []):
                f.write(f"  Frame {ab['index']}: {ab['pose_name']} at {ab['artboard_rect']}\n")
        manifest_files.append({
            "type": "panel_notes",
            "path": panels_note,
            "description": "Flipbook panel reference",
        })

    # 4. Write manifest
    manifest_path = os.path.join(output_dir, f"{character_name}_manifest.json")
    manifest = {
        "character_name": character_name,
        "output_dir": output_dir,
        "files": manifest_files,
        "file_count": len(manifest_files),
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest


def export_manifest(output_dir: str) -> dict:
    """List what was previously exported to a directory.

    Scans the output directory for manifest files and returns their contents.

    Args:
        output_dir: directory to check for exports

    Returns:
        Dict with found manifest data, or error if directory doesn't exist.
    """
    if not os.path.isdir(output_dir):
        return {"error": f"Directory not found: {output_dir}", "files": []}

    # Find manifest files
    manifests = []
    for filename in sorted(os.listdir(output_dir)):
        if filename.endswith("_manifest.json"):
            manifest_path = os.path.join(output_dir, filename)
            with open(manifest_path) as f:
                manifests.append(json.load(f))

    # Also list all files in the directory
    all_files = sorted(os.listdir(output_dir))

    return {
        "output_dir": output_dir,
        "manifests": manifests,
        "all_files": all_files,
        "total_files": len(all_files),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_smart_export tool."""

    @mcp.tool(
        name="adobe_ai_smart_export",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_smart_export(params: AiSmartExportInput) -> str:
        """Export everything After Effects needs in one call.

        Actions:
        - prepare_ae_export: export rig JSON, AE import JSX, and manifest
        - export_manifest: list previously exported files
        """
        action = params.action.lower().strip()

        if action == "prepare_ae_export":
            rig = _load_rig(params.character_name)
            result = prepare_ae_export(rig, params.output_dir)
            return json.dumps(result)

        elif action == "export_manifest":
            result = export_manifest(params.output_dir)
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
