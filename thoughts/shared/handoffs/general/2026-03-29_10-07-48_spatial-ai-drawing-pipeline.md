---
date: "2026-03-29T10:07:48-0700"
session_name: general
researcher: rydersd
git_commit: d4b1ade3aace02ad64a826276fc7671268091358
branch: master
repository: ill_tool
topic: "Teaching AI to See: Spatial Drawing Pipeline Experiments"
tags: [illustration, tracing, spatial-ai, 3d-reconstruction, creation-skill, dwpose, diffvg, constructivist-drawing]
status: complete
last_updated: "2026-03-29"
last_updated_by: rydersd
type: implementation_strategy
root_span_id: ""
turn_span_id: ""
---

# Handoff: Spatial AI Drawing Pipeline — 3 Sessions of Experiments

## Task(s)

### Completed
- **Multi-exposure edge voting system** — `contour_scanner.py` extended with form-vs-shadow edge classification via gamma sweep consensus. 32 tests. Committed.
- **Contour labeler** — classifies CV-extracted contours by tonal adjacency (silhouette_edge, face_boundary, panel_line, shadow_edge). 9 tests. Committed.
- **Tonal analyzer** — k-means zone segmentation + plane transition detection for 3D form surfaces. 7 tests. Committed.
- **Constraint solver** — resolves semantic constraints (silhouette edges, tonal boundaries, contour IDs) to exact pixel coordinates. 22 tests. Committed.
- **Correction delta learning** — stores DWPose joint correction patterns, pre-applies learned corrections to future figures. 24 tests. Committed.
- **DWPose integration** — rtmlib installed, working on mech figures. Detected both mechs with 133 keypoints each. User corrected skeletons stored on layers in Mech_Scan_Test.ai.
- **Creation skill graph** — 54 files (SKILL.md, index.md, 9 MOCs, 47 nodes, 1 orchestrator agent) covering anatomy, geometry, materials, construction, evaluation. At `~/.claude/skills/creation/`.
- **Constructivist drawing research** — Loomis/Vilppu/Bridgman methods, 670 lines. At `docs/research/constructive-drawing-methods.md`.
- **Spatial AI research** — 30+ papers surveyed on LLM spatial reasoning, image-to-SVG, 3D reconstruction. At `docs/research/`.
- **Blog draft** — "Teaching an AI to See Like an Illustrator" at `GIR-DR-Poster/blog-draft-teaching-ai-to-see.md`. Interview done, draft written, credits added. Needs Phase 3 refinement.

### Failed (Experimentally Valuable)
- **All trace attempts** — hand (0.2-1/10), head (0.2-0.3/10), tower (0-0.002/10). Each failure is preserved as a hidden labeled layer in the respective AI document.
- **Evaluator harness** — scored 4.6/10 on work the user scored 0.3/10. 20x calibration error. Needs pixel-deviation-based scoring, not subjective.
- **Algorithmic scanning** — gradient-based contour scanner works on synthetic tests, fails on real MJ renders.

### Next Step (planned, not started)
- **TRELLIS.2 integration** — open source 3D reconstruction from single image. Solves shadow-vs-form by going through 3D (mesh has no shadows, only geometry). Pipeline: reference → 3D mesh → face grouping by normals → 2D projection → vector paths.

## Critical References
1. `docs/research/spatial-ai-state-of-art-2026.md` — comprehensive survey of what's possible NOW
2. `docs/research/llm-spatial-reasoning-papers.md` — 30+ papers proving LLMs can't do precise coordinates
3. `~/.claude/plans/immutable-wishing-feather.md` — full plan with all innovations and pipeline design

## Recent Changes
- `src/adobe_mcp/apps/illustrator/contour_scanner.py` — gradient scanning + multi-exposure edge voting + contour extraction + skeleton assignment
- `src/adobe_mcp/apps/illustrator/contour_labeler.py` — NEW: contour classification by tonal adjacency
- `src/adobe_mcp/apps/illustrator/tonal_analyzer.py` — NEW: k-means zone segmentation + plane transitions
- `src/adobe_mcp/apps/illustrator/constraint_solver.py` — NEW: semantic constraints → coordinates
- `src/adobe_mcp/apps/illustrator/correction_learning.py` — NEW: DWPose correction delta learning
- `src/adobe_mcp/__init__.py` — upstream VoidChecksum/adobe-mcp attribution added
- `docs/research/` — 3 research documents (spatial AI, LLM reasoning, constructivist drawing)
- `tests/` — test_exposure_voting.py, test_contour_labeler.py, test_tonal_analyzer.py, test_constraint_solver.py, test_correction_learning.py

## Learnings

### The Fundamental Limitation (Proven by Research)
LLMs cannot output precise pixel coordinates due to tokenization. The embedding distance between 6.999 and 7.000 is nearly double that of 6.500 and 6.501. This is architectural, not fixable by training or prompting. Every successful spatial AI system uses LLM for semantics + external solver for geometry.

### Shadow vs Form is Unsolvable in 2D
Edge detection (Canny, Sobel, gradient) sees brightness transitions regardless of whether they're structural edges or lighting artifacts. The multi-exposure voting helps (form edges persist across exposures, shadows don't) but isn't sufficient for complex scenes. **Going through 3D solves this intrinsically** — meshes have geometry, not shadows.

### User's Key Drawing Method Insights
1. Adjust exposure to see into shadows BEFORE analyzing
2. Understand form through light/shadow FIRST → gross shapes → secondary → detail (Loomis/Bridgman/Vilppu order)
3. MJ images have anatomy errors — the skill graph is a DEBUGGER, not a textbook
4. "It's a perspective drawing" — I drew flat 2D rectangles on a 3D scene
5. "It's isometric" — there's a top face visible that I completely missed
6. DWPose gives rough skeleton → user corrects → correction patterns can be learned

### What the User Cares About
- Not just having AI do stuff, but figuring out HOW to get ideas out faster without nonsensical slop
- The experiment itself has value even when traces fail — each failure defines the problem more precisely
- Reference: Loomis, Vilppu, Bridgman (sp) for constructivist drawing fundamentals
- The blog post captures the journey — honest about failures

## Post-Mortem

### What Worked
- **DWPose on mechs**: rtmlib detected humanoid pose on robot figures. Spine chain within 2px of actual. Limbs within 12-30px. User corrected to accurate skeleton.
- **Multi-exposure edge voting**: correctly distinguished form edges (high votes) from shadow edges (low votes) on synthetic and real images. 14K form edge pixels found on tower.
- **User reference traces**: the hand reference trace (magenta, L_Hand Ref layer) taught transferable heuristics — 4-8 pts/form, angular segments, overlap for depth.
- **Blog interview process**: /write skill interview captured honest, unsentimental material. Draft has strong angle.
- **Research agents**: found rtmlib (lightweight, cartoon-support pose detection) in 4 minutes. Found 30+ relevant papers on spatial reasoning.

### What Failed
- **All coordinate placement**: 7+ attempts, 0-0.3/10. Proven by research to be an architectural limitation.
- **Evaluator harness**: 20x calibration error. Self-evaluation is fundamentally unreliable for spatial accuracy.
- **Creation skill graph for drawing**: 54 files of knowledge didn't improve trace quality. Knowledge ≠ ability.
- **Constraint pipeline on tower**: silhouette included cast shadow as form. Top face placed at base (coordinate conversion error). Tonal boundary split didn't produce meaningful 3D faces.
- **"Just iterate"**: 8 harness cycles on the head produced 0.3/10. Iterating on bad spatial understanding produces more bad spatial output.

### Key Decisions
- **Decision**: Use rtmlib/DWPose over SDPose for pose detection
  - Alternatives: SDPose (5.3GB, needs MMPose+SD2 stack), ViTPose (photos only)
  - Reason: 200MB, 3 pip packages, HumanArt-trained (cartoon support), one-line inference

- **Decision**: Build creation skill graph as knowledge base
  - Reason: Needed for MJ anatomy debugging and constructivist drawing method
  - Learning: Knowledge alone doesn't produce ability. The graph is a debugger/reference, not a teacher.

- **Decision**: Constraint-based pipeline (LLM labels, solver computes)
  - Alternatives: raw coordinate placement, pure CV
  - Reason: Research proves LLMs can't do coordinates. This plays to strengths.
  - Learning: Even with constraint pipeline, assembly/wiring is still spatial reasoning the LLM struggles with.

- **Decision**: Next step is TRELLIS.2 3D reconstruction
  - Alternatives: StarVector (SVG generation), more 2D tools
  - Reason: Shadow-vs-form is unsolvable in 2D. 3D mesh has no shadows. Open source, handles mechanical geometry.

## Artifacts
- `src/adobe_mcp/apps/illustrator/contour_scanner.py` — gradient scanning + multi-exposure voting
- `src/adobe_mcp/apps/illustrator/contour_labeler.py` — contour classification
- `src/adobe_mcp/apps/illustrator/tonal_analyzer.py` — tonal zone analysis
- `src/adobe_mcp/apps/illustrator/constraint_solver.py` — semantic constraints
- `src/adobe_mcp/apps/illustrator/correction_learning.py` — DWPose correction learning
- `tests/test_exposure_voting.py` — 32 tests
- `tests/test_contour_labeler.py` — 9 tests
- `tests/test_tonal_analyzer.py` — 7 tests
- `tests/test_constraint_solver.py` — 22 tests
- `tests/test_correction_learning.py` — 24 tests
- `~/.claude/skills/creation/` — 54-file skill graph
- `~/.claude/agents/creation-orchestrator.md` — orchestrator agent
- `docs/research/spatial-ai-state-of-art-2026.md` — spatial AI survey
- `docs/research/llm-spatial-reasoning-papers.md` — LLM spatial reasoning papers
- `docs/research/constructive-drawing-methods.md` — Loomis/Vilppu/Bridgman
- `~/.claude/plans/immutable-wishing-feather.md` — full pipeline plan with 12 innovations
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/project_mech_trace_session.md`
- `~/.claude/projects/-Users-ryders-Developer-GitHub-ill-tool/memory/illustration/hand-trace-heuristics.md`
- `GIR-DR-Poster/blog-draft-teaching-ai-to-see.md` — blog draft
- `GIR-DR-Poster/head-trace-hypotheses.md` — head trace analysis

## Action Items & Next Steps
1. **Integrate TRELLIS.2** for single-image 3D reconstruction → solve shadow-vs-form via 3D
2. **Try tower again** with 3D mesh → face grouping → 2D projection pipeline
3. **Install DiffVG** for gradient-based path refinement (Tier 2 of constraint pipeline)
4. **Calibrate evaluator** using pixel deviation metrics from user's hand reference trace
5. **Finish blog post** — Phase 3 (refine) with user voice calibration
6. **User to trace head reference** on magenta layer (discussed, not yet done)
7. **Compute correction deltas** from user's DWPose corrections on both mechs (data exists on layers)
8. **Update blog** with spatial AI research findings and TRELLIS.2 direction

## Other Notes
- The Illustrator documents are at: `/Users/ryders/Documents/Designs/Claude Experiments/GIR-DR-Poster/`
  - `Mech_Scan_Test.ai` — both mech skeletons, hand reference trace, all failed trace attempts
  - `Tower_Trace.ai` — tower reference with 3 failed trace attempts
- The reference image: `reference/mech_pair.png` (974×847, two MJ-generated mechs)
- Tower image cached at: `~/.claude/image-cache/52fb1914-abce-4396-9648-5e0f1e0acb07/1.png`
- All failed trace layers are preserved with scores in layer names (e.g., "Head Trace - Claude 01 [WRONG 0.2/10]")
- DWPose corrected skeletons on layers: "ML Test - DWPose -RB" (right mech), "ML Test - DWPose Left Mech -RB" (left mech)
- The user is also running a parallel SpuriousBlender project with related 3D work — research in docs/research/ is shared between both projects
- rtmlib + onnxruntime are installed in the venv
- Blog post needs Sedaris/Gladwell voice calibration (Phase 3 of /write)
