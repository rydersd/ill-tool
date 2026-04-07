//========================================================================================
//  IllTool — Merge Operations
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <cfloat>
#include <vector>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Stage 6: Merge Operations
//========================================================================================

static double PointDistance(const AIRealPoint& a, const AIRealPoint& b)
{
    double dx = (double)a.h - (double)b.h;
    double dy = (double)a.v - (double)b.v;
    return sqrt(dx * dx + dy * dy);
}

void IllToolPlugin::ScanEndpoints(double tolerance)
{
    try {
        fLastScanTolerance = tolerance;  // Store for chain-merge re-scan
        fprintf(stderr, "[IllTool] ScanEndpoints: begin (tolerance=%.1f)\n", tolerance);
        fMergePairs.clear();

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            BridgeSetMergeReadout("0 pairs found, 0 paths");
            return;
        }

        struct OpenPath { AIArtHandle art; AIRealPoint startPt; AIRealPoint endPt; };
        std::vector<OpenPath> openPaths;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            AIBoolean closed = false;
            sAIPath->GetPathClosed(art, &closed);
            if (closed) continue;

            // Check selection (art-level or segment-level)
            ai::int32 artAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &artAttrs);
            if (!(artAttrs & kArtSelected)) {
                ai::int16 sc = 0;
                sAIPath->GetPathSegmentCount(art, &sc);
                bool hasSel = false;
                for (ai::int16 s = 0; s < sc; s++) {
                    ai::int16 sel = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &sel);
                    if (sel & kSegmentPointSelected) { hasSel = true; break; }
                }
                if (!hasSel) continue;
            }

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 2) continue;

            AIPathSegment firstSeg, lastSeg;
            sAIPath->GetPathSegments(art, 0, 1, &firstSeg);
            sAIPath->GetPathSegments(art, segCount - 1, 1, &lastSeg);
            openPaths.push_back({art, firstSeg.p, lastSeg.p});
        }
        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }

        fprintf(stderr, "[IllTool] ScanEndpoints: %zu open paths\n", openPaths.size());
        if (openPaths.size() < 2) {
            char buf[64]; snprintf(buf, sizeof(buf), "0 pairs found, %d paths", (int)openPaths.size());
            BridgeSetMergeReadout(buf); return;
        }

        std::vector<bool> used(openPaths.size(), false);
        for (size_t i = 0; i < openPaths.size(); i++) {
            if (used[i]) continue;
            int bestJ = -1; double bestDist = DBL_MAX;
            bool bestEA = true, bestEB = true;

            for (size_t j = i + 1; j < openPaths.size(); j++) {
                if (used[j]) continue;
                struct { double d; bool ea; bool eb; } combos[4] = {
                    {PointDistance(openPaths[i].endPt,   openPaths[j].startPt), true,  true},
                    {PointDistance(openPaths[i].endPt,   openPaths[j].endPt),   true,  false},
                    {PointDistance(openPaths[i].startPt, openPaths[j].startPt), false, true},
                    {PointDistance(openPaths[i].startPt, openPaths[j].endPt),   false, false},
                };
                for (int c = 0; c < 4; c++) {
                    if (combos[c].d <= tolerance && combos[c].d < bestDist) {
                        bestJ = (int)j; bestDist = combos[c].d;
                        bestEA = combos[c].ea; bestEB = combos[c].eb;
                    }
                }
            }
            if (bestJ >= 0) {
                fMergePairs.push_back({openPaths[i].art, openPaths[(size_t)bestJ].art, bestEA, bestEB, bestDist});
                used[i] = true; used[(size_t)bestJ] = true;
            }
        }

        char readout[128];
        snprintf(readout, sizeof(readout), "%d pairs found, %d paths", (int)fMergePairs.size(), (int)openPaths.size());
        BridgeSetMergeReadout(readout);
        fprintf(stderr, "[IllTool] ScanEndpoints: %zu pairs among %zu paths\n", fMergePairs.size(), openPaths.size());
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] ScanEndpoints error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] ScanEndpoints unknown error\n"); }
}

void IllToolPlugin::MergeEndpoints(bool chainMerge, bool preserveHandles)
{
    try {
        if (fMergePairs.empty()) { fprintf(stderr, "[IllTool] MergeEndpoints: no pairs\n"); return; }

        fprintf(stderr, "[IllTool] MergeEndpoints: begin (chain=%s, preserve=%s, %zu pairs)\n",
                chainMerge ? "true" : "false", preserveHandles ? "true" : "false", fMergePairs.size());

        fMergeSnapshot = MergeSnapshot();
        fMergeSnapshot.valid = true;
        int totalMerged = 0;
        int maxIterations = chainMerge ? 10 : 1;

        for (int iteration = 0; iteration < maxIterations; iteration++) {
            if (fMergePairs.empty()) break;
            std::vector<AIArtHandle> toDispose;

            for (auto& pair : fMergePairs) {
                ai::int16 segCountA = 0;
                sAIPath->GetPathSegmentCount(pair.artA, &segCountA);
                if (segCountA == 0) continue;
                std::vector<AIPathSegment> segsA(segCountA);
                sAIPath->GetPathSegments(pair.artA, 0, segCountA, segsA.data());

                ai::int16 segCountB = 0;
                sAIPath->GetPathSegmentCount(pair.artB, &segCountB);
                if (segCountB == 0) continue;
                std::vector<AIPathSegment> segsB(segCountB);
                sAIPath->GetPathSegments(pair.artB, 0, segCountB, segsB.data());

                // Snapshot for undo
                {
                    MergeSnapshot::PathData pdA;
                    pdA.segments = segsA;
                    AIBoolean cA = false; sAIPath->GetPathClosed(pair.artA, &cA); pdA.closed = cA;
                    AIArtHandle pA = nullptr; sAIArt->GetArtParent(pair.artA, &pA); pdA.parentRef = pA;
                    fMergeSnapshot.originals.push_back(pdA);

                    MergeSnapshot::PathData pdB;
                    pdB.segments = segsB;
                    AIBoolean cB = false; sAIPath->GetPathClosed(pair.artB, &cB); pdB.closed = cB;
                    AIArtHandle pB = nullptr; sAIArt->GetArtParent(pair.artB, &pB); pdB.parentRef = pB;
                    fMergeSnapshot.originals.push_back(pdB);
                }

                // Orient so matched ends meet
                if (!pair.endA_is_end) {
                    std::reverse(segsA.begin(), segsA.end());
                    for (auto& seg : segsA) std::swap(seg.in, seg.out);
                }
                if (!pair.endB_is_start) {
                    std::reverse(segsB.begin(), segsB.end());
                    for (auto& seg : segsB) std::swap(seg.in, seg.out);
                }

                // Build junction
                AIPathSegment& jA = segsA.back();
                AIPathSegment& jB = segsB.front();
                AIPathSegment junction;
                if (preserveHandles) {
                    junction.p = jA.p; junction.in = jA.in; junction.out = jB.out; junction.corner = false;
                } else {
                    junction.p.h = (jA.p.h + jB.p.h) / 2.0f;
                    junction.p.v = (jA.p.v + jB.p.v) / 2.0f;
                    junction.in = jA.in; junction.out = jB.out; junction.corner = false;
                }

                // Concatenate: A[0..n-2] + junction + B[1..end]
                std::vector<AIPathSegment> merged;
                for (int k = 0; k < (int)segsA.size() - 1; k++) merged.push_back(segsA[k]);
                merged.push_back(junction);
                for (int k = 1; k < (int)segsB.size(); k++) merged.push_back(segsB[k]);

                AIArtHandle newPath = nullptr;
                ASErr nr = sAIArt->NewArt(kPathArt, kPlaceAbove, pair.artA, &newPath);
                if (nr != kNoErr || !newPath) { fprintf(stderr, "[IllTool] MergeEndpoints: NewArt failed: %d\n", (int)nr); continue; }

                sAIPath->SetPathSegmentCount(newPath, (ai::int16)merged.size());
                sAIPath->SetPathSegments(newPath, 0, (ai::int16)merged.size(), merged.data());
                sAIPath->SetPathClosed(newPath, false);

                fMergeSnapshot.mergedPaths.push_back(newPath);
                toDispose.push_back(pair.artA);
                toDispose.push_back(pair.artB);
                totalMerged++;
            }

            for (AIArtHandle art : toDispose) sAIArt->DisposeArt(art);

            // Chain merge: re-scan
            if (chainMerge && iteration < maxIterations - 1) {
                double tol = fLastScanTolerance;
                fMergePairs.clear();

                AIMatchingArtSpec reSpec(kPathArt, 0, 0);
                AIArtHandle** reM = nullptr; ai::int32 reN = 0;
                if (sAIMatchingArt->GetMatchingArt(&reSpec, 1, &reM, &reN) != kNoErr || reN == 0) break;

                struct COP { AIArtHandle art; AIRealPoint s, e; };
                std::vector<COP> cp;
                for (ai::int32 ri = 0; ri < reN; ri++) {
                    AIArtHandle art = (*reM)[ri];
                    ai::int32 at = 0; sAIArt->GetArtUserAttr(art, kArtLocked|kArtHidden, &at);
                    if (at & (kArtLocked|kArtHidden)) continue;
                    AIBoolean cl = false; sAIPath->GetPathClosed(art, &cl); if (cl) continue;
                    ai::int16 sc = 0; sAIPath->GetPathSegmentCount(art, &sc); if (sc < 2) continue;
                    AIPathSegment f, l; sAIPath->GetPathSegments(art, 0, 1, &f); sAIPath->GetPathSegments(art, sc-1, 1, &l);
                    cp.push_back({art, f.p, l.p});
                }
                if (reM) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)reM);
                if (cp.size() < 2) break;

                std::vector<bool> cu(cp.size(), false);
                for (size_t ci = 0; ci < cp.size(); ci++) {
                    if (cu[ci]) continue;
                    int bJ = -1; double bD = DBL_MAX; bool bEA = true, bEB = true;
                    for (size_t cj = ci+1; cj < cp.size(); cj++) {
                        if (cu[cj]) continue;
                        struct { double d; bool ea, eb; } cm[4] = {
                            {PointDistance(cp[ci].e, cp[cj].s), true, true},
                            {PointDistance(cp[ci].e, cp[cj].e), true, false},
                            {PointDistance(cp[ci].s, cp[cj].s), false, true},
                            {PointDistance(cp[ci].s, cp[cj].e), false, false},
                        };
                        for (int c = 0; c < 4; c++) {
                            if (cm[c].d <= tol && cm[c].d < bD) { bJ=(int)cj; bD=cm[c].d; bEA=cm[c].ea; bEB=cm[c].eb; }
                        }
                    }
                    if (bJ >= 0) {
                        fMergePairs.push_back({cp[ci].art, cp[(size_t)bJ].art, bEA, bEB, bD});
                        cu[ci] = true; cu[(size_t)bJ] = true;
                    }
                }
                if (fMergePairs.empty()) break;
            } else {
                fMergePairs.clear();
            }
        }

        char readout[128];
        snprintf(readout, sizeof(readout), "Merged %d pairs", totalMerged);
        BridgeSetMergeReadout(readout);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool] MergeEndpoints: merged %d pairs\n", totalMerged);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] MergeEndpoints error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] MergeEndpoints unknown error\n"); }
}

void IllToolPlugin::UndoMerge()
{
    try {
        if (!fMergeSnapshot.valid) { fprintf(stderr, "[IllTool] UndoMerge: no snapshot\n"); return; }

        fprintf(stderr, "[IllTool] UndoMerge: %zu originals, %zu merged\n",
                fMergeSnapshot.originals.size(), fMergeSnapshot.mergedPaths.size());

        for (AIArtHandle art : fMergeSnapshot.mergedPaths) {
            ASErr r = sAIArt->DisposeArt(art);
            if (r != kNoErr) fprintf(stderr, "[IllTool] UndoMerge: DisposeArt failed: %d\n", (int)r);
        }

        int restoredCount = 0;
        for (auto& pd : fMergeSnapshot.originals) {
            if (pd.segments.empty()) continue;
            AIArtHandle newPath = nullptr;
            ASErr r = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (r != kNoErr || !newPath) { fprintf(stderr, "[IllTool] UndoMerge: NewArt failed: %d\n", (int)r); continue; }

            sAIPath->SetPathSegmentCount(newPath, (ai::int16)pd.segments.size());
            sAIPath->SetPathSegments(newPath, 0, (ai::int16)pd.segments.size(),
                                     const_cast<AIPathSegment*>(pd.segments.data()));
            sAIPath->SetPathClosed(newPath, pd.closed);
            restoredCount++;
        }

        fMergeSnapshot = MergeSnapshot();
        char readout[128];
        snprintf(readout, sizeof(readout), "Undo: restored %d paths", restoredCount);
        BridgeSetMergeReadout(readout);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool] UndoMerge: restored %d paths\n", restoredCount);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] UndoMerge error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] UndoMerge unknown error\n"); }
}
