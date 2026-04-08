//========================================================================================
//  IllTool — Working Mode Lifecycle
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <algorithm>
#include <vector>

extern IllToolPlugin* gPlugin;

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

        // Dim and lock originals
        fOriginalPaths.clear();
        for (AIArtHandle art : sourcePaths) {
            AIReal prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            sAIBlendStyle->SetOpacity(art, 0.30);
            sAIArt->SetArtUserAttr(art, kArtLocked, kArtLocked);
        }

        // Step 6: Place preview path inside the working group
        fPreviewPath = PlacePreview(workGroup,
                                    fCachedShapeFit.points,
                                    fCachedShapeFit.handles,
                                    fCachedShapeFit.closed);

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

        // Select the preview path for direct editing
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
        }

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
    }

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
                sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
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
                sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
            }
        }

        int origCount = (int)fOriginalPaths.size();

        // Step 3: Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();

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
            sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
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
