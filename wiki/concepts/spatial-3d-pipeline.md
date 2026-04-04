# Spatial 3D-to-2D Pipeline

> Brief: Self-correcting pipeline: reference image -> TRELLIS.2 mesh -> face grouping -> 2D projection -> vector paths with Hausdorff scoring.
> Tags: 3d, spatial, trellis, pipeline, hausdorff, feedback-loop
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
The fundamental problem: how do you draw accurate 2D illustrations from reference images when shadows create false edges? Seven iterations of 2D-only approaches failed because 2D fundamentally cannot distinguish form edges from shadow edges. The breakthrough was changing the problem entirely — reconstruct 3D, then project to 2D where shadows don't exist.

## Overview

The spatial pipeline is the project's most significant research contribution. It treats 3D reconstruction as ground truth, projects through 2D, scores deviations using Hausdorff distance, and learns from corrections across sessions.

## Pipeline Steps

```
Reference Image
    |
    v
TRELLIS.2 (single-image 3D reconstruction)
    |
    v
Mesh Face Grouper (group faces by normal direction -> major planes)
    |
    v
2D Projection (project grouped faces to camera plane)
    |
    v
Contour Extraction (boundary edges of face groups)
    |
    v
Vector Path Placement (in Illustrator)
    |
    v
Pixel Deviation Scorer (Hausdorff distance vs reference)
    |
    v
Correction Learning (store displacement deltas for next run)
    |
    v
Feedback Loop (damped 30% correction per iteration)
```

## Key Modules

- **reconstruct_3d_trellis** — TRELLIS.2 single-image-to-mesh integration
- **mesh_face_grouper** — Groups mesh faces by normal direction, extracts boundary edges
- **spatial_pipeline** — End-to-end orchestrator
- **pixel_deviation_scorer** — Hausdorff-based evaluator (replaced subjective multi-factor scoring)
- **dwpose_delta_extractor** — Extracts correction deltas from Illustrator paths
- **feedback_loop_3d** — Closed-loop correction system with damped iterations

## Key Decisions

1. **3D reconstruction solves the shadow problem**: Instead of trying to filter shadows in 2D, reconstruct 3D where shadows don't exist. This single change unlocked viable results.

2. **Hausdorff distance over subjective scoring**: Previous multi-factor scoring reported 4.6/10 on work actually worth 0.3/10. Hausdorff distance measures actual geometric deviation — objective and automatable.

3. **Damped 30% correction**: Full correction overshoots. 30% per iteration converges without oscillation. Pattern borrowed from DWPose correction learning.

4. **External solvers for spatial precision**: LLMs direct the pipeline ("what to do") but external geometric code handles coordinates ("where to put it"). LLM tokenization creates irrational distance metrics between neighboring coordinate values.

## The Failed Approaches (Context)

Before the 3D pipeline, seven 2D approaches were tried across three sessions:
1. Direct edge detection — sees brightness, not form
2. Multi-exposure edge voting — better but still shadow-confused
3. Contour labeling + tonal analysis — 133 tests, sophisticated, zero-quality output
4. Constraint-based solver — semantic constraints to pixels, still fundamentally 2D
5. DiffVG differentiable rendering — gradient descent on paths, local minima traps
6-7. Various combinations of the above

All scored 0.002-0.3/10 because the problem requires 3D understanding.

## See Also
- [[Correction Learning]]
- [[Shadow vs Form Problem]]
- [[TRELLIS Integration]]
