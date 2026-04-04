# Future Tool Ideas

> Brief: Planned tools and improvements from active experimentation — Smart Merge, interaction capture, shape tool refinements, bounding box as skew modifier.
> Tags: future, tools, ideas, smart-merge, interaction-capture, bounding-box
> Created: 2026-04-04
> Updated: 2026-04-04

## Smart Merge Tool

Proximity-based endpoint merging for disparate paths. Like 3D auto-merge:
- Select multiple open paths
- Endpoints within configurable radius auto-merge
- Preserves form — doesn't reshape, just connects
- Use case: GIR's eye chevrons — merge angular path segments without changing the contour
- Should be a third CEP panel using the shared ExtendScript library

## Interaction Capture System

Log user panel actions to inform tool evolution:
- Every reclassification (user overrides auto-detected shape type → training data for classifier)
- Every point adjustment (where the tool placed vs where the user moved → correction deltas)
- Every bounding box rotation/resize (what constraints the user applies)
- Store as JSON journal per session
- Use accumulated data to retrain/tune the auto-classification thresholds
- This is the same pattern as correction learning (DWPose deltas) but applied to the UI tool itself

## Shape Tool Refinements

From active user testing:
- **Simpler output**: Average should produce 3-point curves, not N-point median pass-throughs. The output should be the simplest geometric primitive that fits within tolerance.
- **Isolation mode**: After placing an averaged line, enter Illustrator's isolation mode so the user can direct-select and adjust the 3 points immediately.
- **Bounding box as skew modifier**: Not just a visual guide — the bbox should have draggable control points (4 corners + 4 midpoints). Dragging reshapes the bbox, and the constrained path adjusts to fit. Like a free-transform cage for the averaged path.
- **Rotatable bounding box**: Auto-rotated to match the dominant angle of the point cloud, but user can override the rotation.

## Coordinate System Robustness

Different Illustrator documents have different artboard origins:
- GIR: `artboardRect [0, 0, 758, -1052]` — Y goes negative downward
- Big Mech: `artboardRect [0, 1272, 952, 0]` — Y goes from top to bottom positive

Every extraction must read the actual artboardRect and compute the transform dynamically. Never hardcode Y-flip direction.

## Module Refactor

The `src/adobe_mcp/apps/illustrator/` directory has 200+ flat files. Proposed split:
```
illustrator/
├── core/          # inspect, modify, shapes, paths, layers, export
├── drawing/       # form_edge_*, normal_*, curve_fit, contour_*
├── rigging/       # skeleton, joints, ik, binding, poses
├── storyboard/    # panels, camera, staging, transitions
├── ml_backends/   # already split ✓
├── pipeline/      # spatial, feedback_loop, drawing_orchestrator
└── tools.py       # registration entry point
```

## See Also
- [[Form Edge Extraction Workflow]] — the current tool stack
- [[Normal Map as Shadow-Free Reference]] — the preprocessing architecture
- [[Correction Learning]] — the pattern for learning from user corrections
