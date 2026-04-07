//========================================================================================
//  IllTool — Blend Harmonization (Stage 11)
//  Arc-length parameterization, de Casteljau subdivision, path resampling,
//  starting-point alignment, and interpolated blend execution.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Easing Curve
//========================================================================================

struct EasingCurve {
    struct ControlPoint {
        double x, y;  // both in [0,1]
    };
    std::vector<ControlPoint> points;  // sorted by x

    /** Evaluate y at given x.
        - 0 control points: linear (return t).
        - 2 control points: cubic-bezier(p1x,p1y,p2x,p2y) with Newton iteration.
        - More: piecewise linear through (0,0), points..., (1,1). */
    double Evaluate(double t) const;

    static EasingCurve Linear();
    static EasingCurve EaseIn();
    static EasingCurve EaseOut();
    static EasingCurve EaseInOut();
};

// --- Cubic bezier solver for 2-point easing ---

// Evaluate cubic bezier basis at t for one axis: B(t) = 3(1-t)^2*t*p1 + 3(1-t)*t^2*p2 + t^3
static double CubicBezier1D(double t, double p1, double p2)
{
    double omt = 1.0 - t;
    return 3.0 * omt * omt * t * p1 + 3.0 * omt * t * t * p2 + t * t * t;
}

// Derivative of cubic bezier: B'(t) = 3(1-t)^2*p1 + 6(1-t)*t*(p2-p1) + 3*t^2*(1-p2)
static double CubicBezier1DDeriv(double t, double p1, double p2)
{
    double omt = 1.0 - t;
    return 3.0 * omt * omt * p1 + 6.0 * omt * t * (p2 - p1) + 3.0 * t * t * (1.0 - p2);
}

double EasingCurve::Evaluate(double t) const
{
    // Clamp
    if (t <= 0.0) return 0.0;
    if (t >= 1.0) return 1.0;

    if (points.empty()) {
        // Linear
        return t;
    }

    if (points.size() == 2) {
        // Standard CSS cubic-bezier: control polygon (0,0), (p1x,p1y), (p2x,p2y), (1,1).
        // Solve for bezier parameter u such that Bx(u) = t, then return By(u).
        double p1x = points[0].x, p1y = points[0].y;
        double p2x = points[1].x, p2y = points[1].y;

        // Newton-Raphson to find u where CubicBezier1D(u, p1x, p2x) = t
        double u = t; // initial guess
        for (int i = 0; i < 8; i++) {
            double x = CubicBezier1D(u, p1x, p2x) - t;
            double dx = CubicBezier1DDeriv(u, p1x, p2x);
            if (std::fabs(dx) < 1e-12) break;
            u -= x / dx;
            u = std::max(0.0, std::min(1.0, u));
        }
        // Bisection fallback if Newton didn't converge well
        double xVal = CubicBezier1D(u, p1x, p2x);
        if (std::fabs(xVal - t) > 1e-6) {
            double lo = 0.0, hi = 1.0;
            for (int i = 0; i < 20; i++) {
                double mid = (lo + hi) * 0.5;
                if (CubicBezier1D(mid, p1x, p2x) < t) lo = mid; else hi = mid;
            }
            u = (lo + hi) * 0.5;
        }
        return CubicBezier1D(u, p1y, p2y);
    }

    // Piecewise linear through (0,0), all control points, (1,1)
    // Build full point list
    std::vector<ControlPoint> pts;
    pts.push_back({0.0, 0.0});
    for (auto& cp : points) pts.push_back(cp);
    pts.push_back({1.0, 1.0});

    // Find segment containing t
    for (size_t i = 0; i + 1 < pts.size(); i++) {
        if (t <= pts[i + 1].x || i + 2 == pts.size()) {
            double range = pts[i + 1].x - pts[i].x;
            if (range < 1e-12) return pts[i].y;
            double frac = (t - pts[i].x) / range;
            return pts[i].y + (pts[i + 1].y - pts[i].y) * frac;
        }
    }
    return t;
}

EasingCurve EasingCurve::Linear()
{
    EasingCurve c;
    // Empty points = linear
    return c;
}

EasingCurve EasingCurve::EaseIn()
{
    EasingCurve c;
    c.points = {{0.42, 0.0}, {1.0, 1.0}};
    return c;
}

EasingCurve EasingCurve::EaseOut()
{
    EasingCurve c;
    c.points = {{0.0, 0.0}, {0.58, 1.0}};
    return c;
}

EasingCurve EasingCurve::EaseInOut()
{
    EasingCurve c;
    c.points = {{0.42, 0.0}, {0.58, 1.0}};
    return c;
}

//========================================================================================
//  De Casteljau Subdivision
//========================================================================================

static AIRealPoint Lerp(AIRealPoint a, AIRealPoint b, double t)
{
    AIRealPoint r;
    r.h = (AIReal)(a.h + (b.h - a.h) * t);
    r.v = (AIReal)(a.v + (b.v - a.v) * t);
    return r;
}

/** Split a cubic bezier at parameter t into two sub-beziers.
    Standard de Casteljau: 3 rounds of linear interpolation. */
static void SplitBezier(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                         double t,
                         AIRealPoint left[4], AIRealPoint right[4])
{
    // Level 1
    AIRealPoint q0 = Lerp(p0, p1, t);
    AIRealPoint q1 = Lerp(p1, p2, t);
    AIRealPoint q2 = Lerp(p2, p3, t);
    // Level 2
    AIRealPoint r0 = Lerp(q0, q1, t);
    AIRealPoint r1 = Lerp(q1, q2, t);
    // Level 3 (split point)
    AIRealPoint s = Lerp(r0, r1, t);

    left[0] = p0;
    left[1] = q0;
    left[2] = r0;
    left[3] = s;

    right[0] = s;
    right[1] = r1;
    right[2] = q2;
    right[3] = p3;
}

//========================================================================================
//  Arc-Length Computation
//========================================================================================

static double PointDist(AIRealPoint a, AIRealPoint b)
{
    double dx = (double)(b.h - a.h);
    double dy = (double)(b.v - a.v);
    return std::sqrt(dx * dx + dy * dy);
}

/** Recursively compute arc length of a cubic bezier segment.
    Uses chord-vs-control-polygon comparison. Tolerance: 0.5 pts. Max depth: 10. */
static double BezierArcLength(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                               int depth)
{
    static const double kTolerance = 0.5;
    static const int kMaxDepth = 10;

    double chord = PointDist(p0, p3);
    double polyLen = PointDist(p0, p1) + PointDist(p1, p2) + PointDist(p2, p3);

    if (depth >= kMaxDepth || (polyLen - chord) < kTolerance) {
        // Close enough — return average of chord and polygon length
        return (chord + polyLen) * 0.5;
    }

    AIRealPoint left[4], right[4];
    SplitBezier(p0, p1, p2, p3, 0.5, left, right);

    return BezierArcLength(left[0], left[1], left[2], left[3], depth + 1)
         + BezierArcLength(right[0], right[1], right[2], right[3], depth + 1);
}

/** Compute cumulative arc lengths for each bezier piece of a path.
    For an open path with N segments, there are N-1 pieces.
    For a closed path with N segments, there are N pieces (last wraps to first). */
static std::vector<double> ComputeArcLengths(const AIPathSegment* segs, int segCount, bool closed)
{
    int numPieces = closed ? segCount : (segCount - 1);
    std::vector<double> lengths(numPieces);

    for (int i = 0; i < numPieces; i++) {
        int j = (i + 1) % segCount;  // next segment index (wraps for closed)
        AIRealPoint p0 = segs[i].p;
        AIRealPoint p1 = segs[i].out;
        AIRealPoint p2 = segs[j].in;
        AIRealPoint p3 = segs[j].p;
        lengths[i] = BezierArcLength(p0, p1, p2, p3, 0);
    }
    return lengths;
}

//========================================================================================
//  Path Resampling
//========================================================================================

/** Evaluate a point on a cubic bezier at parameter t. */
static AIRealPoint BezierEval(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3, double t)
{
    double omt = 1.0 - t;
    double omt2 = omt * omt;
    double t2 = t * t;
    AIRealPoint r;
    r.h = (AIReal)(omt2 * omt * p0.h + 3.0 * omt2 * t * p1.h + 3.0 * omt * t2 * p2.h + t2 * t * p3.h);
    r.v = (AIReal)(omt2 * omt * p0.v + 3.0 * omt2 * t * p1.v + 3.0 * omt * t2 * p2.v + t2 * t * p3.v);
    return r;
}

/** Find the bezier parameter t at which a given arc-length distance occurs
    along a bezier segment, using bisection.
    @param p0,p1,p2,p3  Bezier control points
    @param targetLen     Desired arc length from p0
    @param totalLen      Total arc length of this segment
    @return Parameter t in [0,1] */
static double FindTForArcLength(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                                 double targetLen, double totalLen)
{
    if (targetLen <= 0.0) return 0.0;
    if (targetLen >= totalLen) return 1.0;

    // Bisection: find t such that arcLength(0..t) ≈ targetLen
    double lo = 0.0, hi = 1.0;
    for (int iter = 0; iter < 20; iter++) {
        double mid = (lo + hi) * 0.5;
        // Split at mid, measure left half
        AIRealPoint left[4], right[4];
        SplitBezier(p0, p1, p2, p3, mid, left, right);
        double leftLen = BezierArcLength(left[0], left[1], left[2], left[3], 0);
        if (leftLen < targetLen)
            lo = mid;
        else
            hi = mid;
    }
    return (lo + hi) * 0.5;
}

/** Resample a path to have exactly targetCount segments.
    New points are placed at even arc-length intervals ON the existing bezier curves.
    The path shape does NOT change — only new control points are inserted. */
static std::vector<AIPathSegment> ResamplePath(const AIPathSegment* segs, int segCount,
                                                bool closed, int targetCount)
{
    if (segCount <= 0 || targetCount <= 0) return {};

    // If already the right count, just copy
    if (segCount == targetCount) {
        return std::vector<AIPathSegment>(segs, segs + segCount);
    }

    // Compute per-piece arc lengths
    std::vector<double> pieceLengths = ComputeArcLengths(segs, segCount, closed);
    int numPieces = (int)pieceLengths.size();
    if (numPieces == 0) return std::vector<AIPathSegment>(segs, segs + segCount);

    // Compute cumulative lengths
    std::vector<double> cumLen(numPieces);
    cumLen[0] = pieceLengths[0];
    for (int i = 1; i < numPieces; i++)
        cumLen[i] = cumLen[i - 1] + pieceLengths[i];
    double totalLen = cumLen[numPieces - 1];
    if (totalLen < 1e-6) return std::vector<AIPathSegment>(segs, segs + segCount);

    // Number of output pieces
    int outPieces = closed ? targetCount : (targetCount - 1);
    std::vector<AIPathSegment> result(targetCount);

    // First point is always the original first point
    result[0] = segs[0];

    for (int i = 1; i < targetCount; i++) {
        double desiredLen = ((double)i / (double)outPieces) * totalLen;

        // Find which source piece contains this arc-length position
        int pieceIdx = 0;
        while (pieceIdx < numPieces - 1 && cumLen[pieceIdx] < desiredLen)
            pieceIdx++;

        double prevCum = (pieceIdx > 0) ? cumLen[pieceIdx - 1] : 0.0;
        double withinLen = desiredLen - prevCum;

        int srcA = pieceIdx;
        int srcB = (pieceIdx + 1) % segCount;

        AIRealPoint p0 = segs[srcA].p;
        AIRealPoint p1 = segs[srcA].out;
        AIRealPoint p2 = segs[srcB].in;
        AIRealPoint p3 = segs[srcB].p;

        double t = FindTForArcLength(p0, p1, p2, p3, withinLen, pieceLengths[pieceIdx]);

        // Split the bezier at t to get exact point and handles
        AIRealPoint left[4], right[4];
        SplitBezier(p0, p1, p2, p3, t, left, right);

        // The split point becomes the new anchor
        result[i].p = left[3];      // = right[0], the split point
        result[i].in = left[2];     // incoming handle from the left half
        result[i].out = right[1];   // outgoing handle into the right half
        result[i].corner = false;
    }

    // Fix up the first segment's out-handle and ensure continuity:
    // After resampling, the first segment's out handle should point toward the
    // first resampled position. We compute it from the first source piece split.
    if (targetCount >= 2 && numPieces > 0) {
        double firstDesired = (1.0 / (double)outPieces) * totalLen;
        // The first piece always starts from piece 0
        AIRealPoint p0 = segs[0].p;
        AIRealPoint p1 = segs[0].out;
        int nextIdx = 1 % segCount;
        AIRealPoint p2 = segs[nextIdx].in;
        AIRealPoint p3 = segs[nextIdx].p;

        double t0 = FindTForArcLength(p0, p1, p2, p3, firstDesired, pieceLengths[0]);
        if (t0 > 0.0 && t0 <= 1.0) {
            AIRealPoint left[4], right[4];
            SplitBezier(p0, p1, p2, p3, t0, left, right);
            result[0].out = left[1];  // outgoing handle from first split
        }
    }

    // Preserve the in-handle of the first segment
    result[0].in = segs[0].in;
    result[0].corner = segs[0].corner;

    fprintf(stderr, "[IllTool Blend] ResamplePath: %d segs -> %d segs (totalLen=%.1f)\n",
            segCount, targetCount, totalLen);

    return result;
}

//========================================================================================
//  Starting Point Alignment (Closed Paths)
//========================================================================================

/** Find the rotation offset that minimizes total squared distance between
    corresponding points. Tests all rotations, picks the best.
    @return Best rotation offset for B (0 to segCount-1). */
static int FindBestRotation(const AIPathSegment* segsA, const AIPathSegment* segsB, int segCount)
{
    if (segCount <= 1) return 0;

    double bestDist = 1e30;
    int bestRot = 0;

    for (int r = 0; r < segCount; r++) {
        double sum = 0.0;
        for (int i = 0; i < segCount; i++) {
            int j = (i + r) % segCount;
            double dx = (double)(segsA[i].p.h - segsB[j].p.h);
            double dy = (double)(segsA[i].p.v - segsB[j].p.v);
            sum += dx * dx + dy * dy;
        }
        if (sum < bestDist) {
            bestDist = sum;
            bestRot = r;
        }
    }
    return bestRot;
}

/** Apply a rotation to a segment array: shift indices by offset.
    Returns a new array with segments rotated. */
static std::vector<AIPathSegment> RotateSegments(const std::vector<AIPathSegment>& segs, int offset)
{
    int n = (int)segs.size();
    if (n <= 1 || offset == 0) return segs;
    offset = ((offset % n) + n) % n;

    std::vector<AIPathSegment> result(n);
    for (int i = 0; i < n; i++) {
        result[i] = segs[(i + offset) % n];
    }
    return result;
}

//========================================================================================
//  Blend Execution
//========================================================================================

int IllToolPlugin::ExecuteBlend(AIArtHandle pathA, AIArtHandle pathB,
                                 int steps, int easingPreset)
{
    if (!pathA || !pathB || !sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool Blend] ExecuteBlend: null path or missing suite\n");
        return 0;
    }
    if (steps < 1) steps = 1;
    if (steps > 20) steps = 20;

    fprintf(stderr, "[IllTool Blend] ExecuteBlend: steps=%d, easing=%d\n", steps, easingPreset);

    // Build easing curve from preset
    EasingCurve easing;
    switch (easingPreset) {
        case 1:  easing = EasingCurve::EaseIn();    break;
        case 2:  easing = EasingCurve::EaseOut();   break;
        case 3:  easing = EasingCurve::EaseInOut(); break;
        default: easing = EasingCurve::Linear();    break;
    }

    // --- Read segments from both paths ---
    ai::int16 countA = 0, countB = 0;
    ASErr err = sAIPath->GetPathSegmentCount(pathA, &countA);
    if (err != kNoErr || countA < 2) {
        fprintf(stderr, "[IllTool Blend] Path A: segment count failed or < 2\n");
        return 0;
    }
    err = sAIPath->GetPathSegmentCount(pathB, &countB);
    if (err != kNoErr || countB < 2) {
        fprintf(stderr, "[IllTool Blend] Path B: segment count failed or < 2\n");
        return 0;
    }

    std::vector<AIPathSegment> segsA(countA), segsB(countB);
    sAIPath->GetPathSegments(pathA, 0, countA, segsA.data());
    sAIPath->GetPathSegments(pathB, 0, countB, segsB.data());

    AIBoolean closedA = false, closedB = false;
    sAIPath->GetPathClosed(pathA, &closedA);
    sAIPath->GetPathClosed(pathB, &closedB);
    bool isClosed = (closedA && closedB);  // only align start points if both closed

    fprintf(stderr, "[IllTool Blend] Path A: %d segs (closed=%d), Path B: %d segs (closed=%d)\n",
            (int)countA, (int)closedA, (int)countB, (int)closedB);

    // --- Determine target count and resample ---
    int targetCount = std::max((int)countA, (int)countB);
    std::vector<AIPathSegment> resA = ResamplePath(segsA.data(), countA, closedA != 0, targetCount);
    std::vector<AIPathSegment> resB = ResamplePath(segsB.data(), countB, closedB != 0, targetCount);

    if ((int)resA.size() != targetCount || (int)resB.size() != targetCount) {
        fprintf(stderr, "[IllTool Blend] Resample failed: resA=%d resB=%d target=%d\n",
                (int)resA.size(), (int)resB.size(), targetCount);
        return 0;
    }

    // --- Align starting points for closed paths ---
    if (isClosed && targetCount > 1) {
        int bestRot = FindBestRotation(resA.data(), resB.data(), targetCount);
        if (bestRot != 0) {
            resB = RotateSegments(resB, bestRot);
            fprintf(stderr, "[IllTool Blend] Rotated B by %d positions for alignment\n", bestRot);
        }
    }

    // --- Read style from path A for copying to intermediates ---
    AIPathStyle style;
    AIBoolean hasAdvFill = false;
    err = sAIPathStyle->GetPathStyle(pathA, &style, &hasAdvFill);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool Blend] GetPathStyle failed: %d\n", (int)err);
        // Continue with default style
        style.Init();
    }

    // --- Push undo frame ---
    fUndoStack.PushFrame();

    // --- Generate intermediate paths ---
    int created = 0;
    for (int step = 1; step <= steps; step++) {
        double rawT = (double)step / (double)(steps + 1);
        double t = easing.Evaluate(rawT);

        // Interpolate all segments
        std::vector<AIPathSegment> interp(targetCount);
        for (int j = 0; j < targetCount; j++) {
            const AIPathSegment& a = resA[j];
            const AIPathSegment& b = resB[j];

            interp[j].p.h   = (AIReal)(a.p.h   + (b.p.h   - a.p.h)   * t);
            interp[j].p.v   = (AIReal)(a.p.v   + (b.p.v   - a.p.v)   * t);
            interp[j].in.h  = (AIReal)(a.in.h  + (b.in.h  - a.in.h)  * t);
            interp[j].in.v  = (AIReal)(a.in.v  + (b.in.v  - a.in.v)  * t);
            interp[j].out.h = (AIReal)(a.out.h + (b.out.h - a.out.h) * t);
            interp[j].out.v = (AIReal)(a.out.v + (b.out.v - a.out.v) * t);
            interp[j].corner = a.corner;  // preserve corner flag from A
        }

        // Create new path art above pathA
        AIArtHandle newPath = nullptr;
        err = sAIArt->NewArt(kPathArt, kPlaceAbove, pathA, &newPath);
        if (err != kNoErr || !newPath) {
            fprintf(stderr, "[IllTool Blend] NewArt failed at step %d: err=%d\n", step, (int)err);
            continue;
        }

        // Set segment count, write segments
        err = sAIPath->SetPathSegmentCount(newPath, (ai::int16)targetCount);
        if (err != kNoErr) {
            fprintf(stderr, "[IllTool Blend] SetPathSegmentCount failed: %d\n", (int)err);
            sAIArt->DisposeArt(newPath);
            continue;
        }
        err = sAIPath->SetPathSegments(newPath, 0, (ai::int16)targetCount, interp.data());
        if (err != kNoErr) {
            fprintf(stderr, "[IllTool Blend] SetPathSegments failed: %d\n", (int)err);
            sAIArt->DisposeArt(newPath);
            continue;
        }

        // Set closed state (match source paths — both closed = closed, otherwise open)
        sAIPath->SetPathClosed(newPath, isClosed ? true : false);

        // Copy stroke/fill style from path A
        sAIPathStyle->SetPathStyle(newPath, &style);

        // Snapshot for undo
        fUndoStack.SnapshotPath(newPath);

        created++;
        fprintf(stderr, "[IllTool Blend] Step %d/%d: t=%.3f (raw=%.3f), created art %p\n",
                step, steps, t, rawT, (void*)newPath);
    }

    fprintf(stderr, "[IllTool Blend] ExecuteBlend complete: %d paths created\n", created);
    return created;
}
// End IllToolBlend.cpp
