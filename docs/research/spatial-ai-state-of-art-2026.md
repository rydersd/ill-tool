# Spatial AI Research Report: 2025-2026 State of the Art

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
- HIGHLY RELEVANT to our use case -- this is the closest to "see reference, produce construction geometry"
- Trust: 0.85 (published IEEE, novel approach, but early-stage)
- Source: [Img2CAD paper](https://arxiv.org/abs/2410.03417)

**Zoo.dev Text-to-CAD** -- Production text-to-parametric-CAD service
- Generates B-rep CAD models + parametric KCL code from text prompts
- Tuned for mechanical components (CNC milling, 3D printing)
- Free tier available (40 credits/month), API accessible
- Outputs editable parametric models, not meshes
- Trust: 0.82 (commercial product, real users, but text-only input -- no image input)
- Source: [Zoo.dev Text-to-CAD](https://zoo.dev/text-to-cad)

### Models combining LLM reasoning with precise spatial output

**LLaMA-Mesh** (NVIDIA, NeurIPS 2024 / published March 2025)
- Represents OBJ vertex coordinates and face definitions as plain text
- Fine-tuned on LLaMA-3.1-8B-Instruct
- Can generate meshes from text descriptions while maintaining language capabilities
- Quality on par with purpose-built models
- Trust: 0.88 (NVIDIA Research, peer-reviewed)
- Source: [LLaMA-Mesh](https://research.nvidia.com/labs/toronto-ai/LLaMA-Mesh/)

**MeshLLM** (ICCV 2025) -- Outperforms LLaMA-Mesh
- Progressive training strategy: primitive decomposition --> local assembly --> full generation
- Primitive-Mesh decomposition divides meshes into structurally meaningful subunits
- 1500K+ training samples (50x larger than previous methods)
- Retains dialogue abilities (Q&A, reasoning) alongside mesh generation
- Trust: 0.90 (ICCV, code released, benchmark-validated)
- Source: [MeshLLM](https://arxiv.org/abs/2508.01242)

**SpatialLLM** (CVPR 2025) -- 3D-informed multimodal LLM
- Studies impact of 3D-informed data, architecture, and training on spatial reasoning
- Addresses the limitation that most VLMs are biased toward 2D data
- Trust: 0.87 (CVPR)
- Source: [SpatialLLM](https://3d-spatial-reasoning.github.io/spatial-llm/)

---

## 2. Spatial AI Labs / Companies to Watch

### Tier 1: Major Players

**World Labs** (Fei-Fei Li) -- $1.23B+ total funding
- Product: **Marble** -- generates spatially consistent, navigable 3D worlds from text/images/video/panoramas
- Launched November 2025, World API available for developers
- $1B round in February 2026 with Autodesk as strategic investor ($200M)
- Focus: Large World Models (not object-level, but environment-level)
- Relevance to our work: Low-medium. World-scale, not object-level construction.
- Trust: 0.94 (major funding, shipping product, academic pedigree)
- Sources: [World Labs](https://www.worldlabs.ai/), [World API announcement](https://www.worldlabs.ai/blog/announcing-the-world-api), [TechCrunch on Marble](https://techcrunch.com/2025/11/12/fei-fei-lis-world-labs-speeds-up-the-world-model-race-with-marble-its-first-commercial-product/)

**Google DeepMind** -- Genie 3
- General purpose world model generating interactive environments at 24fps/720p
- Text prompts, images, or video as input --> navigable 3D worlds
- Supports "promptable world events" (change weather, add objects)
- Available to Google AI Ultra subscribers in US
- Relevance to our work: Low. Environment generation, not object construction.
- Trust: 0.95 (Google DeepMind, shipping to users)
- Sources: [Genie 3 blog](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/), [Project Genie](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/project-genie/)

**Meta AI** -- SAM 3D + WorldGen + 3D Gen
- **SAM 3D**: Single-image 3D reconstruction using segmentation masks + reconstruction backbone. Nearly 1M annotated images, 3M+ verified meshes. Open source.
- **WorldGen**: Text-to-traversable 3D world in ~5 minutes. Generates navigation meshes alongside visual geometry.
- **Meta 3D AssetGen**: Text-to-mesh with PBR materials (base color, roughness, metallic)
- Relevance to our work: **HIGH for SAM 3D**. Segment object in image --> reconstruct as mesh --> project to 2D outlines.
- Trust: 0.93 (Meta FAIR, open source, massive datasets)
- Sources: [SAM 3D](https://ai.meta.com/blog/sam-3d/), [WorldGen](https://www.meta.com/blog/worldgen-3d-world-generation-reality-labs-generative-ai-research/), [Meta 3D AssetGen](https://ai.meta.com/research/publications/meta-3d-assetgen-text-to-mesh-generation-with-high-quality-geometry-texture-and-pbr-materials/)

**Anthropic (Claude)** -- Vision capabilities
- Spatial reasoning remains a documented limitation: "may struggle with tasks requiring precise localization"
- Claude Opus 4.6 (current) has 1M token context and improved multi-step reasoning
- No bounding box / coordinate output capability (unlike Qwen-VL or Florence-2)
- Can reason about spatial relationships in images but cannot output pixel coordinates or vector paths
- Relevance to our work: Medium. Good for reasoning about what to trace, poor at producing coordinates.
- Trust: 0.95 (self-knowledge, documented limitations)
- Source: [Claude Vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)

### Tier 2: Focused Companies

**Tripo AI** -- $50M funding (March 2026, Alibaba + Baidu Ventures)
- 6.5M+ creators, 90K+ developers, ~100M 3D assets generated
- Image-to-3D in ~10 seconds via API (v2.5)
- Exports: GLB, FBX, OBJ, USD, STL
- Relevance to our work: **HIGH**. Fast image-to-mesh pipeline, API available.
- Trust: 0.88 (shipping product, massive user base)
- Sources: [Tripo AI](https://www.tripo3d.ai/), [Tripo funding announcement](https://www.prnewswire.com/news-releases/tripo-ai-announces-50-million-in-funding-and-new-models-for-production-ready-3d-generation-302724894.html)

**Meshy AI** -- Production 3D generation platform
- Meshy 6 (October 2025): "sculpting-level detail and studio-grade mesh fidelity"
- 97% slicer compatibility for 3D printing
- Text-to-3D, image-to-3D, multi-image-to-3D
- Known limitation: Mechanical/geometric objects may have softened edges
- Relevance to our work: Medium. Good general tool, but softens geometric edges.
- Trust: 0.85 (commercial product, tested by 3D printing community)
- Source: [Meshy AI](https://www.meshy.ai/)

**SpAItial** (Matthias Niessner, Synthesia co-founder) -- $13M seed (May 2025)
- Building "Spatial Foundation Models" -- AI that natively understands geometry, physics, materiality
- Team includes Ricardo Martin-Brualla (Google 3D teleconferencing) and David Novotny (Meta text-to-3D)
- Early stage -- demos shown but no public product yet
- Relevance to our work: High potential, but not yet available
- Trust: 0.80 (strong team, early stage, demo-only)
- Sources: [SpAItial announcement](https://www.spaitial.ai/blog/announcing-spaitial), [TechCrunch](https://techcrunch.com/2025/05/26/one-of-europes-top-ai-researchers-raised-a-13m-seed-to-crack-the-holy-grail-of-models/)

**Luma AI** -- Video and 3D
- Pivoted focus toward video generation (Ray2, Dream Machine, Photon)
- 3D capture requires multiple angles (not single-image)
- Interactive 3D Scenes for web embedding
- Relevance to our work: Low. Multi-view focus, video-first.
- Trust: 0.85 (shipping product)
- Source: [Luma AI](https://lumalabs.ai/)

**Runway** -- $315M funding (February 2026)
- GWM-1 world model for virtual environment generation
- Focus on creative tools and robotics simulation
- Relevance to our work: Low. Environment-level, not construction geometry.
- Trust: 0.85

**Microsoft TRELLIS.2** -- 4B parameter image-to-3D
- Generates meshes at 512^3 resolution in ~3 seconds
- Full PBR materials including transparency
- Handles complex topologies and sharp features
- Open source on GitHub
- Relevance to our work: **HIGH**. Fast, open source, handles sharp features.
- Trust: 0.90 (Microsoft Research, open source, benchmark-validated)
- Sources: [TRELLIS.2](https://microsoft.github.io/TRELLIS.2/), [GitHub](https://github.com/microsoft/TRELLIS.2)

**Tencent Hunyuan3D** -- 3M+ downloads on HuggingFace
- Two-stage: DiT generates bare mesh --> Hunyuan3D-Paint applies PBR textures
- Solves "Janus problem" (multi-faced objects)
- Multi-view input support (up to 4 images)
- Relevance to our work: **HIGH**. Open source, quality mesh generation.
- Trust: 0.88 (Tencent, open source, large community)
- Sources: [Hunyuan3D](https://hy-3d.com/), [GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)

---

## 3. Single-Image-to-3D: 2025 State of the Art

### Current Leaderboard (by practical usability)

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

1. **No single method dominates all metrics**. A 2025 comparative study found ViVid-1-to-3 achieves highest PSNR, Wonder3D highest SSIM, and Zero123++ lowest LPIPS. The landscape is Pareto-optimal across different quality dimensions.

2. **3D Gaussian Splatting (3DGS) has become the dominant paradigm**, largely replacing NeRF for single-image tasks due to faster training and rendering.

3. **The "mesh from single image" problem is effectively solved for organic shapes**. Characters, animals, furniture, and props produce reliable results. Mechanical/geometric objects with precise edges remain harder.

4. **Can these produce 2D outlines from the reconstructed mesh?** YES. Once you have a mesh:
   - Standard graphics pipeline: Project mesh from desired camera angle, extract silhouette edges
   - Tools like `trimesh` (Python) can compute silhouette projections
   - ShapeMeshing (SIGGRAPH Asia 2025) formalizes the pipeline: curve ingestion --> adaptive meshing --> projection
   - Classical algorithm: "A Visibility Algorithm for Converting 3D Meshes into Editable 2D Vector Graphics" computes occluding contours and generates line drawings

### Pipeline for our use case

```
Reference Image --> [TRELLIS.2 or SAM 3D] --> 3D Mesh
                                                  |
                                                  v
                    Set camera to match isometric angle
                                                  |
                                                  v
                    Extract visible face polygons per face group
                                                  |
                                                  v
                    Project to 2D --> silhouette/contour extraction
                                                  |
                                                  v
                    Vectorize contours --> SVG/AI paths
```

---

## 4. Vision-Language Models with Spatial Grounding

### Models that can point, segment, and localize based on text

**Qwen3-VL** (Alibaba, 2025-2026) -- STRONGEST spatial grounding
- Supports absolute pixel-coordinate output in JSON format
- 2D grounding: locates hundreds of objects with bounding boxes and points
- NEW: 3D grounding -- predicts real-world position, size, and depth
- Outperforms Gemini 2.5 Pro and Claude Opus 4.1 on most grounding metrics
- Can be piped into SAM2 for precise segmentation masks
- Trust: 0.90 (benchmark-validated, open weights)
- Sources: [Qwen3-VL GitHub](https://github.com/QwenLM/Qwen3-VL), [Qwen2.5-VL HuggingFace](https://huggingface.co/Qwen/Qwen2.5-VL-72B-Instruct)

**Grounded SAM 2** (IDEA Research) -- Detection + Segmentation pipeline
- Combines Grounding DINO (or Florence-2) for text-grounded detection with SAM 2 for segmentation
- Can process: "front face of the tower" --> bounding box --> precise mask
- Updated to V2 API (April 2025) with DINO-X models
- Pipelines: object detection, dense region caption, phrase grounding, referring expression segmentation
- Trust: 0.92 (widely used, open source)
- Source: [Grounded SAM 2](https://github.com/IDEA-Research/Grounded-SAM-2)

**Florence-2** (Microsoft) -- Zero-shot multimodal grounding
- Prompt-based system handling spatial hierarchy and semantic granularity
- Outputs: captions, bounding boxes, segmentation masks
- Integrates with SAM 2 for refined masks
- Trust: 0.88 (Microsoft, widely adopted)
- Source: [Florence-2 comparison](https://roboflow.com/compare/florence-2-vs-grounding-dino)

### Can any of these output vector paths?

**No model directly outputs vector paths from text instructions.** The pipeline is:

1. VLM (Qwen3-VL / Florence-2) --> bounding boxes or points (JSON coordinates)
2. SAM 2 --> pixel-level segmentation masks
3. **Contour extraction** (OpenCV `findContours`, or scikit-image `marching_squares`) --> polygon vertices
4. **Bezier fitting** (DiffVG optimization, or `potrace`/`vtracer` vectorization) --> smooth vector paths

The gap between "mask" and "construction-quality vector path" is where tools like **DiffVG** and **Bezier Splatting** come in:

**DiffVG** (still the foundation, 2020 --> used in 2025 CVPR papers)
- Differentiable rasterizer bridging raster and vector domains
- Used as optimization backend in Chat2SVG and PyTorch-SVGRender

**Bezier Splatting** (2025) -- 30-150x faster than DiffVG
- Optimizes Bezier curves through Gaussian splatting-based rasterization
- Drop-in replacement for DiffVG in optimization pipelines
- Trust: 0.85 (arXiv, benchmarked against DiffVG)
- Source: [Bezier Splatting paper](https://arxiv.org/abs/2503.16424)

### Can any be instructed "trace the front face of this tower"?

**Closest approach in 2025-2026:**

```
1. Qwen3-VL: "identify the front face of this tower" --> bounding box + description
2. SAM 2: segment the identified region --> precise mask
3. Contour extraction: mask --> polygon boundary
4. Bezier fitting: polygon --> smooth vector paths
```

This gives you a mask-derived contour. It does NOT give you construction geometry (the underlying 3D form edges distinct from shadow edges). For that, you need the 3D reconstruction path.

---

## 5. The Specific Gap: Isometric Mechanical Tower Face Tracing

### What you need
- Reference image of a mechanical tower in isometric view
- Identify 3 visible faces (front, side, top)
- Trace each face as a vector path
- Distinguish shadow edges from form edges
- Produce paths following actual 3D construction, not pixel edges

### Why no single system does this

The fundamental problem is that 2D edge detection (Canny, contour finding, even learned edge detection) cannot distinguish between:
- **Form edges** (where the actual 3D geometry turns away from view)
- **Shadow edges** (where light/dark transitions create apparent boundaries)
- **Material edges** (where surface properties change but geometry doesn't)

This requires 3D understanding. You need to know the actual 3D shape to know which edges are structural.

### Best available pipeline (March 2026)

**Option A: Full 3D reconstruction pipeline** (recommended)

```
Step 1: Image --> 3D Mesh
   Tool: TRELLIS.2 (handles sharp mechanical features, 3 seconds)
   Alt: Hunyuan3D 2.1 or SAM 3D (for real-world images)

Step 2: Mesh --> Face grouping
   Tool: Manual or automated face normal clustering
   Method: Group mesh faces by normal direction into front/side/top

Step 3: Per-face-group --> 2D projection
   Tool: trimesh + custom camera matching isometric angle
   Method: Project each face group separately, extract boundary contours

Step 4: Contours --> Clean vector paths
   Tool: potrace or vtracer for initial vectorization
   Then: Bezier Splatting / DiffVG for optimization against reference image

Step 5: Quality assurance
   Tool: Overlay projected paths on original reference for verification
```

**Option B: Hybrid VLM + segmentation pipeline** (faster, less accurate)

```
Step 1: Face identification
   Tool: Qwen3-VL: "In this isometric view, identify the front face, side face, and top face. Output bounding boxes."

Step 2: Per-face segmentation
   Tool: SAM 2 with Qwen3-VL bounding boxes as prompts

Step 3: Contour extraction + vectorization
   Tool: OpenCV findContours --> potrace/vtracer --> SVG paths

Step 4: Construction geometry refinement
   Tool: Bezier Splatting optimization against the mask boundary
```

**Option C: Direct image-to-CAD** (experimental)

```
Step 1: Img2CAD pipeline
   Tool: Img2CAD with Structured Visual Geometry
   Output: Parametric CAD model with sketch + extrusion operations

Step 2: Project CAD model from isometric view
   Tool: Standard CAD software or headless renderer (FreeCAD, OpenSCAD)

Step 3: Export as vector (hidden-line removal)
   Tool: CAD software's vector export (DXF/SVG)
```

### What comes closest TODAY

**For your specific use case, I recommend Option A with this specific toolchain:**

1. **TRELLIS.2** for mesh reconstruction (best at sharp features, 3 seconds, open source)
2. **trimesh** (Python) for mesh manipulation and face grouping by normals
3. **Custom projection** to flatten each face group to 2D
4. **vtracer** (Rust, very fast) or **potrace** for vectorization
5. **Overlay verification** against the original reference

**The shadow vs. form edge problem is solved by Step 1** -- once you have a 3D mesh, you KNOW which edges are form edges (mesh boundary silhouettes) and which were just lighting artifacts in the original image.

### Confidence assessment

- **Mesh reconstruction quality**: High confidence (85%). TRELLIS.2 and SAM 3D handle mechanical objects well, though very fine geometric details may be smoothed.
- **Face grouping accuracy**: Medium confidence (70%). Automated normal-based clustering works for clean isometric views but may need manual correction for complex geometry.
- **Vector path quality**: Medium confidence (75%). The paths will be structurally correct (following real geometry, not shadows) but may need manual refinement for production illustration quality.
- **End-to-end automation**: Low confidence (50%). Each step works individually, but the full pipeline requires custom glue code and quality checks between stages.

---

## Summary: What's Actually Possible NOW

| Capability | Status | Best Tool | Confidence |
|-----------|--------|-----------|------------|
| Single image --> 3D mesh | **Production-ready** | TRELLIS.2, SAM 3D, Tripo | 0.90 |
| Text --> 3D mesh via LLM | **Working but limited** | MeshLLM, LLaMA-Mesh | 0.75 |
| Image --> SVG vectors | **Working for icons/illustrations** | OmniSVG, StarVector | 0.85 |
| Text instruction --> SVG edits | **Working** | Chat2SVG | 0.80 |
| Image --> parametric CAD | **Experimental** | Img2CAD, Zoo Text-to-CAD | 0.65 |
| VLM spatial grounding (coordinates) | **Production-ready** | Qwen3-VL + SAM 2 | 0.90 |
| 3D mesh --> 2D vector outlines | **Classical, reliable** | trimesh + potrace | 0.95 |
| Shadow vs form edge distinction | **Requires 3D reconstruction** | No direct solution | N/A |
| Full pipeline: reference --> construction paths | **Possible with custom integration** | Multi-tool pipeline | 0.65 |

### Key insight for the ill_tool project

The existing tools in the ill_tool codebase (contour scanner, 3D form projection, axis-guided extraction) are working on the RIGHT problem. The state of the art confirms that:

1. Edge detection alone cannot distinguish form from shadow -- you need 3D understanding first
2. The pipeline should be: **reconstruct 3D --> project back to 2D** (not: detect 2D edges --> guess at 3D)
3. The specific tools to integrate would be TRELLIS.2 or SAM 3D for the reconstruction step, feeding into the existing projection and contour tools

### Sources

- [World Labs](https://www.worldlabs.ai/)
- [World API](https://www.worldlabs.ai/blog/announcing-the-world-api)
- [Marble launch - TechCrunch](https://techcrunch.com/2025/11/12/fei-fei-lis-world-labs-speeds-up-the-world-model-race-with-marble-its-first-commercial-product/)
- [World Labs $1B funding](https://beinsure.com/news/startup-world-labs-secures-1bn/)
- [Genie 3 - DeepMind](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/)
- [Project Genie](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/project-genie/)
- [SAM 3D - Meta](https://ai.meta.com/blog/sam-3d/)
- [Meta WorldGen](https://www.meta.com/blog/worldgen-3d-world-generation-reality-labs-generative-ai-research/)
- [Meta 3D AssetGen](https://ai.meta.com/research/publications/meta-3d-assetgen-text-to-mesh-generation-with-high-quality-geometry-texture-and-pbr-materials/)
- [Tripo AI](https://www.tripo3d.ai/)
- [Tripo $50M funding](https://www.prnewswire.com/news-releases/tripo-ai-announces-50-million-in-funding-and-new-models-for-production-ready-3d-generation-302724894.html)
- [TRELLIS.2 - Microsoft](https://microsoft.github.io/TRELLIS.2/)
- [TRELLIS.2 GitHub](https://github.com/microsoft/TRELLIS.2)
- [Hunyuan3D](https://hy-3d.com/)
- [Hunyuan3D GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)
- [Meshy AI](https://www.meshy.ai/)
- [SpAItial](https://www.spaitial.ai/blog/announcing-spaitial)
- [SpAItial - TechCrunch](https://techcrunch.com/2025/05/26/one-of-europes-top-ai-researchers-raised-a-13m-seed-to-crack-the-holy-grail-of-models/)
- [Luma AI](https://lumalabs.ai/)
- [LLaMA-Mesh - NVIDIA](https://research.nvidia.com/labs/toronto-ai/LLaMA-Mesh/)
- [MeshLLM](https://arxiv.org/abs/2508.01242)
- [SpatialLLM](https://3d-spatial-reasoning.github.io/spatial-llm/)
- [OmniSVG](https://omnisvg.github.io/)
- [StarVector](https://huggingface.co/starvector/starvector-8b-im2svg)
- [Chat2SVG](https://chat2svg.github.io/)
- [Img2CAD](https://arxiv.org/abs/2410.03417)
- [Zoo.dev Text-to-CAD](https://zoo.dev/text-to-cad)
- [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)
- [Grounded SAM 2](https://github.com/IDEA-Research/Grounded-SAM-2)
- [Florence-2 comparison](https://roboflow.com/compare/florence-2-vs-grounding-dino)
- [DiffVG](https://github.com/BachiLi/diffvg)
- [Bezier Splatting](https://arxiv.org/abs/2503.16424)
- [Claude Vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Spatial reasoning in LLM survey - IJCAI 2025](https://www.ijcai.org/proceedings/2025/1200)
- [InstantMesh](https://github.com/TencentARC/InstantMesh)
- [TripoSR](https://github.com/VAST-AI-Research/TripoSR)
- [Wonder3D](https://github.com/xxlong0/Wonder3D)
