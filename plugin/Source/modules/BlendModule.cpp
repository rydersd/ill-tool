//========================================================================================
//  BlendModule — Blend Harmonization (Stage 11)
//  Arc-length parameterization, de Casteljau subdivision, path resampling,
//  starting-point alignment, and interpolated blend execution.
//
//  Ported from IllToolBlend.cpp into module pattern.
//========================================================================================

#include "BlendModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

//========================================================================================
//  Easing Curve
//========================================================================================

struct EasingCurve {
    struct ControlPoint {
        double x, y;  // both in [0,1]
    };
    std::vector<ControlPoint> points;  // sorted by x

    /** Evaluate y at given x. */
    double Evaluate(double t) const;

    static EasingCurve Linear();
    static EasingCurve EaseIn();
    static EasingCurve EaseOut();
    static EasingCurve EaseInOut();
};

// --- Cubic bezier solver for 2-point easing ---

static double CubicBezier1D(double t, double p1, double p2)
{
    double omt = 1.0 - t;
    return 3.0 * omt * omt * t * p1 + 3.0 * omt * t * t * p2 + t * t * t;
}

static double CubicBezier1DDeriv(double t, double p1, double p2)
{
    double omt = 1.0 - t;
    return 3.0 * omt * omt * p1 + 6.0 * omt * t * (p2 - p1) + 3.0 * t * t * (1.0 - p2);
}

double EasingCurve::Evaluate(double t) const
{
    if (t <= 0.0) return 0.0;
    if (t >= 1.0) return 1.0;

    if (points.empty()) {
        return t;  // linear
    }

    if (points.size() == 2) {
        double p1x = points[0].x, p1y = points[0].y;
        double p2x = points[1].x, p2y = points[1].y;

        // Newton-Raphson to find u where CubicBezier1D(u, p1x, p2x) = t
        double u = t;
        for (int i = 0; i < 8; i++) {
            double x = CubicBezier1D(u, p1x, p2x) - t;
            double dx = CubicBezier1DDeriv(u, p1x, p2x);
            if (std::fabs(dx) < 1e-12) break;
            u -= x / dx;
            u = std::max(0.0, std::min(1.0, u));
        }
        // Bisection fallback
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

    // Piecewise linear
    std::vector<ControlPoint> pts;
    pts.push_back({0.0, 0.0});
    for (auto& cp : points) pts.push_back(cp);
    pts.push_back({1.0, 1.0});

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

EasingCurve EasingCurve::Linear()   { EasingCurve c; return c; }
EasingCurve EasingCurve::EaseIn()   { EasingCurve c; c.points = {{0.42, 0.0}, {1.0, 1.0}}; return c; }
EasingCurve EasingCurve::EaseOut()  { EasingCurve c; c.points = {{0.0, 0.0}, {0.58, 1.0}}; return c; }
EasingCurve EasingCurve::EaseInOut(){ EasingCurve c; c.points = {{0.42, 0.0}, {0.58, 1.0}}; return c; }

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

static void SplitBezier(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                         double t,
                         AIRealPoint left[4], AIRealPoint right[4])
{
    AIRealPoint q0 = Lerp(p0, p1, t);
    AIRealPoint q1 = Lerp(p1, p2, t);
    AIRealPoint q2 = Lerp(p2, p3, t);
    AIRealPoint r0 = Lerp(q0, q1, t);
    AIRealPoint r1 = Lerp(q1, q2, t);
    AIRealPoint s  = Lerp(r0, r1, t);

    left[0] = p0;  left[1] = q0;  left[2] = r0;  left[3] = s;
    right[0] = s;  right[1] = r1; right[2] = q2; right[3] = p3;
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

static double BezierArcLength(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                               int depth)
{
    static const double kTolerance = 0.5;
    static const int kMaxDepth = 10;

    double chord = PointDist(p0, p3);
    double polyLen = PointDist(p0, p1) + PointDist(p1, p2) + PointDist(p2, p3);

    if (depth >= kMaxDepth || (polyLen - chord) < kTolerance) {
        return (chord + polyLen) * 0.5;
    }

    AIRealPoint left[4], right[4];
    SplitBezier(p0, p1, p2, p3, 0.5, left, right);

    return BezierArcLength(left[0], left[1], left[2], left[3], depth + 1)
         + BezierArcLength(right[0], right[1], right[2], right[3], depth + 1);
}

static std::vector<double> ComputeArcLengths(const AIPathSegment* segs, int segCount, bool closed)
{
    int numPieces = closed ? segCount : (segCount - 1);
    std::vector<double> lengths(numPieces);

    for (int i = 0; i < numPieces; i++) {
        int j = (i + 1) % segCount;
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

static double FindTForArcLength(AIRealPoint p0, AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                                 double targetLen, double totalLen)
{
    if (targetLen <= 0.0) return 0.0;
    if (targetLen >= totalLen) return 1.0;

    double lo = 0.0, hi = 1.0;
    for (int iter = 0; iter < 20; iter++) {
        double mid = (lo + hi) * 0.5;
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

static std::vector<AIPathSegment> ResamplePath(const AIPathSegment* segs, int segCount,
                                                bool closed, int targetCount)
{
    if (segCount <= 0 || targetCount <= 0) return {};

    if (segCount == targetCount) {
        return std::vector<AIPathSegment>(segs, segs + segCount);
    }

    std::vector<double> pieceLengths = ComputeArcLengths(segs, segCount, closed);
    int numPieces = (int)pieceLengths.size();
    if (numPieces == 0) return std::vector<AIPathSegment>(segs, segs + segCount);

    std::vector<double> cumLen(numPieces);
    cumLen[0] = pieceLengths[0];
    for (int i = 1; i < numPieces; i++)
        cumLen[i] = cumLen[i - 1] + pieceLengths[i];
    double totalLen = cumLen[numPieces - 1];
    if (totalLen < 1e-6) return std::vector<AIPathSegment>(segs, segs + segCount);

    int outPieces = closed ? targetCount : (targetCount - 1);
    std::vector<AIPathSegment> result(targetCount);

    result[0] = segs[0];

    for (int i = 1; i < targetCount; i++) {
        double desiredLen = ((double)i / (double)outPieces) * totalLen;

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

        AIRealPoint left[4], right[4];
        SplitBezier(p0, p1, p2, p3, t, left, right);

        result[i].p = left[3];
        result[i].in = left[2];
        result[i].out = right[1];
        result[i].corner = false;
    }

    // Fix up the first segment's out-handle
    if (targetCount >= 2 && numPieces > 0) {
        double firstDesired = (1.0 / (double)outPieces) * totalLen;
        AIRealPoint p0 = segs[0].p;
        AIRealPoint p1 = segs[0].out;
        int nextIdx = 1 % segCount;
        AIRealPoint p2 = segs[nextIdx].in;
        AIRealPoint p3 = segs[nextIdx].p;

        double t0 = FindTForArcLength(p0, p1, p2, p3, firstDesired, pieceLengths[0]);
        if (t0 > 0.0 && t0 <= 1.0) {
            AIRealPoint left[4], right[4];
            SplitBezier(p0, p1, p2, p3, t0, left, right);
            result[0].out = left[1];
        }
    }

    result[0].in = segs[0].in;
    result[0].corner = segs[0].corner;

    fprintf(stderr, "[BlendModule] ResamplePath: %d segs -> %d segs (totalLen=%.1f)\n",
            segCount, targetCount, totalLen);

    return result;
}

//========================================================================================
//  Starting Point Alignment (Closed Paths)
//========================================================================================

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
//  Blend Core — shared interpolation logic
//========================================================================================

static int GenerateIntermediates(
    const std::vector<AIPathSegment>& resA,
    const std::vector<AIPathSegment>& resB,
    int targetCount, bool isClosed, int steps,
    const EasingCurve& easing,
    const AIPathStyle& style,
    AIArtHandle placeRelTo,
    std::vector<AIArtHandle>& outHandles)
{
    int created = 0;
    for (int step = 1; step <= steps; step++) {
        double rawT = (double)step / (double)(steps + 1);
        double t = easing.Evaluate(rawT);

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
            interp[j].corner = a.corner;
        }

        AIArtHandle newPath = nullptr;
        ASErr err = sAIArt->NewArt(kPathArt, kPlaceAbove, placeRelTo, &newPath);
        if (err != kNoErr || !newPath) {
            fprintf(stderr, "[BlendModule] NewArt failed at step %d: err=%d\n", step, (int)err);
            continue;
        }

        err = sAIPath->SetPathSegmentCount(newPath, (ai::int16)targetCount);
        if (err != kNoErr) {
            fprintf(stderr, "[BlendModule] SetPathSegmentCount failed: %d\n", (int)err);
            sAIArt->DisposeArt(newPath);
            continue;
        }
        err = sAIPath->SetPathSegments(newPath, 0, (ai::int16)targetCount, interp.data());
        if (err != kNoErr) {
            fprintf(stderr, "[BlendModule] SetPathSegments failed: %d\n", (int)err);
            sAIArt->DisposeArt(newPath);
            continue;
        }

        sAIPath->SetPathClosed(newPath, isClosed ? true : false);
        sAIPathStyle->SetPathStyle(newPath, &style);

        outHandles.push_back(newPath);
        created++;
        fprintf(stderr, "[BlendModule] Step %d/%d: t=%.3f (raw=%.3f), art=%p\n",
                step, steps, t, rawT, (void*)newPath);
    }
    return created;
}

/** Harmonize two paths: read segments, resample to matching count, align starts. */
static bool HarmonizePaths(AIArtHandle pathA, AIArtHandle pathB,
                            std::vector<AIPathSegment>& resA,
                            std::vector<AIPathSegment>& resB,
                            int& targetCount, bool& isClosed)
{
    ai::int16 countA = 0, countB = 0;
    ASErr err = sAIPath->GetPathSegmentCount(pathA, &countA);
    if (err != kNoErr || countA < 2) {
        fprintf(stderr, "[BlendModule] Path A: segment count failed or < 2\n");
        return false;
    }
    err = sAIPath->GetPathSegmentCount(pathB, &countB);
    if (err != kNoErr || countB < 2) {
        fprintf(stderr, "[BlendModule] Path B: segment count failed or < 2\n");
        return false;
    }

    std::vector<AIPathSegment> segsA(countA), segsB(countB);
    sAIPath->GetPathSegments(pathA, 0, countA, segsA.data());
    sAIPath->GetPathSegments(pathB, 0, countB, segsB.data());

    AIBoolean closedA = false, closedB = false;
    sAIPath->GetPathClosed(pathA, &closedA);
    sAIPath->GetPathClosed(pathB, &closedB);
    isClosed = (closedA && closedB);

    fprintf(stderr, "[BlendModule] Path A: %d segs (closed=%d), Path B: %d segs (closed=%d)\n",
            (int)countA, (int)closedA, (int)countB, (int)closedB);

    targetCount = std::max((int)countA, (int)countB);
    resA = ResamplePath(segsA.data(), countA, closedA != 0, targetCount);
    resB = ResamplePath(segsB.data(), countB, closedB != 0, targetCount);

    if ((int)resA.size() != targetCount || (int)resB.size() != targetCount) {
        fprintf(stderr, "[BlendModule] Resample failed: resA=%d resB=%d target=%d\n",
                (int)resA.size(), (int)resB.size(), targetCount);
        return false;
    }

    if (isClosed && targetCount > 1) {
        int bestRot = FindBestRotation(resA.data(), resB.data(), targetCount);
        if (bestRot != 0) {
            resB = RotateSegments(resB, bestRot);
            fprintf(stderr, "[BlendModule] Rotated B by %d positions for alignment\n", bestRot);
        }
    }
    return true;
}

//========================================================================================
//  Dictionary persistence helpers
//========================================================================================

static const char* kBlendKeyMarker   = "IllToolBlendGroup";
static const char* kBlendKeySteps    = "IllToolBlendSteps";
static const char* kBlendKeyEasing   = "IllToolBlendEasing";

static void StoreBlendParams(AIArtHandle groupArt, int steps, int easingPreset)
{
    if (!sAIDictionary || !sAIArt) return;

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(groupArt, &dict);
    if (err != kNoErr || !dict) {
        fprintf(stderr, "[BlendModule] GetDictionary failed: %d\n", (int)err);
        return;
    }

    AIDictKey markerKey = sAIDictionary->Key(kBlendKeyMarker);
    AIDictKey stepsKey  = sAIDictionary->Key(kBlendKeySteps);
    AIDictKey easingKey = sAIDictionary->Key(kBlendKeyEasing);

    sAIDictionary->SetBooleanEntry(dict, markerKey, true);
    sAIDictionary->SetIntegerEntry(dict, stepsKey, (ai::int32)steps);
    sAIDictionary->SetIntegerEntry(dict, easingKey, (ai::int32)easingPreset);

    sAIDictionary->Release(dict);
    fprintf(stderr, "[BlendModule] Stored params: steps=%d, easing=%d on group %p\n",
            steps, easingPreset, (void*)groupArt);
}

static bool ReadBlendParams(AIArtHandle groupArt, int& steps, int& easingPreset)
{
    if (!sAIDictionary || !sAIArt) return false;

    AIBoolean hasDictionary = sAIArt->HasDictionary(groupArt);
    if (!hasDictionary) return false;

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(groupArt, &dict);
    if (err != kNoErr || !dict) return false;

    AIDictKey markerKey = sAIDictionary->Key(kBlendKeyMarker);
    AIBoolean isBlend = false;
    err = sAIDictionary->GetBooleanEntry(dict, markerKey, &isBlend);
    if (err != kNoErr || !isBlend) {
        sAIDictionary->Release(dict);
        return false;
    }

    AIDictKey stepsKey  = sAIDictionary->Key(kBlendKeySteps);
    AIDictKey easingKey = sAIDictionary->Key(kBlendKeyEasing);
    ai::int32 s = 5, e = 0;
    sAIDictionary->GetIntegerEntry(dict, stepsKey, &s);
    sAIDictionary->GetIntegerEntry(dict, easingKey, &e);
    steps = (int)s;
    easingPreset = (int)e;

    sAIDictionary->Release(dict);
    return true;
}

//========================================================================================
//  Build easing curve from preset + bridge state
//========================================================================================

static EasingCurve BuildEasingCurve(int easingPreset)
{
    EasingCurve easing;
    switch (easingPreset) {
        case 1:  easing = EasingCurve::EaseIn();    break;
        case 2:  easing = EasingCurve::EaseOut();   break;
        case 3:  easing = EasingCurve::EaseInOut(); break;
        case 4: {
            double pts[20];
            int count = BridgeGetCustomEasingPoints(pts, 10);
            if (count >= 2) {
                for (int ci = 0; ci < count; ci++)
                    easing.points.push_back({pts[ci*2], pts[ci*2+1]});
            } else { easing = EasingCurve::Linear(); }
            break;
        }
        default: easing = EasingCurve::Linear();    break;
    }
    return easing;
}

//========================================================================================
//  HandleOp — operation dispatch
//========================================================================================

bool BlendModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::BlendPickA: {
            BridgeSetBlendPickMode(1);
            fBlendPathA = nullptr;
            BridgeSetBlendPathASet(false);
            fprintf(stderr, "[BlendModule] Entered Pick A mode\n");
            return true;
        }
        case OpType::BlendPickB: {
            BridgeSetBlendPickMode(2);
            fBlendPathB = nullptr;
            BridgeSetBlendPathBSet(false);
            fprintf(stderr, "[BlendModule] Entered Pick B mode\n");
            return true;
        }
        case OpType::BlendSetSteps: {
            int steps = op.intParam;
            if (steps < 1) steps = 1;
            if (steps > 20) steps = 20;
            BridgeSetBlendSteps(steps);
            fprintf(stderr, "[BlendModule] Set steps: %d\n", steps);
            return true;
        }
        case OpType::BlendSetEasing: {
            int preset = op.intParam;
            if (preset < 0) preset = 0;
            if (preset > 4) preset = 4;
            BridgeSetBlendEasing(preset);
            fprintf(stderr, "[BlendModule] Set easing: %d\n", preset);
            return true;
        }
        case OpType::BlendExecute: {
            int steps = BridgeGetBlendSteps();
            int easing = BridgeGetBlendEasing();

            if (fBlendPathA && fBlendPathB) {
                // Fresh blend from picked paths
                int result = ExecuteBlend(fBlendPathA, fBlendPathB, steps, easing);
                fprintf(stderr, "[BlendModule] ExecuteBlend result: %d intermediates\n", result);
            } else {
                // Try re-blend: check if selection is inside a blend group
                AIMatchingArtSpec spec;
                spec.type = kAnyArt;
                spec.whichAttr = kArtSelected;
                spec.attr = kArtSelected;
                AIArtHandle** matches = nullptr;
                ai::int32 numMatches = 0;
                ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
                if (err == kNoErr && numMatches > 0 && matches) {
                    AIArtHandle blendGroup = FindBlendGroupForArt((*matches)[0]);
                    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                    if (blendGroup) {
                        int result = ReblendGroup(blendGroup, steps, easing);
                        fprintf(stderr, "[BlendModule] ReblendGroup result: %d intermediates\n", result);
                    } else {
                        fprintf(stderr, "[BlendModule] BlendExecute: no paths picked and selection is not in a blend group\n");
                    }
                } else {
                    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                    fprintf(stderr, "[BlendModule] BlendExecute: no paths picked and no selection\n");
                }
            }
            return true;
        }
        default:
            return false;
    }
}

//========================================================================================
//  Mouse handling — Pick A/B mode
//========================================================================================

bool BlendModule::HandleMouseDown(AIToolMessage* msg)
{
    int pickMode = BridgeGetBlendPickMode();
    if (pickMode == 0) return false;  // not in pick mode

    if (!msg || !sAIHitTest || !sAIArt) return false;

    // Hit-test for a path at the click point
    AIHitRef hitRef = nullptr;
    ASErr err = sAIHitTest->HitTest(nullptr, &msg->cursor, kAllHitRequest, &hitRef);
    if (err != kNoErr || !hitRef) {
        fprintf(stderr, "[BlendModule] Pick mode %d: no hit\n", pickMode);
        return true;  // consume the click even if no hit
    }

    AIArtHandle hitArt = sAIHitTest->GetArt(hitRef);
    sAIHitTest->Release(hitRef);

    if (!hitArt) {
        fprintf(stderr, "[BlendModule] Pick mode %d: hit but no art\n", pickMode);
        return true;
    }

    // Verify it's a path
    short artType = 0;
    sAIArt->GetArtType(hitArt, &artType);
    if (artType != kPathArt) {
        fprintf(stderr, "[BlendModule] Pick mode %d: hit art is not a path (type=%d)\n",
                pickMode, artType);
        return true;
    }

    if (pickMode == 1) {
        fBlendPathA = hitArt;
        BridgeSetBlendPathASet(true);
        BridgeSetBlendPickMode(0);
        fprintf(stderr, "[BlendModule] Picked path A: %p\n", (void*)hitArt);
    } else if (pickMode == 2) {
        fBlendPathB = hitArt;
        BridgeSetBlendPathBSet(true);
        BridgeSetBlendPickMode(0);
        fprintf(stderr, "[BlendModule] Picked path B: %p\n", (void*)hitArt);
    }

    return true;
}

//========================================================================================
//  Notifications
//========================================================================================

void BlendModule::OnSelectionChanged()
{
    // Nothing needed — blend state is explicit (pick mode)
}

void BlendModule::OnDocumentChanged()
{
    fBlendPathA = nullptr;
    fBlendPathB = nullptr;
    fBlendStates.clear();
    fBlendGroupCounter = 0;
    fUndoStack.Clear();
    BridgeSetBlendPathASet(false);
    BridgeSetBlendPathBSet(false);
    BridgeSetBlendPickMode(0);
}

//========================================================================================
//  Undo
//========================================================================================

bool BlendModule::CanUndo()
{
    return fUndoStack.CanUndo();
}

void BlendModule::Undo()
{
    int restored = fUndoStack.Undo();
    fprintf(stderr, "[BlendModule] Undo: restored %d paths\n", restored);
}

//========================================================================================
//  ExecuteBlend
//========================================================================================

int BlendModule::ExecuteBlend(AIArtHandle pathA, AIArtHandle pathB,
                               int steps, int easingPreset)
{
    if (!pathA || !pathB || !sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[BlendModule] ExecuteBlend: null path or missing suite\n");
        return 0;
    }
    if (steps < 1) steps = 1;
    if (steps > 20) steps = 20;

    fprintf(stderr, "[BlendModule] ExecuteBlend: steps=%d, easing=%d\n", steps, easingPreset);

    EasingCurve easing = BuildEasingCurve(easingPreset);

    // Harmonize paths
    std::vector<AIPathSegment> resA, resB;
    int targetCount = 0;
    bool isClosed = false;
    if (!HarmonizePaths(pathA, pathB, resA, resB, targetCount, isClosed))
        return 0;

    // Read style from path A
    AIPathStyle style;
    AIBoolean hasAdvFill = false;
    ASErr err = sAIPathStyle->GetPathStyle(pathA, &style, &hasAdvFill);
    if (err != kNoErr) {
        fprintf(stderr, "[BlendModule] GetPathStyle failed: %d\n", (int)err);
        style.Init();
    }

    // Push undo frame
    fUndoStack.PushFrame();

    // Create blend group
    AIArtHandle groupArt = nullptr;
    err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
    if (err != kNoErr || !groupArt) {
        fprintf(stderr, "[BlendModule] NewArt(kGroupArt) failed: %d\n", (int)err);
        return 0;
    }

    fBlendGroupCounter++;
    char groupName[64];
    snprintf(groupName, sizeof(groupName), "Blend Group %d", fBlendGroupCounter);
    ai::UnicodeString uName(groupName);
    sAIArt->SetArtName(groupArt, uName);
    fprintf(stderr, "[BlendModule] Created group '%s' (%p)\n", groupName, (void*)groupArt);

    // Move source paths into the group
    AIArtHandle movedA = nullptr, movedB = nullptr;
    err = sAIArt->DuplicateArt(pathA, kPlaceInsideOnTop, groupArt, &movedA);
    if (err != kNoErr || !movedA) {
        fprintf(stderr, "[BlendModule] DuplicateArt(A) failed: %d\n", (int)err);
        sAIArt->DisposeArt(groupArt);
        return 0;
    }
    err = sAIArt->DuplicateArt(pathB, kPlaceInsideOnTop, groupArt, &movedB);
    if (err != kNoErr || !movedB) {
        fprintf(stderr, "[BlendModule] DuplicateArt(B) failed: %d\n", (int)err);
        sAIArt->DisposeArt(groupArt);
        return 0;
    }

    // Generate intermediates inside the group
    std::vector<AIArtHandle> intermediates;
    int created = GenerateIntermediates(resA, resB, targetCount, isClosed, steps,
                                         easing, style, movedA, intermediates);

    // Dispose original paths (they're now duplicated in the group)
    sAIArt->DisposeArt(pathA);
    sAIArt->DisposeArt(pathB);

    // Clear stale handles
    fBlendPathA = nullptr;
    fBlendPathB = nullptr;
    BridgeSetBlendPathASet(false);
    BridgeSetBlendPathBSet(false);

    // Store blend parameters on the group art dictionary
    StoreBlendParams(groupArt, steps, easingPreset);

    // Track state for fast re-blend
    BlendState state;
    state.groupArt = groupArt;
    state.pathA = movedA;
    state.pathB = movedB;
    state.steps = steps;
    state.easingPreset = easingPreset;
    state.intermediates = intermediates;
    fBlendStates.push_back(state);

    // Snapshot group for undo
    fUndoStack.SnapshotPath(groupArt);

    fprintf(stderr, "[BlendModule] ExecuteBlend complete: %d intermediates in '%s'\n",
            created, groupName);
    return created;
}

//========================================================================================
//  FindBlendState / FindBlendGroupForArt
//========================================================================================

BlendModule::BlendState* BlendModule::FindBlendState(AIArtHandle groupArt)
{
    for (auto& bs : fBlendStates) {
        if (bs.groupArt == groupArt) return &bs;
    }
    return nullptr;
}

AIArtHandle BlendModule::FindBlendGroupForArt(AIArtHandle art)
{
    if (!art || !sAIArt) return nullptr;

    int dummySteps, dummyEasing;
    if (ReadBlendParams(art, dummySteps, dummyEasing)) return art;

    AIArtHandle parent = nullptr;
    sAIArt->GetArtParent(art, &parent);
    while (parent) {
        if (ReadBlendParams(parent, dummySteps, dummyEasing)) return parent;
        AIArtHandle next = nullptr;
        sAIArt->GetArtParent(parent, &next);
        parent = next;
    }
    return nullptr;
}

//========================================================================================
//  ReblendGroup
//========================================================================================

int BlendModule::ReblendGroup(AIArtHandle groupArt, int steps, int easingPreset)
{
    if (!groupArt || !sAIArt || !sAIPath) {
        fprintf(stderr, "[BlendModule] ReblendGroup: null group or missing suite\n");
        return 0;
    }
    if (steps < 1) steps = 1;
    if (steps > 20) steps = 20;

    fprintf(stderr, "[BlendModule] ReblendGroup: group=%p, steps=%d, easing=%d\n",
            (void*)groupArt, steps, easingPreset);

    BlendState* state = FindBlendState(groupArt);

    AIArtHandle srcA = nullptr, srcB = nullptr;

    if (state) {
        srcA = state->pathA;
        srcB = state->pathB;
    } else {
        AIArtHandle child = nullptr;
        sAIArt->GetArtFirstChild(groupArt, &child);
        while (child) {
            ai::int16 artType = kUnknownArt;
            sAIArt->GetArtType(child, &artType);
            if (artType == kPathArt) {
                if (!srcA) srcA = child;
                else if (!srcB) { srcB = child; break; }
            }
            AIArtHandle next = nullptr;
            sAIArt->GetArtSibling(child, &next);
            child = next;
        }
    }

    if (!srcA || !srcB) {
        fprintf(stderr, "[BlendModule] ReblendGroup: could not find source paths in group\n");
        return 0;
    }

    // Delete old intermediates
    if (state) {
        for (AIArtHandle h : state->intermediates) {
            if (h) sAIArt->DisposeArt(h);
        }
        state->intermediates.clear();
    } else {
        std::vector<AIArtHandle> toDelete;
        AIArtHandle child = nullptr;
        sAIArt->GetArtFirstChild(groupArt, &child);
        while (child) {
            if (child != srcA && child != srcB) {
                ai::int16 artType = kUnknownArt;
                sAIArt->GetArtType(child, &artType);
                if (artType == kPathArt) toDelete.push_back(child);
            }
            AIArtHandle next = nullptr;
            sAIArt->GetArtSibling(child, &next);
            child = next;
        }
        for (AIArtHandle h : toDelete) sAIArt->DisposeArt(h);
        fprintf(stderr, "[BlendModule] Deleted %d orphaned intermediates\n", (int)toDelete.size());
    }

    EasingCurve easing = BuildEasingCurve(easingPreset);

    // Harmonize paths
    std::vector<AIPathSegment> resA, resB;
    int targetCount = 0;
    bool isClosed = false;
    if (!HarmonizePaths(srcA, srcB, resA, resB, targetCount, isClosed))
        return 0;

    // Read style from path A
    AIPathStyle pathStyle;
    AIBoolean hasAdvFill = false;
    sAIPathStyle->GetPathStyle(srcA, &pathStyle, &hasAdvFill);

    // Push undo frame
    fUndoStack.PushFrame();

    // Generate new intermediates
    std::vector<AIArtHandle> newIntermediates;
    int created = GenerateIntermediates(resA, resB, targetCount, isClosed, steps,
                                         easing, pathStyle, srcA, newIntermediates);

    // Update dictionary
    StoreBlendParams(groupArt, steps, easingPreset);

    // Update or create BlendState
    if (state) {
        state->steps = steps;
        state->easingPreset = easingPreset;
        state->intermediates = newIntermediates;
    } else {
        BlendState newState;
        newState.groupArt = groupArt;
        newState.pathA = srcA;
        newState.pathB = srcB;
        newState.steps = steps;
        newState.easingPreset = easingPreset;
        newState.intermediates = newIntermediates;
        fBlendStates.push_back(newState);
    }

    fprintf(stderr, "[BlendModule] ReblendGroup complete: %d new intermediates\n", created);
    return created;
}
