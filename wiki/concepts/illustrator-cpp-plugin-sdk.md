# Illustrator C++ Plugin SDK — Annotator API

> Brief: AIAnnotatorSuite + AIAnnotatorDrawerSuite enable screen-space overlay drawing (non-scaling handles, guides). Only way to get Astute-style on-canvas UI. Thin C++ bridge (~500-800 LOC) + TypeScript is the viable path.
> Tags: illustrator, c++, plugin, sdk, annotator, overlay, handles
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

Custom on-canvas handles (like Astute Dynamic Shapes) require the C++ Plugin SDK's `AIAnnotatorSuite`. Not accessible from ExtendScript, CEP, or UXP. Every plugin with custom overlay UI uses this API — no exceptions.

## AIAnnotatorSuite (Registration)

```
AddAnnotator()           — Register annotator at plugin startup
SetAnnotatorActive()     — Toggle on/off
InvalAnnotationRect()    — Trigger redraw of a region
```

Plugin receives messages via caller `"AI Annotation"`:
- `"AI Draw"` — provides `AIAnnotatorDrawer*` for rendering
- `"AI Invalidate"` — request to invalidate regions

## AIAnnotatorDrawerSuite v8 (Drawing API)

All drawing in **view/screen coordinates** (not document space). Use `AIDocumentViewSuite::ArtworkToViewPoint()` for conversion.

**Primitives:** DrawLine, DrawRect, DrawPolygon, DrawEllipse, DrawBezier (all with optional fill)
**Text:** DrawText, DrawTextAligned, GetTextBounds
**State:** SetColor (AIRGBColor), SetLineWidth, SetLineDashed/Ex, SetOpacity, SetHighlightMode
**Images:** DrawPNGImage, DrawPNGImageCentered
**Clipping:** DefineClipStart/End, ClearClip
**State stack:** Save/Restore
**Advanced:** GetAGMPort for Adobe Graphics Manager access, anti-aliasing options

## Interaction Model

Annotator is **draw-only** — no hit-testing. Interactive handles require:

1. **AIToolSuite** — Register custom tool receiving mouse events:
   - `kSelectorAIToolMouseDown/Drag/Up` (AIRealPoint in page coords)
   - `kSelectorAITrackToolCursor` (hover detection)
   - Includes pressure, tablet tilt/bearing/rotation

2. **Plugin-side hit-testing** — Track handle positions, compute proximity to cursor

3. **Invalidation loop** — During drag, call `InvalAnnotationRect()` → redraw handles at new positions

## SDK Sources (Available on GitHub)

- **AIAnnotator.h**: https://github.com/mcneel/rhino.inside/.../Illustrator2019SDK/.../AIAnnotator.h
- **AIAnnotatorDrawer.h**: https://github.com/WestonThayer/Bloks/.../AIAnnotatorDrawer.h
- **AITool.h**: https://github.com/WestonThayer/Bloks/.../AITool.h

## Open Source Examples

- **Bloks** (Flexbox for AI): https://github.com/WestonThayer/Bloks — full C++ plugin with annotator
- **PointView**: https://github.com/superpanic/PointView_winx64 — AIAnnotationDrawerSuite example

## Architecture: Thin C++ Bridge

Minimum viable path (~500-800 LOC C++):

```
C++ Plugin (thin render slave)
├── Annotator registration + draw callback
├── Tool registration + mouse event forwarding
├── HTTP/SSE server for TypeScript communication
│   ├── Receives: JSON drawing commands → translates to annotator calls
│   └── Sends: mouse events back to TypeScript
└── All business logic stays in TypeScript/ExtendScript
```

**NUXP** (https://github.com/ByteBard97/nuxp) proves this bridge pattern works — wraps 442+ SDK functions across 19 suites via HTTP/JSON. But does NOT yet wrap Annotator/AnnotatorDrawer suites. Could contribute bindings.

## What Doesn't Work

| Approach | Why Not |
|----------|---------|
| ExtendScript | No annotator access, no view-space drawing |
| CEP panels | Render in docked panel, never on document canvas |
| UXP | Not publicly available for Illustrator (as of 2026) |
| Transparent OS window | Fragile, unsupported, alignment issues |
| Document-space path items | Scale with zoom, clutter artwork, undo pollution |

## Known Limitation

Annotations only update **after tool operations complete** (not during native tool manipulation). For real-time feedback during handle dragging, must use own custom tool, not piggyback on native tools.

## Build Requirements (macOS)

- Xcode (current version)
- Illustrator Plugin SDK (download from Adobe Developer or use GitHub copies)
- Plugin install path: `~/Library/Application Support/Adobe/Illustrator/Plug-ins/`
- Debug loading: unsigned plugins load with `PlayerDebugMode 1`
- Must build universal binary (ARM + x86) for Apple Silicon Macs

## See Also
- [[Edge Clustering]] — clustering feature that needs overlay visualization
- [[Adversarial Review Findings]] — patterns the plugin must avoid
