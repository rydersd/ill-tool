# VOID Engine

> Brief: 7-step procedural machine generation pipeline in ExtendScript — seeded PRNG, axis-locked geometry, multi-style support.
> Tags: void, procedural, generation, jsx, machines
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Needed a deterministic procedural generation system for creating mechanical poster designs in Illustrator, with pluggable style variants (not locked to a single aesthetic).

## Overview

The VOID engine is a multi-step JSX pipeline that generates mechanical/industrial poster designs directly in Adobe Illustrator. It uses a seeded xorshift32 PRNG for deterministic output and supports pluggable style definitions.

## Pipeline Steps

1. **void_run_01_setup.jsx** — Document setup (page size, artboards, guides)
2. **void_run_02_cylinders.jsx** — Cylinder generation
3. **void_run_03_housings.jsx** — Housing geometry
4. **void_run_04_connections.jsx** — Connection elements
5. **void_run_05_sections.jsx** — Cross-section visualization
6. **void_run_06_typography.jsx** — Text/label generation
7. **void_run_07_ortho.jsx** — Orthographic rendering/export

## Architecture

- **void_engine_lib.jsx** — Core 2D drawing primitives, xorshift32 seeded PRNG, math utilities, color, layer management
- **void_engine_compose.jsx** — Axis-locked machine composition aligned to STYLE.angle_grid
- **void_machine_lib.jsx** — Machine-specific drawing primitives
- **void_machine_composer.jsx** — Machine asset generation
- **void_machine_generate.jsx** — High-level generation API

## Style System

Styles are pluggable:
- **void_style_dr.jsx** — "Dr." style variant (Designers Republic-influenced)
- **void_style_manual.jsx** — Manual style definition

The engine is designed for multi-style architecture — any "designer DNA" can be plugged in rather than being locked to a single aesthetic.

## Key Design Choices

- **Seeded PRNG** — Same seed produces identical output. Critical for reproducibility and iteration.
- **Axis-locked geometry** — All shapes align to style-defined angle grids for visual coherence.
- **Style-agnostic core** — The engine draws; the style defines what drawing looks like.

## See Also
- [[Architecture]]
- [[Design DNA System]]
