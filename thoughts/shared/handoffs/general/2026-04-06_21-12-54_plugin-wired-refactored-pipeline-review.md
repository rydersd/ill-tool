---
date: 2026-04-07T04:12:54+0000
session_name: general
researcher: claude
git_commit: 843207a
branch: feat/cpp-plugin-wired
repository: ill_tool
topic: "IllTool C++ Plugin — 9 Stages Wired, Refactored, Pipeline Reviewed"
tags: [c++, illustrator, plugin, sdk, refactor, architecture, blend, shading, perspective]
status: complete
last_updated: 2026-04-06
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: 9 Stages Wired + Refactored + Architecture Plan for Stages 10-12

## Task(s)

### Completed
- **Stages 1-9 implemented** — All panel buttons wired through AITimerSuite dispatch:
  - Stage 1: AITimerSuite universal SDK-context dispatch (replaces TrackToolCursor-only workaround)
  - Stage 2: Fixed broken Apply/Cancel (were calling SDK from Cocoa context)
  - Stage 3: Shape classification (7 types ported from shapes.jsx, auto-detect on selection change)
  - Stage 4: Douglas-Peucker simplification with live slider
  - Stage 5: Grouping (Copy to Group, Detach, Split)
  - Stage 6: Merge (Scan endpoints, Merge with chain support, Undo via snapshot)
  - Stage 7: Application menu (Window > IllTool submenu with tool activation + panel toggles)
  - Stage 8: Locked isolation mode (re-enters if user exits during working mode)
  - Stage 9: Smart select (boundary signature matching via hit-test + arc-length comparison)
- **Adversarial review** — Found and fixed: HTTP `/cleanup/average` calling SDK directly from server thread, 90 lines dead code
- **Module refactor** — Split 3209-line IllToolPlugin.cpp into 6 focused modules + 1157-line core
- **PR created** — rydersd/ill_tool#6 with 3 commits on `feat/cpp-plugin-wired`
- **Depth audit** — Verified all implementations are real (1500+ lines of actual SDK operations, not stubs)
- **Wiki documented** — 3 new articles: AITimer dispatch pattern, architecture hardening, blend harmonization

### Work In Progress
- **Pipeline gaps identified** (6 gaps, not yet fixed — see Action Items)
- **Architecture hardening designed** (H1-H4, not yet implemented)

### Planned/Discussed (Not Started)
- Stage 10: Perspective alignment & distortion (vanishing lines, perspective grid, Option+drag free distort)
- Stage 11: Shape interpolation & blend harmonization (arc-length resampling, de Casteljau, rotation alignment)
- Stage 12: Surface shading (blend mode + mesh gradient mode via AIMeshSuite)
- Architecture hardening H1-H4 (operation queue, result queue, undo stack, subsystem registration)

## Critical References

1. **Plan file**: `/Users/ryders/.claude/plans/flickering-wandering-clover.md` — full pipeline plan with depth audit, gaps, architecture hardening, Stages 10-12
2. **Plugin source**: `/Users/ryders/Developer/GitHub/ill_tool/plugin/Source/` (tracked in repo) + `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/` (build location)
3. **Previous handoff**: `thoughts/shared/handoffs/general/2026-04-06_19-54-50_cpp-plugin-foundation.md` — pre-session state

## Recent Changes

### PR #6 Commits (feat/cpp-plugin-wired)
- `plugin/Source/IllToolSuites.h:25,47` — Added AITimerSuite include + extern declaration
- `plugin/Source/IllToolSuites.cpp:36,61` — Added AITimerSuite to gImportSuites
- `plugin/Source/IllToolPlugin.h:29,91-92,199-204` — Timer handle, ProcessOperationQueue, BoundarySignature struct, 15+ method declarations
- `plugin/Source/IllToolPlugin.cpp` — Core reduced to 1157 lines: lifecycle, dispatch, menu, tool events, ProcessOperationQueue with 15 operation handlers
- `plugin/Source/IllToolLasso.cpp` — 261 lines: polygon overlay, selection, PointInPolygon, InvalidateFullView
- `plugin/Source/IllToolWorkingMode.cpp` — 655 lines: enter/apply/cancel, isolation, average, C-wrappers
- `plugin/Source/IllToolShapes.cpp` — 447 lines: classify (6 tests), reclassify (7 fitters with bezier handles), Douglas-Peucker
- `plugin/Source/IllToolGrouping.cpp` — 197 lines: CopyToGroup, DetachFromGroup, SplitToNewGroup
- `plugin/Source/IllToolMerge.cpp` — 310 lines: ScanEndpoints, MergeEndpoints (chain merge, handle preservation), UndoMerge (snapshot)
- `plugin/Source/IllToolSmartSelect.cpp` — 273 lines: ComputeSignature (MeasureSegments), SelectMatchingPaths (4-criteria)
- `plugin/Source/HttpBridge.h/cpp` — Added ~15 atomic flags, smart threshold, merge readout, shape classification flags
- `plugin/Source/panels/*.mm` — All 4 panels wired to bridge flags instead of direct SDK calls
- `plugin/Source/IllToolID.h` — 8 new menu item constants
- `wiki/concepts/aitimer-dispatch-pattern.md` — SDK context fix documentation
- `wiki/concepts/plugin-architecture-hardening.md` — H1-H4 extensibility plan
- `wiki/concepts/blend-harmonization.md` — 5-step interpolation algorithm

## Learnings

### AITimerSuite is the Universal Fix
SDK calls fail with DOC? (1146045247) outside PluginMain dispatch. `AITimerSuite` sends `kSelectorAIGoTimer` through PluginMain at configurable intervals. Timer at `kTicksPerSecond/10` (6 ticks, ~100ms) provides reliable dispatch. This is documented in `wiki/concepts/aitimer-dispatch-pattern.md`.

### Uncoordinated Agents Create Predictable Problems
5 independent agents editing the same files (no TeamCreate) caused: Stage 9 adding stub bodies that Stages 3-6 had to work around, one critical HTTP endpoint bug (`/cleanup/average` bypassing timer dispatch). **TeamCreate with SendMessage must be used for all future parallel work** — saved as feedback memory.

### Code Depth is Real
The user suspected the agents wrote shallow implementations. Depth audit confirmed: ClassifySelection has full 6-test heuristic suite ported from shapes.jsx, ReclassifyAs generates proper bezier handles (circumcircle for arcs, kappa for ellipses), MergeEndpoints does path reversal and handle junction averaging. ~1500 lines of real SDK operations.

### Xcode Project Modification
Adding new .cpp files to the Xcode project requires 4 pbxproj edits: PBXFileReference, PBXBuildFile, PBXGroup children, PBXSourcesBuildPhase files. Unique hex IDs must not collide. Pattern used: `AABB000001` through `AABB00000C`.

### Architecture Won't Scale Past 25 Operations
The atomic-flag-per-operation pattern (15 flags currently) becomes unmaintainable at 25+. Four hardening steps are planned: operation queue (H1), result queue (H2), undo stack (H3), subsystem registration (H4). These should be implemented BEFORE Stages 10-12.

## Post-Mortem (Required for Artifact Index)

### What Worked
- **AITimerSuite discovery** — reading the SDK header confirmed the fix before writing any code
- **Parallel agent execution** — 5 agents completed 9 stages in ~15 minutes of wall time (vs sequential would take ~1 hour)
- **Adversarial review** — caught the critical HTTP endpoint bug that would have crashed in production
- **Module refactor** — clean extraction with TeamCreate + coordinated agent, no build failures
- **Depth audit** — reading actual implementations (not just trusting agent reports) confirmed code quality

### What Failed
- Tried: **Independent background agents** → Failed because: no coordination, stub collisions, duplicated effort
- Tried: **Trusting build success = working** → Learned: build proves syntax, adversarial review proves correctness
- Error: `/cleanup/average` called `PluginAverageSelection()` from HTTP thread → Fixed by: changing to `BridgeRequestAverageSelection()`
- Missing: **Wiki documentation during implementation** → User had to remind me; should be automatic

### Key Decisions
- Decision: **AITimerSuite over kAIIdleNotifier** for dispatch
  - Alternatives: TrackToolCursor (only works with IllTool active), idle notifier (untested)
  - Reason: Timer is guaranteed periodic in SDK context, configurable frequency
- Decision: **Module refactor into 6 files** (not subsystem objects yet)
  - Alternatives: Full subsystem pattern (H4), keep monolithic
  - Reason: Mechanical extraction first, subsystem pattern comes with Stages 10-12
- Decision: **TeamCreate for review and future dev**
  - Alternatives: Independent background agents
  - Reason: Coordination prevents the stub collision and missed bugs from this session
- Decision: **Blend harmonization as Stage 11** (before perspective and shading)
  - Alternatives: Perspective first, shading first
  - Reason: Blend harmonization is the core innovation and feeds into shading (Stage 12)

## Artifacts

### Plugin Source (in repo)
- `plugin/Source/IllToolPlugin.cpp` (1157 lines — core lifecycle + dispatch)
- `plugin/Source/IllToolPlugin.h` (372 lines — all declarations)
- `plugin/Source/IllToolLasso.cpp` (261 lines)
- `plugin/Source/IllToolWorkingMode.cpp` (655 lines)
- `plugin/Source/IllToolShapes.cpp` (447 lines)
- `plugin/Source/IllToolGrouping.cpp` (197 lines)
- `plugin/Source/IllToolMerge.cpp` (310 lines)
- `plugin/Source/IllToolSmartSelect.cpp` (273 lines)
- `plugin/Source/HttpBridge.h/cpp` (~1400 lines total — server + all atomic flags)
- `plugin/Source/panels/*.mm` (4 panel controllers, ~1340 lines total)
- `plugin/Source/VisionEngine.cpp/h` (1595 lines — 14 CV algorithms, DORMANT)
- `plugin/Source/LearningEngine.cpp/h` (755 lines — SQLite learning, DORMANT)

### Plans & Wiki
- `/Users/ryders/.claude/plans/flickering-wandering-clover.md` — master plan (Stages 1-13 + gaps + architecture hardening)
- `wiki/concepts/aitimer-dispatch-pattern.md`
- `wiki/concepts/plugin-architecture-hardening.md`
- `wiki/concepts/blend-harmonization.md`
- `wiki/concepts/illustrator-cpp-plugin-sdk.md` (updated previous session)

### Memory Files
- `memory/feedback_use_team_create.md` — Always use TeamCreate for parallel work
- `memory/feedback_plugin_ux_requirements.md` — All UX requirements consolidated

### SDK Reference
- `AIMesh.h` — Mesh gradient suite (v6) confirmed available for Stage 12
- `AITimer.h` — Timer suite used for dispatch
- `AIIsolationMode.h` — Isolation mode locking

## Action Items & Next Steps

### Immediate (before implementing new features)
1. **Fix Gap 1**: Wire VisionEngine surface extraction to ClassifySelection as surfaceHint
2. **Fix Gap 2**: Connect tension slider to ReclassifyAs bezier handle length
3. **Fix Gap 3**: Implement SelectSmall(threshold) using AIPathSuite::MeasureSegments
4. **Fix Gap 4**: Wire Add to Selection checkbox to ExecutePolygonSelection
5. **Fix Gap 5**: Add cross-feature integration (classify → simplify, merge → normals)
6. **Fix Gap 6**: Add undo snapshot for ReclassifyAs and SimplifySelection

### Architecture Hardening (before Stages 10-12)
7. **H1+H2**: Replace 15 atomic flags with operation queue + result queue
8. **H3**: Implement generic undo stack for all destructive operations
9. **H4**: Extract operations into subsystem objects (do alongside Stage 11)

### New Features
10. **Stage 11**: Shape interpolation & blend harmonization (the core innovation — arc-length resampling, de Casteljau, rotation alignment)
11. **Stage 12**: Surface shading (blend mode + mesh gradient mode via AIMeshSuite)
12. **Stage 10**: Perspective alignment & distortion (vanishing lines, grid, free distort)

### Deploy & Test
13. Sign, notarize, deploy current build to Illustrator for integration testing (5 test plans in the plan file)

## Other Notes

### Build Pipeline
The plugin builds from the SDK directory, not the repo. Files must be copied both ways:
- Repo → SDK: `cp plugin/Source/*.cpp plugin/Source/*.h /path/to/SDK/samplecode/IllTool/Source/`
- SDK → Repo: reverse after changes
- Xcode project is at: `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/IllTool.xcodeproj`
- Build: `xcodebuild -project IllTool.xcodeproj -configuration release -arch arm64 build`
- New .cpp files need manual addition to the pbxproj (4 sections: FileRef, BuildFile, Group, BuildPhase)

### CEP Reference Code Still Exists
The original working ExtendScript implementations are in `cep/shared/` — shapes.jsx, pathutils.jsx, geometry.jsx, math2d.jsx. These are the ground truth for algorithm correctness. The C++ ports should produce identical results.

### Python MCP Server
Must be running (`uv run adobe-mcp`) for HTTP-based operations. Plugin HTTP bridge on :8787, MCP relay WebSocket on :8765. Independent services.

### AIMeshSuite Confirmed
`AIMesh.h` has full programmatic mesh control: `InitCartesian`, vertex/segment/patch iterators, `MapColors`, `MapPoints`. Can create and populate gradient meshes entirely from code. This unblocks Stage 12 mesh gradient mode.
