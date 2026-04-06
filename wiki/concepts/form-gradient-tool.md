# Form Gradient / Smart Blend Tool

> Brief: Industrial design technique — form-following gradients that map to surface curvature, not linear/radial paths. Two paths define a transition; blend steps follow the cross-contour flow field.
> Tags: gradient, blend, form, industrial-design, normals, curvature
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

Industrial designers create razor-sharp product drawings using gradients that follow the 3D form. Normal gradients follow linear or radial paths. Form gradients follow the actual surface curvature — they compress where the surface turns away (highlight falloff) and stretch where it's flat.

## How It Works

1. User selects two paths defining start/end of a surface transition
2. Tool samples normal map between the paths — gets surface flow direction
3. Generates intermediate blend paths following cross-contour flow field
4. Maps gradient values to perpendicular curvature
5. Creates mesh gradient or expanded blend where color transition follows 3D form

## On a Cylinder
- Blend paths curve around the cylinder
- Gradient compresses where surface turns away (highlight falloff)
- Spacing follows actual surface geometry, not arbitrary distribution

## On Compound Surfaces
- Blend follows surface topology
- Transitions naturally across surface type boundaries
- Curvature map IS the gradient falloff rate

## Data Already Available

| Data | Source | Used for |
|------|--------|----------|
| Surface flow field | Cross-contours from normal map | Gradient direction |
| Curvature map | Gaussian curvature (eigendecomposition) | Gradient falloff rate |
| Surface type boundaries | Boundary signatures | Transition breakpoints |

## MCP Tool

`adobe_ai_form_gradient`
- Input: two path references, image_path, num_steps, color_start, color_end
- At each step: trace a cross-contour between the two paths
- Assign gradient value based on curvature-weighted interpolation
- Output as Illustrator paths with gradient fill

## See Also
- [[Normal Map as Shadow-Free Reference]] — provides the normal map and flow field
- [[Expanded Normal Renderings]] — curvature maps and surface types
