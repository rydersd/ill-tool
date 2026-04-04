# Adversarial Review Findings — Normal Intelligence PR

> Brief: Bugs found and fixed by 5 hostile review agents (2D math, Adobe/CEP, security, architecture, testing). Document patterns so they don't recur.
> Tags: review, bugs, security, math, cep, patterns
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

PR #2 (`feat/normal-intelligence`) was reviewed by 5 adversarial agents after implementation. They found 80+ issues across 5 categories. This article documents the bugs, their root causes, and the patterns to watch for.

## Round 1 Findings (5 agents, 80+ issues)

### 2D Math Specialist — 25 issues

| ID | Severity | Bug | Root Cause | Fix |
|----|----------|-----|------------|-----|
| CRIT-1 | CRITICAL | Eigenvector formula degenerates when dnx_dy=0 (axis-aligned cylinders produce [0,0] direction) | Only one eigenvector formula used, no fallback | Added fallback: when `|b| < eps`, use `[lambda-d, c]` instead of `[b, lambda-a]` |
| CRIT-2 | CRITICAL | Shape operator is Jacobian, not true Weingarten map — overestimates curvature at grazing angles | Screen-space normal field ≠ surface parameterization | Added docstring caveat. Acceptable approximation for illustration. |
| CRIT-3 | CRITICAL | Arc bezier handles 2.4x too long — `tan(sweep/4)` vs correct `tan(sweep/8)` per segment | 3-point arc = 2 segments, each needs sweep/8 not sweep/4 | Fixed formula. Also retracted endpoint outer handles. |
| HIGH-5 | HIGH | Ellipse semi-axes 41% too large — `2*sqrt(ev)` vs correct `sqrt(2*ev)` | Wrong variance-to-axis relationship for uniform perimeter distribution | Fixed: `a = sqrt(2 * ev1)` |
| HIGH-7 | HIGH | weldPoints doesn't swap left/right handles when reversing paths | Reversing traversal direction swaps incoming/outgoing handles | Added handle swap loop after each `.reverse()` |
| HIGH-2 | HIGH | RK4 streamline direction flips between substeps (180-degree line field ambiguity) | Principal directions are line fields, not vector fields — sign is arbitrary | Added `dot(ki, k1) < 0` coherence check on k2/k3/k4 |
| MED-1 | MEDIUM | curvature_line_weight has hard transitions at H=±0.02, not smooth sigmoid | Boolean masks create discontinuity at threshold | Replaced with single smooth formula: `0.3 + 0.4 * sigmoid(-H * 50)` |
| HIGH-8 | HIGH | Greedy endpoint matching misses better global pairings | O(n²) greedy picks first-found, not globally optimal | Acknowledged — greedy is acceptable for interactive use. Added to future improvements. |

**Pattern to watch:** Bezier handle formulas for multi-segment approximations. The formula changes based on how many segments cover the sweep. Always verify: `handle_length = (4/3) * tan(segment_angle / 4) * radius` where segment_angle is the angle PER SEGMENT, not total.

**Pattern to watch:** When reversing path point arrays, ALWAYS swap left↔right handles. This is easy to forget because the anchor positions are symmetric.

**Pattern to watch:** Eigenvector formulas degenerate when off-diagonal elements are zero. Always have a fallback eigenvector formula from the other row of the matrix.

### Adobe/CEP Specialist — 33 issues

| ID | Severity | Bug | Root Cause | Fix |
|----|----------|-----|------------|-----|
| C1 | CRITICAL | Hardcoded `/Users/ryders/...` path — panels break on any other machine | `$.evalFile()` needs absolute path, dev used literal | Derive from `$.fileName` at runtime, hardcoded fallback |
| C2 | CRITICAL | executeMerge _cachedPaths lacks _ref — index mismatch crashes merge | `getSelectedPaths()` doesn't store DOM references | Attach `_ref` on first iteration by matching indices |
| C3 | CRITICAL | Chain merge re-scan hardcodes tolerance=5, ignoring user slider | Copy-paste error in re-scan code | Store `_lastTolerance`, reuse in chain iterations |
| C4 | CRITICAL | applyBboxTransform cumulative — transform applied to already-moved points | No "original positions" stored, transform compounds | Store originals in `_bboxOriginalPoints`, always transform FROM originals |
| C5 | CRITICAL | eval() in jsonParse on world-writable /tmp/ files | ES3 has no JSON.parse, dev used eval() shortcut | Replaced with safe recursive-descent parser |
| C6 | HIGH | drawBoundingBox hardcodes "Cleaned Forms" layer | Function didn't accept layer parameter | Added `layerName` parameter with default |
| H1 | HIGH | Panel rename incomplete — old names in comments/CSS | Search-and-replace missed non-user-facing strings | Updated all comment references |
| L8 | HIGH | doUndo() name collision between panels in shared namespace | ES3 has no modules, all functions global | Renamed to `doUndoAverage()`, `doUndoMerge()` with aliases |

**Pattern to watch:** ExtendScript has NO module system. All functions from all panels share one global namespace per document. Use panel-specific prefixes for any function that could collide.

**Pattern to watch:** When building interactive transform tools, ALWAYS store original positions and transform from originals. Never accumulate transforms on already-moved points.

**Pattern to watch:** `$.evalFile()` paths must be derived at runtime. Use `$.fileName` → parent traversal, never hardcode developer paths.

### Security Specialist — 20 issues

| ID | Severity | Bug | Root Cause | Fix |
|----|----------|-----|------------|-----|
| C1 | CRITICAL | eval() in jsonParse enables arbitrary code execution via sidecar file in /tmp/ | eval() on untrusted input from world-writable directory | Replaced with recursive-descent parser |
| C2 | CRITICAL | Prototype pollution via `__proto__` keys in eval'd JSON | eval() creates objects that can pollute Object.prototype | Fixed by removing eval() |
| H1 | HIGH | Path traversal in logInteraction panelName parameter | No sanitization of panelName before use in file path | Added `panelName.replace(/[\/\\:]/g, "_")` |
| H3 | HIGH | Non-atomic sidecar write — partial read exploitation | Direct write to final path | Write to temp file, `os.replace()` for atomic rename |
| H4 | HIGH | evalScript injection via DOM-manipulated data-shape | Single-quoted string interpolation, no escaping | Use allowlist validation for shape types |
| H5 | HIGH | .debug files expose Chrome DevTools on fixed localhost ports | Development files committed to repo | Removed from git, added to .gitignore |
| H6 | HIGH | Unrestricted directory traversal via log_dir parameter | No path validation on MCP tool input | Validate path is within illtool app data directory |
| M5 | MEDIUM | World-writable /tmp/ output directory — symlink attacks | os.makedirs inherits umask | `os.chmod(OUTPUT_DIR, 0o700)` after creation |
| L6 | LOW | docName unsanitized in sidecar path — traversal via malicious filename | doc.name used directly in file path | Strip path separators from docName |

**Pattern to watch:** NEVER use eval() on data from files in world-writable directories (/tmp/). Even if "we control the writer," any local process can replace the file.

**Pattern to watch:** Any string used to construct a file path must be sanitized — strip `/`, `\`, `:`, `..`. This applies to both Python and ExtendScript.

**Pattern to watch:** Write files atomically (temp + rename) when readers may access them concurrently.

### Architecture Specialist — 24 issues

| ID | Severity | Bug | Root Cause | Fix |
|----|----------|-----|------------|-----|
| CRIT | CRITICAL | Sidecar path mismatch — JSX looks in wrong directory with wrong name | Python writes to `/tmp/ai_form_edges_{uid}/` with image basename, JSX reads from `/tmp/illtool_cache/` with doc name | JSX now searches multiple candidate locations + directory scan |
| HIGH | HIGH | No sidecar schema version — silent drift between producer/consumer | Implicit schema, no shared definition | Added version field consideration. SURFACE_TYPE_NAMES deduplicated. |
| HIGH | HIGH | id() GC reuse in curvature cache | Python can reuse memory addresses after GC | Content-based cache key using shape + dtype + sampled values |
| HIGH | HIGH | 200 imports with zero error handling — one bad file kills all tools | Monolithic registration with no try/except | Wrapped registrations in try/except with logging |
| MED | MEDIUM | Duplicate SURFACE_TYPE_NAMES in form_edge_extract and surface_classifier | Copy-paste during implementation | Import from single source (surface_classifier.py) |
| MED | MEDIUM | No cross-contour streamline count limit | RK4 traces uncapped polylines for large images | Added max_contours=100 parameter, keep longest |

**Pattern to watch:** When Python writes files that ExtendScript reads, the directory paths and filename conventions MUST be documented in a single shared location. A path mismatch makes the entire feature silently non-functional.

**Pattern to watch:** Module-level caches keyed by `id()` are unsafe — Python can reuse addresses after GC. Use content-based keys.

### Test Quality Specialist — 36 issues

| ID | Severity | Bug | Root Cause | Fix |
|----|----------|-----|------------|-----|
| P0 | CRITICAL | 4 tests pass with `return np.zeros_like(input)` | Tests check shape/dtype only, not values | Added value assertions: positive H on sphere, weight < 0.5 for ridges |
| P0 | CRITICAL | No NaN/non-unit/single-pixel/zero fixtures | Only 4 synthetic fixtures, all well-formed | Added 4 edge case fixtures + crash-resistance tests |
| P0 | CRITICAL | interaction_ingest: 0 tests for date filtering, panel filtering, MCP tool | Only internal helpers tested | Added filtering tests, edge cases |
| P1 | HIGH | cross_contour_field test silently passes on empty result | `if len(result) > 0:` skips body on empty | Changed to `assert len(result) > 0` first |
| P1 | HIGH | No integration test between form_edge_extract and surface_classifier | Schema tested synthetically only | Added schema round-trip test |

**Pattern to watch:** A test that only checks `output.shape` and `output.dtype` is worthless — it passes for `np.zeros_like()`. Always assert on VALUES: sign, range, specific pixel checks.

**Pattern to watch:** Tests with `if len(result) > 0:` are false positives — they silently pass when the function returns empty. Use `assert len(result) > 0` as a precondition.

## Recurring Anti-Patterns

1. **eval() on untrusted data** — appears as convenient shortcut for JSON parsing in environments without JSON.parse. Always build a proper parser.

2. **Hardcoded developer paths** — works on one machine, silently fails everywhere else. Derive paths at runtime.

3. **Shape/dtype-only test assertions** — the test "works" but catches nothing. Assert on values.

4. **Cumulative transforms** — applying transforms to already-moved points. Store originals, transform from originals.

5. **Global namespace collisions in ES3** — no modules means every function name must be globally unique across all panels.

6. **Path mismatch between writer and reader** — when two systems communicate via files, the path conventions must be documented and tested.

7. **Handle swap on path reversal** — reversing a bezier path's point array requires swapping left↔right handles on every point.

## See Also
- [[Form Edge Extraction Workflow]] — The extraction pipeline these bugs were found in
- [[Smart Merge Architecture]] — The merge panel that triggered the sidecar path bug
- [[Expanded Normal Renderings]] — The eigendecomposition that had the degenerate eigenvector bug
