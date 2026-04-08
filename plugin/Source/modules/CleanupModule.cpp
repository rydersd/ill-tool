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

// Forward declaration — defined after bounding box section
static double ViewSpaceDist(AIRealPoint a, AIRealPoint b);

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
    if (!fInWorkingMode) return false;

    // Safety: clear any stale drag state from a missed MouseUp
    if (fDragBezierIdx >= 0) {
        fDragBezierIdx = -1;
    }
    if (fDragAnchorIdx >= 0) {
        fDragAnchorIdx = -1;
        ComputeBoundingBox();
    }
    if (fBBox.dragHandle >= 0) {
        fBBox.dragHandle = -1;
    }

    AIRealPoint artPt = msg->cursor;
    bool optionKey = msg->event && (msg->event->modifiers & aiEventModifiers_optionKey) != 0;
    bool shiftKey  = msg->event && (msg->event->modifiers & aiEventModifiers_shiftKey) != 0;

    // Shift-click on an anchor: toggle sharp/smooth
    if (shiftKey && !optionKey && fPreviewPath) {
        int anchorHit = HitTestAnchorHandle(artPt, 7.0);
        if (anchorHit >= 0) {
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
            if (anchorHit < segCount) {
                AIPathSegment seg;
                sAIPath->GetPathSegments(fPreviewPath, anchorHit, 1, &seg);
                if (seg.corner) {
                    // Convert to smooth: compute handles from neighbors
                    seg.corner = false;
                    std::vector<AIPathSegment> allSegs(segCount);
                    sAIPath->GetPathSegments(fPreviewPath, 0, segCount, allSegs.data());
                    AIRealPoint prev = (anchorHit > 0) ? allSegs[anchorHit-1].p : seg.p;
                    AIRealPoint next = (anchorHit < segCount-1) ? allSegs[anchorHit+1].p : seg.p;
                    double dx = next.h - prev.h, dy = next.v - prev.v;
                    double tn = 1.0 / 6.0;
                    seg.in.h  = (AIReal)(seg.p.h - dx * tn);
                    seg.in.v  = (AIReal)(seg.p.v - dy * tn);
                    seg.out.h = (AIReal)(seg.p.h + dx * tn);
                    seg.out.v = (AIReal)(seg.p.v + dy * tn);
                } else {
                    // Convert to sharp: collapse handles to anchor
                    seg.corner = true;
                    seg.in = seg.p;
                    seg.out = seg.p;
                }
                sAIPath->SetPathSegments(fPreviewPath, anchorHit, 1, &seg);
                InvalidateFullView();
                sAIDocument->RedrawDocument();
                fprintf(stderr, "[CleanupModule] Toggled point %d to %s\n",
                        anchorHit, seg.corner ? "sharp" : "smooth");
                return true;
            }
        }
    }

    // Option-click on the path: add a new anchor point at click position
    // Option+Shift = sharp corner (no handles)
    if (optionKey && fPreviewPath) {
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        if (segCount >= 2) {
            std::vector<AIPathSegment> segs(segCount);
            sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());

            double bestDist = 1e20;
            int insertAfter = 0;
            for (int i = 0; i < segCount - 1; i++) {
                double d = PointToSegmentDist(artPt, segs[i].p, segs[i+1].p);
                if (d < bestDist) { bestDist = d; insertAfter = i; }
            }

            if (bestDist < 20.0) {
                bool sharp = shiftKey;

                // Compute smooth handles for the new point using neighbors
                AIRealPoint prev = segs[insertAfter].p;
                AIRealPoint next = segs[insertAfter + 1].p;
                double tn = 1.0 / 6.0;

                AIPathSegment newSeg = {};
                newSeg.p = artPt;
                if (sharp) {
                    newSeg.in = artPt;
                    newSeg.out = artPt;
                    newSeg.corner = true;
                } else {
                    double dx = next.h - prev.h;
                    double dy = next.v - prev.v;
                    newSeg.in.h  = (AIReal)(artPt.h - dx * tn);
                    newSeg.in.v  = (AIReal)(artPt.v - dy * tn);
                    newSeg.out.h = (AIReal)(artPt.h + dx * tn);
                    newSeg.out.v = (AIReal)(artPt.v + dy * tn);
                    newSeg.corner = false;
                }

                // Shorten the outgoing handle of the previous point
                // and the incoming handle of the next point
                double prevToNew = Dist2D(prev, artPt);
                double newToNext = Dist2D(artPt, next);
                double prevToNext = Dist2D(prev, next);
                if (prevToNext > 1e-6) {
                    double prevRatio = prevToNew / prevToNext;
                    double nextRatio = newToNext / prevToNext;
                    // Scale outgoing handle of prev toward the new point
                    AIPathSegment& prevSeg = segs[insertAfter];
                    double odx = prevSeg.out.h - prevSeg.p.h;
                    double ody = prevSeg.out.v - prevSeg.p.v;
                    prevSeg.out.h = (AIReal)(prevSeg.p.h + odx * prevRatio);
                    prevSeg.out.v = (AIReal)(prevSeg.p.v + ody * prevRatio);
                    // Scale incoming handle of next toward the new point
                    AIPathSegment& nextSeg = segs[insertAfter + 1];
                    double idx = nextSeg.in.h - nextSeg.p.h;
                    double idy = nextSeg.in.v - nextSeg.p.v;
                    nextSeg.in.h = (AIReal)(nextSeg.p.h + idx * nextRatio);
                    nextSeg.in.v = (AIReal)(nextSeg.p.v + idy * nextRatio);
                }

                std::vector<AIPathSegment> newSegs;
                for (int i = 0; i <= insertAfter; i++) newSegs.push_back(segs[i]);
                newSegs.push_back(newSeg);
                for (int i = insertAfter + 1; i < segCount; i++) newSegs.push_back(segs[i]);

                ai::int16 nc = (ai::int16)newSegs.size();
                sAIPath->SetPathSegmentCount(fPreviewPath, nc);
                sAIPath->SetPathSegments(fPreviewPath, 0, nc, newSegs.data());

                ComputeBoundingBox();
                InvalidateFullView();
                sAIDocument->RedrawDocument();
                fprintf(stderr, "[CleanupModule] Added %s point at (%.1f, %.1f) after seg %d\n",
                        sharp ? "sharp" : "smooth", artPt.h, artPt.v, insertAfter);
                return true;
            }
        }
    }

    // Priority 1: bezier handle endpoint hit-test (small circles)
    {
        int bezierHit = HitTestBezierHandle(artPt);
        if (bezierHit >= 0) {
            fDragBezierIdx = bezierHit;
            fBezierDragStart = artPt;
            fprintf(stderr, "[CleanupModule] Bezier handle drag start: %s of seg %d\n",
                    (bezierHit % 2 == 0) ? "in" : "out", bezierHit / 2);
            return true;
        }
    }

    // Priority 2: path anchor handle hit-test (squares)
    int anchorHit = HitTestAnchorHandle(artPt);
    if (anchorHit >= 0) {
        fDragAnchorIdx = anchorHit;
        fAnchorDragStart = artPt;
        // Snapshot the original segment for undo
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        if (anchorHit < segCount) {
            sAIPath->GetPathSegments(fPreviewPath, anchorHit, 1, &fAnchorDragOrigSeg);
        }
        fprintf(stderr, "[CleanupModule] Anchor drag start: idx=%d\n", anchorHit);
        return true;
    }

    // Priority 2: bounding box handle hit-test (circles)
    if (fBBox.visible) {
        int bboxHit = HitTestBBoxHandle(artPt);
        if (bboxHit >= 0) {
            fBBox.dragHandle = bboxHit;
            fBBox.dragStart = artPt;
            fprintf(stderr, "[CleanupModule] BBox drag start: handle=%d\n", bboxHit);
            return true;
        }

        // Priority 3: rotate zone — outside bbox near corners
        if (HitTestBBoxRotateZone(artPt)) {
            fBBox.dragHandle = 8;  // 8 = rotating
            fBBox.dragStart = artPt;
            fBBox.dragStartAngle = atan2(artPt.v - fBBox.center.v, artPt.h - fBBox.center.h);
            fprintf(stderr, "[CleanupModule] Rotation drag start\n");
            return true;
        }
    }

    return false;
}

bool CleanupModule::HandleMouseDrag(AIToolMessage* msg)
{
    // Bezier handle drag
    if (fDragBezierIdx >= 0) {
        ApplyBezierDrag(fDragBezierIdx, msg->cursor);
        InvalidateFullView();
        return true;
    }

    // Anchor drag
    if (fDragAnchorIdx >= 0) {
        ApplyAnchorDrag(fDragAnchorIdx, msg->cursor);
        InvalidateFullView();
        return true;
    }

    // Bbox rotation
    if (fBBox.dragHandle == 8) {
        ApplyBBoxRotation(msg->cursor);
        InvalidateFullView();
        return true;
    }

    // Bbox scale/distort
    if (fBBox.dragHandle >= 0 && fBBox.dragHandle < 8) {
        ApplyBBoxTransform(fBBox.dragHandle, msg->cursor);
        InvalidateFullView();
        return true;
    }

    return false;
}

bool CleanupModule::HandleMouseUp(AIToolMessage* msg)
{
    if (!fInWorkingMode) {
        // Clear any stale drag state
        fDragBezierIdx = -1;
        fDragAnchorIdx = -1;
        fBBox.dragHandle = -1;
        return false;
    }

    if (fDragBezierIdx >= 0) {
        fprintf(stderr, "[CleanupModule] Bezier handle drag end: %s of seg %d\n",
                (fDragBezierIdx % 2 == 0) ? "in" : "out", fDragBezierIdx / 2);
        fDragBezierIdx = -1;
        sAIDocument->RedrawDocument();
        return true;
    }

    if (fDragAnchorIdx >= 0) {
        fprintf(stderr, "[CleanupModule] Anchor drag end: idx=%d\n", fDragAnchorIdx);

        // Auto-merge: if this anchor landed within 5px of another anchor, merge them
        if (fPreviewPath) {
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
            if (segCount > 2 && fDragAnchorIdx < segCount) {
                AIPathSegment dragSeg;
                sAIPath->GetPathSegments(fPreviewPath, fDragAnchorIdx, 1, &dragSeg);

                for (ai::int16 j = 0; j < segCount; j++) {
                    if (j == (ai::int16)fDragAnchorIdx) continue;
                    AIPathSegment otherSeg;
                    sAIPath->GetPathSegments(fPreviewPath, j, 1, &otherSeg);
                    if (ViewSpaceDist(dragSeg.p, otherSeg.p) <= 5.0) {
                        // Merge: remove the dragged point
                        std::vector<AIPathSegment> allSegs(segCount);
                        sAIPath->GetPathSegments(fPreviewPath, 0, segCount, allSegs.data());
                        allSegs.erase(allSegs.begin() + fDragAnchorIdx);
                        ai::int16 nc = (ai::int16)allSegs.size();
                        sAIPath->SetPathSegmentCount(fPreviewPath, nc);
                        sAIPath->SetPathSegments(fPreviewPath, 0, nc, allSegs.data());
                        fprintf(stderr, "[CleanupModule] Auto-merged point %d onto %d\n",
                                fDragAnchorIdx, (int)j);
                        fHoverAnchorIdx = -1;
                        fHoverBezierIdx = -1;
                        break;
                    }
                }
            }
        }

        fDragAnchorIdx = -1;
        ComputeBoundingBox();
        sAIDocument->RedrawDocument();
        return true;
    }

    if (fBBox.dragHandle >= 0) {
        fprintf(stderr, "[CleanupModule] BBox drag end: handle=%d\n", fBBox.dragHandle);
        fBBox.dragHandle = -1;
        ComputeBoundingBox();
        sAIDocument->RedrawDocument();
        return true;
    }

    return false;
}

//========================================================================================
//  Cursor tracking — pre-highlight handles on hover
//========================================================================================

void CleanupModule::HandleCursorTrack(AIRealPoint artPt)
{
    if (!fInWorkingMode) {
        fHoverAnchorIdx = -1;
        fHoverBBoxIdx = -1;
        return;
    }

    int prevAnchor = fHoverAnchorIdx;
    int prevBBox = fHoverBBoxIdx;
    int prevBezier = fHoverBezierIdx;

    fHoverBezierIdx = -1;
    fHoverAnchorIdx = -1;
    fHoverBBoxIdx = -1;

    // Check bezier handle endpoints first
    fHoverBezierIdx = HitTestBezierHandle(artPt, 5.0);

    if (fHoverBezierIdx < 0) {
        // Check anchor handles
        fHoverAnchorIdx = HitTestAnchorHandle(artPt, 6.0);
    }

    if (fHoverAnchorIdx < 0 && fHoverBezierIdx < 0) {
        // Check bbox handles
        fHoverBBoxIdx = HitTestBBoxHandle(artPt, 8.0);
        if (fHoverBBoxIdx < 0 && HitTestBBoxRotateZone(artPt)) {
            fHoverBBoxIdx = 8;
        }
    }

    if (fHoverAnchorIdx != prevAnchor || fHoverBBoxIdx != prevBBox || fHoverBezierIdx != prevBezier) {
        InvalidateFullView();
    }
}

//========================================================================================
//  Draw overlay — bounding box with circle handles + path anchor squares
//========================================================================================

void CleanupModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    DrawBoundingBoxOverlay(msg);
    DrawPathAnchorHandles(msg);
}

//========================================================================================
//  Notifications
//========================================================================================

void CleanupModule::OnSelectionChanged()
{
    // Selection count is updated externally via SetSelectedAnchorCount
    // from the plugin's Notify handler where SDK calls are valid.

    // Recompute bounding box if preview path is being edited in working mode
    // BUT NOT during an active drag — segment modifications trigger selection
    // change events which would recompute the bbox mid-drag and break the interaction.
    if (fInWorkingMode && fPreviewPath && fBBox.dragHandle < 0 && fDragAnchorIdx < 0) {
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
    fSourceGroup = nullptr;
    fSourceGroupName.clear();
    fSourceLayerName.clear();
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
        // Without lock, perspective is still being adjusted and shouldn't affect cleanup.
        if (BridgeGetSnapToPerspective() && BridgeGetPerspectiveLocked() && gPlugin) {
            auto* persp = gPlugin->GetModule<PerspectiveModule>();
            if (persp) {
                fprintf(stderr, "[CleanupModule] Projecting preview through locked perspective grid\n");
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

    if (fPreviewPath) {
        UpdatePreviewSegments(fPreviewPath, best->points, best->handles,
                              fCachedShapeFit.closed);
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        for (ai::int16 s = 0; s < segCount; s++) {
            sAIPath->SetPathSegmentSelected(fPreviewPath, s, kSegmentPointSelected);
        }
    } else {
        fPreviewPath = PlacePreview(fWorkingGroup, best->points, best->handles,
                                    fCachedShapeFit.closed);
        if (fPreviewPath) {
            sAIArt->SetArtUserAttr(fPreviewPath, kArtSelected, kArtSelected);
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
        // Suppress isolation re-entry notifier during Apply
        fExitingWorkingMode = true;

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

            // Auto-name
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

        // Clear state
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
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode: complete (originals %s)\n",
                deleteOriginals ? "deleted" : "restored");
    }
    catch (ai::Error& ex) {
        fExitingWorkingMode = false;
        fprintf(stderr, "[CleanupModule] ApplyWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fExitingWorkingMode = false;
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
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[CleanupModule] CancelWorkingMode: complete\n");
    }
    catch (ai::Error& ex) {
        fExitingWorkingMode = false;
        fprintf(stderr, "[CleanupModule] CancelWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fExitingWorkingMode = false;
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
//  Helper: compute distance in screen pixels between two artwork points
//  Used by all hit-tests so handle radius is consistent at any zoom level.
//========================================================================================

static double ViewSpaceDist(AIRealPoint a, AIRealPoint b)
{
    AIPoint va, vb;
    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &a, &va) != kNoErr) return 1e20;
    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &b, &vb) != kNoErr) return 1e20;
    double dx = va.h - vb.h;
    double dy = va.v - vb.v;
    return sqrt(dx * dx + dy * dy);
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

    AIRGBColor hoverHandleFill;
    hoverHandleFill.red   = (ai::uint16)(0.7 * 65535);
    hoverHandleFill.green = (ai::uint16)(0.9 * 65535);
    hoverHandleFill.blue  = (ai::uint16)(1.0 * 65535);

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
        bool active = (fBBox.dragHandle == i);
        bool hovered = (fHoverBBoxIdx == i);
        const AIRGBColor& fill = active ? activeHandleFill : (hovered ? hoverHandleFill : handleFill);
        int r = hovered ? cornerRadius + 2 : cornerRadius;
        DrawBBoxHandle(drawer, viewCorners[i], r, fill, handleStroke);
    }

    for (int i = 0; i < 4; i++) {
        AIPoint viewMid;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &fBBox.midpoints[i], &viewMid) != kNoErr) continue;

        bool active = (fBBox.dragHandle == (i + 4));
        bool hovered = (fHoverBBoxIdx == (i + 4));
        const AIRGBColor& fill = active ? activeHandleFill : (hovered ? hoverHandleFill : handleFill);
        int r = hovered ? midpointRadius + 2 : midpointRadius;
        DrawBBoxHandle(drawer, viewMid, r, fill, handleStroke);
    }

    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
}

//========================================================================================
//  Hit-test bounding box handles
//========================================================================================

int CleanupModule::HitTestBBoxHandle(AIRealPoint artPt, double hitRadiusPx)
{
    if (!fBBox.visible) return -1;

    for (int i = 0; i < 4; i++) {
        if (ViewSpaceDist(artPt, fBBox.corners[i]) <= hitRadiusPx) return i;
    }

    for (int i = 0; i < 4; i++) {
        if (ViewSpaceDist(artPt, fBBox.midpoints[i]) <= hitRadiusPx) return i + 4;
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

//========================================================================================
//  Hit-test rotate zone — outside bbox near corners
//========================================================================================

bool CleanupModule::HitTestBBoxRotateZone(AIRealPoint artPt, double innerRadiusPx, double outerRadiusPx)
{
    if (!fBBox.visible) return false;

    for (int i = 0; i < 4; i++) {
        double dist = ViewSpaceDist(artPt, fBBox.corners[i]);
        if (dist > innerRadiusPx && dist <= outerRadiusPx) return true;
    }
    return false;
}

//========================================================================================
//  Apply rotation — rotate all path segments around bbox center
//========================================================================================

void CleanupModule::ApplyBBoxRotation(AIRealPoint newPos)
{
    if (!fPreviewPath) return;

    double currentAngle = atan2(newPos.v - fBBox.center.v, newPos.h - fBBox.center.h);
    double deltaAngle = currentAngle - fBBox.dragStartAngle;
    fBBox.dragStartAngle = currentAngle;

    double cosA = cos(deltaAngle);
    double sinA = sin(deltaAngle);

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (segCount < 2) return;

    std::vector<AIPathSegment> segs(segCount);
    sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());

    double cx = fBBox.center.h;
    double cy = fBBox.center.v;

    for (int i = 0; i < segCount; i++) {
        AIRealPoint* pts[3] = { &segs[i].in, &segs[i].p, &segs[i].out };
        for (int j = 0; j < 3; j++) {
            double dx = pts[j]->h - cx;
            double dy = pts[j]->v - cy;
            pts[j]->h = (AIReal)(cx + dx * cosA - dy * sinA);
            pts[j]->v = (AIReal)(cy + dx * sinA + dy * cosA);
        }
    }

    sAIPath->SetPathSegments(fPreviewPath, 0, segCount, segs.data());
    ComputeBoundingBox();
    fprintf(stderr, "[CleanupModule] Rotation: delta=%.2f deg\n", deltaAngle * 180.0 / M_PI);
}

//========================================================================================
//  Path Anchor Handles — square handles at each control point of the preview path
//========================================================================================

static void DrawSquareHandle(AIAnnotatorDrawer* drawer, AIPoint center, int halfSize,
                             const AIRGBColor& fillColor, const AIRGBColor& strokeColor)
{
    AIRect r;
    r.left   = center.h - halfSize;
    r.top    = center.v - halfSize;
    r.right  = center.h + halfSize;
    r.bottom = center.v + halfSize;

    sAIAnnotatorDrawer->SetColor(drawer, fillColor);
    sAIAnnotatorDrawer->DrawRect(drawer, r, true);
    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
    sAIAnnotatorDrawer->DrawRect(drawer, r, false);
}

void CleanupModule::DrawPathAnchorHandles(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;
    if (!fInWorkingMode || !fPreviewPath) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    ai::int16 segCount = 0;
    ASErr err = sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (err != kNoErr || segCount < 1) return;

    std::vector<AIPathSegment> segs(segCount);
    err = sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());
    if (err != kNoErr) return;

    // Handle colors — same stroke as bbox, white fill (active = orange)
    AIRGBColor handleFill;
    handleFill.red   = (ai::uint16)(1.0 * 65535);
    handleFill.green = (ai::uint16)(1.0 * 65535);
    handleFill.blue  = (ai::uint16)(1.0 * 65535);

    AIRGBColor handleStroke;
    handleStroke.red   = (ai::uint16)(0.15 * 65535);
    handleStroke.green = (ai::uint16)(0.15 * 65535);
    handleStroke.blue  = (ai::uint16)(0.15 * 65535);

    AIRGBColor activeFill;
    activeFill.red   = (ai::uint16)(1.0 * 65535);
    activeFill.green = (ai::uint16)(0.6 * 65535);
    activeFill.blue  = (ai::uint16)(0.1 * 65535);

    AIRGBColor handleLineColor;
    handleLineColor.red   = (ai::uint16)(0.5 * 65535);
    handleLineColor.green = (ai::uint16)(0.5 * 65535);
    handleLineColor.blue  = (ai::uint16)(0.5 * 65535);

    int handleSize = 5;  // half-size of square — matches bbox circle radius

    sAIAnnotatorDrawer->SetOpacity(drawer, 0.9);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);

    for (ai::int16 i = 0; i < segCount; i++) {
        AIPoint viewPt;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &segs[i].p, &viewPt) != kNoErr) continue;

        // Draw bezier handle lines (in → anchor → out)
        bool hasIn  = (fabs(segs[i].in.h - segs[i].p.h) > 0.5 || fabs(segs[i].in.v - segs[i].p.v) > 0.5);
        bool hasOut = (fabs(segs[i].out.h - segs[i].p.h) > 0.5 || fabs(segs[i].out.v - segs[i].p.v) > 0.5);

        sAIAnnotatorDrawer->SetColor(drawer, handleLineColor);

        if (hasIn) {
            AIPoint viewIn;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &segs[i].in, &viewIn) == kNoErr) {
                sAIAnnotatorDrawer->DrawLine(drawer, viewIn, viewPt);
                bool inHovered = (fHoverBezierIdx == (int)i * 2 + 0);
                bool inDrag    = (fDragBezierIdx == (int)i * 2 + 0);
                int inR = (inHovered || inDrag) ? 5 : 3;
                AIRect inRect;
                inRect.left = viewIn.h - inR; inRect.top = viewIn.v - inR;
                inRect.right = viewIn.h + inR; inRect.bottom = viewIn.v + inR;
                sAIAnnotatorDrawer->SetColor(drawer, (inHovered || inDrag) ? activeFill : handleFill);
                sAIAnnotatorDrawer->DrawEllipse(drawer, inRect, true);
                sAIAnnotatorDrawer->SetColor(drawer, handleLineColor);
                sAIAnnotatorDrawer->DrawEllipse(drawer, inRect, false);
            }
        }

        if (hasOut) {
            AIPoint viewOut;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &segs[i].out, &viewOut) == kNoErr) {
                sAIAnnotatorDrawer->DrawLine(drawer, viewPt, viewOut);
                bool outHovered = (fHoverBezierIdx == (int)i * 2 + 1);
                bool outDrag    = (fDragBezierIdx == (int)i * 2 + 1);
                int outR = (outHovered || outDrag) ? 5 : 3;
                AIRect outRect;
                outRect.left = viewOut.h - outR; outRect.top = viewOut.v - outR;
                outRect.right = viewOut.h + outR; outRect.bottom = viewOut.v + outR;
                sAIAnnotatorDrawer->SetColor(drawer, (outHovered || outDrag) ? activeFill : handleFill);
                sAIAnnotatorDrawer->DrawEllipse(drawer, outRect, true);
                sAIAnnotatorDrawer->SetColor(drawer, handleLineColor);
                sAIAnnotatorDrawer->DrawEllipse(drawer, outRect, false);
            }
        }

        // Draw square anchor handle with hover pre-highlight
        AIRGBColor hoverFill;
        hoverFill.red   = (ai::uint16)(0.7 * 65535);
        hoverFill.green = (ai::uint16)(0.9 * 65535);
        hoverFill.blue  = (ai::uint16)(1.0 * 65535);

        bool active = (fDragAnchorIdx == (int)i);
        bool hovered = (fHoverAnchorIdx == (int)i);
        const AIRGBColor& fill = active ? activeFill : (hovered ? hoverFill : handleFill);
        int hs = hovered ? handleSize + 2 : handleSize;
        DrawSquareHandle(drawer, viewPt, hs, fill, handleStroke);
    }

    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
}

//========================================================================================
//  Hit-test path anchor handles
//========================================================================================

int CleanupModule::HitTestAnchorHandle(AIRealPoint artPt, double hitRadiusPx)
{
    if (!fInWorkingMode || !fPreviewPath) return -1;

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (segCount < 1) return -1;

    std::vector<AIPathSegment> segs(segCount);
    sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());

    for (ai::int16 i = 0; i < segCount; i++) {
        if (ViewSpaceDist(artPt, segs[i].p) <= hitRadiusPx) return (int)i;
    }

    return -1;
}

//========================================================================================
//  Apply anchor drag — move anchor point + shift handles by same delta
//========================================================================================

void CleanupModule::ApplyAnchorDrag(int anchorIdx, AIRealPoint newPos)
{
    if (!fPreviewPath || anchorIdx < 0) return;

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (anchorIdx >= segCount) return;

    // Compute delta from original position
    double dx = newPos.h - fAnchorDragStart.h;
    double dy = newPos.v - fAnchorDragStart.v;

    // Move anchor + handles by the same delta (preserves handle shape)
    AIPathSegment seg = fAnchorDragOrigSeg;
    seg.p.h   += (AIReal)dx;
    seg.p.v   += (AIReal)dy;
    seg.in.h  += (AIReal)dx;
    seg.in.v  += (AIReal)dy;
    seg.out.h += (AIReal)dx;
    seg.out.v += (AIReal)dy;

    sAIPath->SetPathSegments(fPreviewPath, anchorIdx, 1, &seg);
}

//========================================================================================
//  Hit-test bezier handle endpoints (small circles at end of handle lines)
//  Returns: seg*2+0 for "in" handle, seg*2+1 for "out" handle, -1 for miss
//========================================================================================

int CleanupModule::HitTestBezierHandle(AIRealPoint artPt, double hitRadiusPx)
{
    if (!fInWorkingMode || !fPreviewPath) return -1;

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (segCount < 1) return -1;

    std::vector<AIPathSegment> segs(segCount);
    sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());

    for (ai::int16 i = 0; i < segCount; i++) {
        bool hasIn = (fabs(segs[i].in.h - segs[i].p.h) > 0.5 || fabs(segs[i].in.v - segs[i].p.v) > 0.5);
        if (hasIn) {
            if (ViewSpaceDist(artPt, segs[i].in) <= hitRadiusPx) return (int)i * 2 + 0;
        }
        bool hasOut = (fabs(segs[i].out.h - segs[i].p.h) > 0.5 || fabs(segs[i].out.v - segs[i].p.v) > 0.5);
        if (hasOut) {
            if (ViewSpaceDist(artPt, segs[i].out) <= hitRadiusPx) return (int)i * 2 + 1;
        }
    }
    return -1;
}

//========================================================================================
//  Apply bezier handle drag — move just the handle, not the anchor
//========================================================================================

void CleanupModule::ApplyBezierDrag(int bezierIdx, AIRealPoint newPos)
{
    if (!fPreviewPath || bezierIdx < 0) return;

    int segIdx = bezierIdx / 2;
    bool isOut = (bezierIdx % 2) == 1;

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
    if (segIdx >= segCount) return;

    AIPathSegment seg;
    sAIPath->GetPathSegments(fPreviewPath, segIdx, 1, &seg);

    if (isOut) {
        seg.out = newPos;
    } else {
        seg.in = newPos;
    }

    // If the point is smooth (not corner), mirror the opposite handle
    if (!seg.corner) {
        double dx = newPos.h - seg.p.h;
        double dy = newPos.v - seg.p.v;
        if (isOut) {
            // Mirror in handle
            double inLen = sqrt((seg.in.h - seg.p.h) * (seg.in.h - seg.p.h) +
                                (seg.in.v - seg.p.v) * (seg.in.v - seg.p.v));
            double outLen = sqrt(dx * dx + dy * dy);
            if (outLen > 1e-6) {
                double scale = inLen / outLen;
                seg.in.h = (AIReal)(seg.p.h - dx * scale);
                seg.in.v = (AIReal)(seg.p.v - dy * scale);
            }
        } else {
            // Mirror out handle
            double outLen = sqrt((seg.out.h - seg.p.h) * (seg.out.h - seg.p.h) +
                                 (seg.out.v - seg.p.v) * (seg.out.v - seg.p.v));
            double inLen = sqrt(dx * dx + dy * dy);
            if (inLen > 1e-6) {
                double scale = outLen / inLen;
                seg.out.h = (AIReal)(seg.p.h - dx * scale);
                seg.out.v = (AIReal)(seg.p.v - dy * scale);
            }
        }
    }

    sAIPath->SetPathSegments(fPreviewPath, segIdx, 1, &seg);
}
