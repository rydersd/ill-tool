# Character Rigging System

> Brief: Complete skeletal system — joint/bone hierarchy, IK solving, part binding, pose library, weight/deformation zones.
> Tags: rigging, skeleton, ik, joints, animation, character
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Enable Claude to rig Illustrator characters for animation — build skeletons, bind parts, store/apply poses, and export to animation formats.

## Overview

28 tools providing a full rigging pipeline from anatomical analysis through poseable characters.

## Pipeline

1. **Skeleton Annotation** — Mark joint locations on character artwork
2. **Skeleton Build** — Create joint/bone hierarchy from annotations
3. **Landmark Detection** — ML (SDPose 133-keypoint) or manual axis-based landmark placement
4. **Body Part Labeling** — Classify path groups as body parts
5. **IK Chain Setup** — Automatic IK chain detection from hierarchy
6. **Part Binding** — Bind artwork paths to skeleton joints
7. **Deformation Zones** — Define how geometry deforms around joints
8. **Pose Library** — Store/recall named poses with interpolation

## Persistence

Rig data stored as JSON at `/tmp/ai_rigs/{character_name}.json`:
```json
{
  "joints": [...],
  "bones": [...],
  "bindings": [...],
  "body_part_labels": {...},
  "poses": {...},
  "landmarks": [...],
  "axes": [...],
  "transforms": [...]
}
```

## Export Targets

- **Spine** — Spine skeleton JSON for game animation
- **Live2D** — Live2D parameter mapping
- **Rive** — Rive SVG format
- **Lottie** — Bodymovin JSON for web animation
- **After Effects** — AE keyframe/composition export

## See Also
- [[Tool Inventory]]
- [[ML Backends]]
