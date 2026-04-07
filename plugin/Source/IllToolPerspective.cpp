//========================================================================================
//
//  IllTool Plugin — Perspective Grid (Stage 10)
//
//  Implements line-based perspective grid: users place two-handle lines on the canvas,
//  VPs are computed by extending those lines to their intersection points.
//  Provides homography, projection, mirroring, and annotator overlay drawing.
//
//  NOTE: This file must be added to the Xcode project's pbxproj.
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  PerspectiveGrid method implementations
//========================================================================================

void IllToolPlugin::PerspectiveGrid::Recompute()
{
    // A grid is valid when at least the left and right VP lines are active
    valid = leftVP.active && rightVP.active;

    if (leftVP.active && rightVP.active) {
        // Compute VP1: extend left VP line to intersect with right VP line
        // Each line defines a direction; the VP is where both directions converge
        // For left VP: the VP is at the far extension of the left line
        // We use a vertical reference line through infinity — simpler: just extend the line far
        // Actually: VP1 is the point where all leftVP-parallel lines meet. That's the extension
        // of the leftVP line itself. We need TWO lines that share a VP to find the intersection.
        //
        // Correct approach: VP1 = the point where the leftVP line (extended) meets the horizon.
        // VP2 = where the rightVP line (extended) meets the horizon.
        // But with just one line per VP, the VP IS the extension of that line to the horizon.
        //
        // For a robust 2-VP system: each line represents a perspective edge in the scene.
        // The VP is found by extending the line to infinity (or to the horizon).
        // With a single line, the VP direction is simply the line direction.
        // The computed VP position = where the line ray hits the horizon.

        // Left VP: extend leftVP line to the horizon (horizonY)
        double ldx = leftVP.handle2.h - leftVP.handle1.h;
        double ldy = leftVP.handle2.v - leftVP.handle1.v;
        if (std::abs(ldy) > 1e-10) {
            double t = (horizonY - leftVP.handle1.v) / ldy;
            computedVP1.h = (AIReal)(leftVP.handle1.h + t * ldx);
            computedVP1.v = (AIReal)horizonY;
        } else {
            // Horizontal line — VP at infinity in the direction of ldx
            computedVP1.h = (AIReal)(leftVP.handle1.h + ldx * 10000.0);
            computedVP1.v = (AIReal)horizonY;
        }

        // Right VP: extend rightVP line to the horizon
        double rdx = rightVP.handle2.h - rightVP.handle1.h;
        double rdy = rightVP.handle2.v - rightVP.handle1.v;
        if (std::abs(rdy) > 1e-10) {
            double t = (horizonY - rightVP.handle1.v) / rdy;
            computedVP2.h = (AIReal)(rightVP.handle1.h + t * rdx);
            computedVP2.v = (AIReal)horizonY;
        } else {
            computedVP2.h = (AIReal)(rightVP.handle1.h + rdx * 10000.0);
            computedVP2.v = (AIReal)horizonY;
        }
    }

    // Vertical VP (3-point perspective)
    if (verticalVP.active && valid) {
        double vdx = verticalVP.handle2.h - verticalVP.handle1.h;
        double vdy = verticalVP.handle2.v - verticalVP.handle1.v;
        // VP3 is the extension of the vertical line upward (or downward)
        // Project far along the line direction
        double len = std::sqrt(vdx * vdx + vdy * vdy);
        if (len > 1e-6) {
            double scale = 10000.0 / len;
            // Extend in the direction that goes away from horizon (upward = negative v)
            if (vdy > 0) scale = -scale;
            computedVP3.h = (AIReal)(verticalVP.handle1.h + vdx * scale);
            computedVP3.v = (AIReal)(verticalVP.handle1.v + vdy * scale);
        }
    }

    fprintf(stderr, "[IllTool] PerspectiveGrid::Recompute valid=%d lines=%d VP1=[%.0f,%.0f] VP2=[%.0f,%.0f]\n",
            valid, ActiveLineCount(),
            (double)computedVP1.h, (double)computedVP1.v,
            (double)computedVP2.h, (double)computedVP2.v);
}

void IllToolPlugin::PerspectiveGrid::Clear()
{
    leftVP.active = false;
    rightVP.active = false;
    verticalVP.active = false;
    locked = false;
    valid = false;
    computedVP1 = {0, 0};
    computedVP2 = {0, 0};
    computedVP3 = {0, 0};
}

int IllToolPlugin::PerspectiveGrid::ActiveLineCount() const
{
    return (leftVP.active ? 1 : 0) + (rightVP.active ? 1 : 0) + (verticalVP.active ? 1 : 0);
}

bool IllToolPlugin::PerspectiveGrid::ComputeFloorHomography(double matrix[9]) const
{
    if (!valid) return false;

    // 2-point perspective floor homography using computed VPs and horizon.
    double cx = (computedVP1.h + computedVP2.h) * 0.5;
    double cy = horizonY;
    double span = std::abs(computedVP2.h - computedVP1.h);
    if (span < 1.0) span = 1.0;

    double halfSpan = span * 0.25;
    double drop = halfSpan * 0.8;

    double p0x = cx - halfSpan, p0y = cy;
    double p1x = cx + halfSpan, p1y = cy;
    double p2x = cx + halfSpan * 0.6, p2y = cy + drop;
    double p3x = cx - halfSpan * 0.6, p3y = cy + drop;

    double dx1 = p1x - p2x, dy1 = p1y - p2y;
    double dx2 = p3x - p2x, dy2 = p3y - p2y;
    double dx3 = p0x - p1x + p2x - p3x;
    double dy3 = p0y - p1y + p2y - p3y;

    double denom = dx1 * dy2 - dx2 * dy1;
    if (std::abs(denom) < 1e-12) return false;

    double g = (dx3 * dy2 - dx2 * dy3) / denom;
    double h = (dx1 * dy3 - dx3 * dy1) / denom;

    matrix[0] = p1x - p0x + g * p1x;
    matrix[1] = p3x - p0x + h * p3x;
    matrix[2] = p0x;
    matrix[3] = p1y - p0y + g * p1y;
    matrix[4] = p3y - p0y + h * p3y;
    matrix[5] = p0y;
    matrix[6] = g;
    matrix[7] = h;
    matrix[8] = 1.0;

    return true;
}

AIRealPoint IllToolPlugin::PerspectiveGrid::ProjectToPlane(AIRealPoint artPt, int plane) const
{
    if (!valid) return artPt;

    double matrix[9];
    if (!ComputeFloorHomography(matrix)) return artPt;

    double u = artPt.h;
    double v = artPt.v;

    if (plane == 1) {
        double dirX = computedVP1.h - (computedVP1.h + computedVP2.h) * 0.5;
        double dirY = computedVP1.v - horizonY;
        double len = std::sqrt(dirX * dirX + dirY * dirY);
        if (len > 1e-6) { dirX /= len; dirY /= len; }
        double origV = v;
        v = origV + dirY * (origV - horizonY);
    } else if (plane == 2) {
        double dirX = computedVP2.h - (computedVP1.h + computedVP2.h) * 0.5;
        double dirY = computedVP2.v - horizonY;
        double len = std::sqrt(dirX * dirX + dirY * dirY);
        if (len > 1e-6) { dirX /= len; dirY /= len; }
        double origV = v;
        v = origV + dirY * (origV - horizonY);
    }

    double w = matrix[6] * u + matrix[7] * v + matrix[8];
    if (std::abs(w) < 1e-12) return artPt;

    AIRealPoint result;
    result.h = (AIReal)((matrix[0] * u + matrix[1] * v + matrix[2]) / w);
    result.v = (AIReal)((matrix[3] * u + matrix[4] * v + matrix[5]) / w);
    return result;
}

AIRealPoint IllToolPlugin::PerspectiveGrid::MirrorInPerspective(AIRealPoint artPt, bool axisVertical) const
{
    if (!valid) return artPt;

    if (axisVertical) {
        double cx = (computedVP1.h + computedVP2.h) * 0.5;
        AIRealPoint mirrored;
        mirrored.h = (AIReal)(2.0 * cx - artPt.h);
        mirrored.v = artPt.v;
        return mirrored;
    } else {
        AIRealPoint mirrored;
        mirrored.h = artPt.h;
        mirrored.v = (AIReal)(2.0 * horizonY - artPt.v);
        return mirrored;
    }
}

//========================================================================================
//  IllToolPlugin perspective methods
//========================================================================================

void IllToolPlugin::SyncPerspectiveFromBridge()
{
    // Read continuous perspective line state from the bridge (thread-safe getters).
    // This runs every timer tick (~10Hz) so the annotator always has fresh data.

    bool anyChanged = false;

    for (int i = 0; i < 3; i++) {
        BridgePerspectiveLine bl = BridgeGetPerspectiveLine(i);
        PerspectiveLine* target = nullptr;
        switch (i) {
            case 0: target = &fPerspectiveGrid.leftVP; break;
            case 1: target = &fPerspectiveGrid.rightVP; break;
            case 2: target = &fPerspectiveGrid.verticalVP; break;
        }
        if (!target) continue;

        bool changed = (target->active != bl.active) ||
                       (bl.active && (target->handle1.h != (AIReal)bl.h1x ||
                                      target->handle1.v != (AIReal)bl.h1y ||
                                      target->handle2.h != (AIReal)bl.h2x ||
                                      target->handle2.v != (AIReal)bl.h2y));
        if (changed) {
            target->active = bl.active;
            if (bl.active) {
                target->handle1.h = (AIReal)bl.h1x;
                target->handle1.v = (AIReal)bl.h1y;
                target->handle2.h = (AIReal)bl.h2x;
                target->handle2.v = (AIReal)bl.h2y;
            }
            anyChanged = true;
        }
    }

    double bridgeHorizon = BridgeGetHorizonY();
    if (fPerspectiveGrid.horizonY != bridgeHorizon) {
        fPerspectiveGrid.horizonY = bridgeHorizon;
        anyChanged = true;
    }

    bool bridgeLocked = BridgeGetPerspectiveLocked();
    if (fPerspectiveGrid.locked != bridgeLocked) {
        fPerspectiveGrid.locked = bridgeLocked;
        anyChanged = true;
    }

    if (anyChanged) {
        fPerspectiveGrid.Recompute();
        InvalidateFullView();
    }
}

void IllToolPlugin::ClearPerspectiveGrid()
{
    fPerspectiveGrid.Clear();
    // Also clear bridge state
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    fprintf(stderr, "[IllTool] Perspective grid cleared\n");
    InvalidateFullView();
}

//========================================================================================
//  Perspective grid annotator overlay
//========================================================================================

/** Helper: draw a small square handle marker at a view point. */
static void DrawHandleSquare(AIAnnotatorDrawer* drawer, AIPoint center, int halfSize,
                              const AIRGBColor& color)
{
    sAIAnnotatorDrawer->SetColor(drawer, color);
    AIRect r;
    r.left   = center.h - halfSize;
    r.top    = center.v - halfSize;
    r.right  = center.h + halfSize;
    r.bottom = center.v + halfSize;
    sAIAnnotatorDrawer->DrawRect(drawer, r, true);
}

void IllToolPlugin::DrawPerspectiveOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;

    // Draw even if not fully valid — show individual lines as they're placed
    bool hasAnyLine = fPerspectiveGrid.leftVP.active ||
                      fPerspectiveGrid.rightVP.active ||
                      fPerspectiveGrid.verticalVP.active;
    if (!hasAnyLine && !fPerspectiveGrid.valid) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Colors
    AIRGBColor lineColor;       // solid line between handles: white
    lineColor.red = lineColor.green = lineColor.blue = (ai::uint16)(0.9 * 65535);

    AIRGBColor extensionColor;  // dotted extension: dim cyan
    extensionColor.red   = 0;
    extensionColor.green = (ai::uint16)(0.6 * 65535);
    extensionColor.blue  = (ai::uint16)(0.8 * 65535);

    AIRGBColor vpColor;         // computed VP marker: bright yellow
    vpColor.red   = (ai::uint16)(1.0 * 65535);
    vpColor.green = (ai::uint16)(0.9 * 65535);
    vpColor.blue  = 0;

    AIRGBColor handleColor;     // handle squares: bright green
    handleColor.red   = 0;
    handleColor.green = (ai::uint16)(0.9 * 65535);
    handleColor.blue  = (ai::uint16)(0.3 * 65535);

    AIRGBColor horizonColor;    // horizon line: orange
    horizonColor.red   = (ai::uint16)(1.0 * 65535);
    horizonColor.green = (ai::uint16)(0.5 * 65535);
    horizonColor.blue  = 0;

    AIRGBColor gridColor;       // grid lines: cyan
    gridColor.red   = 0;
    gridColor.green = (ai::uint16)(0.7 * 65535);
    gridColor.blue  = (ai::uint16)(0.9 * 65535);

    // --- Draw horizon line ---
    {
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.6);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
        AIFloat dashArray[] = {6.0f, 4.0f};
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
        sAIAnnotatorDrawer->SetColor(drawer, horizonColor);

        // Extend across a wide range
        AIRealPoint artLeft  = {(AIReal)-5000.0, (AIReal)fPerspectiveGrid.horizonY};
        AIRealPoint artRight = {(AIReal)5000.0,  (AIReal)fPerspectiveGrid.horizonY};
        AIPoint vLeft, vRight;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artLeft, &vLeft) == kNoErr &&
            sAIDocumentView->ArtworkPointToViewPoint(NULL, &artRight, &vRight) == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, vLeft, vRight);
        }
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
    }

    // --- Draw each perspective line (solid between handles, dotted extensions) ---
    auto drawPerspectiveLine = [&](const PerspectiveLine& line) {
        if (!line.active) return;

        AIPoint vh1, vh2;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &line.handle1, &vh1) != kNoErr) return;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &line.handle2, &vh2) != kNoErr) return;

        // Solid line between handles
        sAIAnnotatorDrawer->SetColor(drawer, lineColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.8);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
        sAIAnnotatorDrawer->DrawLine(drawer, vh1, vh2);

        // Handle squares
        DrawHandleSquare(drawer, vh1, 4, handleColor);
        DrawHandleSquare(drawer, vh2, 4, handleColor);

        // Dotted extension lines (extend far in both directions)
        double dx = line.handle2.h - line.handle1.h;
        double dy = line.handle2.v - line.handle1.v;
        double len = std::sqrt(dx * dx + dy * dy);
        if (len < 1e-6) return;

        double nx = dx / len;
        double ny = dy / len;
        double extendDist = 5000.0;

        AIRealPoint extA = {(AIReal)(line.handle1.h - nx * extendDist),
                            (AIReal)(line.handle1.v - ny * extendDist)};
        AIRealPoint extB = {(AIReal)(line.handle2.h + nx * extendDist),
                            (AIReal)(line.handle2.v + ny * extendDist)};

        sAIAnnotatorDrawer->SetColor(drawer, extensionColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
        AIFloat dashArray[] = {4.0f, 6.0f};
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);

        AIPoint vExtA, vExtB;
        // Extension from handle1 backward
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extA, &vExtA) == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
        }
        // Extension from handle2 forward
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extB, &vExtB) == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, vh2, vExtB);
        }
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
    };

    drawPerspectiveLine(fPerspectiveGrid.leftVP);
    drawPerspectiveLine(fPerspectiveGrid.rightVP);
    drawPerspectiveLine(fPerspectiveGrid.verticalVP);

    // --- Draw computed VP markers (crosses with circles) ---
    auto drawVPMarker = [&](AIRealPoint artVP) {
        AIPoint viewPt;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artVP, &viewPt) != kNoErr) return;

        int crossSize = 8;
        sAIAnnotatorDrawer->SetColor(drawer, vpColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.7);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);

        AIPoint p1 = {viewPt.h - crossSize, viewPt.v};
        AIPoint p2 = {viewPt.h + crossSize, viewPt.v};
        sAIAnnotatorDrawer->DrawLine(drawer, p1, p2);

        p1 = {viewPt.h, viewPt.v - crossSize};
        p2 = {viewPt.h, viewPt.v + crossSize};
        sAIAnnotatorDrawer->DrawLine(drawer, p1, p2);

        AIRect vpRect;
        vpRect.left   = viewPt.h - crossSize;
        vpRect.top    = viewPt.v - crossSize;
        vpRect.right  = viewPt.h + crossSize;
        vpRect.bottom = viewPt.v + crossSize;
        sAIAnnotatorDrawer->DrawEllipse(drawer, vpRect, false);
    };

    if (fPerspectiveGrid.valid) {
        drawVPMarker(fPerspectiveGrid.computedVP1);
        drawVPMarker(fPerspectiveGrid.computedVP2);
    }
    if (fPerspectiveGrid.verticalVP.active && fPerspectiveGrid.valid) {
        drawVPMarker(fPerspectiveGrid.computedVP3);
    }

    // --- Draw grid lines (only when locked) ---
    if (fPerspectiveGrid.locked && fPerspectiveGrid.valid) {
        sAIAnnotatorDrawer->SetColor(drawer, gridColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.3);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 0.5);

        int density = fPerspectiveGrid.gridDensity;

        double cx = (fPerspectiveGrid.computedVP1.h + fPerspectiveGrid.computedVP2.h) * 0.5;
        double span = std::abs(fPerspectiveGrid.computedVP2.h - fPerspectiveGrid.computedVP1.h);
        if (span < 10.0) span = 10.0;
        double gridExtent = span * 0.5;
        double gridBottom = fPerspectiveGrid.horizonY + gridExtent;

        // Lines from VP1 fanning out
        for (int i = 0; i <= density; i++) {
            double t = (double)i / (double)density;
            double targetX = cx - gridExtent * 0.3 + t * gridExtent * 1.3;
            AIRealPoint artFrom = fPerspectiveGrid.computedVP1;
            AIRealPoint artTo   = {(AIReal)targetX, (AIReal)gridBottom};
            AIPoint vFrom, vTo;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artFrom, &vFrom) == kNoErr &&
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTo, &vTo) == kNoErr) {
                sAIAnnotatorDrawer->DrawLine(drawer, vFrom, vTo);
            }
        }

        // Lines from VP2 fanning out
        for (int i = 0; i <= density; i++) {
            double t = (double)i / (double)density;
            double targetX = cx + gridExtent * 0.3 - t * gridExtent * 1.3;
            AIRealPoint artFrom = fPerspectiveGrid.computedVP2;
            AIRealPoint artTo   = {(AIReal)targetX, (AIReal)gridBottom};
            AIPoint vFrom, vTo;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artFrom, &vFrom) == kNoErr &&
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTo, &vTo) == kNoErr) {
                sAIAnnotatorDrawer->DrawLine(drawer, vFrom, vTo);
            }
        }

        // Horizontal cross-lines (foreshortened)
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.2);
        for (int i = 1; i <= density; i++) {
            double t = (double)i / (double)density;
            double y = fPerspectiveGrid.horizonY + t * (gridBottom - fPerspectiveGrid.horizonY);
            double foreshorten = 1.0 - t * 0.3;
            double leftX  = cx - gridExtent * foreshorten;
            double rightX = cx + gridExtent * foreshorten;
            AIRealPoint artL = {(AIReal)leftX, (AIReal)y};
            AIRealPoint artR = {(AIReal)rightX, (AIReal)y};
            AIPoint vL, vR;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artL, &vL) == kNoErr &&
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artR, &vR) == kNoErr) {
                sAIAnnotatorDrawer->DrawLine(drawer, vL, vR);
            }
        }

        // 3-point vertical converging lines
        if (fPerspectiveGrid.verticalVP.active) {
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            for (int i = 0; i <= density; i++) {
                double t = (double)i / (double)density;
                double targetX = cx - gridExtent * 0.5 + t * gridExtent;
                AIRealPoint artFrom = fPerspectiveGrid.computedVP3;
                AIRealPoint artTo   = {(AIReal)targetX, (AIReal)gridBottom};
                AIPoint vFrom, vTo;
                if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artFrom, &vFrom) == kNoErr &&
                    sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTo, &vTo) == kNoErr) {
                    sAIAnnotatorDrawer->DrawLine(drawer, vFrom, vTo);
                }
            }
        }
    }

    // Restore defaults
    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
}
