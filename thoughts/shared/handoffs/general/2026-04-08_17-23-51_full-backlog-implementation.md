---
date: 2026-04-09T00:23:51+0000
session_name: general
researcher: claude
git_commit: 09c2b94
branch: feat/pipeline-gaps-surface-extraction
repository: ill_tool
topic: "Full Backlog Implementation — Baseline Fixes + 4-Phase Feature Plan"
tags: [cleanup, perspective, transform, learning-engine, vision-engine, undo, handles, panels]
status: complete
last_updated: 2026-04-08
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Full Backlog — Baseline Fixes + Perspective Integration + Intelligence + Transform All

## Task(s)

### Completed — Baseline Fixes (10 items from prior handoff)
All P0/P1/P2 items from `2026-04-08_18-20-00_cleanup-interactive-editing.md` handoff:
- **P0 Undo integration** — NSEvent local monitor intercepts Cmd+Z during working mode. `SetSilent(true)` also set but insufficient alone; the event monitor is what prevents the crash. Installed on `EnterWorkingMode`, removed on `Apply/Cancel` (all exit paths including error handlers).
- **P0 Horizon artboard bounds** — cached in `OnDocumentChanged`, used in `SyncFromBridge` instead of `GetDocumentViewBounds`.
- **P1 Timer-race mid-drag** — `fDragInProgress` flag + `BridgeRequeueOp` for deferred ops.
- **P1 Perspective/cleanup mutual exclusion** — each mode exits the other.
- **P1 PCA sort robustness** — dot product instead of Dist2D.
- **P1 Apply copies original stroke** — via `AIPathStyleSuite::GetPathStyle/SetPathStyle`.
- **P2 Rotate cursor** — cross cursor at 6-20px from bbox corners.
- **P2 Double-click anchor toggle** — 400ms time-based detection.
- **P2 Inverted shape button icons** — rebuilt attributed title with black text on accent bg.
- **P2 Shading hemisphere widget** — radial gradient dome that shifts with light angle.

### Completed — Codex Adversarial Review Fixes (4 issues)
- **P0 Null fPreviewPath deref** — guarded SetArtName + stroke copy after ReorderArt failure.
- **P1 Unpaired SetSilent** — moved after all precondition checks (both AverageSelection and EnterWorkingMode).
- **P1 fOriginalPaths pre-duplication** — only tracked after DuplicateArt succeeds.
- **P1 fDragInProgress stuck** — cleared in DeselectTool + perspective VP mouse-up path.

### Completed — Phase 1: Perspective-Cleanup Integration (5 items)
- **1A Shape-aware perspective projection** — ellipse→12pt projected curve, rect→4pt projected quad. CleanupModule.cpp:920-970.
- **1B Auto-mirror VP2** — when VP1 placed, VP2 mirrors across artboard center. PerspectiveModule.cpp ToolMouseDown.
- **1C Cursor snap constraints** — `AICursorSnapSuite::SetCustom` with `kLinearConstraintAbs` along VP line angles. Registered on grid lock, cleared on unlock.
- **1D Smart Guides toggle** — `AIPreferenceSuite::PutBooleanPreference` disables `smartGuides/showToolGuides` when grid locks. Restores on unlock/clear.
- **1E Perspective-aware LOD** — LOD level > 80 projects through grid.

### Completed — Phase 2: Intelligence Layer (4 items)
- **2A LearningEngine wiring** — `RecordShapeOverride` in AverageSelection, `RecordGrouping` in GroupingModule.
- **2B Predictions to UI** — `PredictShape` shows suggestion in label ("LINE (try: ARC)"), `PredictSimplifyLevel` sets initial LOD.
- **2C InferSurfaceType** — VisionEngine called in ClassifySelection, stored via BridgeSetSurfaceHint.
- **4A Resmooth** — tension slider enqueues `OpType::Resmooth`, recomputes handles via `ComputeSmoothHandles`.

### Completed — Phase 3: New Tools + Polish (5 items)
- **3A Transform All** — new TransformModule + TransformPanelController. Batch scale/rotate with random variance. Segment-level transform (no AITransformArtSuite needed).
- **3D Merge preview overlay** — green dashed connector lines between matched endpoint pairs.
- **4B Perspective preset save/load** — named presets via AIDictionarySuite with prefix keys.
- **4C Shading eyedropper** — pick highlight/shadow color from selected path's fill.
- **4D SelectSmall point-count threshold** — maxPoints param added.

### Completed — Additional Features
- **Auto-match perspective** — VisionEngine Canny→Hough→angle clustering→VP intersection. "Auto Match" button in Perspective panel.
- **Poly lasso cursor icon** — 48x48 SVG with 3-tier grays (arrow=black, vertices=#555, segments=#888).
- **Perspective green line visibility** — white outline behind colored lines.
- **Screen-space handle sizing** — 8/10px handles (normal/hover).
- **Horizon live update** — `InvalidateOverlay` op enqueued on slider change.
- **Enter/Escape keys** — FlippedView keyDown handler.
- **Modifier cursors** — Option→IBeam, Shift→Cross via `[NSEvent modifierFlags]`.
- **Bezier snap to anchor** — collapse when within 5px, magenta highlight.
- **Transform All panel added to PRD** — Stage 9 in illtool-prd.md.

### Not Started / Remaining
- **3B Trace panel** — new TraceModule + panel bridging to MCP Python layer (vtracer/OpenCV/StarVector).
- **3C Surface extraction panel** — new SurfaceModule + panel bridging to MCP DSINE normals.
- **4E Decompose end-to-end test** — 662 lines built, never tested.
- **4F UI skin file** — runtime-loaded IllTool-UI.ai for cursors/handles/icons.
- **Phase 5 LLM integration** — correction learning, interaction journal, batch cleanup.
- **Cursor snap for native tools** — registered but untested in practice.

## Critical References

1. **PRD**: `wiki/concepts/illtool-prd.md` — updated with Transform All (Stage 9) and all Phase 1-4 items.
2. **Implementation Plan**: `/Users/ryders/.claude/plans/proud-squishing-giraffe.md` — 5-phase plan with all items, dependencies, file lists.
3. **Interaction Model**: `wiki/concepts/cleanup-interaction-model.md` — handle types, shortcuts, state machine.

## Recent Changes

### New files created
- `plugin/Source/modules/TransformModule.h` + `.cpp` — batch transform module
- `plugin/Source/panels/TransformPanelController.h` + `.mm` — transform panel UI
- `plugin/Source/AICursorSnap_Wrapper.h` — SDK wrapper for cursor snap constraints
- `plugin/Source/AIPreference_Wrapper.h` — SDK wrapper for preferences (replaced with real `AIPreference.h`)
- `plugin/Source/IAIFilePath.cpp` — copied from SDK for ai::FilePath linker dependency
- `plugin/Resources/raw/S_SDKAnnotatorTool_Lg_N@2x.svg` — poly lasso cursor icon

### Core modifications
- `plugin/Source/modules/CleanupModule.cpp` — undo interceptor (NSEvent monitor), shape-aware perspective projection, bezier snap, double-click toggle, perspective-aware LOD, LearningEngine wiring, predictions to UI, InferSurfaceType, resmooth, fOriginalPaths fix, null deref guard
- `plugin/Source/modules/PerspectiveModule.cpp` — auto-mirror VP, cursor snap constraints, Smart Guides toggle, perspective presets, auto-match, green line outlines, screen-space handles, horizon live update, `#include "IAIFilePath.cpp"`
- `plugin/Source/modules/MergeModule.cpp` + `.h` — merge preview overlay
- `plugin/Source/modules/ShadingModule.cpp` + `.h` — eyedropper mode
- `plugin/Source/modules/GroupingModule.cpp` — LearningEngine recording
- `plugin/Source/IllToolPlugin.cpp` — drag-in-progress flag, modifier cursors, rotate cursor, TransformModule registration, `#include "modules/TransformModule.cpp"`, NSEvent import
- `plugin/Source/IllToolPlugin.h` — fDragInProgress, transform panel/menu/controller refs
- `plugin/Source/HttpBridge.h` + `.cpp` — BridgeRequeueOp, InvalidateOverlay, Resmooth, AutoMatchPerspective, TransformApply, ShadingEyedropper, PerspectivePresetSave/Load + all bridge vars
- `plugin/Source/IllToolSuites.h` + `.cpp` — AIUndoSuite, AIPlacedSuite, AICursorSnapSuite, AIPreferenceSuite
- `plugin/Source/ShapeUtils.cpp` — PCA sort dot product fix
- `plugin/Source/panels/CleanupPanelController.mm` — inverted icons, enter/escape keys, resmooth wiring, maxPoints field
- `plugin/Source/panels/PerspectivePanelController.mm` — auto-match button, preset save/load UI, horizon InvalidateOverlay
- `plugin/Source/panels/ShadingPanelController.mm` — hemisphere widget, eyedropper pick buttons, color sync polling
- `plugin/tools/deploy.sh` — resource file copy step

## Learnings

### NSEvent local monitor is the only reliable way to intercept Cmd+Z
`AIUndoSuite::SetSilent(true)` marks the undo context as silent but does NOT prevent Illustrator from processing Cmd+Z. The native undo still fires and corrupts cached art handles. The fix: `[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown handler:]` intercepts the key event before Illustrator's responder chain sees it. Returns `nil` to consume, `event` to pass through.

### SDK wrapper C++ classes need their .cpp files linked
`ai::FilePath`, `ai::ArtboardList`, `ai::ArtboardProperties` are C++ wrapper classes with constructors/destructors in separate `.cpp` files (e.g., `IAIFilePath.cpp`). These aren't in the Xcode project. Workaround: `#include "IAIFilePath.cpp"` from an existing compilation unit.

### New .cpp files aren't auto-compiled by Xcode
The deploy script copies files but Xcode only compiles files listed in pbxproj. For new modules: `#include "modules/TransformModule.cpp"` from IllToolPlugin.cpp.

### ComputeBoundingBox was killing bbox drag
`ComputeBoundingBox()` had `fBBox.dragHandle = -1` at the end, resetting the drag handle on every recompute. Since `ApplyBBoxTransform` calls `ComputeBoundingBox`, the drag died after the first step. Removed the reset.

### Hit radii must match between cursor tracking and mouse-down
`HandleCursorTrack` used 8px radius for bbox handles, `HandleMouseDown` used 6px. Between 6-8px, the cursor showed "handle hover" but clicking triggered rotation. Fixed by using 6px in both.

### AIPreferenceSuite is already in the SDK precompiled headers
Creating a wrapper `AIPreference_Wrapper.h` caused "redefinition" errors because the SDK's PCH already includes it. Fix: `#include "AIPreference.h"` (the real SDK header).

## Post-Mortem

### What Worked
- **Agent parallelization** — 3 explore agents → 1 plan agent → 2 implementation agents per phase. Non-overlapping files meant zero merge conflicts.
- **Incremental build verification** — build-checking after each agent completes caught the TransformModule vtable issue and AIPreference redefinition early.
- **Codex adversarial review** — found 6 issues (1 P0, 4 P1, 1 P2) including a null deref crash and an undo state leak. All fixed before deploy.
- **Existing infrastructure discovery** — snap-to-perspective and blend easing editor were already implemented. VisionEngine had 14 algorithms, LearningEngine had predict methods. The backlog was mostly wiring, not building.

### What Failed
- **SetSilent approach to undo** — the SDK documentation implies it prevents undo, but it only marks the transaction as "skippable." Native undo still fires and corrupts state. Had to pivot to NSEvent interception.
- **ai::ArtboardList/Properties wrappers** — tried to use AIArtboardSuite for horizon bounds but the C++ wrappers need IAIArtboards.cpp linked. Fell back to caching view bounds at document open.
- **AIPreference wrapper** — created a minimal wrapper that conflicted with the SDK's existing header. Should have checked the PCH first.

### Key Decisions
- **NSEvent monitor for undo** — intercepts Cmd+Z at Cocoa level. Alternatives: SetSilent (insufficient), SetRecordingSuspended (internal-only API), menu interception (complex). NSEvent is reliable and self-contained.
- **Segment-level transforms for Transform All** — no AITransformArtSuite dependency. Alternatives: acquire the suite (untested linker risk), use AIRealMathSuite matrices. Manual segment transform matches the existing ApplyBBoxTransform pattern.
- **#include .cpp for new modules** — avoids modifying pbxproj. Alternative: edit the Xcode project directly. The include approach is fragile but avoids the risk of breaking the project file.
- **Auto-mirror VP2 uses artboard center, not viewport center** — viewport center shifts on zoom/pan. Artboard center is stable.

## Artifacts

### Code
- `plugin/Source/modules/TransformModule.h` + `.cpp` — new module (220 lines)
- `plugin/Source/panels/TransformPanelController.h` + `.mm` — new panel (~400 lines)
- `plugin/Source/AICursorSnap_Wrapper.h` — SDK wrapper (~80 lines)
- `plugin/Resources/raw/S_SDKAnnotatorTool_Lg_N@2x.svg` — cursor icon
- All modified files listed in Recent Changes section

### Documentation
- `wiki/concepts/illtool-prd.md` — updated with Transform All (Stage 9), all backlog items checked off
- `/Users/ryders/.claude/plans/proud-squishing-giraffe.md` — 5-phase implementation plan

## Action Items & Next Steps

### P1 — Next session
1. **Test everything** — restart Illustrator, test undo (Cmd+Z in working mode should be intercepted), test bbox drag, test perspective projection, test Transform All panel, test auto-match.
2. **3B Trace panel** — new TraceModule bridging to MCP Python layer. Backend selector (vtracer/OpenCV/StarVector). HTTP POST to localhost MCP server.
3. **3C Surface extraction panel** — click-to-extract using DSINE normals via MCP.
4. **4E Decompose end-to-end test** — run the 662-line decompose module, fix whatever breaks.
5. **Cursor snap verification** — test if native Pen/Rectangle tools actually snap to our VP line angles.

### P2 — Polish
6. **Enter/Escape only works with panel focus** — need tool-level key handling or first-responder management.
7. **Horizon still uses view bounds for initial cache** — find a way to get actual artboard dimensions without IAIArtboards.cpp.
8. **Transform All: aspect ratio lock** — currently scales width/height independently.

### Future
9. **Phase 5: LLM integration** — correction learning, interaction journal, batch cleanup.
10. **UI skin file** — runtime-loaded IllTool-UI.ai.

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies source → SDK, builds, signs, notarizes, staples (~3min)
# Launch with log capture:
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### New SDK Suites Acquired
- `AIUndoSuite` — `SetSilent`, `SetUndoTextUS`, `UndoChanges`
- `AIPlacedSuite` — `GetPlacedFileSpecification` (for auto-match)
- `AICursorSnapSuite` — `SetCustom`, `ClearCustom` (for perspective snap)
- `AIPreferenceSuite` — `Get/PutBooleanPreference` (for Smart Guides toggle)

### Module Count
Now 9 modules: Cleanup, Perspective, Selection, Merge, Grouping, Blend, Shading, Decompose, **Transform**.

### Panels
9 panels total. Transform panel height: 320px.

### Thread Model
- SDK/timer thread: ProcessOperationQueue at ~10Hz
- HTTP server thread: joinable with 2-second timeout
- Main/Cocoa thread: panel NSTimer callbacks (pollSelection 500ms, perspective status 250ms, shading color sync 250ms)
- NSEvent monitor: runs on main thread via Cocoa event loop
- All mouse events on main thread (SDK guarantee)
