# Project Evolution

> Brief: Chronological evolution from 45-tool monolith to 245+ tool research platform — 8 phases across March 2026.
> Tags: history, evolution, milestones, phases
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Understanding how the project grew explains architectural decisions and the research trajectory from breadth-first automation to depth-first illustration research.

## Timeline

### Phase 1: Foundation (March 15)
- Initial 45-tool monolithic MCP server (2,600 lines in single file)
- 8 Adobe apps: Photoshop, Illustrator, Premiere, After Effects, InDesign, Animate, Character Animator, Media Encoder
- COM + ExtendScript execution

### Phase 2: Architecture Modernization (March 22-23)
- Decomposed monolith into app-based sub-packages
- Added 9 context-efficient meta-tools (batch, workflow, pipeline, discover, etc.)
- WebSocket relay server replacing subprocess-per-call osascript
- CEP panels for in-app real-time control

### Phase 3: Creative Automation Expansion (March 22-23)
- VOID engine procedural generation pipeline
- AE generative render pipeline
- Design DNA reference image system
- Character animation foundation (rigging, posing, AE pipeline)
- 40+ illustration evolution tools
- Storyboard pipeline (20 tools, 203 tests)

### Phase 4: Hierarchy & Workflow (March 23)
- 40 object-agnostic hierarchy tools (176 tests)
- 20 workflow orchestration tools (72 tests)
- Landmark-axis drawing system
- Three-tier test infrastructure (153 tests)

### Phase 5: Advanced Drawing Techniques (March 23-25)
- Axis-guided contour scanner
- 3D form projection (perspective-aware form volumes)
- Multi-exposure edge voting (95 tests)

### Phase 6: ML Integration (March 23-24)
- 29 new tools, total tests: 1,045+
- ML backends: SDPose, CartoonSeg, DiffVG, Animated Drawings
- 3D reconstruction: TripoSR, InstantMesh, StdGEN, CharacterGen
- Format exports: OTIO, Spine, Rive, Lottie, Live2D
- Renamed to ill-tool v0.2.0, detached from upstream

### Phase 7: Research-Driven Drawing (March 25-28)
- Correction learning with upstream attribution
- Contour labeler + tonal analyzer + constraint solver (133 tests)
- Spatial AI research documentation (30+ papers surveyed)
- Constructive drawing methods research

### Phase 8: Spatial 3D-to-2D Pipeline (March 29-31)
- TRELLIS.2 integration for single-image-to-3D
- Mesh face grouper, spatial pipeline orchestrator
- Hausdorff-based pixel deviation scorer
- Self-correcting feedback loop (137 tests)
- Blog post documenting the research journey

## Milestone Summary

| Phase | Date | Tools | Tests |
|-------|------|-------|-------|
| Foundation | Mar 15 | 45 | - |
| Modernization | Mar 22 | 60 | baseline |
| Creative Expansion | Mar 23 | 80+ | 203 |
| Hierarchy/Workflow | Mar 23 | 120+ | 379 |
| ML Integration | Mar 24 | 200+ | 1,045+ |
| Spatial Pipeline | Mar 29 | 245+ | 1,315+ |

## Narrative Arc

The project traces a path from **generic Adobe automation** to **specialized AI-assisted illustration research**. Each phase built on prior foundations while maintaining backward compatibility. The critical inflection point was recognizing that 2D approaches to illustration fundamentally cannot solve problems requiring 3D understanding — leading to the 3D-to-2D spatial pipeline that represents the project's most significant contribution.

## See Also
- [[Architecture]]
- [[Spatial 3D-to-2D Pipeline]]
- [[VOID Engine]]
