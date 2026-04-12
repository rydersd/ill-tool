//========================================================================================
//  CleanupHandles — Handle interaction + annotator drawing for CleanupModule
//
//  Split from CleanupModule.cpp. All methods are CleanupModule members.
//  This file is #included from CleanupModule.cpp (not compiled separately).
//========================================================================================

#include "CleanupModule.h"
#include "IllToolSuites.h"
#include "ShapeUtils.h"
#include "LearningEngine.h"
#include "HttpBridge.h"

#include <cstdio>
#include <cmath>
#include <vector>

extern IllToolPlugin* gPlugin;

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

    // Double-click on an anchor: toggle handles in/out (same as Shift-click but no modifier needed)
    if (!optionKey && !shiftKey && fPreviewPath) {
        int anchorHit = HitTestAnchorHandle(artPt, 7.0);
        if (anchorHit >= 0) {
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - fLastClickTime).count();
            if (anchorHit == fLastClickedAnchor && elapsed < 400) {
                // Double-click detected — toggle handles
                fLastClickedAnchor = -1;  // reset to prevent triple-click
                ai::int16 segCount = 0;
                sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
                if (anchorHit < segCount) {
                    AIPathSegment seg;
                    sAIPath->GetPathSegments(fPreviewPath, anchorHit, 1, &seg);
                    if (seg.corner) {
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
                        seg.corner = true;
                        seg.in = seg.p;
                        seg.out = seg.p;
                    }
                    fUndoStack.PushFrame();
                    fUndoStack.SnapshotPath(fPreviewPath);
                    sAIPath->SetPathSegments(fPreviewPath, anchorHit, 1, &seg);
                    InvalidateFullView();
                    sAIDocument->RedrawDocument();
                    fprintf(stderr, "[CleanupModule] Double-click toggled point %d to %s\n",
                            anchorHit, seg.corner ? "sharp" : "smooth");
                    return true;
                }
            }
            fLastClickedAnchor = anchorHit;
            fLastClickTime = now;
        } else {
            fLastClickedAnchor = -1;
        }
    }

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
            // Push undo frame before bezier handle drag
            fUndoStack.PushFrame();
            fUndoStack.SnapshotPath(fPreviewPath);
            fDragBezierIdx = bezierHit;
            fBezierDragStart = artPt;
            fprintf(stderr, "[CleanupModule] Bezier handle drag start: %s of seg %d (undo frame pushed)\n",
                    (bezierHit % 2 == 0) ? "in" : "out", bezierHit / 2);
            return true;
        }
    }

    // Priority 2: path anchor handle hit-test (squares)
    int anchorHit = HitTestAnchorHandle(artPt);
    if (anchorHit >= 0) {
        fDragAnchorIdx = anchorHit;
        fAnchorDragStart = artPt;
        // Push undo frame BEFORE drag so Cmd+Z can restore
        fUndoStack.PushFrame();
        fUndoStack.SnapshotPath(fPreviewPath);
        // Snapshot the original segment for drag delta computation
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(fPreviewPath, &segCount);
        if (anchorHit < segCount) {
            sAIPath->GetPathSegments(fPreviewPath, anchorHit, 1, &fAnchorDragOrigSeg);
        }
        fprintf(stderr, "[CleanupModule] Anchor drag start: idx=%d (undo frame pushed)\n", anchorHit);
        return true;
    }

    // Priority 2: bounding box handle hit-test (circles)
    if (fBBox.visible) {
        int bboxHit = HitTestBBoxHandle(artPt);
        if (bboxHit >= 0) {
            // Push undo frame BEFORE drag so Cmd+Z can restore
            fUndoStack.PushFrame();
            fUndoStack.SnapshotPath(fPreviewPath);
            fBBox.dragHandle = bboxHit;
            fBBox.dragStart = artPt;
            fprintf(stderr, "[CleanupModule] BBox drag start: handle=%d\n", bboxHit);
            return true;
        }

        // Priority 3: rotate zone — outside bbox near corners
        if (HitTestBBoxRotateZone(artPt)) {
            // Push undo frame BEFORE rotation drag
            fUndoStack.PushFrame();
            fUndoStack.SnapshotPath(fPreviewPath);
            fBBox.dragHandle = 8;  // 8 = rotating
            fBBox.dragStart = artPt;
            fBBox.dragStartAngle = atan2(artPt.v - fBBox.center.v, artPt.h - fBBox.center.h);
            fprintf(stderr, "[CleanupModule] Rotation drag start (undo frame pushed)\n");
            return true;
        }
    }

    return false;
}

bool CleanupModule::HandleMouseDrag(AIToolMessage* msg)
{
    // Bezier handle drag
    if (fDragBezierIdx >= 0) {
        // Check snap-to-anchor proximity for visual feedback
        int segIdx = fDragBezierIdx / 2;
        if (fPreviewPath && segIdx >= 0) {
            ai::int16 sc = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &sc);
            if (segIdx < sc) {
                AIPathSegment seg;
                sAIPath->GetPathSegments(fPreviewPath, segIdx, 1, &seg);
                fBezierSnapPreview = (ViewSpaceDist(msg->cursor, seg.p) <= 5.0);
            }
        }
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
        fBezierSnapPreview = false;
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

        // Record correction delta for LearningEngine
        if (fPreviewPath) {
            AIPathSegment finalSeg;
            ai::int16 sc = 0;
            sAIPath->GetPathSegmentCount(fPreviewPath, &sc);
            if (fDragAnchorIdx < sc) {
                sAIPath->GetPathSegments(fPreviewPath, fDragAnchorIdx, 1, &finalSeg);
                double dx = finalSeg.p.h - fAnchorDragOrigSeg.p.h;
                double dy = finalSeg.p.v - fAnchorDragOrigSeg.p.v;
                if (fabs(dx) > 0.5 || fabs(dy) > 0.5) {
                    const char* surfHint = SurfaceTypeName(BridgeGetSurfaceType());
                    const char* shapeNames[] = {"line","arc","l","rect","s","ellipse","free"};
                    int si = (int)fCachedShapeFit.shape;
                    const char* shapeHint = (si >= 0 && si < 7) ? shapeNames[si] : "unknown";
                    LearningEngine::Instance().RecordCorrection(surfHint, dx, dy, shapeHint);
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
        // Check bbox handles — use same hit radius as HandleMouseDown (6.0)
        // so cursor feedback matches click behavior
        fHoverBBoxIdx = HitTestBBoxHandle(artPt, 6.0);
        if (fHoverBBoxIdx < 0 && HitTestBBoxRotateZone(artPt, 6.0, 20.0)) {
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
    // NOTE: do NOT reset fBBox.dragHandle here — that kills mid-drag updates.
    // dragHandle is managed by HandleMouseDown (set) and HandleMouseUp (clear).
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

    AIRGBColor handleFill    = ITK_COLOR_HANDLE_FILL();
    AIRGBColor handleStroke  = edgeColor;

    // Active = orange, Hover = light blue (keeping existing visual appearance)
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

    // Handle colors — white fill, dark stroke (active = orange)
    AIRGBColor handleFill    = ITK_COLOR_HANDLE_FILL();

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

    int handleSize = (int)ITK_SIZE_ANCHOR;  // half-size of square — matches bbox circle radius

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

        // Snap highlight: when dragging a bezier handle near this anchor, show magenta
        AIRGBColor snapFill;
        snapFill.red   = (ai::uint16)(1.0 * 65535);
        snapFill.green = (ai::uint16)(0.2 * 65535);
        snapFill.blue  = (ai::uint16)(0.6 * 65535);

        bool active = (fDragAnchorIdx == (int)i);
        bool hovered = (fHoverAnchorIdx == (int)i);
        bool snapTarget = (fBezierSnapPreview && fDragBezierIdx >= 0 && fDragBezierIdx / 2 == (int)i);
        const AIRGBColor& fill = snapTarget ? snapFill : (active ? activeFill : (hovered ? hoverFill : handleFill));
        int hs = (hovered || snapTarget) ? handleSize + 2 : handleSize;
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

    // Snap-to-anchor: if handle is dragged within 5px of its anchor, collapse to corner
    double snapDist = ViewSpaceDist(newPos, seg.p);
    if (snapDist <= 5.0) {
        seg.in = seg.p;
        seg.out = seg.p;
        seg.corner = true;
        sAIPath->SetPathSegments(fPreviewPath, segIdx, 1, &seg);
        fprintf(stderr, "[CleanupModule] Bezier handle snapped to anchor — collapsed to corner (seg %d)\n", segIdx);
        return;
    }

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
