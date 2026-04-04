# Cross-Layer Edge Clustering

> Brief: IMPLEMENTED. Two-level clustering by topological boundary signature + spatial proximity. 431 paths → 83 clusters in live test. Learning loop wired. 1907 tests.
> Tags: clustering, cleanup, tracing, learning, workflow, boundary-signatures, implemented
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

The tracing pipeline produces 200-400 paths across 5-7 layers (Scale Fine/Medium/Coarse, Ink Lines, Forms 5%). Many paths represent the SAME structural edge detected at different thresholds. The user spends 80% of cleanup time manually identifying which paths overlap.

## Innovation: Topological Edge Identity

Instead of clustering by proximity alone (which lies — shadow creases near form contours get merged), the system samples the **normal map perpendicular to each path** to determine what 3D boundary it represents.

**Boundary signature**: `(surface_left, surface_right, boundary_curvature)`
- Arm contour: `(cylindrical, background, 0.4)`
- Torso-arm junction: `(cylindrical, flat, 0.2)`
- Shadow crease: `(convex, convex, 0.05)`

**Two-level clustering:**
1. **Level 1 — Edge Identity**: Group by boundary signature (what kind of edge). O(n) dict groupby.
2. **Level 2 — Spatial Instance**: DBSCAN within each group (which specific instance). O(k²) per group.

Shadow creases auto-separate from form edges without threshold tuning.

## Implementation

### Files
- `src/adobe_mcp/apps/illustrator/analysis/boundary_signature.py` — BoundarySignature dataclass, compute via normal map perpendicular sampling
- `src/adobe_mcp/apps/illustrator/analysis/edge_clustering.py` — LayerPath, EdgeCluster, cluster_paths(), self-contained DBSCAN (no sklearn), generate_cluster_json()
- MCP tool: `adobe_ai_cluster_paths` — full pipeline from path JSON to cluster JSON

### Key algorithms
- **Boundary signature**: Sample 15 points along path, step perpendicular both sides, majority vote on surface_type_map, compute boundary curvature as mean angular normal difference
- **DBSCAN**: Self-contained implementation with deque-based seed expansion, min_samples=max(2, min_cluster_size)
- **Spatial distance**: Symmetrized mean-nearest-point (subsample to 20 points)
- **Per-identity thresholds**: learned_thresholds dict overrides global eps per identity group

### Fallback (no normal map)
Without boundary signatures, falls back to `{surface_type}_{sil|int}` identity key. Level 1 grouping is coarser but still functional. Tested live: 431 paths → 83 clusters at 8pt threshold.

## Panel Integration

Shape Cleanup panel has clustering section (being redesigned into separate Cluster tab):
- Distance threshold slider (1-30pt)
- Cluster list with color swatches + confidence badges
- Accept All / Reject / Reset
- Keyboard: Shift+A = Accept All, Delete = Reject, [/] = threshold

ExtendScript functions (sa_ prefixed):
- `sa_readLayerPaths()` — enumerate paths from extraction layers
- `sa_colorClusters()` — apply cluster colors via JSON
- `sa_acceptCluster()` — dedicated batch function (no isolation mode)
- `sa_acceptAllClusters()` — batch accept in reverse order

## The Learning Loop (WIRED)

| Action | Training Signal | Storage |
|--------|----------------|---------|
| Accept cluster | "This grouping was correct at this distance" | cluster_corrections.json |
| Split cluster | "Proximity misleading — tighten threshold" | cluster_corrections.json |
| Reject cluster | "Noise — paths below this length/count are junk" | cluster_corrections.json |
| Adjust slider | "Preferred clustering radius" (strongest signal) | cluster_corrections.json |

Functions in `correction_learning.py`:
- `record_cluster_correction()` — atomic writes (tempfile + os.replace)
- `learn_cluster_thresholds()` — per-identity suggested_threshold from corrections
- `get_convergence_signal()` — tracks Accept All accuracy, reports converged when >0.95 for 3+ sessions

MCP actions registered: `record_cluster_correction`, `get_cluster_thresholds`

## Adversarial Review (2 rounds, 14 hostile agents)

Round 2 found 10 P0, 18 P1 — all fixed:
- Asymmetric spatial distance → symmetrized
- DBSCAN min_samples=1 → max(2, min_cluster_size)
- Perpendicular direction swapped for pixel coords → fixed
- Banker's rounding curvature buckets → half-up rounding
- MCP tool was stub → wired with full pipeline
- Format mismatch (Python JSX vs panel JSON) → generate_cluster_json()
- Learning loop disconnected → MCP actions wired
- Per-identity thresholds not consumable → learned_thresholds parameter

## Live Test Results

| Threshold | Clusters | Paths Grouped | Noise |
|-----------|----------|---------------|-------|
| 4pt | 59 | 194 | 237 |
| **8pt** | **83** | **306** | **125** |
| 12pt | 73 | 345 | 86 |
| 20pt | 46 | 376 | 55 |

## Next Steps

1. **Panel two-tab redesign** — separate Cleanup and Cluster tabs
2. **Ghost Preview** — show averaged result shapes as threshold adjusts
3. **C++ annotator plugin** — AIAnnotatorSuite for non-scaling on-canvas handles
4. **Wire MCP bridge end-to-end** — panel JS → Python clustering → panel display

## See Also
- [[Illustrator C++ Plugin SDK]] — AIAnnotatorSuite for native overlay handles
- [[Expanded Normal Renderings]] — Surface classification powering boundary signatures
- [[Smart Merge Architecture]] — Endpoint merging after clustering
- [[Adversarial Review Findings]] — Patterns the clustering implementation avoids
