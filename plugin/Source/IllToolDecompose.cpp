//========================================================================================
//  IllTool — Auto-Decompose (Stage 14)
//  One-click form analysis: clusters paths into logical groups by proximity,
//  boundary signature similarity, and bounding box overlap. Color-coded overlay
//  for review, then commit to named groups on accept.
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
#include <numeric>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Types
//========================================================================================

struct PathPairScore {
    size_t indexA;
    size_t indexB;
    float  endpointDist;    // min distance between endpoints
    float  signatureSim;    // boundary signature similarity (0-1)
    float  bboxOverlap;     // bounding box overlap ratio (0-1)
};

struct DecomposeCluster {
    std::vector<AIArtHandle> paths;
    const char* dominantType;   // "ARC", "LINE", "ELLIPSE", etc.
    float cleanupScore;         // (actual_points - ideal) / actual
    int clusterIndex;
    AIRGBColor overlayColor;
};

//========================================================================================
//  File-scope state (persists across timer ticks, reset on new analyze)
//========================================================================================

static std::vector<DecomposeCluster> gDecomposeClusters;
static bool gDecomposeActive = false;

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

static float ComputeEndpointDistance(AIArtHandle a, AIArtHandle b)
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

static float ComputeSignatureSimilarity(AIArtHandle a, AIArtHandle b)
{
    if (!gPlugin) return 0.0f;

    IllToolPlugin::BoundarySignature sigA = gPlugin->ComputeSignature(a);
    IllToolPlugin::BoundarySignature sigB = gPlugin->ComputeSignature(b);

    // Length similarity (0-1)
    double maxLen = std::max(sigA.totalLength, sigB.totalLength);
    double lenSim = (maxLen > 0.001)
        ? 1.0 - std::fabs(sigA.totalLength - sigB.totalLength) / maxLen
        : 1.0;

    // Curvature similarity (0-1)
    double maxCurv = std::max(sigA.avgCurvature, sigB.avgCurvature);
    double curvSim = (maxCurv > 0.0001)
        ? 1.0 - std::fabs(sigA.avgCurvature - sigB.avgCurvature) / maxCurv
        : 1.0;

    // Segment count similarity (0-1)
    int maxSeg = std::max(sigA.segmentCount, sigB.segmentCount);
    double segSim = (maxSeg > 0)
        ? 1.0 - (double)std::abs(sigA.segmentCount - sigB.segmentCount) / (double)maxSeg
        : 1.0;

    // Closed/open match bonus
    double closedMatch = (sigA.isClosed == sigB.isClosed) ? 1.0 : 0.5;

    return (float)(lenSim * 0.35 + curvSim * 0.30 + segSim * 0.20 + closedMatch * 0.15);
}

static float ComputeBBoxOverlap(AIArtHandle a, AIArtHandle b)
{
    AIRealRect boundsA, boundsB;
    ASErr errA = sAIArt->GetArtBounds(a, &boundsA);
    ASErr errB = sAIArt->GetArtBounds(b, &boundsB);
    if (errA != kNoErr || errB != kNoErr) return 0.0f;

    // Illustrator: top > bottom (flipped Y)
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

static void BuildProximityGraph(const std::vector<AIArtHandle>& paths,
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

            // Edge exists if any criterion is met
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
static std::vector<int> gParent;

static int Find(int x) {
    while (gParent[x] != x) {
        gParent[x] = gParent[gParent[x]];  // path compression
        x = gParent[x];
    }
    return x;
}

static void Union(int a, int b) {
    a = Find(a);
    b = Find(b);
    if (a != b) gParent[a] = b;
}

static void ClusterConnectedComponents(const std::vector<AIArtHandle>& paths,
                                        const std::vector<PathPairScore>& edges,
                                        std::vector<DecomposeCluster>& clusters)
{
    clusters.clear();
    size_t n = paths.size();
    if (n == 0) return;

    // Initialize union-find
    gParent.resize(n);
    std::iota(gParent.begin(), gParent.end(), 0);

    // Union connected pairs
    for (const auto& edge : edges) {
        Union((int)edge.indexA, (int)edge.indexB);
    }

    // Group by root
    std::vector<std::vector<size_t>> groups(n);
    for (size_t i = 0; i < n; i++) {
        groups[(size_t)Find((int)i)].push_back(i);
    }

    // Build cluster objects
    int clusterIdx = 0;
    for (size_t root = 0; root < n; root++) {
        if (groups[root].empty()) continue;

        DecomposeCluster cluster;
        cluster.clusterIndex = clusterIdx;
        for (size_t idx : groups[root]) {
            cluster.paths.push_back(paths[idx]);
        }

        // Assign color: stray fragments (size 1) get red, others get palette color
        if (cluster.paths.size() == 1) {
            cluster.overlayColor = kStrayColor;
        } else {
            cluster.overlayColor = kClusterColors[clusterIdx % kNumClusterColors];
        }

        // Classify dominant type via signature analysis
        // Count segment totals and check curvature to determine dominant type
        int totalSegs = 0;
        double totalCurv = 0;
        int closedCount = 0;
        for (AIArtHandle path : cluster.paths) {
            if (!gPlugin) break;
            IllToolPlugin::BoundarySignature sig = gPlugin->ComputeSignature(path);
            totalSegs += sig.segmentCount;
            totalCurv += sig.avgCurvature;
            if (sig.isClosed) closedCount++;
        }
        int pathCount = (int)cluster.paths.size();
        double avgSegs = (pathCount > 0) ? (double)totalSegs / pathCount : 0;
        double avgCurv = (pathCount > 0) ? totalCurv / pathCount : 0;
        bool mostlyClosed = (closedCount > pathCount / 2);

        // Simple heuristic classification
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

        // Cleanup score: ratio of excess points
        // ideal = 2 per line segment, actual = total segments
        int idealPts = pathCount * 2;  // minimum for straight lines
        cluster.cleanupScore = (totalSegs > 0)
            ? (float)(totalSegs - idealPts) / (float)totalSegs
            : 0.0f;
        if (cluster.cleanupScore < 0) cluster.cleanupScore = 0;

        clusters.push_back(cluster);
        clusterIdx++;
    }

    gParent.clear();
}

//========================================================================================
//  Public API — called from ProcessOperationQueue
//========================================================================================

void RunDecompose(float sensitivity)
{
    try {
        fprintf(stderr, "[IllTool Decompose] RunDecompose: sensitivity=%.2f\n", sensitivity);

        // Clear previous state
        gDecomposeClusters.clear();
        gDecomposeActive = false;

        // Get all selected path art
        AIMatchingArtSpec spec;
        spec.type = kPathArt;
        spec.whichAttr = kArtSelected;
        spec.attr = kArtSelected;
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool Decompose] No selected paths found\n");
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            BridgeSetDecomposeReadout("No selected paths");
            return;
        }

        // Collect valid paths (skip locked/hidden)
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

        fprintf(stderr, "[IllTool Decompose] %zu valid paths for analysis\n", paths.size());
        if (paths.size() < 2) {
            BridgeSetDecomposeReadout("Need 2+ paths");
            return;
        }

        // Map sensitivity 0-1 to endpoint threshold 2-50pt
        float threshold = 2.0f + sensitivity * 48.0f;

        // Build proximity graph
        std::vector<PathPairScore> edges;
        BuildProximityGraph(paths, threshold, edges);
        fprintf(stderr, "[IllTool Decompose] Proximity graph: %zu edges\n", edges.size());

        // Cluster connected components
        ClusterConnectedComponents(paths, edges, gDecomposeClusters);
        gDecomposeActive = true;

        // Build readout
        char readout[256];
        int strayCount = 0;
        for (const auto& c : gDecomposeClusters) {
            if (c.paths.size() == 1) strayCount++;
        }
        snprintf(readout, sizeof(readout), "%d clusters, %d strays, %d paths",
                 (int)gDecomposeClusters.size() - strayCount, strayCount, (int)paths.size());
        BridgeSetDecomposeReadout(readout);
        fprintf(stderr, "[IllTool Decompose] Result: %s\n", readout);

        // Invalidate to show overlay
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Decompose] RunDecompose error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Decompose] RunDecompose unknown error\n");
    }
}

void AcceptDecompose()
{
    try {
        if (!gDecomposeActive || gDecomposeClusters.empty()) {
            fprintf(stderr, "[IllTool Decompose] AcceptDecompose: no active decompose\n");
            return;
        }

        int groupsCreated = 0;
        for (auto& cluster : gDecomposeClusters) {
            if (cluster.paths.empty()) continue;

            AIArtHandle group = NULL;
            ASErr err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, NULL, &group);
            if (err != kNoErr || !group) {
                fprintf(stderr, "[IllTool Decompose] NewArt(group) failed: %d\n", (int)err);
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

        fprintf(stderr, "[IllTool Decompose] AcceptDecompose: created %d groups\n", groupsCreated);
        gDecomposeClusters.clear();
        gDecomposeActive = false;

        char readout[64];
        snprintf(readout, sizeof(readout), "Created %d groups", groupsCreated);
        BridgeSetDecomposeReadout(readout);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Decompose] AcceptDecompose error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Decompose] AcceptDecompose unknown error\n");
    }
}

void AcceptCluster(int clusterIndex)
{
    try {
        if (!gDecomposeActive) return;

        // Find cluster by index
        DecomposeCluster* target = nullptr;
        size_t targetIdx = 0;
        for (size_t i = 0; i < gDecomposeClusters.size(); i++) {
            if (gDecomposeClusters[i].clusterIndex == clusterIndex) {
                target = &gDecomposeClusters[i];
                targetIdx = i;
                break;
            }
        }
        if (!target || target->paths.empty()) {
            fprintf(stderr, "[IllTool Decompose] AcceptCluster: cluster %d not found\n", clusterIndex);
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

        // Remove accepted cluster from list
        gDecomposeClusters.erase(gDecomposeClusters.begin() + (ptrdiff_t)targetIdx);
        if (gDecomposeClusters.empty()) gDecomposeActive = false;

        fprintf(stderr, "[IllTool Decompose] AcceptCluster: accepted cluster %d\n", clusterIndex);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Decompose] AcceptCluster error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Decompose] AcceptCluster unknown error\n");
    }
}

void SplitCluster(int clusterIndex)
{
    try {
        if (!gDecomposeActive) return;

        // Find cluster
        size_t targetIdx = SIZE_MAX;
        for (size_t i = 0; i < gDecomposeClusters.size(); i++) {
            if (gDecomposeClusters[i].clusterIndex == clusterIndex) {
                targetIdx = i;
                break;
            }
        }
        if (targetIdx == SIZE_MAX) return;

        DecomposeCluster& cluster = gDecomposeClusters[targetIdx];
        if (cluster.paths.size() < 2) {
            fprintf(stderr, "[IllTool Decompose] SplitCluster: cluster %d has only %zu paths\n",
                    clusterIndex, cluster.paths.size());
            return;
        }

        // Split in half — simple bisection by spatial position (centroid X)
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

        // Create new cluster from second half
        int newIndex = 0;
        for (const auto& c : gDecomposeClusters) {
            if (c.clusterIndex >= newIndex) newIndex = c.clusterIndex + 1;
        }

        DecomposeCluster newCluster;
        newCluster.clusterIndex = newIndex;
        newCluster.dominantType = cluster.dominantType;
        newCluster.cleanupScore = cluster.cleanupScore;
        newCluster.overlayColor = kClusterColors[newIndex % kNumClusterColors];

        // Partition paths
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

        // Update stray color if needed
        if (cluster.paths.size() == 1) cluster.overlayColor = kStrayColor;
        if (newCluster.paths.size() == 1) newCluster.overlayColor = kStrayColor;

        gDecomposeClusters.push_back(newCluster);

        fprintf(stderr, "[IllTool Decompose] SplitCluster: %d -> %zu + %zu paths\n",
                clusterIndex, keepPaths.size(), splitPaths.size());
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Decompose] SplitCluster error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Decompose] SplitCluster unknown error\n");
    }
}

void MergeDecomposeClusters(int clusterA, int clusterB)
{
    try {
        if (!gDecomposeActive) return;

        size_t idxA = SIZE_MAX, idxB = SIZE_MAX;
        for (size_t i = 0; i < gDecomposeClusters.size(); i++) {
            if (gDecomposeClusters[i].clusterIndex == clusterA) idxA = i;
            if (gDecomposeClusters[i].clusterIndex == clusterB) idxB = i;
        }
        if (idxA == SIZE_MAX || idxB == SIZE_MAX || idxA == idxB) {
            fprintf(stderr, "[IllTool Decompose] MergeDecomposeClusters: invalid indices %d, %d\n",
                    clusterA, clusterB);
            return;
        }

        // Merge B into A
        for (AIArtHandle path : gDecomposeClusters[idxB].paths) {
            gDecomposeClusters[idxA].paths.push_back(path);
        }

        // Update stray color if was stray
        if (gDecomposeClusters[idxA].paths.size() > 1) {
            gDecomposeClusters[idxA].overlayColor =
                kClusterColors[gDecomposeClusters[idxA].clusterIndex % kNumClusterColors];
        }

        // Remove B
        gDecomposeClusters.erase(gDecomposeClusters.begin() + (ptrdiff_t)idxB);

        fprintf(stderr, "[IllTool Decompose] Merged cluster %d into %d\n", clusterB, clusterA);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Decompose] MergeDecomposeClusters error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Decompose] MergeDecomposeClusters unknown error\n");
    }
}

//========================================================================================
//  Annotator overlay — draws colored bounding boxes around clustered paths
//========================================================================================

void DrawDecomposeOverlay(AIAnnotatorMessage* message)
{
    if (!gDecomposeActive || gDecomposeClusters.empty()) return;
    if (!message || !message->drawer) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    for (const auto& cluster : gDecomposeClusters) {
        sAIAnnotatorDrawer->SetColor(drawer, cluster.overlayColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.5);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);

        for (AIArtHandle path : cluster.paths) {
            AIRealRect bounds;
            if (sAIArt->GetArtBounds(path, &bounds) != kNoErr) continue;

            // Convert art bounds to view coordinates
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

            // Draw bounding rectangle
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[0], viewCorners[1]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[1], viewCorners[2]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[2], viewCorners[3]);
            sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[3], viewCorners[0]);
        }
    }
}

//========================================================================================
//  Query functions (for panel consumption)
//========================================================================================

bool IsDecomposeActive()
{
    return gDecomposeActive;
}

int GetDecomposeClusterCount()
{
    return (int)gDecomposeClusters.size();
}

const DecomposeCluster* GetDecomposeCluster(int index)
{
    if (index < 0 || index >= (int)gDecomposeClusters.size()) return nullptr;
    return &gDecomposeClusters[index];
}

void CancelDecompose()
{
    gDecomposeClusters.clear();
    gDecomposeActive = false;
    BridgeSetDecomposeReadout("---");
    fprintf(stderr, "[IllTool Decompose] CancelDecompose\n");
}
