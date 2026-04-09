//========================================================================================
//  CleanupPipeline — Shape pipeline + working mode for CleanupModule
//
//  Split from CleanupModule.cpp. All methods are CleanupModule members.
//  This file is #included from CleanupModule.cpp (not compiled separately).
//========================================================================================

#include "CleanupModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "ShapeUtils.h"
#include "PerspectiveModule.h"
#include "LearningEngine.h"
#include "VisionEngine.h"
#include "HttpBridge.h"

#include <cstdio>
#include <cmath>
#include <algorithm>
#include <vector>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  AverageSelection — CEP-faithful pipeline
//========================================================================================

/*
    Pipeline:
    1. Collect ALL selected anchor [x,y] from all paths
    2. SortByPCA — order by principal component
    3. ClassifyPoints — identify shape, return fitted points + handles
    4. PrecomputeLOD — 20 levels for slider scrubbing
    5. PlacePreview — create new clean path with bezier handles
    6. Enter working mode (dim originals, enter isolation on preview group)
*/
void CleanupModule::AverageSelection()
{
    try {
        // Step 1: Collect all selected anchor positions
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[CleanupModule] AverageSelection: no path art found\n");
            return;
        }

        std::vector<AIRealPoint> anchors;
        std::vector<AIArtHandle> sourcePaths;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result != kNoErr) continue;

                if (selected & kSegmentPointSelected) {
                    AIPathSegment seg;
                    result = sAIPath->GetPathSegments(art, s, 1, &seg);
                    if (result == kNoErr) {
                        anchors.push_back(seg.p);
                        hasSelected = true;
                    }
                }
            }
            if (hasSelected) {
                bool alreadyTracked = false;
                for (auto sp : sourcePaths) { if (sp == art) { alreadyTracked = true; break; } }
                if (!alreadyTracked) sourcePaths.push_back(art);
            }
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        if ((int)anchors.size() < 2) {
            fprintf(stderr, "[CleanupModule] AverageSelection: need 2+ selected anchors (found %d)\n",
                    (int)anchors.size());
            return;
        }

        fprintf(stderr, "[CleanupModule] AverageSelection: collected %d anchors from %d paths\n",
                (int)anchors.size(), (int)sourcePaths.size());

        // Step 2: Sort by PCA
        fCachedSortedPoints = SortByPCA(anchors);

        // Step 3: Classify shape
        fCachedShapeFit = ClassifyPoints(fCachedSortedPoints);
        fprintf(stderr, "[CleanupModule] AverageSelection: classified as %s (conf=%.2f, %d pts)\n",
                kShapeNames[(int)fCachedShapeFit.shape], fCachedShapeFit.confidence,
                (int)fCachedShapeFit.points.size());

        // Record shape detection in LearningEngine (user accepted auto-detection)
        {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            LearningEngine::Instance().RecordShapeOverride(
                surfaceHint,
                kShapeNames[(int)fCachedShapeFit.shape],
                "");  // empty = user accepted auto-detection
        }

        // Step 4: Precompute LOD levels
        fLODCache = PrecomputeLOD(fCachedSortedPoints, 20, &fCachedShapeFit);

        // Step 5: Enter working mode — dim originals, create working group
        if (fInWorkingMode) {
            CancelWorkingMode();
        }

        if (!sAIBlendStyle) {
            fprintf(stderr, "[CleanupModule] AverageSelection: AIBlendStyleSuite not available\n");
            return;
        }

        // Detect source group — find the common parent of selected paths
        fSourceGroup = nullptr;
        fSourceGroupName.clear();
        fSourceLayerName.clear();
        {
            // Get the parent of the first selected path
            if (!sourcePaths.empty()) {
                AIArtHandle parent = nullptr;
                result = sAIArt->GetArtParent(sourcePaths[0], &parent);
                if (result == kNoErr && parent) {
                    short parentType = 0;
                    sAIArt->GetArtType(parent, &parentType);
                    if (parentType == kGroupArt) {
                        // Check if all selected paths share this parent
                        bool allSameParent = true;
                        for (size_t pi = 1; pi < sourcePaths.size(); pi++) {
                            AIArtHandle otherParent = nullptr;
                            sAIArt->GetArtParent(sourcePaths[pi], &otherParent);
                            if (otherParent != parent) { allSameParent = false; break; }
                        }
                        if (allSameParent) {
                            fSourceGroup = parent;
                            ai::UnicodeString groupName;
                            ASBoolean isDefault = false;
                            if (sAIArt->GetArtName(parent, groupName, &isDefault) == kNoErr && !isDefault) {
                                fSourceGroupName = groupName.as_Platform();
                            }
                        }
                    }
                }

                // Get the layer name
                AILayerHandle srcLayer = nullptr;
                result = sAIArt->GetLayerOfArt(sourcePaths[0], &srcLayer);
                if (result == kNoErr && srcLayer) {
                    ai::UnicodeString layerTitle;
                    sAILayer->GetLayerTitle(srcLayer, layerTitle);
                    fSourceLayerName = layerTitle.as_Platform();
                }
            }

            if (fSourceGroup) {
                fprintf(stderr, "[CleanupModule] AverageSelection: source group='%s' layer='%s'\n",
                        fSourceGroupName.c_str(), fSourceLayerName.c_str());
            } else {
                fprintf(stderr, "[CleanupModule] AverageSelection: no common group (document root)\n");
            }
        }

        // Create working group inside the source group (or at document root)
        AIArtHandle workParent = fSourceGroup;
        if (!workParent) {
            // Fallback: create on a Working layer
            AILayerHandle layer = nullptr;
            ai::UnicodeString workingTitle("Working");
            result = sAILayer->GetLayerByTitle(&layer, workingTitle);
            if (result != kNoErr || layer == nullptr) {
                result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
                if (result != kNoErr || !layer) {
                    fprintf(stderr, "[CleanupModule] AverageSelection: failed to create Working layer\n");
                    return;
                }
                sAILayer->SetLayerTitle(layer, workingTitle);
            }
            sAIArt->GetFirstArtOfLayer(layer, &workParent);
            if (!workParent) {
                fprintf(stderr, "[CleanupModule] AverageSelection: failed to get layer group\n");
                return;
            }
        }

        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, workParent, &workGroup);
        if (result != kNoErr || !workGroup) {
            fprintf(stderr, "[CleanupModule] AverageSelection: failed to create working group\n");
            return;
        }
        sAIArt->SetArtName(workGroup, ai::UnicodeString("__working__"));

        // Dim and lock originals (keep visible at 30% for reference, matching CEP)
        fOriginalPaths.clear();
        for (AIArtHandle art : sourcePaths) {
            AIReal prevOpacity = 1.0;
            if (sAIBlendStyle) prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            if (sAIBlendStyle) sAIBlendStyle->SetOpacity(art, 0.30);
            sAIArt->SetArtUserAttr(art, kArtLocked, kArtLocked);
        }

        // Step 6: Build the preview — ALWAYS minimal points
        std::vector<AIRealPoint> previewPts;
        std::vector<HandlePair> previewHandles;
        bool previewClosed = fCachedShapeFit.closed;

        if (fCachedShapeFit.shape != BridgeShapeType::Freeform &&
            fCachedShapeFit.confidence > 0.15 &&
            (int)fCachedShapeFit.points.size() <= 6) {
            // Classified shape — use its fitted output (2-4 points)
            previewPts = fCachedShapeFit.points;
            previewHandles = fCachedShapeFit.handles;
        } else {
            // Freeform or low confidence — force minimal curve:
            // first point, steepest curve point, last point
            auto& sorted = fCachedSortedPoints;
            int n = (int)sorted.size();
            AIRealPoint first = sorted[0];
            AIRealPoint last = sorted[n - 1];

            double maxDist = 0;
            int maxIdx = n / 2;
            for (int i = 1; i < n - 1; i++) {
                double abx = last.h - first.h, aby = last.v - first.v;
                double apx = sorted[i].h - first.h, apy = sorted[i].v - first.v;
                double abLen = sqrt(abx * abx + aby * aby);
                double dist = (abLen > 1e-6) ? fabs(apx * aby - apy * abx) / abLen : 0;
                if (dist > maxDist) { maxDist = dist; maxIdx = i; }
            }

            double span = Dist2D(first, last);
            bool needMidpoint = (maxDist > span * 0.05);

            if (needMidpoint) {
                AIRealPoint mid = sorted[maxIdx];
                previewPts = { first, mid, last };
                double tn = 1.0 / 6.0;
                double t0x = (mid.h - first.h) * tn, t0y = (mid.v - first.v) * tn;
                double t1x = (last.h - first.h) * tn, t1y = (last.v - first.v) * tn;
                double t2x = (last.h - mid.h) * tn, t2y = (last.v - mid.v) * tn;
                previewHandles = {
                    { first, {(AIReal)(first.h + t0x), (AIReal)(first.v + t0y)} },
                    { {(AIReal)(mid.h - t1x), (AIReal)(mid.v - t1y)},
                      {(AIReal)(mid.h + t1x), (AIReal)(mid.v + t1y)} },
                    { {(AIReal)(last.h - t2x), (AIReal)(last.v - t2y)}, last }
                };
            } else {
                previewPts = { first, last };
            }
            previewClosed = false;
        }

        // Perspective projection — only when grid is LOCKED and snap is enabled.
        // Shape-aware: circles become perspective ellipses, rects become perspective quads.
        if (BridgeGetSnapToPerspective() && BridgeGetPerspectiveLocked() && gPlugin) {
            auto* persp = gPlugin->GetModule<PerspectiveModule>();
            if (persp) {
                int plane = 0;  // floor plane by default

                if (fCachedShapeFit.shape == BridgeShapeType::Ellipse &&
                    previewPts.size() >= 4) {
                    // Circle/Ellipse → perspective ellipse: project 12 points around the
                    // ellipse through the grid, then fit a smooth closed bezier.
                    double cx = 0, cy = 0;
                    for (auto& p : previewPts) { cx += p.h; cy += p.v; }
                    cx /= previewPts.size(); cy /= previewPts.size();
                    double rx = 0, ry = 0;
                    for (auto& p : previewPts) {
                        rx = std::max(rx, fabs(p.h - cx));
                        ry = std::max(ry, fabs(p.v - cy));
                    }

                    const int N = 12;
                    std::vector<AIRealPoint> circlePts(N);
                    for (int i = 0; i < N; i++) {
                        double angle = 2.0 * M_PI * i / N;
                        circlePts[i].h = (AIReal)(cx + rx * cos(angle));
                        circlePts[i].v = (AIReal)(cy + ry * sin(angle));
                    }

                    previewPts = persp->ProjectPointsThroughPerspective(circlePts, plane);
                    previewHandles = ComputeSmoothHandles(previewPts, true, 1.0 / 6.0);
                    previewClosed = true;
                    fprintf(stderr, "[CleanupModule] Perspective: ellipse → %d-point projected ellipse\n", N);

                } else if (fCachedShapeFit.shape == BridgeShapeType::Rect &&
                           previewPts.size() == 4) {
                    // Rectangle → perspective quad: project 4 corners
                    previewPts = persp->ProjectPointsThroughPerspective(previewPts, plane);
                    previewHandles.clear();
                    previewHandles.resize(4);
                    for (int i = 0; i < 4; i++) {
                        previewHandles[i].left = previewPts[i];
                        previewHandles[i].right = previewPts[i];
                    }
                    previewClosed = true;
                    fprintf(stderr, "[CleanupModule] Perspective: rect → projected quad\n");

                } else {
                    // Generic projection for other shapes (line, arc, S-curve, freeform)
                    previewPts = persp->ProjectPointsThroughPerspective(previewPts, plane);
                    for (auto& h : previewHandles) {
                        auto projL = persp->ProjectPointsThroughPerspective({h.left}, plane);
                        auto projR = persp->ProjectPointsThroughPerspective({h.right}, plane);
                        if (!projL.empty()) h.left = projL[0];
                        if (!projR.empty()) h.right = projR[0];
                    }
                    fprintf(stderr, "[CleanupModule] Perspective: generic %d-point projection\n",
                            (int)previewPts.size());
                }
            }
        }

        fPreviewPath = PlacePreview(workGroup, previewPts, previewHandles, previewClosed);

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

        // Clear undo stack — stale frames from prior sessions have disposed art handles
        fUndoStack.Clear();

        // Let Illustrator manage undo natively — the SDK bundles tool mouse
        // selectors into a single undo context per drag. Each drag is undoable.
        // Set undo text so Edit menu shows "Undo Shape Cleanup"
        if (sAIUndo) {
            sAIUndo->SetUndoTextUS(ai::UnicodeString("Undo Shape Cleanup"),
                                    ai::UnicodeString("Redo Shape Cleanup"));
        }

        // Install Enter/Escape interceptor (does NOT intercept Cmd+Z anymore)
        if (!fUndoEventMonitor) {
            fUndoEventMonitor = (void*)InstallUndoInterceptor(this);
        }

        // Enter isolation mode on the working group
        if (sAIIsolationMode && !sAIIsolationMode->IsInIsolationMode()) {
            if (sAIIsolationMode->CanIsolateArt(workGroup)) {
                result = sAIIsolationMode->EnterIsolationMode(workGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[CleanupModule] AverageSelection: entered isolation\n");
                }
            }
        }

        // Select the preview path and all its segments for direct editing
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
            for (ai::int16 s = 0; s < segCount; s++) {
                sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
            }

            // Keep IllTool tool active — our annotator draws bbox (circle) and
            // anchor (square) handles, and our ToolMouseDown/Drag/Up handles dragging.
            // No tool switch needed.
        }

        // Compute rotated bounding box
        ComputeBoundingBox();

        // Update the detected shape label
        fLastDetectedShape = kShapeNames[(int)fCachedShapeFit.shape];

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] AverageSelection: complete — %d anchors → %s preview with %d points\n",
                (int)anchors.size(), fLastDetectedShape,
                (int)fCachedShapeFit.points.size());
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[CleanupModule] AverageSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[CleanupModule] AverageSelection unknown error\n");
    }
}

//========================================================================================
//  Apply LOD Level — slider scrubbing
//========================================================================================

void CleanupModule::ApplyLODLevel(int level)
{
    if (fLODCache.empty() || !fInWorkingMode || !fWorkingGroup) {
        return;
    }

    const LODLevel* best = &fLODCache[0];
    for (auto& lod : fLODCache) {
        if (lod.value <= level) best = &lod;
    }

    // At high LOD levels with perspective active, project through the grid
    std::vector<AIRealPoint> lodPts = best->points;
    std::vector<HandlePair> lodHandles = best->handles;
    bool lodClosed = fCachedShapeFit.closed;

    if (level >= 80 && BridgeGetSnapToPerspective() && BridgeGetPerspectiveLocked() && gPlugin) {
        auto* persp = gPlugin->GetModule<PerspectiveModule>();
        if (persp) {
            lodPts = persp->ProjectPointsThroughPerspective(lodPts, 0);
            for (auto& h : lodHandles) {
                auto projL = persp->ProjectPointsThroughPerspective({h.left}, 0);
                auto projR = persp->ProjectPointsThroughPerspective({h.right}, 0);
                if (!projL.empty()) h.left = projL[0];
                if (!projR.empty()) h.right = projR[0];
            }
        }
    }

    if (fPreviewPath) {
        UpdatePreviewSegments(fPreviewPath, lodPts, lodHandles, lodClosed);
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        for (ai::int16 s = 0; s < segCount; s++) {
            sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
        }
    } else {
        fPreviewPath = PlacePreview(fWorkingGroup, lodPts, lodHandles, lodClosed);
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
        }
    }

    ComputeBoundingBox();
    sAIDocument->RedrawDocument();
    fprintf(stderr, "[CleanupModule] ApplyLODLevel: level=%d → %d points%s\n",
            level, (int)lodPts.size(),
            (level >= 80 && BridgeGetSnapToPerspective()) ? " (perspective-projected)" : "");
}

//========================================================================================
//  Enter Working Mode — duplicate, dim originals, isolate working group
//========================================================================================

static AIArtHandle FindOrCreateWorkingLayer()
{
    if (!sAILayer || !sAIArt) return nullptr;

    ASErr result = kNoErr;
    AILayerHandle layer = nullptr;
    ai::UnicodeString workingTitle("Working");
    result = sAILayer->GetLayerByTitle(&layer, workingTitle);

    if (result != kNoErr || layer == nullptr) {
        result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
        if (result != kNoErr || layer == nullptr) {
            fprintf(stderr, "[CleanupModule] Failed to create Working layer: %d\n", (int)result);
            return nullptr;
        }
        result = sAILayer->SetLayerTitle(layer, workingTitle);
    }

    AIArtHandle layerGroup = nullptr;
    result = sAIArt->GetFirstArtOfLayer(layer, &layerGroup);
    if (result != kNoErr || layerGroup == nullptr) {
        fprintf(stderr, "[CleanupModule] Failed to get Working layer art group: %d\n", (int)result);
        return nullptr;
    }

    return layerGroup;
}

void CleanupModule::EnterWorkingMode()
{
    if (fInWorkingMode) return;
    if (!sAIBlendStyle) return;

    // Mutual exclusion: exit perspective edit mode when entering cleanup
    if (gPlugin) {
        auto* persp = gPlugin->GetModule<PerspectiveModule>();
        if (persp && persp->IsInEditMode()) {
            persp->SetEditMode(false);
            fprintf(stderr, "[CleanupModule] EnterWorkingMode: exited perspective edit mode\n");
        }
    }

    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) return;

        std::vector<AIArtHandle> selectedPaths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    hasSelected = true;
                    break;
                }
            }
            if (hasSelected) selectedPaths.push_back(art);
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }
        if (selectedPaths.empty()) return;

        AIArtHandle layerGroup = FindOrCreateWorkingLayer();
        if (!layerGroup) return;

        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &workGroup);
        if (result != kNoErr || !workGroup) return;

        fOriginalPaths.clear();
        for (AIArtHandle art : selectedPaths) {
            AIArtHandle dupe = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, workGroup, &dupe);
            if (result != kNoErr) continue;

            // Only track original AFTER duplication succeeds — prevents
            // ApplyWorkingMode from disposing user art that was never duplicated
            AIReal prevOpacity = sAIBlendStyle->GetOpacity(art);

            // Copy selection state
            ai::int16 origSegCount = 0;
            sAIPath->GetPathSegmentCount(art, &origSegCount);
            ai::int16 dupeSegCount = 0;
            sAIPath->GetPathSegmentCount(dupe, &dupeSegCount);
            ai::int16 copyCount = std::min(origSegCount, dupeSegCount);
            for (ai::int16 s = 0; s < copyCount; s++) {
                ai::int16 selState = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &selState);
                if (selState != kSegmentNotSelected) {
                    sAIPath->SetPathSegmentSelected(dupe, s, selState);
                }
            }
            sAIArt->SetArtUserAttr(dupe, kArtSelected, kArtSelected);

            // Dim and lock the original
            sAIBlendStyle->SetOpacity(art, 0.30);
            sAIArt->SetArtUserAttr(art, kArtLocked, kArtLocked);

            fOriginalPaths.push_back({art, prevOpacity});
        }

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

        // Clear stale undo frames from prior sessions
        fUndoStack.Clear();

        // Native undo — SDK bundles tool mouse events into one undo context per drag
        if (sAIUndo) {
            sAIUndo->SetUndoTextUS(ai::UnicodeString("Undo Shape Cleanup"),
                                    ai::UnicodeString("Redo Shape Cleanup"));
        }

        if (!fUndoEventMonitor) {
            fUndoEventMonitor = (void*)InstallUndoInterceptor(this);
        }

        if (sAIIsolationMode && !sAIIsolationMode->IsInIsolationMode()) {
            if (sAIIsolationMode->CanIsolateArt(workGroup)) {
                sAIIsolationMode->EnterIsolationMode(workGroup, false);
            }
        }

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[CleanupModule] EnterWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[CleanupModule] EnterWorkingMode unknown error\n");
    }
}

//========================================================================================
//  Apply Working Mode — finalize, optionally delete originals
//========================================================================================

void CleanupModule::ApplyWorkingMode(bool deleteOriginals)
{
    if (!fInWorkingMode) return;

    try {
        // Suppress isolation re-entry notifier during Apply
        fExitingWorkingMode = true;

        // Clear undo stack IMMEDIATELY — before any art disposal.
        // Frames hold raw AIArtHandle pointers that become dangling after DisposeArt.
        fUndoStack.Clear();

        // Set undo text for the Apply action
        if (sAIUndo) {
            sAIUndo->SetUndoTextUS(ai::UnicodeString("Undo Shape Cleanup"),
                                    ai::UnicodeString("Redo Shape Cleanup"));
        }

        // Step 1: Exit isolation mode FIRST (before any art changes)
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            sAIIsolationMode->ExitIsolationMode();
            fprintf(stderr, "[CleanupModule] ApplyWorkingMode: exited isolation\n");
        }

        // Step 2: Unlock and restore originals BEFORE moving preview
        // (so moveTarget art handle is valid for ReorderArt)
        for (auto& rec : fOriginalPaths) {
            short artType = 0;
            if (sAIArt->GetArtType(rec.art, &artType) != kNoErr) {
                fprintf(stderr, "[CleanupModule] Skipping stale original path handle in restore\n");
                continue;
            }
            sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
            if (!deleteOriginals && sAIBlendStyle) {
                sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
            }
        }

        // Step 3: Move preview path out of working group into the source group
        AIArtHandle savedPreview = fPreviewPath;
        if (fPreviewPath && fWorkingGroup) {
            // Validate fSourceGroup handle hasn't gone stale
            if (fSourceGroup) {
                short sgType = 0;
                if (sAIArt->GetArtType(fSourceGroup, &sgType) != kNoErr) {
                    fprintf(stderr, "[CleanupModule] ApplyWorkingMode: source group handle stale — falling back to root\n");
                    fSourceGroup = nullptr;
                }
            }
            ASErr moveErr = kNoErr;
            if (fSourceGroup) {
                if (!fOriginalPaths.empty()) {
                    moveErr = sAIArt->ReorderArt(fPreviewPath, kPlaceAbove, fOriginalPaths[0].art);
                } else {
                    moveErr = sAIArt->ReorderArt(fPreviewPath, kPlaceInsideOnTop, fSourceGroup);
                }
            } else {
                if (!fOriginalPaths.empty()) {
                    moveErr = sAIArt->ReorderArt(fPreviewPath, kPlaceAbove, fOriginalPaths[0].art);
                } else {
                    moveErr = sAIArt->ReorderArt(fPreviewPath, kPlaceAboveAll, nullptr);
                }
            }

            if (moveErr != kNoErr) {
                fprintf(stderr, "[CleanupModule] ApplyWorkingMode: ReorderArt failed: %d — preview handle may be stale\n", (int)moveErr);
                fPreviewPath = nullptr;
            }

            // Auto-name + stroke copy — only if preview handle is still valid
            if (fPreviewPath) {
                std::string autoName;
                if (!fSourceGroupName.empty()) {
                    autoName = fSourceGroupName + " — Cleaned";
                } else if (!fSourceLayerName.empty()) {
                    autoName = fSourceLayerName + " — Cleaned";
                } else {
                    autoName = "Cleaned";
                }
                sAIArt->SetArtName(fPreviewPath, ai::UnicodeString(autoName));
                fprintf(stderr, "[CleanupModule] ApplyWorkingMode: preview promoted as '%s'\n", autoName.c_str());

                // Copy stroke style from first original path to preserve line weight/color
                if (!fOriginalPaths.empty() && sAIPathStyle) {
                    AIPathStyle srcStyle;
                    AIBoolean srcHasAdvFill = false;
                    short srcArtType = 0;
                    if (sAIArt->GetArtType(fOriginalPaths[0].art, &srcArtType) == kNoErr &&
                        srcArtType == kPathArt &&
                        sAIPathStyle->GetPathStyle(fOriginalPaths[0].art, &srcStyle, &srcHasAdvFill) == kNoErr) {
                        AIPathStyle dstStyle;
                        AIBoolean dstHasAdvFill = false;
                        if (sAIPathStyle->GetPathStyle(fPreviewPath, &dstStyle, &dstHasAdvFill) == kNoErr) {
                            dstStyle.stroke = srcStyle.stroke;
                            dstStyle.strokePaint = srcStyle.strokePaint;
                            sAIPathStyle->SetPathStyle(fPreviewPath, &dstStyle);
                            fprintf(stderr, "[CleanupModule] ApplyWorkingMode: copied stroke from original (width=%.1f)\n",
                                    srcStyle.stroke.width);
                        }
                    }
                }
            }  // end if (fPreviewPath)
        }

        // Step 4: Delete originals if requested
        if (deleteOriginals) {
            for (auto& rec : fOriginalPaths) {
                short artType = 0;
                if (sAIArt->GetArtType(rec.art, &artType) != kNoErr) {
                    fprintf(stderr, "[CleanupModule] Skipping stale original path handle in delete\n");
                    continue;
                }
                sAIArt->DisposeArt(rec.art);
            }
        }

        // Step 5: Dispose the working group (now empty)
        if (fWorkingGroup) {
            sAIArt->DisposeArt(fWorkingGroup);
        }

        // Record simplification level in LearningEngine
        if (!fCachedSortedPoints.empty() && fPreviewPath) {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            int pointsBefore = (int)fCachedSortedPoints.size();
            int pointsAfter = 0;
            ai::int16 previewSegCount = 0;
            if (sAIPath && fPreviewPath) {
                sAIPath->GetPathSegmentCount(fPreviewPath, &previewSegCount);
                pointsAfter = (int)previewSegCount;
            }
            double lodLevel = 50.0;
            for (const auto& lod : fLODCache) {
                if ((int)lod.points.size() == pointsAfter) {
                    lodLevel = (double)lod.value;
                    break;
                }
            }
            LearningEngine::Instance().RecordSimplifyLevel(
                surfaceHint, lodLevel, pointsBefore, pointsAfter);
        }

        // Select the final path
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
        }

        // Clear state (undo stack already cleared at top of Apply)
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fSourceGroup = nullptr;
        fSourceGroupName.clear();
        fSourceLayerName.clear();
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;
        fDragAnchorIdx = -1;
        fDragBezierIdx = -1;
        fHoverAnchorIdx = -1;
        fHoverBezierIdx = -1;
        fHoverBBoxIdx = -1;

        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode: complete (originals %s)\n",
                deleteOriginals ? "deleted" : "restored");
    }
    catch (ai::Error& ex) {
        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode unknown error\n");
    }
}

//========================================================================================
//  Cancel Working Mode — restore originals
//========================================================================================

void CleanupModule::CancelWorkingMode()
{
    if (!fInWorkingMode) return;

    try {
        fExitingWorkingMode = true;  // Suppress isolation re-entry notifier

        // Clear undo stack IMMEDIATELY — before any art disposal
        fUndoStack.Clear();

        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            sAIIsolationMode->ExitIsolationMode();
        }

        if (fWorkingGroup) {
            sAIArt->DisposeArt(fWorkingGroup);
        }

        for (auto& rec : fOriginalPaths) {
            short artType = 0;
            if (sAIArt->GetArtType(rec.art, &artType) != kNoErr) {
                fprintf(stderr, "[CleanupModule] Skipping stale original path handle in cancel\n");
                continue;
            }
            if (sAIBlendStyle) sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
            sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
        }

        // (undo stack already cleared at top of Cancel)
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fSourceGroup = nullptr;
        fSourceGroupName.clear();
        fSourceLayerName.clear();
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;
        fDragAnchorIdx = -1;
        fDragBezierIdx = -1;
        fHoverAnchorIdx = -1;
        fHoverBezierIdx = -1;
        fHoverBBoxIdx = -1;

        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] CancelWorkingMode: complete\n");
    }
    catch (ai::Error& ex) {
        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        fprintf(stderr, "[CleanupModule] CancelWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fExitingWorkingMode = false;
        RemoveUndoInterceptor(fUndoEventMonitor);
        fprintf(stderr, "[CleanupModule] CancelWorkingMode unknown error\n");
    }
}

//========================================================================================
//  Classify Selection — multi-path shape detection
//========================================================================================

void CleanupModule::ClassifySelection()
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            fLastDetectedShape = "---";
            return;
        }

        std::vector<AIArtHandle> selected = FindAllSelectedPaths(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (selected.empty()) { fLastDetectedShape = "---"; return; }

        // Classify each selected path, tally votes
        int votes[7] = {0};
        int pathCount = (int)selected.size();

        for (AIArtHandle path : selected) {
            double conf = 0;
            BridgeShapeType type = ClassifySinglePath(path, conf);
            int idx = (int)type;
            if (idx >= 0 && idx < 7) votes[idx]++;
        }

        BridgeShapeType dominant = BridgeShapeType::Freeform;
        int maxVotes = 0;
        for (int i = 0; i < 7; i++) {
            if (votes[i] > maxVotes) { maxVotes = votes[i]; dominant = (BridgeShapeType)i; }
        }

        bool isMixed = (maxVotes < pathCount && pathCount > 1);

        static char labelBuf[32];
        if (pathCount == 1) {
            snprintf(labelBuf, sizeof(labelBuf), "%s", kShapeNames[(int)dominant]);
        } else if (isMixed) {
            snprintf(labelBuf, sizeof(labelBuf), "MIXED (%d)", pathCount);
        } else {
            snprintf(labelBuf, sizeof(labelBuf), "%s (%d)", kShapeNames[(int)dominant], pathCount);
        }
        fLastDetectedShape = labelBuf;

        fprintf(stderr, "[CleanupModule] ClassifySelection: %d paths → %s\n",
                pathCount, fLastDetectedShape);

        // Surface type inference from VisionEngine (if image loaded)
        {
            VisionEngine& ve = VisionEngine::Instance();
            if (ve.IsLoaded()) {
                // Compute selection centroid from the first selected path
                AIArtHandle firstPath = selected[0];
                ai::int16 sc = 0;
                sAIPath->GetPathSegmentCount(firstPath, &sc);
                if (sc > 0) {
                    std::vector<AIPathSegment> segs(sc);
                    sAIPath->GetPathSegments(firstPath, 0, sc, segs.data());
                    double centerX = 0, centerY = 0;
                    for (ai::int16 s = 0; s < sc; s++) {
                        centerX += segs[s].p.h;
                        centerY += segs[s].p.v;
                    }
                    centerX /= sc;
                    centerY /= sc;
                    VisionEngine::SurfaceHint hint = ve.InferSurfaceType(
                        (int)centerX, (int)centerY, 50, 50);
                    if (hint.type != VisionEngine::SurfaceType::Unknown) {
                        BridgeSetSurfaceHint((int)hint.type, hint.confidence, hint.gradientAngle);
                        fprintf(stderr, "[CleanupModule] Surface type inferred: %d (conf=%.2f)\n",
                                (int)hint.type, hint.confidence);
                    }
                }
            }
        }

        // LearningEngine: prediction → UI suggestion
        {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            std::string predicted = LearningEngine::Instance().PredictShape(surfaceHint, 0, 0.0);
            const char* autoDetected = kShapeNames[(int)dominant];
            if (!predicted.empty()) {
                bool match = (predicted == autoDetected);
                fprintf(stderr, "[CleanupModule Learning] PredictShape(%s) → %s, auto=%s, %s\n",
                        surfaceHint, predicted.c_str(), autoDetected,
                        match ? "MATCH" : "MISMATCH");
                // If prediction differs from auto-detection, show suggestion in label
                if (!match) {
                    static char suggestBuf[128];
                    snprintf(suggestBuf, sizeof(suggestBuf), "%s (try: %s)",
                             labelBuf, predicted.c_str());
                    fLastDetectedShape = suggestBuf;
                }
            }

            // Set initial simplification level from learned preference
            double predLevel = LearningEngine::Instance().PredictSimplifyLevel(surfaceHint);
            if (predLevel >= 0) {
                BridgeSetTension(predLevel);
                fprintf(stderr, "[CleanupModule Learning] PredictSimplifyLevel(%s) → %.0f\n",
                        surfaceHint, predLevel);
            }
        }
    }
    catch (ai::Error& ex) { fprintf(stderr, "[CleanupModule] ClassifySelection error: %d\n", (int)ex); fLastDetectedShape = "ERROR"; }
    catch (...) { fprintf(stderr, "[CleanupModule] ClassifySelection unknown error\n"); fLastDetectedShape = "ERROR"; }
}

//========================================================================================
//  Reclassify — force-fit selection to a specific shape type
//========================================================================================

void CleanupModule::ReclassifyAs(BridgeShapeType shapeType)
{
    if (shapeType == BridgeShapeType::Freeform) {
        fLastDetectedShape = "FREEFORM";
        return;
    }

    // If not in working mode, run AverageSelection first to collect + merge anchors
    if (!fInWorkingMode || fCachedSortedPoints.empty()) {
        fprintf(stderr, "[CleanupModule] ReclassifyAs: not in working mode — running AverageSelection first\n");
        AverageSelection();
        // If AverageSelection failed (no selection, etc.), bail
        if (!fInWorkingMode || fCachedSortedPoints.empty()) {
            fprintf(stderr, "[CleanupModule] ReclassifyAs: AverageSelection did not enter working mode — aborting\n");
            return;
        }
    }

    // CEP-style: re-fit cached sorted points and update preview in place
    if (!fCachedSortedPoints.empty() && fInWorkingMode && fWorkingGroup) {
        const char* autoShape = kShapeNames[(int)fCachedShapeFit.shape];

        ShapeFitResult newFit = FitPointsToShape(fCachedSortedPoints, shapeType);
        fCachedShapeFit = newFit;

        // Update existing path in place (no flicker from destroy+create)
        if (fPreviewPath) {
            UpdatePreviewSegments(fPreviewPath, newFit.points, newFit.handles, newFit.closed);
            // Re-select all segments for handle visibility
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
            for (ai::int16 s = 0; s < segCount; s++) {
                sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
            }
        } else {
            fPreviewPath = PlacePreview(fWorkingGroup, newFit.points, newFit.handles, newFit.closed);
            if (fPreviewPath) {
                sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
            }
        }

        fLODCache = PrecomputeLOD(fCachedSortedPoints, 20, &fCachedShapeFit);
        fLastDetectedShape = kShapeNames[(int)shapeType];

        // Record shape override
        const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
        const char* userShape = kShapeNames[(int)shapeType];
        LearningEngine::Instance().RecordShapeOverride(surfaceHint, autoShape, userShape);

        sAIDocument->RedrawDocument();
        return;
    }

    // Direct path reclassification (not in working mode)
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        std::vector<AIArtHandle> selected = FindAllSelectedPaths(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (selected.empty()) return;

        fUndoStack.PushFrame();

        // Capture auto-detected shape for LearningEngine
        const char* autoShapeStr = "FREEFORM";
        if (!selected.empty()) {
            double autoConf = 0;
            BridgeShapeType autoType = ClassifySinglePath(selected[0], autoConf);
            autoShapeStr = kShapeNames[(int)autoType];
        }

        double tensionScale = fmax(0.1, BridgeGetTension() / 50.0);
        int modifiedCount = 0;

        for (AIArtHandle targetPath : selected) {
            fUndoStack.SnapshotPath(targetPath);

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(targetPath, &segCount);
            if (segCount < 2) continue;

            std::vector<AIPathSegment> segs(segCount);
            sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
            std::vector<AIRealPoint> pts(segCount);
            for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p;

            // Use FitPointsToShape to get the fitted result
            ShapeFitResult fit = FitPointsToShape(pts, shapeType);

            // Build segments from fitted points + handles
            std::vector<AIPathSegment> newSegs;
            int np = (int)fit.points.size();
            bool hasHandles = ((int)fit.handles.size() == np);

            for (int i = 0; i < np; i++) {
                AIPathSegment seg = {};
                seg.p = fit.points[i];
                if (hasHandles) {
                    seg.in = fit.handles[i].left;
                    seg.out = fit.handles[i].right;
                    seg.corner = false;
                } else {
                    seg.in = fit.points[i];
                    seg.out = fit.points[i];
                    seg.corner = true;
                }
                // Apply tension scaling to handles
                if (hasHandles && tensionScale != 1.0) {
                    double dx_in = seg.in.h - seg.p.h;
                    double dy_in = seg.in.v - seg.p.v;
                    double dx_out = seg.out.h - seg.p.h;
                    double dy_out = seg.out.v - seg.p.v;
                    seg.in.h = (AIReal)(seg.p.h + dx_in * tensionScale);
                    seg.in.v = (AIReal)(seg.p.v + dy_in * tensionScale);
                    seg.out.h = (AIReal)(seg.p.h + dx_out * tensionScale);
                    seg.out.v = (AIReal)(seg.p.v + dy_out * tensionScale);
                }
                newSegs.push_back(seg);
            }

            if (!newSegs.empty()) {
                ai::int16 nc = (ai::int16)newSegs.size();
                result = sAIPath->SetPathSegmentCount(targetPath, nc);
                if (result != kNoErr) continue;
                result = sAIPath->SetPathSegments(targetPath, 0, nc, newSegs.data());
                if (result != kNoErr) continue;
                sAIPath->SetPathClosed(targetPath, fit.closed);
                modifiedCount++;
            }
        }

        fLastDetectedShape = kShapeNames[(int)shapeType];

        if (modifiedCount > 0) {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            const char* userShape = kShapeNames[(int)shapeType];
            LearningEngine::Instance().RecordShapeOverride(surfaceHint, autoShapeStr, userShape);
            sAIDocument->RedrawDocument();
        }
    }
    catch (ai::Error& ex) { fprintf(stderr, "[CleanupModule] ReclassifyAs error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[CleanupModule] ReclassifyAs unknown error\n"); }
}

//========================================================================================
//  Simplify Selection — Douglas-Peucker on selected paths
//========================================================================================

void CleanupModule::SimplifySelection(double tolerance)
{
    if (tolerance < 0.01) return;

    fUndoStack.PushFrame();
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        int totalSimplified = 0, totalBefore = 0, totalAfter = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden | kArtSelected, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            bool hasSel = false;
            if (attrs & kArtSelected) { hasSel = true; }
            else {
                ai::int16 sc = 0; sAIPath->GetPathSegmentCount(art, &sc);
                for (ai::int16 s = 0; s < sc; s++) {
                    ai::int16 sel = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &sel);
                    if (sel & kSegmentPointSelected) { hasSel = true; break; }
                }
            }
            if (!hasSel) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 3) continue;

            std::vector<AIPathSegment> segs(segCount);
            result = sAIPath->GetPathSegments(art, 0, segCount, segs.data());
            if (result != kNoErr) continue;
            totalBefore += segCount;

            // Douglas-Peucker iterative
            std::vector<bool> keep(segCount, false);
            keep[0] = true; keep[segCount-1] = true;
            std::vector<std::pair<int,int>> stk;
            stk.push_back({0, segCount-1});
            while (!stk.empty()) {
                auto rng = stk.back(); stk.pop_back();
                if (rng.second - rng.first < 2) continue;
                double md = 0; int mi = rng.first;
                for (int j = rng.first+1; j < rng.second; j++) {
                    double d = PointToSegmentDist(segs[j].p, segs[rng.first].p, segs[rng.second].p);
                    if (d > md) { md = d; mi = j; }
                }
                if (md > tolerance) { keep[mi]=true; stk.push_back({rng.first,mi}); stk.push_back({mi,rng.second}); }
            }

            std::vector<AIPathSegment> ns;
            for (int j=0; j<segCount; j++) if (keep[j]) ns.push_back(segs[j]);
            ai::int16 nc = (ai::int16)ns.size();
            if (nc >= 2 && nc < segCount) {
                fUndoStack.SnapshotPath(art);
                sAIPath->SetPathSegmentCount(art, nc);
                sAIPath->SetPathSegments(art, 0, nc, ns.data());
                totalSimplified++; totalAfter += nc;
            } else { totalAfter += segCount; }
        }
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[CleanupModule] SimplifySelection: %d paths, %d → %d pts (tol=%.1f)\n",
                totalSimplified, totalBefore, totalAfter, tolerance);
        if (totalSimplified > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[CleanupModule] SimplifySelection error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[CleanupModule] SimplifySelection unknown error\n"); }
}

//========================================================================================
//  SelectSmall — select paths with arc length below threshold
//========================================================================================

void CleanupModule::SelectSmall(double threshold, int maxPoints)
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        // Deselect all paths first
        for (ai::int32 d = 0; d < numMatches; d++) {
            sAIArt->SetArtUserAttr((*matches)[d], kArtSelected, 0);
        }

        int selectedCount = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 2) continue;

            AIBoolean closed = false;
            sAIPath->GetPathClosed(art, &closed);

            // Point-count threshold: select paths with few anchors (if maxPoints > 0)
            bool belowPointThreshold = (maxPoints > 0 && segCount <= maxPoints);

            // Use MeasureSegments for accurate bezier arc length
            ai::int16 numPieces = closed ? segCount : (ai::int16)(segCount - 1);
            double totalLen = 0;
            if (numPieces > 0) {
                std::vector<AIReal> pieceLengths(numPieces);
                std::vector<AIReal> accumLengths(numPieces);
                ASErr measErr = sAIPath->MeasureSegments(art, 0, numPieces,
                                                         pieceLengths.data(), accumLengths.data());
                if (measErr == kNoErr) {
                    totalLen = (double)accumLengths[numPieces - 1]
                             + (double)pieceLengths[numPieces - 1];
                }
            }

            // Fallback: sum chord distances
            if (totalLen <= 0.0) {
                std::vector<AIPathSegment> fallbackSegs(segCount);
                sAIPath->GetPathSegments(art, 0, segCount, fallbackSegs.data());
                for (ai::int16 s = 1; s < segCount; s++) {
                    totalLen += Dist2D(fallbackSegs[s-1].p, fallbackSegs[s].p);
                }
                if (closed && segCount >= 2) {
                    totalLen += Dist2D(fallbackSegs[segCount-1].p, fallbackSegs[0].p);
                }
            }

            if (totalLen < threshold || belowPointThreshold) {
                sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
                selectedCount++;

                // Record noise candidate in LearningEngine
                double curvVar = 0.0;
                if (segCount >= 3) {
                    std::vector<AIPathSegment> segsLE(segCount);
                    sAIPath->GetPathSegments(art, 0, segCount, segsLE.data());
                    std::vector<double> angles;
                    for (ai::int16 s = 1; s < segCount - 1; s++) {
                        double v1x = segsLE[s].p.h - segsLE[s-1].p.h;
                        double v1y = segsLE[s].p.v - segsLE[s-1].p.v;
                        double v2x = segsLE[s+1].p.h - segsLE[s].p.h;
                        double v2y = segsLE[s+1].p.v - segsLE[s].p.v;
                        double cross = v1x * v2y - v1y * v2x;
                        double dot = v1x * v2x + v1y * v2y;
                        angles.push_back(std::atan2(cross, dot));
                    }
                    if (!angles.empty()) {
                        double mean = 0;
                        for (double a : angles) mean += a;
                        mean /= angles.size();
                        for (double a : angles) curvVar += (a - mean) * (a - mean);
                        curvVar /= angles.size();
                    }
                }
                LearningEngine::Instance().RecordNoiseDelete(totalLen, (int)segCount, curvVar);
            }
        }

        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[CleanupModule] SelectSmall: selected %d paths below %.1f pt (maxPoints=%d)\n",
                selectedCount, threshold, maxPoints);
        if (selectedCount > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[CleanupModule] SelectSmall error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[CleanupModule] SelectSmall unknown error\n"); }
}
