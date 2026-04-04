---
date: 2026-04-04T20:00:00Z
session_name: general
researcher: rydersd
git_commit: 4bdb89d
branch: refactor/module-structure
repository: ill_tool
topic: "Cross-Layer Edge Clustering + Auto-Cleanup"
tags: [clustering, cleanup, tracing, normal-sidecar, learning, cep-panel]
status: planned
last_updated: 2026-04-04
last_updated_by: rydersd
type: feature_plan
---

# Handoff: Cross-Layer Edge Clustering + Auto-Cleanup

## Context

The tracing pipeline extracts edges at multiple thresholds across 5-7 layers (Scale Fine/Medium/Coarse, Ink Lines, Forms 5%, Curvature, Plane Boundaries). This produces 200-400 paths per reference image, many of which represent the SAME structural edge detected at different sensitivities.

The current cleanup workflow is manual: select redundant paths → Shape Cleanup → Smart Merge → Grouping Tools. **The selection step is 80% of the time.** The user manually identifies which paths overlap and should be grouped.

## Feature: Automatic Edge Clustering

### Core Algorithm

1. **Read paths from ALL extraction layers** (not just current selection)
2. **Compute pairwise similarity** between every path pair:
   - **Proximity**: Hausdorff distance or mean nearest-point distance between paths
   - **Angle alignment**: dot product of path tangent vectors at nearest points
   - **Surface coherence**: same dominant_surface from normal sidecar → bonus
   - **Curvature match**: similar mean_curvature → bonus
   - **Layer agreement**: paths on different layers that overlap → high confidence
3. **Cluster using agglomerative clustering** (or DBSCAN) with the similarity matrix
4. **Merge all paths onto a single "Clustered" working layer**, color-coded by cluster ID
5. **Compute per-cluster confidence**: number of distinct source layers that contributed paths
   - 3+ layers → high confidence (real structural edge)
   - 2 layers → medium confidence
   - 1 layer → low confidence (possible noise, flag for review)

### Panel Integration (Shape Cleanup)

Replace the current "select then average" flow with:

```
[Cluster Layers] button → analyzes all extraction layers
  ↓
Distance threshold slider (1-30pt, default 8pt) — controls how close paths
  must be to be grouped. Tighter = more clusters, looser = fewer clusters.
  Live update: re-clusters when slider changes.
  ↓
Panel readout: "47 edge groups from 312 paths across 5 layers"
  "31 high-confidence, 12 medium, 4 low"
  ↓
Artboard: all paths color-coded by cluster (7 distinct hues cycling)
  ↓
Click a cluster → panel shows: shape type, confidence, source layers, path count
  ↓
[Accept] single cluster → averages that group into one clean path
[Accept All] → averages ALL clusters → one-click layer cleanup
[Split] → breaks a cluster into two (user drags paths apart)
[Reject] → marks cluster as noise, removes
```

The distance threshold is the primary user control. It determines the DBSCAN `eps` parameter — the maximum distance between paths to be considered part of the same cluster. The learned threshold adjusts this default over time based on the user's split/merge corrections.

### Overlap Analysis

Where multiple layers detect the same edge, the overlap IS the structural truth:
- The intersection of Scale Fine + Scale Medium + Ink Lines is the highest-confidence edge
- Paths only detected by one layer may be noise OR subtle features
- Visualize confidence as stroke weight: thick = high confidence, thin = low

### Learning Loop

Every accept/split/reject is a training sample:
- **Accept**: confirms the clustering was correct for this path configuration
- **Split**: says "proximity/angle were misleading — these are separate edges"
- **Reject**: says "this cluster is noise — paths below this length/count are junk"

Feed into the correction_learning system:
- Store: cluster_params (proximity_threshold, angle_threshold) + user_action (accept/split/reject) + path_context (surface_type, layer_count, path_count)
- Compute: adjust thresholds per surface_type based on correction history
- Apply: next clustering run uses learned thresholds → more accurate initial grouping
- Goal: "Accept All" works on first try after enough training

### Implementation

**Python side** (new MCP tool `adobe_ai_cluster_paths`):
- Read all paths from specified layers via JSX
- Compute similarity matrix (numpy, vectorized)
- Cluster (scipy.cluster.hierarchy or sklearn DBSCAN)
- Use normal sidecar for surface coherence scoring
- Return cluster assignments + confidence scores

**ExtendScript side** (in Shape Cleanup host.jsx):
- `clusterLayers()` → calls MCP tool, receives cluster assignments
- Color-code paths on artboard (assign strokeColor per cluster)
- `acceptCluster(id)` → average all paths in cluster, place result
- `acceptAll()` → batch accept all clusters
- `splitCluster(id)` → user manually reassigns paths
- `rejectCluster(id)` → remove all paths in cluster

**Panel UI additions**:
- "Cluster Layers" button (replaces "Average Selection" as primary action)
- Cluster readout with confidence breakdown
- Accept / Accept All / Split / Reject buttons
- Cluster list (scrollable, shows each cluster's shape/confidence/count)

### Dependencies

- Normal sidecar (already built — per-path surface metadata)
- Surface classifier (already built — surface_similarity scoring)
- Interaction capture (already built — logging corrections)
- Correction learning (already built — store/compute/apply pattern)
- Shape averaging (already built — classifyShape + placePreview)
- Smart Merge (already built — endpoint welding for merged paths)

### Performance Considerations

- 300 paths → 300×300 = 90,000 pairwise comparisons. With numpy vectorization this is <1s.
- Hausdorff distance is O(n×m) per pair where n,m are point counts. Subsample to 20 points per path for speed.
- Color-coding via JSX: 300 paths × 1 strokeColor assignment = small JSX, no size concern.

### Testing Strategy

- Unit test clustering algorithm with synthetic path data (known clusters)
- Test confidence scoring (3-layer overlap → high, 1-layer → low)
- Test color assignment (unique hues per cluster)
- Integration test: cluster → accept all → verify output path count = cluster count

## Artifacts from This Session

Everything needed is already in place:

- `src/adobe_mcp/apps/illustrator/normal_renderings.py` — 15 renderings including surface_type_map
- `src/adobe_mcp/apps/illustrator/surface_classifier.py` — surface_similarity(), suggest_shape_type()
- `src/adobe_mcp/apps/illustrator/form_edge_extract.py` — sidecar write with per-path surface metadata
- `cep/shared/shapes.jsx` — classifyShape() with surfaceHint
- `cep/com.illtool.shapeaverager/` — Shape Cleanup panel (target for clustering UI)
- `cep/shared/logging.jsx` — interaction capture
- `src/adobe_mcp/apps/illustrator/interaction_ingest.py` — correction analysis
- `src/adobe_mcp/apps/illustrator/analysis/correction_learning.py` — store/compute/apply pattern

## User Preferences (from session)

- Bbox should be on artboard, not panel canvas
- Original paths hidden during cleanup (opacity 0), restored on cancel
- Bbox corners are 2x blue circles, visually distinct from path anchors
- Help hidden behind ⋯ toggle, not shown by default
- Preview path should be selected so anchor handles are visible
- "Later, just do what the user would do" — the learning loop is the endgame
