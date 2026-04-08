---
date: 2026-04-08T14:30:00+0000
session_name: general
researcher: claude
git_commit: 212efab
branch: feat/pipeline-gaps-surface-extraction
repository: ill_tool
topic: "Modular Refactor + P0 Feature Fixes — Incomplete"
tags: [refactor, modules, cleanup, perspective, panels, debugging]
status: in_progress
last_updated: 2026-04-08
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Modular Refactor Done, Features Still Broken

## HONEST STATUS

The modular refactor is complete (8 modules, thin router, compiles). But **nothing actually works end-to-end for the user.** This session spent 6+ hours and the user tested ~10 builds, none of which delivered working cleanup or perspective. The user is frustrated and has lost faith in the agent-driven approach.

## Task(s)

### Completed
- **Modular architecture refactor** — IllToolPlugin.h slimmed from 800→234 lines, IllToolPlugin.cpp from 1530→~780. 8 self-contained modules created. Builds and runs.
- **PRD created** — `wiki/concepts/illtool-prd.md` captures the full product vision, user workflow, UX specs, priorities.
- **CEP port code** — SortByPCA, ClassifyPoints, FitPointsToShape, PrecomputeLOD, ComputeSmoothHandles, PlacePreview all implemented in ShapeUtils.cpp (947 lines).
- **Deploy script** — `plugin/tools/deploy.sh` handles build→sign→notarize→staple in one command.
- **UI skin file** — `~/Developer/ai-plugins/IllTool-UI.ai` with panel mockups, handle/cursor templates, icon size templates.
- **LearningEngine wired** — RecordShapeOverride, RecordSimplifyLevel, RecordNoiseDelete called from CleanupModule. PredictShape logging active.

### BROKEN — Not Working
- **Cleanup (Average Selection)** — Button is clipped off the top of the panel (Cocoa coordinate issue, panel content taller than panel window). When triggered via other means, it creates disparate points instead of one unified path. The CEP collects all anchors into one sorted array and creates ONE output path — the C++ version enters working mode which duplicates all paths.
- **Perspective grid** — VPs can be placed (auto-mirror works) but: grid lines don't draw visually, VPs can't be dragged after placement (tool deselects, arrow tool doesn't receive our mouse events), horizon slider has no visible effect.
- **Panel layouts** — Cocoa uses bottom-up Y coordinates. Content is built top-down from `y = totalHeight`. When panel window is shorter than content, top elements (critical buttons) get clipped. This affects Perspective and Cleanup panels.
- **Isolation mode** — Timer was re-entering isolation on every escape, trapping the user. Disabled now, but the preview path disappears when user clicks away because it's not in isolation and gets deselected.

### Planned (Not Started)
- Custom bounding box with circle handles (code exists in CleanupModule but untested)
- Perspective projection of cleanup output
- Snap-to-perspective toggle (bridge state exists, panel checkbox exists)
- Perspective presets save/load
- All remaining PRD P0-P2 items

## Critical References

1. **PRD (THE SPEC)**: `wiki/concepts/illtool-prd.md` — everything the tool should do
2. **CEP source (WORKING REFERENCE)**: `cep/com.illtool.shapeaverager/jsx/host.jsx` — the cleanup that actually works
3. **Refactor plan**: `.claude/plans/modular-hugging-unicorn.md`

## Recent Changes

### New files (modular refactor)
- `plugin/Source/IllToolModule.h` — base class interface for all modules
- `plugin/Source/ShapeUtils.h` + `ShapeUtils.cpp` — shared math (947 lines)
- `plugin/Source/modules/CleanupModule.h` + `.cpp` (1479 lines) — cleanup, working mode, bbox
- `plugin/Source/modules/PerspectiveModule.h` + `.cpp` (~1600 lines) — grid, VPs, projection
- `plugin/Source/modules/SelectionModule.h` + `.cpp` — lasso, smart select
- `plugin/Source/modules/MergeModule.h` + `.cpp` — endpoint merge
- `plugin/Source/modules/GroupingModule.h` + `.cpp` — copy/detach/split
- `plugin/Source/modules/BlendModule.h` + `.cpp` — blend harmonization
- `plugin/Source/modules/ShadingModule.h` + `.cpp` — surface shading
- `plugin/Source/modules/DecomposeModule.h` + `.cpp` — auto-decompose clustering
- `plugin/tools/deploy.sh` — one-command build+sign+notarize+staple

### Modified files
- `plugin/Source/IllToolPlugin.h` — slimmed to thin router (234 lines)
- `plugin/Source/IllToolPlugin.cpp` — thin router with module dispatch (~780 lines)
- `plugin/Source/HttpBridge.h` — restored all 86 function declarations (router-builder agent had stripped them)

## Learnings

### CRITICAL: Illustrator SDK Only Sends Mouse Events to YOUR Tool
The SDK only calls ToolMouseDown/Drag/Up when the plugin's own registered tool is the active tool. When the user is on Illustrator's arrow tool, the plugin receives NO mouse events. This means:
- Perspective VP dragging can't work with the arrow tool
- Either keep the perspective tool active (but it deselects when panel takes focus)
- Or use a different mechanism (NotifierSuite for art modification, or make the main IllTool Handle tool always active)

### CRITICAL: Cocoa Panel Layout
NSView origin is bottom-left. Content built from `y = totalHeight - padding` going DOWN produces elements at the TOP of the coordinate space. If the panel window is shorter than the content, the TOP gets clipped — hiding the most important buttons. The Cleanup panel has this issue (Average Selection button invisible).

**Fix options:**
1. Reduce content height to match panel height
2. Wrap in NSScrollView
3. Build layout bottom-up (important buttons at low y = bottom = always visible)
4. Use `isFlipped` override on a custom NSView subclass

### CRITICAL: HttpBridge.h Declarations
The router-builder agent stripped all 86 BridgeRequest/BridgeGet/BridgeSet function declarations from HttpBridge.h. The .cpp implementations existed but without header declarations, Objective-C panels called unresolved symbols that silently failed at runtime. **Always verify headers match implementations after any refactor.**

### Objective-C Symbol Resolution
Unlike C++, Objective-C resolves C function calls at runtime. Missing declarations don't cause linker errors — the calls silently do nothing. Use `nm binary | grep FunctionName` to verify symbols are linked.

### Build Pipeline
```bash
# One command:
bash plugin/tools/deploy.sh

# Or manual:
xcodebuild → rm -rf ~/Developer/ai-plugins/IllTool.aip → cp -R → find -name "*.cstemp" -delete → codesign --force --sign "Developer ID Application: Ryder Booth (ASH39KMW4S)" --deep --options runtime --timestamp → zip -r → xcrun notarytool submit --wait → xcrun stapler staple
```

### Log Capture
Launch Illustrator from Terminal to see plugin stderr:
```bash
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### SDK Source Location
Build project: `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/IllTool.xcodeproj`
Source must be copied to SDK before building: `cp plugin/Source/*.cpp plugin/Source/*.h SDK/Source/ && cp modules/*.cpp modules/*.h SDK/Source/modules/`

## Post-Mortem

### What Worked
- **Modular refactor architecture** — 8 self-contained modules with clear interfaces. Clean separation of concerns. Compiles.
- **Deploy script** — `plugin/tools/deploy.sh` eliminated the notarization fumbling that wasted 30+ minutes earlier.
- **Log-driven debugging** — launching from Terminal and reading `/tmp/illustrator.log` revealed the actual bugs (annotator inactive, HttpBridge.h stripped, isolation re-entry).
- **CEP port math** — SortByPCA, ClassifyPoints, LOD precomputation are faithful ports that work correctly.
- **PRD creation** — finally captured the user's full vision in one document after extensive interviewing.
- **TeamCreate for parallel module extraction** — 4 agents produced 8 modules in ~10 minutes. Architecture was right.

### What Failed
- **Agents making assumptions** — router-builder stripped HttpBridge.h declarations without checking what callers needed. Cleanup-agent's code was correct but untested in the actual dispatch flow.
- **Testing without logs** — spent hours deploying builds without log capture. Every deploy should have been tested with Terminal launch from the start.
- **Iterative patching** — fixing one thing broke another. Should have planned the full fix set, implemented, verified with logs, THEN deployed.
- **Panel layout without understanding Cocoa** — three attempts at fixing perspective panel layout, all wrong. Should have read how AIPanelSuite sizes the window before writing any layout code.
- **Polling notarization** — wasted 30 minutes polling Apple's service in a tight loop. Should have used `--wait` from the start with background execution.
- **Saying "ready for testing" without verification** — multiple builds deployed where key functions were silently broken. Should have run `nm binary | grep FunctionName` before every deploy.

### Key Decisions
- Decision: **Modular architecture with IllToolModule base class** — each feature self-contained
  - Alternatives: keep monolithic but organize better, or split into separate plugins
  - Reason: monolithic was unmaintainable, separate plugins too complex for SDK
- Decision: **Perspective placement via flag + tool activation** instead of arrow-tool mouse intercept
  - Alternatives: always keep our tool active, use NotifierSuite
  - Reason: SDK only sends mouse events to the owning tool. No way around this.
- Decision: **Disable isolation re-entry** — user wants preview path adjustable without being trapped
  - Alternatives: keep isolation but don't re-enter on escape, use kArtSelected to highlight
  - Reason: user explicitly said "doesn't need to be in isolate"

## Artifacts

### Code
- `plugin/Source/IllToolModule.h` — module base class
- `plugin/Source/ShapeUtils.h` + `.cpp` — shared math
- `plugin/Source/modules/*.h` + `*.cpp` — 8 feature modules
- `plugin/Source/IllToolPlugin.h` + `.cpp` — thin router
- `plugin/tools/deploy.sh` — build+sign+notarize+staple script
- `plugin/tools/update-pbxproj.sh` — Xcode project file updater

### Documentation
- `wiki/concepts/illtool-prd.md` — complete PRD with north star, workflow, priorities
- `wiki/concepts/cep-to-cpp-port-audit.md` — function-by-function audit
- `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md` — 5-phase port plan

### Memory
- `memory/project_illtool_vision.md` — local-first co-pilot, real-time visual feedback, multi-app
- `memory/user_workflow_profile.md` — ADHD, limited time, automate tedious work
- `memory/feedback_cleanup_workflow.md` — ONE path from all anchors, handles active, perspective projection
- `memory/feedback_verify_before_deploy.md` — check ALL functions before deploying
- `memory/feedback_agent_verification.md` — agents must verify as they go

### UI
- `~/Developer/ai-plugins/IllTool-UI.ai` — panel mockups, handle/cursor/icon templates

## Action Items & Next Steps

### BEFORE ANYTHING ELSE: Get Logs Working
1. Always launch Illustrator from Terminal: `/Applications/Adobe\ Illustrator\ 2026/...Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &`
2. Test each feature and read the log to understand what's happening
3. Do NOT deploy without verifying with `nm binary | grep FunctionName`

### P0 Fix #1: Cleanup Panel Layout
4. The "Average Selection" button is clipped off the top. Either reduce content height to match panel (448pt), or move the button lower in the layout, or use NSScrollView.
5. Test by clicking the button and verifying `[IllTool Panel] Average Selection — queuing request` appears in the log.

### P0 Fix #2: Cleanup Creates One Path
6. `CleanupModule::AverageSelection()` at `modules/CleanupModule.cpp:~350` — verify it collects anchors from ALL selected paths into ONE array, sorts by PCA, classifies, and creates ONE preview path with 2-4 points.
7. Compare output to CEP `sa_averageSelectedAnchors()` at `cep/com.illtool.shapeaverager/jsx/host.jsx:100` side-by-side.
8. The preview path must have orange stroke and stay visible.

### P0 Fix #3: Perspective Grid Drawing
9. `PerspectiveModule::DrawOverlay()` is being called but nothing renders. Add `fprintf` inside the draw function to verify it reaches the drawing code. Check if `fGrid.visible` is true when DrawOverlay runs.
10. VP coordinates are extreme (1000104, -89) — they're correct for perspective VPs but the grid line drawing may clip or fail at these scales.
11. After VPs are placed, switch to arrow tool (currently stays on perspective tool which gets deselected by panel focus).

### P0 Fix #4: VP Handle Dragging
12. Mouse events only reach the plugin when OUR tool is active. Either: keep the perspective tool active during VP adjustment, or find an alternative mechanism.

### THEN: Focus on One Feature at a Time
13. Get cleanup working end-to-end (select → average → one clean path with handles → adjust → apply/cancel)
14. Get perspective working end-to-end (set → place VPs → see grid → adjust → lock)
15. Wire perspective into cleanup (snap toggle, projection)

## Other Notes

### User Profile
- Has ADHD, limited time. Tedious organization makes them crazy.
- Professional illustrator cleaning up Midjourney art and iPad sketches for blog + game ideas.
- The tool is a personal creative accelerator, not a generic product.
- Preferences: orange + blue group colors. No dashed lines ever. Native Illustrator handles.

### Thread Model (unchanged)
- SDK/timer thread: ProcessOperationQueue at ~10Hz
- HTTP server thread: detachable (no join on quit)
- Main/Cocoa thread: panel NSTimer callbacks
- VisionEngine: recursive_mutex
- LearningEngine: recursive_mutex

### Notarytool Credentials
- Keychain profile: "notarytool"
- Apple ID: ryder@rydersdesign.com
- Team ID: ASH39KMW4S
- Identity: "Developer ID Application: Ryder Booth (ASH39KMW4S)"

### pbxproj
- Last used ID: AABB00002F
- Old monolithic .cpp files removed from build, new module .cpp files added
- Panel .mm files unchanged
