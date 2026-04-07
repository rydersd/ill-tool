# Plugin Architecture Hardening

> Brief: Four structural improvements to scale the C++ plugin beyond 15 operations: operation queue, result queue, undo stack, subsystem registration.
> Tags: architecture, plugin, extensibility, refactor
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

The atomic-flag-per-operation pattern works for 15 operations but won't scale to 25+ (Stages 10-12 add ~10 more). Four improvements prepare for known AND unexpected features.

## H1: Operation Queue

Replace N atomic flags with a single thread-safe queue of `{OpType, params}` structs.

- Panels push ops: `BridgeEnqueueOp({OpType::Simplify, .param1=tolerance})`
- Timer pops: `while (BridgeDequeueOp(op)) { switch (op.type) { ... } }`
- Adding a new feature = add an enum value + switch case. No new flag trio.

## H2: Result Callback Queue

Replace polling shared variables (`fLastDetectedShape`, `BridgeGetMergeReadout`) with a single result queue.

- Operations post: `BridgePostResult({.source=Classify, .text="ARC", .doubleValue=0.87})`
- Panels poll ONE queue in their NSTimer

## H3: Generic Undo Stack

Replace bespoke merge snapshot with a universal undo mechanism.

- `undoStack.PushFrame()` before any destructive operation
- `undoStack.SnapshotPath(art)` saves current segments + attributes
- `undoStack.Undo()` restores all paths in the top frame
- Works for Reclassify, Simplify, Merge, Blend, Shade — all destructive ops

## H4: Subsystem Registration

Replace God Object (all methods on IllToolPlugin) with registered subsystems.

```
ShapeSubsystem → Classify, Reclassify, Simplify
GroupingSubsystem → CopyToGroup, Detach, Split
MergeSubsystem → Scan, Merge, Undo
PerspectiveSubsystem → Grid, Distort
BlendSubsystem → Harmonize, Interpolate
ShadingSubsystem → Blend shade, Mesh gradient
```

Each subsystem owns its own state and undo frames. IllToolPlugin becomes a thin dispatcher.

## Implementation Order

1. H1+H2 (mechanical refactor, same behavior)
2. H3 (add to existing destructive operations)
3. H4 (extract into subsystems as new features are built)

## Key Decisions

- **Why not do H4 first?** Subsystems need the operation queue (H1) to receive ops. Build the queue first, then subsystems consume from it.
- **Why generic undo?** Every new destructive feature was reinventing snapshot/restore. One mechanism prevents bugs and reduces code.
- **Why result queue?** Each panel currently polls its own shared variable. With 6+ panels and 25+ operations, the polling spaghetti becomes unmaintainable.

## See Also
- [[AITimer Dispatch Pattern]] — the foundation these improvements build on
- [[Illustrator C++ Plugin SDK]] — full SDK article
