//========================================================================================
//  ShapeUtils — Pure math for shape classification, fitting, and simplification
//
//  No plugin state. No side effects. All functions operate on point/segment arrays.
//  Ported from CEP: geometry.jsx, shapes.jsx, pathutils.jsx, math2d.jsx
//  Extracted from IllToolShapes.cpp for modularity.
//========================================================================================

#include "ShapeUtils.h"
#include "IllustratorSDK.h"
#include "IllToolSuites.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

//========================================================================================
//  Shape type name lookup
//========================================================================================

const char* kShapeNames[] = {
    "LINE", "ARC", "L-SHAPE", "RECT", "S-CURVE", "ELLIPSE", "FREEFORM"
};

//========================================================================================
//  2D geometry helpers
//========================================================================================

// Helper: perpendicular distance from point P to line segment AB
double PointToSegmentDist(AIRealPoint p, AIRealPoint a, AIRealPoint b)
{
    double abx = b.h - a.h, aby = b.v - a.v;
    double apx = p.h - a.h, apy = p.v - a.v;
    double abLenSq = abx * abx + aby * aby;
    if (abLenSq < 1e-12) return sqrt(apx * apx + apy * apy);
    double t = (apx * abx + apy * aby) / abLenSq;
    if (t < 0) t = 0; if (t > 1) t = 1;
    double dx = p.h - (a.h + abx * t);
    double dy = p.v - (a.v + aby * t);
    return sqrt(dx * dx + dy * dy);
}

double Dist2D(AIRealPoint a, AIRealPoint b) {
    double dx = b.h - a.h, dy = b.v - a.v;
    return sqrt(dx * dx + dy * dy);
}

bool Circumcircle(AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                          double& cx, double& cy, double& radius) {
    double ax = p1.h, ay = p1.v, bx = p2.h, by = p2.v, ccx = p3.h, ccy = p3.v;
    double D = 2.0 * (ax*(by-ccy) + bx*(ccy-ay) + ccx*(ay-by));
    if (fabs(D) < 1e-10) return false;
    cx = ((ax*ax+ay*ay)*(by-ccy) + (bx*bx+by*by)*(ccy-ay) + (ccx*ccx+ccy*ccy)*(ay-by)) / D;
    cy = ((ax*ax+ay*ay)*(ccx-bx) + (bx*bx+by*by)*(ax-ccx) + (ccx*ccx+ccy*ccy)*(bx-ax)) / D;
    double ddx = cx - p1.h, ddy = cy - p1.v;
    radius = sqrt(ddx*ddx + ddy*ddy);
    return true;
}

//========================================================================================
//  PCA Sort — order scattered anchors along their dominant direction
//  Port of CEP geometry.jsx:17 sortByPCA()
//========================================================================================

std::vector<AIRealPoint> SortByPCA(const std::vector<AIRealPoint>& pts)
{
    if (pts.size() < 2) return pts;

    // Compute centroid
    double cx = 0, cy = 0;
    for (auto& p : pts) { cx += p.h; cy += p.v; }
    cx /= pts.size(); cy /= pts.size();

    // Covariance matrix [cxx, cxy; cxy, cyy]
    double cxx = 0, cxy = 0, cyy = 0;
    for (auto& p : pts) {
        double dx = p.h - cx, dy = p.v - cy;
        cxx += dx * dx; cxy += dx * dy; cyy += dy * dy;
    }

    // First eigenvector via analytic 2x2 solution
    double trace = cxx + cyy;
    double det = cxx * cyy - cxy * cxy;
    double eigenvalue = trace / 2.0 + sqrt(fmax(0, trace * trace / 4.0 - det));

    double vx, vy;
    if (fabs(cxy) > 1e-10) {
        vx = eigenvalue - cyy;
        vy = cxy;
    } else if (cxx >= cyy) {
        vx = 1; vy = 0;
    } else {
        vx = 0; vy = 1;
    }

    // Normalize
    double vlen = sqrt(vx * vx + vy * vy);
    if (vlen > 1e-12) { vx /= vlen; vy /= vlen; }

    // Project each point and sort by projection value
    struct IndexedProj { int idx; double proj; };
    std::vector<IndexedProj> indexed(pts.size());
    for (int k = 0; k < (int)pts.size(); k++) {
        indexed[k] = { k, (pts[k].h - cx) * vx + (pts[k].v - cy) * vy };
    }
    std::sort(indexed.begin(), indexed.end(),
              [](const IndexedProj& a, const IndexedProj& b) { return a.proj < b.proj; });

    std::vector<AIRealPoint> sorted(pts.size());
    for (int m = 0; m < (int)pts.size(); m++) {
        sorted[m] = pts[indexed[m].idx];
    }

    // Direction check: use dot product of PCA axis with (last - first) of original
    // points. If negative, the sort reversed the curve direction — flip it back.
    // Dot product is more robust than Dist2D for collinear or nearly-symmetric cases.
    double origDirH = pts.back().h - pts[0].h;
    double origDirV = pts.back().v - pts[0].v;
    double sortDirH = sorted.back().h - sorted[0].h;
    double sortDirV = sorted.back().v - sorted[0].v;
    double dot = origDirH * sortDirH + origDirV * sortDirV;
    if (dot < 0) {
        std::reverse(sorted.begin(), sorted.end());
    }

    return sorted;
}

//========================================================================================
//  Inflection point detection — for LOD simplification
//  Port of CEP geometry.jsx:129 _findInflectionIndices()
//========================================================================================

std::vector<int> FindInflectionIndices(const std::vector<AIRealPoint>& pts)
{
    std::vector<int> result;
    result.push_back(0); // always keep first point

    if ((int)pts.size() < 3) {
        if (pts.size() > 1) result.push_back((int)pts.size() - 1);
        return result;
    }

    int prevSign = 0;
    for (int i = 1; i < (int)pts.size() - 1; i++) {
        double v1x = pts[i].h - pts[i-1].h, v1y = pts[i].v - pts[i-1].v;
        double v2x = pts[i+1].h - pts[i].h, v2y = pts[i+1].v - pts[i].v;
        double cp = v1x * v2y - v1y * v2x;
        int sign = (cp > 0) ? 1 : ((cp < 0) ? -1 : 0);
        if (sign != 0 && prevSign != 0 && sign != prevSign) {
            result.push_back(i);
        }
        if (sign != 0) prevSign = sign;
    }

    result.push_back((int)pts.size() - 1); // always keep last point
    return result;
}

//========================================================================================
//  Merge inflection points into a simplified point set
//  Port of CEP geometry.jsx:164 _mergeInflectionPoints()
//========================================================================================

std::vector<AIRealPoint> MergeInflectionPoints(
    const std::vector<AIRealPoint>& simplified,
    const std::vector<AIRealPoint>& allPts,
    const std::vector<int>& inflectionIndices)
{
    if (inflectionIndices.empty()) return simplified;

    std::vector<AIRealPoint> merged = simplified;
    const double EPSILON = 1e-6;

    for (int idx : inflectionIndices) {
        AIRealPoint ip = allPts[idx];

        // Check if this inflection point is already in merged
        bool found = false;
        for (auto& m : merged) {
            double dx = m.h - ip.h, dy = m.v - ip.v;
            if (dx * dx + dy * dy < EPSILON) { found = true; break; }
        }

        if (!found) {
            // Insert at correct position: find where it belongs by closest segment
            int bestInsert = (int)merged.size();
            double bestDist = 1e30;
            for (int s = 0; s < (int)merged.size() - 1; s++) {
                double d = PointToSegmentDist(ip, merged[s], merged[s + 1]);
                if (d < bestDist) { bestDist = d; bestInsert = s + 1; }
            }
            merged.insert(merged.begin() + bestInsert, ip);
        }
    }

    return merged;
}

//========================================================================================
//  Douglas-Peucker simplification on AIRealPoint arrays
//  (Static version for LOD precomputation — existing SimplifySelection uses path segments)
//========================================================================================

std::vector<AIRealPoint> DouglasPeuckerPoints(
    const std::vector<AIRealPoint>& pts, double epsilon)
{
    if ((int)pts.size() < 3) return pts;

    // Find the point with max distance from start-end line
    double maxDist = 0;
    int maxIdx = 0;
    AIRealPoint first = pts[0], last = pts[pts.size() - 1];

    for (int i = 1; i < (int)pts.size() - 1; i++) {
        double d = PointToSegmentDist(pts[i], first, last);
        if (d > maxDist) { maxDist = d; maxIdx = i; }
    }

    if (maxDist > epsilon) {
        // Recurse on both halves
        std::vector<AIRealPoint> left(pts.begin(), pts.begin() + maxIdx + 1);
        std::vector<AIRealPoint> right(pts.begin() + maxIdx, pts.end());
        auto recLeft = DouglasPeuckerPoints(left, epsilon);
        auto recRight = DouglasPeuckerPoints(right, epsilon);
        // Combine (remove duplicate at junction)
        std::vector<AIRealPoint> result(recLeft.begin(), recLeft.end() - 1);
        result.insert(result.end(), recRight.begin(), recRight.end());
        return result;
    } else {
        return { first, last };
    }
}

//========================================================================================
//  Precompute LOD levels — surface-aware multi-level simplification
//  Port of CEP geometry.jsx:220 precomputeLOD()
//========================================================================================

std::vector<LODLevel> PrecomputeLOD(
    const std::vector<AIRealPoint>& pts,
    int numLevels,
    const ShapeFitResult* primitiveFit)
{
    if (numLevels <= 0) numLevels = 20;
    std::vector<LODLevel> levels;

    // Compute bounding diagonal for epsilon scaling
    double minX = pts[0].h, maxX = pts[0].h;
    double minY = pts[0].v, maxY = pts[0].v;
    for (int i = 1; i < (int)pts.size(); i++) {
        if (pts[i].h < minX) minX = pts[i].h;
        if (pts[i].h > maxX) maxX = pts[i].h;
        if (pts[i].v < minY) minY = pts[i].v;
        if (pts[i].v > maxY) maxY = pts[i].v;
    }
    double diag = sqrt((maxX - minX) * (maxX - minX) + (maxY - minY) * (maxY - minY));
    if (diag < 1) diag = 1;

    // Level 0 = no simplification (original points)
    levels.push_back({ 0, pts, {} });

    // Precompute inflection indices for medium-level preservation
    auto inflectionIndices = FindInflectionIndices(pts);

    for (int lv = 1; lv <= numLevels; lv++) {
        double t = (double)lv / numLevels;
        int sliderValue = (int)(t * 100 + 0.5);

        if (t < 0.3 || !primitiveFit) {
            // Low simplification (or no surface hint): pure Douglas-Peucker
            double epsilon = diag * 0.001 * pow(100.0, t);
            auto simplified = DouglasPeuckerPoints(pts, epsilon);
            levels.push_back({ sliderValue, simplified, {} });

        } else if (t < 0.7) {
            // Medium: Douglas-Peucker with mandatory inflection points
            double epsilon = diag * 0.001 * pow(100.0, t);
            auto dpResult = DouglasPeuckerPoints(pts, epsilon);
            auto withInflections = MergeInflectionPoints(dpResult, pts, inflectionIndices);
            levels.push_back({ sliderValue, withInflections, {} });

        } else {
            // High: blend toward primitive fit
            double blendT = (t - 0.7) / 0.3;
            if (blendT >= 0.95 && primitiveFit) {
                // Pure primitive — the mathematically ideal shape
                levels.push_back({ sliderValue, primitiveFit->points, primitiveFit->handles });
            } else {
                // Transitional: increasingly aggressive DP
                double epsilon = diag * 0.001 * pow(100.0, t);
                auto dpHigh = DouglasPeuckerPoints(pts, epsilon);
                levels.push_back({ sliderValue, dpHigh, {} });
            }
        }
    }

    return levels;
}

//========================================================================================
//  Compute smooth Catmull-Rom handles for a point array
//  Port of CEP pathutils.jsx:161 computeSmoothHandles()
//========================================================================================

std::vector<HandlePair> ComputeSmoothHandles(
    const std::vector<AIRealPoint>& pts, bool closed, double tension)
{
    if (tension <= 0) tension = 1.0 / 6.0;
    int n = (int)pts.size();
    std::vector<HandlePair> handles(n);

    for (int i = 0; i < n; i++) {
        double ax = pts[i].h, ay = pts[i].v;

        int prevIdx, nextIdx;
        if (closed) {
            prevIdx = (i - 1 + n) % n;
            nextIdx = (i + 1) % n;
        } else {
            prevIdx = (i > 0) ? i - 1 : 0;
            nextIdx = (i < n - 1) ? i + 1 : n - 1;
        }

        if (!closed && (i == 0 || i == n - 1)) {
            // Endpoints on open paths: retracted handles
            handles[i] = { {(AIReal)ax, (AIReal)ay}, {(AIReal)ax, (AIReal)ay} };
        } else {
            // Interior or closed-path point: smooth tangent
            double tx = (pts[nextIdx].h - pts[prevIdx].h) * tension;
            double ty = (pts[nextIdx].v - pts[prevIdx].v) * tension;
            handles[i] = {
                {(AIReal)(ax - tx), (AIReal)(ay - ty)},
                {(AIReal)(ax + tx), (AIReal)(ay + ty)}
            };
        }
    }

    return handles;
}

//========================================================================================
//  Create a preview path from points + handles via AIPathSuite
//  Port of CEP pathutils.jsx:210 createPathWithHandles()
//========================================================================================

AIArtHandle PlacePreview(
    AIArtHandle parentGroup,
    const std::vector<AIRealPoint>& points,
    const std::vector<HandlePair>& handles,
    bool closed)
{
    if (points.empty()) return nullptr;

    AIArtHandle newPath = nullptr;
    ASErr err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, parentGroup, &newPath);
    if (err != kNoErr || !newPath) {
        fprintf(stderr, "[IllTool] PlacePreview: NewArt failed: %d\n", (int)err);
        return nullptr;
    }

    int n = (int)points.size();
    std::vector<AIPathSegment> segs(n);

    bool hasHandles = ((int)handles.size() == n);

    for (int i = 0; i < n; i++) {
        segs[i].p = points[i];
        if (hasHandles) {
            segs[i].in  = handles[i].left;
            segs[i].out = handles[i].right;
            segs[i].corner = false;
        } else {
            segs[i].in  = points[i];
            segs[i].out = points[i];
            segs[i].corner = true;
        }
    }

    sAIPath->SetPathSegmentCount(newPath, (ai::int16)n);
    sAIPath->SetPathSegments(newPath, 0, (ai::int16)n, segs.data());
    sAIPath->SetPathClosed(newPath, closed);

    // Style: 1pt 80% black stroke, no fill — clear preview for cleanup editing
    AIPathStyle style;
    memset(&style, 0, sizeof(style));
    style.fillPaint = false;
    style.strokePaint = true;
    style.stroke.width = (AIReal)1.0;
    style.stroke.color.kind = kThreeColor;
    style.stroke.color.c.rgb.red   = (AIReal)0.2;
    style.stroke.color.c.rgb.green = (AIReal)0.2;
    style.stroke.color.c.rgb.blue  = (AIReal)0.2;
    sAIPathStyle->SetPathStyle(newPath, &style);

    // Name for identification
    sAIArt->SetArtName(newPath, ai::UnicodeString("__preview__"));

    fprintf(stderr, "[IllTool] PlacePreview: created path with %d segments (handles=%s, closed=%s)\n",
            n, hasHandles ? "yes" : "no", closed ? "yes" : "no");
    return newPath;
}

//========================================================================================
//  Update an existing preview path's segments in place (no destroy+create)
//========================================================================================

bool UpdatePreviewSegments(
    AIArtHandle existingPath,
    const std::vector<AIRealPoint>& points,
    const std::vector<HandlePair>& handles,
    bool closed)
{
    if (!existingPath || points.empty()) return false;

    int n = (int)points.size();
    std::vector<AIPathSegment> segs(n);
    bool hasHandles = ((int)handles.size() == n);

    for (int i = 0; i < n; i++) {
        segs[i].p = points[i];
        if (hasHandles) {
            segs[i].in  = handles[i].left;
            segs[i].out = handles[i].right;
            segs[i].corner = false;
        } else {
            segs[i].in  = points[i];
            segs[i].out = points[i];
            segs[i].corner = true;
        }
    }

    sAIPath->SetPathSegmentCount(existingPath, (ai::int16)n);
    sAIPath->SetPathSegments(existingPath, 0, (ai::int16)n, segs.data());
    sAIPath->SetPathClosed(existingPath, closed);

    fprintf(stderr, "[IllTool] UpdatePreviewSegments: updated to %d segments (handles=%s, closed=%s)\n",
            n, hasHandles ? "yes" : "no", closed ? "yes" : "no");
    return true;
}

//========================================================================================
//  Classify a raw point array (not from a path) — returns ShapeFitResult
//  This is the standalone version used by AverageSelection on PCA-sorted points.
//  Uses the same math as ClassifySinglePath but operates on a point vector.
//========================================================================================

ShapeFitResult ClassifyPoints(
    const std::vector<AIRealPoint>& pts, bool isClosed)
{
    ShapeFitResult result;
    result.shape = BridgeShapeType::Freeform;
    result.closed = false;
    result.confidence = 0.1;
    result.points = pts;

    int n = (int)pts.size();
    if (n < 2) return result;

    AIRealPoint first = pts[0], last = pts[n-1];
    double span = Dist2D(first, last);

    // --- Test Line ---
    double lineDev = 0;
    for (int i = 1; i < n-1; i++) lineDev += PointToSegmentDist(pts[i], first, last);
    double avgLineDev = (n > 2) ? lineDev / (n-2) : 0;
    double lineConf = fmax(0, 1.0 - ((span > 1e-6) ? avgLineDev/span : 1.0) * 20.0);

    // --- Test Arc ---
    double arcConf = 0;
    double arcCx = 0, arcCy = 0, arcR = 0;
    if (n >= 3) {
        if (Circumcircle(first, pts[n/2], last, arcCx, arcCy, arcR) && arcR > 1e-6) {
            double td = 0;
            for (int i = 0; i < n; i++)
                td += fabs(sqrt((pts[i].h-arcCx)*(pts[i].h-arcCx)+(pts[i].v-arcCy)*(pts[i].v-arcCy)) - arcR);
            double sw = fabs(atan2(first.v-arcCy,first.h-arcCx) - atan2(last.v-arcCy,last.h-arcCx));
            if (sw > M_PI) sw = 2*M_PI - sw;
            arcConf = fmax(0, (1.0 - (td/n)/arcR*10.0) * (sw < 5.5 ? 1.0 : 0.3));
        }
    }

    // --- Test L-Shape ---
    double lConf = 0;
    int cornerIdx = 0;
    if (n >= 3 && span > 1e-6) {
        double maxD = 0;
        for (int i = 1; i < n-1; i++) { double d = PointToSegmentDist(pts[i],first,last); if (d>maxD){maxD=d;cornerIdx=i;} }
        AIRealPoint corner = pts[cornerIdx];
        double d1 = 0, d2 = 0;
        for (int a = 1; a < cornerIdx; a++) d1 += PointToSegmentDist(pts[a], first, corner);
        for (int b = cornerIdx+1; b < n-1; b++) d2 += PointToSegmentDist(pts[b], corner, last);
        double rd = ((d1+d2)/fmax(1,n-3)) / span;
        double v1x=first.h-corner.h, v1y=first.v-corner.v, v2x=last.h-corner.h, v2y=last.v-corner.v;
        double ll1=sqrt(v1x*v1x+v1y*v1y), ll2=sqrt(v2x*v2x+v2y*v2y);
        double dot = (ll1>1e-6&&ll2>1e-6) ? (v1x*v2x+v1y*v2y)/(ll1*ll2) : 0;
        lConf = fmax(0, (1.0-rd*15.0) * fmax(0,1.0-fabs(dot)));
    }

    // --- Test S-Curve ---
    double sConf = 0;
    int inflIdx = n/2;
    if (n >= 4) {
        int sc = 0, ps = 0;
        for (int i = 1; i < n-1; i++) {
            double cp = (pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v) - (pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
            int sg = (cp>0)?1:((cp<0)?-1:0);
            if (sg && ps && sg!=ps) { sc++; if (sc == 1) inflIdx = i; }
            if (sg) ps = sg;
        }
        sConf = 0.6 * ((sc>=1&&sc<=3)?1.0:0.3) * ((lineConf<0.7)?1.0:0.3);
    }

    // --- Test Ellipse ---
    double ellConf = 0;
    double ecx=0, ecy=0;
    if (n >= 5) {
        for (int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
        double ar=0;
        for (int i=0;i<n;i++) ar += sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy));
        ar /= n; if (ar<1) ar=1;
        double closureDist = Dist2D(first, last);
        double closureFactor = closureDist < ar * 0.5 ? 1.0 : 0.3;
        double td=0;
        for (int i=0;i<n;i++) td += fabs(sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy))-ar);
        ellConf = fmax(0, (1.0-(td/n)/ar*5.0) * closureFactor);
    }

    // --- Test Rectangle (only if closure distance is small) ---
    double rectConf = 0;
    if (n >= 4) {
        double closureDist = Dist2D(first, last);
        double diagLen = 0;
        double mnH=pts[0].h, mxH=pts[0].h, mnV=pts[0].v, mxV=pts[0].v;
        for(int i=1;i<n;i++){
            if(pts[i].h<mnH)mnH=pts[i].h; if(pts[i].h>mxH)mxH=pts[i].h;
            if(pts[i].v<mnV)mnV=pts[i].v; if(pts[i].v>mxV)mxV=pts[i].v;
        }
        diagLen = sqrt((mxH-mnH)*(mxH-mnH) + (mxV-mnV)*(mxV-mnV));
        if (diagLen < 1) diagLen = 1;
        double closureFactor = closureDist < diagLen * 0.3 ? 1.0 : 0.3;
        // Simple axis-aligned rectangle test
        double totalDist = 0;
        AIRealPoint co[4]={{(AIReal)mnH,(AIReal)mnV},{(AIReal)mxH,(AIReal)mnV},
                           {(AIReal)mxH,(AIReal)mxV},{(AIReal)mnH,(AIReal)mxV}};
        for (int i = 0; i < n; i++) {
            double minD = 1e30;
            for (int e = 0; e < 4; e++) {
                int e2 = (e + 1) % 4;
                double d = PointToSegmentDist(pts[i], co[e], co[e2]);
                if (d < minD) minD = d;
            }
            totalDist += minD;
        }
        double relDist = (totalDist / n) / diagLen;
        double aspect = 1;
        double w = mxH - mnH, h = mxV - mnV;
        if (w > 0 && h > 0) aspect = fmin(w,h)/fmax(w,h);
        double aspectPenalty = (aspect < 0.05) ? 0.2 : 1.0;
        rectConf = fmax(0, (1.0 - relDist * 10.0) * aspectPenalty * closureFactor);
    }

    // Find best candidate
    struct { double conf; BridgeShapeType type; } cands[] = {
        {lineConf, BridgeShapeType::Line}, {arcConf, BridgeShapeType::Arc},
        {lConf, BridgeShapeType::LShape}, {rectConf, BridgeShapeType::Rect},
        {sConf, BridgeShapeType::SCurve}, {ellConf, BridgeShapeType::Ellipse},
    };

    BridgeShapeType bestType = BridgeShapeType::Freeform;
    double bestConf = 0.1;
    for (auto& c : cands) { if (c.conf > bestConf) { bestConf = c.conf; bestType = c.type; } }

    // Now generate fitted output (points + handles) for the winning shape
    result.shape = bestType;
    result.confidence = bestConf;

    switch (bestType) {
        case BridgeShapeType::Line:
            result.points = { first, last };
            result.closed = false;
            break;

        case BridgeShapeType::Arc: {
            if (arcR < 1e-6) { result.points = { first, last }; break; }
            double a1 = atan2(first.v - arcCy, first.h - arcCx);
            double a3 = atan2(last.v - arcCy, last.h - arcCx);
            double sweep = a3 - a1;
            while (sweep > M_PI) sweep -= 2*M_PI;
            while (sweep < -M_PI) sweep += 2*M_PI;
            double am = a1 + sweep * 0.5;
            AIRealPoint ap[3] = {
                {(AIReal)(arcCx+arcR*cos(a1)), (AIReal)(arcCy+arcR*sin(a1))},
                {(AIReal)(arcCx+arcR*cos(am)), (AIReal)(arcCy+arcR*sin(am))},
                {(AIReal)(arcCx+arcR*cos(a1+sweep)), (AIReal)(arcCy+arcR*sin(a1+sweep))}
            };
            double sa = fabs(sweep/2), hLen = (4.0/3.0)*tan(sa/4.0)*arcR;
            double ss = (sweep >= 0) ? 1.0 : -1.0;
            double angs[3] = { a1, am, a1+sweep };
            result.points.resize(3);
            result.handles.resize(3);
            for (int i = 0; i < 3; i++) {
                double th = angs[i], tx = -sin(th)*ss, ty = cos(th)*ss;
                result.points[i] = ap[i];
                if (i == 0) {
                    result.handles[i] = { ap[i], {(AIReal)(ap[i].h+tx*hLen), (AIReal)(ap[i].v+ty*hLen)} };
                } else if (i == 2) {
                    result.handles[i] = { {(AIReal)(ap[i].h-tx*hLen), (AIReal)(ap[i].v-ty*hLen)}, ap[i] };
                } else {
                    result.handles[i] = { {(AIReal)(ap[i].h-tx*hLen), (AIReal)(ap[i].v-ty*hLen)},
                                          {(AIReal)(ap[i].h+tx*hLen), (AIReal)(ap[i].v+ty*hLen)} };
                }
            }
            result.closed = false;
            break;
        }

        case BridgeShapeType::LShape:
            result.points = { first, pts[cornerIdx], last };
            result.closed = false;
            break;

        case BridgeShapeType::Rect: {
            double mnH=pts[0].h, mxH=pts[0].h, mnV=pts[0].v, mxV=pts[0].v;
            for(int i=1;i<n;i++){
                if(pts[i].h<mnH)mnH=pts[i].h; if(pts[i].h>mxH)mxH=pts[i].h;
                if(pts[i].v<mnV)mnV=pts[i].v; if(pts[i].v>mxV)mxV=pts[i].v;
            }
            result.points = {
                {(AIReal)mnH,(AIReal)mnV}, {(AIReal)mxH,(AIReal)mnV},
                {(AIReal)mxH,(AIReal)mxV}, {(AIReal)mnH,(AIReal)mxV}
            };
            result.closed = true;
            break;
        }

        case BridgeShapeType::SCurve: {
            AIRealPoint ip = pts[inflIdx];
            double tn = 1.0/6.0;
            result.points = { first, ip, last };
            double t0x=(ip.h-first.h)*tn, t0y=(ip.v-first.v)*tn;
            double t1x=(last.h-first.h)*tn, t1y=(last.v-first.v)*tn;
            double t2x=(last.h-ip.h)*tn, t2y=(last.v-ip.v)*tn;
            result.handles = {
                { first, {(AIReal)(first.h+t0x),(AIReal)(first.v+t0y)} },
                { {(AIReal)(ip.h-t1x),(AIReal)(ip.v-t1y)}, {(AIReal)(ip.h+t1x),(AIReal)(ip.v+t1y)} },
                { {(AIReal)(last.h-t2x),(AIReal)(last.v-t2y)}, last }
            };
            result.closed = false;
            break;
        }

        case BridgeShapeType::Ellipse: {
            // Recompute PCA for ellipse fit
            double cxx=0,cxy=0,cyy=0;
            for(int i=0;i<n;i++){double dx=pts[i].h-ecx,dy=pts[i].v-ecy; cxx+=dx*dx; cxy+=dx*dy; cyy+=dy*dy;}
            cxx/=n; cxy/=n; cyy/=n;
            double tr=cxx+cyy, dt=cxx*cyy-cxy*cxy, disc=fmax(0,tr*tr/4-dt);
            double ev1=tr/2+sqrt(disc), ev2=tr/2-sqrt(disc);
            double ssa=sqrt(fmax(0,2*ev1)), ssb=sqrt(fmax(0,2*ev2));
            if(ssa<1)ssa=1; if(ssb<1)ssb=1;
            double ang = fabs(cxy)>1e-10 ? atan2(ev1-cxx,cxy) : (cxx>=cyy?0:M_PI/2);
            double ca=cos(ang), sna=sin(ang), kp=(4.0/3.0)*(sqrt(2.0)-1.0);
            double cAng[4]={0,M_PI/2,M_PI,3*M_PI/2};
            result.points.resize(4);
            result.handles.resize(4);
            for(int j=0;j<4;j++){
                double t=cAng[j], exx=ssa*cos(t), eyy=ssb*sin(t);
                double px=exx*ca-eyy*sna+ecx, py=exx*sna+eyy*ca+ecy;
                double ltx=-ssa*sin(t), lty=ssb*cos(t);
                double wtx=ltx*ca-lty*sna, wty=ltx*sna+lty*ca;
                double tl=sqrt(wtx*wtx+wty*wty); if(tl>1e-10){wtx/=tl;wty/=tl;}
                double hl=((j%2==0)?kp*ssb:kp*ssa);
                result.points[j] = {(AIReal)px, (AIReal)py};
                result.handles[j] = {
                    {(AIReal)(px-wtx*hl), (AIReal)(py-wty*hl)},
                    {(AIReal)(px+wtx*hl), (AIReal)(py+wty*hl)}
                };
            }
            result.closed = true;
            break;
        }

        default:
            // Freeform: keep original sorted points, compute smooth handles
            result.points = pts;
            result.handles = ComputeSmoothHandles(pts, false, 1.0/6.0);
            result.closed = false;
            break;
    }

    return result;
}

//========================================================================================
//  FitPointsToShape — force-fit sorted points to a specific shape type
//  Used by ReclassifyAs when operating on cached sorted points
//========================================================================================

ShapeFitResult FitPointsToShape(
    const std::vector<AIRealPoint>& pts, BridgeShapeType shapeType)
{
    // Create a temporary result with the right shape type,
    // then use ClassifyPoints and override the winner
    ShapeFitResult result;
    result.shape = shapeType;
    result.confidence = 0.5;
    result.closed = false;

    int n = (int)pts.size();
    if (n < 2) { result.points = pts; return result; }

    AIRealPoint first = pts[0], last = pts[n-1];

    switch (shapeType) {
        case BridgeShapeType::Line:
            result.points = { first, last };
            break;

        case BridgeShapeType::Arc: {
            double cx, cy, r;
            if (!Circumcircle(first, pts[n/2], last, cx, cy, r) || r < 1e-6) {
                result.points = { first, last };
                break;
            }
            double a1 = atan2(first.v - cy, first.h - cx);
            double a3 = atan2(last.v - cy, last.h - cx);
            double sweep = a3 - a1;
            while (sweep > M_PI) sweep -= 2*M_PI;
            while (sweep < -M_PI) sweep += 2*M_PI;
            double am = a1 + sweep * 0.5;
            result.points = {
                {(AIReal)(cx+r*cos(a1)), (AIReal)(cy+r*sin(a1))},
                {(AIReal)(cx+r*cos(am)), (AIReal)(cy+r*sin(am))},
                {(AIReal)(cx+r*cos(a1+sweep)), (AIReal)(cy+r*sin(a1+sweep))}
            };
            double sa = fabs(sweep/2), hLen = (4.0/3.0)*tan(sa/4.0)*r;
            double ss = (sweep >= 0) ? 1.0 : -1.0;
            double angs[3] = { a1, am, a1+sweep };
            result.handles.resize(3);
            for (int i = 0; i < 3; i++) {
                double th = angs[i], tx = -sin(th)*ss, ty = cos(th)*ss;
                AIRealPoint p = result.points[i];
                if (i == 0) result.handles[i] = { p, {(AIReal)(p.h+tx*hLen),(AIReal)(p.v+ty*hLen)} };
                else if (i == 2) result.handles[i] = { {(AIReal)(p.h-tx*hLen),(AIReal)(p.v-ty*hLen)}, p };
                else result.handles[i] = { {(AIReal)(p.h-tx*hLen),(AIReal)(p.v-ty*hLen)},
                                           {(AIReal)(p.h+tx*hLen),(AIReal)(p.v+ty*hLen)} };
            }
            break;
        }

        case BridgeShapeType::LShape: {
            double maxD = 0; int ci = 0;
            for (int i = 1; i < n-1; i++) { double d = PointToSegmentDist(pts[i],first,last); if(d>maxD){maxD=d;ci=i;} }
            result.points = { first, pts[ci], last };
            break;
        }

        case BridgeShapeType::Rect: {
            double mnH=pts[0].h, mxH=pts[0].h, mnV=pts[0].v, mxV=pts[0].v;
            for(int i=1;i<n;i++){
                if(pts[i].h<mnH)mnH=pts[i].h; if(pts[i].h>mxH)mxH=pts[i].h;
                if(pts[i].v<mnV)mnV=pts[i].v; if(pts[i].v>mxV)mxV=pts[i].v;
            }
            result.points = {
                {(AIReal)mnH,(AIReal)mnV}, {(AIReal)mxH,(AIReal)mnV},
                {(AIReal)mxH,(AIReal)mxV}, {(AIReal)mnH,(AIReal)mxV}
            };
            result.closed = true;
            break;
        }

        case BridgeShapeType::SCurve: {
            int ii = n/2, ps = 0;
            for (int i = 1; i < n-1; i++) {
                double cp = (pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v)-(pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
                int sg = (cp>0)?1:((cp<0)?-1:0);
                if (sg && ps && sg!=ps) { ii=i; break; }
                if (sg) ps=sg;
            }
            AIRealPoint ip = pts[ii];
            double tn = 1.0/6.0;
            result.points = { first, ip, last };
            double t0x=(ip.h-first.h)*tn, t0y=(ip.v-first.v)*tn;
            double t1x=(last.h-first.h)*tn, t1y=(last.v-first.v)*tn;
            double t2x=(last.h-ip.h)*tn, t2y=(last.v-ip.v)*tn;
            result.handles = {
                { first, {(AIReal)(first.h+t0x),(AIReal)(first.v+t0y)} },
                { {(AIReal)(ip.h-t1x),(AIReal)(ip.v-t1y)}, {(AIReal)(ip.h+t1x),(AIReal)(ip.v+t1y)} },
                { {(AIReal)(last.h-t2x),(AIReal)(last.v-t2y)}, last }
            };
            break;
        }

        case BridgeShapeType::Ellipse: {
            double ecx=0,ecy=0;
            for(int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
            double cxx=0,cxy=0,cyy=0;
            for(int i=0;i<n;i++){double dx=pts[i].h-ecx,dy=pts[i].v-ecy; cxx+=dx*dx; cxy+=dx*dy; cyy+=dy*dy;}
            cxx/=n; cxy/=n; cyy/=n;
            double tr=cxx+cyy, dt=cxx*cyy-cxy*cxy, disc=fmax(0,tr*tr/4-dt);
            double ev1=tr/2+sqrt(disc), ev2=tr/2-sqrt(disc);
            double ssa=sqrt(fmax(0,2*ev1)), ssb=sqrt(fmax(0,2*ev2));
            if(ssa<1)ssa=1; if(ssb<1)ssb=1;
            double ang = fabs(cxy)>1e-10 ? atan2(ev1-cxx,cxy) : (cxx>=cyy?0:M_PI/2);
            double ca=cos(ang), sna=sin(ang), kp=(4.0/3.0)*(sqrt(2.0)-1.0);
            double cAng[4]={0,M_PI/2,M_PI,3*M_PI/2};
            result.points.resize(4);
            result.handles.resize(4);
            for(int j=0;j<4;j++){
                double t=cAng[j], exx=ssa*cos(t), eyy=ssb*sin(t);
                double px=exx*ca-eyy*sna+ecx, py=exx*sna+eyy*ca+ecy;
                double ltx=-ssa*sin(t), lty=ssb*cos(t);
                double wtx=ltx*ca-lty*sna, wty=ltx*sna+lty*ca;
                double tl=sqrt(wtx*wtx+wty*wty); if(tl>1e-10){wtx/=tl;wty/=tl;}
                double hl=((j%2==0)?kp*ssb:kp*ssa);
                result.points[j] = {(AIReal)px, (AIReal)py};
                result.handles[j] = {
                    {(AIReal)(px-wtx*hl), (AIReal)(py-wty*hl)},
                    {(AIReal)(px+wtx*hl), (AIReal)(py+wty*hl)}
                };
            }
            result.closed = true;
            break;
        }

        default:
            result.points = pts;
            result.handles = ComputeSmoothHandles(pts, false, 1.0/6.0);
            break;
    }

    return result;
}

//========================================================================================
//  Selection helpers
//========================================================================================

// Helper: find first path with segment-level or art-level selection
AIArtHandle FindSelectedPath(AIArtHandle** matches, ai::int32 numMatches)
{
    AIArtHandle targetPath = nullptr;
    for (ai::int32 i = 0; i < numMatches && !targetPath; i++) {
        AIArtHandle art = (*matches)[i];
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(art, &segCount);
        if (segCount < 2) continue;
        for (ai::int16 s = 0; s < segCount; s++) {
            ai::int16 sel = kSegmentNotSelected;
            sAIPath->GetPathSegmentSelected(art, s, &sel);
            if (sel & kSegmentPointSelected) { targetPath = art; break; }
        }
        if (!targetPath) {
            ai::int32 selAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &selAttrs);
            if (selAttrs & kArtSelected) targetPath = art;
        }
    }
    return targetPath;
}

// Helper: find ALL paths with segment-level or art-level selection
std::vector<AIArtHandle> FindAllSelectedPaths(AIArtHandle** matches, ai::int32 numMatches)
{
    std::vector<AIArtHandle> result;
    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(art, &segCount);
        if (segCount < 2) continue;
        bool hasSel = false;
        for (ai::int16 s = 0; s < segCount; s++) {
            ai::int16 sel = kSegmentNotSelected;
            sAIPath->GetPathSegmentSelected(art, s, &sel);
            if (sel & kSegmentPointSelected) { hasSel = true; break; }
        }
        if (!hasSel) {
            ai::int32 selAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &selAttrs);
            if (!(selAttrs & kArtSelected)) continue;
        }
        result.push_back(art);
    }
    return result;
}

// Classify a single path — returns best shape type and confidence
BridgeShapeType ClassifySinglePath(AIArtHandle targetPath, double& outConf)
{
    outConf = 0;
    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(targetPath, &segCount);
    if (segCount < 2) return BridgeShapeType::Freeform;

    std::vector<AIRealPoint> pts(segCount);
    { std::vector<AIPathSegment> segs(segCount);
      sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
      for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p; }

    AIBoolean isClosed = false;
    sAIPath->GetPathClosed(targetPath, &isClosed);

    int n = (int)pts.size();
    AIRealPoint first = pts[0], last = pts[n-1];
    double span = Dist2D(first, last);

    // --- Test Line ---
    double lineDev = 0;
    for (int i = 1; i < n-1; i++) lineDev += PointToSegmentDist(pts[i], first, last);
    double avgLineDev = (n > 2) ? lineDev / (n-2) : 0;
    double lineConf = fmax(0, 1.0 - ((span > 1e-6) ? avgLineDev/span : 1.0) * 20.0);

    // --- Test Arc ---
    double arcConf = 0;
    if (n >= 3) {
        double ccxv, ccyv, r;
        if (Circumcircle(first, pts[n/2], last, ccxv, ccyv, r) && r > 1e-6) {
            double td = 0;
            for (int i = 0; i < n; i++)
                td += fabs(sqrt((pts[i].h-ccxv)*(pts[i].h-ccxv)+(pts[i].v-ccyv)*(pts[i].v-ccyv)) - r);
            double sw = fabs(atan2(first.v-ccyv,first.h-ccxv) - atan2(last.v-ccyv,last.h-ccxv));
            if (sw > M_PI) sw = 2*M_PI - sw;
            arcConf = fmax(0, (1.0 - (td/n)/r*10.0) * (sw < 5.5 ? 1.0 : 0.3));
        }
    }

    // --- Test L-Shape ---
    double lConf = 0;
    if (n >= 3 && span > 1e-6) {
        double maxD = 0; int ci = 0;
        for (int i = 1; i < n-1; i++) { double d = PointToSegmentDist(pts[i],first,last); if (d>maxD){maxD=d;ci=i;} }
        AIRealPoint corner = pts[ci];
        double d1 = 0, d2 = 0;
        for (int a = 1; a < ci; a++) d1 += PointToSegmentDist(pts[a], first, corner);
        for (int b = ci+1; b < n-1; b++) d2 += PointToSegmentDist(pts[b], corner, last);
        double rd = ((d1+d2)/fmax(1,n-3)) / span;
        double v1x=first.h-corner.h, v1y=first.v-corner.v, v2x=last.h-corner.h, v2y=last.v-corner.v;
        double ll1=sqrt(v1x*v1x+v1y*v1y), ll2=sqrt(v2x*v2x+v2y*v2y);
        double dot = (ll1>1e-6&&ll2>1e-6) ? (v1x*v2x+v1y*v2y)/(ll1*ll2) : 0;
        lConf = fmax(0, (1.0-rd*15.0) * fmax(0,1.0-fabs(dot)));
    }

    // --- Test Rectangle ---
    double rectConf = 0;
    if (n >= 4 && isClosed && (n == 4 || n == 5)) {
        int ra = 0;
        for (int i = 0; i < n; i++) {
            int prv = (i==0)?n-1:i-1, nxt = (i+1)%n;
            double aax=pts[prv].h-pts[i].h, aay=pts[prv].v-pts[i].v;
            double bbx=pts[nxt].h-pts[i].h, bby=pts[nxt].v-pts[i].v;
            double la=sqrt(aax*aax+aay*aay), lb=sqrt(bbx*bbx+bby*bby);
            if (la>1e-6 && lb>1e-6 && fabs((aax*bbx+aay*bby)/(la*lb)) < 0.3) ra++;
        }
        rectConf = (double)ra / fmax(1,n) * 0.9;
    }

    // --- Test S-Curve ---
    double sConf = 0;
    if (n >= 4) {
        int sc = 0, ps = 0;
        for (int i = 1; i < n-1; i++) {
            double cp = (pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v) - (pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
            int sg = (cp>0)?1:((cp<0)?-1:0);
            if (sg && ps && sg!=ps) sc++;
            if (sg) ps = sg;
        }
        sConf = 0.6 * ((sc>=1&&sc<=3)?1.0:0.3) * ((lineConf<0.7)?1.0:0.3);
    }

    // --- Test Ellipse ---
    double ellConf = 0;
    if (n >= 5 && isClosed) {
        double ecx=0,ecy=0;
        for (int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
        double ar=0;
        for (int i=0;i<n;i++) ar += sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy));
        ar /= n; if (ar<1) ar=1;
        double td=0;
        for (int i=0;i<n;i++) td += fabs(sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy))-ar);
        ellConf = fmax(0, (1.0-(td/n)/ar*5.0) * (isClosed ? 1.0 : 0.3));
    }

    struct { double conf; BridgeShapeType type; } cands[] = {
        {lineConf, BridgeShapeType::Line}, {arcConf, BridgeShapeType::Arc},
        {lConf, BridgeShapeType::LShape}, {rectConf, BridgeShapeType::Rect},
        {sConf, BridgeShapeType::SCurve}, {ellConf, BridgeShapeType::Ellipse},
    };

    BridgeShapeType bestType = BridgeShapeType::Freeform;
    double bestConf = 0.1;
    for (auto& c : cands) { if (c.conf > bestConf) { bestConf = c.conf; bestType = c.type; } }
    outConf = bestConf;
    return bestType;
}
