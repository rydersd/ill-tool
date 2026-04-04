# Wiki Index
> Auto-maintained. Last updated: 2026-04-03. Articles: 22. Words: ~38K.

## Recent
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
- [Normal Map as Shadow-Free Reference](concepts/normal-map-as-reference.md) — DSINE normals → 5 shadow-free renderings as preprocessor for all tools. 166 tests. Tags: normals, architecture

## References
- [Spatial AI Research 2026](references/spatial-ai-research-2026.md) — **FULL SURVEY** migrated from docs/research/. 30+ systems, leaderboard, 3 pipeline options, implementation results. Tags: papers, spatial-ai
- [Constructive Drawing Methods](references/constructive-drawing-methods.md) — **FULL RESEARCH** migrated from docs/research/. Loomis head/figure ratios, Vilppu 6-phase pipeline, Bridgman wedging chain, unified programmable rules, foreshortening formulas. Tags: drawing, proportions
- [Mechanical Extraction Notes](references/mech-extraction-notes.md) — 8 failed 2D iterations, fill-percentage insight, 4.x plateau. Source: thoughts/. Tags: history
- [Blog: Teaching AI to See](references/blog-teaching-ai-to-see.md) — Research journey narrative from 2D failure to 3D breakthrough. Source: docs/. Tags: blog
- [Adding Tools Guide](references/adding-tools-guide.md) — Step-by-step: Pydantic model -> tool impl -> registration -> tests. Source: docs/. Tags: guide
- [Form Understanding Without Reconstruction 2026](references/form-understanding-without-reconstruction-2026.md) — **FULL SURVEY**: 30+ models for 3D form understanding from 2D without mesh reconstruction. Depth estimation (DA3, DepthPro, Marigold), surface normals (StableNormal, DSINE, GeoWizard), intrinsic decomposition (compphoto, FlowIID), edge classification (RINDNet++), line art, vectorization. Proposed lightweight pipeline alternatives to TRELLIS.2. Tags: research, depth, normals, edges
