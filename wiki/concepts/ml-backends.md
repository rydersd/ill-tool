# ML Backends

> Brief: Optional ML models — SDPose (pose), CartoonSeg (segmentation), DiffVG (differentiable rendering), TRELLIS.2 (3D reconstruction).
> Tags: ml, sdpose, cartoonseg, diffvg, trellis, triposr
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Track which ML models are integrated, what they do, and how they're used in the pipeline.

## Models

### Pose Detection
- **SDPose** — 133-keypoint cartoon pose detection. Used by `landmark_ml` tool.

### Segmentation
- **CartoonSegmentation** — Instance segmentation for cartoon/illustration images. Used by `segment_ml` tool.

### Differentiable Rendering
- **DiffVG** — Differentiable vector graphics renderer. Enables gradient descent on SVG paths. Used by `diffvg_correct` tool. Falls back to finite-difference approximation via `path_gradient_approx` when DiffVG unavailable.

### 3D Reconstruction
- **TRELLIS.2** — Single-image-to-3D mesh reconstruction. Primary backend for spatial pipeline. Used by `reconstruct_3d_trellis`.
- **TripoSR** — Fast 0.5s mesh generation. Used by `reconstruct_3d_quick`.
- **InstantMesh** — Two-stage quality mesh reconstruction. Used by `reconstruct_3d_quality`.
- **StdGEN** — Semantic decomposition of characters. Used by `character_3d`.
- **CharacterGen** — A-pose normalization. Used by `character_apose`.

### Animation Bridges
- **Meta Animated Drawings** — Bridge to Meta's cartoon animation system. Used by `animated_drawings_bridge`.

## Dependency Groups

```toml
[project.optional-dependencies]
ml = ["torch>=2.0", "torchvision>=0.15", "transformers>=4.40"]
ml-diffvg = ["torch>=2.0"]
ml-3d = ["torch>=2.0", "trimesh>=4.0", "open3d>=0.18"]
ml-trellis = ["torch>=2.0", "trimesh>=4.0"]
```

## See Also
- [[Spatial 3D-to-2D Pipeline]]
- [[Tool Inventory]]
