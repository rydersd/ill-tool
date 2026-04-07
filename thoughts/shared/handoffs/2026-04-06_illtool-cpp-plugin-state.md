# Handoff: IllTool C++ Plugin — Current State & Next Steps

> Created: 2026-04-06
> Session: C++ plugin development across 3 days (Apr 4-6)

## What Was Accomplished

### Plugin Foundation (WORKING)
- C++ Illustrator plugin loads, initializes, runs in AI 2026
- Built against **30.2 SDK** (30.3 SDK has suite version mismatch with AI 30.0)
- Notarized with Developer ID (Ryder Booth, ASH39KMW4S)
- PiPL as file in `Contents/Resources/pipl/plugin.pipl`
- Deploy script: `/tmp/deploy.sh` (build → sign → notarize → staple → install)

### What Actually Works
- **Polygon lasso tool** — click vertices, Enter/double-click to close, selects anchors inside polygon
- **Selection count display** — panel shows "Points: N" via notifier (not timer polling)
- **4 native SDK panels** — Selection, Cleanup, Grouping, Merge (show in Window menu)
- **HTTP bridge** on localhost:8787 — POST /draw, /clear, /status, etc.
- **Annotator overlay** — renders draw commands in screen space
- **Tool registration** — "IllTool Handle" in toolbox

### What Does NOT Work (Stubs Only)
- **Shape type buttons** — log to stderr, don't reclassify
- **Average Selection** — queued via atomic flag, but centroid math fails in some contexts
- **Simplification slider** — not connected to anything
- **Merge** — completely stubbed
- **Grouping** — completely stubbed
- **Smart Select** — mode toggle exists, no hit-test implementation
- **Apply/Cancel** — partially wired, isolation mode is escapable

### Critical Discovery: SDK Context Problem
SDK API calls (`GetMatchingArt`, `DuplicateArt`, etc.) ONLY work during SDK message dispatch (PluginMain → tool handlers, notifiers). They fail with `DOC?` error (code 1146045247) when called from:
- NSTimer callbacks
- Cocoa button actions
- HTTP bridge thread

**Fix pattern**: Use atomic flags + process in `TrackToolCursor` or idle notifier (`kAIIdleNotifier`).

## Architecture

### Plugin Location
`/Users/ryders/Developer/adobe sdk/Adobe Illustrator 2026 SDK 30.2 osx/samplecode/IllTool/`

### Source Files
```
Source/
├── IllToolPlugin.h/.cpp       — entry point, tool handlers, working mode
├── IllToolAnnotator.h/.cpp    — overlay rendering via AIAnnotatorDrawerSuite
├── IllToolSuites.h/.cpp       — suite declarations + gImportSuites
├── IllToolID.h                — constants
├── IllToolPanels.mm           — panel registration (4 panels)
├── DrawCommands.h/.cpp        — thread-safe command buffer + JSON parsing
├── HttpBridge.h/.cpp          — HTTP server on :8787
├── LearningEngine.h/.cpp      — SQLite-backed on-device ML
├── VisionEngine.h/.cpp        — 14 CV algorithms, no OpenCV
├── panels/
│   ├── SelectionPanelController.h/.mm
│   ├── CleanupPanelController.h/.mm
│   ├── GroupingPanelController.h/.mm
│   └── MergePanelController.h/.mm
└── vendor/
    ├── httplib.h              — cpp-httplib v0.18.3
    ├── json.hpp               — nlohmann/json v3.11.3
    └── stb_image.h            — image loading
```

### Python MCP Server (ill_tool repo)
```
src/adobe_mcp/apps/illustrator/drawing/
├── shape_classify.py          — classify + simplify + LOD (NEW)
├── form_gradient.py           — form-following gradients (NEW)
├── path_completion.py         — predictive path extension (NEW)
├── surface_extract.py         — click-to-extract by surface type (NEW)
├── form_edge_extract.py       — multi-backend edge extraction
└── ... (250+ tools total)
```

### Build & Deploy
```bash
# Build
xcodebuild -project '.../IllTool/IllTool.xcodeproj' -configuration release -arch arm64 build

# Deploy (sign, notarize, install)
/tmp/deploy.sh
```

### Apple Developer Account
- Developer ID Application: Ryder Booth (ASH39KMW4S)
- Notarization profile: `notarytool-profile` (stored in Keychain)
- App-specific password for notarytool stored
- **Important**: "Always Allow" keychain access for codesign or it hangs

## User Feedback (Priority Order)

1. **Select → Apply workflow**: Lasso selects, but need explicit Apply to enter isolation. Currently auto-enters.
2. **Locked isolation**: User shouldn't be able to exit isolation except via Apply/Cancel.
3. **Port CEP operations**: Shape cleanup, simplification, merge are stubs. Need real implementations using SDK API or MCP server.
4. **Application menu**: IllTool submenu with all tools (like Astute).
5. **Bounding box distort**: Option+drag for free distort, perspective lock with vanishing lines.
6. **Icon/panel templates**: Illustrator artboards for designing plugin UI.
7. **Perspective tool**: 3 vanishing lines define perspective, distortions align.

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| 30.2 SDK, not 30.3 | 30.3 suite versions don't match AI 30.0 runtime |
| Atomic flags for panel→tool | SDK calls fail outside message dispatch context |
| Selection via notifier, not timer | `GetMatchingArt` returns `DOC?` from NSTimer |
| No OpenCV in plugin | Too large, complicates notarization. Pure C++ math instead |
| Python for complex algorithms | Shape classification, LOD, boundary signatures stay in MCP server |
| SQLite for learning | System library on macOS, no vendoring needed |

## Files Changed on Master (ill_tool repo)

Recent commits:
```
697aef2 docs: wiki — local vision engine
52fd55e feat: shape classifier, form gradient, predictive path completion  
eb6caac docs: wiki — on-device learning, predictive path completion, form gradient tool
ae364d9 docs: wiki — C++ plugin working, 30.2 SDK fix, polygon lasso architecture
8725b5f fix: isolation mode — select group before isolating
4679bd7 fix: adversarial review P2
ec8dc17 fix: adversarial review P0/P1
1007abe feat: panel UX overhaul — tabs, isolation toggle, surface-aware simplify
```

## Next Session: Start Here

1. **Audit every panel button** — mark WORKS / STUB / BROKEN
2. **Find kAIIdleNotifier or AITimerSuite** — need SDK-context execution without requiring mouse movement
3. **Wire Average Selection end-to-end** — prove one operation works fully
4. **Then port remaining operations** one at a time
5. **Don't add new features until existing ones work**

## Memory Files Updated
- `feedback_plugin_ux_requirements.md` — all UX feedback
- `feedback_extraction_workflow.md` — extraction workflow requirements
- Wiki articles: on-device-learning, predictive-path-completion, form-gradient-tool, vision-engine, illustrator-cpp-plugin-sdk
