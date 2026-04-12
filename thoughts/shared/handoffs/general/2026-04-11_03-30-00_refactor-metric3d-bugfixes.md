---
date: 2026-04-11T05:09:36+0000
session_name: general
researcher: claude
git_commit: 2f7244b
branch: fix/pen-tool-and-polish
repository: ill_tool
topic: "TraceModule refactor, Metric3D integration, P0/P1 bugfixes, cutout enhancements"
tags: [refactor, metric3d, depth, normals, bugfix, clipping-mask, cutout, trace-panel, tabs, onnx]
status: complete
last_updated: 2026-04-11
last_updated_by: claude
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Trace Refactor + Metric3D + Full Bug Sweep

## Task(s)

### Completed — Clipping Mask & Cutout Pipeline
- **CommitCutout** now produces 3 outputs: cut lines on "Cut Lines" layer, clipping mask on the image (kGroupArt + kArtIsClipMask via new AIGroupSuite), and cutout RGBA PNG with transparency
- **Normal pipeline** updated to prefer cutout RGBA — loads alpha channel, sets transparent pixels to mid-gray before Sobel (no false edges), masks output normals to flat (128,128,255) for background
- **AIGroupSuite** added to IllToolSuites.h/.cpp with import table entry

### Completed — TraceModule Refactor
- **Split TraceModule.cpp** (3738 lines) into 3 files:
  - `TraceModule.cpp` — 721 lines (hub: HandleOp, FindImagePath, DrawOverlay, events)
  - `TraceImage.cpp` — 1187 lines (cutout, depth, normals, preprocessing)
  - `TraceVector.cpp` — 1830 lines (vtracer, contours, pose, SVG, commit)
- **TracePanelController.mm** restructured: 2 tabs (Image | Vectors), NSBezelStyleDisclosure triangles replacing chevrons, all sections collapsed by default

### Completed — Metric3D v2 Integration
- Downloaded `metric3d_v2_vit_small.onnx` (144MB) from HuggingFace onnx-community
- Added to OnnxVisionBridge as second ONNX session alongside Depth Anything V2
- VisionIntelligence.h: `VIEstimateMetricDepth`, `VISaveDepthMapPNG`, `VISaveNormalMapPNG`, `VIHasMetricDepth`
- Outputs: metric depth (meters), surface normals (3ch xyz), confidence
- TraceImage.cpp: FindOrComputeNormalMap Strategy 0 uses ML normals when available; ExecuteDepthDecompose supports model selection via BridgeGetDepthModel()
- Bridge flags: BridgeSetDepthModel (0=DA V2, 1=Metric3D), BridgeSetHasMetricDepth

### Completed — All P0 Bugs (6 fixes)
1. **ONNX OOB read** — imgW/imgH < 2 guard in both depth functions (`OnnxVisionBridge.cpp:182,371`)
2. **Empty layer placement** — fallback via current-layer trick when GetFirstArtOfLayer returns null (`LayerModule.cpp:568`)
3. **Cmd+G multi-select** — addToSelection param on SelectNode, first clears + rest additive (`LayerModule.h`, `LayerModule.cpp`, `LayerPanelController.mm`)
4. **Cutout Clear** — resets instance checkboxes, enqueues InvalidateOverlay (`TracePanelController.mm:1547`)
5. **Cutout Commit enable** — added "instance(s)" to done-detection match (`TracePanelController.mm:1315`)
6. **Space-to-pan cursor** — kAIEffectiveToolChangedNotifier restores mode-specific cursor (`IllToolPlugin.cpp:712-737`, `IllToolPlugin.h:98`)

### Completed — All P1 Bugs (4 fixes)
7. **MRR memory leaks** — 8 leak fixes in LayerPanelController.mm: LayerNode dealloc, controller dealloc releases 7 ivars, tree reload releases old data, autorelease on nodes/columns/alerts/pasteboard items
8. **ONNX output validation** — type/rank/null checks on DA V2 and Metric3D outputs; depth fatal, normals/confidence graceful degradation (`OnnxVisionBridge.cpp`)
9. **Layer reorder root drops** — dstID=0 handling for both layer-to-root and art-to-root (`LayerModule.cpp`)
10. **Cutout tool isolation** — removed BridgeRequestToolActivation during cutout preview, all clicks consumed when preview active (`IllToolPlugin.cpp:800-819`, `TraceImage.cpp:766`)

### Completed — P2 Features (2)
11. **Cutout curve editing** — click+drag to move preview points, Cmd+drag to smooth (blend toward neighbor average + recompute bezier handles). 205 lines in TraceVector.cpp, wired in IllToolPlugin.cpp mouse handlers
12. **Preprocess preview overlay** — toggle button in vtracer section, generates Canny/skeleton/grayscale preview matching current params, renders as 70% opacity annotator overlay via DrawPNGImageCentered. No document modification.

### Completed — Housekeeping
- `plugin/models/THIRD_PARTY_NOTICES.md` — Apache 2.0 for both depth models, MIT for ONNX Runtime and stb

## Critical References
1. **Prior handoff**: `thoughts/shared/handoffs/general/2026-04-10_20-30-00_vision-intelligence-layers.md` — full context on Vision Intelligence, Ill Layers, pen tool fixes
2. **Memory: project vision**: `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/project_illtool_vision.md` — north star updated: messy sketch/Midjourney → fix perspective → fix impossible details → clean production vectors

## Recent Changes

- `plugin/Source/IllToolSuites.h:35,67` + `.cpp:47,82` — AIGroupSuite added
- `plugin/Source/modules/TraceModule.h` — fImageArtHandle, preview editing members (HitTest/Drag/Commit), GeneratePreprocessPreview
- `plugin/Source/modules/TraceModule.cpp` — hub (721 lines), #includes TraceImage.cpp + TraceVector.cpp
- `plugin/Source/modules/TraceImage.cpp` — NEW file, image processing ops (1187+ lines)
- `plugin/Source/modules/TraceVector.cpp` — NEW file, vector/path ops (1830+ lines), cutout curve editing
- `plugin/Source/OnnxVisionBridge.h` + `.cpp` — Metric3D session, validation, OOB guards
- `plugin/Source/VisionIntelligence.h` + `.cpp` — VIEstimateMetricDepth, VISaveDepthMapPNG, VISaveNormalMapPNG
- `plugin/Source/HttpBridge.h` + `.cpp` — depth model flag, preprocess preview state, TracePreprocessPreview op
- `plugin/Source/IllToolPlugin.h` + `.cpp` — kAIEffectiveToolChangedNotifier, cutout isolation, curve editing mouse routing
- `plugin/Source/modules/LayerModule.h` + `.cpp` — addToSelection, empty layer fallback, root drop handling
- `plugin/Source/panels/LayerPanelController.mm` — MRR fixes (8), Cmd+G fix
- `plugin/Source/panels/TracePanelController.mm` — 2-tab layout, disclosure triangles, cutout clear/commit fixes, preprocess preview button
- `plugin/models/metric3d_v2_vit_small.onnx` — NEW (144MB)
- `plugin/models/THIRD_PARTY_NOTICES.md` — NEW

## Learnings

### VNGenerateDepthImageRequest doesn't exist
Apple Vision has no built-in monocular depth estimation API. The closest is running your own CoreML model through VNCoreMLRequest. Web research confirmed this — don't waste time searching for it again.

### Metric3D v2 gives normals for free
The model outputs predicted_depth + predicted_normal + normal_confidence from a single forward pass. This eliminates the Sobel height-to-normal hack for images where the model is available. Strategy 0 in FindOrComputeNormalMap uses this.

### AIAnnotatorDrawerSuite supports PNG rendering
`DrawPNGImageCentered` accepts raw PNG file bytes as uint8* buffer — no need to modify the document for visual previews. Used for preprocess preview overlay.

### Clipping mask SDK sequence
Must create group first, move art inside, create clip path on top, THEN SetGroupClipped(true), THEN SetArtUserAttr(clipPath, kArtIsClipMask, kArtIsClipMask). The clip mask flag can only be set on paths already inside a clip group.

### Agent orchestration saves massive context
The session started with manual file editing that burned ~45K tokens on TraceModule.cpp alone. Switching to agents for the remaining work kept main context clean. All P0/P1 fixes ran as parallel background agents touching separate files.

## Post-Mortem

### What Worked
- **Agent parallelization** — 4 P0 agents and 4 P1 agents ran simultaneously on separate files, each completing in 1-6 minutes
- **Research agent for model comparison** — web-research-engine produced a thorough comparison table that eliminated 2 models (Marigold, DepthPro) and identified Metric3D as the clear winner
- **3-file trace split** — total lines preserved exactly (3738), each sub-file under 1900 lines, hub under 750
- **2-tab panel redesign** — natural grouping by output type (Image vs Vectors) instead of arbitrary GPU/CPU distinction

### What Failed
- **Early manual editing** — burned ~45K tokens editing TraceModule.cpp directly in main context before switching to agents. Should have delegated from the start
- **VNGenerateDepthImageRequest assumption** — claimed this API existed without verifying. Research agent corrected this. Always verify Apple APIs before coding against them
- **Agent autonomy for UX** — user feedback: agents should ask questions via SendMessage for UX decisions, not assume. Orchestrator answers using user preference knowledge, doesn't block on user

### Key Decisions
- **Decision**: 2 tabs (Image | Vectors) instead of 3 (GPU | Image | Trace)
  - Alternatives: 3 tabs by hardware, flat list
  - Reason: User said "group by what they produce" — some GPU ops produce vectors (Apple Contours), some produce images (Cutout). Output type is what matters to the artist.

- **Decision**: Metric3D v2 ViT-Small (not DepthPro or Marigold)
  - Alternatives: DepthPro (1.9GB, no ONNX), Marigold (2GB, slow), DA V2 Metric
  - Reason: 144MB, official ONNX, metric depth + normals in one pass, ~0.3s inference

- **Decision**: Clipping mask + RGBA PNG (not either/or)
  - Alternatives: clipping mask only, cutout PNG only
  - Reason: User said both are useful. Mask is non-destructive in AI, RGBA is needed for pixel-level ops (normals)

- **Decision**: Preprocess preview via annotator overlay (not document layer)
  - Alternatives: embed as locked reference layer
  - Reason: Non-destructive, no undo stack pollution, DrawPNGImageCentered works

## Artifacts

- `plugin/Source/modules/TraceImage.cpp` — NEW: image processing operations
- `plugin/Source/modules/TraceVector.cpp` — NEW: vector/path operations + curve editing
- `plugin/Source/modules/TraceModule.cpp` — refactored hub (721 lines)
- `plugin/Source/OnnxVisionBridge.cpp` — Metric3D session + validation
- `plugin/Source/VisionIntelligence.h` — metric depth + normal map APIs
- `plugin/models/metric3d_v2_vit_small.onnx` — 144MB ONNX model
- `plugin/models/THIRD_PARTY_NOTICES.md` — model licenses
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/project_trace_presets.md` — preset strategy
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/feedback_agents_ask_questions.md` — agent communication preference

## Action Items & Next Steps

### Must do before merge
1. **Build and test** — `bash plugin/tools/deploy.sh` — nothing has been compiled yet this session. All changes are code-only.
2. **Verify clipping mask** — run cutout → commit → check that image is visually masked in Illustrator
3. **Verify Metric3D loads** — check console for `[OnnxVision] Metric3D session created` on startup
4. **Test 2-tab panel** — verify Image and Vectors tabs show correct sections
5. **Test curve editing** — cutout preview → click+drag point → Cmd+drag to smooth → commit

### P2 backlog remaining
6. **Replace flood fill with SAM point prompting** — SAM2 via ONNX, biggest remaining feature gap in cutout
7. **LLM name lookup spark icon** — "what's this called?" in Ill Layers rename
8. **Default "Mech Design" layer preset** — need usage data first (see project_trace_presets.md)
9. **ONNX Windows backend** — CUDA/DirectML for SAM2, RTMO, MediaPipe
10. **Metric3D scale calibration** — let user set reference distance ("this object is 2m tall")
11. **Trace presets from usage** — observe param combos during dev → MVP, build presets from real data

## Other Notes

### Build & Deploy
```bash
bash plugin/tools/deploy.sh   # copies, clean builds, signs, notarizes, staples (~3min)
pkill -9 -f "Adobe Illustrator"; sleep 3
/Applications/Adobe\ Illustrator\ 2026/Adobe\ Illustrator.app/Contents/MacOS/Adobe\ Illustrator 2>&1 | tee /tmp/illustrator.log &
```

### Module Count: 13
Selection, Cleanup, Perspective, Merge, Grouping, Blend, Shading, Decompose, Transform, Trace, Surface, Pen, Layer

### Panel Count: 12
Selection, Cleanup, Grouping, Merge, Shading, Blend, Perspective, Transform, Ill Trace (2 tabs), Ill Surface, Ill Pen, Ill Layers

### File sizes after refactor
- TraceModule.cpp: 721 lines (hub)
- TraceImage.cpp: ~1240 lines (image + preprocess preview)
- TraceVector.cpp: ~2035 lines (vector + curve editing)
- TracePanelController.mm: ~1924 lines (2-tab layout)
- OnnxVisionBridge.cpp: ~636 lines (DA V2 + Metric3D + validation)
- LayerModule.cpp: ~650 lines (with root drop + empty layer fixes)
- LayerPanelController.mm: ~1100 lines (with MRR fixes)

### ONNX Models
- `depth_anything_v2_small_int8.onnx` — 26MB, relative depth, fast (~0.1s)
- `metric3d_v2_vit_small.onnx` — 144MB, metric depth + normals, ~0.3s
- Both loaded as separate OrtSession, CoreML EP attempted first

### North Star
Messy sketch/Midjourney → fix perspective → fix impossible details → clean production vectors. Every feature serves this pipeline.
