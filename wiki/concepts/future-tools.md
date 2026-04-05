# Future Tool Ideas

> Brief: Planned tools — C++ plugin toolbar (polygon lasso, handles, click-to-extract), CEP improvements (ref opacity, activity accordion), and active experiments.
> Tags: future, tools, ideas, c++, backlog, polygon-lasso, surface-extract
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

## C++ Plugin Toolbar Tools (blocked on Apple notarization)

### Polygon Lasso Selection Tool
Click to place polygon vertices on canvas, double-click to close. All anchor points inside get selected. Works on visible/unlocked layers only.

**How it works**: C++ custom tool (AIToolSuite) captures canvas clicks. Annotator overlay draws polygon edges in real-time. On close, calls `polygonLassoSelect()` (already implemented in `cep/shared/ui.jsx` with `pointInPolygon` from `math2d.jsx`). Shift+double-click adds to selection.

### IllTool Handle Tool  
Non-scaling programmatic handles for cleanup operations. Draggable bezier curve handles. Bounding box as pixel-less line. All via AIAnnotatorSuite — no PathItems, no document pollution.

### Click-to-Extract (Surface Intelligence)
Click on reference → identify surface type → flood-fill connected region → extract boundary contours. MCP tool `adobe_ai_surface_extract` already built (click_extract, type_extract, region_extract). Needs C++ plugin for canvas click capture.

## CEP Panel Improvements (can ship now)

### Reference Opacity Slider
Slider in MCP panel to adjust reference layer opacity. Needed because reference should be dimmed while tracing.

### Activity Log Accordion
Operation log collapsed by default. Expand on click. Don't waste panel space.

## See Also
- [[Illustrator C++ Plugin SDK]] — C++ plugin architecture and notarization status
- [[Form Edge Extraction Workflow]] — the current tool stack
- [[Normal Map as Shadow-Free Reference]] — the preprocessing architecture
- [[Correction Learning]] — the pattern for learning from user corrections
