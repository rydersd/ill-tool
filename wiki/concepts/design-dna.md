# Design DNA System

> Brief: Extractable/transplantable design aesthetics — genetic approach to style with DNA extraction, mutation, and cross-pollination.
> Tags: design, dna, style, genetics, void
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
The VOID engine needed pluggable aesthetics, not a hardcoded style. Design DNA provides a framework for extracting, representing, and recombining visual style attributes.

## Overview

Design DNA treats visual style as a set of extractable attributes that can be:
- **Extracted** from reference images or existing designs
- **Transplanted** to new compositions
- **Mutated** with controlled variation
- **Cross-pollinated** between different style sources

## Components

- Reference image scraping (`scripts/fetch_reference_images.py`) with Pinterest deduplication
- Style definition files (e.g., `void_style_dr.jsx` for Designers Republic aesthetic)
- DNA backbone shared between `/design` and `/mj` (Midjourney prompt) skills
- Creative-director + prompt-engineer agents sharing the backbone

## Multi-Style Architecture

The system is explicitly designed for multiple styles, not a single aesthetic. Any "designer DNA" can be plugged into the VOID engine or other generation pipelines.

## See Also
- [[VOID Engine]]
- [[Architecture]]
