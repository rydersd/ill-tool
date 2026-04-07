# Pipeline Gaps Closed + Architecture Hardening

> Brief: All 6 pipeline gaps fixed, H1-H3 architecture hardening complete, adversarial review by both Claude and Codex with all findings addressed.
> Tags: plugin, architecture, pipeline, review
> Created: 2026-04-07
> Updated: 2026-04-07

## Motivation
After 9 stages were implemented by parallel agents, an adversarial review identified 6 pipeline gaps (disconnected UI controls, missing undo, dormant VisionEngine) and architectural limitations (16 atomic flags won't scale past 25 operations).

## Gap Fixes

| Gap | What | Approach |
|-----|------|----------|
| 1 | VisionEngine surface extraction dormant | Gradient histogram + divergence analysis → SurfaceHint → 0.15 confidence boost in ClassifySelection. Axial histogram (0..π), absolute divergence (polarity-safe). Python MCP override via HTTP. |
| 2 | Tension slider disconnected | BridgeSetTension → tensionScale in ReclassifyAs (clamped min 0.1) |
| 3 | SelectSmall not implemented | AIPathSuite::MeasureSegments for accurate bezier arc length, deselects before selecting |
| 4 | Add to Selection ignored | BridgeGetAddToSelection → conditional deselect in ExecutePolygonSelection |
| 5 | No cross-feature integration | Surface hint from VisionEngine feeds into shape classification |
| 6 | No undo for shape operations | Generic UndoStack with 20-frame multi-level undo, stale handle validation |

## Architecture Hardening

| Phase | What | Result |
|-------|------|--------|
| H1 | Operation queue | `mutex + deque<PluginOp>` replaces 16 atomic flag trios. New ops = enum + case. |
| H2 | Result queue | `mutex + deque<PluginResult>` replaces per-feature readout variables. |
| H3 | Generic undo stack | UndoStack class with PushFrame/SnapshotPath/Undo. 20-frame limit. |

## Adversarial Reviews

Two rounds of adversarial review:
1. **Claude review**: 14 issues (3 P0, 7 P1, 4 P2). All P0/P1 fixed.
2. **Codex review**: 6 issues (3 P1, 3 P2). All fixed.

Key fixes: stale handle validation via GetArtType, memory leak on early returns, axial gradient histogram, absolute divergence for polarity safety, MeasureSegments for arc length, boost guard (conf > 0.2).

## See Also
- [[AITimer Dispatch Pattern]]
- [[Plugin Architecture Hardening]]
- [[Local Vision Engine]]
