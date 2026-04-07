---
date: 2026-04-07T22:47:54+0000
session_name: general
researcher: claude
git_commit: 910a897
branch: feat/pipeline-gaps-surface-extraction
repository: ill_tool
topic: "Stages 10-14 Implementation + Bug Fixes + CEP Port Audit"
tags: [c++, illustrator, plugin, perspective, blend, shading, decompose, port, audit, bugfix]
status: complete
last_updated: 2026-04-07
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Stages 10-14 Built, Critical Bugs Fixed, CEP Port Plan Created

## Task(s)

### Completed
- **Stages 10b-d: Perspective Mirror/Duplicate/Paste** — Full implementations in IllToolPerspective.cpp. Homography-based projection math, panel controls wired.
- **Stage 14: Auto-Decompose** — New IllToolDecompose.cpp (24KB). Path clustering via proximity graph + connected components, annotator overlay, group creation on accept.
- **Perspective Tool Registration** — Separate AIToolSuite tool with own ToolMouseDown/Drag/Up for handle placement.
- **Perspective Panel UX** — Single "Set Perspective" button, circle handles, per-line colors (VP1=red, VP2=green, VP3=blue), lock toggle.
- **Perspective Document Persistence** — AIDictionarySuite save/load (same pattern as blend groups).
- **All 7 panels wired** — Shading, Blend, Perspective added to IllTool submenu + toggle arrays.
- **Multi-path ClassifySelection** — Now classifies ALL selected paths (vote-based), shows "ARC (3)" or "MIXED (7)".
- **Multi-path ReclassifyAs** — Reshapes all selected paths, not just the first.
- **Perspective flyout fix** — `sameGroupAs = mainToolNum` (was `kNoTool`, creating invisible separate group).
- **Grid visible=false default** — No more cyan lines on startup.
- **HTTP bridge shutdown timeout** — 2-second join timeout prevents Illustrator quit hang.
- **Duplicate menu items removed** — CreateOnePanel no longer adds standalone Window menu items.
- **3 build errors fixed** — AIToolType mismatch, GetMatchingArtIsolationAware signature, SetArtName UnicodeString.
- **CEP → C++ Port Audit** — Comprehensive function-by-function audit: 7 correct, 10 partial, 2 wrong, 7 missing.

### Critical Finding: AverageSelection Is Completely Wrong
- C++ computes centroid and moves ALL points to it (collapses shape to a star)
- CEP collects anchors → `sortByPCA()` → `classifyShape()` → `precomputeLOD()` → `placePreview()` as new clean path
- This is the core cleanup operation — needs complete rewrite
- ReclassifyAs is also wrong in multi-path context (CEP uses sorted point cloud, not per-path segments)

### Planned (Not Started)
- **Phase 1-5 of CEP Port** — detailed in `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md`
- **AIPerspectiveGridSuite sync toggle** — SDK has `SnapToGrid()`, `ShowGrid()`, transform projection. Optional sync, not mandatory.

## Critical References

1. **CEP Port Plan**: `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md` — 5-phase plan, 29 functions audited, ~600-800 lines estimated
2. **CEP Source (THE SPEC)**: `cep/com.illtool.shapeaverager/jsx/host.jsx`, `cep/shared/geometry.jsx`, `cep/shared/shapes.jsx`, `cep/shared/pathutils.jsx`
3. **Wiki Audit Article**: `wiki/concepts/cep-to-cpp-port-audit.md`

## Recent Changes

### New files created
- `plugin/Source/IllToolDecompose.cpp` — Auto-Decompose clustering (~600 lines)
- `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md` — port plan
- `wiki/concepts/cep-to-cpp-port-audit.md` — audit article

### Modified files (significant)
- `plugin/Source/IllToolPlugin.cpp` — perspective tool registration (sameGroupAs fix), 3 new submenu items (Shading/Blend/Perspective), Blend+Perspective added to toggle arrays, ProcessOperationQueue cases for all new OpTypes, mainToolNum variable order fix
- `plugin/Source/IllToolPlugin.h` — `visible = false` for PerspectiveGrid default
- `plugin/Source/IllToolPerspective.cpp` — Mirror/Duplicate/Paste math (~400 lines), circle handles, per-line colors, GetSelectedPaths refactored to AIArtHandle** with (*matches)[i] access, document persistence
- `plugin/Source/IllToolShapes.cpp` — `FindAllSelectedPaths()` + `ClassifySinglePath()` extracted, multi-path ClassifySelection (vote-based), multi-path ReclassifyAs (per-path loop)
- `plugin/Source/HttpBridge.h` — OpTypes for mirror/duplicate/paste/decompose, bridge state for all new features
- `plugin/Source/HttpBridge.cpp` — HTTP endpoints, bridge state, 2-second shutdown timeout + `<future>` include
- `plugin/Source/panels/PerspectivePanelController.mm` — Full UX refactor (single button, lock, colors, 4-tab wiring)
- `plugin/Source/panels/CleanupPanelController.mm` — Decompose tab added
- `plugin/Source/panels/BlendPanelController.mm` — OpType wiring verified
- `plugin/Source/IllToolPanels.mm` — Removed standalone Window menu item creation from CreateOnePanel
- `plugin/Source/IllToolID.h` — `kIllToolPerspectiveTool`, `kIllToolPerspectiveCursorID`
- SDK pbxproj — IllToolDecompose.cpp added (4 entries, IDs AABB00001C/1D)

## Learnings

### Build Pipeline (CRITICAL — saved to memory)
Every build MUST: `xcodebuild` → `codesign --sign "Developer ID Application: Ryder Booth (ASH39KMW4S)"` → `zip` → `xcrun notarytool submit --keychain-profile "notarytool" --wait` → `xcrun stapler staple`. Install to `~/Developer/ai-plugins/` (not /Applications — needs sudo). Forgetting notarization = Illustrator SafeMode blocks the plugin silently.

### Must copy ALL source files before building
Previous builds only copied individual changed files to SDK directory. This caused fixes to be missing in deployed builds. Always: `cp plugin/Source/*.cpp plugin/Source/*.h` + `cp plugin/Source/panels/*.mm plugin/Source/panels/*.h` to SDK Source directory.

### Agents don't report back reliably
Explore-type subagents frequently go idle without reporting findings. When audit results are needed urgently, read the files directly rather than waiting. SendMessage requests for reports often get ignored.

### CEP source is the authoritative spec
The original Stage 1-9 agents never read CEP source. Future implementation agents MUST be given the specific CEP function to port, with the file path and line numbers.

### AIPerspectiveGridSuite exists but has no VP setters
Can show/hide, lock, snap-to-grid, project art through grid — but can't programmatically set VP positions. Sync is consumption-only: read AI's grid geometry, use for transforms. Our grid handles setup UX.

### Tool registration: sameGroupAs AND sameToolsetAs
Per AITool.h:810-816, adding a tool to an existing flyout group requires BOTH `sameGroupAs = mainToolNum` AND `sameToolsetAs = mainToolNum`. Using `kNoTool` for either creates a new group/toolset.

## Post-Mortem

### What Worked
- **TeamCreate with 4 agents** for parallel Stage 10-14 implementation — hub/math/panel/decompose with non-overlapping file ownership. All completed within ~10 minutes.
- **Direct file reading** for audit — when subagents failed to report, reading CEP/C++ directly was faster and more reliable.
- **Incremental build-fix cycle** — each build error was isolated and fixed in one edit. 3 errors across 12K lines of new code is clean.

### What Failed
- **Explore subagents for auditing** — spawned 3 audit agents, none reported back after 20+ minutes. Had to do the audit manually.
- **Forgot notarization step** — built and deployed without signing. Plugin loaded but was blocked by SafeMode. Now saved to memory.
- **Forgot to copy all source files** — copied only changed .cpp but missed .h changes. Built plugin was missing fixes. Now always copy everything.
- **Agents wrote code without reading CEP** — the root cause of the entire port problem. Original Stage 1-9 agents invented AverageSelection as "centroid collapse" because they were never given the CEP source.

### Key Decisions
- Decision: **Optional sync toggle for AI perspective grid, not mandatory replacement** — Reason: AI grid has no VP setters, so we can't programmatically create a grid. Our grid is the primary; sync enables native tool snapping as opt-in.
- Decision: **Vote-based multi-path classification** — Alternatives: aggregate all points into single classification (CEP approach). Reason: vote-based is simpler and works for the common case. Will revisit when AverageSelection is rewritten to use PCA sort.
- Decision: **Write comprehensive port plan before starting port** — Reason: user testing revealed AverageSelection was fundamentally wrong. Rather than patching, document everything that's wrong and fix systematically.

## Artifacts

### Plans
- `thoughts/shared/plans/2026-04-07_cep-to-cpp-port-plan.md` — 5-phase port plan with function mapping
- `/Users/ryders/.claude/plans/jiggly-leaping-bear.md` — bug fix plan (perspective flyout, multi-path, menu items)

### Wiki
- `wiki/concepts/cep-to-cpp-port-audit.md` — permanent audit record
- `wiki/index.md` — updated with port audit entry

### Memory
- `memory/feedback_notarize_builds.md` — ALWAYS sign+notarize+staple after build

### Plugin Source (uncommitted)
- `plugin/Source/IllToolDecompose.cpp` — NEW file
- All other modifications listed in Recent Changes above

## Action Items & Next Steps

### Immediate: Commit Current Work
1. Commit all changes (new files + modifications). This session's work is uncommitted.

### Phase 1: Port Core Shape Pipeline (~200 lines new C++)
2. Port `sortByPCA()` from `cep/shared/geometry.jsx:17` → new static in IllToolShapes.cpp
3. Refactor `ClassifySinglePath()` to return points + handles (not just type name)
4. Port `computeSmoothHandles()` from `cep/shared/pathutils.jsx:161`
5. Port `placePreview()` — create AIPathArt from points + handles

### Phase 2: Rewrite AverageSelection (~300 lines)
6. Rewrite `AverageSelection()` in IllToolWorkingMode.cpp to match `sa_averageSelectedAnchors()`
7. Port `precomputeLOD()` from `cep/shared/geometry.jsx:220`
8. Wire tension/simplification sliders to LOD cache
9. Update Apply/Cancel for preview workflow

### Phase 3: Merge Improvements
10. Add merge preview via annotator overlay
11. Verify handle swap on path reversal matches `weldPoints()`

### Phase 4: Test Stages 10-14
12. Test all perspective operations in Illustrator
13. Test blend end-to-end (pick A/B → execute → re-edit)
14. Test shading (blend mode + mesh mode)
15. Test decompose (analyze → accept → verify groups)

### Phase 5: Wake Dormant Systems
16. Wire LearningEngine to record user choices
17. Wire remaining VisionEngine algorithms for decompose

## Other Notes

### Notarytool Credentials
Keychain profile "notarytool" is stored with:
- Apple ID: ryder@rydersdesign.com
- Team ID: ASH39KMW4S
- App-specific password stored in keychain (regenerated 2026-04-07)

### Plugin Install Path
`~/Developer/ai-plugins/IllTool.aip` — Illustrator prefs "Additional Plug-ins Folder" points here. No sudo needed.

### pbxproj ID Range
Last used: `AABB00001D`. Next available: `AABB00001E+`.

### Duplicate Plugin Warning
There was an old copy in `/Applications/Adobe Illustrator 2026/Plug-ins.localized/IllTool.aip` that caused a "conflicting plugins" error. User removed it with `sudo rm -rf`. Only the `~/Developer/ai-plugins/` copy should exist.

### Thread Model (unchanged from previous handoff)
- SDK/timer thread: ProcessOperationQueue at ~10Hz
- HTTP server thread: joinable with 2-second timeout (was hanging on quit)
- Main/Cocoa thread: panel NSTimer callbacks
- VisionEngine: recursive_mutex
- LearningEngine: recursive_mutex
