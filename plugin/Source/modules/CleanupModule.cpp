//========================================================================================
//  CleanupModule — Shape cleanup implementation
//
//  Ported from IllToolWorkingMode.cpp and IllToolShapes.cpp.
//  All pure math delegated to ShapeUtils.h.
//========================================================================================

#include "CleanupModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "ShapeUtils.h"
#include "PerspectiveModule.h"
#include "LearningEngine.h"
#include "HttpBridge.h"
#include "AIToolNames.h"

#include <cstdio>
#include <cmath>
#include <algorithm>
#include <vector>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  UndoStack implementation (standalone, from IllToolModule.h)
//========================================================================================

void UndoStack::PushFrame()
{
    stack.push_back({});
    while ((int)stack.size() > kMaxFrames) {
        stack.erase(stack.begin());
    }
    fprintf(stderr, "[UndoStack] pushed frame (%zu frames total)\n", stack.size());
}

void UndoStack::SnapshotPath(AIArtHandle art)
{
    if (stack.empty()) return;
    PathSnapshot snap;
    snap.art = art;
    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(art, &segCount);
    snap.segments.resize(segCount);
    sAIPath->GetPathSegments(art, 0, segCount, snap.segments.data());
    sAIPath->GetPathClosed(art, &snap.closed);
    stack.back().push_back(std::move(snap));
}

int UndoStack::Undo()
{
    if (stack.empty()) return 0;

    auto& frame = stack.back();
    int restored = 0;
    for (auto& snap : frame) {
        short artType = 0;
        ASErr err = sAIArt->GetArtType(snap.art, &artType);
        if (err != kNoErr || artType != kPathArt) continue;
        ai::int16 nc = (ai::int16)snap.segments.size();
        sAIPath->SetPathSegmentCount(snap.art, nc);
        sAIPath->SetPathSegments(snap.art, 0, nc, snap.segments.data());
        sAIPath->SetPathClosed(snap.art, snap.closed);
        restored++;
    }
    stack.pop_back();
    fprintf(stderr, "[UndoStack] restored %d paths (%zu frames remain)\n",
            restored, stack.size());
    return restored;
}

//========================================================================================
//  IllToolModule::InvalidateFullView — shared across all modules
//========================================================================================

void IllToolModule::InvalidateFullView()
{
    try {
        if (!sAIDocumentView) return;
        AIRealRect viewBounds = {0, 0, 0, 0};
        ASErr result = sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
        if (result == kNoErr && sAIAnnotator) {
            AIRealPoint topLeft = { viewBounds.left, viewBounds.top };
            AIRealPoint botRight = { viewBounds.right, viewBounds.bottom };
            AIPoint tlView, brView;
            sAIDocumentView->ArtworkPointToViewPoint(NULL, &topLeft, &tlView);
            sAIDocumentView->ArtworkPointToViewPoint(NULL, &botRight, &brView);
            AIRect invalRect;
            invalRect.left = std::min(tlView.h, brView.h);
            invalRect.top = std::min(tlView.v, brView.v);
            invalRect.right = std::max(tlView.h, brView.h);
            invalRect.bottom = std::max(tlView.v, brView.v);
            sAIAnnotator->InvalAnnotationRect(nullptr, &invalRect);
        }
    }
    catch (...) {
        // Silently ignore — can happen during shutdown
    }
}

//========================================================================================
//  Surface type name lookup
//========================================================================================

const char* CleanupModule::SurfaceTypeName(int surfaceType)
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
//  HandleOp — operation dispatch
//========================================================================================

bool CleanupModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::AverageSelection:
            AverageSelection();
            return true;

        case OpType::Classify:
            ClassifySelection();
            return true;

        case OpType::Reclassify:
            ReclassifyAs(static_cast<BridgeShapeType>(op.intParam));
            return true;

        case OpType::Simplify:
            if (fInWorkingMode && !fLODCache.empty()) {
                ApplyLODLevel(static_cast<int>(op.param1));
            } else {
                SimplifySelection(op.param1);
            }
            return true;

        case OpType::WorkingApply:
            ApplyWorkingMode(op.boolParam1);
            return true;

        case OpType::WorkingCancel:
            CancelWorkingMode();
            return true;

        case OpType::UndoShape:
            if (fInWorkingMode) {
                CancelWorkingMode();
            } else if (fUndoStack.CanUndo()) {
                int restored = fUndoStack.Undo();
                fprintf(stderr, "[CleanupModule] UndoShape: restored %d paths\n", restored);
                sAIDocument->RedrawDocument();
            }
            return true;

        case OpType::SelectSmall:
            SelectSmall(op.param1);
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  Mouse events — bounding box handle interaction
//========================================================================================

bool CleanupModule::HandleMouseDown(AIToolMessage* msg)
{
    if (!fInWorkingMode || !fBBox.visible) return false;

    AIRealPoint artPt = msg->cursor;
    int hit = HitTestBBoxHandle(artPt);
    if (hit >= 0) {
        fBBox.dragHandle = hit;
        fBBox.dragStart = artPt;
        return true;
    }
    return false;
}

bool CleanupModule::HandleMouseDrag(AIToolMessage* msg)
{
    if (fBBox.dragHandle < 0) return false;

    ApplyBBoxTransform(fBBox.dragHandle, msg->cursor);
    InvalidateFullView();
    return true;
}

bool CleanupModule::HandleMouseUp(AIToolMessage* msg)
{
    if (fBBox.dragHandle < 0) return false;

    fBBox.dragHandle = -1;
    sAIDocument->RedrawDocument();
    return true;
}

//========================================================================================
//  Draw overlay — bounding box with circle handles
//========================================================================================

void CleanupModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    DrawBoundingBoxOverlay(msg);
}

//========================================================================================
//  Notifications
//========================================================================================

void CleanupModule::OnSelectionChanged()
{
    // Selection count is updated externally via SetSelectedAnchorCount
    // from the plugin's Notify handler where SDK calls are valid.

    // Recompute bounding box if preview path is being edited in working mode
    if (fInWorkingMode && fPreviewPath) {
        ComputeBoundingBox();
        InvalidateFullView();
    }
}

void CleanupModule::OnDocumentChanged()
{
    // Clear all cached state on document change
    fCachedSortedPoints.clear();
    fCachedShapeFit = ShapeFitResult{};
    fLODCache.clear();
    fPreviewPath = nullptr;
    fWorkingGroup = nullptr;
    fInWorkingMode = false;
    fOriginalPaths.clear();
    fBBox.visible = false;
    fBBox.dragHandle = -1;
    fUndoStack.Clear();
    fLastDetectedShape = "---";
}

//========================================================================================
//  Undo
//========================================================================================

bool CleanupModule::CanUndo()
{
    return fInWorkingMode || fUndoStack.CanUndo();
}

void CleanupModule::Undo()
{
    if (fInWorkingMode) {
        CancelWorkingMode();
    } else if (fUndoStack.CanUndo()) {
        int restored = fUndoStack.Undo();
        fprintf(stderr, "[CleanupModule] Undo: restored %d paths\n", restored);
        sAIDocument->RedrawDocument();
    }
}

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

        // Find or create Working layer + group
        AIArtHandle layerGroup = nullptr;
        {
            AILayerHandle layer = nullptr;
            ai::UnicodeString workingTitle("Working");
            result = sAILayer->GetLayerByTitle(&layer, workingTitle);
            if (result != kNoErr || layer == nullptr) {
                result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
                if (result != kNoErr || layer == nullptr) {
                    fprintf(stderr, "[CleanupModule] AverageSelection: failed to create Working layer\n");
                    return;
                }
                sAILayer->SetLayerTitle(layer, workingTitle);
            }
            result = sAIArt->GetFirstArtOfLayer(layer, &layerGroup);
            if (result != kNoErr || !layerGroup) {
                fprintf(stderr, "[CleanupModule] AverageSelection: failed to get layer group\n");
                return;
            }
        }

        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &workGroup);
        if (result != kNoErr || !workGroup) {
            fprintf(stderr, "[CleanupModule] AverageSelection: failed to create working group\n");
            return;
        }

        // Dim and lock originals
        fOriginalPaths.clear();
        for (AIArtHandle art : sourcePaths) {
            AIReal prevOpacity = 1.0;
            if (sAIBlendStyle) prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            if (sAIBlendStyle) sAIBlendStyle->SetOpacity(art, 0.30);
            sAIArt->SetArtUserAttr(art, kArtLocked | kArtHidden, kArtLocked | kArtHidden);
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

        // Perspective projection if enabled — delegate to PerspectiveModule
        if (BridgeGetSnapToPerspective() && gPlugin) {
            auto* persp = gPlugin->GetModule<PerspectiveModule>();
            if (persp) {
                previewPts = persp->ProjectPointsThroughPerspective(previewPts, 0);
                for (auto& h : previewHandles) {
                    auto projL = persp->ProjectPointsThroughPerspective({h.left}, 0);
                    auto projR = persp->ProjectPointsThroughPerspective({h.right}, 0);
                    if (!projL.empty()) h.left = projL[0];
                    if (!projR.empty()) h.right = projR[0];
                }
            }
        }

        fPreviewPath = PlacePreview(workGroup, previewPts, previewHandles, previewClosed);

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

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

            // Activate Direct Selection tool
            if (sAITool) {
                AIToolType directSelectNum = 0;
                ASErr toolErr = sAITool->GetToolNumberFromName(kDirectSelectTool, &directSelectNum);
                if (toolErr == kNoErr) {
                    AIToolHandle directSelectHandle = nullptr;
                    toolErr = sAITool->GetToolHandleFromNumber(directSelectNum, &directSelectHandle);
                    if (toolErr == kNoErr && directSelectHandle) {
                        sAITool->SetSelectedTool(directSelectHandle);
                    }
                }
            }
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

    if (fPreviewPath) {
        sAIArt->DisposeArt(fPreviewPath);
        fPreviewPath = nullptr;
    }

    fPreviewPath = PlacePreview(fWorkingGroup, best->points, best->handles,
                                fCachedShapeFit.closed);

    if (fPreviewPath) {
        sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        for (ai::int16 s = 0; s < segCount; s++) {
            sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
        }
    }

    ComputeBoundingBox();
    sAIDocument->RedrawDocument();
    fprintf(stderr, "[CleanupModule] ApplyLODLevel: level=%d → %d points\n",
            level, (int)best->points.size());
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
            AIReal prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});

            AIArtHandle dupe = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, workGroup, &dupe);
            if (result != kNoErr) continue;

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
        }

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

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
        // Exit isolation mode
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            sAIIsolationMode->ExitIsolationMode();
        }

        // Handle originals
        for (auto& rec : fOriginalPaths) {
            if (deleteOriginals) {
                sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
                sAIArt->DisposeArt(rec.art);
            } else {
                if (sAIBlendStyle) sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
                sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
            }
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

        // Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode: complete (originals %s)\n",
                deleteOriginals ? "deleted" : "restored");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
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
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            sAIIsolationMode->ExitIsolationMode();
        }

        if (fWorkingGroup) {
            sAIArt->DisposeArt(fWorkingGroup);
        }

        for (auto& rec : fOriginalPaths) {
            if (sAIBlendStyle) sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
            sAIArt->SetArtUserAttr(rec.art, kArtLocked | kArtHidden, 0);
        }

        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fPreviewPath = nullptr;
        fInWorkingMode = false;
        fCachedSortedPoints.clear();
        fCachedShapeFit = ShapeFitResult{};
        fLODCache.clear();
        fBBox.visible = false;
        fBBox.dragHandle = -1;

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] CancelWorkingMode: complete\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[CleanupModule] CancelWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
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

        // LearningEngine: log prediction vs auto-detection
        {
            const char* surfaceHint = SurfaceTypeName(BridgeGetSurfaceType());
            std::string predicted = LearningEngine::Instance().PredictShape(surfaceHint, 0, 0.0);
            const char* autoDetected = kShapeNames[(int)dominant];
            if (!predicted.empty()) {
                bool match = (predicted == autoDetected);
                fprintf(stderr, "[CleanupModule Learning] PredictShape(%s) → %s, auto=%s, %s\n",
                        surfaceHint, predicted.c_str(), autoDetected,
                        match ? "MATCH" : "MISMATCH");
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

    // CEP-style: if cached sorted points exist, re-fit and update preview
    if (!fCachedSortedPoints.empty() && fInWorkingMode && fWorkingGroup) {
        const char* autoShape = kShapeNames[(int)fCachedShapeFit.shape];

        ShapeFitResult newFit = FitPointsToShape(fCachedSortedPoints, shapeType);
        fCachedShapeFit = newFit;

        if (fPreviewPath) {
            sAIArt->DisposeArt(fPreviewPath);
            fPreviewPath = nullptr;
        }
        fPreviewPath = PlacePreview(fWorkingGroup, newFit.points, newFit.handles, newFit.closed);
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
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

void CleanupModule::SelectSmall(double threshold)
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

            if (totalLen < threshold) {
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
        fprintf(stderr, "[CleanupModule] SelectSmall: selected %d paths below %.1f pt\n",
                selectedCount, threshold);
        if (selectedCount > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[CleanupModule] SelectSmall error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[CleanupModule] SelectSmall unknown error\n"); }
}

//========================================================================================
//  Bounding Box — PCA-rotated custom transform cage with circle handles
//========================================================================================

void CleanupModule::ComputeBoundingBox()
{
    if (!fPreviewPath || !fInWorkingMode) {
        fBBox.visible = false;
        return;
    }

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

    // Compute PCA eigenvector for rotation angle
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

    fBBox.rotation = atan2(vy, vx);

    double px = -vy;
    double py = vx;

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

    double pad = 4.0;
    minPrimary -= pad; maxPrimary += pad;
    minSecondary -= pad; maxSecondary += pad;

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

    for (int i = 0; i < 4; i++) {
        int j = (i + 1) % 4;
        fBBox.midpoints[i].h = (AIReal)((fBBox.corners[i].h + fBBox.corners[j].h) * 0.5);
        fBBox.midpoints[i].v = (AIReal)((fBBox.corners[i].v + fBBox.corners[j].v) * 0.5);
    }

    fBBox.center.h = (AIReal)cx;
    fBBox.center.v = (AIReal)cy;
    fBBox.visible = true;
    fBBox.dragHandle = -1;
}

//========================================================================================
//  Draw bounding box overlay
//========================================================================================

static void DrawBBoxHandle(AIAnnotatorDrawer* drawer, AIPoint center, int radius,
                           const AIRGBColor& fillColor, const AIRGBColor& strokeColor)
{
    AIRect r;
    r.left   = center.h - radius;
    r.top    = center.v - radius;
    r.right  = center.h + radius;
    r.bottom = center.v + radius;

    sAIAnnotatorDrawer->SetColor(drawer, fillColor);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, true);
    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, false);
}

void CleanupModule::DrawBoundingBoxOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;
    if (!fBBox.visible || !fInWorkingMode) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    AIRGBColor edgeColor;
    edgeColor.red   = (ai::uint16)(0.10 * 65535);
    edgeColor.green = (ai::uint16)(0.70 * 65535);
    edgeColor.blue  = (ai::uint16)(0.85 * 65535);

    AIRGBColor handleFill;
    handleFill.red   = (ai::uint16)(1.0 * 65535);
    handleFill.green = (ai::uint16)(1.0 * 65535);
    handleFill.blue  = (ai::uint16)(1.0 * 65535);

    AIRGBColor handleStroke = edgeColor;

    AIRGBColor activeHandleFill;
    activeHandleFill.red   = (ai::uint16)(1.0 * 65535);
    activeHandleFill.green = (ai::uint16)(0.6 * 65535);
    activeHandleFill.blue  = (ai::uint16)(0.1 * 65535);

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

    for (int i = 0; i < 4; i++) {
        int j = (i + 1) % 4;
        sAIAnnotatorDrawer->DrawLine(drawer, viewCorners[i], viewCorners[j]);
    }

    int cornerRadius = 5;
    int midpointRadius = 4;

    for (int i = 0; i < 4; i++) {
        const AIRGBColor& fill = (fBBox.dragHandle == i) ? activeHandleFill : handleFill;
        DrawBBoxHandle(drawer, viewCorners[i], cornerRadius, fill, handleStroke);
    }

    for (int i = 0; i < 4; i++) {
        AIPoint viewMid;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &fBBox.midpoints[i], &viewMid) != kNoErr) continue;

        const AIRGBColor& fill = (fBBox.dragHandle == (i + 4)) ? activeHandleFill : handleFill;
        DrawBBoxHandle(drawer, viewMid, midpointRadius, fill, handleStroke);
    }

    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
}

//========================================================================================
//  Hit-test bounding box handles
//========================================================================================

int CleanupModule::HitTestBBoxHandle(AIRealPoint artPt, double hitRadius)
{
    if (!fBBox.visible) return -1;

    for (int i = 0; i < 4; i++) {
        double dx = artPt.h - fBBox.corners[i].h;
        double dy = artPt.v - fBBox.corners[i].v;
        if (sqrt(dx * dx + dy * dy) <= hitRadius) return i;
    }

    for (int i = 0; i < 4; i++) {
        double dx = artPt.h - fBBox.midpoints[i].h;
        double dy = artPt.v - fBBox.midpoints[i].v;
        if (sqrt(dx * dx + dy * dy) <= hitRadius) return i + 4;
    }

    return -1;
}

//========================================================================================
//  Apply bounding box transform — scale path based on handle drag
//========================================================================================

void CleanupModule::ApplyBBoxTransform(int handleIdx, AIRealPoint newPos)
{
    if (!fPreviewPath || handleIdx < 0 || handleIdx > 7) return;

    ai::int16 segCount = 0;
    ASErr err = sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (err != kNoErr || segCount < 2) return;

    std::vector<AIPathSegment> segs(segCount);
    err = sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());
    if (err != kNoErr) return;

    double cosR = cos(fBBox.rotation);
    double sinR = sin(fBBox.rotation);

    AIRealPoint anchor;
    if (handleIdx < 4) {
        anchor = fBBox.corners[(handleIdx + 2) % 4];
    } else {
        anchor = fBBox.midpoints[((handleIdx - 4) + 2) % 4];
    }

    AIRealPoint origHandle;
    if (handleIdx < 4) {
        origHandle = fBBox.corners[handleIdx];
    } else {
        origHandle = fBBox.midpoints[handleIdx - 4];
    }

    double origDx = origHandle.h - anchor.h;
    double origDy = origHandle.v - anchor.v;
    double origPrimary   = origDx * cosR + origDy * sinR;
    double origSecondary = origDx * (-sinR) + origDy * cosR;

    double newDx = newPos.h - anchor.h;
    double newDy = newPos.v - anchor.v;
    double newPrimary   = newDx * cosR + newDy * sinR;
    double newSecondary = newDx * (-sinR) + newDy * cosR;

    double scalePrimary = 1.0;
    double scaleSecondary = 1.0;

    if (handleIdx < 4) {
        if (fabs(origPrimary) > 1e-6) scalePrimary = newPrimary / origPrimary;
        if (fabs(origSecondary) > 1e-6) scaleSecondary = newSecondary / origSecondary;
    } else {
        int edgeIdx = handleIdx - 4;
        if (edgeIdx == 0 || edgeIdx == 2) {
            if (fabs(origSecondary) > 1e-6) scaleSecondary = newSecondary / origSecondary;
        } else {
            if (fabs(origPrimary) > 1e-6) scalePrimary = newPrimary / origPrimary;
        }
    }

    if (fabs(scalePrimary) < 0.01) scalePrimary = 0.01;
    if (fabs(scaleSecondary) < 0.01) scaleSecondary = 0.01;

    for (int i = 0; i < segCount; i++) {
        AIRealPoint* pts[3] = { &segs[i].in, &segs[i].p, &segs[i].out };
        for (int j = 0; j < 3; j++) {
            double dx = pts[j]->h - anchor.h;
            double dy = pts[j]->v - anchor.v;
            double projP = dx * cosR + dy * sinR;
            double projS = dx * (-sinR) + dy * cosR;
            projP *= scalePrimary;
            projS *= scaleSecondary;
            pts[j]->h = (AIReal)(anchor.h + projP * cosR + projS * (-sinR));
            pts[j]->v = (AIReal)(anchor.v + projP * sinR + projS * cosR);
        }
    }

    sAIPath->SetPathSegments(fPreviewPath, 0, segCount, segs.data());
    ComputeBoundingBox();
}
