# Correction Learning

> Brief: Store displacement deltas from each drawing iteration to improve the next — borrowed from DWPose joint correction pattern.
> Tags: correction, learning, feedback, dwpose, delta
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
3D-to-2D projection introduces systematic errors (lens distortion, mesh quality, face grouping boundaries). Rather than fixing the projection math, learn correction vectors from each run and apply them to improve the next.

## Overview

Correction learning stores the displacement between where the pipeline placed path points and where they should have been (measured by Hausdorff deviation against reference). These deltas are accumulated and applied as initial offsets in subsequent runs.

## How It Works

1. **Run spatial pipeline** — produces projected contours in Illustrator
2. **Score with Hausdorff** — measure point-to-point deviation against reference
3. **Extract deltas** — DWPose delta extractor captures displacement vectors
4. **Store corrections** — JSON file with per-region displacement data
5. **Next run** — pipeline applies stored deltas as initial offset before projection
6. **Damped application** — only 30% of correction applied per iteration to prevent oscillation

## Pattern Origin

Adapted from DWPose skeleton joint corrections. DWPose detects 133 keypoints on cartoon characters, then applies learned correction offsets to improve accuracy on non-standard body proportions. Same principle applied here to projection geometry.

## Key Insight

The correction deltas are **per-region** (grouped by mesh face normal clusters), not global. A correction that fixes the head projection might hurt the torso projection. Region-specific learning prevents cross-contamination.

## See Also
- [[Spatial 3D-to-2D Pipeline]]
- [[Shadow vs Form Problem]]
