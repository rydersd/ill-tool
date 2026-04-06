# Predictive Path Completion

> Brief: Place 3 points on a surface, the tool draws the rest. Uses normal map flow field + boundary signatures + learned preferences to project paths along surface curvature.
> Tags: prediction, path-completion, normals, surface-flow, ml
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

Drawing vector paths over complex 3D forms is slow because the user must manually trace every contour. But the normal map already tells us where the surface curves. The boundary signature system already knows what kind of edge we're on. The extraction pipeline already found fragments of the same edge. Combine these: place a few seed points, and the tool completes the path.

## How It Works

1. User places 2-3 seed points on the canvas
2. Tool computes tangent direction from the seed points
3. **Walks the surface** in both directions from the endpoints:
   - Samples the normal map at each step
   - Projects the walking direction onto the surface tangent plane
   - Follows curvature by detecting normal changes ahead
4. **Stops at surface boundaries** — when surface type changes (cylindrical→flat), the edge naturally terminates
5. **Connects to existing fragments** — finds edge cluster members near the predicted path's endpoints
6. **Simplifies** with Douglas-Peucker
7. Shows ghosted preview — Enter to accept, adjust handles if needed

## Data Sources (all already computed)

| Source | What it provides |
|--------|-----------------|
| Normal map (DSINE) | Surface direction at every pixel |
| Surface type map | Where boundaries are (stop conditions) |
| Cross-contour flow field | Direction to walk along the surface |
| Edge clusters | Existing fragments to connect to |
| Sidecar JSON | Per-path boundary signatures |
| Learning engine | Preferred point density per surface type |

## Algorithm: Surface Walking

```
current_point = seed_endpoint
direction = tangent_from_seeds

for each step:
    normal = normal_map[current_point]
    projected_direction = direction - dot(direction, normal) * normal
    current_point += projected_direction * step_size
    
    if surface_type changed: STOP
    if near existing fragment endpoint: CONNECT
    
    adjust direction based on curvature (normal change ahead)
```

## Not Generative AI

This is **geometric projection** grounded in measured surface data:
- The normal map is computed from the actual image (DSINE inference)
- The surface types are classified from differential geometry (eigendecomposition)
- The edge fragments are from multi-scale extraction (Canny + DSINE edges)
- The preferences are from the user's own history (on-device learning)

No hallucination. No statistical generation. Pure geometry + personal style.

## MCP Tool

`adobe_ai_predict_path`
- Input: seed_points, image_path, max_extension, connect_existing
- Output: predicted path points, connections to existing fragments

## See Also
- [[Normal Map as Shadow-Free Reference]] — the DSINE pipeline providing normal maps
- [[On-Device Learning]] — learned preferences for point density
- [[Edge Clustering]] — existing fragments to connect to
- [[Form Edge Extraction Workflow]] — the extraction layers providing edge data
