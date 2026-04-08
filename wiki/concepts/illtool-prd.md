# IllTool Plugin — Product Requirements Document

> Brief: Complete PRD for the IllTool Illustrator plugin. Defines the end-to-end workflow for cleaning up AI-generated (Midjourney) art: trace → classify → simplify → perspective → shade → export.
> Tags: prd, plugin, requirements, workflow, perspective, cleanup, tracing
> Created: 2026-04-07
> Updated: 2026-04-07

## Purpose

IllTool is a native C++ Illustrator plugin for accelerating work in illustrator in perspective as cleaning up AI-generated illustration art (primarily Midjourney). The workflow takes raster art with good concepts but imprecise shapes, traces it to vectors, then provides tools to quickly reduce messy paths to clean geometric primitives, adjust handles, project into perspective, and shade for production.

### Why C++ (not CEP)

The CEP panels drew fake control handles (circles via JSX) that looked like handles but couldn't actually manipulate the refined shapes. They were purely visual — the user couldn't drag them to adjust curves. The move to C++ was specifically to get **native Illustrator handles**: after simplification, the preview path is a real `kPathArt` object. The user gets real Direct Selection tool handles — real bezier control points they can drag, just like any Illustrator path. This is the fundamental requirement that drove the C++ port. Shapes should also be deformable via the bounding box either with perspective enabled or disabled that is built into the tool, not illustrators perspective tools. 

## Target User

Solo illustrator (blog + game art, ADHD, limited time). Needs tools that eliminate tedious work and keep creative flow. Every manual step that could be automated should be. Default to the smart choice, override only when needed.

### Two Input Modes

1. **Midjourney cleanup** (primary target) — raster PNG with good concepts but imprecise shapes, AI weirdness (wrong proportions, wobbly curves, inconsistent perspective). Needs tracing → cleanup → perspective correction.
2. **iPad sketch refinement** — rough vectors drawn directly in Illustrator on iPad, brought to desktop. Already vector, just messy. Ranges from quick gesture lines to full chiaroscuro shading. Same cleanup + perspective tools apply.

Midjourney cleanup is the first target. The tools built for it naturally extend to sketch refinement.

## North Star

IllTool evolves into a **local-first creative co-pilot** across the AI/AE/PS ecosystem. Key principles:

1. **Local-first** — runs without cloud. On-device LLMs (Apple silicon models, local LLama, etc.) can plug in. No dependency on Claude API for core functionality.
2. **Real-time visual feedback** — live MJPEG stream from plugin to LLM. The model watches you work and learns. Not screenshot-on-request — continuous.
3. **Multi-app** — Illustrator today, but the architecture (HTTP bridge + MCP tools) extends to After Effects and Photoshop for rapid iteration across the pipeline.
4. **Toward spatial** — 2D tools now, but the 3D pipeline (TRELLIS.2, mesh projection, normal maps) is already built. As models improve, the tool evolves from 2D cleanup to 3D-aware illustration.
5. **Provider-agnostic LLM interface** — Claude today, local models tomorrow. The plugin's HTTP bridge doesn't care who's calling.

## Vision: The Learning Loop

IllTool is not just a set of cleanup tools — it's a **data capture system** that feeds an evolving automation pipeline. The core loop:

```
User Action → Data Capture → Learning Engine → Better Defaults → Less Manual Work
     ↓                                              ↓
Interaction Journal                          Predicted shape types
(every click, override,                      Suggested simplify levels
 grouping, adjustment)                       Noise detection thresholds
                                             Grouping affinities
```

**Why the LLM can't drive this today**: Claude can't see the artwork. It can invoke MCP tools but has no visual feedback loop. The plugin bridges this gap by:
1. Capturing structured interaction data (shape overrides, simplify levels, grouping choices)
2. Building on-device ML models (k-NN, decision trees) from that data — no cloud, no LLM
3. Progressively automating decisions as confidence grows
4. Eventually feeding captured data to LLM for higher-level automation (e.g., "clean up this whole character" as one operation)

**The LearningEngine exists** (`LearningEngine.cpp`, SQLite-backed, thread-safe) but has **zero callers**. Every cleanup operation should be recording data.

## Architecture: Three Layers

```
┌─────────────────────────────────────────────────┐
│  Layer 3: LLM (Claude via MCP)                  │
│  - High-level commands ("clean up this arm")     │
│  - ML backends (StarVector, DSINE, CartoonSeg)   │
│  - Can invoke any MCP tool (245+)                │
│  - CANNOT see artwork directly                   │
├─────────────────────────────────────────────────┤
│  Layer 2: C++ Plugin (IllTool.aip)               │
│  - Native Illustrator tool + panels              │
│  - Real-time interaction (polygon lasso, handles) │
│  - VisionEngine (14 CV algorithms, mostly dormant)│
│  - LearningEngine (SQLite, zero callers)         │
│  - HTTP bridge ↔ MCP server                      │
│  - Data capture → ~/Library/App Support/illtool/  │
├─────────────────────────────────────────────────┤
│  Layer 1: MCP Server (Python)                    │
│  - 245+ tools across 8 Adobe apps                │
│  - ML vision: vtracer, StarVector, CartoonSeg    │
│  - Surface extraction from normal maps (DSINE)    │
│  - Contour detection, labeling, nesting           │
│  - Trace workflow (OpenCV → AI paths)             │
│  - DiffVG differentiable rendering               │
└─────────────────────────────────────────────────┘
```

---

## End-to-End Workflow

```
1. TRACE       — ML-powered vector tracing of raster Midjourney art
2. ORGANIZE    — Layer naming, grouping by surface/part/region
3. SELECT      — Polygon lasso / Smart Select to pick paths
4. CLEANUP     — Average Selection: reduce to clean geometric primitive
5. ADJUST      — Live handles for manual tweaking
6. PERSPECTIVE — Project shapes into defined perspective grid
7. MERGE       — Join adjacent endpoints
8. BLEND       — Create intermediate paths for production rendering
9. SHADE       — Apply surface shading (blend or mesh gradient)
10. CAPTURE    — Every step records data for learning
```

### Data Captured At Each Step

| Step | Data Captured | Used By |
|------|--------------|---------|
| Trace | Backend choice, parameters, result quality | Backend selection defaults |
| Organize | Layer naming patterns, grouping choices | Auto-group suggestions |
| Select | Selection patterns (which paths grouped) | Smart Select signatures |
| Cleanup | Auto shape → user override, final simplify level | Shape prediction, simplify defaults |
| Adjust | Handle movements (where tool placed vs where user moved) | Correction deltas |
| Perspective | VP positions, which shapes projected | Perspective preset suggestions |
| Merge | Which endpoints merged, tolerance used | Merge threshold defaults |
| Blend | Step counts, easing curves per shape type | Blend preset suggestions |
| Shade | Colors, light direction, intensity per surface | Shading defaults |

---

## Stage 1: Vector Tracing

### What Exists
- **MCP tools** (Python, not in C++ plugin):
  - `adobe_ai_vtrace` — vtracer (Rust): raster → clean SVG, better than Image Trace for cartoon art
  - `adobe_ai_trace_workflow` — OpenCV contour detection → AI path creation (setup, auto_trace, list_shapes, export)
  - `adobe_ai_vectorize_ml` — StarVector (HuggingFace causal LM): high-quality image-to-SVG
  - `adobe_ai_segment_ml` — CartoonSegmentation: instance segmentation for character parts
  - `adobe_ai_contour_to_path` — bridge from contour manifests to AI paths
  - `adobe_ai_contour_scanner` / `adobe_ai_contour_labeler` / `adobe_ai_contour_nesting` — contour analysis tools

### What's Missing
- **No tracing panel in C++ plugin** — all tracing currently requires MCP/Claude
- Need a Trace panel that:
  - Accepts placed raster image (or lets user place one)
  - Offers tracing backend selection (vtracer for clean art, OpenCV for lineart, StarVector for complex)
  - Shows preview of trace result
  - Expands to editable paths on confirm
  - Communicates with MCP server via HTTP bridge for ML backends

### Requirements
- [ ] Trace panel in C++ plugin with backend selector
- [ ] HTTP bridge endpoints for trace operations
- [ ] Preview overlay before expanding
- [ ] Color quantization controls (for Midjourney's noisy gradients)
- [ ] Min area / speckle filter controls
- [ ] Layer naming for traced output

---

## Stage 1b: Surface Extraction (Click-to-Extract)

### What Exists (MCP Python layer)
- `adobe_ai_surface_extract` — click on reference → DSINE normal map → surface type classification → flood-fill region → extract boundary contours → place as AI paths
- Actions: `click_extract` (click point), `region_extract` (rectangular ROI), `type_extract` (all regions of a type)
- Surface types: flat, cylindrical, convex, concave, saddle, angular
- VisionEngine (C++) has `InferSurfaceType` (gradient histogram + divergence) — used by ClassifySelection

### What's Missing
- [ ] Surface extraction panel in C++ plugin (click on canvas → extract region)
- [ ] HTTP bridge endpoint to invoke DSINE normal estimation
- [ ] Surface type overlay visualization (color-coded regions on reference)
- [ ] Bridge VisionEngine surface classification to MCP normal maps

---

## Stage 1c: Organization

### Concept
After tracing, paths need to be organized by surface type, body part, or spatial region before cleanup. This is where the LearningEngine should start capturing grouping patterns.

### What Exists
- [x] CopyToGroup, DetachFromGroup, SplitToNewGroup (C++ plugin)
- [x] Layer auto-organize tool (MCP)
- [x] Part segmentation (CartoonSeg via MCP)
- [x] Auto-Decompose clustering (IllToolDecompose.cpp) — proximity graph + connected components

### What's Missing
- [ ] LearningEngine recording grouping choices
- [ ] Auto-suggest groupings based on learned patterns
- [ ] Surface-type-aware grouping (group by flat/curved/angular)
- [ ] Layer naming conventions enforced by plugin

---

## Stage 2: Selection Tools

### What Exists (WORKING)
- **Polygon Lasso** — click-to-define polygon, double-click to close, selects all paths/points inside
- **Smart Select** — arc-length curvature density matching (signature-based)
- **SelectSmall** — select paths below arc-length threshold

### Requirements
- [x] Polygon lasso tool
- [x] Smart select (signature matching)
- [x] Select small paths
- [ ] Point-count threshold for SelectSmall (CEP has this, C++ missing)

---

## Stage 3: Shape Cleanup (Average Selection)

### What It Must Do
1. User selects messy paths (lasso or click)
2. Clicks "Average Selection"
3. Plugin collects ALL selected anchors across all paths into ONE sorted array
4. Creates ONE output path spanning first-to-last point
5. Classifies shape: line (2pts), arc (3pts + handles), L-shape (3pts), rectangle (4pts), S-curve (3pts + handles), ellipse (4pts + handles), freeform
6. Simplifies to fewest possible points for that shape type
7. Preview path replaces messy originals (dimmed, in isolation)
8. **Handles stay active** — user can drag to adjust
9. Simplification slider scrubs through LOD cache (0=original, 100=pure primitive)
10. Tension slider adjusts handle smoothness
11. Reclassify buttons force a different shape type
12. Confirm = delete originals, promote preview. Cancel = restore originals.

### What Exists
- [x] PCA sort (SortByPCA)
- [x] Shape classification with fitted output points + handles (ClassifyPoints)
- [x] LOD precomputation with inflection preservation (PrecomputeLOD)
- [x] Preview path creation (PlacePreview)
- [x] Working mode (dim originals, isolate working group)
- [x] LOD slider scrubbing (ApplyLODLevel)
- [x] Reclassify on cached sorted points (FitPointsToShape)
- [x] Catmull-Rom handle computation (ComputeSmoothHandles)

### What's Missing / Broken
- [ ] Verify ONE path is created (not multiple)
- [ ] Handles must be visible and draggable after preview creation (Direct Selection tool activation)
- [ ] Auto-switch to Direct Selection tool after Average Selection
- [ ] Stroke: 80% black for preview path (not 1pt black default)
- [ ] Surface hint from VisionEngine integration (InferSurfaceType → boost classification confidence)
- [ ] Resmooth (tension slider recomputing handles on preview)
- [ ] Test end-to-end in Illustrator

---

## Stage 4: Perspective Grid

### UX Design (User's Specification)
1. **One button** ("Set Perspective") → all perspective lines appear at once
2. **Place first VP** → second VP automatically mirrored across horizon in the screen x space, once the vp is placed it can be manipulated
3. **Button to add vertical VP** → placed at center, user drags to position
4. **All handles live** — circle handles, per-line colors (VP1=red, VP2=green, VP3=blue)
5. **Lock button** → locks perspective, hides controls, disables editing
6. **Unlock** → shows controls again, with option to delete grid entirely
7. **Save/load perspective presets**
8. **Stored with document** via AIDictionarySuite (survives save/reopen)

### Perspective + Cleanup Integration
- If perspective is defined and shape is **circle** → output is an **ellipse projected into perspective**, the tool should guess the correct axis for the center of the elipse, if it's wrong, user should be able to toggle through the different axis by option clicking the circle. 
- If perspective is defined and shape is **rectangle** → output is a **quad projected into perspective**
- **Snap-to-perspective toggle** — enabled by default when perspective is locked
- **Can disable snap** to manually distort shapes via bounding box handles, which should be circles, the shape handles should be squares
- Mirror, duplicate, paste operations project through the perspective homography

### What Exists
- [x] Perspective grid annotator overlay with circle handles + per-line colors
- [x] Document persistence via AIDictionarySuite
- [x] Mirror/Duplicate/Paste-in-perspective math (homography projection)
- [x] Separate perspective tool registered in toolbox
- [x] Grid visible/hidden toggle
- [x] Lock toggle

### What's Missing
- [ ] Auto-mirror second VP when first is placed
- [ ] "Add Vertical" button that creates VP3 at center
- [ ] VP handle interaction (ToolMouseDown/Drag/Up for dragging VPs)
- [ ] Lock = hide controls + disable interaction (currently just a flag)
- [ ] Perspective preset save/load (serialize to named presets in plugin prefs)
- [ ] Snap-to-perspective toggle
- [ ] **Perspective projection of cleanup output** (circle→perspective-ellipse, rect→perspective-quad)
- [ ] Perspective-aware LOD (high simplification levels should output the perspective-projected primitive)

---

## Stage 5: Smart Merge

### What Exists
- [x] Greedy endpoint pairing with tolerance (ScanEndpoints)
- [x] Endpoint concatenation with handle averaging (MergeEndpoints)
- [x] Chain merge (re-scan after each merge)
- [x] Undo via snapshot

### What's Missing
- [ ] Merge preview via annotator overlay (connector lines between matched endpoints, colored by surface type)
- [ ] Surface-type scoring (optional VisionEngine integration)
- [ ] Verify handle swap on path reversal matches CEP's weldPoints()
- [ ] preserveHandles option (GIR mode)

---

## Stage 6: Blend Harmonization

### UX Design
- **Separate tool/panel** (not a tab in another panel)
- **Pick A → Pick B** dedicated mode (not shift-click)
- **Immediate real paths** — intermediates ARE final art, not preview
- **Easing curve editor** — square with draggable handles (cubic-bezier), presets (linear, ease-in/out), saveable custom presets
- **Re-editable** — select blend group later, adjust steps/easing/re-blend
- **State persistence** via AIDictionarySuite per blend group

### What Exists
- [x] Arc-length resampled blending with easing curves
- [x] Panel wired with step count, easing presets
- [x] AIDictionarySuite persistence for blend parameters

### What's Missing
- [ ] Interactive cubic-bezier curve editor widget in panel
- [ ] Save/load easing presets
- [ ] Re-edit mode (select existing blend group → recall parameters → adjust)

---

## Stage 7: Surface Shading

### UX Design
- **Separate tool/panel**
- **Two modes**: Blend shading (stacked contours for cel shading) + Mesh gradient (AIMeshSuite for smooth)
- **Color picking**: Panel pickers AND document eyedropper sampling
- **Light direction**: Circle widget with draggable handle (compass dial)
- **Intensity slider**

### What Exists
- [x] Blend shading + mesh gradient implementations
- [x] Panel with mode toggle, light direction, step count

### What's Missing
- [ ] Circle light direction widget (currently text/slider, not visual dial)
- [ ] Document color sampling (eyedropper)
- [ ] Intensity slider wiring

---

## Stage 8: Auto-Decompose

### What Exists
- [x] Proximity graph clustering (IllToolDecompose.cpp, 662 lines)
- [x] Annotator overlay with color-coded clusters
- [x] Accept/Split/Merge cluster operations

### What's Missing
- [ ] Test end-to-end in Illustrator
- [ ] VisionEngine integration (connected components, distance transform for smarter clustering)

---

## UI Skin File (IllTool-UI.ai)

An Illustrator file that defines all plugin visual elements — handles, cursors, icons, bounding box shapes. The plugin reads this file at runtime. Editing the `.ai` file changes the plugin's appearance without recompiling.

### Layers / Named Objects
- **Cursors**: Named art objects per tool cursor (lasso, perspective, smart select, etc.). Each has a hotspot marker (small crosshair or dot) that defines the click point.
- **Handles**: Shape handle (square), bbox handle (circle), perspective VP handle (circle, colored per VP), blend handle, shading handle.
- **Icons**: Panel toolbar icons for each operation.
- **Colors**: Named swatches for tool colors (orange edit stroke, 80% black final, VP1 red, VP2 green, VP3 blue, group orange, group blue).

### Runtime Loading
Plugin reads `~/Developer/ai-plugins/IllTool-UI.ai` (or bundled inside the .aip resources) on startup. Extracts named art objects and caches their geometry/colors. Falls back to hardcoded defaults if file missing.

### Current Issue
Lasso cursor hotspot is at upper-left corner instead of the actual click point. The UI skin file solves this — draw the cursor, place a hotspot marker, plugin reads the marker position.

## Cross-Cutting Requirements

### Plugin UX Standards
- Isolation mode MANDATORY during cleanup
- No bounding box — just edit simplified path directly
- No dashed lines EVER — solid strokes only
- Programmatic handles via AIAnnotatorSuite (not PathItem artwork)
- 80% black stroke for final paths, orange/cyan during edits
- Enter = confirm, Escape = cancel for ALL panels
- All overlays non-scaling, screen-space, no document pollution

### Dormant Systems to Wire
- **VisionEngine** — 14 algorithms built, only 3 called. Connected components + Hough could improve decompose + perspective detection.
- **LearningEngine** — SQLite-backed preference learning. Zero callers. Should record shape classifications, simplification levels, merge decisions.

### Build Pipeline
```bash
# 1. Build
xcodebuild -project IllTool.xcodeproj -configuration Release -arch arm64 build

# 2. Copy to install dir
rm -rf ~/Developer/ai-plugins/IllTool.aip
cp -R <sdk>/samplecode/output/mac/debug/IllTool.aip ~/Developer/ai-plugins/

# 3. Sign
codesign --force --sign "Developer ID Application: Ryder Booth (ASH39KMW4S)" \
  --deep --options runtime ~/Developer/ai-plugins/IllTool.aip

# 4. Zip + notarize
cd /tmp && rm -f IllTool.zip && zip -r IllTool.zip ~/Developer/ai-plugins/IllTool.aip
xcrun notarytool submit IllTool.zip --keychain-profile "notarytool" --wait

# 5. Staple
xcrun stapler staple ~/Developer/ai-plugins/IllTool.aip
```

### Thread Model
- SDK/timer thread: ProcessOperationQueue at ~10Hz
- HTTP server thread: joinable with 2-second timeout
- Main/Cocoa thread: panel NSTimer callbacks
- VisionEngine: recursive_mutex
- LearningEngine: recursive_mutex

---

## Priority Order

### P0 — Core loop must work
1. Fix cleanup to produce ONE clean path with **native Illustrator handles** (Direct Selection tool active after simplify)
2. Wire LearningEngine into EVERY cleanup operation (shape override, simplify level, noise delete, grouping) — data capture is the product
3. Fix perspective VP placement (place one → auto-mirror second, add vertical button, lock/hide, presets)
4. Wire perspective projection into cleanup output (circle→perspective-ellipse, rect→perspective-quad)
5. Add snap-to-perspective toggle

### P1 — Complete workflow
6. Trace panel in C++ plugin (bridge to vtracer/OpenCV/StarVector via HTTP)
7. Surface extraction panel (click-to-extract using DSINE normals)
8. Merge preview overlay
9. Blend easing curve editor
10. Perspective preset save/load
11. Shading light direction widget

### P2 — Intelligence & automation
12. LearningEngine predictions feeding UI defaults (shape suggestion, simplify level, noise threshold)
13. Wire remaining VisionEngine algorithms (connected components for decompose, Hough for perspective detection)
14. Surface-type scoring for merge
15. Correction learning (DWPose-style displacement deltas from user adjustments)
16. Interaction journal export for LLM consumption (structured data Claude can read to learn user patterns)
17. LLM-driven batch cleanup ("clean up all arm paths" → Claude reads captured data + invokes plugin operations)

---

## See Also
- [[CEP → C++ Port Audit]] — function-by-function correctness audit
- [[Plugin Architecture Hardening]] — queue/bridge infrastructure
- [[Local Vision Engine]] — 14 algorithms, mostly dormant
- [[On-Device Learning]] — SQLite learning, dormant
- [[Tool Inventory]] — 245+ MCP tools available
- [[ML Backends]] — SDPose, CartoonSeg, DiffVG, TRELLIS.2
