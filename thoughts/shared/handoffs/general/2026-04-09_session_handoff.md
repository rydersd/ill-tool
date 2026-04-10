---
date: 2026-04-09
session_name: general
branch: feat/pipeline-gaps-surface-extraction
repository: ill_tool
topic: "Full session: undo fix, trace pipeline, MCP integration, refactor, pen tool"
status: in_progress
---

# Handoff: 2026-04-09 Session

## 13 commits this session. Plugin: 12 modules, 11 panels, 3 tools.

## What Works

### Undo
- Native Illustrator undo (no SetSilent, no custom UndoStack)
- Global undo context for ALL mutating operations (SetUndoTextUS per op type)
- Enter/Escape global via NSEvent monitor

### Trace (Ill Trace panel)
- vtracer working end-to-end: image → SVG → AI paths with coordinate mapping
- SVG transform="translate(x,y)" properly applied
- Full SVG path command support (M/L/H/V/C/S/Q/T/Z + relative)
- Fill colors from SVG hex attributes
- 3 output modes: Outline, Fill, Centerline
- Centerline: Canny edges → dilate → Zhang-Suen skeleton → vtracer
- Semantic grouping via normal map (k-means on gradient directions)
- Luminance grouping fallback (Background/Highlights/Midtones/Shadows/Outlines)
- Per-model accordion panel with 12 backends + individual params + Run buttons
- Progress bar replaces Run button during trace
- Normal Reference backend: DSINE normals → 9 renderings + auto-vectorize
- Height-to-normal: pure C++ Sobel (no Python/DSINE needed for illustrations)
- Persistent surface identity: AIDictionary metadata per path
- Embedded rasters (no linked files)
- Project-level data persistence (ProjectStore alongside .ai file)

### MCP Integration
- 6 HTTP routes replacing CEP: /api/inspect, create_path, create_shape, layers, select, modify
- Condvar sync mechanism for thread-safe SDK access
- LLM batch endpoint (/api/batch) + interaction journal (/api/journal)
- Telemetry: opt-in anonymous upload with SHA-256 machine ID

### Blend
- Color interpolation A→B for intermediates
- Pick A/B auto-activates tool + custom SVG cursors

### Perspective
- Normal-to-VP pipeline: dual detection (Hough + normals)
- VisionEngine: ClusterNormalDirections, EstimateVPsFromNormals

### Code Quality
- Deleted 7 legacy files (6400 lines dead code)
- Split 3 monoliths into 9 files (CleanupModule, HttpBridge, PerspectiveModule)
- 2 Codex adversarial reviews: 5 P0s + 10 P1s found and fixed
- No file over 2200 lines

### New Tools
- Ill Pen Tool (registered in toolbox as 3rd tool)
- Transform All with aspect ratio lock
- Surface Extraction panel

## What's Broken / In Progress

### Pen Tool (P0 — next session priority)
- **Preview path creation fails** — `NewArt(kPathArt)` called from mouse handler context, needs to be enqueued via bridge/timer
- **Panel not in Window menu** — AddAppMenu doesn't include Pen panel entry
- **No perspective snap** — pen points don't snap to VP grid lines
- **No cursor differentiation** — pen tool shows default cursor
- **Chamfer not tested** — the math is implemented but never exercised

### Trace Issues
- **Normal Reference re-trace produces 0 vectors** — BW trace of normal renderings at speckle=1 still produces only background path. Need different approach (trace in color mode, or use the C++ edge detection output directly)
- **Raster positioning** — matrix copies from original raster work BUT only on clean documents. Old embedded rasters pollute FindImagePath bounds.
- **One-shot issue** — sometimes second trace run fails (fTraceInProgress might stick)

### Undo
- Undo is grayed out after trace operations (SetUndoTextUS in timer context may not create proper undo context — may need to use the SDK's undo API differently)

## User Feature Requests (captured, not implemented)

1. **Perspective/normal snap for pen tool** — snap drawn points to VP grid lines or surface normal directions
2. **Auto-offset from adjacent curves** — detect nearby curve, replicate at offset distance for panel lines
3. **Chamfer width + distance** — not just radius but gap between rounded edges (industrial fillet)
4. **Transform arrays** — radial/linear arrays of duplicated objects in Transform All panel
5. **IllToolPlugin.cpp modularization** — split into Tools, Menu, MCP, Core (4 files)
6. **Per-model presets** — save parameter sets per trace backend
7. **Spatial/structural grouping** — containment-based hierarchy instead of luminance bands

## Critical Files

| File | Lines | Role |
|------|-------|------|
| TraceModule.cpp | ~1800 | Trace pipeline (getting big — may need split) |
| PenModule.cpp | ~450 | Pen tool (new, needs work) |
| IllToolPlugin.cpp | ~2200 | Router (needs split) |
| VisionEngine.cpp | ~2100 | CV algorithms (Canny, skeleton, normals, VP) |
| HttpBridge.cpp | ~805 | Server core + state |
| HttpBridgeRoutes.cpp | ~1550 | HTTP routes |

## Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies, builds, signs, notarizes, staples
# Launch with logs:
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

## Module Count: 12
Selection, Cleanup, Perspective, Merge, Grouping, Blend, Shading, Decompose, Transform, Trace, Surface, Pen

## Panel Count: 11
Selection, Cleanup, Grouping, Merge, Shading, Blend, Perspective, Transform, Ill Trace, Ill Surface, Ill Pen
