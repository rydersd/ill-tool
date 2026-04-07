# Local Vision Engine

> Brief: Pure C++ computer vision engine in the plugin. 14 algorithms, no OpenCV, no cloud. Canny, Hough, active contours, flood fill, contour extraction. Integrated with on-device learning for noise detection and smart grouping.
> Tags: vision, cv, c++, edge-detection, hough, contours, active-contours, learning
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

Real-time computer vision operations need zero latency. HTTP round-trips to Python add 10-50ms per call. For operations that run during mouse tracking (snap-to-edge, live contour highlighting), the CV must be in-process.

## Architecture

Pure C++ math — no OpenCV, no external CV libraries. ~1300 lines implementing 14 algorithms. Uses stb_image (public domain, header-only) for image loading. Integrated with the LearningEngine for noise detection and grouping.

## Algorithms Implemented

### Edge Detection
- **Canny** — Gaussian blur → Sobel gradient → non-maximum suppression → hysteresis thresholding
- **Sobel** — 3x3 gradient magnitude thresholding
- **Multi-scale** — Canny at N threshold scales with voting (edges that persist = form edges)

### Feature Detection
- **Hough lines** — rho/theta accumulator with precomputed trig tables
- **Hough circles** — gradient-direction voting in 3D accumulator with NMS

### Segmentation
- **Flood fill** — queue-based BFS with tolerance
- **Connected components** — union-find with path compression

### Contour Operations
- **Contour extraction** — Moore boundary tracing with area computation
- **Douglas-Peucker** — recursive polyline simplification
- **Active contours (snakes)** — energy minimization balancing elasticity, stiffness, edge attraction

### Learning-Integrated
- **DetectNoise** — queries LearningEngine per contour (arc length, point count, curvature variance)
- **SuggestGroups** — agglomerative clustering on proximity + curvature similarity + learned affinity

## HTTP Endpoints (localhost:8787)

| Endpoint | Purpose |
|----------|---------|
| POST /vision/load | Load reference image |
| GET /vision/status | Image dimensions, loaded state |
| POST /vision/edges | Edge detection (canny/sobel/multiscale) |
| POST /vision/detect-lines | Hough line detection |
| POST /vision/detect-circles | Hough circle detection |
| POST /vision/suggest-groups | Smart grouping with learning |
| POST /vision/snap-to-edge | Active contour snapping |
| POST /vision/flood-fill | Region segmentation |

## No Dependencies

- No OpenCV (would be ~100MB, complicates notarization)
- No external ML frameworks
- stb_image for PNG/JPEG loading (7KB, public domain)
- SQLite3 for learning engine (macOS system library)
- Standard C++ math only

## Learning Integration

**Noise detection**: For each contour, computes arc length, point count, and curvature variance. Queries LearningEngine::IsLikelyNoise() which returns true if metrics fall below learned thresholds from user's deletion history.

**Smart grouping**: Clusters contours by:
1. Spatial proximity (centroid distance)
2. Curvature similarity (mean curvature ratio)
3. Arc length similarity
4. Learned affinity (from user's past grouping actions)

After 50+ sessions, grouping suggestions match the user's actual grouping patterns.

## See Also
- [[On-Device Learning]] — the SQLite-backed learning engine
- [[Illustrator C++ Plugin SDK]] — the plugin hosting the vision engine
- [[Form Edge Extraction Workflow]] — Python-side extraction (complements C++ for batch operations)
