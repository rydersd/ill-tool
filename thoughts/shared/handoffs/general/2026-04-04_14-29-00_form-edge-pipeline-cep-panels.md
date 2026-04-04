---
date: 2026-04-04T14:29:00Z
session_name: general
researcher: rydersd
git_commit: a8ab775c8aca4875bf3af6dddf1bb852921df037
branch: feat/spatial-3d-pipeline
repository: ill_tool
topic: "Form Edge Pipeline + CEP Panels + Shape Averaging"
tags: [form-edges, dsine, normals, cep-panels, shape-averaging, path-refinement, illustrator]
status: complete
last_updated: 2026-04-04
last_updated_by: rydersd
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Form Edge Pipeline, CEP Panels, and Interactive Path Tools

## Task(s)

### Completed
1. **Wiki bootstrap** — Created project wiki (23 articles) covering architecture, research surveys, tool inventory, spatial pipeline, drawing methods. Migrated full research surveys from docs/research/.
2. **Cross-project knowledge base** — Created `~/Developer/GitHub/llm-tooling` repo (28 articles) for reusable patterns, agent catalogs, skill documentation. Global rules updated to reference it.
3. **Form edge pipeline (Phase 0-4)** — DSINE normal estimation → 5 shadow-free renderings → form edge extraction → integration with drawing orchestrator, smart dispatcher, feedback loop. 1613 tests.
4. **Security hardening** — 3 rounds of adversarial review. Path validation, JSX injection prevention, image size limits, commit-pinned DSINE, thread-safe model loading. 250 tests for fixes.
5. **RINDNet++ + Informative Drawings** — Edge classifier with heuristic fallback, ONNX line art extraction. Auto-selection: rindnet > dsine > informative > heuristic.
6. **2D Vector Math skill tree** — 8-node skill tree: bezier-curves, path-operations, path-optimization, contour-extraction, coordinate-transforms, vectorization, svg-interchange.
7. **Shape Averager CEP panel** — PCA sorting, shape classification (7 types), LOD precomputation, interactive reclassification. Standalone (no WebSocket).
8. **Path Detach & Refine CEP panel** — Detach selected anchors, simplify with instant slider, auto-rotated bounding box. Standalone.
9. **Shared ExtendScript library** — 5 modules (math2d, geometry, shapes, pathutils, ui) — 1,450 lines of ES3 math shared between panels.
10. **Mech + GIR tracing** — Tested extraction on 3 reference images. Identified winning tool stack: Scale Fine/Medium/Coarse + Ink Lines + Forms 5%.

### In Progress / Discussed
11. **Smart Merge tool** — Proximity-based endpoint merging for disparate paths within radius. Like 3D auto-merge. Discussed, not built.
12. **Interaction capture** — Log user panel actions (reclassifications, adjustments, deletions) to inform tool evolution. Discussed, not built.
13. **Shape tool refinements** — User wants: 3-point output curves (not N-point), isolation mode after placement, rotatable bounding box as skew modifier with control points, GIR eye chevron merging without changing form.
14. **Module refactor** — Split flat 200+ file illustrator directory into core/, drawing/, rigging/, storyboard/, ml_backends/, pipeline/ subdirectories. Discussed, not started.

## Critical References
- `wiki/concepts/form-edge-extraction-workflow.md` — Ranked tool stack and critical implementation details
- `wiki/concepts/normal-map-as-reference.md` — The architectural insight: one DSINE prediction improves all tools
- `.claude/plans/wobbly-leaping-yeti.md` — Last active plan (standalone CEP panels)

## Recent changes
- `cep/shared/*.jsx` — 5 shared ExtendScript libraries (NEW)
- `cep/com.illtool.shapeaverager/jsx/host.jsx` — Rewritten standalone, $.evalFile includes
- `cep/com.illtool.pathrefine/jsx/host.jsx` — Rewritten standalone, $.evalFile includes
- `src/adobe_mcp/apps/illustrator/average_selection.py` — MCP tool + math (NEW)
- `src/adobe_mcp/apps/illustrator/form_edge_extract.py` — MCP tool (NEW)
- `src/adobe_mcp/apps/illustrator/form_edge_pipeline.py` — Pure Python pipeline (NEW)
- `src/adobe_mcp/apps/illustrator/normal_reference.py` — MCP tool (NEW)
- `src/adobe_mcp/apps/illustrator/normal_renderings.py` — 5 rendering functions (NEW)
- `src/adobe_mcp/apps/illustrator/ml_backends/normal_estimator.py` — DSINE wrapper (NEW)
- `src/adobe_mcp/apps/illustrator/ml_backends/edge_classifier.py` — RINDNet++ (NEW)
- `src/adobe_mcp/apps/illustrator/ml_backends/informative_draw.py` — ONNX backend (NEW)
- `src/adobe_mcp/apps/illustrator/path_validation.py` — Security utility (NEW)

## Learnings

### Coordinate Systems
- **Illustrator artboards vary**: Some documents have artboard at (0,0,width,-height), others at (0,height,width,0). ALWAYS read `artboardRect` from the actual document — never assume.
- GIR document: `ab:[0,0,758,-1052]` — Y goes negative downward. Transform: `ai_y = -(pixel_y * scale)`.
- Big Mech document: `ab:[0,1272,952,0]` — Y goes from 1272 (top) to 0 (bottom). Transform: `ai_y = 1272 - (pixel_y * scale)`.

### ExtendScript / CEP
- `JSON.stringify` fails in Illustrator without polyfill. Use pipe-delimited strings for JSX returns.
- `#include` paths break through symlinks. Use `$.evalFile()` with absolute paths.
- `app.redraw()` must be called after creating visible content or Illustrator won't repaint.
- JSX files > 2MB cause osascript timeout. Split into per-layer files or reduce point counts.
- CEP `ScriptPath` loads host.jsx at panel startup; `evalScript` calls functions already loaded.

### Edge Extraction
- **Skeletonize before contouring** — `findContours` on raw edge masks produces doubled-up boundary paths. Skeletonize gives single-pixel centerlines → open paths.
- **No figure mask for ink drawings** — Otsu threshold on white-background art produces bad masks. The ink IS the content.
- **Schneider fitting warps Y** — The curve fitter distorts coordinates during optimization. Place raw points with C1 handles first, smooth AFTER positioning.
- **Douglas-Peucker epsilon=2.0** — Good balance for mechanical illustration. epsilon=1.0 keeps too many points (huge JSX), epsilon=4.0 loses detail.

### Tool Stack (ranked by user feedback on mechs)
1. Scale Fine (Canny blur=3, 40-100)
2. Scale Medium (Canny blur=7, 50-120)
3. Scale Coarse (Canny blur=15, 60-150)
4. Ink Lines (adaptive threshold filtered by dilated normal form edges)
5. Forms 5% (DSINE normals, skeletonized)
6. Curvature (Gaussian curvature from normals) — supplementary
7. Plane Boundaries k=8 (k-means on normals) — supplementary

## Post-Mortem

### What Worked
- **DSINE on MPS**: 4-6s inference, produces clean normal maps. Shadow-free form extraction is a real improvement over all prior approaches.
- **Multi-threshold exploration**: Running 7+ threshold levels on each tool type, color-coded by layer, lets the user toggle and compare. Science approach — don't delete experiments.
- **Adversarial review methodology**: 3 parallel hostile agents (bug hunter, security auditor, architect) found 23 issues in round 1, drove quality significantly.
- **Shared ExtendScript library**: 5 modules, no duplication between panels. ES3-compatible with full implementations (PCA, convex hull, rotating calipers, Douglas-Peucker).
- **Wiki knowledge base**: `index.md` as LLM routing table — instant context for future sessions.

### What Failed
- **Schneider curve fitting for placement**: Warps Y coordinates during least-squares optimization. Must place points first, optimize handles separately.
- **Figure mask on ink drawings**: Otsu thresholding misclassifies white background on ink art. Caused paths to cluster at bottom of artboard.
- **WebSocket-dependent panels**: Required MCP server running. Users expect panels to work standalone. Rewrote to pure ExtendScript.
- **PCA-based point averaging**: Projecting all points onto one axis destroys 2D shape for non-linear forms (arcs, L-shapes, rectangles). Fixed with arc-length parameterized averaging.
- **`#include` through symlinks**: CEP panels installed via symlinks can't resolve relative `#include` paths. Fixed with `$.evalFile()` + absolute paths.
- **JSON.stringify in JSX**: Illustrator ES3 engine has no native JSON. Kept hitting this — pipe-delimited strings are the reliable pattern.

### Key Decisions
- **Normal map as preprocessor, not parallel pipeline**: One DSINE prediction generates 5 renderings that improve all 245+ tools, rather than building a competing edge extraction path.
- **Standalone panels over WebSocket**: Reliability > elegance. All math in ExtendScript means panels work without any server running.
- **Preserve experiments**: User directive: "This is science, you don't delete your experiments." Group, hide, lock — never delete exploration layers.
- **Dark orange/dark blue for path colors**: Never yellow or light gray. Orange for preview/detached paths, blue for bounding boxes, black for confirmed.
- **Hardcoded repo path in $.evalFile**: Ugly but reliable. CEP path resolution through symlinks is too fragile for dynamic resolution.

## Artifacts
- `wiki/` — 23 articles (project wiki)
- `~/Developer/GitHub/llm-tooling/` — 28 articles (cross-project KB)
- `~/.claude/skills/2d-vector-math/` — 8 skill files
- `cep/shared/` — 5 shared ExtendScript libraries
- `cep/com.illtool.shapeaverager/` — Shape Averager CEP panel
- `cep/com.illtool.pathrefine/` — Path Detach & Refine CEP panel
- `src/adobe_mcp/apps/illustrator/form_edge_extract.py` — Form edge MCP tool
- `src/adobe_mcp/apps/illustrator/normal_reference.py` — Normal reference MCP tool
- `src/adobe_mcp/apps/illustrator/average_selection.py` — Shape averaging MCP tool
- `src/adobe_mcp/apps/illustrator/ml_backends/` — DSINE, RINDNet++, Informative Drawings
- `tests/test_average_selection.py` — 44 tests
- `tests/test_form_edge_*.py` — 80+ tests
- `tests/test_normal_*.py` — 86 tests
- `tests/test_path_validation.py` — 20 tests
- `.claude/plans/wobbly-leaping-yeti.md` — Last active plan

## Action Items & Next Steps

### High Priority
1. **Smart Merge tool** — New CEP panel: select multiple open paths, merge endpoints within configurable radius. Like 3D auto-merge. Should also handle GIR's eye chevrons (merge without changing form).
2. **Shape tool output simplification** — Average should produce 3-point curves, not N-point median pass-throughs. Enter isolation mode after placement for direct editing.
3. **Interaction capture system** — Log panel interactions (reclassifications, adjustments, point edits) to a JSON journal. Use this data to improve auto-classification over time.
4. **Bounding box as skew modifier** — Rotatable with control points. Acts as a constraint/transform tool, not just a visual guide.

### Medium Priority
5. **Module refactor** — Split `src/adobe_mcp/apps/illustrator/` (200+ flat files) into `core/`, `drawing/`, `rigging/`, `storyboard/`, `ml_backends/`, `pipeline/`.
6. **Coordinate transform robustness** — Read artboardRect dynamically in every extraction, not assume origin. The GIR offset bug and the mech figure-mask bug both stem from incorrect coordinate assumptions.
7. **Push branch / merge PR** — PR #1 at github.com/rydersd/ill-tool/pull/1 has all commits. Needs final review and merge to master.

### Lower Priority
8. **10-innovation evolution cycle** — User requested: run 10 rounds of "smartest addition" brainstorming, PR, adversarial review, iterate.
9. **Obsidian vault** — Set up single vault spanning all project wikis + llm-tooling KB for cross-project search and graph visualization.
10. **RINDNet++ actual model integration** — Currently uses heuristic fallback. When RINDNet++ becomes pip-installable, wire the real model.

## Other Notes

### Branch state
- `feat/spatial-3d-pipeline` — 10 commits ahead of master
- PR #1 open at github.com/rydersd/ill-tool/pull/1
- All tests pass: 1613+ (excluding pre-existing Adobe smoke test failures)

### User preferences (from memory)
- Never delete experiments — group, hide, lock
- Path colors: dark orange for preview, dark blue for guides, NEVER yellow or light gray
- Layer colors: orange=type, royal blue=illustration, gray=grid
- Always `app.redraw()` after JSX that creates content
- Tests alongside features, never ship untested
- Clip to artboard bounds, never bleed into pasteboard

### GIR-specific note
User mentioned: "his eyes are a strange shape, the chevron... i want to merge them without changing the form." This is the primary use case for the Smart Merge tool — merge path segments that form a complex shape (like GIR's angular eyes) at their endpoints while preserving the overall contour.
