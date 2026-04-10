---
date: 2026-04-08T18:28:00+0000
session_name: general
researcher: claude
git_commit: 2732287
branch: feat/pipeline-gaps-surface-extraction
repository: ill_tool
topic: "Interactive Cleanup + Perspective Handle Editing"
tags: [cleanup, handles, perspective, interaction, adversarial-review]
status: complete
last_updated: 2026-04-08
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Interactive Cleanup + Perspective Handle Editing

## Task(s)

### Completed
- **Cleanup panel layout fix** — FlippedView (isFlipped=YES) on both Cleanup and Perspective panels. Fixes Cocoa bottom-up Y coordinate clipping.
- **Cleanup end-to-end workflow** — Shape buttons auto-trigger AverageSelection, create ONE merged path, enter isolation with draggable handles. Apply exits cleanly.
- **Handle interaction system** — Three handle types (anchor squares, bezier circles, bbox circles) all drawn by annotator and draggable with IllTool tool. View-space hit-testing (5px consistent at any zoom). Hover pre-highlighting.
- **Keyboard shortcuts** — Option-click adds smooth point, Option-Shift adds sharp corner, Shift-click toggles sharp/smooth, drag-to-merge (5px threshold).
- **Group-aware cleanup** — Detects source group of selected paths, creates working group inside it, Apply places result back with auto-name ("GroupName — Cleaned").
- **Perspective handle editing** — VP handles draggable with main IllTool tool (no tool switch). Edit mode with arrow cursor. Grid lines visible and canvas-clipped. Horizon slider as percentage.
- **Lasso vertex editing** — Existing polygon vertices draggable with hover highlighting. Vertex hit-test before double-click prevents accidental close.
- **Adversarial review** — 3 review agents found 22 issues. All 12 P0/P1/P2 issues fixed before commit.
- **PCA direction fix** — Sort now checks direction against first original anchor, prevents curve flipping.
- **Deploy script** — Fixed missing modules/ copy, added stale file cleanup.

### Not Started / Remaining
- **Undo integration** — Cmd+Z crashes Illustrator (native undo conflicts with our UndoStack). P0.
- **Horizon artboard bounds** — Currently uses GetDocumentViewBounds which shifts on zoom. P0.
- **Timer-race mid-drag** — ProcessOperationQueue can change working mode between mouse events. P1.
- **Perspective/cleanup mutual exclusion** — Both modes can be active simultaneously. P1.
- **Rotate cursor** near bbox corners, **double-click handle toggle**, **inverted shape icons**. P2.
- **Shading hemisphere light widget**. P2.

## Critical References

1. **PRD**: `wiki/concepts/illtool-prd.md` — fully updated with all session UX feedback
2. **Interaction Model**: `wiki/concepts/cleanup-interaction-model.md` — complete handle types, shortcuts, state machine
3. **CEP source**: `cep/com.illtool.shapeaverager/jsx/host.jsx` — working reference for cleanup math (sa_averageSelectedAnchors)

## Recent Changes

### Core cleanup (plugin/Source/modules/CleanupModule.cpp — 943 lines added)
- `AverageSelection()` — group detection, source group tracking, PCA sort, classify, LOD, preview creation
- `ReclassifyAs()` — auto-triggers AverageSelection when not in working mode, updates segments in place
- `HandleMouseDown/Drag/Up` — bezier handle drag, anchor drag, bbox drag, rotation, option-click add point, shift-click toggle sharp, auto-merge
- `HandleCursorTrack()` — hover highlighting for all handle types
- `DrawPathAnchorHandles()` — square handles at anchors, circles at bezier endpoints, hover/active colors
- `ApplyWorkingMode()` — exit isolation (suppressed re-entry), validate source group, move preview, auto-name, dispose working group
- Safety: fExitingWorkingMode flag, GetArtType validation on original paths, stale drag clearing

### Mouse routing (plugin/Source/IllToolPlugin.cpp — 86 lines added)
- `ToolMouseDown` — cleanup priority when in working mode, perspective priority 2, skip persp in module loop
- Drag/Up routing — cleanup and perspective priority before module loop
- `TrackToolCursor` — hover tracking for cleanup, perspective, selection. Arrow cursor in working/edit mode.

### Perspective (plugin/Source/modules/PerspectiveModule.cpp — 181 lines added)
- `HandleCursorTrack()` — VP handle hover highlighting
- `SetEditMode()` — enter/exit edit mode (arrow cursor, handles draggable)
- Grid lines visible when valid (not just when locked)
- Canvas-clipped extension lines via GetDocumentViewBounds
- VP markers clamped to prevent annotator overflow at extreme coordinates
- View-space hit radius via PerspViewDist

### Panels (CleanupPanelController.mm, PerspectivePanelController.mm — 172 lines each)
- FlippedView / PerspFlippedView subclasses (isFlipped=YES)
- All layout math converted to top-down Y coordinates
- Shape button array + active state highlighting
- Horizon slider 0-100% with percentage display

### Lasso (SelectionModule.cpp — 92 lines added)
- Vertex hit-test + drag in HandleMouseDown/Drag/Up
- Hover highlighting via UpdateHoverVertex
- Double-click detection AFTER vertex hit-test

### Other
- `ShapeUtils.cpp` — UpdatePreviewSegments (in-place), PCA direction fix, 80% black stroke
- `HttpBridge.h` — SetPerspEditMode op type
- `HttpBridge.cpp` — gPerspHorizonY default changed 400→33
- `deploy.sh` — modules/ copy + stale file cleanup

## Learnings

### SDK mouse events only go to the active tool
The Illustrator SDK only sends ToolMouseDown/Drag/Up to the plugin's registered tool. If you switch to Illustrator's arrow tool, you lose ALL mouse events. Solution: keep IllTool tool active and draw everything via annotator.

### Cocoa panel layout: isFlipped=YES
NSView origin is bottom-left. Without isFlipped, content built top-down gets clipped from the top when the panel is shorter than content. FlippedView subclass with isFlipped=YES makes y=0 at the top.

### Isolation re-entry notifier fires during programmatic exit
The kAIIsolationModeChangedNotifier fires immediately when ExitIsolationMode() is called. If the notifier handler re-enters isolation (for "locked isolation" behavior), it creates a race: exit → notifier fires → re-enter → then dispose the group → user stuck in isolation on disposed group. Fix: fExitingWorkingMode flag suppresses re-entry during Apply/Cancel.

### View-space hit-testing is essential
Artwork-coordinate hit radius changes with zoom. At high zoom, 6pt is huge; at low zoom, it's tiny. Convert both points to view coordinates via ArtworkPointToViewPoint, then compute pixel distance.

### GetDocumentViewBounds changes on zoom/pan
Don't use view bounds for persistent positions (like horizon). Use artboard bounds instead.

## Post-Mortem

### What Worked
- **Iterative build-test-fix cycle** — ~15 deploys, user tested each one and provided immediate feedback. This drove rapid convergence on the UX.
- **Log-driven debugging** — launching Illustrator from Terminal with `tee /tmp/illustrator.log` made every issue diagnosable from logs alone.
- **Adversarial review before commit** — 3 agents found 22 issues including P0 use-after-free bugs that would have crashed in production.
- **FlippedView pattern** — clean fix for the Cocoa panel clipping problem. One-time change, works permanently.
- **In-place segment updates** — UpdatePreviewSegments avoids destroy+create flicker when toggling shapes or scrubbing LOD.

### What Failed
- **Initial assumption: switch to arrow tool** — tried switching to Selection tool (black arrow) after cleanup. Lost all mouse events because SDK only sends events to our tool. Had to revert and keep IllTool active.
- **Fixed hit radius in artwork coordinates** — bezier handles were grabbing at huge distances when zoomed in. Had to convert all hit-testing to view-space.
- **Horizon as absolute Y** — initial implementation sent absolute Y from slider. Broke when changing to percentage because bridge default was 400 (absolute) but panel default was 33 (percentage).
- **Isolation re-entry during Apply** — the notifier was re-entering isolation on the working group BETWEEN ExitIsolationMode and DisposeArt, leaving user stuck in <No Objects> state.

### Key Decisions
- Decision: **Keep IllTool tool active during editing** (not switch to arrow)
  - Alternatives: switch to Selection tool, switch to Direct Selection tool
  - Reason: SDK only sends mouse events to the owning tool. Our annotator draws all handles, our mouse handlers do all interaction.
- Decision: **Perspective projection only when grid is LOCKED**
  - Alternatives: always project when grid is visible, project when snap toggle is on
  - Reason: unlocked grid means user is still adjusting VPs. Projecting cleanup output through an incomplete grid produces garbage.
- Decision: **Shape buttons auto-trigger AverageSelection**
  - Alternatives: require separate "Average Selection" click first, or separate "merge" step
  - Reason: user has ADHD, limited time. Two-step workflow is one step too many.
- Decision: **All 12 adversarial review issues fixed before commit**
  - Alternatives: fix P0 only, document rest
  - Reason: user explicitly requested "fix all before commit"

## Artifacts

### Code
- `plugin/Source/modules/CleanupModule.cpp` + `.h` — main cleanup logic (2246 lines)
- `plugin/Source/modules/PerspectiveModule.cpp` + `.h` — perspective with edit mode
- `plugin/Source/modules/SelectionModule.cpp` + `.h` — lasso vertex editing
- `plugin/Source/IllToolPlugin.cpp` — mouse routing + cursor tracking
- `plugin/Source/ShapeUtils.cpp` + `.h` — PCA direction fix, UpdatePreviewSegments, PlacePreview
- `plugin/Source/HttpBridge.cpp` + `.h` — SetPerspEditMode op, horizon default
- `plugin/Source/panels/CleanupPanelController.mm` — FlippedView, shape button array
- `plugin/Source/panels/PerspectivePanelController.mm` — PerspFlippedView, horizon %
- `plugin/tools/deploy.sh` — modules copy + stale cleanup

### Documentation
- `wiki/concepts/illtool-prd.md` — updated with all session UX feedback
- `wiki/concepts/cleanup-interaction-model.md` — handle types, shortcuts, state machine
- `memory/feedback_cleanup_ux_session_20260408.md` — session feedback memory

## Action Items & Next Steps

### P0 — Must fix next session
1. **Undo integration** — either hook into AI SDK undo system (AIUndoSuite) or intercept Cmd+Z as a key event. Current UndoStack is separate and conflicts with native undo causing crashes.
2. **Horizon artboard bounds** — acquire AIArtboardSuite in IllToolSuites.h, use artboard bounds instead of view bounds for horizon Y calculation.

### P1 — Should fix
3. **Timer-race mid-drag** — add a "drag in progress" flag that prevents ProcessOperationQueue from dequeueing WorkingApply/Cancel while mouse is down.
4. **Perspective/cleanup mutual exclusion** — when cleanup enters working mode, exit perspective edit mode (and vice versa).
5. **PCA sort robustness** — use dot product of PCA axis with (pts.back() - pts[0]) instead of Dist2D comparison.
6. **Apply copies original stroke style** — after promoting preview, copy the stroke from the first original path.

### P2 — Polish
7. Rotate cursor near bbox corners (rotation code exists, just needs cursor change)
8. Double-click anchor to toggle handles in/out
9. Invert shape button icons when active
10. Shading hemisphere light widget (3D feel)

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # build + sign + notarize + staple (~2min)
# Launch with log capture:
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### Plugin Portability
Plugin is Developer ID signed + Apple notarized. Works on any Mac. LearningEngine auto-creates `~/Library/Application Support/illtool/` with `mkdir` on first run.

### Thread Model
- SDK/timer thread: ProcessOperationQueue at ~10Hz
- HTTP server thread: detachable
- Main/Cocoa thread: panel NSTimer callbacks (pollSelection 500ms, perspective status 250ms)
- All mouse events on main thread (SDK guarantee)

### Notarytool Credentials
- Keychain profile: "notarytool"
- Identity: "Developer ID Application: Ryder Booth (ASH39KMW4S)"
- Team ID: ASH39KMW4S

### SDK Source Location
Build project: `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/IllTool.xcodeproj`

### Cross-project Knowledge
Terminal launch pattern for plugin logging added to `~/Developer/GitHub/llm-tooling/patterns/terminal-launch-for-logging.md`
