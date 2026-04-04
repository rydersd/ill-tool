# ExtendScript Guide

> Brief: Per-app JSX differences — Illustrator ES3 JSON polyfill, Photoshop native JSON, coordinate inversions, indexing quirks.
> Tags: extendscript, jsx, polyfill, json, es3
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Adobe apps use different ExtendScript engines with incompatible behaviors. This knowledge prevents hours of debugging from app-specific gotchas.

## Critical Differences

### JSON Support
- **Illustrator**: ES3 engine, **NO native JSON**. Must inject polyfill from `src/adobe_mcp/jsx/polyfills.py` with stringify/parse implementations. This was a major debugging sink — `JSON.stringify()` silently fails without the polyfill.
- **Photoshop**: Native JSON support. No polyfill needed.
- **After Effects**: Native JSON support.

### Coordinate Systems
- **Illustrator**: Y-axis goes UP (mathematical convention). Origin at bottom-left of artboard.
- **Photoshop**: Y-axis goes DOWN (screen convention). Origin at top-left.
- Coordinate inversions between apps are a common source of positioning bugs.

### Layer Indexing
- **Illustrator**: 0-based layer indexing
- **Photoshop**: 1-based layer indexing
- Off-by-one errors across apps are frequent

### Return Value Handling
- JSX `return` values must be strings — complex data must be JSON-stringified
- Illustrator requires the polyfill for this to work
- Template engine uses `{{param}}` placeholder substitution

## The JSON Polyfill

Located in `src/adobe_mcp/jsx/polyfills.py`. Auto-injected into all Illustrator JSX calls. Provides:
- `JSON.stringify(obj)` — object to JSON string
- `JSON.parse(str)` — JSON string to object

Without this, any tool that returns structured data from Illustrator will silently return `undefined`.

## See Also
- [[Architecture]]
- [[WebSocket Relay]]
