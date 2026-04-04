# Normal Map as Shadow-Free Reference

> Brief: Use ML-predicted surface normals to generate 15 shadow-free renderings that improve every existing tool without modification — the architectural centerpiece of the lightweight form extraction pipeline. Now with full differential geometry via shape operator eigendecomposition.
> Tags: normals, shadow-free, reference, preprocessing, dsine, architecture, eigendecomposition
> Created: 2026-04-03
> Updated: 2026-04-04

## Motivation

The shadow-vs-form problem blocked accurate illustration from reference images. The original solution (TRELLIS.2 full 3D reconstruction) works but requires CUDA and is heavyweight. The key insight: **surface normal maps encode surface orientation, and shadows don't change surface orientation.** By predicting normals from a single image, we get a complete shadow-free understanding of form that every existing tool can exploit.

## Overview

Instead of building a parallel pipeline, this is a **preprocessor**. One DSINE prediction generates five shadow-free renderings. Every existing tool (contour scanner, tonal analyzer, constraint solver, drawing orchestrator, compare drawing, auto correct, feedback loop) can consume these renderings as their reference image — improving without modification.

## The Five Renderings

| Rendering | Technique | What It Shows | Best For |
|-----------|-----------|---------------|----------|
| **Flat Planes** | K-means on normal vectors | Major structural planes as flat colors | `tonal_analyzer`, plane identification |
| **Form Lines** | Sobel on normal channels | Pure form edges, zero shadows | `contour_scanner`, `contour_to_path` |
| **Curvature** | Spatial derivatives of normal field | Where surfaces bend | `contour_labeler`, ridge/valley detection |
| **Re-lit Reference** | albedo x dot(normal, light_dir) | Shadow-free "clean" version | `compare_drawing`, `auto_correct` |
| **Depth Edges** | Normal discontinuity detection | Occlusion contours only | `silhouette`, boundary detection |

## Architecture

```
Original Reference Image
    → DSINE (1GB, MPS-native, ~1s)
    → Normal Map (HxWx3 float32)
    → 5 Renderings (pure numpy/OpenCV, instant)
    → Place as locked hidden layers in Illustrator
    → Claude picks the best rendering per task
    → Existing tools consume shadow-free input
```

## Implementation

Three modules:
- `ml_backends/normal_estimator.py` — DSINE wrapper (lazy load, device selection, MPS-native)
- `normal_renderings.py` — Pure numpy rendering functions (zero ML deps)
- `normal_reference.py` — MCP tool (`adobe_ai_normal_reference`) with generate/place/status actions

Plus the form edge extraction tool:
- `form_edge_pipeline.py` — Pure Python: heuristic backend + DSINE backend + contour extraction
- `form_edge_extract.py` — MCP tool (`adobe_ai_form_edge_extract`) with extract/place/compare actions

## Key Design Decisions

1. **Preprocessor, not parallel pipeline**: One step improves 245+ tools vs building a competing path
2. **DSINE over Marigold**: Smaller (1GB vs 4GB), faster, explicit MPS support, torch.hub load
3. **Renderings are pure numpy**: Only the normal prediction needs ML; all post-processing is always available
4. **Heuristic fallback**: Multi-exposure Canny voting works without any ML — always available
5. **Layered in Illustrator**: Renderings placed as locked hidden reference layers, selectable by Claude

## Why Not Just 3D Reconstruction?

| | TRELLIS.2 | Normal Map Reference |
|---|---|---|
| Runs on Mac | No (CUDA-only) | Yes (MPS) |
| Speed | 3-10s | ~1s |
| GPU memory | 24GB+ VRAM | ~1GB |
| Shadow elimination | Perfect | Very good |
| Novel viewpoints | Yes | No |
| Tools improved | Only spatial_pipeline | All 245+ |

## Test Coverage

166 tests across 5 test files covering:
- All rendering functions with synthetic normal maps
- DSINE loading, inference, and device selection
- MCP tool actions, JSX generation, error handling
- Coordinate transforms, contour extraction, edge quality
- Graceful fallback when ML unavailable

## Expansion: Full Differential Geometry (2026-04-04)

The original 5 renderings used only `det(S)` of the shape operator. Eigendecomposing S yields principal curvatures (κ1, κ2), mean curvature (H), principal directions (eigenvectors), and surface type classification — 10 additional renderings with zero extra ML cost. See [[Expanded Normal Renderings]] for the full set.

Key additions:
- **Normal sidecar file**: per-path surface metadata written by form_edge_extract
- **Form-aware Smart Merge**: merge decisions weighted by surface coherence
- **Auto line weight**: strokeWidth varies by curvature (silhouettes thickest, ridges thinnest)
- **Cross-contour guides**: streamlines along principal directions as locked guide paths

## See Also
- [[Expanded Normal Renderings]] — The 10 new eigendecomposition-derived renderings
- [[Smart Merge Architecture]] — Form-aware merge using normal sidecar
- [[Shadow vs Form Problem]]
- [[Spatial 3D-to-2D Pipeline]]
- [[ML Backends]]
- [[Form Understanding Without Reconstruction]]
