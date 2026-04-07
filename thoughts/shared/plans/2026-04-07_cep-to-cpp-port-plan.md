# Plan: CEP → C++ Faithful Port + Complete Feature Build

## Context

The C++ plugin's operation implementations were written by agents who never read the CEP source code. They invented behavior based on function names. The infrastructure (queue, bridge, panels, timer, annotator) is correct — but the **operation logic** needs rewriting against the CEP source as the authoritative spec.

This plan maps every CEP function to its C++ counterpart, grades correctness, and defines the port work.

---

## CEP → C++ Function Audit

### Legend
- **CORRECT**: C++ matches CEP algorithm
- **PARTIAL**: Core algorithm similar, missing features
- **WRONG**: Fundamentally different behavior
- **MISSING**: No C++ implementation exists

---

### Shape Cleanup (CEP: `cep/com.illtool.shapeaverager/jsx/host.jsx`)

#### 1. `sa_averageSelectedAnchors()` → `AverageSelection()` — **WRONG**
- **CEP** (host.jsx:100): Collects ALL selected anchors → `sortByPCA()` → `classifyShape()` → `precomputeLOD()` → `placePreview()` as NEW path → dims originals → enters isolation on preview group
- **C++** (IllToolWorkingMode.cpp:26): Computes centroid of all selected points → moves ALL points to centroid. Collapses shape into a star.
- **Port**: Complete rewrite. Need C++ ports of `sortByPCA`, `classifyShape`, `fitToShape`, `precomputeLOD`, `placePreview`. This is the biggest single piece.
- **Difficulty**: XL

#### 2. `sa_reclassifyAs(shapeType)` → `ReclassifyAs()` — **PARTIAL**
- **CEP** (host.jsx:199): Calls `fitToShape(cachedSortedPoints, shapeType)` on the PCA-sorted point cloud → updates preview path with new fit + handles → recomputes LOD cache
- **C++** (IllToolShapes.cpp:270): Takes existing path segments → generates new segments per shape type. Math is similar but operates on path segments not a sorted point cloud. Does NOT use PCA sort. Does NOT generate bezier handles.
- **Port**: After AverageSelection is rewritten to use PCA sort, reclassify should operate on the cached sorted points (same as CEP). The shape-fit math in C++ is close but needs handle generation.
- **Difficulty**: M

#### 3. `classifyShape(sortedPoints)` → `ClassifySelection()` — **PARTIAL**
- **CEP** (shapes.jsx:18): Takes PCA-sorted points → runs 6 shape tests → returns {shape, points, handles, closed, confidence}. Each test also returns fitted output points + handles.
- **C++** (IllToolShapes.cpp:224): Similar 6 tests with similar math. BUT: operates on raw path segments (not PCA-sorted), doesn't generate output points/handles, only returns a type name. Now multi-path (votes).
- **Port**: The classification confidence math is close enough. The real gap is that CEP classify also generates the fitted output (points + handles), which C++ doesn't. After PCA sort is ported, classification should use sorted points.
- **Difficulty**: M

#### 4. `sa_applyLODLevel(level)` → No C++ equivalent — **MISSING**
- **CEP** (host.jsx:226): Slider 0-100 picks from precomputed LOD cache (Douglas-Peucker at varying epsilon, inflection point preservation, primitive blend at high levels)
- **C++**: The Simplification slider calls `SimplifySelection()` which does one-shot Douglas-Peucker. No LOD cache, no slider scrubbing.
- **Port**: Need `precomputeLOD()` port + cache in plugin state + slider reads from cache
- **Difficulty**: L

#### 5. `sa_resmooth(tension)` → No C++ equivalent — **MISSING**
- **CEP** (host.jsx:249): Recomputes Catmull-Rom handles on preview path
- **Port**: Need `computeSmoothHandles()` port — ~40 lines
- **Difficulty**: S

#### 6. `sa_doConfirm()` → `ApplyWorkingMode()` — **PARTIAL**
- **CEP** (host.jsx:265): Exits isolation → moves preview out of group → deletes source copies → selects confirmed path → enters isolation on it → activates Free Transform
- **C++** (IllToolWorkingMode.cpp): Exits isolation → deletes working group OR restores originals. Missing: preview promotion, Free Transform activation.
- **Port**: Adapt to match CEP flow after AverageSelection rewrite
- **Difficulty**: M

#### 7. `sa_doUndoAverage()` → `CancelWorkingMode()` — **PARTIAL**
- **CEP** (host.jsx:327): Exits isolation → removes preview group → restores hidden path opacity → clears caches
- **C++** (IllToolWorkingMode.cpp): Similar but lacks opacity restoration and cache clearing
- **Difficulty**: S

#### 8. `sa_selectSmallPaths(maxPoints, maxArcLength)` → `SelectSmall()` — **PARTIAL**
- **CEP** (host.jsx:715): Selects paths with few points OR short arc length. Uses bezier arc approximation. Skips internal paths.
- **C++** (IllToolShapes.cpp:535): Selects by arc-length threshold using `MeasureSegments`. Missing: point-count threshold, internal path skip.
- **Port**: Add point-count threshold and skip paths named `__preview__` etc.
- **Difficulty**: S

---

### Smart Merge (CEP: `cep/com.illtool.smartmerge/jsx/host.jsx`)

#### 9. `sm_scanEndpoints(tolerance)` → `ScanEndpoints()` — **PARTIAL**
- **CEP** (host.jsx:152): Greedy endpoint pairing with optional form-aware scoring (normal sidecar). Returns pair count + same/cross surface stats.
- **C++** (IllToolMerge.cpp): Greedy 4-combo endpoint matching with tolerance. Missing: form-aware scoring, surface type comparison.
- **Port**: Core matching is close. Add optional surface-type weighting if VisionEngine surface data is available.
- **Difficulty**: M

#### 10. `sm_previewMerge()` → No C++ equivalent — **MISSING**
- **CEP** (host.jsx:193): Creates colored preview lines (green=same surface, orange=cross surface) on "Merge Preview" layer
- **Port**: Could use annotator overlay instead of creating actual paths. Draw connector lines between matched endpoints.
- **Difficulty**: M

#### 11. `sm_executeMerge(chainMerge, preserveHandles)` → `MergeEndpoints()` — **PARTIAL**
- **CEP** (host.jsx:257): Uses `weldPoints()` (pathutils.jsx:383) for proper endpoint concatenation with handle averaging at junction. Preserves bezier handles. Chain merge iterates.
- **C++** (IllToolMerge.cpp): Segment concatenation with handle junction averaging. Chain merge re-scans. Core algorithm is similar.
- **Port**: Verify handle averaging matches `weldPoints()` logic (especially path reversal + handle swap). The CEP version swaps left/right handles on reversal — check if C++ does this.
- **Difficulty**: M

#### 12. `sm_doUndoMerge()` → `UndoMerge()` — **CORRECT**
- Both use snapshot-based restoration.

---

### Shared Libraries Needing C++ Ports

#### 13. `sortByPCA()` (geometry.jsx:17) — **MISSING**
- PCA sort: centroid → covariance matrix → eigenvector → project + sort
- ~60 lines of C++. Critical dependency for AverageSelection rewrite.
- **Difficulty**: S

#### 14. `fitToShape()` (shapes.jsx:76) — **PARTIAL** (exists as ReclassifyAs)
- CEP returns {points, handles, closed, confidence}
- C++ generates segments but doesn't return handles separately
- **Difficulty**: M (refactor existing code to return handles)

#### 15. `precomputeLOD()` (geometry.jsx:220) — **MISSING**
- Surface-aware multi-level Douglas-Peucker with inflection preservation and primitive blend
- ~80 lines of C++
- **Difficulty**: M

#### 16. `computeSmoothHandles()` (pathutils.jsx:161) — **MISSING**
- Catmull-Rom tangent handles
- ~40 lines of C++
- **Difficulty**: S

#### 17. `placePreview()` / `createPathWithHandles()` (pathutils.jsx:118,210) — **MISSING**
- Create new path with explicit handle positions via AIPathSuite
- ~30 lines of C++
- **Difficulty**: S

#### 18. `findEndpointPairs()` (pathutils.jsx:295) — **PARTIAL** (exists in MergeEndpoints)
- C++ has similar greedy matching. Missing: surface scoring.
- **Difficulty**: S

#### 19. `weldPoints()` (pathutils.jsx:383) — **PARTIAL** (exists in MergeEndpoints)
- C++ does segment concatenation. Check handle swap on path reversal.
- **Difficulty**: S

---

### Selection Tools

#### 20. Polygon Lasso → `ExecutePolygonSelection()` — **CORRECT**
- Both do point-in-polygon selection of path segments.

#### 21. Smart Select → `ComputeSignature()` + `SelectMatchingPaths()` — **CORRECT**
- Arc-length curvature density matching. No CEP equivalent (C++ only feature from plugin plan).

---

### Grouping Tools

#### 22. `CopyToGroup()` — **CORRECT**
- NewArt(kGroupArt) + DuplicateArt. Standard SDK ops.

#### 23. `DetachFromGroup()` — **CORRECT**
- ReorderArt to move paths out.

#### 24. `SplitToNewGroup()` — **CORRECT**
- Create group + ReorderArt(kPlaceInsideOnTop).

#### 25. `EnterWorkingMode()` — **CORRECT**
- Duplicate-dim-lock-isolate workflow.

---

### Stages 10-14 (C++ only — no CEP equivalent)

#### 26. Perspective Grid — **BUILT, needs testing**
- Tool registration fixed (sameGroupAs)
- Grid visible=false default fixed
- Mirror/Duplicate/Paste math written but untested
- Document persistence via AIDictionarySuite

#### 27. Blend Harmonization — **BUILT, needs testing**
- Arc-length parameterization, easing curves, AIDictionarySuite persistence
- Panel wired, pick A/B mode, execute blend

#### 28. Surface Shading — **BUILT, needs testing**
- Blend shading (stacked contours) + Mesh gradient shading
- Light direction widget

#### 29. Auto-Decompose — **BUILT, needs testing**
- Clustering algorithm, overlay rendering, accept/split/merge
- Uses existing algorithms (endpoint scanning, signature matching, classification)

---

### VisionEngine (14 algorithms) — **BUILT but mostly DORMANT**

Per wiki/concepts/vision-engine.md, these algorithms exist in VisionEngine.cpp:
1. Canny edge detection — called by `InferSurfaceType` only
2. Gaussian blur — internal helper
3. Sobel gradient — used by Canny
4. Hough line detection — NOT called from any panel
5. Hough circle detection — NOT called
6. Harris corner detection — NOT called
7. Template matching — NOT called
8. Active contours — NOT called
9. Watershed segmentation — NOT called
10. Connected components — NOT called
11. Distance transform — NOT called
12. Multi-scale edge detection — called by `InferSurfaceType`
13. Gradient histogram — called by `InferSurfaceType`
14. Divergence analysis — called by `InferSurfaceType`

Only `InferSurfaceType` (gradient histogram + divergence) is actually called from the classification pipeline. The other 10 algorithms compile but have no caller. Auto-Decompose could use some of them (connected components, distance transform) but currently uses its own proximity graph.

### LearningEngine — **BUILT but DORMANT**
- SQLite-backed preference learning exists in LearningEngine.cpp
- Has `recursive_mutex` for thread safety
- NOT called from any panel operation
- Was intended to learn shape preferences, simplification levels, noise thresholds from usage

---

## Port Priority Order

### Phase 1: Core Shape Pipeline (blocks everything else)
1. **Port `sortByPCA()`** → new static function in IllToolShapes.cpp (~60 lines)
2. **Port `classifyShape()` output** → modify ClassifySinglePath to return points + handles (not just type)
3. **Port `fitToShape()`** → modify to return points + handles arrays
4. **Port `computeSmoothHandles()`** → new function for Catmull-Rom handles (~40 lines)
5. **Port `placePreview()`** → new function: create AIPathArt from points + handles (~30 lines)

### Phase 2: Rewrite AverageSelection
6. **Rewrite `AverageSelection()`**: collect anchors → sortByPCA → classifyShape → precomputeLOD → placePreview → enter working mode on preview
7. **Update `ReclassifyAs()`**: operate on cached sorted points, not path segments
8. **Port `precomputeLOD()`**: surface-aware LOD cache with slider scrubbing
9. **Wire tension slider** to `computeSmoothHandles()` on preview path

### Phase 3: Merge Improvements
10. **Add merge preview** via annotator overlay (connector lines between matched endpoints)
11. **Verify handle swap on path reversal** in MergeEndpoints vs CEP's `weldPoints()`
12. **Add surface-type scoring** to endpoint pairing (optional, uses VisionEngine)

### Phase 4: Test Stages 10-14
13. **Test perspective tool** — flyout, handle drag, grid rendering, mirror/duplicate/paste
14. **Test blend** — pick A/B, execute, easing curve, re-edit
15. **Test shading** — blend mode, mesh mode, light direction
16. **Test decompose** — analyze, accept, split, merge groups

### Phase 5: Wake Dormant Systems
17. **Wire LearningEngine** — record shape classifications, simplification levels, merge decisions
18. **Wire remaining VisionEngine algorithms** — connected components for decompose, Hough for perspective detection

---

## Files to Modify

| File | Changes |
|------|---------|
| `IllToolShapes.cpp` | Add sortByPCA, refactor classifyShape to return points+handles, refactor fitToShape |
| `IllToolWorkingMode.cpp` | Complete rewrite of AverageSelection, update Apply/Cancel for preview workflow |
| `IllToolMerge.cpp` | Add merge preview overlay, verify handle swap, add surface scoring |
| `IllToolPlugin.h` | Add LOD cache, sorted points cache, preview path handle to plugin state |
| `IllToolPlugin.cpp` | Wire LOD slider, add preview path management |
| `IllToolPanels.mm` | No changes (panels already wired correctly) |

## Shared Library Port Mapping

| CEP File | Function | C++ Target | Lines |
|----------|----------|------------|-------|
| geometry.jsx | `sortByPCA()` | IllToolShapes.cpp (new static) | ~60 |
| geometry.jsx | `douglasPeucker()` | Already exists in SimplifySelection | 0 |
| geometry.jsx | `precomputeLOD()` | IllToolShapes.cpp (new static) | ~80 |
| geometry.jsx | `_findInflectionIndices()` | IllToolShapes.cpp (new static) | ~25 |
| geometry.jsx | `_mergeInflectionPoints()` | IllToolShapes.cpp (new static) | ~40 |
| shapes.jsx | `classifyShape()` | Refactor existing ClassifySinglePath | ~50 delta |
| shapes.jsx | `fitToShape()` + 6 fitters | Refactor existing ReclassifyAs cases | ~100 delta |
| pathutils.jsx | `getSelectedAnchors()` | Refactor existing FindAllSelectedPaths | ~20 delta |
| pathutils.jsx | `computeSmoothHandles()` | IllToolShapes.cpp (new static) | ~40 |
| pathutils.jsx | `createPathWithHandles()` | IllToolShapes.cpp (new function) | ~30 |
| pathutils.jsx | `placePreview()` | IllToolWorkingMode.cpp (new function) | ~50 |
| pathutils.jsx | `weldPoints()` | Verify existing MergeEndpoints | ~20 delta |
| pathutils.jsx | `findEndpointPairs()` | Verify existing ScanEndpoints | ~10 delta |

**Estimated total new/changed C++ lines: ~600-800**

## Verification

After each phase:
1. Build → sign → notarize → staple → install
2. Test in Illustrator with real artwork:
   - Phase 1: Internal only (functions exist, not yet called)
   - Phase 2: Select messy paths → Average Selection → verify clean preview appears with correct shape + handles
   - Phase 3: Select open paths → Scan → verify connector preview → Merge → verify handle continuity
   - Phase 4: Each panel feature end-to-end
   - Phase 5: Verify learning DB populates after repeated use
