# Plan: Cross-Layer Edge Clustering with Topological Edge Identity

> Date: 2026-04-04
> Branch: refactor/module-structure (PR #5 fixes) → feat/edge-clustering (new feature)
> Prerequisites: PR #5 adversarial fixes merged
> Depends on: form_edge_extract.py, surface_classifier.py, correction_learning.py, shapes.jsx, host.jsx

## Goal

Build a system that automatically clusters 200-400 extracted paths across 5-7 layers into "same structural edge" groups, enabling one-click cleanup via Accept All. The system should learn from corrections until Accept All works on first try.

## The Radical Innovation: Topological Edge Identity

### The Problem with Proximity-Only Clustering

The handoff spec describes DBSCAN with proximity + angle + surface bonus. This is better than pure proximity, but it has a fundamental weakness: **proximity lies.**

Two paths 3pt apart could be:
- The same edge detected by two extraction layers (should cluster)
- A shadow crease next to a form contour (should NOT cluster)

Two paths 30pt apart could be:
- Unrelated edges (should not cluster)
- The same structural edge that extraction missed in the middle (SHOULD cluster)

### The Insight: Boundary Signatures

We have the normal map. From the normal map we derived surface types per path. But we're only using surface type as a *bonus signal* on proximity. **We should flip this.**

Every path in the document doesn't just have "its own" surface type — it sits at a **boundary between two surface regions**. By sampling the normal map perpendicular to the path tangent on both sides, we get:

```
boundary_signature = (surface_left, surface_right, curvature_at_boundary)
```

Examples:
- Arm contour: `(cylindrical, background, 0.4)` — cylinder meeting empty space
- Torso-arm junction: `(cylindrical, flat, 0.2)` — cylinder meeting flat torso
- Shadow crease on face: `(convex, convex, 0.05)` — slight curvature change within same surface
- Sharp fold in fabric: `(flat, flat, 0.8)` — high curvature within flat regions

Paths sharing the same boundary signature are structurally the same kind of edge, regardless of distance. This is information nobody else in the vector tracing space has.

### Two-Level Clustering Hierarchy

**Level 1 — Edge Identity** (boundary signature space):
Group all paths by what kind of 3D boundary they represent.
- "All paths at a cylinder-to-flat boundary with curvature ~0.3"
- This creates edge identity classes

**Level 2 — Spatial Instance** (proximity within identity class):
Within each identity class, sub-cluster by spatial proximity.
- "This particular cylinder-to-flat boundary on the LEFT arm"
- This separates spatially distinct instances of the same edge type

### Why This Is Radically Better

1. **Structural meaning**: Not "these paths are near each other" but "these paths represent the left contour of the torso where it meets the arm"
2. **Noise rejection**: Shadow creases (same-surface boundaries) are automatically separated from form edges (cross-surface boundaries) — no threshold tuning needed
3. **Confidence from identity**: 3+ layers detecting the same boundary signature at the same location = near-certain structural edge
4. **Learning becomes semantic**: Instead of learning "paths within 8pt should cluster," we learn "cylinder-to-flat boundaries with curvature > 0.2 are always real structural edges"
5. **Accept All accuracy**: Boundary signatures are much more discriminating than proximity, so initial clustering is more accurate, so Accept All works sooner

### What's Needed to Compute Boundary Signatures

The sidecar already stores `dominant_surface` and `mean_curvature` per path. To compute boundary signatures, we need:

1. **Sample normal map perpendicular to path** — at 10-20 points along each path, step 3-5 pixels perpendicular in both directions, classify the surface type at each sample point
2. **Determine left/right surface** — the majority surface type on each side of the path
3. **Compute boundary curvature** — the rate of normal change across the path (not along it)

This is ~50 lines of numpy on top of the existing `_compute_path_surface_info()` in form_edge_extract.py. The normal map and surface type map are already computed.

---

## Phase 0: Adversarial Fixes (before merge)

Fix all P0/P1 findings from adversarial review of PR #5.

### P0 Fixes (3)

**F1. Namespace collision across 3 panels**
- Files: all 3 `host.jsx`
- Fix: Prefix all global functions with panel abbreviation
  - `cleanupOrphans()` → `sa_cleanupOrphans()`, `sm_cleanupOrphans()`, `pr_cleanupOrphans()`
  - `getSelectionInfo()` → `sa_getSelectionInfo()`, `pr_getSelectionInfo()`
  - `_SHARED` → `_SA_SHARED`, `_SM_SHARED`, `_PR_SHARED`
  - Update all `csInterface.evalScript()` calls in corresponding `main.js` files
- Also prefix cache variables: `_cachedSortedPoints` → `_sa_cachedSortedPoints`, etc.

**F2. polyfills.py JSON.stringify key escaping**
- File: `src/adobe_mcp/jsx/polyfills.py:28`
- Fix: Escape keys the same way json_es3.jsx does:
  ```python
  # Before:
  parts.push('"' + k + '":' + JSON.stringify(obj[k], replacer, space));
  # After:
  parts.push('"' + k.replace(/\\\\/g,'\\\\\\\\').replace(/"/g,'\\\\"').replace(/\\n/g,'\\\\n').replace(/\\r/g,'\\\\r').replace(/\\t/g,'\\\\t') + '":' + JSON.stringify(obj[k], replacer, space));
  ```

**F3. (Elevated from P1) evalScript injection via data-shape DOM attribute**
- File: `cep/com.illtool.shapeaverager/js/main.js:159`
- Fix: Add allowlist validation before evalScript:
  ```javascript
  var VALID_SHAPES = ["line","arc","lshape","rectangle","scurve","ellipse","freeform"];
  if (VALID_SHAPES.indexOf(shapeType) === -1) return;
  ```

### P1 Fixes (6)

**F4. Polling re-average loop**
- File: `shapeaverager/js/main.js:290-299`
- Fix: After `averageSelectedAnchors()` sets selection, store the resulting selection string as `lastSelectionState` so the next poll doesn't see it as a change. Add a `_selfSelectionChange` flag.

**F5. `_hiddenSourcePaths` reset on re-average**
- File: `shapeaverager/jsx/host.jsx:61`
- Fix: Don't reset `_hiddenSourcePaths = []` on line 61. Instead, append new items. Deduplicate by checking if item is already in the array before pushing.

**F6. `doConfirm()` leaves originals at opacity 0**
- File: `shapeaverager/jsx/host.jsx:173`
- Fix: On confirm, DELETE the hidden source paths (they've been replaced by the clean preview). Add `for (var i = _hiddenSourcePaths.length - 1; i >= 0; i--) { try { _hiddenSourcePaths[i].item.remove(); } catch(e){} }` before clearing the array.

**F7. `__proto__` prototype pollution in JSON parsers**
- Files: `cep/shared/json_es3.jsx:175`, `src/adobe_mcp/jsx/polyfills.py:81`
- Fix: Skip dangerous keys in object parsing:
  ```javascript
  if (key === "__proto__" || key === "constructor" || key === "prototype") {
      _parseValue(); // consume but don't assign
  } else {
      obj[key] = _parseValue();
  }
  ```

**F8. Hardcoded fallback path in all 3 host.jsx**
- Files: all 3 host.jsx line 22
- Fix: Derive from known CEP extension location. The `$.fileName` gives us the host.jsx path; walk up to find `cep/shared/`:
  ```javascript
  // Fallback: walk up from this file to find shared/
  var f = File($.fileName);
  var shared = f.parent.parent.parent.path + "/shared/";
  if (!Folder(shared).exists) shared = f.parent.parent.path + "/shared/";
  return shared;
  ```

**F9. innerHTML XSS on Smart Merge error path**
- File: `cep/com.illtool.smartmerge/js/main.js:94`
- Fix: Pass through `escapeHtml()` before setting innerHTML.

### P2 Fixes (housekeeping, non-blocking)

- F10: Update docstring "14 subdirectories" → "15 subdirectories" in `__init__.py`
- F11: Clean stale .pyc: `find src/adobe_mcp/apps/illustrator/__pycache__ -name "*.pyc" -delete`
- F12: Add manifest.xml validation for CEP panels in install script
- F13: Uninstall removes PlayerDebugMode

---

## Phase 1: Boundary Signature Computation

**New file**: `src/adobe_mcp/apps/illustrator/analysis/boundary_signature.py`

### Functions

```python
def compute_boundary_signature(
    contour_points: list[tuple[float, float]],
    normal_map: np.ndarray,        # H x W x 3
    surface_type_map: np.ndarray,  # H x W, values 0-4
    sample_count: int = 15,
    perpendicular_offset: int = 4  # pixels
) -> BoundarySignature:
    """
    Sample the surface type on both sides of a path to determine
    what 3D boundary this path represents.
    
    Returns BoundarySignature(surface_left, surface_right, 
            boundary_curvature, confidence)
    """
```

```python
@dataclass
class BoundarySignature:
    surface_left: str      # "flat"|"convex"|"concave"|"saddle"|"cylindrical"
    surface_right: str     # same
    boundary_curvature: float  # rate of normal change across the path
    confidence: float      # 0-1, based on sampling consistency
    
    def identity_key(self) -> str:
        """Canonical string for this edge identity. 
        Ordered so (A,B) == (B,A)."""
        surfaces = sorted([self.surface_left, self.surface_right])
        curv_bucket = round(self.boundary_curvature * 10) / 10
        return f"{surfaces[0]}|{surfaces[1]}|{curv_bucket}"
    
    def similarity(self, other: 'BoundarySignature') -> float:
        """0-1 similarity between two boundary signatures."""
```

### Algorithm

1. For each path, compute tangent vectors at `sample_count` evenly-spaced points
2. At each sample point, compute perpendicular direction (rotate tangent 90 degrees)
3. Step `perpendicular_offset` pixels left and right
4. Look up `surface_type_map` at each offset position
5. Majority vote for `surface_left` and `surface_right`
6. Compute `boundary_curvature` as mean angular difference of normals across the path
7. Confidence = fraction of sample points where left and right surfaces are consistent

### Tests

- Synthetic path along known boundary → correct signature
- Path in flat region (same surface both sides) → `(flat, flat, ~0)`
- Path at cylinder edge → `(cylindrical, background, high)`
- Reversed path → same identity_key (order-invariant)

---

## Phase 2: Multi-Layer Path Registry + Clustering Engine

**New file**: `src/adobe_mcp/apps/illustrator/analysis/edge_clustering.py`

### Data Structures

```python
@dataclass
class LayerPath:
    path_name: str
    layer_name: str
    points: list[tuple[float, float]]
    surface_info: PathSurfaceInfo  # from sidecar
    boundary_sig: BoundarySignature
    extraction_backend: str  # "dsine"|"heuristic"|"informative"|etc.

@dataclass
class EdgeCluster:
    cluster_id: int
    members: list[LayerPath]
    identity_key: str          # from boundary signature
    confidence: float          # 0-1, based on layer agreement
    source_layer_count: int    # how many distinct layers contributed
    representative_surface: str
    quality_score: float       # spatial continuity + surface consistency
    
    @property
    def confidence_tier(self) -> str:
        if self.source_layer_count >= 3: return "high"
        if self.source_layer_count >= 2: return "medium"
        return "low"
```

### Core Algorithm

```python
def cluster_paths(
    layer_paths: list[LayerPath],
    distance_threshold: float = 8.0,  # DBSCAN eps in points
    signature_weight: float = 0.6,     # how much boundary signature matters
    proximity_weight: float = 0.3,     # how much spatial proximity matters
    angle_weight: float = 0.1,         # how much tangent alignment matters
) -> list[EdgeCluster]:
    """
    Two-level clustering:
    1. Group by boundary signature identity (Level 1)
    2. Within each identity group, DBSCAN by spatial proximity (Level 2)
    3. Score each cluster by layer agreement
    """
```

### The Two-Level Algorithm Detail

**Level 1: Identity Grouping**
- Compute `boundary_sig.identity_key()` for every path
- Group paths by identity key (exact match after bucketing curvature to 0.1 increments)
- This is O(n) — just a dictionary groupby

**Level 2: Spatial Sub-Clustering**
- Within each identity group, compute pairwise mean-nearest-point distance
- Run DBSCAN with `eps=distance_threshold`
- Each resulting sub-cluster is a spatial instance of that edge identity

**Scoring**
- `source_layer_count` = number of distinct layers in the cluster
- `quality_score` = weighted combination of:
  - Spatial continuity (are endpoints near each other? 0-1)
  - Surface consistency (do all members have similar curvature? 0-1)
  - Signature confidence (mean confidence of member boundary signatures)

### New MCP Tool

```python
def register(mcp):
    @mcp.tool("adobe_ai_cluster_paths")
    async def cluster_paths_tool(
        layer_names: list[str] | None = None,  # None = all extraction layers
        distance_threshold: float = 8.0,
        image_path: str | None = None,  # for normal map access
    ) -> dict:
        """
        Cluster paths across extraction layers into structural edge groups.
        Returns cluster assignments, confidence scores, and JSX to color-code.
        """
```

### Performance

- 300 paths → Level 1 grouping is O(n), typically produces 10-30 identity groups
- Level 2 DBSCAN within each group: each group has ~10-30 paths, so pairwise is ~100-900 comparisons per group
- Total: ~5,000-20,000 distance computations (vs. 90,000 for flat all-pairs)
- Boundary signature computation: 300 paths x 15 samples x 2 lookups = 9,000 pixel lookups (~10ms)

### Tests

- Synthetic paths with known boundary signatures cluster correctly
- Paths with same signature but far apart → separate spatial clusters
- Paths with different signatures but close together → separate clusters
- Noise paths (1 layer, low confidence) → flagged as low-confidence
- 3-layer overlap → high confidence score

---

## Phase 3: Panel Integration

### ExtendScript Additions (Shape Cleanup host.jsx)

```javascript
// New functions (all prefixed with sa_ per F1 fix)
function sa_clusterLayers(threshold) {
    // Call MCP tool via panel bridge, receive cluster assignments
    // Color-code paths on artboard (7 distinct hues, cycling)
    // Return summary string: "clusters|pathCount|layerCount|high|med|low"
}

function sa_acceptCluster(clusterId) {
    // Average all paths in cluster using existing classifyShape + placePreview
    // Log interaction: "cluster_accept"
    // Return "accepted|pathName"
}

function sa_acceptAllClusters() {
    // Batch accept: iterate clusters, average each
    // Log interaction: "cluster_accept_all"
    // Return "accepted|count"
}

function sa_splitCluster(clusterId) {
    // Remove cluster color-coding, let user manually reassign
    // Log interaction: "cluster_split" with before/after
}

function sa_rejectCluster(clusterId) {
    // Remove all paths in cluster
    // Log interaction: "cluster_reject"
}
```

### Panel UI Additions (index.html + main.js)

New section in Shape Cleanup panel (replaces nothing — adds above existing controls):

```
[Cluster Layers] button
  ↓
Distance threshold slider (1-30pt, default 8pt)
  Live update on change (debounced 300ms)
  ↓
Readout: "47 edge groups from 312 paths across 5 layers"
         "31 high-confidence, 12 medium, 4 low"
  ↓
Cluster list (scrollable, max 200px height):
  Each row: [color swatch] [identity label] [confidence badge] [path count]
  Click row → selects cluster paths on artboard
  ↓
Action buttons: [Accept] [Accept All] [Split] [Reject]
```

### Color Coding

7 distinct hues cycling per cluster: `[#FF4444, #44AA44, #4488FF, #FF8800, #AA44FF, #00AAAA, #FF44AA]`

Stroke weight encodes confidence:
- High (3+ layers): 2pt stroke
- Medium (2 layers): 1pt stroke  
- Low (1 layer): 0.5pt stroke, dashed

### Keyboard Shortcuts

- `A` — Accept All (the big one)
- `Enter` — Accept selected cluster
- `S` — Split selected cluster
- `Delete/Backspace` — Reject selected cluster
- `[` / `]` — Decrease / increase distance threshold by 1pt

---

## Phase 4: Learning Loop Wiring

### Cluster Correction Logging

Extend interaction logging to capture clustering decisions:

```json
{
    "action": "cluster_accept",
    "panel": "shapeaverager",
    "timestamp": "2026-04-05T10:30:00Z",
    "context": {
        "cluster_id": 7,
        "identity_key": "cylindrical|flat|0.3",
        "member_count": 4,
        "source_layers": ["Scale Fine", "Ink Lines", "Forms 5%"],
        "distance_threshold": 8.0,
        "confidence": 0.89,
        "quality_score": 0.92
    }
}
```

```json
{
    "action": "cluster_split",
    "context": {
        "cluster_id": 12,
        "identity_key": "flat|flat|0.1",
        "original_member_count": 6,
        "split_into": [3, 3],
        "reason_hint": "proximity_misleading"
    }
}
```

### Threshold Learning

New function in `correction_learning.py`:

```python
def learn_cluster_thresholds(
    corrections: list[dict],  # from interaction logs
    current_thresholds: dict,
) -> dict:
    """
    Adjust clustering thresholds per boundary identity type.
    
    - Accept at distance D → threshold for this identity can stay >= D
    - Split at distance D → threshold for this identity should be < D
    - Reject → this identity type at this confidence should be filtered
    
    Returns updated thresholds dict keyed by identity_key.
    """
```

### Convergence Signal

Track "Accept All accuracy" over time:
- `accept_all_ratio` = clusters accepted without modification / total clusters
- When `accept_all_ratio > 0.95` for 3 consecutive sessions → clustering has converged
- Log this milestone to interaction log

---

## Phase 5: Validation + Adversarial Review

- Run clustering on synthetic test data with known ground truth
- Run on real extracted paths from 3+ reference images
- 2 rounds adversarial review (5-6 hostile agents each, worktree isolation)
- Performance benchmark: clustering 300 paths must complete in <2 seconds
- Panel UX review with user

---

## Implementation Order

```
Phase 0: Adversarial fixes        → merge PR #5
Phase 1: Boundary signatures      → pure Python, testable in isolation
Phase 2: Clustering engine        → pure Python, testable in isolation  
Phase 3: Panel integration        → ExtendScript + JS, needs Illustrator
Phase 4: Learning loop            → Python + JSX, needs interaction data
Phase 5: Validation               → adversarial review + user testing
```

Phases 1 and 2 can be built and tested without Illustrator. Phase 3 requires the panel. Phase 4 requires real usage data.

---

## Files to Create

| File | Phase | Purpose |
|------|-------|---------|
| `src/adobe_mcp/apps/illustrator/analysis/boundary_signature.py` | 1 | Boundary signature computation |
| `src/adobe_mcp/apps/illustrator/analysis/edge_clustering.py` | 2 | Clustering engine + MCP tool |
| `tests/test_boundary_signature.py` | 1 | Signature tests |
| `tests/test_edge_clustering.py` | 2 | Clustering tests |

## Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| All 3 `host.jsx` | 0 | Namespace prefixes |
| All 3 `main.js` | 0 | Updated evalScript calls, allowlist |
| `polyfills.py` | 0 | Key escaping, proto guard |
| `json_es3.jsx` | 0 | Proto guard |
| `shapeaverager/jsx/host.jsx` | 3 | Cluster functions |
| `shapeaverager/js/main.js` | 3 | Cluster UI, polling fix |
| `shapeaverager/index.html` | 3 | Cluster section |
| `analysis/__init__.py` | 2 | Register new tools |
| `correction_learning.py` | 4 | Cluster threshold learning |
| `interaction_ingest.py` | 4 | Cluster event parsing |
