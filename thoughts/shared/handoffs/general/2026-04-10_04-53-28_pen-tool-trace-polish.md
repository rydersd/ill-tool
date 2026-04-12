---
date: 2026-04-10T04:53:28+0000
session_name: general
researcher: claude
git_commit: fe156d3
branch: fix/pen-tool-and-polish
repository: ill_tool
topic: "Massive session: undo, trace pipeline, MCP integration, refactor, pen tool"
tags: [undo, trace, mcp, normals, perspective, refactor, pen-tool, centerline, telemetry]
status: complete
last_updated: 2026-04-10
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Full Backlog Implementation → Trace Pipeline → Pen Tool

## Task(s)

### Completed
- **Native Illustrator undo** — removed SetSilent/custom UndoStack. SDK tool context bundling handles per-drag undo. Global undo context (SetUndoTextUS) for all mutating ops in ProcessOperationQueue. 4 adversarial review rounds, all P0s fixed.
- **Ill Trace panel** — 12 backends in per-model accordion with params + Run buttons. vtracer end-to-end: image→SVG→AI paths. Full SVG command support, transform="translate" parsing, fill colors, coordinate mapping.
- **3 output modes** — Outline (BW strokes), Fill (colored regions), Centerline (Canny→dilate→Zhang-Suen skeleton→vtracer)
- **Semantic grouping** — normal-map-guided surface grouping via k-means. Height-to-normal in C++ (Sobel, no DSINE). Persistent surface identity via AIDictionary.
- **MCP HTTP integration** — 6 routes replacing CEP (/api/inspect, create_path, create_shape, layers, select, modify). Condvar sync mechanism. Batch endpoint + journal.
- **Normal-to-VP pipeline** — VisionEngine ClusterNormalDirections + EstimateVPsFromNormals. Dual detection (Hough + normals).
- **Blend color interpolation** — A→B for intermediates. Pick auto-activates tool.
- **Code refactor** — deleted 7 legacy files (6400 lines), split 3 monoliths into 9 files. No file over 2200 lines.
- **ProjectStore** — saves trace artifacts alongside .ai file.
- **Telemetry** — opt-in anonymous upload with SHA-256 machine ID, PII stripping.
- **Ill Pen Tool** — registered as 3rd toolbox tool. Module + panel created with chamfer, grouping integration, presets.

### In Progress (P0 for next session)
- **Pen tool preview path fails** — `NewArt(kPathArt)` called from mouse handler context (not timer). Needs bridge enqueue pattern.
- **Pen panel not in Window menu** — AddAppMenu missing Pen entry.
- **Undo grayed out after trace** — SetUndoTextUS in timer context may not create proper undo context.

### Planned / Discussed
- Perspective/normal snap for pen tool
- Auto-offset from adjacent curves (parallel panel lines)
- Chamfer width + distance (industrial fillet)
- Transform arrays (radial/linear)
- IllToolPlugin.cpp split into 4 files
- Per-model trace presets
- Spatial/structural grouping (containment-based instead of luminance)

## Critical References

1. **PRD**: `wiki/concepts/illtool-prd.md` — full product requirements with UX specs
2. **Session article**: `wiki/concepts/session-2026-04-09.md` — key decisions, what was built, adversarial review results
3. **Prior handoff**: `thoughts/shared/handoffs/general/2026-04-09_session_handoff.md` — detailed status of all features

## Recent Changes

- `plugin/Source/modules/PenModule.cpp` — new module, click-to-draw with chamfer arc computation
- `plugin/Source/panels/PenPanelController.mm` — pen panel with chamfer, grouping, presets
- `plugin/Source/IllToolPlugin.cpp:673-692` — pen tool registration as 3rd toolbox tool
- `plugin/Source/IllToolPlugin.cpp:330-360` — pen tool mouse drag/up routing
- `plugin/Source/IllToolPlugin.cpp:768-790` — global undo context (SetUndoTextUS) per op type
- `plugin/Source/modules/TraceModule.cpp:497-570` — centerline mode (Canny→skeleton)
- `plugin/Source/VisionEngine.cpp:1983-2095` — Zhang-Suen skeletonize + GenerateNormalFromHeight
- `plugin/Source/ProjectStore.cpp` — new, project-level data persistence
- `plugin/Source/LearningEngine.cpp:639-930` — telemetry consent, anonymization, upload

## Learnings

### Pen tool NewArt must use bridge enqueue
`sAIArt->NewArt()` called from `ToolMouseDown` handler fails because the mouse handler context may not have proper art creation permissions. The pattern used by ALL other modules: enqueue an op via `BridgeEnqueueOp`, let `ProcessOperationQueue` (timer callback) execute the SDK call. The pen tool bypasses this and calls NewArt directly from HandleMouseDown → fails.

### Undo requires proper context, not just SetUndoTextUS
`SetUndoTextUS` sets the menu text but may not actually create an undo context in the timer callback. The SDK says undo contexts are created "each time Illustrator sends a plug-in a selector" — timer callbacks may not get one. May need to use `AIUndoSuite::SetKind(kAIStandardUndoContext)` explicitly.

### SVG transform="translate(x,y)" is critical for vtracer output
6030/6031 vtracer paths carry non-zero translate transforms. Without parsing these, all paths cluster at origin. This was the root cause of the coordinate collapse bug.

### Raster matrix: copy from original, don't compute
After many failed attempts to compute the raster placement matrix (4 wrong combinations of d/ty signs), the working solution: read the original image's matrix via `GetRasterMatrix` and copy it exactly for embedded rasters.

### FindImagePath must skip our own embedded rasters
After embedding raster references, `GetMatchingArt(kRasterArt)` finds our embedded images instead of the original. Fix: skip rasters on hidden/locked layers (our refs are always hidden+locked).

### DSINE fails on illustrations
DSINE expects photos of real 3D objects. Midjourney illustrations have painted shading but no actual geometry. The height-to-normal (Sobel on grayscale) approach works much better for illustrations.

## Post-Mortem

### What Worked
- **Native undo** — removing SetSilent and letting SDK handle undo natively was the correct approach. Custom UndoStack with SetPathSegments crashed repeatedly.
- **Agent parallelization** — splitting HttpBridge and PerspectiveModule using two background agents simultaneously saved significant time.
- **Codex adversarial reviews** — found the stale AIArtHandle root cause for undo crash, the translate transform root cause for coordinate collapse, and the AISlice front/back fields for GetRasterTile.
- **Bridge enqueue pattern** — every mutating operation going through the timer callback is the only safe way to use SDK APIs.
- **Per-model accordion panel** — much better UX than the flat checkbox list. Each model owns its params.

### What Failed
- **Custom UndoStack** — 4 attempts to fix (clear on boundaries, frame validation, RedrawDocument removal, Codex fixes). All failed. Root cause was fundamental: SetPathSegments from timer conflicts with SDK internal undo state.
- **AIArtboardSuite C++ wrappers** — `ai::ArtboardList` needs `IAIArtboards.cpp` which pulls in assertion stubs we don't have. Blocked.
- **Raster placement matrix** — tried 4 combinations of d/ty signs. None computed correctly. Only copying the original's matrix works.
- **DSINE on illustrations** — produces garbage normals. Height-to-normal is the right approach.
- **Codex reliability** — timed out or returned shallow results ~40% of the time. Manual verification was often needed as backup.

### Key Decisions
- **Decision**: Native Illustrator undo instead of custom UndoStack
  - Alternatives: SetSilent + manual segment restoration, AIUndoSuite::UndoChanges
  - Reason: SDK bundles tool mouse events into undo contexts automatically. Custom approaches all crashed.

- **Decision**: Direct vtracer call via popen instead of MCP HTTP
  - Alternatives: HTTP POST to MCP server, MCP stdio protocol
  - Reason: MCP uses stdio (not HTTP). Plugin HTTP server was POSTing to itself. Direct popen is simpler.

- **Decision**: #include .cpp pattern for new modules (not in pbxproj)
  - Alternatives: edit Xcode project file
  - Reason: modifying pbxproj risks breaking the build. Include pattern is fragile but avoids the risk.

- **Decision**: Height-to-normal (Sobel) instead of DSINE for illustrations
  - Alternatives: DSINE neural network, StableNormal, GeoWizard
  - Reason: DSINE fails on painted shading. Sobel is instant and works on illustrations.

## Artifacts

- `plugin/Source/modules/PenModule.h` + `.cpp` — Ill Pen Tool module
- `plugin/Source/panels/PenPanelController.h` + `.mm` — Pen panel
- `plugin/Source/modules/TraceModule.h` + `.cpp` — Trace pipeline (~1800 lines, may need split)
- `plugin/Source/panels/TracePanelController.mm` — 12-backend accordion panel
- `plugin/Source/ProjectStore.h` + `.cpp` — Project data persistence
- `plugin/Source/VisionEngine.cpp` — Skeletonize, GenerateNormalFromHeight, ClusterNormalMapRegions
- `plugin/tools/run_trace_backend.py` — Python backend runner for normal_ref/form_edge
- `wiki/concepts/session-2026-04-09.md` — Session documentation
- `thoughts/shared/handoffs/general/2026-04-09_session_handoff.md` — Prior handoff

## Action Items & Next Steps

### P0 (fix immediately)
1. **Fix pen tool NewArt** — enqueue PenPlacePoint op via bridge, let timer create preview path
2. **Add Pen to Window menu** — add entry in AddAppMenu function
3. **Fix undo grayed out** — investigate timer context undo wrapping, may need SetKind(kAIStandardUndoContext)

### P1 (next iteration)
4. **Pen perspective snap** — snap points to VP grid lines when perspective active
5. **Split IllToolPlugin.cpp** — into Tools, Menu, MCP, Core (4 files)
6. **Trace re-vectorize normal renderings** — BW trace produces 0 paths, need different approach

### P2 (feature backlog)
7. Auto-offset from adjacent curves (parallel panel lines)
8. Chamfer width + distance (industrial fillet)
9. Transform arrays (radial/linear duplication)
10. Per-model trace presets
11. Spatial/structural grouping (containment hierarchy)

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies, clean builds, signs, notarizes, staples (~3min)
# Launch with logs:
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### Module Count: 12
Selection, Cleanup, Perspective, Merge, Grouping, Blend, Shading, Decompose, Transform, Trace, Surface, Pen

### Panel Count: 11
Selection, Cleanup, Grouping, Merge, Shading, Blend, Perspective, Transform, Ill Trace, Ill Surface, Ill Pen

### Tool Count: 3
IllTool Handle, IllTool Perspective, IllTool Pen

### Key Architecture
- All SDK calls MUST go through timer callback (ProcessOperationQueue at 10Hz)
- New modules: `#include "Module.cpp"` from IllToolPlugin.cpp (not in pbxproj)
- New panels: `#include "Panel.mm"` from IllToolPanels.mm (not in pbxproj)
- Bridge state: atomic for simple types, mutex for strings
- MCP sync: condvar handshake between HTTP thread and timer callback
- Deploy script copies source to SDK directory, clean builds, signs, notarizes

### Stale plugin warning
A stale plugin copy at `~/Library/Application Support/Adobe/Illustrator/Plug-ins/` was found earlier. If panels don't load, check for duplicates there.
