//========================================================================================
//  PenModule — Ill Pen Tool implementation
//
//  Smart pen with click-to-place, drag-to-handle, chamfered corners,
//  grouping integration, and live annotator preview.
//========================================================================================

#include "IllustratorSDK.h"
#include "PenModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include "IllToolTokens.h"

#include <cstdio>
#include <cmath>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Operation dispatch
//========================================================================================

bool PenModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::PenPlacePoint:
            fprintf(stderr, "[PenModule] PlacePoint (%.1f, %.1f)\n", op.param1, op.param2);
            PlacePoint(op.param1, op.param2);
            InvalidateFullView();
            return true;

        case OpType::PenFinalize:
            fprintf(stderr, "[PenModule] Finalize\n");
            Finalize();
            InvalidateFullView();
            return true;

        case OpType::PenCancel:
            fprintf(stderr, "[PenModule] Cancel\n");
            Cancel();
            InvalidateFullView();
            return true;

        case OpType::PenSetChamfer:
            fprintf(stderr, "[PenModule] SetChamfer radius=%.1f\n", op.param1);
            SetChamfer(op.param1);
            InvalidateFullView();
            return true;

        case OpType::PenUndo:
            fprintf(stderr, "[PenModule] Undo last point\n");
            UndoLastPoint();
            InvalidateFullView();
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  Mouse interaction
//========================================================================================

bool PenModule::HandleMouseDown(AIToolMessage* msg)
{
    // Only handle clicks when pen mode is active
    if (!BridgeGetPenMode()) return false;

    AIRealPoint artPt = msg->cursor;

    // Check for double-click → finalize
    auto now = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - fLastClickTime).count();
    double dist = std::sqrt(
        (artPt.h - fLastClickPos.h) * (artPt.h - fLastClickPos.h) +
        (artPt.v - fLastClickPos.v) * (artPt.v - fLastClickPos.v));

    if (fDrawing && elapsed < kDoubleClickMs && dist < kDoubleClickDist) {
        // Double-click: remove the extra point that was just added by the first click
        // and finalize
        if (!fPoints.empty()) {
            fPoints.pop_back();
            fHandles.pop_back();
            fChamferRadii.pop_back();
        }
        Finalize();
        fPreviewDirty = true;
        InvalidateFullView();
        fLastClickTime = {};
        return true;
    }

    fLastClickTime = now;
    fLastClickPos = artPt;

    // Place a new point
    PlacePoint(artPt.h, artPt.v);
    fDragging = true;
    fDragCurrent = artPt;
    InvalidateFullView();

    return true;
}

bool PenModule::HandleMouseDrag(AIToolMessage* msg)
{
    if (!BridgeGetPenMode() || !fDragging || fPoints.empty()) return false;

    fDragCurrent = msg->cursor;

    // Update the handle for the current (last placed) point.
    // Handle direction = drag position relative to the anchor point.
    size_t lastIdx = fPoints.size() - 1;
    AIRealPoint anchor = fPoints[lastIdx];

    // The handle stores the outgoing direction handle position (absolute coords)
    fHandles[lastIdx].h = fDragCurrent.h;
    fHandles[lastIdx].v = fDragCurrent.v;

    fPreviewDirty = true;
    InvalidateFullView();

    return true;
}

bool PenModule::HandleMouseUp(AIToolMessage* msg)
{
    if (!BridgeGetPenMode() || !fDragging) return false;

    fDragging = false;

    // If user didn't drag far, clear the handle (corner point)
    if (!fPoints.empty()) {
        size_t lastIdx = fPoints.size() - 1;
        double dx = fHandles[lastIdx].h - fPoints[lastIdx].h;
        double dy = fHandles[lastIdx].v - fPoints[lastIdx].v;
        double handleDist = std::sqrt(dx * dx + dy * dy);
        if (handleDist < 2.0) {
            // Negligible drag — treat as corner point
            fHandles[lastIdx] = fPoints[lastIdx];
        }
    }

    fPreviewDirty = true;
    InvalidateFullView();
    return true;
}

//========================================================================================
//  Point operations
//========================================================================================

void PenModule::PlacePoint(double x, double y)
{
    AIRealPoint pt;
    pt.h = (AIReal)x;
    pt.v = (AIReal)y;

    fPoints.push_back(pt);
    fHandles.push_back(pt);  // default: corner point (handle at anchor)

    // Get chamfer radius from bridge (uniform or per-point)
    double chamfer = BridgeGetPenChamferRadius();
    fChamferRadii.push_back(chamfer);

    if (!fDrawing) {
        fDrawing = true;
        fprintf(stderr, "[PenModule] Drawing started\n");
    }

    fPreviewDirty = true;
}

void PenModule::UndoLastPoint()
{
    if (fPoints.empty()) return;

    fPoints.pop_back();
    fHandles.pop_back();
    fChamferRadii.pop_back();

    if (fPoints.empty()) {
        Cancel();
        return;
    }

    fPreviewDirty = true;
}

void PenModule::SetChamfer(double radius)
{
    bool uniform = BridgeGetPenUniformEdges();
    if (uniform) {
        // Apply to all points
        for (auto& r : fChamferRadii) r = radius;
    } else if (!fChamferRadii.empty()) {
        // Apply to last point only
        fChamferRadii.back() = radius;
    }
    UpdatePreview();
}

//========================================================================================
//  Finalize — create the real AI path
//========================================================================================

void PenModule::Finalize()
{
    if (fPoints.size() < 2) {
        fprintf(stderr, "[PenModule] Not enough points to finalize (%zu)\n", fPoints.size());
        Cancel();
        return;
    }

    // Build segments with chamfers
    auto segs = BuildSegments();

    // Determine if path should be closed (last point near first point)
    bool closed = false;
    if (fPoints.size() >= 3) {
        double dx = fPoints.front().h - fPoints.back().h;
        double dy = fPoints.front().v - fPoints.back().v;
        double dist = std::sqrt(dx * dx + dy * dy);
        if (dist < 8.0) {
            closed = true;
            // Remove the last point (it overlaps the first)
            if (!segs.empty()) {
                segs.pop_back();
            }
        }
    }

    // Create the actual path
    AIArtHandle finalPath = CreateFinalPath(segs, closed);
    if (finalPath) {
        // Apply path name from panel
        std::string pathName = BridgeGetPenPathName();
        if (!pathName.empty() && sAIArt) {
            sAIArt->SetArtName(finalPath, ai::UnicodeString(pathName));
            fprintf(stderr, "[PenModule] Named path '%s'\n", pathName.c_str());
        }

        // Select the new path
        if (sAIArt) {
            sAIArt->SetArtUserAttr(finalPath, kArtSelected, kArtSelected);
        }

        fprintf(stderr, "[PenModule] Path created with %zu segments (closed=%d)\n",
                segs.size(), (int)closed);
    }

    // Clean up drawing state
    DeletePreview();
    fPoints.clear();
    fHandles.clear();
    fChamferRadii.clear();
    fDrawing = false;
    fDragging = false;
}

void PenModule::Cancel()
{
    DeletePreview();
    fPoints.clear();
    fHandles.clear();
    fChamferRadii.clear();
    fDrawing = false;
    fDragging = false;
    fprintf(stderr, "[PenModule] Drawing cancelled\n");
}

//========================================================================================
//  Path building
//========================================================================================

std::vector<AIPathSegment> PenModule::BuildSegments() const
{
    std::vector<AIPathSegment> segs;
    if (fPoints.empty()) return segs;

    segs.resize(fPoints.size());

    for (size_t i = 0; i < fPoints.size(); i++) {
        AIPathSegment& seg = segs[i];
        seg.p = fPoints[i];

        // Check if this point has a handle (not at anchor = smooth point)
        double dx = fHandles[i].h - fPoints[i].h;
        double dy = fHandles[i].v - fPoints[i].v;
        double handleDist = std::sqrt(dx * dx + dy * dy);

        if (handleDist > 2.0) {
            // Smooth point — handle gives outgoing direction
            // Incoming handle is mirrored
            seg.out = fHandles[i];
            seg.in.h = fPoints[i].h - dx;
            seg.in.v = fPoints[i].v - dy;
            seg.corner = false;
        } else {
            // Corner point — handles at anchor
            seg.in = fPoints[i];
            seg.out = fPoints[i];
            seg.corner = true;
        }
    }

    // Apply chamfers to corner points
    std::vector<double> radii = fChamferRadii;
    // Ensure radii vector matches segment count
    while (radii.size() < segs.size()) radii.push_back(0.0);
    ApplyChamfers(segs, radii);

    return segs;
}

void PenModule::ApplyChamfers(std::vector<AIPathSegment>& segs,
                              const std::vector<double>& radii)
{
    if (segs.size() < 3) return;  // Need at least 3 points for a corner

    // Work backwards so insertion indices stay valid
    for (int i = (int)segs.size() - 2; i >= 1; i--) {
        if (i >= (int)radii.size() || radii[i] <= 0.0) continue;
        if (!segs[i].corner) continue;  // Only chamfer corner points

        AIPathSegment seg1, seg2;
        bool ok = ComputeChamferArc(
            segs[i - 1].p, segs[i].p, segs[i + 1].p,
            radii[i], seg1, seg2);

        if (ok) {
            // Replace the corner point with two arc points
            segs.erase(segs.begin() + i);
            segs.insert(segs.begin() + i, seg2);
            segs.insert(segs.begin() + i, seg1);
        }
    }
}

bool PenModule::ComputeChamferArc(AIRealPoint prev, AIRealPoint corner, AIRealPoint next,
                                  double radius,
                                  AIPathSegment& outSeg1, AIPathSegment& outSeg2)
{
    // Vector from corner to prev
    double dx1 = prev.h - corner.h;
    double dy1 = prev.v - corner.v;
    double len1 = std::sqrt(dx1 * dx1 + dy1 * dy1);

    // Vector from corner to next
    double dx2 = next.h - corner.h;
    double dy2 = next.v - corner.v;
    double len2 = std::sqrt(dx2 * dx2 + dy2 * dy2);

    if (len1 < 0.01 || len2 < 0.01) return false;

    // Normalize
    double nx1 = dx1 / len1, ny1 = dy1 / len1;
    double nx2 = dx2 / len2, ny2 = dy2 / len2;

    // Clamp radius to half the shorter edge
    double maxR = std::min(len1, len2) * 0.5;
    double r = std::min(radius, maxR);
    if (r < 0.5) return false;

    // Points where the arc starts and ends
    AIRealPoint p1, p2;
    p1.h = (AIReal)(corner.h + nx1 * r);
    p1.v = (AIReal)(corner.v + ny1 * r);
    p2.h = (AIReal)(corner.h + nx2 * r);
    p2.v = (AIReal)(corner.v + ny2 * r);

    // Compute the angle between the two edges
    double dot = nx1 * nx2 + ny1 * ny2;
    dot = std::max(-1.0, std::min(1.0, dot));
    double halfAngle = std::acos(dot) / 2.0;

    // Handle length for circular arc approximation
    // For a 90-degree arc: kappa = 0.5522847498
    // General formula: k = (4/3) * tan(angle/4)
    double arcAngle = M_PI - std::acos(dot);  // the arc's sweep angle
    double k = (4.0 / 3.0) * std::tan(arcAngle / 4.0);
    double handleLen = r * k;

    // Tangent directions at arc endpoints
    // At p1: tangent perpendicular to (corner->prev) direction, toward p2
    // At p2: tangent perpendicular to (corner->next) direction, toward p1
    // Tangent at p1 is along the edge direction (toward next, not prev)
    double tx1 = -nx1;  // tangent at p1 points away from prev toward the arc
    double ty1 = -ny1;
    double tx2 = -nx2;  // tangent at p2 points away from next toward the arc
    double ty2 = -ny2;

    // Segment 1: start of arc (on incoming edge)
    outSeg1.p = p1;
    outSeg1.in = p1;  // incoming handle: straight from previous edge
    outSeg1.out.h = (AIReal)(p1.h + tx1 * handleLen);
    outSeg1.out.v = (AIReal)(p1.v + ty1 * handleLen);
    outSeg1.corner = false;

    // Segment 2: end of arc (on outgoing edge)
    outSeg2.p = p2;
    outSeg2.in.h = (AIReal)(p2.h + tx2 * handleLen);
    outSeg2.in.v = (AIReal)(p2.v + ty2 * handleLen);
    outSeg2.out = p2;  // outgoing handle: straight to next edge
    outSeg2.corner = false;

    return true;
}

//========================================================================================
//  Preview path
//========================================================================================

void PenModule::UpdatePreview()
{
    if (fPoints.size() < 2) {
        DeletePreview();
        return;
    }

    auto segs = BuildSegments();
    if (segs.empty()) return;

    try {
        if (!fPreviewPath) {
            // Create a new preview path
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &fPreviewPath);
            if (err != kNoErr || !fPreviewPath) {
                fprintf(stderr, "[PenModule] Failed to create preview path\n");
                return;
            }
        }

        // Set segments
        sAIPath->SetPathSegmentCount(fPreviewPath, (ai::int16)segs.size());
        sAIPath->SetPathSegments(fPreviewPath, 0, (ai::int16)segs.size(), segs.data());
        sAIPath->SetPathClosed(fPreviewPath, false);

        // Style: thin blue stroke, no fill
        AIPathStyle style;
        memset(&style, 0, sizeof(style));
        style.fillPaint = false;
        style.strokePaint = true;
        style.stroke.width = 1.0;
        style.stroke.color.kind = kThreeColor;
        style.stroke.color.c.rgb.red   = 0.3f;
        style.stroke.color.c.rgb.green = 0.6f;
        style.stroke.color.c.rgb.blue  = 1.0f;

        sAIPathStyle->SetPathStyle(fPreviewPath, &style);
    }
    catch (...) {
        fprintf(stderr, "[PenModule] Exception updating preview\n");
    }
}

void PenModule::TickUpdatePreview()
{
    if (!fPreviewDirty) return;
    fPreviewDirty = false;
    UpdatePreview();
}

void PenModule::DeletePreview()
{
    if (fPreviewPath) {
        try {
            sAIArt->DisposeArt(fPreviewPath);
        } catch (...) {}
        fPreviewPath = nullptr;
    }
}

//========================================================================================
//  Create final path with grouping
//========================================================================================

AIArtHandle PenModule::CreateFinalPath(const std::vector<AIPathSegment>& segs, bool closed)
{
    AIArtHandle finalPath = nullptr;

    try {
        // Determine target group from bridge state
        std::string targetGroup = BridgeGetPenTargetGroup();
        AIArtHandle groupArt = nullptr;

        if (!targetGroup.empty() && targetGroup != "None") {
            // Find group by name in the document
            AIMatchingArtSpec spec;
            spec.type = kGroupArt;
            spec.whichAttr = 0;
            spec.attr = 0;
            AIArtHandle** matches = nullptr;
            ai::int32 numMatches = 0;
            ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
            if (err == kNoErr && numMatches > 0) {
                for (ai::int32 i = 0; i < numMatches; i++) {
                    ai::UnicodeString name;
                    sAIArt->GetArtName((*matches)[i], name, nullptr);
                    if (name.as_UTF8() == targetGroup) {
                        groupArt = (*matches)[i];
                        break;
                    }
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            }
        }

        // Create path: inside target group, or in target layer, or in current layer
        if (groupArt) {
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, groupArt, &finalPath);
            if (err != kNoErr) finalPath = nullptr;
        }

        // If no group target, try the Ill Layers target layer
        if (!finalPath) {
            std::string layerTarget = BridgeGetLayerTarget();
            if (!layerTarget.empty() && sAILayer) {
                AILayerHandle targetLayer = nullptr;
                ai::UnicodeString uTarget(layerTarget);
                sAILayer->GetLayerByTitle(&targetLayer, uTarget);
                if (targetLayer) {
                    AIArtHandle layerArt = nullptr;
                    sAIArt->GetFirstArtOfLayer(targetLayer, &layerArt);
                    if (layerArt) {
                        ASErr err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, layerArt, &finalPath);
                        if (err != kNoErr) finalPath = nullptr;
                        else fprintf(stderr, "[PenModule] Path placed in target layer: %s\n", layerTarget.c_str());
                    }
                }
            }
        }

        // Fallback: create in the current layer (not at document top)
        if (!finalPath && sAILayer) {
            AILayerHandle currentLayer = nullptr;
            sAILayer->GetCurrentLayer(&currentLayer);
            if (currentLayer) {
                AIArtHandle layerArt = nullptr;
                sAIArt->GetFirstArtOfLayer(currentLayer, &layerArt);
                if (layerArt) {
                    ASErr err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, layerArt, &finalPath);
                    if (err != kNoErr) finalPath = nullptr;
                    else fprintf(stderr, "[PenModule] Path placed in current layer\n");
                }
            }
        }

        // Last resort: top of document
        if (!finalPath) {
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &finalPath);
            if (err != kNoErr) return nullptr;
        }

        // Set segments
        sAIPath->SetPathSegmentCount(finalPath, (ai::int16)segs.size());
        sAIPath->SetPathSegments(finalPath, 0, (ai::int16)segs.size(), segs.data());
        sAIPath->SetPathClosed(finalPath, closed);

        // Style: default black stroke, no fill
        AIPathStyle style;
        memset(&style, 0, sizeof(style));
        style.fillPaint = false;
        style.strokePaint = true;
        style.stroke.width = 1.0;
        style.stroke.color.kind = kThreeColor;
        style.stroke.color.c.rgb.red   = 0.0f;
        style.stroke.color.c.rgb.green = 0.0f;
        style.stroke.color.c.rgb.blue  = 0.0f;

        sAIPathStyle->SetPathStyle(finalPath, &style);

        fprintf(stderr, "[PenModule] Final path created (%zu segs, closed=%d, group='%s')\n",
                segs.size(), (int)closed,
                targetGroup.empty() ? "<none>" : targetGroup.c_str());
    }
    catch (...) {
        fprintf(stderr, "[PenModule] Exception creating final path\n");
    }

    return finalPath;
}

//========================================================================================
//  Annotator overlay
//========================================================================================

void PenModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    if (!BridgeGetPenMode() || !fDrawing || fPoints.empty()) return;
    if (!msg || !msg->drawer || !sAIDocumentView) return;

    DrawPathLines(msg);
    DrawAnchorHandles(msg);
    DrawBezierHandles(msg);
    DrawChamferPreviews(msg);
}

void PenModule::DrawPathLines(AIAnnotatorMessage* msg)
{
    if (fPoints.size() < 2) return;

    AIAnnotatorDrawer* drawer = msg->drawer;

    // First pass: shadow outline for contrast against any background
    sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_PRIMARY_SHADOW());
    sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_SHADOW);

    for (size_t i = 0; i + 1 < fPoints.size(); i++) {
        AIPoint viewA, viewB;
        ASErr err1 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i], &viewA);
        ASErr err2 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i + 1], &viewB);
        if (err1 == kNoErr && err2 == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, viewA, viewB);
        }
    }

    // Second pass: primary highlight on top
    sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_PRIMARY());
    sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_PRIMARY);

    for (size_t i = 0; i + 1 < fPoints.size(); i++) {
        AIPoint viewA, viewB;
        ASErr err1 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i], &viewA);
        ASErr err2 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i + 1], &viewB);
        if (err1 == kNoErr && err2 == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, viewA, viewB);
        }
    }

    // Draw line from last point to current drag position (rubber band)
    if (fDragging && fPoints.size() >= 1) {
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_SECONDARY());
        sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_SECONDARY);

        AIPoint viewLast, viewCur;
        ASErr err1 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints.back(), &viewLast);
        ASErr err2 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fDragCurrent, &viewCur);
        if (err1 == kNoErr && err2 == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, viewLast, viewCur);
        }
    }
}

void PenModule::DrawAnchorHandles(AIAnnotatorMessage* msg)
{
    AIAnnotatorDrawer* drawer = msg->drawer;

    // Draw square handles at each anchor point
    AIRGBColor white = ITK_COLOR_HANDLE_FILL();
    AIRGBColor blue = ITK_COLOR_HANDLE_STROKE();

    for (size_t i = 0; i < fPoints.size(); i++) {
        AIPoint viewPt;
        ASErr err = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i], &viewPt);
        if (err != kNoErr) continue;

        int sz = (int)kAnchorSize;
        AIRect rect;
        rect.left   = viewPt.h - sz;
        rect.top    = viewPt.v - sz;
        rect.right  = viewPt.h + sz;
        rect.bottom = viewPt.v + sz;

        // Fill white, stroke blue
        sAIAnnotatorDrawer->SetColor(drawer, white);
        sAIAnnotatorDrawer->DrawRect(drawer, rect, true);
        sAIAnnotatorDrawer->SetColor(drawer, blue);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
        sAIAnnotatorDrawer->DrawRect(drawer, rect, false);
    }
}

void PenModule::DrawBezierHandles(AIAnnotatorMessage* msg)
{
    AIAnnotatorDrawer* drawer = msg->drawer;

    // Draw direction handles for smooth points
    AIRGBColor handleColor = ITK_COLOR_BEZIER_HANDLE();

    for (size_t i = 0; i < fPoints.size(); i++) {
        double dx = fHandles[i].h - fPoints[i].h;
        double dy = fHandles[i].v - fPoints[i].v;
        double dist = std::sqrt(dx * dx + dy * dy);
        if (dist < 2.0) continue;  // Corner point, no handle to draw

        AIPoint viewAnchor, viewHandle, viewMirror;
        ASErr err1 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPoints[i], &viewAnchor);
        ASErr err2 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &fHandles[i], &viewHandle);
        if (err1 != kNoErr || err2 != kNoErr) continue;

        // Mirror handle (incoming)
        AIRealPoint mirrorPt;
        mirrorPt.h = fPoints[i].h - dx;
        mirrorPt.v = fPoints[i].v - dy;
        ASErr err3 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &mirrorPt, &viewMirror);

        sAIAnnotatorDrawer->SetColor(drawer, handleColor);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 0.75);

        // Draw handle lines
        sAIAnnotatorDrawer->DrawLine(drawer, viewAnchor, viewHandle);
        if (err3 == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, viewAnchor, viewMirror);
        }

        // Draw handle endpoint circles
        int r = (int)kBezierHandleSize;
        AIRect handleRect;
        handleRect.left   = viewHandle.h - r;
        handleRect.top    = viewHandle.v - r;
        handleRect.right  = viewHandle.h + r;
        handleRect.bottom = viewHandle.v + r;
        sAIAnnotatorDrawer->DrawEllipse(drawer, handleRect, false);

        if (err3 == kNoErr) {
            AIRect mirrorRect;
            mirrorRect.left   = viewMirror.h - r;
            mirrorRect.top    = viewMirror.v - r;
            mirrorRect.right  = viewMirror.h + r;
            mirrorRect.bottom = viewMirror.v + r;
            sAIAnnotatorDrawer->DrawEllipse(drawer, mirrorRect, false);
        }
    }
}

void PenModule::DrawChamferPreviews(AIAnnotatorMessage* msg)
{
    if (fPoints.size() < 3) return;

    AIAnnotatorDrawer* drawer = msg->drawer;

    AIRGBColor chamferColor;
    chamferColor.red   = 65535;
    chamferColor.green = (ai::uint16)(0.7 * 65535);
    chamferColor.blue  = 0;

    sAIAnnotatorDrawer->SetColor(drawer, chamferColor);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.5);

    for (size_t i = 1; i + 1 < fPoints.size(); i++) {
        if (i >= fChamferRadii.size() || fChamferRadii[i] <= 0.0) continue;

        AIPathSegment seg1, seg2;
        bool ok = ComputeChamferArc(fPoints[i - 1], fPoints[i], fPoints[i + 1],
                                    fChamferRadii[i], seg1, seg2);
        if (!ok) continue;

        // Draw the chamfer arc as a line from seg1.p to seg2.p
        // (simplified preview -- full bezier would need DrawBezier API)
        AIPoint viewP1, viewP2;
        ASErr err1 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &seg1.p, &viewP1);
        ASErr err2 = sAIDocumentView->ArtworkPointToViewPoint(NULL, &seg2.p, &viewP2);
        if (err1 == kNoErr && err2 == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, viewP1, viewP2);
        }
    }
}

//========================================================================================
//  Notifications
//========================================================================================

void PenModule::OnSelectionChanged()
{
    // No action needed for pen mode on selection change
}

void PenModule::OnDocumentChanged()
{
    Cancel();
}
