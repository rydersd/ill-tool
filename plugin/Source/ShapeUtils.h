#ifndef __SHAPEUTILS_H__
#define __SHAPEUTILS_H__

//========================================================================================
//  ShapeUtils — Pure math for shape classification, fitting, and simplification
//
//  No plugin state. No side effects. All functions operate on point/segment arrays.
//  Ported from CEP: geometry.jsx, shapes.jsx, pathutils.jsx, math2d.jsx
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"  // for BridgeShapeType enum
#include <vector>

//------------------------------------------------------------------------------------
//  Types shared across modules
//------------------------------------------------------------------------------------

/** Handle pair for bezier control points (in/left and out/right). */
struct HandlePair {
    AIRealPoint left;   // incoming handle
    AIRealPoint right;  // outgoing handle
};

/** Result of shape classification + fitting. */
struct ShapeFitResult {
    BridgeShapeType              shape = BridgeShapeType::Freeform;
    std::vector<AIRealPoint>     points;
    std::vector<HandlePair>      handles;
    bool                         closed = false;
    double                       confidence = 0;
};

/** One level in the LOD cache. */
struct LODLevel {
    int                          value;     // 0..100
    std::vector<AIRealPoint>     points;
    std::vector<HandlePair>      handles;   // empty if corner-only
};

//------------------------------------------------------------------------------------
//  Shape type name strings
//------------------------------------------------------------------------------------

extern const char* kShapeNames[];  // indexed by BridgeShapeType enum

//------------------------------------------------------------------------------------
//  2D geometry helpers
//------------------------------------------------------------------------------------

double PointToSegmentDist(AIRealPoint p, AIRealPoint a, AIRealPoint b);
double Dist2D(AIRealPoint a, AIRealPoint b);
bool   Circumcircle(AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                     double& cx, double& cy, double& radius);

//------------------------------------------------------------------------------------
//  PCA sort — order scattered anchors along dominant direction
//  Port of CEP geometry.jsx:17
//------------------------------------------------------------------------------------

std::vector<AIRealPoint> SortByPCA(const std::vector<AIRealPoint>& pts);

//------------------------------------------------------------------------------------
//  Shape classification + fitting
//  Port of CEP shapes.jsx:18 classifyShape() + shapes.jsx:76 fitToShape()
//------------------------------------------------------------------------------------

/** Classify a raw point array — returns best shape with fitted points + handles. */
ShapeFitResult ClassifyPoints(const std::vector<AIRealPoint>& pts, bool isClosed = false);

/** Force-fit points to a specific shape type — returns fitted points + handles. */
ShapeFitResult FitPointsToShape(const std::vector<AIRealPoint>& pts, BridgeShapeType shapeType);

//------------------------------------------------------------------------------------
//  LOD precomputation
//  Port of CEP geometry.jsx:220 precomputeLOD()
//------------------------------------------------------------------------------------

std::vector<LODLevel> PrecomputeLOD(
    const std::vector<AIRealPoint>& pts,
    int numLevels = 20,
    const ShapeFitResult* primitiveFit = nullptr);

//------------------------------------------------------------------------------------
//  Simplification helpers
//------------------------------------------------------------------------------------

/** Douglas-Peucker simplification on point arrays. */
std::vector<AIRealPoint> DouglasPeuckerPoints(
    const std::vector<AIRealPoint>& pts, double epsilon);

/** Find inflection points (curvature sign changes). */
std::vector<int> FindInflectionIndices(const std::vector<AIRealPoint>& pts);

/** Merge inflection points into a simplified point set. */
std::vector<AIRealPoint> MergeInflectionPoints(
    const std::vector<AIRealPoint>& simplified,
    const std::vector<AIRealPoint>& allPts,
    const std::vector<int>& inflectionIndices);

//------------------------------------------------------------------------------------
//  Handle computation
//  Port of CEP pathutils.jsx:161 computeSmoothHandles()
//------------------------------------------------------------------------------------

/** Compute Catmull-Rom handles for a point array. */
std::vector<HandlePair> ComputeSmoothHandles(
    const std::vector<AIRealPoint>& pts, bool closed, double tension = 1.0/6.0);

//------------------------------------------------------------------------------------
//  Preview path creation
//  Port of CEP pathutils.jsx:210 createPathWithHandles()
//------------------------------------------------------------------------------------

/** Create a real AIPathArt from points + handles inside a parent group. */
AIArtHandle PlacePreview(
    AIArtHandle parentGroup,
    const std::vector<AIRealPoint>& points,
    const std::vector<HandlePair>& handles,
    bool closed);

/** Update an existing path's segments in place (avoids destroy+create flicker). */
bool UpdatePreviewSegments(
    AIArtHandle existingPath,
    const std::vector<AIRealPoint>& points,
    const std::vector<HandlePair>& handles,
    bool closed);

//------------------------------------------------------------------------------------
//  Selection helpers
//------------------------------------------------------------------------------------

/** Find first selected path with segment-level or art-level selection. */
AIArtHandle FindSelectedPath(AIArtHandle** matches, ai::int32 numMatches);

/** Find ALL selected paths. */
std::vector<AIArtHandle> FindAllSelectedPaths(AIArtHandle** matches, ai::int32 numMatches);

/** Classify a single path from its segments — returns type + confidence. */
BridgeShapeType ClassifySinglePath(AIArtHandle targetPath, double& outConf);

#endif // __SHAPEUTILS_H__
