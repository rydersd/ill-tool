# Cleanup Interaction Model

> Brief: Complete interaction model for the cleanup tool — handle types, keyboard shortcuts, modes, and state machine for the shape cleanup workflow.
> Tags: cleanup, interaction, handles, shortcuts, UX
> Created: 2026-04-08
> Updated: 2026-04-08

## Motivation
The cleanup workflow needed a cohesive interaction model where all handles are draggable with one tool, keyboard modifiers provide power-user shortcuts, and the state machine cleanly transitions between lasso selection, handle editing, and apply/cancel.

## Handle Types

Three types of handles, all drawn by the annotator overlay, all interactive with the IllTool Handle tool:

| Handle | Shape | Color | Action |
|--------|-------|-------|--------|
| **Anchor point** | Square | White fill, dark outline (orange when active/hovered) | Drag to move anchor + handles together |
| **Bezier handle** | Small circle | White fill, gray outline (orange when hovered) | Drag to reshape curve (smooth points auto-mirror opposite handle) |
| **Bounding box** | Circle | White fill, cyan outline (yellow when hovered) | Drag to scale path (corners = free scale, midpoints = constrained) |
| **Rotate zone** | (outside bbox corners) | Cursor changes to rotation | Drag to rotate around bbox center |

All hit-testing uses **view-space distance** (screen pixels) so handles are consistent at any zoom level.

## Keyboard Shortcuts

| Modifier | Action | Context |
|----------|--------|---------|
| **Click** shape button | Auto-AverageSelection + reclassify | When not in working mode |
| **Click** shape button | Reclassify in place | When in working mode |
| **Option-click** path | Add smooth anchor point | Working mode |
| **Option-Shift-click** path | Add sharp corner point | Working mode |
| **Shift-click** anchor | Toggle sharp/smooth | Working mode |
| **Drag** anchor onto another | Auto-merge (5px threshold) | Working mode |
| **Enter** | Close lasso polygon | Lasso mode |
| **Apply** button | Promote preview, delete originals if checked, exit isolation | Working mode |
| **Cancel** button | Restore originals, delete preview, exit isolation | Working mode |

## State Machine

```
IDLE (lasso tool active, crosshair cursor)
  |
  |-- Lasso click → add vertex (can drag existing vertices to adjust)
  |-- Enter / double-click → execute selection
  |-- Shape button click → AverageSelection + enter WORKING MODE
  |
WORKING MODE (arrow cursor, handles visible)
  |
  |-- Click anchor → drag anchor
  |-- Click bezier handle → drag bezier handle
  |-- Click bbox handle → scale path
  |-- Click outside bbox near corner → rotate
  |-- Option-click path → add point
  |-- Shift-click anchor → toggle sharp/smooth
  |-- Shape button → reclassify in place
  |-- Apply → promote + exit
  |-- Cancel → restore + exit
  |
  → back to IDLE
```

## Group-Aware Cleanup

When selected paths share a common parent group:
- Working group is created inside the source group
- Apply places the cleaned path back in the source group
- Auto-naming: `"GroupName \u2014 Cleaned"` or `"LayerName \u2014 Cleaned"`

## See Also
- [[IllTool PRD]] \u2014 full product requirements
- [[CEP to C++ Port Audit]] \u2014 function-by-function correctness
