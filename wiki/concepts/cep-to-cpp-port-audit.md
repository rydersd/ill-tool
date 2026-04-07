# CEP → C++ Port Audit

> Brief: Comprehensive function-by-function audit of CEP ExtendScript vs C++ plugin implementations. 29 functions audited: 7 CORRECT, 10 PARTIAL, 5 WRONG, 7 MISSING.
> Tags: audit, port, cep, c++, plugin
> Created: 2026-04-07
> Updated: 2026-04-07

## Motivation

User testing on 2026-04-07 revealed that C++ plugin operations don't match CEP behavior. Root cause: original Stage 1-9 agents never read the CEP source — they invented implementations from function names alone. Infrastructure (queue, bridge, panels) is correct; operation logic needs rewriting.

## Summary

| Status | Count | Examples |
|--------|-------|---------|
| CORRECT | 7 | Lasso, SmartSelect, CopyToGroup, Detach, Split, EnterWorkingMode, UndoMerge |
| PARTIAL | 10 | ClassifySelection, ReclassifyAs, SimplifySelection, SelectSmall, ScanEndpoints, MergeEndpoints, ApplyWorkingMode, CancelWorkingMode, findEndpointPairs, weldPoints |
| WRONG | 2 | AverageSelection (centroid collapse vs PCA-sort+classify+refit) |
| MISSING | 7 | sortByPCA, precomputeLOD, LOD slider scrubbing, computeSmoothHandles, placePreview/createPathWithHandles, merge preview overlay, resmooth |

## Critical Finding: AverageSelection

The core cleanup operation — the one users interact with most — is fundamentally wrong.

**CEP algorithm** (`sa_averageSelectedAnchors` in host.jsx:100):
1. Collect all selected anchor [x,y] from all paths
2. `sortByPCA()` — order by principal component (coherent spatial order)
3. `classifyShape()` — identify as line/arc/L/rect/S-curve/ellipse/freeform
4. `precomputeLOD()` — 20 levels of Douglas-Peucker with inflection preservation and primitive blend
5. `placePreview()` — create new clean path with bezier handles
6. Dim originals, enter isolation on preview group
7. User adjusts tension/simplification via slider (reads LOD cache)
8. Confirm → delete originals, promote preview. Cancel → restore originals.

**C++ algorithm** (`AverageSelection` in IllToolWorkingMode.cpp:26):
1. Collect all selected anchor positions
2. Compute centroid (average X, average Y)
3. Move ALL points to the centroid
4. Done.

Steps 2-8 of the CEP version are completely absent. The C++ version doesn't sort, classify, fit, preview, or create any new geometry — it just collapses everything to a single point.

## Shared Libraries Needing C++ Ports

| CEP Function | File | C++ Status | Lines to Write |
|-------------|------|------------|---------------|
| `sortByPCA()` | geometry.jsx:17 | MISSING | ~60 |
| `precomputeLOD()` | geometry.jsx:220 | MISSING | ~80 |
| `_findInflectionIndices()` | geometry.jsx:129 | MISSING | ~25 |
| `_mergeInflectionPoints()` | geometry.jsx:164 | MISSING | ~40 |
| `classifyShape()` output | shapes.jsx:18 | PARTIAL (no handles) | ~50 delta |
| `fitToShape()` + fitters | shapes.jsx:76 | PARTIAL (no handles) | ~100 delta |
| `computeSmoothHandles()` | pathutils.jsx:161 | MISSING | ~40 |
| `createPathWithHandles()` | pathutils.jsx:210 | MISSING | ~30 |
| `placePreview()` | uses createPath | MISSING | ~50 |
| `findEndpointPairs()` | pathutils.jsx:295 | PARTIAL | ~10 delta |
| `weldPoints()` | pathutils.jsx:383 | PARTIAL | ~20 delta |

**Total estimated new C++ code: ~600-800 lines**

## Dormant Systems

### VisionEngine (14 algorithms, 3 called)
Only `InferSurfaceType` (gradient histogram + divergence + multi-scale edges) is actually invoked. 10 algorithms (Hough, Harris, template matching, active contours, watershed, connected components, distance transform) compile but have zero callers.

### LearningEngine (built, zero callers)
SQLite-backed preference learning exists with thread-safe recursive_mutex. Not called from any panel or operation.

## Key Decisions

- Port plan is at `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md`
- CEP source is the authoritative spec for all shape cleanup and merge operations
- Stages 10-14 (perspective, blend, shading, decompose) have no CEP equivalent — they're C++ originals, need testing not porting

## See Also
- [[Plugin Architecture Hardening]] — queue/bridge infrastructure (this IS correct)
- [[AITimer Dispatch Pattern]] — SDK context dispatch (correct)
- [[Smart Merge Architecture]] — CEP merge design
- [[Local Vision Engine]] — 14 algorithms, mostly dormant
- [[On-Device Learning]] — SQLite learning, dormant
