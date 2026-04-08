//========================================================================================
//  DecomposeModule — Auto-Decompose (Stage 14)
//  One-click form analysis: clusters paths into logical groups by proximity,
//  boundary signature similarity, and bounding box overlap. Color-coded overlay
//  for review, then commit to named groups on accept.
//
//  Ported from IllToolDecompose.cpp into module pattern.
//========================================================================================

#include "DecomposeModule.h"
#include "SelectionModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <cfloat>
#include <vector>
#include <algorithm>
#include <numeric>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Overlay color palette
//========================================================================================

static const AIRGBColor kClusterColors[] = {
    {0,         0,         65535},     // blue
    {0,         65535,     0},         // green
    {65535,     32768,     0},         // orange
    {32768,     0,         65535},     // purple
    {0,         65535,     65535},     // cyan
    {65535,     65535,     0},         // yellow
    {65535,     0,         32768},     // magenta
    {32768,     65535,     0},         // lime
    {0,         32768,     65535},     // sky blue
    {65535,     32768,     32768},     // pink
};
static const int kNumClusterColors = sizeof(kClusterColors) / sizeof(kClusterColors[0]);
static const AIRGBColor kStrayColor = {65535, 0, 0};  // red for stray fragments

//========================================================================================
//  Internal helpers
//========================================================================================

static double PointDist(const AIRealPoint& a, const AIRealPoint& b)
{
    double dx = (double)a.h - (double)b.h;
    double dy = (double)a.v - (double)b.v;
    return std::sqrt(dx * dx + dy * dy);
}

float DecomposeModule::ComputeEndpointDistance(AIArtHandle a, AIArtHandle b)
{
    ai::int16 segCountA = 0, segCountB = 0;
    sAIPath->GetPathSegmentCount(a, &segCountA);
    sAIPath->GetPathSegmentCount(b, &segCountB);
    if (segCountA < 1 || segCountB < 1) return (float)FLT_MAX;

    AIPathSegment firstA, lastA, firstB, lastB;
    sAIPath->GetPathSegments(a, 0, 1, &firstA);
    sAIPath->GetPathSegments(a, segCountA - 1, 1, &lastA);
    sAIPath->GetPathSegments(b, 0, 1, &firstB);
    sAIPath->GetPathSegments(b, segCountB - 1, 1, &lastB);

    double d1 = PointDist(lastA.p, firstB.p);
    double d2 = PointDist(lastA.p, lastB.p);
    double d3 = PointDist(firstA.p, firstB.p);
    double d4 = PointDist(firstA.p, lastB.p);
    return (float)std::min({d1, d2, d3, d4});
}

float DecomposeModule::ComputeSignatureSimilarity(AIArtHandle a, AIArtHandle b)
{
    if (!gPlugin) return 0.0f;

    auto* selMod = gPlugin->GetModule<SelectionModule>();
    if (!selMod) return 0.0f;
    SelectionModule::BoundarySignature sigA = selMod->ComputeSignature(a);
    SelectionModule::BoundarySignature sigB = selMod->ComputeSignature(b);

    double maxLen = std::max(sigA.totalLength, sigB.totalLength);
    double lenSim = (maxLen > 0.001)
        ? 1.0 - std::fabs(sigA.totalLength - sigB.totalLength) / maxLen
        : 1.0;

    double maxCurv = std::max(sigA.avgCurvature, sigB.avgCurvature);
    double curvSim = (maxCurv > 0.0001)
        ? 1.0 - std::fabs(sigA.avgCurvature - sigB.avgCurvature) / maxCurv
        : 1.0;

    int maxSeg = std::max(sigA.segmentCount, sigB.segmentCount);
    double segSim = (maxSeg > 0)
        ? 1.0 - (double)std::abs(sigA.segmentCount - sigB.segmentCount) / (double)maxSeg
        : 1.0;

    double closedMatch = (sigA.isClosed == sigB.isClosed) ? 1.0 : 0.5;

    return (float)(lenSim * 0.35 + curvSim * 0.30 + segSim * 0.20 + closedMatch * 0.15);
}

float DecomposeModule::ComputeBBoxOverlap(AIArtHandle a, AIArtHandle b)
{
    AIRealRect boundsA, boundsB;
    ASErr errA = sAIArt->GetArtBounds(a, &boundsA);
    ASErr errB = sAIArt->GetArtBounds(b, &boundsB);
    if (errA != kNoErr || errB != kNoErr) return 0.0f;

    double left   = std::max((double)boundsA.left,  (double)boundsB.left);
    double right  = std::min((double)boundsA.right, (double)boundsB.right);
    double bottom = std::max((double)boundsA.bottom,(double)boundsB.bottom);
    double top    = std::min((double)boundsA.top,   (double)boundsB.top);

    if (left >= right || bottom >= top) return 0.0f;

    double overlapArea = (right - left) * (top - bottom);

    double areaA = ((double)boundsA.right - (double)boundsA.left) *
                   ((double)boundsA.top - (double)boundsA.bottom);
    double areaB = ((double)boundsB.right - (double)boundsB.left) *
                   ((double)boundsB.top - (double)boundsB.bottom);
    double minArea = std::min(areaA, areaB);

    return (minArea > 0.001) ? (float)(overlapArea / minArea) : 0.0f;
}

void DecomposeModule::BuildProximityGraph(const std::vector<AIArtHandle>& paths,
                                           float threshold,
                                           std::vector<PathPairScore>& edges)
{
    edges.clear();
    size_t n = paths.size();

    for (size_t i = 0; i < n; i++) {
        for (size_t j = i + 1; j < n; j++) {
            PathPairScore score;
            score.indexA = i;
            score.indexB = j;
            score.endpointDist = ComputeEndpointDistance(paths[i], paths[j]);
            score.signatureSim = ComputeSignatureSimilarity(paths[i], paths[j]);
            score.bboxOverlap  = ComputeBBoxOverlap(paths[i], paths[j]);

            bool connected = (score.endpointDist < threshold) ||
                             (score.signatureSim > 0.7f) ||
                             (score.bboxOverlap > 0.5f);

            if (connected) {
                edges.push_back(score);
            }
        }
    }
}

// Union-Find for connected components
static std::vector<int> sParent;

static int Find(int x) {
    while (sParent[x] != x) {
        sParent[x] = sParent[sParent[x]];
        x = sParent[x];
    }
    return x;
}

static void Union(int a, int b) {
    a = Find(a);
    b = Find(b);
    if (a != b) sParent[a] = b;
}

void DecomposeModule::ClusterConnectedComponents(const std::vector<AIArtHandle>& paths,
                                                   const std::vector<PathPairScore>& edges)
{
    fClusters.clear();
    size_t n = paths.size();
    if (n == 0) return;

    sParent.resize(n);
    std::iota(sParent.begin(), sParent.end(), 0);

    for (const auto& edge : edges) {
        Union((int)edge.indexA, (int)edge.indexB);
    }

    std::vector<std::vector<size_t>> groups(n);
    for (size_t i = 0; i < n; i++) {
        groups[(size_t)Find((int)i)].push_back(i);
    }

    int clusterIdx = 0;
    for (size_t root = 0; root < n; root++) {
        if (groups[root].empty()) continue;

        DecomposeCluster cluster;
        cluster.clusterIndex = clusterIdx;
        for (size_t idx : groups[root]) {
            cluster.paths.push_back(paths[idx]);
        }

        if (cluster.paths.size() == 1) {
            cluster.overlayColor = kStrayColor;
        } else {
            cluster.overlayColor = kClusterColors[clusterIdx % kNumClusterColors];
        }

        // Classify dominant type
        int totalSegs = 0;
        double totalCurv = 0;
        int closedCount = 0;
        for (AIArtHandle path : cluster.paths) {
            if (!gPlugin) break;
            auto* selMod2 = gPlugin->GetModule<SelectionModule>();
            SelectionModule::BoundarySignature sig = selMod2 ? selMod2->ComputeSignature(path) : SelectionModule::BoundarySignature{};
            totalSegs += sig.segmentCount;
            totalCurv += sig.avgCurvature;
            if (sig.isClosed) closedCount++;
        }
        int pathCount = (int)cluster.paths.size();
        double avgSegs = (pathCount > 0) ? (double)totalSegs / pathCount : 0;
        double avgCurv = (pathCount > 0) ? totalCurv / pathCount : 0;
        bool mostlyClosed = (closedCount > pathCount / 2);

        if (mostlyClosed && avgCurv > 0.02) {
            cluster.dominantType = "ELLIPSE";
        } else if (avgSegs <= 2.5 && avgCurv < 0.005) {
            cluster.dominantType = "LINE";
        } else if (avgCurv > 0.01) {
            cluster.dominantType = "ARC";
        } else if (avgSegs <= 5 && !mostlyClosed) {
            cluster.dominantType = "L-SHAPE";
        } else {
            cluster.dominantType = "FREEFORM";
        }

        int idealPts = pathCount * 2;
        cluster.cleanupScore = (totalSegs > 0)
            ? (float)(totalSegs - idealPts) / (float)totalSegs
            : 0.0f;
        if (cluster.cleanupScore < 0) cluster.cleanupScore = 0;

        fClusters.push_back(cluster);
        clusterIdx++;
    }

    sParent.clear();
}

//========================================================================================
//  HandleOp — operation dispatch
//========================================================================================

bool DecomposeModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::Decompose:
            RunDecompose((float)op.param1);
            return true;
        case OpType::DecomposeAccept:
            AcceptDecompose();
            return true;
        case OpType::DecomposeAcceptOne:
            AcceptCluster(op.intParam);
            return true;
        case OpType::DecomposeSplit:
            SplitCluster(op.intParam);
            return true;
        case OpType::DecomposeMergeGroups:
            MergeDecomposeClusters(op.intParam, (int)op.param1);
            return true;
        case OpType::DecomposeCancel:
            CancelDecompose();
            return true;
        default:
            return false;
    }
}

//========================================================================================
//  DrawOverlay
//========================================================================================

void DecomposeModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    if (!fDecomposeActive || fClusters.empty()) return;
    if (!msg || !msg->drawer) return;

    AIAnnotatorDrawer* drawer = msg->drawer;

    for (const auto& cluster : fClusters) {
        sAIAnnotatorDrawer->SetColor(drawer, cluster.overlayColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.5);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);

        for (AIArtHandle path : cluster.paths) {
            AIRealRect bounds;
            if (sAIArt->GetArtBounds(path, &bounds) != kNoErr) continue;

            AIRealPoint corners[4] = {
                {bounds.left,  bounds.top},
                {bounds.right, bounds.top},
                {bounds.right, bounds.bottom},
                {bounds.left,  bounds.bottom}
            };

            AIPoint viewCorners[4];
            bool allOK = true;
            for (int c = 0; c < 4; c++) {
                if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &corners[c], &viewCorners[c]) != kNoErr) {
                    allOK = false;
                    break;
                }
            }
            if (!allOK) continue;

            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[0], viewCorners[1]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[1], viewCorners[2]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[2], viewCorners[3]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[3], viewCorners[0]);
        }
    }
}

//========================================================================================
//  Notifications
//========================================================================================

void DecomposeModule::OnDocumentChanged()
{
    fClusters.clear();
    fDecomposeActive = false;
}

//========================================================================================
//  RunDecompose
//========================================================================================

void DecomposeModule::RunDecompose(float sensitivity)
{
    try {
        fprintf(stderr, "[DecomposeModule] RunDecompose: sensitivity=%.2f\n", sensitivity);

        fClusters.clear();
        fDecomposeActive = false;

        AIMatchingArtSpec spec;
        spec.type = kPathArt;
        spec.whichAttr = kArtSelected;
        spec.attr = kArtSelected;
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[DecomposeModule] No selected paths found\n");
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            BridgeSetDecomposeReadout("No selected paths");
            return;
        }

        std::vector<AIArtHandle> paths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 2) continue;

            paths.push_back(art);
        }
        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

        fprintf(stderr, "[DecomposeModule] %zu valid paths for analysis\n", paths.size());
        if (paths.size() < 2) {
            BridgeSetDecomposeReadout("Need 2+ paths");
            return;
        }

        float threshold = 2.0f + sensitivity * 48.0f;

        std::vector<PathPairScore> edges;
        BuildProximityGraph(paths, threshold, edges);
        fprintf(stderr, "[DecomposeModule] Proximity graph: %zu edges\n", edges.size());

        ClusterConnectedComponents(paths, edges);
        fDecomposeActive = true;

        char readout[256];
        int strayCount = 0;
        for (const auto& c : fClusters) {
            if (c.paths.size() == 1) strayCount++;
        }
        snprintf(readout, sizeof(readout), "%d clusters, %d strays, %d paths",
                 (int)fClusters.size() - strayCount, strayCount, (int)paths.size());
        BridgeSetDecomposeReadout(readout);
        fprintf(stderr, "[DecomposeModule] Result: %s\n", readout);

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[DecomposeModule] RunDecompose error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[DecomposeModule] RunDecompose unknown error\n");
    }
}

//========================================================================================
//  AcceptDecompose
//========================================================================================

void DecomposeModule::AcceptDecompose()
{
    try {
        if (!fDecomposeActive || fClusters.empty()) {
            fprintf(stderr, "[DecomposeModule] AcceptDecompose: no active decompose\n");
            return;
        }

        int groupsCreated = 0;
        for (auto& cluster : fClusters) {
            if (cluster.paths.empty()) continue;

            AIArtHandle group = NULL;
            ASErr err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, NULL, &group);
            if (err != kNoErr || !group) {
                fprintf(stderr, "[DecomposeModule] NewArt(group) failed: %d\n", (int)err);
                continue;
            }

            char name[64];
            snprintf(name, sizeof(name), "%s Group %d",
                     cluster.dominantType, cluster.clusterIndex + 1);
            sAIArt->SetArtName(group, ai::UnicodeString::FromRoman(name));

            for (AIArtHandle path : cluster.paths) {
                sAIArt->ReorderArt(path, kPlaceInsideOnTop, group);
            }
            groupsCreated++;
        }

        fprintf(stderr, "[DecomposeModule] AcceptDecompose: created %d groups\n", groupsCreated);
        fClusters.clear();
        fDecomposeActive = false;

        char readout[64];
        snprintf(readout, sizeof(readout), "Created %d groups", groupsCreated);
        BridgeSetDecomposeReadout(readout);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[DecomposeModule] AcceptDecompose error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[DecomposeModule] AcceptDecompose unknown error\n");
    }
}

//========================================================================================
//  AcceptCluster
//========================================================================================

void DecomposeModule::AcceptCluster(int clusterIndex)
{
    try {
        if (!fDecomposeActive) return;

        DecomposeCluster* target = nullptr;
        size_t targetIdx = 0;
        for (size_t i = 0; i < fClusters.size(); i++) {
            if (fClusters[i].clusterIndex == clusterIndex) {
                target = &fClusters[i];
                targetIdx = i;
                break;
            }
        }
        if (!target || target->paths.empty()) {
            fprintf(stderr, "[DecomposeModule] AcceptCluster: cluster %d not found\n", clusterIndex);
            return;
        }

        AIArtHandle group = NULL;
        ASErr err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, NULL, &group);
        if (err != kNoErr || !group) return;

        char name[64];
        snprintf(name, sizeof(name), "%s Group %d",
                 target->dominantType, target->clusterIndex + 1);
        sAIArt->SetArtName(group, ai::UnicodeString::FromRoman(name));

        for (AIArtHandle path : target->paths) {
            sAIArt->ReorderArt(path, kPlaceInsideOnTop, group);
        }

        fClusters.erase(fClusters.begin() + (ptrdiff_t)targetIdx);
        if (fClusters.empty()) fDecomposeActive = false;

        fprintf(stderr, "[DecomposeModule] AcceptCluster: accepted cluster %d\n", clusterIndex);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[DecomposeModule] AcceptCluster error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[DecomposeModule] AcceptCluster unknown error\n");
    }
}

//========================================================================================
//  SplitCluster
//========================================================================================

void DecomposeModule::SplitCluster(int clusterIndex)
{
    try {
        if (!fDecomposeActive) return;

        size_t targetIdx = SIZE_MAX;
        for (size_t i = 0; i < fClusters.size(); i++) {
            if (fClusters[i].clusterIndex == clusterIndex) {
                targetIdx = i;
                break;
            }
        }
        if (targetIdx == SIZE_MAX) return;

        DecomposeCluster& cluster = fClusters[targetIdx];
        if (cluster.paths.size() < 2) {
            fprintf(stderr, "[DecomposeModule] SplitCluster: cluster %d has only %zu paths\n",
                    clusterIndex, cluster.paths.size());
            return;
        }

        struct PathCentroid {
            size_t index;
            double cx;
        };
        std::vector<PathCentroid> centroids;
        for (size_t i = 0; i < cluster.paths.size(); i++) {
            AIRealRect bounds;
            if (sAIArt->GetArtBounds(cluster.paths[i], &bounds) == kNoErr) {
                centroids.push_back({i, ((double)bounds.left + (double)bounds.right) / 2.0});
            }
        }
        std::sort(centroids.begin(), centroids.end(),
                  [](const PathCentroid& a, const PathCentroid& b) { return a.cx < b.cx; });

        size_t splitPoint = centroids.size() / 2;

        int newIndex = 0;
        for (const auto& c : fClusters) {
            if (c.clusterIndex >= newIndex) newIndex = c.clusterIndex + 1;
        }

        DecomposeCluster newCluster;
        newCluster.clusterIndex = newIndex;
        newCluster.dominantType = cluster.dominantType;
        newCluster.cleanupScore = cluster.cleanupScore;
        newCluster.overlayColor = kClusterColors[newIndex % kNumClusterColors];

        std::vector<AIArtHandle> keepPaths, splitPaths;
        for (size_t i = 0; i < centroids.size(); i++) {
            if (i < splitPoint) {
                keepPaths.push_back(cluster.paths[centroids[i].index]);
            } else {
                splitPaths.push_back(cluster.paths[centroids[i].index]);
            }
        }

        cluster.paths = keepPaths;
        newCluster.paths = splitPaths;

        if (cluster.paths.size() == 1) cluster.overlayColor = kStrayColor;
        if (newCluster.paths.size() == 1) newCluster.overlayColor = kStrayColor;

        fClusters.push_back(newCluster);

        fprintf(stderr, "[DecomposeModule] SplitCluster: %d -> %zu + %zu paths\n",
                clusterIndex, keepPaths.size(), splitPaths.size());
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[DecomposeModule] SplitCluster error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[DecomposeModule] SplitCluster unknown error\n");
    }
}

//========================================================================================
//  MergeDecomposeClusters
//========================================================================================

void DecomposeModule::MergeDecomposeClusters(int clusterA, int clusterB)
{
    try {
        if (!fDecomposeActive) return;

        size_t idxA = SIZE_MAX, idxB = SIZE_MAX;
        for (size_t i = 0; i < fClusters.size(); i++) {
            if (fClusters[i].clusterIndex == clusterA) idxA = i;
            if (fClusters[i].clusterIndex == clusterB) idxB = i;
        }
        if (idxA == SIZE_MAX || idxB == SIZE_MAX || idxA == idxB) {
            fprintf(stderr, "[DecomposeModule] MergeDecomposeClusters: invalid indices %d, %d\n",
                    clusterA, clusterB);
            return;
        }

        for (AIArtHandle path : fClusters[idxB].paths) {
            fClusters[idxA].paths.push_back(path);
        }

        if (fClusters[idxA].paths.size() > 1) {
            fClusters[idxA].overlayColor =
                kClusterColors[fClusters[idxA].clusterIndex % kNumClusterColors];
        }

        fClusters.erase(fClusters.begin() + (ptrdiff_t)idxB);

        fprintf(stderr, "[DecomposeModule] Merged cluster %d into %d\n", clusterB, clusterA);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[DecomposeModule] MergeDecomposeClusters error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[DecomposeModule] MergeDecomposeClusters unknown error\n");
    }
}

//========================================================================================
//  CancelDecompose
//========================================================================================

void DecomposeModule::CancelDecompose()
{
    fClusters.clear();
    fDecomposeActive = false;
    BridgeSetDecomposeReadout("---");
    fprintf(stderr, "[DecomposeModule] CancelDecompose\n");
}
