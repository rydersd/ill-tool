---
date: 2026-04-07T16:43:15+0000
session_name: general
researcher: claude
git_commit: 8bef81e
branch: feat/pipeline-gaps-surface-extraction (merged to feat/cpp-plugin-wired)
repository: ill_tool
topic: "Pipeline Gaps + Stages 10-12 + Architecture Hardening + 3 Rounds Adversarial Review"
tags: [c++, illustrator, plugin, pipeline, perspective, blend, shading, review, thread-safety, mrc]
status: complete
last_updated: 2026-04-07
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Stages 10-12, Pipeline Gaps, Architecture Hardening, Adversarial Review

## Task(s)

### Completed
- **Pipeline Gaps 1-6** — All closed. VisionEngine surface extraction (gradient histogram + divergence), tension slider wired to ReclassifyAs, SelectSmall with MeasureSegments, Add to Selection checkbox, cross-feature surface hint boost, shape undo snapshots with UndoStack.
- **H1+H2: Operation Queue** — Replaced 16 atomic flag trios with `mutex+deque<PluginOp>`. Single `while(dequeue) switch` in ProcessOperationQueue. Adding new ops = enum value + case.
- **H2: Result Queue** — `mutex+deque<PluginResult>` for operation outputs.
- **H3: Generic Undo Stack** — 20-frame multi-level undo replacing per-feature ShapeSnapshot. MergeSnapshot kept separate (handles art creation/deletion).
- **Stage 10: Perspective Grid** — Draggable-line model: PerspectiveLine structs with two handles, VPs derived from line extensions. Annotator overlay (horizon, lines, handles, extensions, VP markers, grid). Bridge state for continuous sync. PerspectivePanelController with 4-tab segmented control (Grid|Mirror|Duplicate|Paste). Show/hide toggle. Document persistence stubs.
- **Stage 11: Blend Harmonization** — Arc-length parameterization via recursive de Casteljau, point correspondence by arc-length, resampling, rotation alignment for closed paths, N-step interpolation with custom easing. Interactive EasingCurveView (224x224 cubic-bezier editor with add/remove handles). Re-editable blend groups via AIDictionarySuite persistence. Dedicated BlendPanelController.
- **Stage 12: Surface Shading** — Mode A (Blend Shading): stacked scaled contours with highlight-shadow color ramp. Mode B (Mesh Gradient): AIMeshSuite programmatic mesh with light-direction vertex colors. LightDirectionView (circular widget with draggable perimeter handle). Dedicated ShadingPanelController.
- **3 Rounds Adversarial Review** — Claude (14 issues), Codex (17 issues), 5-specialist team (40 issues). ALL ~55 issues fixed including: VisionEngine+LearningEngine mutexes, HttpBridge thread join, MRC retain cycles, ~50 leaked objects, 32 dead functions removed, matches disposal on all early returns, stale handle validation, blend pick wiring end-to-end.
- **PR #7 merged** — 13 commits squashed to `feat/cpp-plugin-wired`.

### Planned/Discussed (Not Started)
- **Stage 10b/c/d**: Mirror, Duplicate, Paste in Perspective — require perspective as a SEPARATE TOOL (user confirmed), not a mode of lasso/smart. Interactive handle dragging needs own AIToolSuite registration.
- **Stage 14: Auto-Decompose** — One-click form analysis clustering paths into named groups.
- **H4: Subsystem Registration** — Extract operations into subsystem objects (optional polish).
- **Perspective panel UX refinement** — Single "Set Perspective" button (not 3 separate VP buttons), circle handles (not squares), per-line colors, all 3 lines appear at once.

## Critical References

1. **Plan file**: `/Users/ryders/.claude/plans/robust-floating-hammock.md` — tabs, perspective tools (mirror/duplicate/paste), Stage 14 auto-decompose
2. **Master plan**: `/Users/ryders/.claude/plans/flickering-wandering-clover.md` — full Stages 1-13 + gaps + architecture hardening
3. **Plugin source**: `/Users/ryders/Developer/GitHub/ill_tool/plugin/Source/` (tracked in repo)

## Recent Changes

### New files created (this session)
- `plugin/Source/IllToolPerspective.cpp` — perspective grid logic, VP computation, annotator overlay, bridge sync
- `plugin/Source/IllToolBlend.cpp` — arc-length math, de Casteljau, easing curves, ExecuteBlend, ReblendGroup, BlendState persistence
- `plugin/Source/IllToolShading.cpp` — blend shading, mesh gradient shading, DispatchShadingOp
- `plugin/Source/panels/PerspectivePanelController.h/.mm` — 4-tab perspective panel
- `plugin/Source/panels/BlendPanelController.h/.mm` — blend panel with EasingCurveView
- `plugin/Source/panels/ShadingPanelController.h/.mm` — shading panel with LightDirectionView

### Modified files (significant changes)
- `plugin/Source/HttpBridge.h` — OpType enum now has 22 values, operation queue + result queue, ~32 dead functions removed, perspective/blend/shading bridge state
- `plugin/Source/HttpBridge.cpp` — queue implementation, bridge state atomics/mutexes, ~15 new HTTP endpoints, StopHttpBridge thread join
- `plugin/Source/IllToolPlugin.h` — UndoStack class, PerspectiveGrid struct, blend/shading declarations, 7 panel handles, std::atomic<int> fLastKnownSelectionCount
- `plugin/Source/IllToolPlugin.cpp` — ProcessOperationQueue dequeue loop (was 16 if-blocks), blend pick in ToolMouseDown, perspective/blend/shading dispatch, constructor init for all panel pointers
- `plugin/Source/IllToolShapes.cpp` — surface hint boost in ClassifySelection, tension scaling in ReclassifyAs, SelectSmall with MeasureSegments, matches disposal fixes
- `plugin/Source/VisionEngine.h/.cpp` — SurfaceType enum, InferSurfaceType (gradient histogram), ArtToPixelMapping, recursive_mutex
- `plugin/Source/LearningEngine.h/.cpp` — recursive_mutex added
- `plugin/Source/IllToolSuites.h/.cpp` — AIPathStyleSuite, AIMeshSuite, AIMeshVertexIteratorSuite, AIDictionarySuite added
- All 7 panel .mm files — MRC fixes (dealloc, [super dealloc], release leaked objects, retain cycle fixes)

## Learnings

### User UX Preferences (saved to memory)
- **Perspective**: separate tool (not lasso/smart mode), all 3 lines at once with one button + lock, circle handles, per-line colors, show/hide toggle, stored with document
- **Blend**: dedicated pick A→B mode, immediate real paths (no preview), editable easing curve with saveable presets, each blend saves state for re-editing
- **Shading**: separate panel, both blend + mesh modes, color pickers + document sampling, circular light direction widget with handle, intensity control
- **General**: always interview user about UX before implementing features, don't stop to ask "want to continue?", use agent teams for parallel work

### Architecture Patterns
- **Operation queue** is the canonical way to add new features: add OpType enum value + switch case. No new bridge functions needed.
- **Bridge state** (atomics/mutexes) for continuous values read every frame (tension, threshold, perspective lines). Operations for one-shot actions.
- **AIDictionarySuite** for document persistence (blend groups store params on art dictionary — survives save/reopen).
- **recursive_mutex** needed for VisionEngine because MultiScaleEdges calls CannyEdges internally.
- **MRC panels**: use `__block` qualifier to break retain cycles in blocks, always add `-dealloc` with `[super dealloc]`, release alloc'd objects after addSubview or strong property assignment.

### Adversarial Review Insights
- **3 rounds catch different things**: first pass finds obvious bugs, second finds architectural issues, specialist team finds domain-specific problems (thread safety, math correctness, MRC lifecycle).
- **Integration review** is the most valuable single domain — found that Blend panel was completely non-functional (3 independent wiring gaps).
- **MRC leaks** are pervasive in Cocoa panel code — every `[[X alloc] init]` needs a matching `release`.
- Common pattern: `GetMatchingArtIsolationAware` MUST dispose matches on ALL exit paths (early return, catch blocks, success path).

## Post-Mortem (Required for Artifact Index)

### What Worked
- **TeamCreate with SendMessage** for parallel implementation (H3 + Stage 10 simultaneously, blend math + panel simultaneously). Agents don't conflict when given non-overlapping file sets.
- **User interview before features** caught the perspective UX mid-implementation — saved complete rewrite by redirecting the agent.
- **Codex plugin** for external adversarial review — found issues Claude's own review missed (custom easing disconnected, blend not wired end-to-end).
- **5-specialist team** was the most thorough review approach — each domain expert found things the others missed.
- **Incremental build-after-each-change** caught pbxproj ID collisions, DrawEllipse/DrawRect missing 3rd arg, and other SDK-specific issues immediately.

### What Failed
- Tried: `std::atomic<const char*>` for fLastDetectedShape → Failed because: required `.store()/.load()` everywhere, broke existing code. Reverted to plain `const char*` (pointer writes are atomic on ARM64).
- Tried: `volatile const char*` → Failed because: `volatile` propagates to readers, causing type mismatch in panel code.
- Error: pbxproj ID collision (`AABB0000070E` used for both IllToolLasso and IllToolPerspective) → Fixed by: using unique ID range `AABB000010+`.
- Error: agent wrote `BridgeSetBlendEasingPoints` as local static in panel .mm file instead of using the real HttpBridge function → Fixed by: replacing with forwarding function.

### Key Decisions
- Decision: **Operation queue (H1) over expanding atomic flags** — Reason: 16 flags was already unmaintainable, queue scales indefinitely
- Decision: **Keep MergeSnapshot separate from UndoStack** — Reason: merge creates new art that must be deleted on undo; generic UndoStack only restores segments
- Decision: **Perspective as separate tool** (user decision) — Reason: handle dragging needs own ToolMouseDown, conflicts with lasso/smart modes
- Decision: **Blend creates real artwork immediately** (user decision) — Reason: user treats blend as production tool, not preview/exploration
- Decision: **recursive_mutex for VisionEngine** — Alternatives: regular mutex + refactor internal calls. Reason: recursive is simpler, CV operations already have internal cross-calls
- Decision: **AIDictionarySuite for blend persistence** — Alternatives: sidecar files, art name encoding. Reason: dictionary survives save/reopen, structured data, standard SDK pattern

## Artifacts

### Plugin Source (in repo, merged)
- `plugin/Source/IllToolPlugin.h` — all declarations (580 lines)
- `plugin/Source/IllToolPlugin.cpp` — lifecycle, dispatch, tool events (~800 lines)
- `plugin/Source/HttpBridge.h` — OpType enum, PluginOp, bridge state API (~450 lines after cleanup)
- `plugin/Source/HttpBridge.cpp` — queue, bridge state, HTTP endpoints (~1700 lines)
- `plugin/Source/IllToolPerspective.cpp` — perspective grid (~500 lines)
- `plugin/Source/IllToolBlend.cpp` — blend math + persistence (~850 lines)
- `plugin/Source/IllToolShading.cpp` — shading engine (~300 lines)
- `plugin/Source/VisionEngine.h/.cpp` — CV engine + surface inference (~1500 lines)
- `plugin/Source/panels/*.mm` — 7 panel controllers (~4000 lines total)

### Plans
- `/Users/ryders/.claude/plans/robust-floating-hammock.md` — tabs, perspective tools, auto-decompose, implementation order
- `/Users/ryders/.claude/plans/flickering-wandering-clover.md` — master plan Stages 1-13

### Wiki
- `wiki/concepts/plugin-pipeline-gaps-closed.md`
- `wiki/concepts/blend-tool-implementation.md`
- `wiki/concepts/perspective-grid-foundation.md`
- `wiki/concepts/plugin-adversarial-review-round3.md`

### Memory
- `memory/feedback_dont_stop.md` — don't pause for confirmation
- `memory/feedback_interview_before_features.md` — interview user before implementing
- `memory/feedback_perspective_ux.md` — perspective grid UX decisions
- `memory/feedback_blend_ux.md` — blend tool UX decisions
- `memory/feedback_shading_ux.md` — shading tool UX decisions

## Action Items & Next Steps

### Immediate
1. **Register Perspective as a separate tool** — New AIToolSuite registration in StartupPlugin, own cursor, own ToolMouseDown/Drag/Up for handle placement/dragging. This is the blocker for Stage 10b/c/d.
2. **Perspective panel UX** — Consolidate to single "Set Perspective" button (all 3 lines at once), circle handles, per-line colors.
3. **Stage 10b: Mirror in Perspective** — Project points through perspective matrix, mirror, project back. Controls in Perspective panel Mirror tab.
4. **Stage 10c: Duplicate in Perspective** — Repeat with foreshortening. Controls in Duplicate tab.
5. **Stage 10d: Paste in Perspective** — Read clipboard via AIClipboardSuite, transform through perspective matrix. Controls in Paste tab.

### Architecture
6. **Perspective document persistence** — Replace SaveToDocument/LoadFromDocument stubs with real AIDictionarySuite implementation (same pattern as blend groups).
7. **H4: Subsystem Registration** — Extract operations into subsystem objects (optional, do alongside new features).

### Features
8. **Stage 14: Auto-Decompose** — One-click form analysis using existing algorithms (endpoint scanning + signature matching + classification). Decompose tab in Cleanup panel.

### Cleanup
9. **Deploy and test** current build in Illustrator — verify all 7 panels appear, test blend end-to-end through panel UI.
10. **Mesh shading clip to silhouette** — Currently shades bounding box rectangle, not the actual path shape. Future improvement.

## Other Notes

### Build Pipeline
Plugin builds from SDK directory. Files must be copied both ways:
```
Repo → SDK: cp plugin/Source/*.cpp plugin/Source/*.h "/path/to/SDK/samplecode/IllTool/Source/"
             cp plugin/Source/panels/*.mm plugin/Source/panels/*.h "/path/to/SDK/samplecode/IllTool/Source/panels/"
SDK path: /Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/
Build: xcodebuild -project IllTool.xcodeproj -configuration Release -arch arm64 build
```
New .cpp/.mm files need 4 pbxproj edits (PBXFileReference, PBXBuildFile, PBXGroup, PBXSourcesBuildPhase). Use IDs starting from `AABB000018+` (last used: `AABB00001B`).

### Codex Plugin
Installed and authenticated. Use `/codex:rescue` for adversarial review or task delegation. High-effort mode available with `--effort high`.

### Panel Count
7 panels now registered: Selection, Cleanup, Grouping, Merge, Shading, Blend, Perspective. Each has its own AIPanelRef, AIMenuItemHandle, and ObjC controller pointer in IllToolPlugin.h.

### Thread Model
- SDK/timer thread: ProcessOperationQueue at ~10Hz, all SDK calls
- HTTP server thread: joinable (was detached, fixed), REST endpoints
- Main/Cocoa thread: panel NSTimer callbacks, button handlers
- VisionEngine: recursive_mutex protects all public methods
- LearningEngine: recursive_mutex protects all public methods
- HttpBridge: atomics for scalars, mutexes for complex state (perspective lines, merge readout, custom easing points, shading colors)
