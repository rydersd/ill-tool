# Mechanical Shape Extraction Notes

> Brief: Working notes from 8 iterations of 2D extraction approaches — the fill-percentage insight and the plateau at 4.x scores before 3D pivot.
> Tags: mech, extraction, iterations, failure, pivot
> Created: 2026-04-03
> Updated: 2026-04-03
> Source: thoughts/mech-extraction-notes.md

## Motivation
Historical record of the 2D approach failures. Understanding why each approach failed is essential context for the 3D pipeline design.

## Key Insights from Notes

1. **Fill percentage determines contour quality** — Higher fill percentage (more of the reference covered) correlated with better contour extraction, but plateaued
2. **Scores plateaued at 4.x/10** before the architectural pivot to 3D — no amount of 2D refinement could break past this ceiling
3. **Subjective multi-factor scoring was unreliable** — Reported 4.6/10 on work actually worth 0.3/10, leading to adoption of Hausdorff distance
4. **8 distinct iteration approaches** were tried, each addressing a different aspect of the problem but all limited by 2D's inability to distinguish form from shadow

## Full Source
`thoughts/mech-extraction-notes.md`

## See Also
- [[Shadow vs Form Problem]]
- [[Spatial 3D-to-2D Pipeline]]
