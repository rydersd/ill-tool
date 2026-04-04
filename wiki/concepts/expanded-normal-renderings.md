# Expanded Normal Map Renderings

> Brief: Shape operator eigendecomposition unlocks 10 additional renderings from DSINE normals — principal curvatures, surface classification, ridge/valley separation, silhouettes, depth facing, flow fields, ambient occlusion, boundary classification, cross-contour guides, and auto line weight. Pure numpy, no new ML models.
> Tags: normals, differential-geometry, curvatures, renderings, eigendecomposition
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

The original 5 normal map renderings (flat_planes, form_lines, curvature_map, relit_reference, depth_discontinuities) used only part of the geometric information in DSINE normals. Specifically, `curvature_map()` computed the **determinant** of the shape operator (Gaussian curvature K = κ1·κ2) but discarded the eigenvalues. Eigendecomposing the shape operator unlocks the full differential geometry of the surface from a single normal map prediction.

## The Shape Operator

The Weingarten map S encodes how surface orientation changes across the image:

```
S = [[∂nx/∂x, ∂nx/∂y],
     [∂ny/∂x, ∂ny/∂y]]
```

Previous: only `det(S)` was computed. Now: full eigendecomposition gives:
- **κ1, κ2** — principal curvatures (eigenvalues)
- **H = (κ1 + κ2) / 2** — mean curvature
- **K = κ1 · κ2** — Gaussian curvature (what we had before)
- **e1, e2** — principal directions (eigenvectors)

## The 10 New Renderings

### Curvature-Derived (from eigendecomposition)

| Rendering | What It Computes | Output | Key Use |
|-----------|-----------------|--------|---------|
| `principal_curvatures()` | κ1, κ2, H per pixel | HxWx3 float32 | Foundation for all others |
| `surface_type_map()` | Classify: flat/convex/concave/saddle/cylindrical | HxW uint8 | Per-path surface intelligence, sidecar |
| `ridge_valley_map()` | Separate ridge (H>0) and valley (H<0) masks | HxWx2 uint8 | Line weight, illustration conventions |
| `surface_flow_field()` | Eigenvectors of S — principal curvature directions | HxWx4 float32 | Cross-contour guides, stroke direction |

### View-Dependent

| Rendering | What It Computes | Output | Key Use |
|-----------|-----------------|--------|---------|
| `silhouette_contours()` | Rim edges where Nz ≈ 0 | HxW uint8 mask | Silhouette extraction (separate from occlusion) |
| `depth_facing_map()` | Nz clamped to [0,1] | HxW float32 | Depth ordering, camera-facing intensity |

### Composite / Derived

| Rendering | What It Computes | Output | Key Use |
|-----------|-----------------|--------|---------|
| `ambient_occlusion_approx()` | Local normal variance | HxW float32 | Crease/crevice detection without raycast |
| `form_vs_material_boundaries()` | Distinguish occlusion edges from paint/decal edges | HxWx2 uint8 | Separate form edges from material boundaries |
| `cross_contour_field()` | RK4 streamlines along principal directions | List of polylines | Cross-hatching guides for illustration |
| `curvature_line_weight()` | Sigmoid-blended weight from curvature + silhouette | HxW float32 | Auto stroke width: silhouettes thickest, ridges thinnest |

### Surface Type Classification

```
κ1 > ε, κ2 > ε     → convex (dome)
κ1 < -ε, κ2 < -ε   → concave (bowl)
κ1 · κ2 < 0         → saddle (horse-saddle)
one |κ| < ε, other > ε → cylindrical (tube)
both |κ| < ε         → flat (plane)
```

This per-pixel classification feeds into:
1. **Normal sidecar file** — each extracted path tagged with dominant surface type
2. **Smart Merge** — same-surface endpoints merge preferentially
3. **Shape Averager** — surface type biases shape classification (cylindrical → arc)

### Auto Line Weight Convention

Traditional illustration: stroke weight varies with surface geometry.
- **Silhouettes**: thickest (weight ≈ 1.0) — defines the form boundary
- **Valleys**: thick (weight ≈ 0.7) — creases, folds, recessions
- **Flat surfaces**: medium (weight ≈ 0.5) — panel lines, surface detail
- **Ridges**: thin (weight ≈ 0.3) — convex highlights, edge catches

Applied automatically when `form_edge_extract` places paths in Illustrator.

### Cross-Contour Guides

Surface flow eigenvectors define how the surface bends. Streamlines traced along these directions are cross-contour lines — the lines a sculptor draws to show volume.

Generation: seed on regular grid → RK4 integration along principal direction → stop at image boundary or flat region. Placed as locked guide paths on "Cross Contours" layer.

## Architecture Change

```
Original:
  Normal Map → 5 renderings

Expanded:
  Normal Map → eigendecompose S → {κ1, κ2, H, e1, e2}
    → 10 new renderings (all from cached eigendecomposition)
    → normal sidecar JSON (per-path surface metadata)
    → auto line weight (strokeWidth at placement time)
    → cross-contour guides (locked layer)
```

The eigendecomposition is cached — computed once, reused by all 10 functions.

## Test Coverage

41 tests using synthetic fixtures (flat, sphere, cube, step normal maps). Each rendering verified for shape, dtype, and geometric correctness.

## See Also
- [[Normal Map as Shadow-Free Reference]] — Original 5-rendering architecture
- [[Form Edge Extraction Workflow]] — How renderings feed into path extraction
- [[Shadow vs Form Problem]] — Why normal maps solve what 2D edge detection can't
