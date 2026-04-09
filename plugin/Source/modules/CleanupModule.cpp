//========================================================================================
//  CleanupModule — Dispatch + lifecycle core
//
//  Split into 3 files for maintainability:
//    CleanupModule.cpp   — HandleOp, lifecycle, undo, NSEvent interceptor (this file)
//    CleanupHandles.cpp  — mouse interaction, hit-testing, bbox transform, annotator drawing
//    CleanupPipeline.cpp — AverageSelection, Classify, Reclassify, LOD, working mode
//
//  All 3 files implement methods of the CleanupModule class.
//  CleanupHandles.cpp and CleanupPipeline.cpp are #included at the bottom
//  (they are not separate compilation units — not in pbxproj).
//========================================================================================

#include "CleanupModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "ShapeUtils.h"
#include "PerspectiveModule.h"
#include "LearningEngine.h"
#include "VisionEngine.h"
#include "HttpBridge.h"
#include "AIToolNames.h"

#include <cstdio>
#include <cmath>
#include <algorithm>
#include <vector>

#import <AppKit/NSEvent.h>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Cmd+Z interceptor — NSEvent local monitor that eats Cmd+Z during working mode
//  to prevent Illustrator's native undo from corrupting our cached art handles.
//========================================================================================

static id InstallUndoInterceptor(CleanupModule* cleanup)
{
    id monitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
        handler:^NSEvent*(NSEvent* event) {
            if (!cleanup || !cleanup->IsInWorkingMode()) return event;

            unsigned short keyCode = [event keyCode];

            // Cmd+Z/Cmd+Shift+Z: let Illustrator handle undo natively.
            // The SDK bundles tool mouse selectors into a single undo context,
            // so each drag is automatically undoable. No interception needed.

            // Enter/Return (keyCode 36 or 76) → Apply working mode
            if (keyCode == 36 || keyCode == 76) {
                BridgeRequestWorkingApply(true);
                fprintf(stderr, "[CleanupModule] Enter intercepted → enqueued Apply\n");
                return nil;
            }

            // Escape (keyCode 53) → Cancel working mode
            if (keyCode == 53) {
                BridgeRequestWorkingCancel();
                fprintf(stderr, "[CleanupModule] Escape intercepted → enqueued Cancel\n");
                return nil;
            }

            return event;  // pass through
        }];
    fprintf(stderr, "[CleanupModule] Undo interceptor installed\n");
    return monitor;
}

static void RemoveUndoInterceptor(void*& monitor)
{
    if (monitor) {
        [NSEvent removeMonitor:(id)monitor];
        monitor = nullptr;
        fprintf(stderr, "[CleanupModule] Undo interceptor removed\n");
    }
}

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
        if (!snap.art) {
            fprintf(stderr, "[UndoStack] skipping null art handle in frame\n");
            continue;
        }
        short artType = 0;
        ASErr err = sAIArt->GetArtType(snap.art, &artType);
        if (err != kNoErr) {
            fprintf(stderr, "[UndoStack] stale art handle (err=%d) — skipping\n", (int)err);
            continue;
        }
        if (artType != kPathArt) {
            fprintf(stderr, "[UndoStack] art is type %d, not path — skipping\n", (int)artType);
            continue;
        }
        if (snap.segments.empty()) {
            fprintf(stderr, "[UndoStack] empty segments in snapshot — skipping\n");
            continue;
        }
        ai::int16 nc = (ai::int16)snap.segments.size();
        err = sAIPath->SetPathSegmentCount(snap.art, nc);
        if (err != kNoErr) {
            fprintf(stderr, "[UndoStack] SetPathSegmentCount failed (err=%d) — skipping\n", (int)err);
            continue;
        }
        err = sAIPath->SetPathSegments(snap.art, 0, nc, snap.segments.data());
        if (err != kNoErr) {
            fprintf(stderr, "[UndoStack] SetPathSegments failed (err=%d)\n", (int)err);
            continue;
        }
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
            LearningEngine::Instance().JournalLog("average_selection",
                "\"shape\":\"auto\"");
            return true;

        case OpType::Classify:
            ClassifySelection();
            return true;

        case OpType::Reclassify:
            ReclassifyAs(static_cast<BridgeShapeType>(op.intParam));
            {
                char jbuf[128];
                snprintf(jbuf, sizeof(jbuf), "\"shape_type\":%d", op.intParam);
                LearningEngine::Instance().JournalLog("reclassify", jbuf);
            }
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
            LearningEngine::Instance().JournalLog("apply",
                op.boolParam1 ? "\"delete_originals\":true" : "\"delete_originals\":false");
            return true;

        case OpType::WorkingCancel:
            CancelWorkingMode();
            LearningEngine::Instance().JournalLog("cancel", "");
            return true;

        case OpType::UndoShape:
            if (fInWorkingMode && fUndoStack.CanUndo()) {
                // Validate: top frame must target the current preview path
                if (!fPreviewPath || !fUndoStack.TopFrameTargets(fPreviewPath)) {
                    fprintf(stderr, "[CleanupModule] UndoShape: stale frame — clearing + cancel\n");
                    fUndoStack.Clear();
                    CancelWorkingMode();
                    return true;
                }
                {
                    int restored = fUndoStack.Undo();
                    fprintf(stderr, "[CleanupModule] UndoShape in working mode: restored %d paths (%zu remain)\n",
                            restored, fUndoStack.FrameCount());
                    ComputeBoundingBox();
                    InvalidateFullView();
                }
            } else if (fInWorkingMode) {
                CancelWorkingMode();
            } else if (fUndoStack.CanUndo()) {
                int restored = fUndoStack.Undo();
                fprintf(stderr, "[CleanupModule] UndoShape: restored %d paths\n", restored);
                sAIDocument->RedrawDocument();
            }
            return true;

        case OpType::SelectSmall:
            SelectSmall(op.param1, op.intParam);
            return true;

        case OpType::Resmooth:
            if (fInWorkingMode && fPreviewPath) {
                ai::int16 segCount = 0;
                sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
                std::vector<AIPathSegment> segs(segCount);
                sAIPath->GetPathSegments(fPreviewPath, 0, segCount, segs.data());
                std::vector<AIRealPoint> pts(segCount);
                for (int i = 0; i < segCount; i++) pts[i] = segs[i].p;
                AIBoolean closed = false;
                sAIPath->GetPathClosed(fPreviewPath, &closed);
                double tension = BridgeGetTension() / 300.0;  // 0-100 → 0-0.33
                auto handles = ComputeSmoothHandles(pts, closed, tension);
                UpdatePreviewSegments(fPreviewPath, pts, handles, closed);
                ComputeBoundingBox();
                InvalidateFullView();
                sAIDocument->RedrawDocument();
                fprintf(stderr, "[CleanupModule] Resmooth: tension=%.3f\n", tension);
            }
            return true;

        default:
            return false;
    }
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

CleanupModule::~CleanupModule()
{
    // Belt-and-suspenders: remove NSEvent monitor if still installed
    // (normally removed in Cancel/Apply/OnDocumentChanged, but this catches plugin unload)
    RemoveUndoInterceptor(fUndoEventMonitor);
}

void CleanupModule::OnDocumentChanged()
{
    // Clean up Enter/Escape interceptor across documents
    RemoveUndoInterceptor(fUndoEventMonitor);

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
    // Don't undo mid-drag — the drag-in-progress guard in ProcessOperationQueue
    // should have deferred this, but belt-and-suspenders here too.
    if (fDragAnchorIdx >= 0 || fBBox.dragHandle >= 0 || fDragBezierIdx >= 0) {
        fprintf(stderr, "[CleanupModule] Undo blocked: drag in progress\n");
        return;
    }

    if (fInWorkingMode) {
        // Cmd+Z in working mode = cancel the session.
        // Custom UndoStack segment restoration crashes because Illustrator's internal
        // undo state becomes inconsistent with our direct SetPathSegments calls,
        // even with SetSilent(true). Disabling per-drag undo until a safer approach
        // is found (e.g., using AIUndoSuite::UndoChanges instead of manual restore).
        CancelWorkingMode();
    } else if (fUndoStack.CanUndo()) {
        int restored = fUndoStack.Undo();
        fprintf(stderr, "[CleanupModule] Undo: restored %d paths\n", restored);
        sAIDocument->RedrawDocument();
    }
}

//========================================================================================
//  Include split implementation files — not separate compilation units
//========================================================================================

#include "CleanupHandles.cpp"
#include "CleanupPipeline.cpp"
