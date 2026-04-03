# Constructive Drawing Methods: Loomis, Vilppu, Bridgman

> Brief: Full extractable rules for programmatic figure construction — proportional ratios, geometric assignments, wedging chains, gesture pipelines.
> Tags: research, drawing, loomis, vilppu, bridgman, construction, proportions, figure
> Created: 2026-04-03
> Updated: 2026-04-03
> Migrated from: docs/research/constructive-drawing-methods.md

**Research date**: 2026-03-26
**Purpose**: Programmable geometric decomposition rules for AI-assisted illustration construction.
**Confidence**: HIGH for proportional systems and geometric assignments; MODERATE for exact ratios; LOW for subjective "feel" techniques.

---

## 1. Andrew Loomis

**Key texts**: *Drawing the Head and Hands* (1956), *Figure Drawing for All It's Worth* (1943)

### Head Construction: Ball-and-Jaw Method

The head is a sphere (cranium) with a jaw block attached. Construction order:

1. Draw sphere (cranium)
2. Place the cross: vertical center/nose line + horizontal brow line curving around sphere
3. Flatten sides (~2/3 sphere radius)
4. Divide vertically into thirds below brow: hairline-to-brow, brow-to-nose, nose-to-chin
5. Attach jaw block from ear area converging to chin

#### Programmable Ratios

| Measurement | Value |
|---|---|
| Head vertical division | 4 equal units: top-hairline, hairline-brow, brow-nose, nose-chin |
| Eye line position | Vertical center of total head height |
| Eye spacing | Width of one eye between eyes (front view) |
| Inner eye corners | Align vertically with nostril edges |
| Mouth placement | ~2/3 up from chin to nose base |
| Side plane width | ~2/3 of sphere radius |
| Ear vertical span | From brow line to nose base |

#### 3D Rotation Rules (Prokopenko extension)

- **Y-axis (left/right)**: Front-plane oval narrows; side-plane widens. Center line shifts toward visible edge.
- **X-axis (up/down)**: Thirds foreshorten. Down compresses upper thirds; up compresses lower.
- **Z-axis (roll)**: Angle of center line + side-plane oval establishes roll.
- **Foreshortening**: Nose base and ear base align at eye level. Tilt back = nose rises above ear. Tilt forward = nose drops below.

### Figure: 8-Head Mannequin

| Unit | Landmark |
|---|---|
| 0-1 | Top of head to chin |
| 1-2 | Chin to nipple line |
| 2-3 | Nipple to navel |
| 3-4 | Navel to crotch (HALFWAY) |
| 4-5 | Crotch to mid-thigh |
| 5-6 | Mid-thigh to below knee |
| 6-7 | Below knee to mid-lower-leg |
| 7-8 | Mid-lower-leg to sole |

#### Width Proportions

| Measurement | Male | Female |
|---|---|---|
| Shoulder width | 2 1/3 heads | 2 heads |
| Hip width | 1.5 heads | 1.5 heads |
| Waist width | ~1 1/3 heads | 1 head |

---

## 2. Glenn Vilppu

**Key texts**: *Vilppu Drawing Manual* (2012/2021), Vilppu Academy courses

### Core Philosophy

**"There are no rules, just tools."** Unlike Loomis's measurement-first, Vilppu treats primitives as analytical tools applied flexibly.

### Gesture-to-Construction Pipeline

| Phase | Purpose | Technique |
|-------|---------|-----------|
| 1. Gesture | Skeleton of movement | C/S/I curve vocabulary. Longest axis first. One main line of action. |
| 2. Spherical Forms | Containment | Wrap masses in spherical volumes. Two-mass indication (ribcage + pelvis). |
| 3. Box Forms | Spatial analysis | Convert spheres to boxes for plane orientation + perspective. |
| 4. Cylinders + Cross Contours | Volume description | Connect forms with cylinders. Ellipse orientation shows direction. |
| 5. Combining Forms | Interaction | Opposites — where one stretches, the other compresses. |
| 6. Bringing to Life | Gesture through form | Analysis of how forms function to show gesture through opposites. |

### Line Vocabulary (CSI)

- **C curve**: Single-direction arc (relaxed, flowing)
- **S curve**: Reversal curve/"line of beauty" (dynamic, twisting)
- **Straight (I)**: Tension, rigidity, structural emphasis

### Rules

1. Find LONGEST AXIS first
2. ONE main line of action connecting head through body to ground
3. Body forms alternate in angle (head, ribcage, pelvis create alternating C-curves)
4. NEVER make forms symmetrical ("snowman effect")

---

## 3. George Bridgman

**Key texts**: *Constructive Anatomy* (1920), *Bridgman's Life Drawing* (1924)

### Core Philosophy

**The body is a machine of interlocking wedges, boxes, and cylinders.** Mechanics-first approach.

### Three-Mass System

| Mass | Shape | Proportions |
|---|---|---|
| Head | Cube/block | 1" x 5/8" |
| Thorax | Tapered box: square top, triangular bottom | 1 3/4" x 1 1/4" |
| Pelvis | Square block | 1" x 1 3/8" |

### Wedging Chain

```
Neck (cylinder) -> Shoulders (square) -> Ribcage top (square) -> 
Ribcage bottom (triangular) -> Pelvis (square) -> Thighs (round) ->
Knees (square) -> Calves (triangular) -> Ankles (square)
```

**Pattern**: square -> triangular -> square -> round -> square -> triangular -> square

### Head: Cube Method

- Front face ratio: 1.75:1 (height:width) = 4:3 units
- Depth ratio: 1.25x width (7.5:6 units)
- 4-line feature placement system
- Ear: Diagonal intersection on side plane
- Cheekbone: 1/3 from front face to ear

---

## 4. Cross-Artist Comparison

| Aspect | Loomis | Vilppu | Bridgman |
|---|---|---|---|
| **Approach** | Template/measurement | Gesture/pipeline | Mechanics/wedging |
| **Starting point** | Proportional framework | Action/gesture line | Three mass blocks |
| **Head basis** | Sphere + jaw | Sphere (flexible) | Cube |
| **Ideal for AI** | Highest (most numerical) | Medium (clear pipeline, flexible values) | High for body (wedging is algorithmic) |

---

## 5. Unified Programmable Rules

### Proportional Framework (Loomis)

```
FIGURE_HEIGHT = 8 * HEAD_HEIGHT
HALFWAY_POINT = CROTCH (4 heads from top)
SHOULDER_WIDTH_MALE = 2.33 * HEAD_WIDTH
HIP_WIDTH = 1.5 * HEAD_WIDTH
RIBCAGE_HEIGHT = 2.0 * HEAD_HEIGHT
UPPER_ARM_LENGTH = 1.5 * HEAD_HEIGHT
UPPER_LEG_LENGTH = 2.0 * HEAD_HEIGHT
```

### Gesture Pipeline (Vilppu)

```python
PIPELINE_ORDER = [
    "gesture_line",          # C/S/I curves
    "two_mass_indication",   # ribcage + pelvis
    "sphere_containment",    # wrap in volumes
    "box_conversion",        # establish planes
    "cylinder_bridging",     # connect + cross-contours
    "anatomical_landmarks",  # thoracic arch, iliac crest
    "form_interaction",      # compress/stretch
    "surface_rendering"      # tone and line
]
```

### Wedging Chain (Bridgman)

```python
WEDGE_CHAIN = [
    {"part": "neck",    "shape": "cylinder"},
    {"part": "shoulders", "shape": "square"},
    {"part": "ribcage_top", "shape": "square"},
    {"part": "ribcage_bottom", "shape": "triangular"},
    {"part": "pelvis",  "shape": "square"},
    {"part": "thigh",   "shape": "round"},
    {"part": "knee",    "shape": "square"},
    {"part": "calf",    "shape": "triangular"},
    {"part": "ankle",   "shape": "square"}
]
```

---

## 6. Foreshortening Rules (All Three)

Universal principles:
1. **Draw through the form** — imagine transparency, draw contours over/under/around
2. **Overlap is the strongest depth cue** — foreshortened forms stack
3. **Ellipse width indicates angle** — rounder = more aimed at viewer
4. **Closer forms are larger** — consistent scale diminution
5. **Cross-contours follow curvature** — every surface mark wraps around form

```python
ELLIPSE_OPENNESS = sin(angle_between_axis_and_view) * 90
```

---

## 7. Seeing Through Shadows to Form

All three artists share: **Establish geometric mass BEFORE considering light.**

- **Loomis**: Build mannequin first, light is applied to known forms
- **Vilppu**: Construction in LINE before tonal rendering. Shadows follow cross-contours.
- **Bridgman**: Block construction IS the form. Shadows are unlit planes of known blocks.

```python
FORM_EDGES = ["plane_change", "silhouette_contour", "cross_contour_boundary"]
LIGHT_EDGES = ["cast_shadow", "ambient_occlusion", "specular_highlight_edge"]  # ignore for construction
```

**This principle validates the spatial pipeline approach**: artists have always known 2D contour tracing fails. Build 3D form first, project to 2D.

---

## Sources

### Primary (books)
- Loomis, A. (1943). *Figure Drawing for All It's Worth*
- Loomis, A. (1956). *Drawing the Head and Hands*
- Vilppu, G. (2021). *Vilppu Drawing Manual*
- Bridgman, G.B. (1920). *Constructive Anatomy*
- Bridgman, G.B. (1924). *Bridgman's Life Drawing*

### Research sources (web)
- GVAAT's Workshop (Loomis + Bridgman step-by-step) — HIGH trust
- Stan Prokopenko (Loomis 3D rotation extension) — HIGH trust
- Vilppu Academy, NMA lecture series — HIGH trust (first-party)
- Art Students League LINEA — HIGH trust (institutional)
- Binge Drawing, Love Life Drawing, 21-Draw, Fine Art Tutorials — MODERATE-HIGH trust

### Trust Assessment
- Proportional systems: well-corroborated across 3+ independent sources
- Vilppu pipeline: extractable but intentionally resists rigid formalization
- Bridgman body ratios: sparse numerically (illustrated rather than specified)
- Loomis mannequin: most numerically complete and directly programmable

## See Also
- [[Constructive Drawing Methods]] (concept article)
- [[Shadow vs Form Problem]]
- [[Spatial 3D-to-2D Pipeline]]
