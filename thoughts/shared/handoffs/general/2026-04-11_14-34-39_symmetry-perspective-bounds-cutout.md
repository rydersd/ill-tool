---
date: 2026-04-11T21:34:39+0000
session_name: general
researcher: claude
git_commit: 2f7244b
branch: fix/pen-tool-and-polish
repository: ill_tool
topic: "Symmetry Correction, Perspective Enhancements, Bounds Enforcement, Cutout UX"
tags: [symmetry, perspective, bounds, cutout, localization, blender, research, strings]
status: complete
last_updated: 2026-04-11
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Symmetry + Perspective + Bounds + Cutout Fixes

## Task(s)

### Completed — Symmetry Correction Feature (NEW)
- `TraceSymmetry.cpp` — mirror + smoothstep gradient blend for fixing near-symmetrical Midjourney references
- Bridge state: axis position, side, blend %, preview/output paths
- Panel UI: Show Midline toggle, Left/Right segmented control, Blend slider, Preview/Apply/Reset buttons
- Annotator overlay: orange midline, drag handles, green/gray side indicators, preview PNG
- Per-document state persistence via AIDictionarySuite (hidden marker art)
- **ISSUE**: Symmetry Apply failed on initial test — art type detection fixed (handles both kPlacedArt and kRasterArt), but needs runtime verification. Generic Run button hidden.

### Completed — Perspective Auto-Match Enhancements
- **Adaptive Canny** (optional): `BridgeSetAdaptiveCanny(true)` enables Otsu-based thresholds. Default off.
- **5-degree angle bins**: Changed from 10-degree. Adjacent-bin merge unchanged.
- **ML normals VP estimation**: `EstimateVPsFromMLNormals()` — segments planes via ClusterNormalDirections, runs Hough per plane cluster. Gated behind Metric3D active.
- **3-point perspective** (gated): Two-pass VP estimation. Vertical VP from near-vertical lines. Requires `BridgeSet3PointPerspective(true)` + confidence > 0.6.
- **Confidence visualization**: Stores detected Hough lines, renders color-coded by VP cluster (blue/red/green). `BridgeSetShowVPLines(true)`.
- **NOTE**: None of these have panel UI toggles wired yet — accessible via bridge state only.

### Completed — Bounds Enforcement
- `EnsureImageBounds()` / `IsPointInImageBounds()` on TraceModule
- Bounds check in dispatcher before cutout and surface extract clicks
- `HandleCutoutClick` refreshes bounds via `FindImagePath()` at top
- `DragPreviewPoint` clamped to image bounds
- Flood fill constrained: spatial radius + mask-aware (subtract only through mask-white, add only through mask-black)

### Completed — Tool Save/Restore
- `BridgeSetPriorToolNumber()` / `BridgeGetPriorToolNumber()` — saves by AIToolType number
- `RestorePriorTool` OpType — restores by number via `GetToolHandleFromNumber`
- Cutout preview activates IllTool Handle (arrow cursor), Clear restores prior tool

### Completed — Localization Infrastructure
- `IllToolStrings.h` — 213 `#define kITS_*` macros using `NSLocalizedString`
- `en.lproj/Localizable.strings` — 210 English base translations
- All 12 panel .mm files updated (264 macro references)

### Completed — Licensing Fix
- `THIRD_PARTY_NOTICES.md` corrected: Metric3D CC0/BSD-2, added httplib.h + json.hpp, ONNX Runtime transitive notices

### Completed — Per-Document State
- `SaveDocState()` / `LoadDocState()` — stores symmetry + cutout state in document's hidden marker art dictionary
- `kAIDocumentChangedNotifier` clears transient state on document switch, loads incoming doc state

### Completed — Cutout Preview UX Changes
- Green filled polygon overlay (10% opacity fill, 80% outline) showing what STAYS
- Arrow cursor instead of crosshair during cutout preview
- Modifier keys read from SDK event (`message->event->modifiers`) not NSEvent
- `sAIDocument->RedrawDocument()` for forced overlay refresh

### Completed — Research & Skill Tree
- `creation/nodes/bleeding-edge-research.md` — SIGGRAPH/CVPR/arXiv research protocol
- Creation skill tree now has Phase 0: RESEARCH before UNDERSTAND
- `wiki/references/research-siggraph-vectorization-2024.md` — curated SIGGRAPH papers
- `wiki/concepts/blender-freestyle-pipeline.md` — Blender→IllTool pipeline design

### Completed — Blender Render Config
- `plugin/blender/illtool_render_setup.py` — Python script for Blender to auto-enable render passes, Freestyle SVG, camera JSON export

### IN PROGRESS — Cutout Click Interaction Bugs
**This is the main unresolved work.** Multiple intertwined issues:

1. **Option+click subtract floods wrong region** — PARTIALLY FIXED. Mask constraint added (flood only through pixels currently in mask). Needs testing.
2. **Overlay doesn't visually update after clicks** — PARTIALLY FIXED. `RedrawDocument()` added. DrawAnnotation count went from 1 to 3. Still inconsistent.
3. **Shift+click ADD vs Option+click SUBTRACT** — Adobe convention restored (Shift=ADD, Option=SUBTRACT). Needs verification.
4. **"Not cutting out the image"** — CommitCutout creates cut lines + clipping mask + RGBA PNG (logs confirm). User reports visual result not matching expectation. Needs debugging with user in the loop.

## Critical References
1. `plugin/Source/modules/TraceImage.cpp:1117-1280` — HandleCutoutClick (the buggy code path)
2. `plugin/Source/IllToolPlugin.cpp:836-874` — cutout click dispatcher with bounds check
3. Memory: `project_assess_workflow.md` — north star: "Assess Image" is first op, setup perspective, user tweaks

## Recent Changes

- `plugin/Source/modules/TraceSymmetry.cpp` — **NEW** (~200 LOC)
- `plugin/Source/modules/TraceModule.cpp:329-360` — SymmetryPreview/CommitSymmetry/CutoutGlobalClick dispatch + SaveDocState/LoadDocState + EnsureImageBounds + green polygon overlay
- `plugin/Source/modules/TraceModule.h:38-51` — SaveDocState, LoadDocState, EnsureImageBounds, IsPointInImageBounds, symmetry members
- `plugin/Source/modules/TraceImage.cpp:1117-1280` — HandleCutoutClick: bounds refresh, mask-constrained flood fill, spatial radius, RedrawDocument
- `plugin/Source/modules/TraceVector.cpp:1086-1094` — DragPreviewPoint bounds clamp
- `plugin/Source/VisionEngine.cpp:1269-1530` — adaptive Canny, 5-degree bins, vertical VP second pass
- `plugin/Source/VisionEngine.cpp:2092-2353` — EstimateVPsFromMLNormals (new function)
- `plugin/Source/VisionEngine.h:346-356` — EstimateVPsFromMLNormals declaration
- `plugin/Source/modules/PerspectiveAutoMatch.cpp:109-340` — ML normals call, 3-point VP, detected lines storage
- `plugin/Source/modules/PerspectiveModule.h:162-170` — DetectedLine struct, fAutoMatch* cached coords
- `plugin/Source/modules/PerspectiveHandles.cpp:737-810` — VP confidence line visualization
- `plugin/Source/modules/PerspectiveModule.cpp` — ClearGrid clears fDetectedLines
- `plugin/Source/HttpBridge.h:135-139` — SymmetryPreview, CommitSymmetry, RestorePriorTool OpTypes
- `plugin/Source/HttpBridge.h:846-870` — symmetry state + prior tool number declarations
- `plugin/Source/HttpBridge.cpp:452-465` — adaptiveCanny, showVPLines, 3PointPerspective atomics
- `plugin/Source/HttpBridge.cpp:1092-1127` — symmetry state implementation
- `plugin/Source/IllToolPlugin.cpp:836-874` — cutout dispatcher with bounds check + SDK modifiers
- `plugin/Source/IllToolPlugin.cpp:940-956` — tool save by number before activation
- `plugin/Source/IllToolPlugin.cpp:1023-1038` — RestorePriorTool handler
- `plugin/Source/IllToolPlugin.h:101-102` — fDocumentChangedNotifier
- `plugin/Source/panels/IllToolStrings.h` — **NEW** (213 localization macros)
- `plugin/Resources/en.lproj/Localizable.strings` — **NEW** (210 English strings)
- `plugin/Source/panels/TracePanelController.mm:446-460` — symmetry section + Run button hidden
- `plugin/Source/panels/TracePanelController.mm:1988-2110` — buildSymmetryParams + action handlers
- All 12 panel .mm files — `#import "IllToolStrings.h"` + string replacements
- `plugin/models/THIRD_PARTY_NOTICES.md` — corrected licenses
- `plugin/blender/illtool_render_setup.py` — **NEW** (Blender render config)

## Learnings

### RedrawDocument() is required for overlay updates during tool mouse handlers
`InvalidateFullView()` alone doesn't trigger a repaint when called from inside `ToolMouseDown`. `sAIDocument->RedrawDocument()` forces a full repaint including all annotator overlays. Still not 100% reliable — needs investigation.

### NSEvent modifierFlags is unreliable in SDK context
`[NSEvent modifierFlags]` returns stale or incorrect modifier state when called from within Illustrator SDK tool handlers. Use `message->event->modifiers` with `aiEventModifiers_shiftKey` / `aiEventModifiers_optionKey` instead.

### AIToolHandle is NULL for native Illustrator tools
`GetSelectedTool()` returns NULL for built-in tools (Selection, Pen, etc.). Save/restore tools by number (`GetToolNumberFromHandle` / `GetToolHandleFromNumber`) not by handle.

### Global NSEvent monitor can't convert coordinates
`addLocalMonitorForEventsMatchingMask` gives window-space coordinates that can't be reliably converted to Illustrator artwork coordinates without access to the document view's NSView. Attempted and removed — tool activation is the correct approach.

### Flood fill needs mask awareness
Color-based flood fill on the original image can eat through the subject because similar colors exist inside and outside the mask. The fix: constrain the flood to only spread through pixels that are currently on the correct side of the existing composite mask.

### Per-document state via AIDictionarySuite
Create a hidden, locked group art in the first layer with a boolean marker key. Store state as real/boolean/integer entries in the art's dictionary. Same pattern as PerspectiveModule presets. Survives document save/reopen.

## Post-Mortem

### What Worked
- **Codex adversarial review** — 3 rounds caught critical issues: licensing errors, stale bounds, tool handle vs number, flood radius formula, missing bounds checks. The plan improved significantly each round.
- **Parallel agent execution** — Phases 5/6/7 (ML normals, 3-point VP, confidence viz) ran as 3 parallel agents, all landed cleanly with no merge conflicts.
- **Per-document state pattern** — clean reuse of PerspectiveModule's AIDictionarySuite pattern for symmetry/cutout state.
- **Localization infrastructure** — mechanical but comprehensive: 213 macros across 12 files in one pass.

### What Failed
- **Global event monitor approach** — attempted NSEvent monitor for tool-independent click routing. Coordinates couldn't be converted reliably. Wasted ~3 iterations before removing.
- **Cutout overlay redraw** — multiple attempts (InvalidateFullView, dirty flag, InvalidateOverlay op, RedrawDocument). Still not 100% reliable. Root cause unclear.
- **Modifier key mapping confusion** — swapped shift/option twice before confirming Adobe convention (Shift=ADD, Option=SUBTRACT). Should have checked convention first.
- **Symmetry commit art type detection** — initial implementation only searched kPlacedArt, failed on linked raster. Fixed by using FindImagePath() which handles both.

### Key Decisions
- **Decision**: Activate IllTool Handle (arrow cursor) for cutout preview instead of global event monitor
  - Alternatives: Global NSEvent monitor, separate cutout tool
  - Reason: SDK requires active tool for mouse events. Monitor can't convert coordinates. Arrow cursor avoids UX confusion.

- **Decision**: Save/restore tool by number, not name or handle
  - Alternatives: Tool handle (NULL for native), tool name (API uses char**)
  - Reason: GetToolNumberFromHandle works for all tools including native ones.

- **Decision**: Flood fill mask constraint (only flood through correct side of existing mask)
  - Alternatives: Larger spatial radius, lower tolerance, no constraint
  - Reason: Without mask awareness, subtract floods through similar-colored subject pixels into the kept region.

## Artifacts

- `plugin/Source/modules/TraceSymmetry.cpp` — symmetry correction implementation
- `plugin/Source/panels/IllToolStrings.h` — localization string macros
- `plugin/Resources/en.lproj/Localizable.strings` — English string table
- `plugin/blender/illtool_render_setup.py` — Blender render pass config
- `plugin/models/THIRD_PARTY_NOTICES.md` — corrected licenses
- `.claude/skills/creation/nodes/bleeding-edge-research.md` — research protocol skill node
- `wiki/references/research-siggraph-vectorization-2024.md` — SIGGRAPH paper survey
- `wiki/concepts/blender-freestyle-pipeline.md` — Blender→IllTool pipeline design
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/project_assess_workflow.md` — assess-first workflow vision
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/project_blender_pipeline.md` — Blender pipeline tracking

## Action Items & Next Steps

### P0 — Must fix before merge
1. **Debug cutout overlay redraw** — the green polygon doesn't update visually after shift/option clicks despite data being correct in bridge. RedrawDocument helps but isn't reliable. Need to investigate why DrawAnnotation isn't being called consistently.
2. **Verify cutout shift/option behavior end-to-end** — Adobe convention: Shift=ADD, Option=SUBTRACT. Mask constraint should prevent cross-region flooding. Test with the ship reference image.
3. **Test symmetry Apply** — verify it produces a correctly mirrored image and replaces the placed art. Test with both linked and embedded raster.
4. **Verify CommitCutout produces visible clipping mask** — logs show it creates mask, but user reports "not cutting out." May need to inspect the clip group structure.

### P1 — Should do soon
5. **Wire perspective panel toggles** — BridgeSetAdaptiveCanny, BridgeSet3PointPerspective, BridgeSetShowVPLines have no panel UI yet. Add checkboxes to PerspectivePanelController.mm.
6. **Remove spike code** — `SpikeRelinkPlacedArt` and `/api/spike_relink` endpoint (temporary test code).
7. **Tooltip localization** — tooltips are still hardcoded @"..." strings. Convert to NSLocalizedString inline or add to IllToolStrings.h.

### P2 — Future
8. **Blender camera import** — parse camera.json → auto-set perspective grid (bypass VP detection)
9. **EXR reader** — tinyexr for Blender render pass import
10. **Deep Sketch Vectorization** — SIGGRAPH 2024 UDF net for sketch→bezier (highest-value research paper)
11. **Per-document state for perspective** — migrate perspective grid to use the IllToolDocState dictionary pattern (currently uses separate kPerspGridMarker)

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies, clean builds, signs, notarizes, staples (~3min)
pkill -9 -f "Adobe Illustrator"; sleep 3
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### Module Count: 13
Selection, Cleanup, Perspective, Merge, Grouping, Blend, Shading, Decompose, Transform, Trace, Surface, Pen, Layer

### File Sizes After This Session
- TraceModule.cpp: ~850 lines (hub + doc state)
- TraceImage.cpp: ~1500 lines (cutout click, depth, normals, symmetry)
- TraceVector.cpp: ~2050 lines (vector + curve editing + commit)
- TraceSymmetry.cpp: ~285 lines (NEW)
- TracePanelController.mm: ~2120 lines (2-tab + symmetry section)
- VisionEngine.cpp: ~2400 lines (+ ML normals VP + vertical VP)
- PerspectiveAutoMatch.cpp: ~370 lines (+ ML normals call + 3-point + line storage)
- IllToolPlugin.cpp: ~2450 lines (+ bounds checks + tool save/restore + doc notifier)
- IllToolStrings.h: ~280 lines (NEW)

### North Star (Updated)
Midjourney/sketch → **Assess** (one button: depth, normals, VPs, symmetry, surface) → fix perspective → fix impossible details → clean production vectors. Features are hypotheses — ship with defaults, observe usage, evolve presets.

### Back Pocket
- Standalone app extraction — image processing layer is portable (zero SDK deps)
- Blender → IllTool pipeline — ground truth replaces ML inference
- Localization — infrastructure done, ready for Japanese/Chinese/Korean when needed
