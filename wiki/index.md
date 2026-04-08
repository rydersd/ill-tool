# Wiki Index
> Auto-maintained. Last updated: 2026-04-07. Articles: 38. Words: ~82K.

## Recent
- 2026-04-07: [IllTool PRD](concepts/illtool-prd.md) — Complete product requirements: trace → classify → simplify → perspective → shade. P0-P2 priorities, UX specs, what exists vs missing. Tags: prd, requirements, workflow
- 2026-04-07: [CEP → C++ Port Audit](concepts/cep-to-cpp-port-audit.md) — Function-by-function audit: 7 correct, 10 partial, 2 wrong, 7 missing. AverageSelection completely wrong (centroid collapse vs PCA+classify+refit). Tags: audit, port, cep, c++
- 2026-04-07: [Adversarial Review Round 3](concepts/plugin-adversarial-review-round3.md) — 40 issues from 5 specialist reviewers (thread, math, memory, integration, MRC). All P0s fixed. Tags: review, thread-safety, adversarial
- 2026-04-07: [Perspective Grid Foundation](concepts/perspective-grid-foundation.md) — Draggable-line perspective grid, VPs derived from extensions, annotator overlay. Tags: perspective, grid, annotator, tool
- 2026-04-07: [Blend Tool Implementation](concepts/blend-tool-implementation.md) — Production blend: arc-length resampling, easing curve editor, re-editable groups, AIDictionarySuite persistence. Tags: blend, easing, tool
- 2026-04-07: [Pipeline Gaps Closed](concepts/plugin-pipeline-gaps-closed.md) — All 6 gaps fixed, H1-H3 architecture hardening, dual adversarial review (Claude + Codex). Tags: plugin, architecture, review
- 2026-04-06: [Blend Harmonization](concepts/blend-harmonization.md) — Pre-blend point harmonization: arc-length resampling + de Casteljau + rotation alignment = twist-free interpolation for final art. Tags: blend, interpolation, bezier, art-production
- 2026-04-06: [Plugin Architecture Hardening](concepts/plugin-architecture-hardening.md) — Operation queue, result queue, undo stack, subsystem registration — scaling the plugin to 25+ operations. Tags: architecture, plugin, extensibility
- 2026-04-06: [AITimer Dispatch Pattern](concepts/aitimer-dispatch-pattern.md) — Universal SDK-context dispatch via AITimerSuite — the fix for DOC? errors blocking panel operations. Tags: sdk, architecture, timer, critical-fix
- 2026-04-06: [On-Device Learning](concepts/on-device-learning.md) — SQLite-backed ML learns shape preferences, simplification levels, noise thresholds from usage. No cloud, no LLM. Tags: learning, ml, on-device, sqlite
- 2026-04-06: [Predictive Path Completion](concepts/predictive-path-completion.md) — Place 3 points, tool draws the rest following surface curvature. Normal map + boundary signatures + learned preferences. Tags: prediction, path-completion, normals
- 2026-04-06: [Form Gradient Tool](concepts/form-gradient-tool.md) — Industrial design form-following gradients. Blend steps follow cross-contour flow, curvature controls falloff. Tags: gradient, blend, industrial-design
- 2026-04-06: [Local Vision Engine](concepts/vision-engine.md) — Pure C++ CV engine: 14 algorithms, no OpenCV. Canny, Hough, active contours, smart grouping with learning. Tags: vision, cv, c++
- 2026-04-06: [Illustrator C++ Plugin SDK](concepts/illustrator-cpp-plugin-sdk.md) — WORKING: notarized plugin with polygon lasso, HTTP bridge, 4 native panels, vision engine, learning engine. Tags: illustrator, c++, plugin
- 2026-04-04: [Cross-Layer Edge Clustering](concepts/edge-clustering.md) — Auto-cluster paths across extraction layers into structural edge groups. Distance threshold, overlap confidence, learning from accept/split/reject. Tags: clustering, cleanup, learning
- 2026-04-04: [Expanded Normal Renderings](concepts/expanded-normal-renderings.md) — Shape operator eigendecomposition → 10 new renderings: principal curvatures, surface type classification, ridge/valley, silhouettes, flow fields, cross-contour guides, auto line weight. Tags: normals, differential-geometry, eigendecomposition
- 2026-04-04: [Adversarial Review Findings](concepts/adversarial-review-findings.md) — 80+ bugs from 5 hostile agents: eval injection, bezier handle math, sidecar path mismatch, namespace collisions, weak tests. Patterns to prevent recurrence. Tags: review, bugs, security, patterns
- 2026-04-04: [Smart Merge Architecture](concepts/smart-merge.md) — Form-edge-aware path merging using normal sidecar intelligence. CEP panel with chain merge, preserve handles, color-coded surface coherence preview. Tags: tools, merge, normals, cep
- 2026-04-04: [Future Tools](concepts/future-tools.md) — Smart Merge, interaction capture for auto-model improvement, bounding box as skew modifier, coordinate robustness, module refactor. Tags: future, tools, ideas
- 2026-04-03: [Normal Map as Shadow-Free Reference](concepts/normal-map-as-reference.md) — **IMPLEMENTED**: DSINE normals → 5 shadow-free renderings that improve all 245+ tools. 166 tests. Tags: normals, architecture, preprocessing
- 2026-04-03: [Form Understanding Without Reconstruction](references/form-understanding-without-reconstruction-2026.md) — FULL SURVEY: depth estimation, surface normals, intrinsic decomposition, edge classification, line art -- 30+ models for extracting form edges without 3D mesh. Tags: research, depth, normals, edges, form-vs-shadow
- 2026-04-03: [Constructive Drawing Methods (Full)](references/constructive-drawing-methods.md) — FULL research: Loomis ratios, Vilppu gesture pipeline, Bridgman wedging chain, programmable rules. Tags: research, drawing
- 2026-04-03: [Spatial AI Research 2026 (Full)](references/spatial-ai-research-2026.md) — FULL survey: 30+ systems, leaderboard, VLM grounding, pipeline options, implementation results. Tags: research, papers
- 2026-04-03: [Project Evolution](concepts/project-evolution.md) — Chronological 8-phase evolution from 45-tool monolith to 245+ tool research platform. Tags: history, milestones
- 2026-04-03: [Spatial 3D-to-2D Pipeline](concepts/spatial-3d-pipeline.md) — Self-correcting pipeline: image -> TRELLIS.2 mesh -> face grouping -> 2D projection -> Hausdorff scoring. Tags: 3d, spatial, pipeline
- 2026-04-03: [LLM Spatial Reasoning](concepts/llm-spatial-reasoning.md) — LLMs can't output precise coordinates (tokenization problem); use LLMs for semantics, external solvers for geometry. Tags: llm, architecture
- 2026-04-03: [Correction Learning](concepts/correction-learning.md) — Store displacement deltas per iteration to improve the next, borrowed from DWPose. Tags: feedback, learning
- 2026-04-03: [Shadow vs Form Problem](concepts/shadow-vs-form.md) — Why 2D edge detection fails: shadows create false contours indistinguishable from form without 3D. Tags: fundamental-problem
- 2026-04-03: [ML Backends](concepts/ml-backends.md) — SDPose, CartoonSeg, DiffVG, TRELLIS.2, TripoSR, InstantMesh integration details. Tags: ml, models
- 2026-04-03: [Constructive Drawing Methods](concepts/constructive-drawing.md) — Loomis/Vilppu/Bridgman systematic drawing ratios, 3D-first construction. Tags: drawing, art
- 2026-04-03: [Blog: Teaching AI to See](references/blog-teaching-ai-to-see.md) — Narrative from 0.002/10 2D failure to 3D breakthrough with feedback learning. Tags: blog, narrative

## Concepts
- [Architecture](concepts/architecture.md) — FastMCP server with app-based modules, 245+ tools across 8 Adobe apps. Tags: architecture, mcp
- [Tool Inventory](concepts/tool-inventory.md) — 245+ tools by category: drawing, rigging, 3D, storyboard, export, meta. Tags: tools, inventory
- [Spatial 3D-to-2D Pipeline](concepts/spatial-3d-pipeline.md) — Image -> TRELLIS.2 -> face grouping -> 2D projection -> Hausdorff scoring -> correction learning. Tags: 3d, spatial, pipeline
- [VOID Engine](concepts/void-engine.md) — 7-step procedural machine generation in JSX with seeded PRNG and pluggable styles. Tags: void, procedural
- [Correction Learning](concepts/correction-learning.md) — Per-region displacement deltas accumulated across runs, 30% damped application. Tags: feedback, learning
- [Shadow vs Form Problem](concepts/shadow-vs-form.md) — Why 2D edge detection fails: shadows are not shapes, need 3D understanding. Tags: fundamental-problem
- [LLM Spatial Reasoning](concepts/llm-spatial-reasoning.md) — Tokenization prevents precise coordinates; LLMs for semantics, solvers for geometry. Tags: llm, architecture
- [ExtendScript Guide](concepts/extendscript-guide.md) — Per-app JSX differences: Illustrator ES3 JSON polyfill, coordinate inversions, indexing. Tags: jsx, polyfill
- [WebSocket Relay](concepts/websocket-relay.md) — Persistent CEP panel connections at ws://localhost:8765 with subprocess fallback. Tags: websocket, execution
- [Design DNA System](concepts/design-dna.md) — Extractable/transplantable design aesthetics with mutation and cross-pollination. Tags: design, style
- [Constructive Drawing Methods](concepts/constructive-drawing.md) — Loomis/Vilppu/Bridgman: ratio-based 3D-first construction for programmatic illustration. Tags: drawing, art
- [ML Backends](concepts/ml-backends.md) — SDPose, CartoonSeg, DiffVG, TRELLIS.2, TripoSR, InstantMesh model integration. Tags: ml, models
- [Test Infrastructure](concepts/test-infrastructure.md) — 163 test files, 3-tier testing, synthetic fixtures, JSXMock isolation. Tags: testing
- [Character Rigging](concepts/character-rigging.md) — 28 tools: skeleton, IK, binding, poses, deformation zones, multi-format export. Tags: rigging, animation
- [Storyboarding](concepts/storyboarding.md) — 30 tools: panels, camera, staging, transitions, beat sheets, EDL/OTIO export. Tags: storyboard, production
- [Project Evolution](concepts/project-evolution.md) — 8-phase growth from Mar 15-31 2026, monolith to spatial AI research platform. Tags: history, milestones
- [Normal Map as Shadow-Free Reference](concepts/normal-map-as-reference.md) — DSINE normals → 15 renderings (5 original + 10 eigendecomposition) as preprocessor for all tools. Tags: normals, architecture
- [Expanded Normal Renderings](concepts/expanded-normal-renderings.md) — Shape operator eigendecomposition: curvatures, surface types, ridge/valley, silhouettes, flow fields, cross-contours, auto line weight. Tags: normals, differential-geometry
- [Smart Merge Architecture](concepts/smart-merge.md) — Form-edge-aware path merging with normal sidecar intelligence. Tags: tools, merge, cep
- [Pipeline Gaps Closed](concepts/plugin-pipeline-gaps-closed.md) — 6 gaps fixed + H1-H3 hardening + dual adversarial review. Tags: plugin, architecture, review
- [Blend Tool Implementation](concepts/blend-tool-implementation.md) — Production blend with easing curve editor, state persistence, re-editable groups. Tags: blend, tool
- [Perspective Grid Foundation](concepts/perspective-grid-foundation.md) — Draggable-line perspective, derived VPs, annotator overlay. Tags: perspective, grid, tool
- [Adversarial Review Round 3](concepts/plugin-adversarial-review-round3.md) — 40 issues from 5 specialist reviewers. Thread mutexes, MRC fixes, integration wiring. Tags: review, adversarial
- [Adversarial Review Findings](concepts/adversarial-review-findings.md) — 80+ bugs from 5 hostile agents, root causes, patterns to prevent recurrence. Tags: review, bugs, patterns
- [Illustrator C++ Plugin SDK](concepts/illustrator-cpp-plugin-sdk.md) — WORKING: notarized plugin with lasso, panels, vision engine, learning engine. Tags: illustrator, c++, plugin
- [Local Vision Engine](concepts/vision-engine.md) — Pure C++ CV: 14 algorithms, no OpenCV. Canny, Hough, active contours, learning-integrated grouping. Tags: vision, cv, c++
- [On-Device Learning](concepts/on-device-learning.md) — SQLite-backed ML learns shape preferences, simplify levels, noise thresholds from usage. No cloud. Tags: learning, ml, sqlite
- [Predictive Path Completion](concepts/predictive-path-completion.md) — Place 3 points, tool extends along surface curvature using normal map + edge clusters. Tags: prediction, normals
- [Form Gradient Tool](concepts/form-gradient-tool.md) — Form-following gradients that map to surface curvature. Industrial design technique. Tags: gradient, blend
- [Form Edge Extraction Workflow](concepts/form-edge-extraction-workflow.md) — Ranked tool stack: multi-scale Canny, ink, DSINE form edges, shape averaging. Tags: workflow, edges, normals
- [AITimer Dispatch Pattern](concepts/aitimer-dispatch-pattern.md) — Universal SDK-context dispatch fixing DOC? errors. Tags: sdk, timer, critical-fix
- [Plugin Architecture Hardening](concepts/plugin-architecture-hardening.md) — Op queue, result queue, undo stack, subsystem registration. Tags: architecture, extensibility
- [Blend Harmonization](concepts/blend-harmonization.md) — Arc-length resampling + de Casteljau for twist-free shape interpolation. Tags: blend, bezier, art-production

## References
- [Spatial AI Research 2026](references/spatial-ai-research-2026.md) — **FULL SURVEY** migrated from docs/research/. 30+ systems, leaderboard, 3 pipeline options, implementation results. Tags: papers, spatial-ai
- [Constructive Drawing Methods](references/constructive-drawing-methods.md) — **FULL RESEARCH** migrated from docs/research/. Loomis head/figure ratios, Vilppu 6-phase pipeline, Bridgman wedging chain, unified programmable rules, foreshortening formulas. Tags: drawing, proportions
- [Mechanical Extraction Notes](references/mech-extraction-notes.md) — 8 failed 2D iterations, fill-percentage insight, 4.x plateau. Source: thoughts/. Tags: history
- [Blog: Teaching AI to See](references/blog-teaching-ai-to-see.md) — Research journey narrative from 2D failure to 3D breakthrough. Source: docs/. Tags: blog
- [Adding Tools Guide](references/adding-tools-guide.md) — Step-by-step: Pydantic model -> tool impl -> registration -> tests. Source: docs/. Tags: guide
- [Form Understanding Without Reconstruction 2026](references/form-understanding-without-reconstruction-2026.md) — **FULL SURVEY**: 30+ models for 3D form understanding from 2D without mesh reconstruction. Depth estimation (DA3, DepthPro, Marigold), surface normals (StableNormal, DSINE, GeoWizard), intrinsic decomposition (compphoto, FlowIID), edge classification (RINDNet++), line art, vectorization. Proposed lightweight pipeline alternatives to TRELLIS.2. Tags: research, depth, normals, edges
