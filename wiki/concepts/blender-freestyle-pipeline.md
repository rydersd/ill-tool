# Blender Freestyle → IllTool Pipeline

> Brief: Ground-truth render passes from Blender replace ML inference for Freestyle line art cleanup. Camera matrix, depth, normals, object IDs — all exact.
> Tags: blender, freestyle, pipeline, render-passes, exr, camera, depth, normals, cleanup
> Created: 2026-04-11
> Updated: 2026-04-11

## Motivation

Freestyle SVG from Blender is messy — overlapping strokes, gaps at intersections, variable width from distance, redundant edges. IllTool already estimates depth, normals, and vanishing points with ML, but Blender has **ground truth** for all of these. Using render passes instead of inference is faster, exact, and eliminates estimation errors.

## Overview

### What Blender provides (ground truth)

| Render Pass | What IllTool currently estimates with ML | Benefit |
|---|---|---|
| Z-Depth | Metric3D v2 (~0.3s inference) | Exact depth, zero latency |
| Normal | Metric3D normals / Sobel | Exact surface orientation |
| Camera matrix | Hough + clustering VP detection | Exact perspective grid, no tweaking |
| Object Index | Vision framework segmentation | Exact object boundaries |
| Material Index | (not estimated) | Surface type per pixel |
| Freestyle line types | (not available) | Silhouette vs crease vs boundary |

### Data flow

```
Blender renders:
  → Freestyle SVG (line art paths with type tags)
  → EXR multi-pass (depth, normals, object ID, material ID)
  → Camera JSON (matrix, focal length, sensor size)

IllTool imports:
  → SVG paths via existing parser (TraceVector.cpp)
  → EXR passes into VisionEngine (new: tinyexr reader)
  → Camera → PerspectiveModule (bypass VP detection entirely)
  → Per-path: sample depth/normal/objectID → auto-assign layers
  → Stroke consolidation using object ID grouping
  → Gap closing using normal plane continuity
```

## Blender Render Config

A Python script or Blender addon that auto-configures:

```python
# illtool_render_setup.py — run in Blender to configure passes
import bpy

scene = bpy.context.scene
rl = scene.view_layers[0]

# Enable required render passes
rl.use_pass_z = True              # Depth
rl.use_pass_normal = True         # Surface normals
rl.use_pass_object_index = True   # Object ID
rl.use_pass_material_index = True # Material ID

# Enable Freestyle SVG export
scene.render.use_freestyle = True
rl.freestyle_settings.as_render_pass = False  # separate SVG output

# Configure output
scene.render.image_settings.file_format = 'OPEN_EXR_MULTILAYER'
scene.render.image_settings.color_depth = '32'
scene.render.filepath = '//render/illtool_'

# Enable Freestyle SVG addon
bpy.ops.preferences.addon_enable(module='render_freestyle_svg')

# Export camera data as JSON sidecar
import json, mathutils
cam = scene.camera
if cam:
    cam_data = {
        'matrix_world': [list(row) for row in cam.matrix_world],
        'focal_length': cam.data.lens,
        'sensor_width': cam.data.sensor_width,
        'sensor_height': cam.data.sensor_height,
        'clip_start': cam.data.clip_start,
        'clip_end': cam.data.clip_end,
        'resolution_x': scene.render.resolution_x,
        'resolution_y': scene.render.resolution_y,
    }
    with open(bpy.path.abspath('//render/camera.json'), 'w') as f:
        json.dump(cam_data, f, indent=2)
```

## IllTool Integration Path

### Phase 1: Camera import (shortest path to value)
- Parse camera.json → compute VP positions from projection matrix
- Set PerspectiveModule grid directly (bypass EstimateVanishingPoints)
- ~50 LOC in PerspectiveAutoMatch.cpp

### Phase 2: EXR reader
- Add tinyexr (BSD, header-only, ~1200 LOC) to vendor/
- Load depth + normal + object ID channels into VisionEngine
- Same buffer interface as ML inference outputs
- ~200 LOC

### Phase 3: Freestyle SVG enhanced import
- Parse Freestyle line type attributes from SVG (silhouette, crease, border, material_boundary)
- Route to different layers with different stroke weights
- ~100 LOC in TraceVector.cpp

### Phase 4: Object-ID-driven cleanup
- Sample object ID pass at path midpoint → assign to layer by object name
- Merge overlapping strokes with same object ID
- Close gaps between stroke endpoints on same normal plane
- ~300 LOC (new cleanup pipeline)

## Dependencies

| Library | License | Size | Purpose |
|---|---|---|---|
| tinyexr | BSD-3-Clause | ~1200 LOC header-only | EXR multi-pass reader |

## Key Decisions

- **EXR over PNG sequences**: Multi-layer EXR is one file with all passes. PNG sequences require multiple files and lose float precision.
- **Camera JSON sidecar**: Blender's camera matrix is 4x4 world-space. Computing VPs from projection matrix is straightforward linear algebra.
- **tinyexr over OpenEXR**: Header-only, BSD license, no build dependencies. OpenEXR is heavy and LGPL.

## See Also

- [[blender-mcp-integration]] — existing Blender MCP tools
- [[vision-intelligence]] — current ML pipeline that this replaces for Blender sources
- Memory: `project_blender_pipeline.md` — project-level tracking
