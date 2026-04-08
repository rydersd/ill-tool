//========================================================================================
//  IllTool — Working Mode Lifecycle
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include "LearningEngine.h"
#include "AIToolNames.h"
#include <cstdio>
#include <cmath>
#include <algorithm>
#include <vector>

extern IllToolPlugin* gPlugin;

/** Surface type name lookup — maps BridgeGetSurfaceType() int to LearningEngine string. */
static const char* SurfaceTypeName(int surfaceType)
{
    switch (surfaceType) {
        case 0:  return "flat";
        case 1:  return "convex";
        case 2:  return "concave";
        case 3:  return "saddle";
        case 4:  return "cylindrical";
        default: return "unknown";
    }
}

//========================================================================================
//  Average Selection
//========================================================================================

/*
    AverageSelection — CEP-faithful pipeline:
    1. Collect ALL selected anchor [x,y] from all paths
    2. sortByPCA — order by principal component
    3. classifyShape — identify as line/arc/L/rect/S-curve/ellipse/freeform
    4. precomputeLOD — 20 levels of Douglas-Peucker with inflection preservation
    5. placePreview — create new clean path with bezier handles
    6. Enter working mode (dim originals, enter isolation on preview group)
    7. User adjusts tension/simplification via slider (reads LOD cache)
    8. Confirm → delete originals, promote preview. Cancel → restore originals.
*/
void IllToolPlugin::AverageSelection()
{
    try {
        // Step 1: Collect all selected anchor positions
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] AverageSelection: no path art found\n");
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
                // Track unique source paths for dimming
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
            fprintf(stderr, "[IllTool] AverageSelection: need 2+ selected anchors (found %d)\n",
                    (int)anchors.size());
            return;
        }

        fprintf(stderr, "[IllTool] AverageSelection: collected %d anchors from %d paths\n",
                (int)anchors.size(), (int)sourcePaths.size());

        // Step 2: Sort by PCA — orders points along dominant direction
        fCachedSortedPoints = SortByPCA(anchors);
        fprintf(stderr, "[IllTool] AverageSelection: PCA sorted %d points\n",
                (int)fCachedSortedPoints.size());

        // Step 3: Classify shape — identify type + generate fitted output
        fCachedShapeFit = ClassifyPoints(fCachedSortedPoints);
        fprintf(stderr, "[IllTool] AverageSelection: classified as %s (conf=%.2f, %d output pts)\n",
                kShapeNames[(int)fCachedShapeFit.shape], fCachedShapeFit.confidence,
                (int)fCachedShapeFit.points.size());

        // Step 4: Precompute LOD levels for instant slider scrubbing
        fLODCache = PrecomputeLOD(fCachedSortedPoints, 20,
                                  &fCachedShapeFit);
        fprintf(stderr, "[IllTool] AverageSelection: precomputed %d LOD levels\n",
                (int)fLODCache.size());

        // Step 5: Enter working mode — dim originals, create working group
        if (fInWorkingMode) {
            fprintf(stderr, "[IllTool] AverageSelection: already in working mode — cancelling first\n");
            CancelWorkingMode();
        }

        if (!sAIBlendStyle) {
            fprintf(stderr, "[IllTool] AverageSelection: AIBlendStyleSuite not available\n");
            return;
        }

        // Find or create Working layer + group
        // (reuse the same pattern as EnterWorkingMode)
        AIArtHandle layerGroup = nullptr;
        {
            AILayerHandle layer = nullptr;
            ai::UnicodeString workingTitle("Working");
            result = sAILayer->GetLayerByTitle(&layer, workingTitle);
            if (result != kNoErr || layer == nullptr) {
                result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
                if (result != kNoErr || layer == nullptr) {
                    fprintf(stderr, "[IllTool] AverageSelection: failed to create Working layer\n");
                    return;
                }
                sAILayer->SetLayerTitle(layer, workingTitle);
            }
            result = sAIArt->GetFirstArtOfLayer(layer, &layerGroup);
            if (result != kNoErr || !layerGroup) {
                fprintf(stderr, "[IllTool] AverageSelection: failed to get layer group\n");
                return;
            }
        }

        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &workGroup);
        if (result != kNoErr || !workGroup) {
            fprintf(stderr, "[IllTool] AverageSelection: failed to create working group\n");
            return;
        }

        // Dim and lock originals — hide them so only the preview is visible
        fOriginalPaths.clear();
        for (AIArtHandle art : sourcePaths) {
            AIReal prevOpacity = 1.0;
            if (sAIBlendStyle) prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            // Set opacity to 30% AND hide the art
            if (sAIBlendStyle) sAIBlendStyle->SetOpacity(art, 0.30);
            sAIArt->SetArtUserAttr(art, kArtLocked | kArtHidden, kArtLocked | kArtHidden);
            fprintf(stderr, "[IllTool] AverageSelection: dimmed+hid original path %p\n", (void*)art);
        }

        // Step 6: Build the preview — ALWAYS minimal points
        //
        // The user expectation: first point, last point, maybe one inflection
        // point at the steepest curve. 2-3 points with smooth bezier handles.
        // NOT a simplified version of all points — a FITTED primitive.
        //
        // If classification found a confident shape (arc, line, etc.), use its
        // fitted output (already minimal). Otherwise, force a simple curve:
        // first, inflection, last.

        std::vector<AIRealPoint> previewPts;
        std::vector<HandlePair> previewHandles;
        bool previewClosed = fCachedShapeFit.closed;

        if (fCachedShapeFit.shape != BridgeShapeType::Freeform &&
            fCachedShapeFit.confidence > 0.15 &&
            (int)fCachedShapeFit.points.size() <= 6) {
            // Classified shape — use its fitted output (2-4 points)
            previewPts = fCachedShapeFit.points;
            previewHandles = fCachedShapeFit.handles;
            fprintf(stderr, "[IllTool] AverageSelection: using %s fit (%d pts, conf=%.2f)\n",
                    kShapeNames[(int)fCachedShapeFit.shape],
                    (int)previewPts.size(), fCachedShapeFit.confidence);
        } else {
            // Freeform or low confidence — force minimal curve:
            // first point, steepest curve point, last point
            auto& sorted = fCachedSortedPoints;
            int n = (int)sorted.size();
            AIRealPoint first = sorted[0];
            AIRealPoint last = sorted[n - 1];

            // Find the point with maximum perpendicular distance from first→last line
            // (the steepest curve point / inflection)
            double maxDist = 0;
            int maxIdx = n / 2; // fallback to midpoint
            for (int i = 1; i < n - 1; i++) {
                double abx = last.h - first.h, aby = last.v - first.v;
                double apx = sorted[i].h - first.h, apy = sorted[i].v - first.v;
                double abLen = sqrt(abx * abx + aby * aby);
                double dist = (abLen > 1e-6) ? fabs(apx * aby - apy * abx) / abLen : 0;
                if (dist > maxDist) { maxDist = dist; maxIdx = i; }
            }

            double span = sqrt((last.h-first.h)*(last.h-first.h) + (last.v-first.v)*(last.v-first.v));
            bool needMidpoint = (maxDist > span * 0.05); // only add if curve is significant

            if (needMidpoint) {
                AIRealPoint mid = sorted[maxIdx];
                previewPts = { first, mid, last };
                // Catmull-Rom handles for 3-point open curve
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
                // Straight line — no handles needed
            }

            previewClosed = false;
            fprintf(stderr, "[IllTool] AverageSelection: forced %d-point curve (maxDist=%.1f, span=%.1f)\n",
                    (int)previewPts.size(), maxDist, span);
        }

        // Perspective projection if enabled
        if (BridgeGetSnapToPerspective() && fPerspectiveGrid.valid) {
            previewPts = ProjectPointsThroughPerspective(previewPts, 0);
            for (auto& h : previewHandles) {
                auto projL = ProjectPointsThroughPerspective({h.left}, 0);
                auto projR = ProjectPointsThroughPerspective({h.right}, 0);
                if (!projL.empty()) h.left = projL[0];
                if (!projR.empty()) h.right = projR[0];
            }
        }

        fPreviewPath = PlacePreview(workGroup, previewPts, previewHandles, previewClosed);

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

        // Step 7: Enter isolation mode on the working group
        if (sAIIsolationMode && !sAIIsolationMode->IsInIsolationMode()) {
            if (sAIIsolationMode->CanIsolateArt(workGroup)) {
                result = sAIIsolationMode->EnterIsolationMode(workGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[IllTool] AverageSelection: entered isolation on working group\n");
                }
            }
        }

        // Select the preview path and all its segments for direct editing
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);

            // Select all segments so native handles are visible immediately
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
            for (ai::int16 s = 0; s < segCount; s++) {
                sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
            }
            fprintf(stderr, "[IllTool] AverageSelection: selected all %d segments on preview path\n",
                    (int)segCount);

            // Activate the Direct Selection tool so user gets native Illustrator
            // handles immediately — no need to switch tools manually
            if (sAITool) {
                AIToolType directSelectNum = 0;
                ASErr toolErr = sAITool->GetToolNumberFromName(kDirectSelectTool, &directSelectNum);
                if (toolErr == kNoErr) {
                    AIToolHandle directSelectHandle = nullptr;
                    toolErr = sAITool->GetToolHandleFromNumber(directSelectNum, &directSelectHandle);
                    if (toolErr == kNoErr && directSelectHandle) {
                        sAITool->SetSelectedTool(directSelectHandle);
                        fprintf(stderr, "[IllTool] AverageSelection: activated Direct Selection tool\n");
                    } else {
                        fprintf(stderr, "[IllTool] AverageSelection: could not get Direct Selection handle (err=%d)\n",
                                (int)toolErr);
                    }
                } else {
                    fprintf(stderr, "[IllTool] AverageSelection: could not find Direct Selection tool (err=%d)\n",
                            (int)toolErr);
                }
            }
        }

        // Compute rotated bounding box from PCA direction for the custom bbox overlay
        ComputeBoundingBox();

        // Update the detected shape label
        fLastDetectedShape = kShapeNames[(int)fCachedShapeFit.shape];

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool] AverageSelection: complete — %d anchors → %s preview with %d points\n",
                (int)anchors.size(), fLastDetectedShape,
                (int)fCachedShapeFit.points.size());
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] AverageSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] AverageSelection unknown error\n");
    }
}

//========================================================================================
//  Apply LOD Level — slider scrubbing over precomputed cache
//========================================================================================

void IllToolPlugin::ApplyLODLevel(int level)
{
    if (fLODCache.empty() || !fInWorkingMode || !fWorkingGroup) {
        fprintf(stderr, "[IllTool] ApplyLODLevel: no LOD cache or not in working mode\n");
        return;
    }

    // Find the closest cached level at or below the requested value
    const LODLevel* best = &fLODCache[0];
    for (auto& lod : fLODCache) {
        if (lod.value <= level) best = &lod;
    }

    // Delete old preview and create new one
    if (fPreviewPath) {
        sAIArt->DisposeArt(fPreviewPath);
        fPreviewPath = nullptr;
    }

    fPreviewPath = PlacePreview(fWorkingGroup, best->points, best->handles,
                                fCachedShapeFit.closed);

    if (fPreviewPath) {
        sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);

        // Select all segments so native handles remain visible after LOD change
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        for (ai::int16 s = 0; s < segCount; s++) {
            sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
        }
    }

    // Recompute bounding box for the updated preview
    ComputeBoundingBox();

    sAIDocument->RedrawDocument();
    fprintf(stderr, "[IllTool] ApplyLODLevel: level=%d → %d points\n",
            level, (int)best->points.size());
}

//========================================================================================
//  Enter isolation mode for the parent group(s) of selected paths
//========================================================================================

void IllToolPlugin::EnterIsolationForSelection()
{
    if (!sAIIsolationMode) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection: AIIsolationModeSuite not available\n");
        return;
    }

    // Already in isolation mode? Don't double-enter.
    if (sAIIsolationMode->IsInIsolationMode()) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection: already in isolation mode\n");
        return;
    }

    try {
        // Find the first selected path and get its parent group
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] EnterIsolationForSelection: no paths found\n");
            return;
        }

        // Find the first path that has selected segments
        AIArtHandle targetGroup = nullptr;
        for (ai::int32 i = 0; i < numMatches && !targetGroup; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) continue;

            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    // Found a selected segment — get its parent
                    AIArtHandle parent = nullptr;
                    result = sAIArt->GetArtParent(art, &parent);
                    if (result == kNoErr && parent) {
                        // Check if the parent is a group (not a layer)
                        short artType = kUnknownArt;
                        sAIArt->GetArtType(parent, &artType);
                        if (artType == kGroupArt) {
                            targetGroup = parent;
                        }
                    }
                    break;
                }
            }
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        if (targetGroup) {
            // Verify isolation is legal for this art
            if (sAIIsolationMode->CanIsolateArt(targetGroup)) {
                result = sAIIsolationMode->EnterIsolationMode(targetGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[IllTool] Entered isolation mode for parent group\n");
                } else {
                    fprintf(stderr, "[IllTool] EnterIsolationMode failed: %d\n", (int)result);
                }
            } else {
                fprintf(stderr, "[IllTool] Cannot isolate target group (CanIsolateArt returned false)\n");
            }
        } else {
            fprintf(stderr, "[IllTool] EnterIsolationForSelection: no isolatable parent group found\n");
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection unknown error\n");
    }
}

//========================================================================================
//  C-callable wrappers for panel buttons
//========================================================================================

void PluginAverageSelection()
{
    if (gPlugin) {
        gPlugin->AverageSelection();
    }
}

void PluginApplyWorkingMode(bool deleteOriginals)
{
    if (gPlugin) {
        gPlugin->ApplyWorkingMode(deleteOriginals);
    }
}

void PluginCancelWorkingMode()
{
    if (gPlugin) {
        gPlugin->CancelWorkingMode();
    }
}

//========================================================================================
//  C-callable: count selected anchor points (for panel polling)
//========================================================================================

int PluginGetSelectedAnchorCount()
{
    // Return the cached count from the selection-changed notifier.
    // SDK calls (GetMatchingArt) don't work from NSTimer callbacks —
    // they return DOC? error because the callback runs outside the SDK
    // message dispatch context. The notifier updates fLastKnownSelectionCount
    // during the SDK's own message dispatch, where the calls work.
    if (!gPlugin) return 0;
    return gPlugin->fLastKnownSelectionCount;

}

//========================================================================================
//  Working Mode — duplicate, dim originals, isolate working group
//========================================================================================

/*
    FindOrCreateWorkingLayer — find a layer titled "Working", or create one at the top.
    Returns the AIArtHandle for the layer group (the container for art on that layer).
*/
static AIArtHandle FindOrCreateWorkingLayer()
{
    if (!sAILayer || !sAIArt) return nullptr;

    ASErr result = kNoErr;
    AILayerHandle layer = nullptr;

    // Try to find existing "Working" layer
    ai::UnicodeString workingTitle("Working");
    result = sAILayer->GetLayerByTitle(&layer, workingTitle);

    if (result != kNoErr || layer == nullptr) {
        // Create a new layer at the top of the stack
        result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
        if (result != kNoErr || layer == nullptr) {
            fprintf(stderr, "[IllTool] Failed to create Working layer: %d\n", (int)result);
            return nullptr;
        }
        result = sAILayer->SetLayerTitle(layer, workingTitle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] Failed to set Working layer title: %d\n", (int)result);
        }
        fprintf(stderr, "[IllTool] Created 'Working' layer\n");
    } else {
        fprintf(stderr, "[IllTool] Found existing 'Working' layer\n");
    }

    // Get the layer's art group (container for art on that layer)
    AIArtHandle layerGroup = nullptr;
    result = sAIArt->GetFirstArtOfLayer(layer, &layerGroup);
    if (result != kNoErr || layerGroup == nullptr) {
        fprintf(stderr, "[IllTool] Failed to get Working layer art group: %d\n", (int)result);
        return nullptr;
    }

    return layerGroup;
}

void IllToolPlugin::EnterWorkingMode()
{
    if (fInWorkingMode) {
        fprintf(stderr, "[IllTool] EnterWorkingMode: already in working mode — no-op\n");
        return;
    }

    if (!sAIBlendStyle) {
        fprintf(stderr, "[IllTool] EnterWorkingMode: AIBlendStyleSuite not available\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: begin\n");

        // Step 1: Collect all paths that have any selected segments
        // NOTE: Using whole-document GetMatchingArt here (NOT isolation-aware)
        // because we're collecting originals BEFORE entering isolation mode
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: calling GetMatchingArt (whole doc)\n");
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: GetMatchingArt returned err=%d, numMatches=%d\n",
                (int)result, (int)numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: no path art found — aborting\n");
            return;
        }

        // Find paths with selected segments
        std::vector<AIArtHandle> selectedPaths;
        int totalChecked = 0;
        int lockedHiddenSkipped = 0;
        int emptySkipped = 0;
        int noSelectedSegs = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            totalChecked++;

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                lockedHiddenSkipped++;
                continue;
            }

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) {
                emptySkipped++;
                continue;
            }

            bool hasSelected = false;
            int selectedInThisPath = 0;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    hasSelected = true;
                    selectedInThisPath++;
                }
            }

            if (hasSelected) {
                fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: path[%d]=%p has %d/%d selected segs\n",
                        (int)i, (void*)art, selectedInThisPath, (int)segCount);
                selectedPaths.push_back(art);
            } else {
                noSelectedSegs++;
            }
        }

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: scan summary — checked=%d, locked/hidden=%d, empty=%d, no-sel=%d, WITH-sel=%zu\n",
                totalChecked, lockedHiddenSkipped, emptySkipped, noSelectedSegs, selectedPaths.size());

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        if (selectedPaths.empty()) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: no paths with selected segments — aborting\n");
            return;
        }

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: %zu paths with selected segments\n",
                selectedPaths.size());

        // Step 2: Find or create the "Working" layer
        AIArtHandle layerGroup = FindOrCreateWorkingLayer();
        if (!layerGroup) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: could not get Working layer group — aborting\n");
            return;
        }
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: layerGroup=%p\n", (void*)layerGroup);

        // Step 3: Create a group inside the Working layer to hold duplicates
        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &workGroup);
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: NewArt(group) err=%d, workGroup=%p\n",
                (int)result, (void*)workGroup);
        if (result != kNoErr || !workGroup) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: failed to create working group — aborting\n");
            return;
        }

        // Step 4: For each selected path, store original state, duplicate, dim, lock
        fOriginalPaths.clear();
        int dupeIndex = 0;
        for (AIArtHandle art : selectedPaths) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: processing path %d/%zu (art=%p)\n",
                    dupeIndex, selectedPaths.size(), (void*)art);

            // Store the original's current opacity
            AIReal prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            fprintf(stderr, "[IllTool DEBUG]   prevOpacity=%.2f\n", (double)prevOpacity);

            // Duplicate the path into the working group
            AIArtHandle dupe = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, workGroup, &dupe);
            fprintf(stderr, "[IllTool DEBUG]   DuplicateArt: err=%d, dupe=%p\n",
                    (int)result, (void*)dupe);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   DuplicateArt FAILED — skipping this path\n");
                continue;
            }

            // Copy selection state from original to duplicate
            {
                ai::int16 origSegCount = 0;
                sAIPath->GetPathSegmentCount(art, &origSegCount);
                ai::int16 dupeSegCount = 0;
                sAIPath->GetPathSegmentCount(dupe, &dupeSegCount);
                fprintf(stderr, "[IllTool DEBUG]   origSegCount=%d, dupeSegCount=%d\n",
                        (int)origSegCount, (int)dupeSegCount);
                if (origSegCount != dupeSegCount) {
                    fprintf(stderr, "[IllTool DEBUG]   WARNING: segment count MISMATCH after DuplicateArt!\n");
                }
                ai::int16 copyCount = std::min(origSegCount, dupeSegCount);
                int copiedSelections = 0;
                for (ai::int16 s = 0; s < copyCount; s++) {
                    ai::int16 selState = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &selState);
                    if (selState != kSegmentNotSelected) {
                        ASErr selErr = sAIPath->SetPathSegmentSelected(dupe, s, selState);
                        if (selErr == kNoErr) {
                            copiedSelections++;
                        } else {
                            fprintf(stderr, "[IllTool DEBUG]   SetPathSegmentSelected(dupe, %d) FAILED: err=%d\n",
                                    (int)s, (int)selErr);
                        }
                    }
                }
                fprintf(stderr, "[IllTool DEBUG]   copied %d segment selections to dupe\n", copiedSelections);
            }

            // Mark the duplicate as selected in the document selection model
            // (segment-level selection alone is not enough for queries that
            //  check art-level selection attributes)
            result = sAIArt->SetArtUserAttr(dupe, kArtSelected, kArtSelected);
            fprintf(stderr, "[IllTool DEBUG]   SetArtUserAttr(kArtSelected) on dupe: err=%d\n", (int)result);

            // Dim the original to 30% opacity
            result = sAIBlendStyle->SetOpacity(art, 0.30);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   SetOpacity(0.30) on original FAILED: err=%d\n", (int)result);
            } else {
                fprintf(stderr, "[IllTool DEBUG]   SetOpacity(0.30) on original: OK\n");
            }

            // Lock the original so it can't be accidentally selected
            result = sAIArt->SetArtUserAttr(art, kArtLocked, kArtLocked);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   SetArtUserAttr(kArtLocked) on original FAILED: err=%d\n", (int)result);
            } else {
                fprintf(stderr, "[IllTool DEBUG]   locked original: OK\n");
            }

            dupeIndex++;
        }

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: %zu originals dimmed, working group=%p, fInWorkingMode=true\n",
                fOriginalPaths.size(), (void*)fWorkingGroup);

        // Step 5: Enter isolation mode on the working group
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: checking isolation mode — sAIIsolationMode=%p\n",
                (void*)sAIIsolationMode);
        if (sAIIsolationMode && !sAIIsolationMode->IsInIsolationMode()) {
            bool canIsolate = sAIIsolationMode->CanIsolateArt(workGroup);
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: CanIsolateArt(workGroup)=%s\n",
                    canIsolate ? "true" : "false");
            if (canIsolate) {
                result = sAIIsolationMode->EnterIsolationMode(workGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: entered isolation on working group — SUCCESS\n");
                } else {
                    fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: EnterIsolationMode FAILED: err=%d\n",
                            (int)result);
                }
            } else {
                fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: cannot isolate working group\n");
            }
        } else if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: already in isolation mode — skipping\n");
        } else {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: sAIIsolationMode is NULL — cannot isolate\n");
        }

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: complete\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] EnterWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] EnterWorkingMode unknown error\n");
    }
}

void IllToolPlugin::ApplyWorkingMode(bool deleteOriginals)
{
    if (!fInWorkingMode) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode: not in working mode — no-op\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool] ApplyWorkingMode: begin (deleteOriginals=%s)\n",
                deleteOriginals ? "true" : "false");

        // Step 1: Exit isolation mode
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            ASErr result = sAIIsolationMode->ExitIsolationMode();
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] ApplyWorkingMode: exited isolation mode\n");
            } else {
                fprintf(stderr, "[IllTool] ApplyWorkingMode: ExitIsolationMode failed: %d\n",
                        (int)result);
            }
        }

        // Step 2: Handle originals
        for (auto& rec : fOriginalPaths) {
            if (deleteOriginals) {
                // Unlock first (DisposeArt may fail on locked art)
                sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
                ASErr result = sAIArt->DisposeArt(rec.art);
                if (result != kNoErr) {
                    fprintf(stderr, "[IllTool] ApplyWorkingMode: DisposeArt failed: %d\n",
                            (int)result);
                }
            } else {
                // Restore opacity and unlock
                if (sAIBlendStyle) {
                    sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
                }
                sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
            }
        }

        int origCount = (int)fOriginalPaths.size();

        // Record simplification level in LearningEngine before clearing cached data
        if (!fCachedSortedPoints.empty() && fPreviewPath) {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            int pointsBefore = (int)fCachedSortedPoints.size();
            int pointsAfter = 0;

            // Count segments on the preview path to get final point count
            ai::int16 previewSegCount = 0;
            if (sAIPath && fPreviewPath) {
                sAIPath->GetPathSegmentCount(fPreviewPath, &previewSegCount);
                pointsAfter = (int)previewSegCount;
            }

            // Determine the LOD level that's currently applied:
            // find the LOD entry matching the preview's point count
            double lodLevel = 50.0;  // default if no match found
            for (const auto& lod : fLODCache) {
                if ((int)lod.points.size() == pointsAfter) {
                    lodLevel = (double)lod.value;
                    break;
                }
            }

            LearningEngine::Instance().RecordSimplifyLevel(
                surfaceHint, lodLevel, pointsBefore, pointsAfter);
            fprintf(stderr, "[IllTool Learning] Simplify level recorded: surface=%s level=%.0f pts=%d->%d\n",
                    surfaceHint, lodLevel, pointsBefore, pointsAfter);
        }

        // Step 3: Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;

        // Step 4: Redraw
        sAIDocument->RedrawDocument();

        fprintf(stderr, "[IllTool] ApplyWorkingMode: complete (%d originals %s)\n",
                origCount, deleteOriginals ? "deleted" : "restored");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode unknown error\n");
    }
}

void IllToolPlugin::CancelWorkingMode()
{
    if (!fInWorkingMode) {
        fprintf(stderr, "[IllTool] CancelWorkingMode: not in working mode — no-op\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool] CancelWorkingMode: begin\n");

        // Step 1: Exit isolation mode
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            ASErr result = sAIIsolationMode->ExitIsolationMode();
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] CancelWorkingMode: exited isolation mode\n");
            } else {
                fprintf(stderr, "[IllTool] CancelWorkingMode: ExitIsolationMode failed: %d\n",
                        (int)result);
            }
        }

        // Step 2: Delete the working group (all duplicates)
        if (fWorkingGroup) {
            ASErr result = sAIArt->DisposeArt(fWorkingGroup);
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] CancelWorkingMode: disposed working group\n");
            } else {
                fprintf(stderr, "[IllTool] CancelWorkingMode: DisposeArt(workingGroup) failed: %d\n",
                        (int)result);
            }
        }

        // Step 3: Restore originals — unlock and restore opacity
        for (auto& rec : fOriginalPaths) {
            if (sAIBlendStyle) {
                sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
            }
            sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
        }

        int origCount = (int)fOriginalPaths.size();

        // Step 4: Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;

        // Step 5: Redraw
        sAIDocument->RedrawDocument();

        fprintf(stderr, "[IllTool] CancelWorkingMode: complete (%d originals restored)\n",
                origCount);
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] CancelWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] CancelWorkingMode unknown error\n");
    }
}

//========================================================================================
//  Bounding Box — PCA-rotated custom transform cage with circle handles
//========================================================================================

/*
    ComputeBoundingBox — builds a rotated bounding box from the preview path.
    The rotation angle comes from the PCA eigenvector (same axis used for sorting).
    Projects all path segment positions onto the PCA axes, finds min/max extents,
    then computes the 4 corners and 4 midpoints in artwork coordinates.
*/
void IllToolPlugin::ComputeBoundingBox()
{
    if (!fPreviewPath || !fInWorkingMode) {
        fBBox.visible = false;
        return;
    }

    // Read all segment anchor points from the preview path
    ai::int16 segCount = 0;
    ASErr err = sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (err != kNoErr || segCount < 2) {
        fBBox.visible = false;
        return;
    }

    std::vector<AIPathSegment> segs(segCount);
    err = sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());
    if (err != kNoErr) {
        fBBox.visible = false;
        return;
    }

    // Compute PCA eigenvector to get the dominant rotation direction
    // (same algorithm as SortByPCA but we only need the angle)
    double cx = 0, cy = 0;
    for (int i = 0; i < segCount; i++) {
        cx += segs[i].p.h;
        cy += segs[i].p.v;
    }
    cx /= segCount;
    cy /= segCount;

    double cxx = 0, cxy = 0, cyy = 0;
    for (int i = 0; i < segCount; i++) {
        double dx = segs[i].p.h - cx;
        double dy = segs[i].p.v - cy;
        cxx += dx * dx;
        cxy += dx * dy;
        cyy += dy * dy;
    }

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
    double vlen = sqrt(vx * vx + vy * vy);
    if (vlen > 1e-12) { vx /= vlen; vy /= vlen; }

    // PCA rotation angle
    fBBox.rotation = atan2(vy, vx);

    // The perpendicular axis (secondary PCA component)
    double px = -vy;
    double py = vx;

    // Project all anchor points onto PCA axes to find min/max extents
    double minPrimary = 1e20, maxPrimary = -1e20;
    double minSecondary = 1e20, maxSecondary = -1e20;

    for (int i = 0; i < segCount; i++) {
        double dx = segs[i].p.h - cx;
        double dy = segs[i].p.v - cy;
        double projPrimary   = dx * vx + dy * vy;
        double projSecondary = dx * px + dy * py;
        if (projPrimary < minPrimary) minPrimary = projPrimary;
        if (projPrimary > maxPrimary) maxPrimary = projPrimary;
        if (projSecondary < minSecondary) minSecondary = projSecondary;
        if (projSecondary > maxSecondary) maxSecondary = projSecondary;
    }

    // Add a small padding (4pt) around the bbox for visual clarity
    double pad = 4.0;
    minPrimary -= pad; maxPrimary += pad;
    minSecondary -= pad; maxSecondary += pad;

    // Compute 4 corners in artwork coordinates (counter-clockwise order):
    //   corner[0] = min primary, min secondary
    //   corner[1] = max primary, min secondary
    //   corner[2] = max primary, max secondary
    //   corner[3] = min primary, max secondary
    double cornerProj[4][2] = {
        { minPrimary, minSecondary },
        { maxPrimary, minSecondary },
        { maxPrimary, maxSecondary },
        { minPrimary, maxSecondary }
    };

    for (int i = 0; i < 4; i++) {
        fBBox.corners[i].h = (AIReal)(cx + cornerProj[i][0] * vx + cornerProj[i][1] * px);
        fBBox.corners[i].v = (AIReal)(cy + cornerProj[i][0] * vy + cornerProj[i][1] * py);
    }

    // Compute 4 midpoints (one per edge)
    for (int i = 0; i < 4; i++) {
        int j = (i + 1) % 4;
        fBBox.midpoints[i].h = (AIReal)((fBBox.corners[i].h + fBBox.corners[j].h) * 0.5);
        fBBox.midpoints[i].v = (AIReal)((fBBox.corners[i].v + fBBox.corners[j].v) * 0.5);
    }

    // Center
    fBBox.center.h = (AIReal)cx;
    fBBox.center.v = (AIReal)cy;

    fBBox.visible = true;
    fBBox.dragHandle = -1;

    fprintf(stderr, "[IllTool] ComputeBoundingBox: rotation=%.1f° center=(%.1f,%.1f)\n",
            fBBox.rotation * 180.0 / M_PI, cx, cy);
}

//========================================================================================
//  Draw bounding box overlay — circle handles at corners + midpoints
//========================================================================================

/** Helper: draw a filled circle handle with an outline at a view point. */
static void DrawBBoxHandle(AIAnnotatorDrawer* drawer, AIPoint center, int radius,
                           const AIRGBColor& fillColor, const AIRGBColor& strokeColor)
{
    AIRect r;
    r.left   = center.h - radius;
    r.top    = center.v - radius;
    r.right  = center.h + radius;
    r.bottom = center.v + radius;

    // Fill
    sAIAnnotatorDrawer->SetColor(drawer, fillColor);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, true);
    // Stroke
    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, false);
}

void IllToolPlugin::DrawBoundingBoxOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;
    if (!fBBox.visible || !fInWorkingMode) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Bbox edge color: teal/cyan to distinguish from perspective grid colors
    AIRGBColor edgeColor;
    edgeColor.red   = (ai::uint16)(0.10 * 65535);
    edgeColor.green = (ai::uint16)(0.70 * 65535);
    edgeColor.blue  = (ai::uint16)(0.85 * 65535);

    // Handle fill: white
    AIRGBColor handleFill;
    handleFill.red   = (ai::uint16)(1.0 * 65535);
    handleFill.green = (ai::uint16)(1.0 * 65535);
    handleFill.blue  = (ai::uint16)(1.0 * 65535);

    // Handle stroke: same as edge
    AIRGBColor handleStroke = edgeColor;

    // Active/dragged handle color: orange
    AIRGBColor activeHandleFill;
    activeHandleFill.red   = (ai::uint16)(1.0 * 65535);
    activeHandleFill.green = (ai::uint16)(0.6 * 65535);
    activeHandleFill.blue  = (ai::uint16)(0.1 * 65535);

    // --- Draw edges ---
    sAIAnnotatorDrawer->SetColor(drawer, edgeColor);
    sAIAnnotatorDrawer->SetOpacity(drawer, 0.7);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);

    AIPoint viewCorners[4];
    bool cornersOK = true;
    for (int i = 0; i < 4; i++) {
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &fBBox.corners[i], &viewCorners[i]) != kNoErr) {
            cornersOK = false;
            break;
        }
    }
    if (!cornersOK) return;

    // Draw 4 edges
    for (int i = 0; i < 4; i++) {
        int j = (i + 1) % 4;
        sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[i], viewCorners[j]);
    }

    // --- Draw corner handles (circles, radius 5) ---
    int cornerRadius = 5;
    int midpointRadius = 4;

    for (int i = 0; i < 4; i++) {
        const AIRGBColor& fill = (fBBox.dragHandle == i) ? activeHandleFill : handleFill;
        DrawBBoxHandle(drawer, viewCorners[i], cornerRadius, fill, handleStroke);
    }

    // --- Draw midpoint handles (smaller circles, radius 4) ---
    for (int i = 0; i < 4; i++) {
        AIPoint viewMid;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &fBBox.midpoints[i], &viewMid) != kNoErr) continue;

        const AIRGBColor& fill = (fBBox.dragHandle == (i + 4)) ? activeHandleFill : handleFill;
        DrawBBoxHandle(drawer, viewMid, midpointRadius, fill, handleStroke);
    }

    // Reset
    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
}

//========================================================================================
//  Hit-test bounding box handles
//========================================================================================

int IllToolPlugin::HitTestBBoxHandle(AIRealPoint artPt, double hitRadius)
{
    if (!fBBox.visible) return -1;

    // Check corners first (0-3)
    for (int i = 0; i < 4; i++) {
        double dx = artPt.h - fBBox.corners[i].h;
        double dy = artPt.v - fBBox.corners[i].v;
        if (sqrt(dx * dx + dy * dy) <= hitRadius) {
            return i;
        }
    }

    // Check midpoints (4-7)
    for (int i = 0; i < 4; i++) {
        double dx = artPt.h - fBBox.midpoints[i].h;
        double dy = artPt.v - fBBox.midpoints[i].v;
        if (sqrt(dx * dx + dy * dy) <= hitRadius) {
            return i + 4;
        }
    }

    return -1;
}

//========================================================================================
//  Apply bounding box transform — scale path based on handle drag
//========================================================================================

/*
    ApplyBBoxTransform — transforms the preview path in response to dragging
    a bbox handle. Corner handles scale uniformly from the opposite corner.
    Midpoint handles scale along one axis (constrained to the PCA axes).

    The transform is computed as:
    1. Find the anchor point (opposite corner or opposite midpoint)
    2. Compute original distance from anchor to original handle position
    3. Compute new distance from anchor to current mouse position (projected onto axis)
    4. Scale all path segments relative to the anchor point
*/
void IllToolPlugin::ApplyBBoxTransform(int handleIdx, AIRealPoint newPos)
{
    if (!fPreviewPath || handleIdx < 0 || handleIdx > 7) return;

    // Read current path segments
    ai::int16 segCount = 0;
    ASErr err = sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (err != kNoErr || segCount < 2) return;

    std::vector<AIPathSegment> segs(segCount);
    err = sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());
    if (err != kNoErr) return;

    // PCA axes
    double cosR = cos(fBBox.rotation);
    double sinR = sin(fBBox.rotation);
    // Primary axis: (cosR, sinR)
    // Secondary axis: (-sinR, cosR)

    // Find anchor point (opposite corner/midpoint)
    AIRealPoint anchor;
    if (handleIdx < 4) {
        // Corner: anchor is the opposite corner
        anchor = fBBox.corners[(handleIdx + 2) % 4];
    } else {
        // Midpoint: anchor is the opposite midpoint
        anchor = fBBox.midpoints[((handleIdx - 4) + 2) % 4];
    }

    // Original handle position
    AIRealPoint origHandle;
    if (handleIdx < 4) {
        origHandle = fBBox.corners[handleIdx];
    } else {
        origHandle = fBBox.midpoints[handleIdx - 4];
    }

    // Project into PCA space relative to anchor
    double origDx = origHandle.h - anchor.h;
    double origDy = origHandle.v - anchor.v;
    double origPrimary   = origDx * cosR + origDy * sinR;
    double origSecondary = origDx * (-sinR) + origDy * cosR;

    double newDx = newPos.h - anchor.h;
    double newDy = newPos.v - anchor.v;
    double newPrimary   = newDx * cosR + newDy * sinR;
    double newSecondary = newDx * (-sinR) + newDy * cosR;

    // Compute scale factors along each PCA axis
    double scalePrimary = 1.0;
    double scaleSecondary = 1.0;

    if (handleIdx < 4) {
        // Corner handle: scale both axes
        if (fabs(origPrimary) > 1e-6) scalePrimary = newPrimary / origPrimary;
        if (fabs(origSecondary) > 1e-6) scaleSecondary = newSecondary / origSecondary;
    } else {
        // Midpoint handle: scale only along the axis perpendicular to the edge
        int edgeIdx = handleIdx - 4;
        // Edges 0 and 2 are along the primary axis → midpoint scales secondary
        // Edges 1 and 3 are along the secondary axis → midpoint scales primary
        if (edgeIdx == 0 || edgeIdx == 2) {
            if (fabs(origSecondary) > 1e-6) scaleSecondary = newSecondary / origSecondary;
        } else {
            if (fabs(origPrimary) > 1e-6) scalePrimary = newPrimary / origPrimary;
        }
    }

    // Clamp scale factors to prevent degenerate transforms
    if (fabs(scalePrimary) < 0.01) scalePrimary = 0.01;
    if (fabs(scaleSecondary) < 0.01) scaleSecondary = 0.01;

    // Apply transform to all path segments
    for (int i = 0; i < segCount; i++) {
        // Transform each of the 3 points per segment: in, p, out
        AIRealPoint* pts[3] = { &segs[i].in, &segs[i].p, &segs[i].out };
        for (int j = 0; j < 3; j++) {
            // Project into PCA space relative to anchor
            double dx = pts[j]->h - anchor.h;
            double dy = pts[j]->v - anchor.v;
            double projP = dx * cosR + dy * sinR;
            double projS = dx * (-sinR) + dy * cosR;

            // Scale
            projP *= scalePrimary;
            projS *= scaleSecondary;

            // Unproject back to artwork space
            pts[j]->h = (AIReal)(anchor.h + projP * cosR + projS * (-sinR));
            pts[j]->v = (AIReal)(anchor.v + projP * sinR + projS * cosR);
        }
    }

    // Write back
    sAIPath->SetPathSegments(fPreviewPath, 0, segCount, segs.data());

    // Recompute bounding box from the transformed path
    ComputeBoundingBox();
}
