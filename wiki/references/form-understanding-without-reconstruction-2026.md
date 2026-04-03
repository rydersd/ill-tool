# Form Understanding Without 3D Reconstruction: 2026 Survey

> Brief: Comprehensive survey of AI/ML models that understand 3D form from 2D images WITHOUT mesh reconstruction -- depth estimation, surface normals, intrinsic decomposition, edge classification, line art extraction. Evaluates whether these can replace full 3D for the shadow-vs-form problem.
> Tags: research, depth-estimation, surface-normals, intrinsic-decomposition, edge-classification, line-art, form-edges, shadow-edges, survey
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation

The current spatial pipeline (see [[Spatial 3D-to-2D Pipeline]]) solves the shadow-vs-form problem via full 3D mesh reconstruction (TRELLIS.2). This works but is heavyweight: requires GPU-intensive 3D reconstruction, mesh face grouping, 2D re-projection, and correction learning. The question: can lighter-weight "2.5D" approaches that understand 3D form WITHOUT building an explicit mesh achieve the same result? If surface normal maps can identify where surfaces change direction, we might extract form edges directly -- skipping the entire 3D reconstruction step.

**Use case**: Given a reference image, distinguish form edges (actual shape boundaries) from shadow edges (lighting artifacts) to produce clean vector illustrations.

---

## 1. Monocular Depth Estimation

Depth maps predict per-pixel distance from camera. They encode 3D structure as a 2D image, making them the simplest "2.5D" representation.

### Can depth maps alone reveal form edges?

**Partially.** Depth discontinuities correspond to occlusion boundaries (where one object is in front of another) and some shape boundaries. However:
- Depth maps are smooth across surface plane changes that face the camera at similar distances
- A box face transition (front face to side face) at the same depth produces NO depth discontinuity
- Depth maps excel at silhouette/occlusion edges but miss surface orientation changes

**Verdict**: Depth maps alone are insufficient. They capture "what's in front" but not "which way surfaces face." However, combined with surface normals, they become powerful.

### SOTA Models (ranked by quality and relevance)

#### Depth Anything 3 (DA3) -- ByteDance Seed, November 2025
- **Architecture**: Plain DINOv2 transformer, depth-ray prediction target
- **Capabilities**: Single image, multi-view, and video depth
- **Performance**: Surpasses VGGT by 35.7% camera pose accuracy, 23.6% geometric accuracy; outperforms DA2 on monocular benchmarks
- **Streaming**: DA3-Streaming handles ultra-long video with <12GB GPU memory
- **HuggingFace**: [depth-anything/DA3-LARGE](https://huggingface.co/depth-anything/DA3-LARGE)
- **macOS/MPS**: Uses DINOv2 encoder -- standard ViT operations, likely MPS-compatible with PYTORCH_ENABLE_MPS_FALLBACK=1
- **Trust**: 0.93 (ByteDance Seed, massive benchmark validation, open weights)

#### Depth Anything V2 -- NeurIPS 2024
- **Architecture**: DINOv2 encoder + DPT decoder
- **Performance**: Foundation model for monocular depth, widely adopted
- **HuggingFace**: [depth-anything/Depth-Anything-V2-Large-hf](https://huggingface.co/depth-anything/Depth-Anything-V2-Large-hf)
- **macOS/MPS**: Explicitly supported -- code includes MPS device detection. Apple published CoreML conversions: [apple/coreml-depth-anything-v2-small](https://huggingface.co/apple/coreml-depth-anything-v2-small)
- **CoreML**: Official Apple conversion available, optimized for Neural Engine
- **Trust**: 0.92 (NeurIPS, Apple CoreML integration, massive adoption)

#### DepthPro -- Apple ML Research, October 2024
- **Architecture**: Multi-scale ViT, DINOv2 encoder, DPT-like fusion. Images scaled at multiple ratios, split into overlapping patches.
- **Performance**: 2.25-megapixel depth map in 0.3s on V100 GPU. Metric depth (absolute scale) without camera intrinsics.
- **HuggingFace**: [apple/DepthPro-hf](https://huggingface.co/apple/DepthPro-hf), also [apple/DepthPro](https://huggingface.co/apple/DepthPro)
- **macOS/MPS**: Apple's own model -- highest likelihood of MPS compatibility. CoreML conversion efforts exist ([PR #45](https://github.com/apple/ml-depth-pro/pull/45)).
- **Trust**: 0.94 (Apple Research, official HuggingFace model, metric depth)

#### Distill Any Depth -- February 2025
- **Architecture**: Knowledge distillation from DAv2 (primary teacher) + GenPercept (diffusion-based assistant)
- **Performance**: New SOTA via cross-context distillation. Smoother surfaces, sharper edges, more detailed depth maps.
- **Innovation**: Multi-teacher distillation integrates complementary strengths of discriminative (DAv2) and generative (GenPercept) models
- **HuggingFace**: [Papers page](https://huggingface.co/papers/2502.19204), weights available
- **macOS/MPS**: Standard ViT-based, should work with MPS fallback
- **Trust**: 0.88 (recent, Westlake University + NUS, pre-print but strong benchmarks)

#### Marigold -- CVPR 2024 Oral, Best Paper Candidate
- **Architecture**: Fine-tuned Stable Diffusion for dense prediction. Minimal modification of pretrained diffusion model.
- **Performance**: SOTA zero-shot generalization trained on small synthetic datasets, single GPU
- **Updates**: v1.1 depth and normals checkpoints released May 2025 with updated noise scheduler
- **HuggingFace**: [prs-eth/marigold-depth-v1-1](https://huggingface.co/prs-eth/marigold-depth-v1-1), integrated in diffusers since v0.28.0. LCM variants for fast inference: [prs-eth/marigold-depth-lcm-v1-0](https://huggingface.co/prs-eth/marigold-depth-lcm-v1-0)
- **macOS/MPS**: Diffusion-based, uses diffusers pipeline -- MPS support via HuggingFace diffusers MPS backend
- **Trust**: 0.94 (CVPR Oral + Best Paper candidate, code + weights, HuggingFace integration)

#### Lotus -- September 2024
- **Architecture**: Reformulated diffusion into single-step procedure with "detail preserver" tuning strategy
- **Performance**: SOTA zero-shot depth AND normals with only 59K training samples. Hundreds of times faster than multi-step diffusion methods.
- **Unique value**: Joint depth + normal estimation in one model, single step
- **HuggingFace**: [GitHub](https://github.com/EnVision-Research/Lotus), [project page](https://lotus3d.github.io/)
- **macOS/MPS**: Diffusion architecture but single-step -- lower memory requirements than iterative methods
- **Trust**: 0.90 (strong benchmarks, open source, ICLR-level work)

### Depth Estimation: Summary for Our Use Case

| Model | Speed | Metric? | Edge Quality | macOS Ready | Best For |
|-------|-------|---------|-------------|-------------|----------|
| DA3 | Fast | Yes | Excellent | Likely (ViT) | Overall best depth |
| DAv2 | Fast | Relative | Very Good | Yes (CoreML) | Production deployment |
| DepthPro | 0.3s | Yes | Excellent | Best (Apple) | macOS-native metric depth |
| Distill Any Depth | Fast | Relative | Sharpest edges | Likely (ViT) | Maximum edge quality |
| Marigold v1.1 | Medium | Relative | Very Good | Yes (diffusers) | Zero-shot generalization |
| Lotus | Fast | Relative | Excellent | Likely | Joint depth+normal |

**Recommendation for our pipeline**: DepthPro for metric depth (Apple-native), DAv2 for relative depth (proven CoreML), Lotus if we want joint depth+normal in one pass.

---

## 2. Surface Normal Estimation

Surface normals predict which direction each pixel's surface faces. This is arguably the MOST RELEVANT representation for the shadow-vs-form problem because:

- **Form edges = normal discontinuities**: Where surface orientation changes abruptly (box edge, cylinder silhouette), normals change direction sharply
- **Shadow edges = NO normal change**: A shadow falling on a flat plane does not change the surface normal
- **Therefore**: Edge detection on a normal map should produce ONLY form edges, with zero shadow contamination

This is the core theoretical insight that could bypass full 3D reconstruction.

### How to extract form edges from normal maps

1. Predict surface normal map (RGB image where R=X, G=Y, B=Z direction)
2. Apply edge detection (Sobel, Laplacian, or Canny) to the normal map
3. Edges found = C1 discontinuities = surface orientation changes = form edges
4. Shadows are invisible because they don't change surface orientation

This technique is well-established in real-time NPR rendering (game engines use it for cel-shading outlines) but has not been widely applied to the "extract form edges from photos" problem using predicted normals from ML models.

### SOTA Models (ranked by quality and relevance)

#### StableNormal -- ACM Transactions on Graphics 2024
- **Architecture**: Diffusion-based, specifically designed to reduce variance for stable and sharp normal predictions
- **Performance**: SOTA across iBims-1, ScanNetV2, and DIODE-indoor by large margins over DSINE, Marigold, GenPercept, and GeoWizard
- **Unique value**: Explicitly designed for sharpness at edges -- exactly what we need for detecting form edge discontinuities
- **HuggingFace**: [Stable-X/StableNormal](https://huggingface.co/spaces/Stable-X/StableNormal) (Space), model weights available
- **macOS/MPS**: Diffusion-based architecture -- MPS compatible via diffusers with PYTORCH_ENABLE_MPS_FALLBACK=1
- **Trust**: 0.92 (ACM TOG, benchmark-validated, strong margin over competitors)

#### DSINE -- CVPR 2024 Oral
- **Architecture**: Novel inductive bias using per-pixel ray direction encoding + relative rotation learning between neighboring normals
- **Performance**: Crisp, piecewise smooth predictions. Stronger generalization than ViT-based models despite orders of magnitude smaller training data.
- **Unique value**: Lightweight, fast, does not require diffusion inference. Assumes camera intrinsics but works with approximations.
- **Code**: [GitHub](https://github.com/baegwangbin/DSINE), loadable via `torch.hub`
- **ComfyUI**: Integrated ([kijai/ComfyUI-DSINE](https://github.com/kijai/ComfyUI-DSINE))
- **macOS/MPS**: Standard CNN/ViT architecture -- high MPS compatibility likelihood
- **Trust**: 0.91 (CVPR Oral, clean implementation, well-adopted)

#### GeoWizard -- ECCV 2024
- **Architecture**: Extended Stable Diffusion for joint depth + normal prediction with geometry switcher
- **Performance**: Mutual information exchange between depth and normal ensures high consistency between representations
- **Unique value**: Joint estimation means depth and normals are geometrically consistent -- depth edges align with normal edges
- **HuggingFace**: Available via diffusers wrapper, [GitHub](https://github.com/fuxiao0719/GeoWizard)
- **ComfyUI**: Integrated for creative workflows
- **macOS/MPS**: Diffusion-based, MPS via diffusers
- **Trust**: 0.90 (ECCV, open weights, well-documented)

#### Marigold Normals v1.1 -- May 2025
- **Architecture**: Same Marigold framework fine-tuned for normal estimation
- **HuggingFace**: [prs-eth/marigold-normals-lcm-v0-1](https://huggingface.co/prs-eth/marigold-normals-lcm-v0-1) (fast LCM variant)
- **Integration**: Native diffusers pipeline, same API as Marigold depth
- **macOS/MPS**: Same as Marigold depth -- diffusers MPS backend
- **Trust**: 0.90 (same provenance as Marigold depth)

#### Lotus Normal -- September 2024
- **Architecture**: Single-step diffusion normal estimation
- **Unique value**: Fastest diffusion-based normal estimation (single step vs multi-step). Joint with depth.
- **Trust**: 0.88 (same model as Lotus depth)

### Surface Normal Estimation: Summary for Our Use Case

| Model | Speed | Edge Sharpness | Consistency | macOS Ready | Best For |
|-------|-------|---------------|-------------|-------------|----------|
| StableNormal | Medium | Best | Very Good | MPS+fallback | Maximum edge quality |
| DSINE | Fast | Very Good | Good | High (CNN/ViT) | Fast inference, lightweight |
| GeoWizard | Medium | Good | Best (joint) | MPS+diffusers | Depth+normal consistency |
| Marigold Normals | Medium | Good | Good | MPS+diffusers | Ecosystem integration |
| Lotus Normal | Fast | Very Good | Good (joint) | Likely | Speed + joint estimation |

**Recommendation for our pipeline**: StableNormal for maximum edge sharpness (critical for form edge detection), DSINE as fast lightweight alternative.

### The Key Technique: Edge Detection on Predicted Normals

```python
# Pseudocode for form edge extraction via surface normals
import torch
import cv2
import numpy as np

# Step 1: Predict surface normals
normal_map = stable_normal_model(reference_image)  # RGB: (H, W, 3) in [-1, 1]

# Step 2: Apply Sobel edge detection to EACH CHANNEL of normal map
edges_x = cv2.Sobel(normal_map, cv2.CV_64F, 1, 0, ksize=3)
edges_y = cv2.Sobel(normal_map, cv2.CV_64F, 0, 1, ksize=3)

# Step 3: Compute gradient magnitude across all 3 normal channels
# Large gradient = surface orientation changes abruptly = FORM EDGE
edge_magnitude = np.sqrt(np.sum(edges_x**2 + edges_y**2, axis=-1))

# Step 4: Threshold to binary edges
form_edges = (edge_magnitude > threshold).astype(np.uint8) * 255

# These edges are SHADOW-FREE because shadows don't change surface normals
```

This is well-established in NPR/cel-shading (Houdini's `edgedetectnormal` COP node, Unreal Engine normal-based edge detection, Godot shaders) but applying it to ML-predicted normals from photos is novel for illustration extraction.

---

## 3. Intrinsic Image Decomposition

Intrinsic decomposition separates an image into:
- **Albedo** (reflectance/material color) -- what the surface IS
- **Shading** (illumination) -- how light falls on it

If you remove shading, what remains is albedo. Albedo changes ONLY where the material changes (paint color boundaries, texture boundaries). This is a complementary approach to surface normals: normals find form edges (geometry changes), albedo finds material edges (color/texture changes). Neither contains shadow edges.

### SOTA Models (ranked by quality and relevance)

#### compphoto/Intrinsic -- TOG 2023 + TOG 2024
- **Papers**: "Intrinsic Image Decomposition via Ordinal Shading" (2023) + "Colorful Diffuse Intrinsic Image Decomposition in the Wild" (2024)
- **Architecture**: Three-stage pipeline -- grayscale ordinal shading estimation, low-res chromaticity for colorful illumination, high-res sparse albedo layer
- **Output**: Albedo + diffuse shading + specular residual
- **Unique value**: Works on in-the-wild photos. Handles colorful illumination (not just white light). Most practical for real reference images.
- **Code**: [GitHub](https://github.com/compphoto/Intrinsic) -- inference code + pre-trained weights
- **macOS/MPS**: Standard PyTorch -- likely MPS compatible
- **Trust**: 0.92 (Two TOG papers, clean open-source implementation, well-validated)

#### IntrinsicAnything -- ECCV 2024
- **Architecture**: Learns diffusion priors for albedo + specular under unknown illumination
- **Performance**: Uses generative model as material prior for inverse rendering regularization
- **Unique value**: Handles unknown illumination conditions -- critical for reference images with arbitrary lighting
- **Code**: [GitHub](https://github.com/zju3dv/IntrinsicAnything)
- **Trust**: 0.88 (ECCV, ZJU, novel approach)

#### FlowIID -- January 2025
- **Architecture**: VAE-guided latent flow matching for single-step albedo/shading decomposition
- **Performance**: Comparable to diffusion methods with only 52M parameters in a SINGLE inference step
- **Unique value**: Extremely lightweight and fast. Suitable for real-time and resource-constrained deployment (macOS).
- **Trust**: 0.85 (recent pre-print, novel architecture, small but fast)

#### IDArb -- ICLR 2025
- **Architecture**: Cross-view, cross-domain attention for multi-view intrinsic decomposition
- **Output**: Surface normals + material properties (albedo, roughness, metalness)
- **Unique value**: If you have multiple views of the same reference, this gives consistent decomposition across views
- **Dataset**: ARB-Objaverse with multi-view intrinsic data under diverse lighting
- **Trust**: 0.90 (ICLR 2025, comprehensive approach)

### Intrinsic Decomposition: Summary for Our Use Case

| Model | Speed | Output | Quality | macOS Ready | Best For |
|-------|-------|--------|---------|-------------|----------|
| compphoto/Intrinsic | Medium | Albedo + shading + specular | Best in-the-wild | Likely (PyTorch) | Real reference photos |
| IntrinsicAnything | Slow (diffusion) | Albedo + specular | Good | MPS+fallback | Unknown lighting |
| FlowIID | Fast (single step) | Albedo + shading | Good | Best (52M params) | Speed, macOS-friendly |
| IDArb | Medium | Normals + full material | Excellent | MPS+fallback | Multi-view references |

**Recommendation for our pipeline**: compphoto/Intrinsic for best in-the-wild quality, FlowIID as fast lightweight alternative.

### How intrinsic decomposition helps form edge extraction

```python
# After decomposition:
albedo = intrinsic_model.predict_albedo(reference_image)
shading = intrinsic_model.predict_shading(reference_image)

# Edge detection on ALBEDO finds only material boundaries
# (paint color changes, surface material changes)
# NO shadow edges because shading has been removed
material_edges = canny(albedo)

# Edge detection on SHADING finds lighting boundaries
# These are what we want to DISCARD
shadow_edges = canny(shading)  # for reference/debugging only
```

---

## 4. Edge Classification / Contour Understanding

Rather than predicting intermediate representations and deriving edges, some models directly classify edge types.

### SOTA Models

#### RINDNet++ -- IJCV 2025 (THE MOST DIRECTLY RELEVANT MODEL)
- **What it does**: Simultaneously detects and classifies four edge types:
  - **R**eflectance edges (material/texture boundaries)
  - **I**llumination edges (SHADOW EDGES -- what we want to discard)
  - **N**ormal edges (surface orientation changes -- FORM EDGES we want)
  - **D**epth edges (occlusion boundaries -- FORM EDGES we want)
- **Architecture**: Three-stage CNN -- shared backbone, per-type specialized decoders, independent decision heads
- **Benchmark**: Introduced BSDS-RIND with annotations for all four edge types
- **Downstream**: Improves shadow detection and depth estimation as side benefits
- **Code**: [GitHub](https://github.com/MengyangPu/RINDNet-plusplus)
- **macOS/MPS**: Standard CNN architecture -- high MPS compatibility
- **Trust**: 0.91 (IJCV 2025, benchmark-validated, builds on ICCV 2021 Oral)

**This is a near-perfect match for the shadow-vs-form problem.** RINDNet++ literally classifies edges into exactly the categories we need:
- Keep: Normal edges (N) + Depth edges (D) = form edges
- Discard: Illumination edges (I) = shadow edges
- Keep selectively: Reflectance edges (R) = material boundaries (may or may not want)

#### PIDINet-MC -- 2025-2026
- **What it does**: Real-time multi-class edge detection based on PiDiNet
- **Performance**: Simultaneously predicts background + four edge categories from full-resolution inputs
- **Speed**: Real-time capable
- **Trust**: 0.82 (recent, builds on well-established PiDiNet)

#### PiDiNeXt -- 2024
- **What it does**: Improved PiDiNet combining traditional operators with deep learning in parallel
- **Performance**: Outperforms PiDiNet accuracy at 80 FPS on BSDS500 and BIPED
- **Architecture**: Lightweight (<1M parameters for base PiDiNet)
- **Trust**: 0.85 (peer-reviewed, fast, well-benchmarked)

### Edge Classification: Summary for Our Use Case

| Model | Edge Types | Speed | Directly Solves Problem? | macOS Ready |
|-------|-----------|-------|--------------------------|-------------|
| RINDNet++ | R, I, N, D | Medium | YES -- classify and discard I edges | High (CNN) |
| PIDINet-MC | 4 categories | Real-time | Partially (categories differ) | High (<1M params) |
| PiDiNeXt | Binary | 80 FPS | No (no classification) | High |

**Recommendation**: RINDNet++ is the most directly relevant model in this entire survey. It was literally designed to do what we need.

---

## 5. Line Art Extraction

These models extract clean line art from photos/illustrations. They are trained to produce the lines an artist would draw, which implicitly means they should favor form edges over shadow edges.

### SOTA Models

#### Informative Drawings -- HuggingFace
- **What it does**: Converts photos to clean black-and-white sketch/line-art
- **Architecture**: Based on "Adversarial Open Domain Adaptation for Sketch-to-Photo Synthesis"
- **Styles**: Two sketch styles available
- **HuggingFace**: [Space](https://huggingface.co/spaces/carolineec/informativedrawings), [ONNX model](https://huggingface.co/rocca/informative-drawings-line-art-onnx) (17MB)
- **macOS**: ONNX model is 17MB -- trivially runs on CPU, no GPU needed
- **Trust**: 0.80 (established, small model, but trained on photos/illustrations not mechanical subjects)

**Caveat for our use case**: These models are trained on natural photos and anime/illustrations. They learn what edges "look like drawings" which is a learned aesthetic, not geometric understanding. They may still include some shadow edges if those shadows "look like they should be drawn." They don't truly understand 3D form.

#### ControlNet Lineart Variants
- **Lineart**: Extracts lineart from real-life images, produces illustration-quality lines
- **Lineart Anime**: Specialized for anime/illustration inputs
- **Lineart Coarse**: Rougher, more expressive lines
- **HuggingFace**: Multiple models available as ControlNet preprocessors
- **macOS**: Run as preprocessors, standard PyTorch
- **Trust**: 0.82 (widely used in ControlNet ecosystem, empirically validated)

#### Anime2Sketch
- **What it does**: Extracts sketch from anime/illustration art
- **Code**: [GitHub](https://github.com/Mukosame/Anime2Sketch)
- **Limitation**: Designed for anime style, not photographic or mechanical references
- **Trust**: 0.78 (older, limited domain)

#### marked-lineart-vectorizer
- **What it does**: Vectorizes clean line-art raster images using encoder-decoder model
- **Output**: Vector paths directly (not raster edges)
- **Code**: [GitHub](https://github.com/nopperl/marked-lineart-vectorization)
- **Trust**: 0.75 (specialized, less widely validated)

### Line Art Extraction: Assessment for Our Use Case

**Honest assessment**: Line art models are trained to produce aesthetically pleasing drawings, not geometrically accurate form edges. They work through learned pattern matching ("this looks like a line an artist would draw") rather than understanding 3D structure. For our use case:

- They might produce good results on simple, well-lit references
- They will fail on complex lighting because they don't truly separate form from shadow
- They are a useful POST-PROCESSING step after geometric edge extraction (clean up the output of normal-based edges)
- They should NOT be the primary form edge detector

---

## 6. Geometric Understanding Without Reconstruction

### Normal Map Edge Detection (The Bridge Technique)

The most promising approach combines predicted surface normals with classical edge detection:

1. Surface normals encode 3D orientation as color (RGB = XYZ direction)
2. Edge detection on normal maps finds orientation discontinuities
3. These discontinuities are EXACTLY form edges
4. Well-proven in real-time rendering (Houdini, Unreal, Godot)

**Houdini's `edgedetectnormal` COP node**: Detects varying-width crease lines by comparing surface normals of neighboring pixels via ray differentials. This is exactly the operation we'd apply to ML-predicted normals.

**Unreal Engine**: Normal-based edge detection in material editor finds edges where surface orientation changes, used for NPR/cel-shading outlines.

**Godot shaders**: Sobel operator on normal buffer for screenspace edge detection in NPR rendering.

The innovation is applying this established rendering technique to ML-predicted normal maps from single photos rather than from rendered 3D scenes.

### Bezier Splatting -- NeurIPS 2025
- **What it does**: 30-150x faster differentiable vector graphics than DiffVG
- **Architecture**: Samples 2D Gaussians along Bezier curves, splatting-based rasterization
- **Relevance**: Once form edges are extracted, this is the fastest path to optimized SVG output
- **Code**: [GitHub](https://github.com/xiliu8006/Bezier_splatting)
- **Trust**: 0.88 (NeurIPS 2025, significant speedup, SVG-compatible output)

### StarVector -- CVPR 2025
- **What it does**: Image-to-SVG via vision-language model
- **Limitation**: "StarVector models will not work for natural images or illustrations" -- icons/logos/diagrams only
- **HuggingFace**: [starvector/starvector-8b-im2svg](https://huggingface.co/starvector/starvector-8b-im2svg)
- **Trust for our use case**: 0.40 (explicitly not designed for our input type)

---

## 7. Proposed Lightweight Pipeline (Alternative to Full 3D)

Based on this research, here is a pipeline that could solve shadow-vs-form WITHOUT mesh reconstruction:

### Pipeline A: Normal-Based Form Edge Extraction

```
Reference Image
    |
    v
StableNormal (or DSINE for speed)
    |
    v
Surface Normal Map (H x W x 3, each pixel = surface direction)
    |
    v
Edge Detection on Normal Map (Sobel/Canny on normal channels)
    |
    v
Form Edges Only (shadows invisible in normal space)
    |
    v
Vectorize (potrace/vtracer -> SVG paths)
    |
    v
Optimize (Bezier Splatting or DiffVG refinement)
    |
    v
Place in Illustrator
```

**Strengths**: Simple, fast, theoretically sound. Normal discontinuities ARE form edges by definition.
**Weaknesses**: Normal prediction quality determines everything. Predicted normals may have artifacts at fine details. No depth-based occlusion information.

### Pipeline B: Multi-Signal Fusion

```
Reference Image
    |
    +---> StableNormal --> Normal Map --> Edge Detection --> Form Edges (N)
    |
    +---> DepthPro --> Depth Map --> Edge Detection --> Occlusion Edges (D)  
    |
    +---> compphoto/Intrinsic --> Albedo --> Edge Detection --> Material Edges (R)
    |
    v
Edge Fusion: Union(N, D) AND NOT(illumination edges)
    |
    v
Vectorize + Optimize
```

**Strengths**: Combines complementary signals. Normal edges + depth edges = complete form edges. Albedo edges add material boundaries. Robust against individual model failures.
**Weaknesses**: Three model inferences (slower). Need fusion logic to combine edge maps.

### Pipeline C: RINDNet++ Direct Classification

```
Reference Image
    |
    v
RINDNet++
    |
    v
Four Edge Maps: R(eflectance), I(llumination), N(ormal), D(epth)
    |
    v
Keep: N + D edges (form edges)
Discard: I edges (shadow edges)
Optional: R edges (material boundaries)
    |
    v
Vectorize + Optimize
```

**Strengths**: Single model, single inference, directly outputs the classification we need. Simplest pipeline.
**Weaknesses**: RINDNet++ trained on BSDS-RIND dataset -- may not generalize to illustration/mechanical reference images. Edge quality depends on model generalization. Less control over individual signal quality.

### Pipeline D: Hybrid (Recommended)

```
Reference Image
    |
    +---> StableNormal --> Normal Map 
    |         |
    |         v
    |    Sobel Edge Detection --> Candidate Form Edges
    |
    +---> RINDNet++ --> I(llumination) edge map
    |
    v
Candidate Form Edges MINUS Illumination Edges = Clean Form Edges
    |
    v
Vectorize (potrace) --> Bezier Splatting optimization --> SVG
```

**Strengths**: Best of both approaches. StableNormal provides high-quality form edge candidates via normal discontinuity detection. RINDNet++ provides a shadow edge mask for filtering any remaining artifacts. Two-model pipeline with clear roles.
**Weaknesses**: Two model inferences. Requires tuning edge detection thresholds and subtraction logic.

---

## 8. Comparison: Lightweight vs Full 3D Reconstruction

| Criterion | Full 3D (TRELLIS.2) | Lightweight (Normal+Edge) |
|-----------|---------------------|---------------------------|
| Shadow elimination | Perfect (geometry has no shadows) | Very Good (normal discontinuities are shadow-free) |
| Occlusion handling | Perfect (mesh visibility) | Good (depth edges handle this) |
| Fine detail | Limited by mesh resolution | Limited by normal prediction quality |
| Speed | Slow (~3-10s for mesh + processing) | Fast (~0.5-2s for normal prediction + edge detection) |
| GPU requirements | High (3D reconstruction) | Moderate (single model inference) |
| macOS/MPS | Uncertain (TRELLIS.2 GPU requirements) | Good (ViT/CNN models on MPS) |
| Complexity | High (mesh + face grouping + projection) | Low (predict normals + edge detect) |
| Robustness | High (full geometric understanding) | Moderate (depends on normal prediction accuracy) |
| Novel view generation | Yes (rotate mesh freely) | No (single viewpoint only) |

### When to use which

**Use Full 3D (TRELLIS.2) when**:
- You need to generate illustrations from novel viewpoints
- The reference has extreme lighting that corrupts normal predictions
- You need face grouping (front face, side face, top face separately)
- Geometric precision is paramount

**Use Lightweight (Normals) when**:
- You just need form edges from the reference viewpoint
- Speed matters (interactive pipeline)
- Running on macOS without dedicated GPU
- The reference has moderate, well-understood lighting
- As a fast first pass before deciding if full 3D is needed

---

## 9. macOS / Apple Silicon Compatibility Summary

| Model | MPS Support | CoreML | Memory | Notes |
|-------|-------------|--------|--------|-------|
| DepthPro | Best (Apple) | Yes (official) | ~2GB | Apple's own model |
| DAv2 | Yes (tested) | Yes (Apple published) | ~1-2GB | MPS device detection in code |
| DA3 | Likely (ViT) | Not yet | ~2-3GB | Standard DINOv2 ops |
| Distill Any Depth | Likely (ViT) | Not yet | ~2GB | Based on DAv2 architecture |
| Marigold | Yes (diffusers) | Not yet | ~4GB | Diffusion model, higher memory |
| Lotus | Likely | Not yet | ~2-3GB | Single-step, lower than Marigold |
| StableNormal | MPS+fallback | Not yet | ~4GB | Diffusion-based |
| DSINE | High (CNN/ViT) | Not yet | ~1GB | Lightweight architecture |
| GeoWizard | MPS+diffusers | Not yet | ~4GB | Diffusion-based |
| RINDNet++ | High (CNN) | Not yet | ~500MB | Standard CNN |
| compphoto/Intrinsic | Likely (PyTorch) | Not yet | ~1-2GB | Standard architecture |
| FlowIID | Best (52M params) | Not yet | ~200MB | Extremely lightweight |
| Informative Drawings | Yes (ONNX, 17MB) | N/A | ~17MB | Runs on CPU |

**MPS known limitations**:
- Some PyTorch operations not implemented -- use PYTORCH_ENABLE_MPS_FALLBACK=1
- No fp16 support on MPS (models run in fp32, using more memory)
- No distributed training (not relevant for inference)
- Memory-sensitive: system swaps degrade performance significantly

---

## 10. Trust Assessment & Confidence

### High-Confidence Findings (Trust >= 0.90)

1. **Surface normal maps from ML models CAN identify form edges via edge detection.** This is theoretically sound (normal discontinuities = form edges by definition) and proven in rendering pipelines. The only question is whether predicted normals from photos are accurate enough.

2. **RINDNet++ directly classifies edge types including illumination (shadow) edges.** Published IJCV 2025, benchmarked, code available.

3. **Depth estimation is production-ready on macOS.** DepthPro (Apple) and DAv2 have official CoreML models.

4. **Intrinsic decomposition can separate albedo from shading.** compphoto/Intrinsic handles in-the-wild photos with colorful illumination.

### Medium-Confidence Findings (Trust 0.75-0.89)

5. **The lightweight pipeline (normals + edge detection) is likely sufficient for moderate-complexity references.** Not validated end-to-end, but each component is proven individually.

6. **RINDNet++ generalizes to illustration/mechanical references.** Trained on BSDS-RIND (natural images). Mechanical/illustration domains are untested.

7. **MPS compatibility for diffusion-based models.** Works in principle via diffusers, but specific models may have untested operations.

### Low-Confidence / Unvalidated

8. **End-to-end quality of lightweight pipeline vs full 3D.** No direct comparison exists. Needs empirical testing.

9. **Normal prediction quality on MJ-rendered/stylized references.** All models trained primarily on real photos. Stylized/NPR inputs are edge cases.

10. **Bezier Splatting on macOS.** NeurIPS 2025, no macOS testing reported.

---

## 11. Recommended Next Steps

### Immediate (validate core hypothesis)

1. **Run StableNormal on a test reference image** -- get normal map
2. **Apply Sobel edge detection to the normal map** -- extract candidate form edges
3. **Compare against reference image edges** -- are shadow edges truly eliminated?
4. **If yes**: The lightweight pipeline is viable. Build it.
5. **If partially**: Add RINDNet++ as shadow edge filter. Test again.

### Short-term (build lightweight pipeline)

6. **Implement Pipeline D** (StableNormal + RINDNet++ hybrid)
7. **Add DepthPro** for occlusion edge detection
8. **Compare output quality** against current TRELLIS.2 pipeline
9. **Measure speed difference** on Apple Silicon

### Medium-term (integration)

10. **Add as alternative mode** in spatial_pipeline tool -- "lightweight" vs "full 3D"
11. **Use lightweight as fast preview**, full 3D as final quality pass
12. **Update ML backends** with new model dependencies

---

## Sources

### Depth Estimation
- [Depth Anything V2 - GitHub](https://github.com/DepthAnything/Depth-Anything-V2) (NeurIPS 2024)
- [Depth Anything 3 - GitHub](https://github.com/ByteDance-Seed/Depth-Anything-3) (Nov 2025)
- [Distill Any Depth - GitHub](https://github.com/Westlake-AGI-Lab/Distill-Any-Depth) (Feb 2025)
- [DepthPro - Apple ML Research](https://machinelearning.apple.com/research/depth-pro) (Oct 2024)
- [DepthPro on HuggingFace](https://huggingface.co/apple/DepthPro-hf)
- [Apple CoreML Depth Anything V2](https://huggingface.co/apple/coreml-depth-anything-v2-small)
- [Marigold - GitHub](https://github.com/prs-eth/Marigold) (CVPR 2024 Oral)
- [Marigold on HuggingFace](https://huggingface.co/prs-eth/marigold-depth-v1-1)
- [Lotus - GitHub](https://github.com/EnVision-Research/Lotus) (Sep 2024)
- [Distill Any Depth Project Page](https://distill-any-depth-official.github.io/)

### Surface Normal Estimation
- [StableNormal - ACM TOG](https://dl.acm.org/doi/10.1145/3687971) (2024)
- [StableNormal on HuggingFace](https://huggingface.co/spaces/Stable-X/StableNormal)
- [StableNormal Paper](https://arxiv.org/html/2406.16864v1)
- [DSINE - GitHub](https://github.com/baegwangbin/DSINE) (CVPR 2024 Oral)
- [DSINE Paper](https://arxiv.org/abs/2403.00712)
- [GeoWizard - GitHub](https://github.com/fuxiao0719/GeoWizard) (ECCV 2024)
- [GeoWizard Project Page](https://fuxiao0719.github.io/projects/geowizard/)
- [Marigold Normals LCM on HuggingFace](https://huggingface.co/prs-eth/marigold-normals-lcm-v0-1)

### Intrinsic Image Decomposition
- [compphoto/Intrinsic - GitHub](https://github.com/compphoto/Intrinsic) (TOG 2023 + 2024)
- [Colorful Diffuse Intrinsic Decomposition](https://yaksoy.github.io/ColorfulShading/) (TOG 2024)
- [IntrinsicAnything - GitHub](https://github.com/zju3dv/IntrinsicAnything) (ECCV 2024)
- [IntrinsicAnything Paper](https://arxiv.org/html/2404.11593v2)
- [FlowIID Paper](https://arxiv.org/abs/2601.12329) (Jan 2025)
- [IDArb - ICLR 2025](https://openreview.net/forum?id=uuef1HP6X7)
- [IDArb Project Page](https://lizb6626.github.io/IDArb/)

### Edge Classification
- [RINDNet++ - IJCV 2025](https://link.springer.com/article/10.1007/s11263-025-02541-0)
- [RINDNet++ GitHub](https://github.com/MengyangPu/RINDNet-plusplus)
- [RINDNet - ICCV 2021 Oral](https://arxiv.org/abs/2108.00616)
- [PIDINet-MC - 2025](https://www.techscience.com/cmc/v86n2/64798)
- [PiDiNeXt Paper](https://link.springer.com/chapter/10.1007/978-981-99-8549-4_22)
- [PiDiNet - GitHub](https://github.com/hellozhuo/pidinet) (ICCV 2021 Oral)

### Line Art Extraction
- [Informative Drawings on HuggingFace](https://huggingface.co/spaces/carolineec/informativedrawings)
- [Informative Drawings ONNX](https://huggingface.co/rocca/informative-drawings-line-art-onnx)
- [Anime2Sketch - GitHub](https://github.com/Mukosame/Anime2Sketch)
- [ControlNet Lineart](https://openlaboratory.ai/models/control-sd15-lineart)
- [marked-lineart-vectorizer](https://github.com/nopperl/marked-lineart-vectorization)

### Vectorization
- [DiffVG - GitHub](https://github.com/BachiLi/diffvg)
- [Bezier Splatting - NeurIPS 2025](https://arxiv.org/abs/2503.16424)
- [Bezier Splatting Project Page](https://xiliu8006.github.io/Bezier_splatting_project/)
- [PyTorch-SVGRender](https://github.com/ximinng/PyTorch-SVGRender)
- [StarVector on HuggingFace](https://huggingface.co/starvector/starvector-8b-im2svg)

### macOS / Apple Silicon
- [PyTorch MPS Documentation](https://docs.pytorch.org/docs/stable/mps.html)
- [HuggingFace Apple Silicon Guide](https://huggingface.co/docs/transformers/en/perf_train_special)
- [HuggingFace Accelerate MPS Guide](https://huggingface.co/docs/accelerate/en/usage_guides/mps)
- [Apple Metal PyTorch](https://developer.apple.com/metal/pytorch/)

### NPR Edge Detection from Normals
- [Houdini edgedetectnormal](https://www.sidefx.com/docs/houdini/nodes/cop/edgedetectnormal.html)
- [Godot Normal-Based Edge Detection Shader](https://godotshaders.com/shader/normal-based-edge-detection-with-sobel-operator-screenspace/)
- [Normal Map Edge Detection in Unreal](https://polycount.com/discussion/84517/detecting-edges-in-normal-maps-in-the-unreal-material-editor)

## See Also
- [[Shadow vs Form Problem]]
- [[Spatial 3D-to-2D Pipeline]]
- [[ML Backends]]
- [[Constructive Drawing Methods]]
