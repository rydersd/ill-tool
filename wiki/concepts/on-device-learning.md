# On-Device Learning Engine

> Brief: Lightweight ML that learns from user interactions — shape preferences, simplification levels, noise thresholds, grouping patterns. SQLite-backed, no cloud, no LLM. Decision tree / k-NN inference in C++.
> Tags: learning, ml, on-device, preferences, sqlite, plugin
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

Generic tools apply the same defaults to every user. But an illustrator who draws mechanical subjects has different preferences than one who draws characters. After 50 sessions, the plugin should know:
- What shape types the user prefers for each surface type
- What simplification level they settle on
- What they consider "noise" worth deleting
- Which paths they group together

## Architecture

```
User Action → Interaction Logger → SQLite DB → Inference Engine → UI Defaults
                                                    ↓
                                            Predicted Shape Type
                                            Suggested Simplify Level
                                            Noise Detection Threshold
                                            Grouping Affinity Score
```

### Storage
- `~/Library/Application Support/illtool/learning.db` (SQLite3, macOS system library)
- `interactions` table: every shape override, simplification, deletion, grouping action
- `preferences` table: derived preferences (updated after each session)

### Data Captured Per Interaction

| Action | Fields |
|--------|--------|
| Shape override | surface_type, auto_shape, user_shape |
| Simplification | surface_type, level, points_before, points_after |
| Noise delete | path_length, point_count, curvature_variance |
| Grouping | list of path names selected together |

### Inference (no external ML library)

**Shape prediction**: Most frequent user_shape for a given surface_type. Requires ≥3 samples.

**Simplify level**: Average simplify_level per surface_type. Requires ≥5 samples.

**Noise detection**: Paths shorter than 1.2× average deleted path length AND fewer points than 1.2× average deleted point count.

**Noise threshold**: Derived from deletion history — the learned "Select Small" threshold.

### C++ API

```cpp
class LearningEngine {
    void RecordShapeOverride(surfaceType, autoShape, userShape);
    void RecordSimplifyLevel(surfaceType, level, pointsBefore, pointsAfter);
    void RecordNoiseDelete(pathLength, pointCount, curvatureVariance);
    
    string PredictShape(surfaceType, pointCount, curvatureVariance);
    double PredictSimplifyLevel(surfaceType);
    bool IsLikelyNoise(pathLength, pointCount, curvatureVariance);
    double GetNoiseThreshold();
};
```

## What It Enables

- "Select Small" learns what YOU consider small
- Auto-detect shape learns YOUR preferences per surface type
- Simplification slider defaults to YOUR preferred level
- Smart Select knows which paths YOU group together
- All without any cloud calls, LLM inference, or external dependencies

## See Also
- [[Illustrator C++ Plugin SDK]] — the plugin that hosts the learning engine
- [[Correction Learning]] — the Python-side correction learning (displacement deltas)
- [[Future Tools]] — predictive path completion uses learned preferences
