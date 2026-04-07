---
date: 2026-04-07T02:54:50+0000
session_name: general
researcher: claude
git_commit: 6ea4bbe
branch: master
repository: ill_tool
topic: "IllTool C++ Illustrator Plugin — Foundation Build + Critical Bug Discovery"
tags: [c++, illustrator, plugin, sdk, panels, lasso, selection, notarization]
status: complete
last_updated: 2026-04-06
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: C++ Plugin — Foundation Works, Operations Stubbed, SDK Context Bug Found

## Task(s)

### Completed
- C++ plugin loads in Illustrator 2026 (notarized, Developer ID signed)
- Polygon lasso tool — click vertices, Enter to close, selects anchors inside
- 4 native SDK panels (Selection, Cleanup, Grouping, Merge) registered and visible
- HTTP bridge on localhost:8787 with draw commands, SSE events, mode switching
- Annotator overlay rendering (draw commands → screen-space shapes)
- Selection count display via `kAIArtSelectionChangedNotifier` (NOT timer polling)
- On-device learning engine (SQLite, shape prediction, noise detection)
- Local vision engine (14 CV algorithms, pure C++ math, no OpenCV)
- Python MCP tools: shape_classify, form_gradient, path_completion, surface_extract

### Work In Progress (STUBBED — NOT FUNCTIONAL)
- Shape type buttons — log to stderr only, don't reclassify
- Average Selection — queued via atomic flag, centroid math exists but untested end-to-end
- Simplification slider — not connected
- Merge — completely stubbed
- Grouping (Copy to Group, Detach, Split) — completely stubbed
- Smart Select — mode toggle exists, no hit-test
- Apply/Cancel workflow — partially wired, isolation escapable

### Planned/Discussed (Not Started)
- Locked isolation mode (user can't exit except via Apply/Cancel)
- Application menu (IllTool submenu like Astute)
- Perspective tool (3 vanishing lines)
- Bounding box distort (Option+drag)
- Icon/panel templates (Illustrator artboards → plugin resources)
- Live edge snap (cursor snaps to reference image edges)
- Predictive path completion integration with plugin

## Critical References

1. **Plan file**: `/Users/ryders/.claude/plans/quizzical-humming-dragonfly.md` — full audit plan with priorities
2. **Plugin source**: `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/`
3. **UX requirements**: `/Users/ryders/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/feedback_plugin_ux_requirements.md`

## Recent Changes

- `Source/IllToolPlugin.cpp:297-330` — SelectionChanged notifier now counts selected anchors and caches in `fLastKnownSelectionCount`
- `Source/IllToolPlugin.cpp:1176-1186` — `PluginGetSelectedAnchorCount()` returns cached count instead of calling SDK
- `Source/IllToolPlugin.cpp:292-296` — Forward declaration of `GetMatchingArtIsolationAware`
- `Source/IllToolPlugin.cpp:449-454` — Average Selection queued via `BridgeIsAverageSelectionRequested()` in TrackToolCursor
- `Source/HttpBridge.h:101-106` — Added average selection request atomic flag API
- `Source/HttpBridge.cpp:164-170` — Average selection atomic flag implementation
- `Source/panels/CleanupPanelController.mm:130-160` — pollSelection reads cached count, debug logging
- `Source/IllToolPlugin.h:147-149` — `fLastKnownSelectionCount` public member
- Lasso overlay: filled cyan boxes 6x6, dual-line paths (white bg + cyan dashed)

## Learnings

### SDK Context Problem (THE critical discovery)
SDK API calls (`GetMatchingArt`, `GetPathSegments`, `DuplicateArt`, etc.) ONLY work during SDK message dispatch — from PluginMain handlers (tool events, notifiers, menu clicks). They return error `1146045247` (`DOC?` = "no document") when called from:
- NSTimer callbacks (panel polling)
- Cocoa button action handlers (panel buttons)
- HTTP bridge thread

**Fix pattern**: Queue operations via atomic flags. Process in:
- `TrackToolCursor` (only fires when IllTool is active + mouse moves)
- `Notify` handler for `kAIArtSelectionChangedNotifier` (fires on selection changes)
- Need to investigate `kAIIdleNotifier` or `AITimerSuite` for operations when tool isn't active

### SDK Version Mismatch
- AI 30.0 installed, 30.3 SDK requests suite versions AI 30.0 doesn't provide
- Error: `kSPSuiteNotFoundError` (1394689636 = `S!Fd`)
- 30.2 SDK works — suite versions match

### Notarization
- Required for AI 2026 to call PluginMain (without it, binary loads but SafeMode blocks execution)
- `--timestamp` flag required on codesign or notarization returns "Invalid"
- `--deep` flag can cause ad-hoc signing — sign without it
- "Always Allow" keychain access for codesign or it hangs in non-interactive contexts
- `.cstemp` files from concurrent codesign attempts must be deleted before zipping

### Panel Visibility
- SDK panel `NSView.window.isVisible` returns false even when panel is shown in Illustrator UI
- Cannot use visibility check for polling optimization — just poll unconditionally
- But polling with SDK calls doesn't work anyway (see SDK Context Problem above)

## Post-Mortem (Required for Artifact Index)

### What Worked
- **Starting from SDK Annotator sample** rather than building from scratch — saved days of PiPL/bundle debugging
- **Notarization pipeline** (`/tmp/deploy.sh`) — once "Always Allow" was set, consistent workflow
- **Polygon lasso** — the tool interaction model (click vertices, Enter to close) works well
- **Atomic flag pattern** for cross-context communication — simple, reliable
- **SelectionChanged notifier** for selection count — runs in SDK context, no polling issues

### What Failed
- Tried: **CMake-built plugin** → Failed because: missing PiPL, wrong bundle structure, no SDK framework
- Tried: **Ad-hoc signing** → Failed because: AI 2026 requires notarization for PluginMain to execute
- Tried: **30.3 SDK** → Failed because: suite version mismatch with AI 30.0 (`kSPSuiteNotFoundError`)
- Tried: **NSTimer polling for selection count** → Failed because: SDK calls return `DOC?` from timer context
- Tried: **Direct C++ function calls from panel buttons** → Failed because: same SDK context problem
- Error: `DOC?` (1146045247) when calling `GetMatchingArt` outside SDK dispatch → Fixed by: caching count in notifier
- Tried: **Installing to ~/Library/Application Support/Adobe/** → Failed because: AI 2026 doesn't scan that path
- Tried: **Embedding PiPL in __DATA section** → Failed because: AI uses file-based PiPL since v25.1

### Key Decisions
- Decision: **30.2 SDK** for building
  - Alternatives: 30.3 SDK (suite mismatch), scraping headers from GitHub (incomplete)
  - Reason: Suite versions match AI 30.0 runtime
- Decision: **Pure C++ math for vision engine** instead of OpenCV
  - Alternatives: Vendor OpenCV (~100MB), use Python via HTTP
  - Reason: Notarization complexity, binary size, zero-latency requirement
- Decision: **Atomic flags + TrackToolCursor** for panel→tool communication
  - Alternatives: Direct function calls (don't work), idle notifier (not yet investigated)
  - Reason: TrackToolCursor runs in SDK context; only option that works NOW
- Decision: **Cache selection count in notifier** instead of polling
  - Alternatives: Timer-based polling (DOC? error), kAIIdleNotifier (not investigated)
  - Reason: Notifier is guaranteed to run in SDK context
- Decision: **Python MCP server for complex algorithms** (shape classification, LOD)
  - Alternatives: Port everything to C++ (huge effort, duplicates code)
  - Reason: Algorithms already exist and are tested in Python

## Artifacts

### Plugin Source
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/IllToolPlugin.h`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/IllToolPlugin.cpp`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/panels/CleanupPanelController.mm`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/HttpBridge.h`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/HttpBridge.cpp`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/LearningEngine.h`
- `/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/Source/VisionEngine.h`

### Python MCP Tools (new this session)
- `src/adobe_mcp/apps/illustrator/drawing/shape_classify.py`
- `src/adobe_mcp/apps/illustrator/drawing/form_gradient.py`
- `src/adobe_mcp/apps/illustrator/drawing/path_completion.py`
- `tests/test_path_completion.py`

### Plans & Wiki
- `/Users/ryders/.claude/plans/quizzical-humming-dragonfly.md` — current plan (audit + fix)
- `wiki/concepts/illustrator-cpp-plugin-sdk.md` — comprehensive SDK article
- `wiki/concepts/on-device-learning.md`
- `wiki/concepts/predictive-path-completion.md`
- `wiki/concepts/form-gradient-tool.md`
- `wiki/concepts/vision-engine.md`
- `wiki/concepts/future-tools.md` — backlog items

### Memory Files
- `memory/feedback_plugin_ux_requirements.md` — all UX feedback consolidated
- `memory/feedback_extraction_workflow.md` — extraction workflow requirements

### Deploy Script
- `/tmp/deploy.sh` — build, sign, notarize, staple, install (must run from user terminal for keychain access)

## Action Items & Next Steps

1. **Investigate `kAIIdleNotifier` or `AITimerSuite`** — need SDK-context execution that doesn't require mouse movement. Check `illustratorapi/illustrator/AITimer.h` if it exists. This unblocks ALL panel button operations.

2. **Audit every panel button** — mark WORKS / STUB / BROKEN. Read each `.mm` file's action handlers.

3. **Wire Average Selection end-to-end** — prove one full operation works: button click → atomic flag → SDK-context execution → result displayed. This is the template for all other operations.

4. **Port remaining operations** using the same pattern. Priority: simplify slider, then merge, then grouping.

5. **Add Application menu** — IllTool submenu with tool activation + panel show/hide.

6. **Implement locked isolation** — check `AIIsolationMode.h` for lock flags, or use notifier to detect and re-enter if user exits.

7. **Select → Apply workflow** — decouple selection from isolation entry. Add Apply button to Selection panel.

## Other Notes

### CEP Panels (removed from master)
The old CEP tool panels (shapeaverager, pathrefine, smartmerge) were removed from `~/Library/Application Support/Adobe/CEP/extensions/`. The MCP relay panel (adobe-mcp-ai) was reinstalled for the MCP server connection. The CEP panel code still exists in the `cep/` directory of the repo and has working ExtendScript implementations of all the algorithms — these are the reference for what the C++ operations should do.

### The feat/cpp-plugin Branch
An early attempt at the C++ plugin using CMake (before we had the SDK) lives on `feat/cpp-plugin`. It has the HTTP bridge, draw commands, and LLM client code but uses fake SDK compatibility headers. The SDK-based plugin in the 30.2 SDK samplecode directory supersedes it.

### Python MCP Server
Must be running (`uv run adobe-mcp`) for the HTTP-based operations to work. The plugin's HTTP bridge is on :8787, the MCP relay WebSocket is on :8765. They're independent services.
