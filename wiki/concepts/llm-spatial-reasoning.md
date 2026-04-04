# LLM Spatial Reasoning Limitations

> Brief: LLMs cannot output precise coordinates — tokenization creates irrational distance metrics. Use LLMs for semantics, external solvers for geometry.
> Tags: llm, spatial, coordinates, tokenization, architecture
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Understanding why LLMs fail at spatial precision is critical for designing pipelines that actually work. This insight shapes every tool in the spatial pipeline.

## The Problem

LLM tokenizers split numbers into arbitrary subword tokens. The token distance between "100" and "101" bears no relation to their numeric distance. This means:

- Asking an LLM to output pixel coordinates produces randomly distributed points
- Fine-tuning doesn't fix this — it's architectural, not a data problem
- Even models specifically trained on spatial tasks (LLaMA-Mesh, MeshLLM) use discrete bins, not continuous coordinates

## The Pattern

All successful spatial AI systems follow the same architecture:

```
LLM → "what to do" (semantics, classification, layout decisions)
External Solver → "where to put it" (precise coordinates, geometry)
```

Examples:
- **Chat2SVG**: LLM generates SVG structure, optimization refines coordinates
- **StarVector**: LLM generates coarse paths, DiffVG refines them
- **Our pipeline**: LLM directs which forms to draw, TRELLIS+projection handles coordinates

## Key Insight

The constraint-based drawing pipeline failed not because the constraints were wrong, but because it ultimately asked the LLM to resolve constraints to pixel coordinates — the one thing LLMs architecturally cannot do.

## See Also
- [[Spatial 3D-to-2D Pipeline]]
- [[Shadow vs Form Problem]]
