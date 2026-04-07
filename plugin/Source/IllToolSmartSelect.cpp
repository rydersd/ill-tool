//========================================================================================
//  IllTool — Smart Select (Boundary Signature Matching)
//  Extracted from IllToolPlugin.cpp for modularity.
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
//  Smart Select — Boundary Signature Matching (Stage 9)
//========================================================================================

/*
    ComputeSignature — compute a geometric fingerprint of a path that captures
    its length, curvature profile, direction, closure, and complexity.
    Used by Smart Select to find visually similar paths.
*/
IllToolPlugin::BoundarySignature IllToolPlugin::ComputeSignature(AIArtHandle path)
{
    BoundarySignature sig = {0.0, 0.0, 0.0, 0.0, false, 0};

    if (!path || !sAIPath) return sig;

    try {
        // Get segment count
        ai::int16 segCount = 0;
        ASErr err = sAIPath->GetPathSegmentCount(path, &segCount);
        if (err != kNoErr || segCount == 0) return sig;
        sig.segmentCount = segCount;

        // Check if path is closed
        AIBoolean closed = false;
        sAIPath->GetPathClosed(path, &closed);
        sig.isClosed = (closed != 0);

        // Read all segments
        std::vector<AIPathSegment> segs(segCount);
        err = sAIPath->GetPathSegments(path, 0, segCount, segs.data());
        if (err != kNoErr) return sig;

        // Compute total path length using MeasureSegments (accurate arc lengths).
        // Number of pieces: open path = segCount-1, closed path = segCount.
        ai::int16 numPieces = sig.isClosed
                            ? segCount
                            : (segCount > 1 ? (ai::int16)(segCount - 1) : (ai::int16)0);
        if (numPieces > 0) {
            std::vector<AIReal> pieceLengths(numPieces);
            std::vector<AIReal> accumLengths(numPieces);
            err = sAIPath->MeasureSegments(path, 0, numPieces,
                                           pieceLengths.data(), accumLengths.data());
            if (err == kNoErr) {
                sig.totalLength = (double)accumLengths[numPieces - 1]
                                + (double)pieceLengths[numPieces - 1];
            }
        }

        // Fallback: sum straight-line distances if MeasureSegments yielded zero
        if (sig.totalLength <= 0.0 && segCount > 1) {
            double lenSum = 0.0;
            for (ai::int16 i = 1; i < segCount; i++) {
                double dx = (double)(segs[i].p.h - segs[i-1].p.h);
                double dy = (double)(segs[i].p.v - segs[i-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            if (sig.isClosed && segCount >= 2) {
                double dx = (double)(segs[0].p.h - segs[segCount-1].p.h);
                double dy = (double)(segs[0].p.v - segs[segCount-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            sig.totalLength = lenSum;
        }

        // Average curvature: sum of absolute angle changes at interior anchors,
        // divided by total length (curvature density).
        if (segCount >= 3 && sig.totalLength > 0.0) {
            double angleChangeSum = 0.0;
            int numInteriorPts = sig.isClosed ? segCount : (segCount - 2);
            for (int ci = 0; ci < numInteriorPts; ci++) {
                int idx  = sig.isClosed ? ci : (ci + 1);
                int prev = (idx - 1 + segCount) % segCount;
                int next = (idx + 1) % segCount;

                double dx1 = (double)(segs[idx].p.h - segs[prev].p.h);
                double dy1 = (double)(segs[idx].p.v - segs[prev].p.v);
                double dx2 = (double)(segs[next].p.h - segs[idx].p.h);
                double dy2 = (double)(segs[next].p.v - segs[idx].p.v);

                double a1 = std::atan2(dy1, dx1);
                double a2 = std::atan2(dy2, dx2);
                double ad = a2 - a1;
                while (ad >  M_PI) ad -= 2.0 * M_PI;
                while (ad < -M_PI) ad += 2.0 * M_PI;
                angleChangeSum += std::fabs(ad);
            }
            sig.avgCurvature = angleChangeSum / sig.totalLength;
        }

        // Start and end tangent directions
        if (segCount >= 2) {
            double sx = (double)(segs[0].out.h - segs[0].p.h);
            double sy = (double)(segs[0].out.v - segs[0].p.v);
            if (std::fabs(sx) < 0.001 && std::fabs(sy) < 0.001) {
                sx = (double)(segs[1].p.h - segs[0].p.h);
                sy = (double)(segs[1].p.v - segs[0].p.v);
            }
            sig.startAngle = std::atan2(sy, sx);

            int last = segCount - 1;
            double ex = (double)(segs[last].p.h - segs[last].in.h);
            double ey = (double)(segs[last].p.v - segs[last].in.v);
            if (std::fabs(ex) < 0.001 && std::fabs(ey) < 0.001) {
                ex = (double)(segs[last].p.h - segs[last-1].p.h);
                ey = (double)(segs[last].p.v - segs[last-1].p.v);
            }
            sig.endAngle = std::atan2(ey, ex);
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Smart] ComputeSignature error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Smart] ComputeSignature unknown error\n");
    }
    return sig;
}

/*
    SelectMatchingPaths — find all paths in the document with a similar
    boundary signature, and select them.

    The threshold slider (0-100) controls matching strictness:
    - 0  = very strict (nearly identical paths only)
    - 100 = very loose (anything vaguely similar)
*/
void IllToolPlugin::SelectMatchingPaths(const BoundarySignature& refSig,
                                        double thresholdPct,
                                        AIArtHandle hitArt)
{
    try {
        // Map threshold 0-100 to tolerances
        double t = thresholdPct / 100.0;
        double lengthTol   = 0.05 + t * 0.75;
        double curvTol     = 0.10 + t * 1.90;
        int    maxSegDelta = 1 + (int)(t * 19.0);

        fprintf(stderr, "[IllTool Smart] Matching: threshold=%.0f%% lenTol=%.0f%% "
                "curvTol=%.0f%% segDelta=%d\n",
                thresholdPct, lengthTol * 100.0, curvTol * 100.0, maxSegDelta);

        // Get all path art in document
        AIMatchingArtSpec spec;
        spec.type = kPathArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool Smart] No paths in document\n");
            return;
        }

        // Deselect all currently selected art (clean slate)
        {
            AIMatchingArtSpec selSpec;
            selSpec.type = kAnyArt;
            selSpec.whichAttr = kArtSelected;
            selSpec.attr = kArtSelected;
            AIArtHandle** selMatches = nullptr;
            ai::int32 numSelMatches = 0;
            ASErr selErr = sAIMatchingArt->GetMatchingArt(&selSpec, 1,
                                                          &selMatches, &numSelMatches);
            if (selErr == kNoErr && numSelMatches > 0) {
                for (ai::int32 si = 0; si < numSelMatches; si++) {
                    sAIArt->SetArtUserAttr((*selMatches)[si], kArtSelected, 0);
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)selMatches);
            }
        }

        int matchCount = 0;
        int skippedLocked = 0;
        int skippedMismatch = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            // Always select the originally clicked path
            if (art == hitArt) {
                sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
                matchCount++;
                continue;
            }

            // Compute candidate signature
            BoundarySignature candSig = ComputeSignature(art);

            // Criteria 1: same open/closed status
            if (candSig.isClosed != refSig.isClosed) {
                skippedMismatch++;
                continue;
            }

            // Criteria 2: segment count within delta
            int segDiff = std::abs(candSig.segmentCount - refSig.segmentCount);
            if (segDiff > maxSegDelta) {
                skippedMismatch++;
                continue;
            }

            // Criteria 3: total length within tolerance
            if (refSig.totalLength > 0.001 || candSig.totalLength > 0.001) {
                double maxLen = std::max(refSig.totalLength, candSig.totalLength);
                if (maxLen > 0.001) {
                    double lenDiff = std::fabs(candSig.totalLength - refSig.totalLength)
                                   / maxLen;
                    if (lenDiff > lengthTol) {
                        skippedMismatch++;
                        continue;
                    }
                }
            }

            // Criteria 4: average curvature within tolerance
            double maxCurv = std::max(refSig.avgCurvature, candSig.avgCurvature);
            if (maxCurv > 0.0001) {
                double curvDiff = std::fabs(candSig.avgCurvature - refSig.avgCurvature)
                                / maxCurv;
                if (curvDiff > curvTol) {
                    skippedMismatch++;
                    continue;
                }
            }

            // All criteria passed
            sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
            matchCount++;
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        fprintf(stderr, "[IllTool Smart] Matches: %d (skipped: %d locked, "
                "%d mismatch, %d total)\n",
                matchCount, skippedLocked, skippedMismatch, (int)numMatches);

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Smart] SelectMatchingPaths error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Smart] SelectMatchingPaths unknown error\n");
    }
}
