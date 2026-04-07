# Perspective Grid Foundation (Stage 10)

> Brief: Draggable-line perspective grid — users place lines with two handles, VPs derived from extensions. Annotator overlay with dashed horizon, grid lines, VP markers.
> Tags: perspective, grid, annotator, tool
> Created: 2026-04-07
> Updated: 2026-04-07

## Motivation
Cleanup paths need to respect scene perspective. All existing transforms are flat — no vanishing point awareness. Stage 10 establishes the perspective grid that Stages 10b-d (Mirror, Duplicate, Paste in Perspective) and Stage 12 (Surface Shading) depend on.

## Interaction Model (from user interview)

- All 3 perspective lines appear at once (single "Set Perspective" button)
- Each line has two draggable handles (circles, different color per line)
- VPs are COMPUTED by extending lines to the horizon (not directly placed)
- Adjustable horizon line
- Lock button to freeze the grid
- VPs derived, not placed

## Data Model

```
PerspectiveLine: handle1, handle2, active
PerspectiveGrid: leftVP, rightVP, verticalVP (PerspectiveLines)
                 horizonY, locked, gridDensity
                 computedVP1, computedVP2, computedVP3 (derived)
```

Bridge state (continuous, not queued): `BridgeSetPerspectiveLine()` with mutex protection. Timer syncs at 10Hz.

## Annotator Overlay
- Horizon: dashed orange line
- User lines: solid white between handles, green square handle markers
- Extensions: dotted cyan from handles to infinity
- VP markers: yellow crosses with circles at computed intersection points
- Grid lines: radiating from VPs when locked

## Pending UX Refinements
- Consolidate to single "Set Perspective" button (currently 3 separate VP buttons)
- Circle handles instead of squares (user preference)
- Per-line colors (user preference)
- Interactive handle dragging via tool mode

## See Also
- [[AITimer Dispatch Pattern]]
- [[Plugin Architecture Hardening]]
