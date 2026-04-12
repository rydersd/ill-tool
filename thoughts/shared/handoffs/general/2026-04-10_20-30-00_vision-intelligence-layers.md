---
date: 2026-04-11T03:21:15+0000
session_name: general
researcher: claude
git_commit: 2f7244b
branch: fix/pen-tool-and-polish
repository: ill_tool
topic: "Vision Intelligence, Ill Layers, Trace Polish, Pen Fixes"
tags: [vision, layers, trace, pen, onnx, depth, contours, pose, cutout, theme, tokens]
status: complete
last_updated: 2026-04-10
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Vision Intelligence + Ill Layers + Trace Polish

## Task(s)

### Completed
- **Pen tool P0 fixes** — preview path via fPreviewDirty/timer bridge, Ill Pen in Window menu, undo with proper redo text, pen draws in current/target layer, highlighting via design tokens
- **Centerline trace fix** — raised Canny (80/200), 5x5 dilation, morphological close, vtracer speckle=8/length=12/corner=90
- **Ill Layers panel** (Module #13, Panel #12) — NSOutlineView tree, drag-drop, eye/lock swipe, inline rename, Cmd+G/R/]/[, multi-select, auto-organize, learning engine, presets, GroupingModule integration
- **IllToolTheme** — appearance-aware helpers, all 12 panels retrofitted for light+dark mode
- **9 new trace param sliders** — length threshold, splice angle, curve fit iterations, layer difference, Canny low/high, dilation radius, skeleton threshold, normal strength + pre-blur/k-means stride/iter for normal ref
- **Tooltips** on all trace controls (500ms delay)
- **IllToolTokens.h** — design token system for annotator overlays, retrofitted across 5 modules
- **VisionIntelligence abstraction** — common C interface for Apple Vision + ONNX Runtime
- **Apple Contours** — VNDetectContoursRequest → vector paths directly (no vtracer)
- **Subject Cutout** — per-instance masks, Shift+click add, Option+click subtract, isolation mode, flood fill with threshold
- **Pose Detection** — 19 body joints, 73 face landmarks, hand keypoints, skeleton annotator overlay
- **Depth Decomposition** — Depth Anything V2 (ONNX+CoreML, 26MB int8) → N depth bands → contours per layer
- **Masked contour tracing** — contours only inside active cutout mask
- **Hardware gating** — deferred to poll timer (PostStartupPlugin race fix), Intel features grayed with tooltips
- **grill-me skill** — created at ~/.claude/skills/grill-me/

### Known Bugs (P0 for next session)
- **Cutout Clear doesn't reset** — preview overlay persists after Clear button
- **Cutout flood fill too broad** — clicking background floods 25% of image even with RGB distance. Needs SAM-style point prompting instead of flood fill
- **Cutout tool mode confusion** — auto-activating IllTool Handle disrupts workflow. Needs proper isolation mode with dedicated cursor

### Planned / Discussed
- **Cutout curve editing** — Cmd+drag to smooth preview path, click+drag to move points on preview line
- **Preprocess preview layer** — opaque overlay showing what the algorithm sees before trace
- **Sharpen + find edges filter** — post-blur preprocessing chain: blur → sharpen → edges → normal/skeleton
- **TraceModule.cpp split** — 3500+ lines, needs splitting into TraceCutout, TraceContours, TracePose, TraceDepth
- **LLM name lookup** — spark icon during rename in Ill Layers for "what's this called?" chat
- **ONNX Windows backend** — OnnxVisionBridge with CUDA/DirectML for SAM2, RTMO, MediaPipe

## Critical References
1. **Plan**: `.claude/plans/dapper-mixing-crab.md` — Vision Intelligence full plan with 6 phases
2. **Ultraplan**: `thoughts/Vision Intelligence — Cross-Platform ML Vision (Apple Vision.txt` — cross-platform architecture from Ultraplan
3. **Prior handoff**: `thoughts/shared/handoffs/general/2026-04-10_04-53-28_pen-tool-trace-polish.md`

## Recent Changes

- `plugin/Source/VisionIntelligence.h` + `.cpp` — common C interface, dispatcher
- `plugin/Source/AppleVisionBridge.h` + `.mm` — macOS Vision backend (contours, pose, instance masks)
- `plugin/Source/OnnxVisionBridge.h` + `.cpp` — ONNX Runtime + CoreML, Depth Anything V2
- `plugin/Source/VisionCutout.h` + `.mm` — subject mask extraction (wrapped by AppleVisionBridge)
- `plugin/Source/IllToolTokens.h` — design token system
- `plugin/Source/panels/IllToolTheme.h` + `.mm` — theme-aware panel helpers
- `plugin/Source/modules/LayerModule.h` + `.cpp` — smart layer management module
- `plugin/Source/panels/LayerPanelController.h` + `.mm` — NSOutlineView layer panel
- `plugin/Source/modules/TraceModule.cpp:2358-2500` — cutout preview/commit/recomposite
- `plugin/Source/modules/TraceModule.cpp:2754-2860` — Apple Contours via VisionIntelligence
- `plugin/Source/modules/TraceModule.cpp:2960-3120` — pose detection + skeleton overlay
- `plugin/Source/modules/TraceModule.cpp:3165-3357` — depth decomposition
- `plugin/Source/modules/TraceModule.cpp:3362-3500` — cutout click handler (flood fill add/subtract)
- `plugin/Source/IllToolPlugin.cpp:761-767` — cutout click routing with modifier keys
- `plugin/Source/IllToolPlugin.cpp:404-413` — cutout isolation (consume drags during preview)
- `plugin/Source/IllToolPlugin.cpp:829-832` — auto-tool activation via bridge request
- `plugin/Source/modules/PenModule.cpp:480-530` — draw in current/target layer
- `plugin/Source/panels/TracePanelController.mm:1259-1400` — cutout accordion with instance checkboxes + threshold

## Learnings

### Cutout flood fill is wrong approach
RGB flood fill grabs similar-colored background areas instead of missing subject parts. The user clicks holes/gaps that Vision missed, but those areas look like background. Need SAM-style point prompting ("this point IS foreground") not color-based flood fill. SAM2 via ONNX is the path forward.

### Panel init vs PostStartupPlugin race
Panels are created in StartupPlugin but VIInitialize runs in PostStartupPlugin. Hardware capability flags read at panel init are always false. Fixed with deferred gating in the poll timer (first tick after startup).

### Tool activation disrupts workflow
Auto-selecting IllTool Handle via BridgeRequestToolActivation switches the user's active tool unexpectedly. The cutout mode needs a proper isolation pattern — either a dedicated tool or an NSEvent monitor that intercepts clicks globally.

### NSOutlineView expansion state
reloadData resets all expansion. Must save expanded node IDs before reload, restore after. Track via didExpand/didCollapse notifications.

### ONNX Runtime CoreML provider
CoreML EP only handles ~690 of 1166 nodes in Depth Anything V2. Remaining nodes fall back to CPU. Performance is still good (~1s on M4) but not full Neural Engine acceleration.

### VNDetectContoursRequest normalized coords
Vision contour points are 0-1 normalized with bottom-left origin. AI artboard Y matches (both bottom-up in normalized space). Map: artX = left + nx*(right-left), artY = bottom + ny*(top-bottom).

## Post-Mortem

### What Worked
- **Parallel agent implementation** — launching backend + frontend agents on separate files simultaneously saved huge time for Ill Layers and Vision Intelligence
- **VisionIntelligence abstraction** — clean C interface makes adding ONNX backend trivial later
- **IllToolTheme centralization** — one change propagates to all 12 panels
- **Design tokens** — IllToolTokens.h eliminates hardcoded color drift across modules
- **Deferred hardware gating** — poll timer check after PostStartupPlugin solves the race cleanly
- **Bridge pattern** — atomic/mutex state transfer between ObjC panel thread and C++ timer thread continues to be reliable

### What Failed
- **Cutout flood fill** — fundamentally wrong tool for adding subject regions. Color similarity ≠ semantic "is foreground"
- **Tool activation** — auto-switching to IllTool Handle disrupts the user's workflow. Need isolation mode
- **Cutout Clear** — doesn't fully reset state (overlay persists)
- **Ultraplan** — timed out twice (90min limit), couldn't send results back to CLI session

### Key Decisions
- **Decision**: VisionIntelligence as C-callable interface (not C++ class)
  - Alternatives: C++ abstract class, ObjC protocol
  - Reason: Must work across ObjC++ and pure C++ translation units. C linkage is universal.

- **Decision**: ONNX Runtime via homebrew (not bundled)
  - Alternatives: bundle dylib in plugin, ship as separate installer
  - Reason: dev convenience. For distribution, bundle in plugin Resources/

- **Decision**: Depth Anything V2 int8 quantized (not full precision)
  - Alternatives: fp32 (99MB), fp16 (49MB), q4f16 (19MB)
  - Reason: 26MB is reasonable plugin size, int8 accuracy is sufficient for depth band separation

- **Decision**: NSOutlineView for Ill Layers (not custom tree)
  - Alternatives: custom NSView tree, flat NSTableView
  - Reason: built-in disclosure, drag-drop, keyboard nav, accessibility. Worth the styling work.

## Artifacts

- `plugin/Source/VisionIntelligence.h` — common ML vision interface
- `plugin/Source/AppleVisionBridge.mm` — macOS Vision backend
- `plugin/Source/OnnxVisionBridge.cpp` — ONNX Runtime backend
- `plugin/Source/IllToolTokens.h` — design token system
- `plugin/Source/panels/IllToolTheme.h/.mm` — theme helpers
- `plugin/Source/modules/LayerModule.h/.cpp` — layer management module
- `plugin/Source/panels/LayerPanelController.h/.mm` — layer panel
- `plugin/models/depth_anything_v2_small_int8.onnx` — depth model (26MB)
- `.claude/plans/dapper-mixing-crab.md` — Vision Intelligence plan
- `.claude/skills/grill-me/SKILL.md` — grill-me interview skill

## Action Items & Next Steps

### P0 (fix immediately — Codex review + user-reported)
1. **OOB read in ONNX** — `OnnxVisionBridge.cpp:160-176`: 1px image causes buffer overflow. Fix: reject imgW<2 || imgH<2
2. **Empty layer handling** — `LayerModule.cpp:568-579` + `PenModule.cpp:520-555`: GetFirstArtOfLayer returns null for empty layers, art placement fails silently. Fix: use layer's paint group handle directly
3. **Cmd+G loses multi-select** — `LayerPanelController.mm:819-834`: SelectNode deselects all before each selection, only last item survives for GroupSelected. Fix: batch-select without clearing
4. **Fix cutout Clear** — reset BridgeSetCutoutPreviewActive(false), clear preview paths, clear instance state, invalidate view. Currently overlay persists after Clear
5. **Fix cutout Commit button** — button doesn't enable after preview. Check enable state logic in updateStatus poll
6. **Space-to-pan cursor stuck** — pressing space during cutout preview switches to hand cursor but doesn't return to crosshair after release

### P1 (fix before merge)
7. **MRR memory leaks in LayerPanel** — `LayerPanelController.mm:277-281`: dealloc doesn't release retained ivars, tree reloads leak previous model graph. Add proper release calls
8. **ONNX output validation** — `OnnxVisionBridge.cpp:225-255`: no type/rank check before iterating output tensor. Add status checks
9. **Layer reorder ignores child index** — `LayerModule.cpp:464-552`: UI sends dstID=0 for root drops but ReorderNode has no root branch
10. **Accordion triangle consistency** — Ill Layers uses chevrons, Trace panel uses triangles. Use NSOutlineView default disclosure triangles everywhere
11. **Trace accordion reorganization** — group 16 sections into 3 categories: Accelerated (Cutout, Contours, Pose, Depth), Image Processing (Normal, Form Edge, DiffVG, Analyze), Tracing (vtracer, OpenCV, StarVector, CartoonSeg, Contour*)
12. **Fix cutout tool mode** — proper isolation mode: dedicated cursor, consume all mouse events, no lasso interference

### P2 (next iteration)
13. Cutout curve editing — Cmd+drag to smooth, click+drag to move preview path points
14. Replace flood fill with SAM point prompting
15. Split TraceModule.cpp (~3500 lines → 4 files)
16. Preprocess preview — opaque overlay
17. LLM name lookup spark icon
18. Default "Mech Design" layer preset
19. ONNX Windows backend (CUDA/DirectML)

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies, clean builds, signs, notarizes, staples (~3min)
# Kill and relaunch with logs:
pkill -9 -f "Adobe Illustrator"; sleep 3
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### Module Count: 13
Selection, Cleanup, Perspective, Merge, Grouping, Blend, Shading, Decompose, Transform, Trace, Surface, Pen, **Layer**

### Panel Count: 12
Selection, Cleanup, Grouping, Merge, Shading, Blend, Perspective, Transform, Ill Trace, Ill Surface, Ill Pen, **Ill Layers**

### Trace Accordion Sections: 16
vtracer, OpenCV, StarVector, DiffVG, CartoonSeg, Normal Ref, Form Edge, Analyze Ref, Contour Scanner, Contour Path, Contour Labeler, Contour Nesting, **Subject Cutout**, **Apple Contours**, **Pose Detection**, **Depth Layers**

### PR #9 — Codex Review
Adversarial review launched in background. Check results with:
```bash
gh pr view 9 --comments
```

### ONNX Runtime
Installed via homebrew at `/opt/homebrew/lib/libonnxruntime.dylib`. Header/lib search paths added to `AIPluginCommon.xcconfig`. For distribution, bundle the dylib in the plugin's Resources/.

### Key Architecture
- All SDK calls MUST go through timer callback (ProcessOperationQueue at 10Hz)
- VisionIntelligence.h is the ONLY interface for ML vision ops — never call AVB_* or ONNX_* directly
- IllToolTokens.h is the ONLY source for annotator colors/widths — no hardcoded AIRGBColor
- IllToolTheme is the ONLY source for panel colors/fonts — no hardcoded RGB values
- Bridge state: atomic for simple types, mutex for strings/complex data
- New modules: `#include "Module.cpp"` from IllToolPlugin.cpp (not in pbxproj)
- New panels: `#include "Panel.mm"` from IllToolPanels.mm (not in pbxproj)
