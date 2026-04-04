---
date: 2026-04-04T21:00:00Z
session_name: general
researcher: rydersd
git_commit: c941160
branch: refactor/module-structure
repository: ill_tool
topic: "Normal Map Intelligence + CEP Panels + Module Refactor + Edge Clustering Plan"
tags: [normal-renderings, eigendecomposition, cep-panels, adversarial-review, module-refactor, edge-clustering, learning]
status: complete
last_updated: 2026-04-04
last_updated_by: rydersd
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Normal Map Intelligence — Full Session

## Task(s)

### Completed
1. **PR #2 (merged)** — 10 new normal renderings from shape operator eigendecomposition, normal sidecar file, surface classifier, coordinate transforms, Smart Merge CEP panel, Shape Cleanup panel refinements, Grouping Tools panel, interaction capture system, shared ExtendScript library extensions. 1800 tests.
2. **PR #3 (merged)** — Adversarial review round 3 fixes: isolation mode exit guidance, merge confirmation dialog, first-use help, polyfill security (eval→parser), $.fileName try/catch.
3. **PR #4 (merged)** — UX polish: 20px icons with text labels, keyboard shortcuts (Enter/Esc/Space/1-7), consistent terminology, WCAG AA contrast, tooltips, orphan cleanup, selection polling lifecycle.
4. **3 rounds of adversarial review** — 14 hostile agent runs, 125+ issues found and fixed, 14 anti-patterns documented in wiki.
5. **Shape Cleanup interaction model** — Removed panel-side bbox canvas, added selection polling with live re-averaging, native Free Transform after confirm, hidden originals during cleanup, 2x blue bbox corner handles.

### In Progress (PR #5 — open, not merged)
6. **Module refactor** — 197 files split into 14 subdirectories (core/, drawing/, rigging/, analysis/, character/, animation/, storyboard/, production/, pipeline/, export_formats/, ml_vision/, threed/, ui/, utility/). 124 cross-imports fixed, 237 test imports updated. 1786 tests passing.
7. **Install script** updated to symlink all 3 CEP panels.
8. **Edge clustering handoff** written — ready for implementation.

### Planned (next session)
9. **Cross-Layer Edge Clustering** — The single most impactful next feature. Auto-cluster paths across all extraction layers into "same structural edge" groups. Distance threshold slider, overlap confidence scoring (multi-layer agreement = high confidence), Accept/Accept All/Split/Reject workflow, learning loop from corrections.

## Critical References
- `thoughts/shared/handoffs/general/2026-04-04_20-00-00_edge-clustering-cleanup.md` — Full spec for edge clustering feature
- `wiki/concepts/adversarial-review-findings.md` — 14 anti-patterns to avoid (eval injection, handle swap, namespace collision, etc.)
- `wiki/concepts/edge-clustering.md` — Architecture overview of clustering feature

## Recent changes
- `src/adobe_mcp/apps/illustrator/` — 197 files moved to 14 subdirectories
- `src/adobe_mcp/apps/illustrator/__init__.py` — 458→68 lines, delegates to subdirectory register functions
- `cep/com.illtool.shapeaverager/jsx/host.jsx` — Hidden originals, 2x bbox handles, selection polling, getSelectionInfo, cleanupOrphans
- `cep/com.illtool.shapeaverager/js/main.js` — Removed ~490 lines of bbox canvas code, added polling + live re-average + help toggle
- `cep/com.illtool.shapeaverager/index.html` — Selection count in header, help behind ⋯, removed bbox canvas section
- `cep/shared/ui.jsx` — drawBoundingBox now creates blue filled circle handles at corners
- `cep/shared/json_es3.jsx` — Safe recursive-descent parser (no eval)
- `src/adobe_mcp/jsx/polyfills.py` — JSON.parse polyfill replaced with safe parser
- `scripts/install-cep-panels.sh` — Now installs all 3 CEP tool panels

## Learnings

### ExtendScript Constraints
- No mouse events on canvas — can't build interactive handles in ExtendScript. Use native Illustrator tools instead.
- `$.fileName` can be empty — always wrap in try/catch with hardcoded fallback.
- ES3 global namespace — all functions from all panels share one scope. Use panel-specific prefixes.
- `eval()` on `/tmp/` files is arbitrary code execution — always use recursive-descent parser.

### Adversarial Review Methodology
- 3 rounds with 5-6 hostile agents each is effective. Round 1 finds bulk issues, round 2 catches unfixed/reintroduced bugs, round 3 verifies convergence.
- UX review should happen in round 1, not round 3 — the most user-facing issues were found latest.
- Agents can overwrite each other's fixes when working on overlapping files. Use `isolation: "worktree"` or serialize.
- "Fix agent says done" ≠ "fix is actually in the code." Always re-read files to verify.

### UX Principles (from user feedback)
- Panel-side canvas proxies aren't useful — work should happen on the artboard with native tools.
- Help text that's always visible hides the controls — put behind a toggle.
- Preview path should be selected so anchor handles are visible.
- Original paths hidden during cleanup (opacity 0), restored on cancel.
- Bbox handles must be visually distinct (2x size, different color) from shape anchors.

## Post-Mortem

### What Worked
- **Parallel agent execution**: Launching 3-6 agents simultaneously for implementation cut wall-clock time dramatically. Phase 0A-1B all ran in parallel.
- **Adversarial review pattern**: 14 hostile agents across 3 rounds caught 125+ issues including critical security (eval injection), broken core features (sidecar path mismatch), and math errors (bezier handles 2.4x wrong).
- **Wiki as institutional memory**: `adversarial-review-findings.md` with 14 anti-patterns means future sessions can reference known pitfalls.
- **Shape operator eigendecomposition**: One mathematical operation (eigendecompose the 2x2 Weingarten map) unlocked 10 new renderings from the same normal map. Zero new ML models needed.
- **Sidecar file pattern**: Python writes surface metadata per-path, JSX reads it for form-aware merge intelligence. Decoupled but connected.

### What Failed
- **Panel-side bbox canvas**: Built ~490 lines of canvas drag/affine code. User feedback: "not super useful." Removed and replaced with native Free Transform. Should have asked before building.
- **Parallel agents on overlapping files**: Fix agents overwrote each other's changes. The RK4 coherence fix and smooth sigmoid fix had to be reapplied. Need worktree isolation.
- **"Fix claimed but not shipped"**: Round 2 found that round 1's eigenvector fallback and log_dir validation were claimed as done by the fix agent but weren't in the code. Trust but verify.
- **Help text visible by default**: Took up space and hid controls. User wanted it behind ⋯ toggle.

### Key Decisions
- **Merge PR #2 as single unit** (feature + R1+R2 fixes) rather than splitting into separate PRs. Commits are tightly coupled on the same files.
- **Normal sidecar as bridge** between Python (writes) and ExtendScript (reads). Decoupled architecture — panels work without server (graceful degradation).
- **Standalone CEP panels** (no WebSocket) — all math in ExtendScript. Reliability over elegance.
- **Module refactor AFTER features** — avoided blocking feature work. Each subdirectory migrated and tested independently.
- **Usage data in ~/Library/Application Support/illtool/** — persistent across reboots, not /tmp/.

## Artifacts
- `wiki/concepts/expanded-normal-renderings.md` — 10 new renderings documentation
- `wiki/concepts/smart-merge.md` — Smart Merge architecture
- `wiki/concepts/adversarial-review-findings.md` — 125+ bugs, 14 anti-patterns
- `wiki/concepts/edge-clustering.md` — Next feature spec
- `thoughts/shared/handoffs/general/2026-04-04_20-00-00_edge-clustering-cleanup.md` — Full clustering handoff
- `cep/com.illtool.shapeaverager/` — Shape Cleanup panel (all files)
- `cep/com.illtool.smartmerge/` — Smart Merge panel (all files)
- `cep/com.illtool.pathrefine/` — Grouping Tools panel (all files)
- `cep/shared/` — 7 shared ExtendScript libraries
- `src/adobe_mcp/apps/illustrator/normal_renderings.py` — 15 rendering functions
- `src/adobe_mcp/apps/illustrator/surface_classifier.py` — Surface classification utility
- `src/adobe_mcp/apps/illustrator/coordinate_transforms.py` — Shared transform utility
- `src/adobe_mcp/apps/illustrator/interaction_ingest.py` — MCP ingestion tool
- `tests/test_expanded_renderings.py` — 52 tests for new renderings
- `tests/test_surface_classifier.py` — 35 tests
- `tests/test_coordinate_transforms.py` — 38 tests
- `tests/test_interaction_ingest.py` — 11 tests

## Action Items & Next Steps

### Immediate (next session)
1. **Merge PR #5** (`refactor/module-structure`) — module refactor + all UX fixes + clustering handoff. 1786 tests passing.
2. **Build Edge Clustering** — the single most impactful feature. Full spec at `thoughts/shared/handoffs/general/2026-04-04_20-00-00_edge-clustering-cleanup.md`. Key: DBSCAN with distance threshold slider, cross-layer overlap confidence, Accept All workflow.
3. **Wire learning loop closed** — feed reclassification history from interaction logs into classifyShape() confidence adjustments. The correction_learning pattern exists; needs to be connected to the CEP panels.

### Medium priority
4. **Fragment Sweeper** — one-click remove paths below N points or M length on a layer.
5. **Select Similar** — click one path, auto-select all nearby paths with similar angle/curvature.
6. **Snap to Reference** — after averaging, snap cleaned path to nearest edge in reference image.

### Lower priority
7. **Module refactor PR review** — run adversarial review on PR #5 before merge.
8. **RINDNet++ real model** — when pip-installable.

## Other Notes

### Branch state
- `master` — up to date with PRs #2, #3, #4 merged
- `refactor/module-structure` — PR #5 open, 6 commits ahead of master
- `feat/normal-intelligence` — can be deleted (merged)
- `fix/adversarial-review-r3` — can be deleted (merged)
- `feat/ux-polish` — can be deleted (merged)

### Panel installation
Panels must be installed via `bash scripts/install-cep-panels.sh` and Illustrator restarted to see them in Window > Extensions.

### User preferences (from session)
- "Later, just do what the user would do" — the learning loop is the endgame
- Bbox on artboard, not panel canvas
- Help behind ⋯ toggle, not always visible
- Preview selected so handles visible
- Originals hidden during cleanup
- Bbox handles 2x size, blue, visually distinct
- Track usage in app data (~/Library/Application Support/illtool/)
- Shape type icons should be bigger and use their space
- "Shape Averager" renamed to "Shape Cleanup"
- "Path Detach & Refine" renamed to "Grouping Tools"
- Clustering needs a distance threshold slider
- Multi-layer clustering, merge to single layer, analyze overlaps
