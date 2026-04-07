# Blend Tool Implementation (Stage 11)

> Brief: Production blend harmonization — arc-length resampling, de Casteljau subdivision, custom easing curve editor, re-editable blend groups with AIDictionarySuite persistence.
> Tags: blend, interpolation, bezier, easing, art-production, tool
> Created: 2026-04-07
> Updated: 2026-04-07

## Motivation
Illustrator's built-in Blend tool matches points by index — if paths have different point counts or misaligned starting points, blends twist and distort. This tool solves the fundamental problem: harmonize two paths so they blend cleanly, then generate real intermediate artwork.

## Architecture

### Math Core (IllToolBlend.cpp)
1. **Arc-length parameterization**: Recursive de Casteljau subdivision (0.5pt tolerance, depth 10) gives position-based coordinate system independent of point count.
2. **Point correspondence**: Match by arc-length position, not index. 30% along Path A → 30% along Path B.
3. **Resampling**: Insert new anchors ON existing bezier curve at arc-length positions. Shape does NOT change. Both paths get equal point counts.
4. **Starting point alignment**: For closed paths, test all rotations of point indices, pick minimum total distance. O(n²) but n is small.
5. **Interpolation**: Lerp anchors + in/out handles with custom easing. Creates real kPathArt.

### Easing System
- 4 presets: Linear, EaseIn, EaseOut, EaseInOut (cubic-bezier with Newton iteration)
- Custom: interactive curve editor (224×224 NSView) with draggable control points
- Piecewise linear fallback for 3+ control points
- Curves saveable as presets

### State Persistence
Blend groups store parameters on art dictionary via AIDictionarySuite:
- `IllToolBlendGroup` (bool) — marker for identification
- `IllToolBlendSteps` (int) — step count
- `IllToolBlendEasing` (int) — easing preset

BlendState struct in memory tracks: group art, source paths, intermediates, custom easing points. ReblendGroup() deletes old intermediates and regenerates with new settings.

## UX (from user interview)
- Dedicated Pick A → Pick B mode (not shift-click)
- Immediate real paths (no preview overlay)
- Easing curve editor with add/remove handles
- Blend groups are re-editable after creation
- Each blend saves state

## Key Decisions
- Used AIDictionarySuite over SetArtName for persistence — structured data, survives save/reopen
- EasingCurve is internal to IllToolBlend.cpp — only preset index crosses the header boundary
- AIPathStyleSuite copies stroke/fill from path A to all intermediates

## See Also
- [[Blend Harmonization]] (algorithm theory)
- [[Plugin Pipeline Gaps Closed]] (architecture context)
