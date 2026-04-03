# Spatial AI Research Report: 2025-2026 State of the Art

> Brief: Full survey of 30+ systems — single-image-to-3D, LLM mesh generation, image-to-SVG, spatial grounding, and implementation results.
> Tags: research, spatial-ai, papers, 3d-reconstruction, survey, trellis, sam3d, diffvg
> Created: 2026-04-03
> Updated: 2026-04-03
> Migrated from: docs/research/spatial-ai-state-of-art-2026.md, docs/spatial-ai-research-2026.md

**Research date**: 2026-03-26
**Scope**: Systems that reconstruct 3D form from 2D images, follow instructions to manipulate spatial/visual output, and produce structured geometric output (coordinates, meshes, vector paths).
**Source count**: 20+ web searches across academic papers, startup announcements, product launches, blog posts, and demos.

---

## Executive Summary

The spatial AI landscape in 2025-2026 has undergone a category-level shift. What was research-only territory 18 months ago is now productized across multiple companies. The key developments:

1. **Single-image-to-3D is production-ready** -- Tripo, Meshy, TRELLIS.2, Hunyuan3D, and SAM 3D all produce usable meshes from a single photo in seconds.
2. **LLMs can now generate 3D meshes as text** -- LLaMA-Mesh and MeshLLM represent meshes in OBJ format as plain text tokens, letting language models reason about and generate 3D geometry.
3. **Image-to-SVG is a solved problem for icons/illustrations** -- OmniSVG and StarVector produce vector output from images, but are trained primarily on icons/illustrations, not mechanical/architectural subjects.
4. **The gap you need filled (isometric mechanical face tracing) has no single solution** -- but a pipeline combining 2-3 existing systems gets close.

---

## 1. Vision Controllers That Reconstruct Form From Instruction

### Models that take image + text instruction and produce structured 3D or vector output

**Chat2SVG** (CVPR 2025) -- The closest match to "image + instruction = structured output"
- Pipeline: LLM generates SVG template from primitives --> SDEdit/ControlNet enhances visually --> dual-stage optimization refines paths
- Supports iterative refinement through natural language: "make the top face wider", "add a bevel edge"
- Output: Clean SVG paths with Bezier curves
- Limitation: Trained on icons/logos, not mechanical drawings
- Trust: 0.90 (peer-reviewed CVPR, code available)
- Source: [Chat2SVG](https://chat2svg.github.io/)

**OmniSVG** (NeurIPS 2025) -- Unified multimodal SVG generation
- Built on Qwen-VL vision-language model
- Supports text-to-SVG, image-to-SVG, and character-reference SVG
- Generates up to 30,000-token SVG sequences (complex illustrations)
- Trained on MMSVG-2M dataset (2 million annotated SVGs across icons, illustrations, characters)
- Best FID score of 145.89, significantly outperforming VectorFusion (218.76) and SVGDreamer (193.42)
- Trust: 0.92 (NeurIPS, comprehensive benchmark, code + weights released)
- Source: [OmniSVG](https://omnisvg.github.io/)

**StarVector** (CVPR 2025) -- Multimodal image/text to SVG code
- Architecture based on StarCoder (code generation LLM)
- Image projected into visual tokens by visual encoder, then generates SVG code
- Handles icons, logos, and technical diagrams
- Trust: 0.88 (CVPR, HuggingFace weights available)
- Source: [StarVector on HuggingFace](https://huggingface.co/starvector/starvector-8b-im2svg)

**Img2CAD** -- Image to parametric CAD via structured visual geometry
- First system to generate editable parametric CAD models from single 2D images
- Introduces "Structured Visual Geometry" (SVG) -- vectorized wireframe extracted from objects as intermediate representation
- Outputs sketch + extrusion operations parseable by CAD kernels (B-Rep format)
- Two new datasets: ABC-mono (200K+ CAD models) and KOCAD (real-world captures with ground truth)
- HIGHLY RELEVANT to our use case -- closest to "see reference, produce construction geometry"
- Trust: 0.85 (published IEEE, novel approach, but early-stage)
- Source: [Img2CAD paper](https://arxiv.org/abs/2410.03417)

**Zoo.dev Text-to-CAD** -- Production text-to-parametric-CAD service
- Generates B-rep CAD models + parametric KCL code from text prompts
- Tuned for mechanical components (CNC milling, 3D printing)
- Free tier available (40 credits/month), API accessible
- Trust: 0.82 (commercial product, real users, but text-only input)
- Source: [Zoo.dev Text-to-CAD](https://zoo.dev/text-to-cad)

### Models combining LLM reasoning with precise spatial output

**LLaMA-Mesh** (NVIDIA, NeurIPS 2024 / published March 2025)
- Represents OBJ vertex coordinates and face definitions as plain text
- Fine-tuned on LLaMA-3.1-8B-Instruct
- Quality on par with purpose-built models
- Trust: 0.88 (NVIDIA Research, peer-reviewed)
- Source: [LLaMA-Mesh](https://research.nvidia.com/labs/toronto-ai/LLaMA-Mesh/)

**MeshLLM** (ICCV 2025) -- Outperforms LLaMA-Mesh
- Progressive training: primitive decomposition --> local assembly --> full generation
- 1500K+ training samples (50x larger than previous methods)
- Retains dialogue abilities alongside mesh generation
- Trust: 0.90 (ICCV, code released, benchmark-validated)
- Source: [MeshLLM](https://arxiv.org/abs/2508.01242)

**SpatialLLM** (CVPR 2025) -- 3D-informed multimodal LLM
- Studies impact of 3D-informed data, architecture, and training on spatial reasoning
- Trust: 0.87 (CVPR)
- Source: [SpatialLLM](https://3d-spatial-reasoning.github.io/spatial-llm/)

---

## 2. Spatial AI Labs / Companies to Watch

### Tier 1: Major Players

| Company | Product | Funding | Relevance | Trust |
|---------|---------|---------|-----------|-------|
| **World Labs** (Fei-Fei Li) | Marble -- navigable 3D worlds | $1.23B+ | Low-medium (environment-level) | 0.94 |
| **Google DeepMind** | Genie 3 -- interactive environments 24fps/720p | - | Low (environment-level) | 0.95 |
| **Meta AI** | SAM 3D + WorldGen + 3D AssetGen | - | **HIGH for SAM 3D** | 0.93 |
| **Anthropic (Claude)** | Vision capabilities | - | Medium (reasoning, not coordinates) | 0.95 |

### Tier 2: Focused Companies

| Company | Product | Speed | Relevance | Trust |
|---------|---------|-------|-----------|-------|
| **Microsoft TRELLIS.2** | 4B param image-to-3D, 512^3 | ~3s | **HIGH** -- sharp features, open source | 0.90 |
| **Tencent Hunyuan3D** | DiT mesh + PBR textures | ~10s | **HIGH** -- solves Janus problem | 0.88 |
| **Tripo AI** | Image-to-3D API v2.5 | ~10s | **HIGH** -- fast API, 6.5M+ creators | 0.88 |
| **Meshy AI** | Meshy 6, 97% slicer compat | ~30s | Medium (softens geometric edges) | 0.85 |
| **SpAItial** | Spatial Foundation Models | TBD | High potential, no product yet | 0.80 |
| **Luma AI** | Ray2, Dream Machine | - | Low (multi-view, video-first) | 0.85 |
| **Runway** | GWM-1 world model | - | Low (environment-level) | 0.85 |

---

## 3. Single-Image-to-3D Leaderboard (March 2026)

| Model | Speed | Quality | Sharp Features | Open Source | API |
|-------|-------|---------|----------------|-------------|-----|
| **TRELLIS.2** | ~3s (512^3) | Excellent | Yes | Yes | No |
| **Hunyuan3D 2.1/3.0** | ~10s | Excellent | Good | Yes | No |
| **SAM 3D** | ~15s | Excellent (real-world) | Good | Yes | Playground |
| **Tripo v2.5** | ~10s | Very Good | Moderate | TripoSR only | Yes |
| **Meshy 6** | ~30s | Very Good | Moderate (softened) | No | Yes |
| **InstantMesh** | ~10s | Good | Good | Yes | No |
| **TripoSR** | <0.5s | Good (Objaverse-like) | Moderate | Yes | No |
| **Wonder3D** | 2-3min | Good (texture quality) | Moderate | Yes | No |

### Key findings

1. **No single method dominates all metrics**. Pareto-optimal across quality dimensions.
2. **3D Gaussian Splatting (3DGS) is the dominant paradigm**, replacing NeRF for single-image tasks.
3. **Solved for organic shapes**. Mechanical/geometric objects with precise edges remain harder.
4. **Mesh-to-2D-outlines is classical and reliable**: trimesh silhouette projections, ShapeMeshing (SIGGRAPH Asia 2025), standard visibility algorithms.

---

## 4. Vision-Language Models with Spatial Grounding

**Qwen3-VL** (Alibaba) -- STRONGEST spatial grounding
- Absolute pixel-coordinate output in JSON
- 2D + 3D grounding, outperforms Gemini 2.5 Pro and Claude Opus 4.1
- Pipes into SAM2 for segmentation masks
- Trust: 0.90 | Sources: [GitHub](https://github.com/QwenLM/Qwen3-VL), [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-VL-72B-Instruct)

**Grounded SAM 2** (IDEA Research) -- Detection + Segmentation
- Grounding DINO + SAM 2 for text-grounded precise masks
- Trust: 0.92 | Source: [GitHub](https://github.com/IDEA-Research/Grounded-SAM-2)

**Florence-2** (Microsoft) -- Zero-shot multimodal grounding
- Trust: 0.88 | Source: [Comparison](https://roboflow.com/compare/florence-2-vs-grounding-dino)

### No model directly outputs vector paths from text

Pipeline: VLM -> bounding boxes -> SAM 2 -> masks -> contour extraction -> Bezier fitting

**DiffVG** remains the foundation for differentiable vector optimization (used in Chat2SVG, PyTorch-SVGRender).

**Bezier Splatting** (2025) is 30-150x faster than DiffVG via Gaussian splatting-based rasterization. Source: [arXiv](https://arxiv.org/abs/2503.16424)

---

## 5. The Specific Gap & Recommended Pipeline

### Why no single system does isometric mechanical face tracing

2D edge detection cannot distinguish form edges from shadow edges from material edges. Requires 3D understanding.

### Recommended: Option A — Full 3D Reconstruction Pipeline

```
Reference Image --> TRELLIS.2 --> 3D Mesh
                                    |
                    Face grouping by normals (front/side/top)
                                    |
                    Per-face-group 2D projection
                                    |
                    Vectorize contours (potrace/vtracer)
                                    |
                    Optimize (DiffVG / Bezier Splatting)
                                    |
                    Overlay verification against reference
```

### Confidence Assessment

| Step | Confidence |
|------|-----------|
| Mesh reconstruction | 85% |
| Face grouping | 70% |
| Vector path quality | 75% |
| End-to-end automation | 50% |

---

## 6. Implementation Results (March 2026)

### What We Built

Implemented Option A with:
1. **TRELLIS.2** for mesh reconstruction
2. **Custom mesh face grouper** — clusters by normals, extracts boundaries, projects to 2D
3. **Path gradient approximation** — pure-Python DiffVG fallback (finite-difference gradients + OpenCV)
4. **Self-correcting feedback loop** — correction deltas stored per-run, pre-applied to future runs

### Key Implementation Findings

1. **Research was right about LLM coordinate precision.** Seven trace attempts scored 0-0.3/10. Constraint pipeline found 14K correct form edges but assembled them into 0/10 trace. Assembly is spatial reasoning the LLM can't do.

2. **3D approach eliminates shadow-vs-form by construction.** Meshes have geometry, not lighting. Face grouping by normals produces exactly the planes an illustrator would identify.

3. **Evaluator calibration > pipeline sophistication.** Initial multi-factor scorer gave 4.6/10 on 0.3/10 work. Hausdorff pixel deviation gives honest scores. Can't improve what you can't measure.

4. **Feedback loop is novel and works on synthetic data.** DWPose correction pattern extended to face boundaries. Each run improves the next. Awaiting real-image validation.

5. **Pure-Python fallbacks essential.** DiffVG C++ compilation fails on macOS ARM. Finite-difference approximation is 100x slower but always available.

### Pipeline Architecture (Implemented)

```
Reference Image -> TRELLIS.2 -> 3D Mesh
                                  |
                  Face grouping by normals (pure Python + optional trimesh)
                                  |
                  2D projection (orthographic, camera yaw/pitch)
                                  |
                  Pre-apply stored correction deltas
                                  |
                  Score against reference (Hausdorff distance)
                                  |
                  Gradient optimization (DiffVG or finite-difference fallback)
                                  |
                  Store correction deltas for future runs
                                  |
                  Place in Illustrator (contour_to_path + bezier_optimize)
```

### What's Left To Validate

- End-to-end tower retry with TRELLIS.2 model weights downloaded
- Whether MJ-rendered mechs (non-photorealistic) produce usable meshes
- Cross-image generalization of learned projection deltas
- Pipeline performance on subjects with complex topology

---

## Capability Summary Table

| Capability | Status | Best Tool | Confidence |
|-----------|--------|-----------|------------|
| Single image -> 3D mesh | **Production-ready** | TRELLIS.2, SAM 3D, Tripo | 0.90 |
| Text -> 3D mesh via LLM | **Working but limited** | MeshLLM, LLaMA-Mesh | 0.75 |
| Image -> SVG vectors | **Working for icons** | OmniSVG, StarVector | 0.85 |
| Text instruction -> SVG edits | **Working** | Chat2SVG | 0.80 |
| Image -> parametric CAD | **Experimental** | Img2CAD, Zoo Text-to-CAD | 0.65 |
| VLM spatial grounding | **Production-ready** | Qwen3-VL + SAM 2 | 0.90 |
| 3D mesh -> 2D vector outlines | **Classical, reliable** | trimesh + potrace | 0.95 |
| Shadow vs form edge distinction | **Requires 3D reconstruction** | No direct solution | N/A |
| Full pipeline: ref -> paths | **Possible with custom integration** | Multi-tool pipeline | 0.65 |

---

## Sources

Academic papers: Chat2SVG (CVPR 2025), OmniSVG (NeurIPS 2025), StarVector (CVPR 2025), Img2CAD (IEEE), LLaMA-Mesh (NeurIPS 2024), MeshLLM (ICCV 2025), SpatialLLM (CVPR 2025), Bezier Splatting (arXiv 2025), IJCAI 2025 spatial reasoning survey.

Products/platforms: TRELLIS.2 (Microsoft), Hunyuan3D (Tencent), SAM 3D (Meta), Tripo AI, Meshy AI, World Labs, Genie 3 (DeepMind), Qwen3-VL (Alibaba), Grounded SAM 2 (IDEA Research), Florence-2 (Microsoft), Zoo.dev, DiffVG, InstantMesh, TripoSR, Wonder3D.

## See Also
- [[Spatial 3D-to-2D Pipeline]]
- [[LLM Spatial Reasoning Limitations]]
- [[ML Backends]]
- [[Shadow vs Form Problem]]
- [[Constructive Drawing Methods]]
