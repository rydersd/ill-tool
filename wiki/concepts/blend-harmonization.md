# Blend Harmonization — Shape Interpolation for Final Art

> Brief: Pre-blend point harmonization that fixes Illustrator's broken Blend tool. Arc-length resampling + de Casteljau subdivision + starting point alignment = twist-free interpolation.
> Tags: blend, interpolation, bezier, art-production, de-casteljau
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

Illustrator's Blend tool matches points by index. If paths have different point counts or misaligned starting points, blends twist and distort. Users must manually add/remove points and align starts — tedious, error-prone, and the #1 reason blend is avoided for production art.

## The Fix: 5-Step Harmonization

### Step 1: Arc-Length Parameterization
Compute arc length of each path via cubic bezier integration (recursive de Casteljau subdivision until segments are ~linear, sum chord lengths). Parameterize as t in [0, 1] where t = (arc length from start) / (total arc length).

### Step 2: Point Correspondence by Arc-Length
Don't match by index. Match by position. Point at 30% along Path A corresponds to position at 30% along Path B.

### Step 3: Resample to Match (Non-Destructive)
For the path with fewer points: insert new anchors ON the existing bezier curve at the arc-length positions that correspond to the other path's points. Uses de Casteljau splitting — the path shape DOES NOT CHANGE.

### Step 4: Starting Point Alignment (Closed Paths)
Test all rotations of point indices on Path B. Score each rotation: sum of distances between corresponding pairs. Choose minimum-distance rotation. O(n^2) but n is small (4-30 points).

### Step 5: Interpolation
With harmonized paths (same count, aligned starts, geometric correspondence):
```
for each step i in 1..N:
    t = i / (N + 1)  // or apply easing
    for each point j:
        intermediate[j].p   = lerp(A[j].p,   B[j].p,   t)
        intermediate[j].in  = lerp(A[j].in,  B[j].in,  t)
        intermediate[j].out = lerp(A[j].out, B[j].out, t)
```

## Shape-Aware Mode

Integrates with shape classification (Stage 3). If both paths are the same classified type:
- **Arcs**: lerp(center, radius, startAngle, sweepAngle) — cleaner intermediates
- **Ellipses**: lerp(center, semiMajor, semiMinor, rotation)
- **Lines**: trivial endpoint lerp
- **Mixed types**: fall back to harmonized point-lerp (still clean because of Steps 1-4)

## Key Math

- **De Casteljau**: Split bezier at parameter t → two sub-beziers with exact new control points
- **Bezier evaluation**: B(t) = (1-t)^3 P0 + 3(1-t)^2 t P1 + 3(1-t) t^2 P2 + t^3 P3
- **Arc-length**: Recursive subdivision until chord error < epsilon, sum chords
- **Rotation alignment**: argmin_r sum(dist(A[i], B[(i+r) % n]))

## Surface Shading Integration

Once blend harmonization works, it feeds directly into surface shading:
- **Blend mode**: Interpolated shapes get color steps from highlight → shadow
- **Mesh mode**: AIMeshSuite creates gradient mesh instead of blend steps
- Both driven by VisionEngine surface normal data (flat, cylindrical, convex, concave, saddle)

## See Also
- [[Form Gradient Tool]] — earlier concept using blend for shading
- [[Plugin Architecture Hardening]] — subsystem pattern for the blend implementation
- [[Local Vision Engine]] — surface type data that drives shading decisions
