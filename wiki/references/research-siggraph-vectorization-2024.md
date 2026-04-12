# SIGGRAPH Papers Relevant to IllTool

> Brief: Curated list of SIGGRAPH/TOG/CVPR papers (2020-2025) that could directly enhance IllTool's vectorization, perspective, depth, and cleanup pipelines.
> Tags: siggraph, vectorization, depth, perspective, line-art, ml, onnx, research
> Created: 2026-04-11
> Updated: 2026-04-11

## Motivation

Surveyed the research frontier to identify papers that could level up IllTool's core capabilities. Focused on papers with available code/models that could run on-device via ONNX Runtime with CoreML EP.

## Tier 1 — High Impact, Integrable Now

### Deep Sketch Vectorization via Implicit Surface Extraction
- **Authors**: Yan, Li, Aneja, Fisher, Simo-Serra, Gingold (Adobe Research)
- **Venue**: SIGGRAPH 2024 (TOG 43:4)
- **What**: Treats sketch vectorization as UDF extraction + neural dual contouring. Messy sketch -> clean bezier paths with interactive topology refinement.
- **Integration**: Core upgrade to trace pipeline. UDF network is ONNX-exportable. Would replace vtracer for sketch inputs.
- **Code**: https://github.com/Nauchcnay/Deep-Sketch-Vectorization
- **License**: Check repo

### Bezier Splatting for Fast and Differentiable Vector Graphics
- **Authors**: Liu, Zhou, Zhao, Huang (Adobe Research)
- **Venue**: NeurIPS 2025
- **What**: Samples 2D Gaussians along Bezier curves. 30-150x faster than DiffVG for forward/backward passes.
- **Integration**: Drop-in DiffVG replacement for trace optimization loop.
- **Code**: https://xiliu8006.github.io/Bezier_splatting_project/

### StripMaker: Perception-driven Learned Vector Sketch Consolidation
- **Authors**: Liu, Aoki, Bessmeltsev, Sheffer
- **Venue**: SIGGRAPH 2023 (TOG 42:4)
- **What**: Replaces groups of overdrawn strokes with single intended curves.
- **Integration**: Pen tool cleanup — consolidate messy strokes into production curves.
- **Code**: https://www.cs.ubc.ca/labs/imager/tr/2023/stripmaker/

### SSI Depth (Scale-Invariant Monocular Depth)
- **Authors**: Miangoleh, Reddy, Aksoy
- **Venue**: SIGGRAPH 2024
- **What**: Decomposes metric depth into normalized depth + scale features. Trains on synthetic, generalizes in-the-wild.
- **Integration**: Lighter alternative to Metric3D, or ensemble candidate. PyTorch model exportable to ONNX.
- **Code**: https://github.com/compphoto/SIDepth

## Tier 2 — High Impact, More Work

### LayerPeeler: Autoregressive Peeling for Layer-wise Image Vectorization
- **Venue**: SIGGRAPH Asia 2025
- **What**: Progressively peels and vectorizes layers from front to back, recovering occluded content. Layer-separated vector output matching Illustrator's layer model.
- **Code**: https://layerpeeler.github.io/

### Image Vectorization via Linear Gradient Layer Decomposition
- **Authors**: Du, Kang, Tan, Gingold, Xu
- **Venue**: SIGGRAPH 2023 (TOG 42:4)
- **What**: Decomposes raster images into layered vector regions with linear gradient fills.
- **Code**: https://github.com/Zhengjun-Du/ImageVectorViaLayerDecomposition

### Robust Symmetry Detection via Riemannian Langevin Dynamics
- **Venue**: SIGGRAPH Asia 2024
- **What**: Detects symmetry planes in 3D meshes from image-to-mesh outputs. Could detect bilateral symmetry in AI-generated concept art.
- **Code**: https://symmetry-langevin.github.io/

## Tier 3 — Reference / Evaluation

### A Benchmark for Rough Sketch Cleanup
- **Venue**: SIGGRAPH Asia 2020 (TOG 39:6)
- **What**: 281 real sketches with professional artist ground-truth cleanups.
- **Use**: Evaluation dataset for trace/cleanup pipeline quality.
- **Data**: https://cragl.cs.gmu.edu/sketchbench/

### SGLIVE (Segmentation-Guided Layer-wise Image Vectorization)
- **Venue**: ECCV 2024
- **What**: Gradient-aware segmentation guiding concise bezier path generation with radial gradients.
- **Code**: https://github.com/Rhacoal/SGLIVE

## Key Decisions

- **Priority**: Deep Sketch Vectorization is the highest-value target (UDF net exports to ONNX, directly improves core trace pipeline)
- **Bezier Splatting**: Second priority — massive speedup for DiffVG optimization, already referenced in codebase
- **Symmetry**: No great ML solution yet — custom flip+correlate approach is probably better for our specific use case (Midjourney cleanup)

## See Also

- [[../concepts/vision-intelligence.md]] — current ML pipeline (Depth Anything V2 + Metric3D)
- Memory: `reference_ml_models.md` — existing model inventory
