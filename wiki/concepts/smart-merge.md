# Smart Merge Architecture

> Brief: Form-edge-aware path endpoint merging using normal sidecar intelligence. CEP panel with chain merge, preserve handles, and color-coded surface coherence preview.
> Tags: tools, merge, normals, cep, form-aware
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

When tracing mech reference images, the edge extraction pipeline produces many partial paths — fragments of the same structural edge captured at different thresholds. These need to be merged into continuous paths. Simple proximity-based merging (like 3D auto-merge) doesn't distinguish between endpoints that should merge (same form edge) and those that shouldn't (different form edges that happen to be close).

The primary use case: GIR's angular eye chevrons — merge path segments at endpoints without reshaping the contour.

## Key Innovation: Form-Aware Scoring

Smart Merge reads the normal sidecar file (written by `form_edge_extract.py`) to determine which geometric surface each path sits on. Merge decisions are weighted by both proximity AND surface coherence:

```
merge_score = proximity_score × surface_similarity_score
```

- **Same surface type, close endpoints** → HIGH score → merge
- **Different surfaces, close endpoints** → LOW score → skip
- **Same surface, moderate distance** → MODERATE score → preview for user decision

## Color-Coded Preview

Preview lines between merge candidates:
- **Green dashed** — same-surface merge (geometrically coherent)
- **Red-orange dashed** — cross-surface merge (may be incorrect)

This visual encoding lets the user judge merge quality at a glance.

## Chain Merge

For paths A→B→C where A-end is near B-start and B-end is near C-start: merge iteratively. After first pass (A+B, C remains), re-scan for new proximity matches. Iterate until no new pairs found (max 10 iterations safety limit).

## Preserve Handles Mode

For angular contours like GIR's eyes: the junction uses path A's anchor position (not averaged) and keeps A's incoming right-direction handle and B's outgoing left-direction handle. This maintains the angular shape instead of smoothing it.

## Architecture

```
Illustrator Selection
    → getSelectedPaths() (shared pathutils.jsx)
    → loadSidecar() (reads {doc}_normals.json from /tmp/illtool_cache/)
    → findEndpointPairs(paths, tolerance, normalScores)
    → previewMerge() — color-coded dashed lines
    → executeMerge(chain, preserveHandles)
    → weldPoints() — concatenate with junction averaging or handle preservation
```

All math runs in standalone ExtendScript (no WebSocket). Falls back to proximity-only mode when no sidecar exists.

## Panel: `cep/com.illtool.smartmerge/`

Third CEP panel following the established pattern:
- Manifest: `com.illtool.smartmerge`, ILST 28.0+, 280×480
- UI: radius slider (1-20pt), form-aware toggle, chain merge toggle, preserve handles toggle
- Actions: Scan → Preview → Merge → Undo
- Interaction logging via shared `logging.jsx`

## See Also
- [[Expanded Normal Renderings]] — The surface classification that powers form-aware scoring
- [[Form Edge Extraction Workflow]] — How paths are extracted and sidecar written
- [[Normal Map as Shadow-Free Reference]] — The DSINE foundation
