# Shadow vs Form Problem

> Brief: 2D edge detection sees brightness not construction — shadows create false contours indistinguishable from form edges without 3D understanding.
> Tags: shadows, form, edge-detection, fundamental-problem
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
This is the core problem that drove the pivot from 2D-only approaches to 3D reconstruction. Understanding it explains why seven different 2D methods all failed.

## The Problem

When you run edge detection on a reference image, the algorithm finds brightness transitions. It cannot distinguish between:

1. **Form edges** — actual boundaries of 3D shapes (what you want to draw)
2. **Shadow edges** — brightness changes caused by lighting on surfaces (noise)
3. **Texture edges** — pattern boundaries within a surface (noise)

A human artist knows the difference because they understand the 3D form beneath the image. They draw the cylinder, not the shadow on the cylinder. Edge detection algorithms don't have this understanding.

## Why 2D Approaches Failed

Every 2D approach tried was fundamentally limited by this:

- **Multi-exposure voting**: Voting across exposure levels helps with noise but shadows vote consistently
- **Contour labeling**: Can classify contour types but still starts from shadow-contaminated edges
- **Tonal analysis**: K-means zone segmentation identifies planes but can't separate shadow planes from form planes
- **DiffVG optimization**: Gradient descent on paths gets trapped in local minima created by shadow edges

## The Solution

Reconstruct the 3D mesh (via TRELLIS.2), where shadows don't exist. Then project back to 2D and extract contours from geometry, not from brightness.

## Key Insight

"Edge detection sees brightness, not construction. Shadows are not shapes. You need the body plan first." This is also why constructive drawing methods (Loomis, Vilppu, Bridgman) start with 3D form construction, not 2D contour tracing.

## See Also
- [[Spatial 3D-to-2D Pipeline]]
- [[Constructive Drawing Methods]]
