# Constructive Drawing Methods

> Brief: Loomis/Vilppu/Bridgman systematic drawing — programmable ratios, geometric assignments, 3D form before 2D contour.
> Tags: drawing, loomis, vilppu, bridgman, construction
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Traditional constructive drawing methods (taught in art schools for 100+ years) align perfectly with computational approaches — they're systematic, ratio-based, and prioritize 3D understanding over 2D contour tracing.

## Key Methods

### Andrew Loomis
- Head construction via sphere + jaw block with precise proportional ratios
- Figure construction from landmarks (7.5-8 head heights)
- All measurements relative — programmable as parametric ratios

### Glenn Vilppu
- Gesture-first approach: capture the action/flow before form
- Sphere-cylinder-box decomposition of organic forms
- "Draw through" — show hidden edges to prove 3D understanding

### George Bridgman
- Wedge/block decomposition of anatomy
- Emphasis on mechanical articulation points
- Form as interlocking geometric solids

## Relevance to Pipeline

These methods validate the spatial pipeline approach: artists have always known that 2D contour tracing produces dead drawings. The solution is the same whether human or AI — **understand the 3D form first, then project to 2D**.

The constraint-based drawing pipeline (contour labeler, tonal analyzer, constraint solver) was an attempt to encode these methods computationally in 2D. It produced 133 passing tests but zero-quality output — confirming that the methods require actual 3D understanding, not 2D approximations of it.

## See Also
- [[Shadow vs Form Problem]]
- [[Spatial 3D-to-2D Pipeline]]
