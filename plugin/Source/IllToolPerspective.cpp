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

//========================================================================================
//  Project a set of points through the perspective grid
//  Used by AverageSelection when snap-to-perspective is on
//========================================================================================

std::vector<AIRealPoint> IllToolPlugin::ProjectPointsThroughPerspective(
    const std::vector<AIRealPoint>& points, int plane)
{
    if (!fPerspectiveGrid.valid || points.empty()) return points;

    std::vector<AIRealPoint> projected(points.size());
    for (int i = 0; i < (int)points.size(); i++) {
        projected[i] = fPerspectiveGrid.ProjectToPlane(points[i], plane);
    }
    return projected;
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

    bool bridgeVisible = BridgeGetPerspectiveVisible();
    if (fPerspectiveGrid.visible != bridgeVisible) {
        fPerspectiveGrid.visible = bridgeVisible;
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

void IllToolPlugin::SavePerspectiveToDocument()
{
    fPerspectiveGrid.SaveToDocument();
}

void IllToolPlugin::LoadPerspectiveFromDocument()
{
    fPerspectiveGrid.LoadFromDocument();
}

//========================================================================================
//  Perspective grid annotator overlay
//========================================================================================

/** Helper: draw a circle handle marker at a view point. */
static void DrawHandleCircle(AIAnnotatorDrawer* drawer, AIPoint center, int radius,
                              const AIRGBColor& color)
{
    sAIAnnotatorDrawer->SetColor(drawer, color);
    AIRect r;
    r.left   = center.h - radius;
    r.top    = center.v - radius;
    r.right  = center.h + radius;
    r.bottom = center.v + radius;
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, true);
}

/** Helper: create a dimmed version of a color (for extension lines). */
static AIRGBColor DimColor(const AIRGBColor& c, double factor)
{
    AIRGBColor dim;
    dim.red   = (ai::uint16)(c.red   * factor);
    dim.green = (ai::uint16)(c.green * factor);
    dim.blue  = (ai::uint16)(c.blue  * factor);
    return dim;
}

//========================================================================================
//  Document persistence — AIDictionarySuite on a hidden marker art object
//
//  Strategy: create a hidden kGroupArt with a marker dictionary entry.
//  On save, find or create the marker group, write all grid state into its dict.
//  On load, scan top-level art for the marker, read back.
//========================================================================================

static const char* kPerspGridMarker     = "IllToolPerspGrid";
static const char* kPerspKeyHorizonY    = "IllToolPerspGrid_horizonY";
static const char* kPerspKeyLocked      = "IllToolPerspGrid_locked";
static const char* kPerspKeyVisible     = "IllToolPerspGrid_visible";
static const char* kPerspKeyDensity     = "IllToolPerspGrid_density";
// Per-line keys: _L0h1x, _L0h1y, _L0h2x, _L0h2y, _L0active (L0=left, L1=right, L2=vert)
static const char* kPerspLinePrefix[3]  = {"_L0", "_L1", "_L2"};

/** Find the hidden marker group in the document. Returns nullptr if not found. */
static AIArtHandle FindPerspMarkerArt()
{
    if (!sAIArt || !sAIDictionary || !sAILayer) return nullptr;

    // Iterate all layers, scan top-level children for the marker dictionary entry
    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    for (ai::int32 li = 0; li < layerCount; li++) {
        AILayerHandle layer = nullptr;
        if (sAILayer->GetNthLayer(li, &layer) != kNoErr) continue;
        AIArtHandle layerGroup = nullptr;
        if (sAIArt->GetFirstArtOfLayer(layer, &layerGroup) != kNoErr || !layerGroup) continue;

        AIArtHandle child = nullptr;
        sAIArt->GetArtFirstChild(layerGroup, &child);
        while (child) {
            AIBoolean hasDict = sAIArt->HasDictionary(child);
            if (hasDict) {
                AIDictionaryRef dict = nullptr;
                if (sAIArt->GetDictionary(child, &dict) == kNoErr && dict) {
                    AIDictKey key = sAIDictionary->Key(kPerspGridMarker);
                    AIBoolean isMarker = false;
                    ASErr gErr = sAIDictionary->GetBooleanEntry(dict, key, &isMarker);
                    sAIDictionary->Release(dict);
                    if (gErr == kNoErr && isMarker) {
                        return child;
                    }
                }
            }
            AIArtHandle next = nullptr;
            sAIArt->GetArtSibling(child, &next);
            child = next;
        }
    }
    return nullptr;
}

/** Create a hidden marker group in the first layer. Returns the art handle or nullptr. */
static AIArtHandle CreatePerspMarkerArt()
{
    if (!sAIArt || !sAIDictionary || !sAILayer) return nullptr;

    // Get the first layer
    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    if (layerCount == 0) return nullptr;

    AILayerHandle layer = nullptr;
    sAILayer->GetNthLayer(0, &layer);
    if (!layer) return nullptr;

    AIArtHandle layerGroup = nullptr;
    if (sAIArt->GetFirstArtOfLayer(layer, &layerGroup) != kNoErr || !layerGroup) return nullptr;

    // Create a group inside the layer
    AIArtHandle markerArt = nullptr;
    ASErr err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &markerArt);
    if (err != kNoErr || !markerArt) {
        fprintf(stderr, "[IllTool Persp] CreatePerspMarkerArt: NewArt failed %d\n", (int)err);
        return nullptr;
    }

    // Hide it and lock it so the user can't accidentally interact with it
    sAIArt->SetArtUserAttr(markerArt, kArtHidden | kArtLocked, kArtHidden | kArtLocked);

    // Set the marker flag
    AIDictionaryRef dict = nullptr;
    err = sAIArt->GetDictionary(markerArt, &dict);
    if (err == kNoErr && dict) {
        AIDictKey key = sAIDictionary->Key(kPerspGridMarker);
        sAIDictionary->SetBooleanEntry(dict, key, true);
        sAIDictionary->Release(dict);
    }

    fprintf(stderr, "[IllTool Persp] Created marker art %p\n", (void*)markerArt);
    return markerArt;
}

void IllToolPlugin::PerspectiveGrid::SaveToDocument()
{
    if (!sAIDictionary || !sAIArt) return;

    fprintf(stderr, "[IllTool] PerspectiveGrid::SaveToDocument — grid valid=%d lines=%d\n",
            valid, ActiveLineCount());

    // Find or create the hidden marker art
    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) marker = CreatePerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool Persp] SaveToDocument: could not create marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) {
        fprintf(stderr, "[IllTool Persp] SaveToDocument: GetDictionary failed %d\n", (int)err);
        return;
    }

    // Horizon, locked, visible, density
    sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(kPerspKeyHorizonY), (AIReal)horizonY);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyLocked), locked);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyVisible), visible);
    sAIDictionary->SetIntegerEntry(dict, sAIDictionary->Key(kPerspKeyDensity), (ai::int32)gridDensity);

    // Each line: active, h1x, h1y, h2x, h2y
    const PerspectiveLine* lines[3] = {&leftVP, &rightVP, &verticalVP};
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        const char* prefix = kPerspLinePrefix[i];
        char keyBuf[64];

        snprintf(keyBuf, sizeof(keyBuf), "%s_active", prefix);
        sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(keyBuf), line.active);

        snprintf(keyBuf, sizeof(keyBuf), "%s_h1x", prefix);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(keyBuf), line.handle1.h);

        snprintf(keyBuf, sizeof(keyBuf), "%s_h1y", prefix);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(keyBuf), line.handle1.v);

        snprintf(keyBuf, sizeof(keyBuf), "%s_h2x", prefix);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(keyBuf), line.handle2.h);

        snprintf(keyBuf, sizeof(keyBuf), "%s_h2y", prefix);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(keyBuf), line.handle2.v);
    }

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool Persp] SaveToDocument: wrote %d lines, horizon=%.0f, locked=%d, visible=%d, density=%d\n",
            ActiveLineCount(), horizonY, locked, visible, gridDensity);
}

void IllToolPlugin::PerspectiveGrid::LoadFromDocument()
{
    fprintf(stderr, "[IllTool] PerspectiveGrid::LoadFromDocument — checking for saved grid\n");

    if (!sAIDictionary || !sAIArt) return;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool Persp] LoadFromDocument: no marker art found\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) {
        fprintf(stderr, "[IllTool Persp] LoadFromDocument: GetDictionary failed %d\n", (int)err);
        return;
    }

    // Horizon, locked, visible, density
    AIReal hY = 400;
    sAIDictionary->GetRealEntry(dict, sAIDictionary->Key(kPerspKeyHorizonY), &hY);
    horizonY = (double)hY;

    AIBoolean bLocked = false, bVisible = true;
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyLocked), &bLocked);
    locked = bLocked;

    if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyVisible), &bVisible) == kNoErr)
        visible = bVisible;
    else
        visible = true;

    ai::int32 dens = 5;
    sAIDictionary->GetIntegerEntry(dict, sAIDictionary->Key(kPerspKeyDensity), &dens);
    gridDensity = (int)dens;

    // Each line
    PerspectiveLine* lines[3] = {&leftVP, &rightVP, &verticalVP};
    for (int i = 0; i < 3; i++) {
        PerspectiveLine& line = *lines[i];
        const char* prefix = kPerspLinePrefix[i];
        char keyBuf[64];

        AIBoolean bActive = false;
        snprintf(keyBuf, sizeof(keyBuf), "%s_active", prefix);
        sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(keyBuf), &bActive);
        line.active = bActive;

        if (line.active) {
            AIReal val = 0;
            snprintf(keyBuf, sizeof(keyBuf), "%s_h1x", prefix);
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key(keyBuf), &val);
            line.handle1.h = val;

            snprintf(keyBuf, sizeof(keyBuf), "%s_h1y", prefix);
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key(keyBuf), &val);
            line.handle1.v = val;

            snprintf(keyBuf, sizeof(keyBuf), "%s_h2x", prefix);
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key(keyBuf), &val);
            line.handle2.h = val;

            snprintf(keyBuf, sizeof(keyBuf), "%s_h2y", prefix);
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key(keyBuf), &val);
            line.handle2.v = val;
        }
    }

    sAIDictionary->Release(dict);

    // Recompute VPs from loaded data
    Recompute();

    // Sync loaded state back to bridge so panel reflects it
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        if (line.active) {
            BridgeSetPerspectiveLine(i, line.handle1.h, line.handle1.v,
                                        line.handle2.h, line.handle2.v);
        }
    }
    BridgeSetHorizonY(horizonY);
    BridgeSetPerspectiveLocked(locked);
    BridgeSetPerspectiveVisible(visible);

    fprintf(stderr, "[IllTool Persp] LoadFromDocument: loaded %d lines, horizon=%.0f, locked=%d, visible=%d, density=%d\n",
            ActiveLineCount(), horizonY, locked, visible, gridDensity);
}

void IllToolPlugin::DrawPerspectiveOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;

    // Show/hide toggle — grid data preserved but overlay not drawn
    if (!fPerspectiveGrid.visible) return;

    // Draw even if not fully valid — show individual lines as they're placed
    bool hasAnyLine = fPerspectiveGrid.leftVP.active ||
                      fPerspectiveGrid.rightVP.active ||
                      fPerspectiveGrid.verticalVP.active;
    if (!hasAnyLine && !fPerspectiveGrid.valid) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Per-line colors matching the panel legend
    AIRGBColor vp1Color;        // VP1 (left): red
    vp1Color.red   = (ai::uint16)(0.90 * 65535);
    vp1Color.green = (ai::uint16)(0.30 * 65535);
    vp1Color.blue  = (ai::uint16)(0.30 * 65535);

    AIRGBColor vp2Color;        // VP2 (right): green
    vp2Color.red   = (ai::uint16)(0.30 * 65535);
    vp2Color.green = (ai::uint16)(0.80 * 65535);
    vp2Color.blue  = (ai::uint16)(0.30 * 65535);

    AIRGBColor vp3Color;        // VP3 (vertical): blue
    vp3Color.red   = (ai::uint16)(0.35 * 65535);
    vp3Color.green = (ai::uint16)(0.55 * 65535);
    vp3Color.blue  = (ai::uint16)(0.95 * 65535);

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
    auto drawPerspectiveLine = [&](const PerspectiveLine& line, const AIRGBColor& color) {
        if (!line.active) return;

        AIPoint vh1, vh2;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &line.handle1, &vh1) != kNoErr) return;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &line.handle2, &vh2) != kNoErr) return;

        // Solid line between handles — per-line color
        sAIAnnotatorDrawer->SetColor(drawer, color);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.8);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
        sAIAnnotatorDrawer->DrawLine(drawer, vh1, vh2);

        // Circle handles — same color as line; hidden when grid is locked
        if (!fPerspectiveGrid.locked) {
            DrawHandleCircle(drawer, vh1, 5, color);
            DrawHandleCircle(drawer, vh2, 5, color);
        }

        // Dotted extension lines (extend far in both directions) — dimmed version of line color
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

        AIRGBColor extColor = DimColor(color, 0.6);
        sAIAnnotatorDrawer->SetColor(drawer, extColor);
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

    drawPerspectiveLine(fPerspectiveGrid.leftVP, vp1Color);
    drawPerspectiveLine(fPerspectiveGrid.rightVP, vp2Color);
    drawPerspectiveLine(fPerspectiveGrid.verticalVP, vp3Color);

    // --- Draw computed VP markers (crosses with circles, per-line color) ---
    auto drawVPMarker = [&](AIRealPoint artVP, const AIRGBColor& color) {
        AIPoint viewPt;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artVP, &viewPt) != kNoErr) return;

        int crossSize = 8;
        sAIAnnotatorDrawer->SetColor(drawer, color);
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
        drawVPMarker(fPerspectiveGrid.computedVP1, vp1Color);
        drawVPMarker(fPerspectiveGrid.computedVP2, vp2Color);
    }
    if (fPerspectiveGrid.verticalVP.active && fPerspectiveGrid.valid) {
        drawVPMarker(fPerspectiveGrid.computedVP3, vp3Color);
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

//========================================================================================
//  Homography math helpers (3x3 matrix operations)
//========================================================================================

/** Invert a 3x3 matrix. Returns false if singular. */
static bool InvertMatrix3x3(const double M[9], double Minv[9])
{
    double det = M[0] * (M[4] * M[8] - M[5] * M[7])
               - M[1] * (M[3] * M[8] - M[5] * M[6])
               + M[2] * (M[3] * M[7] - M[4] * M[6]);
    if (std::abs(det) < 1e-15) return false;

    double invDet = 1.0 / det;
    Minv[0] =  (M[4] * M[8] - M[5] * M[7]) * invDet;
    Minv[1] = -(M[1] * M[8] - M[2] * M[7]) * invDet;
    Minv[2] =  (M[1] * M[5] - M[2] * M[4]) * invDet;
    Minv[3] = -(M[3] * M[8] - M[5] * M[6]) * invDet;
    Minv[4] =  (M[0] * M[8] - M[2] * M[6]) * invDet;
    Minv[5] = -(M[0] * M[5] - M[2] * M[3]) * invDet;
    Minv[6] =  (M[3] * M[7] - M[4] * M[6]) * invDet;
    Minv[7] = -(M[0] * M[7] - M[1] * M[6]) * invDet;
    Minv[8] =  (M[0] * M[4] - M[1] * M[3]) * invDet;
    return true;
}

/** Apply a 3x3 homography to a 2D point. Returns the projected result. */
static AIRealPoint ApplyHomography(const double H[9], AIRealPoint pt)
{
    double x = pt.h, y = pt.v;
    double w = H[6] * x + H[7] * y + H[8];
    if (std::abs(w) < 1e-15) return pt;
    AIRealPoint result;
    result.h = (AIReal)((H[0] * x + H[1] * y + H[2]) / w);
    result.v = (AIReal)((H[3] * x + H[4] * y + H[5]) / w);
    return result;
}

/** Build a wall-plane homography (left wall or right wall).
    Rotates the floor homography 90 degrees around the appropriate VP axis. */
static bool ComputeWallHomography(const IllToolPlugin::PerspectiveGrid& grid, int plane, double matrix[9])
{
    if (!grid.ComputeFloorHomography(matrix)) return false;

    // For wall planes, we modify the floor homography:
    // Left wall (plane 1): use VP1 as the horizontal vanishing, vertical stays vertical
    // Right wall (plane 2): use VP2 as the horizontal vanishing, vertical stays vertical
    // This is achieved by swapping the Y-axis mapping to go vertical instead of toward the floor
    double cx = (grid.computedVP1.h + grid.computedVP2.h) * 0.5;
    double span = std::abs(grid.computedVP2.h - grid.computedVP1.h);
    if (span < 1.0) span = 1.0;
    double halfSpan = span * 0.25;

    AIRealPoint vp = (plane == 1) ? grid.computedVP1 : grid.computedVP2;
    double vpDirX = vp.h - cx;
    double vpDirY = vp.v - grid.horizonY;
    double vpDist = std::sqrt(vpDirX * vpDirX + vpDirY * vpDirY);
    if (vpDist < 1.0) vpDist = 1.0;

    // Wall quad: two points on horizon, two points below (forming a vertical wall face)
    double wallWidth = halfSpan * 0.8;
    double wallHeight = halfSpan * 1.0;

    // Foreshorten the far edge toward the VP
    double farScale = 0.7;  // foreshortening ratio

    double p0x, p0y, p1x, p1y, p2x, p2y, p3x, p3y;
    if (plane == 1) {
        // Left wall: near edge on left, far edge converges toward VP1 (left)
        p0x = cx;                   p0y = grid.horizonY;             // top-near
        p1x = cx - wallWidth;       p1y = grid.horizonY;             // top-far (toward VP1)
        p2x = cx - wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale; // bottom-far
        p3x = cx;                   p3y = grid.horizonY + wallHeight; // bottom-near
    } else {
        // Right wall: near edge on right, far edge converges toward VP2 (right)
        p0x = cx;                   p0y = grid.horizonY;
        p1x = cx + wallWidth;       p1y = grid.horizonY;
        p2x = cx + wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale;
        p3x = cx;                   p3y = grid.horizonY + wallHeight;
    }

    // Build homography from unit square [0,1]x[0,1] -> quad
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

/** Get selected path art handles using isolation-aware matching. Caller must dispose *matches. */
static bool GetSelectedPaths(AIArtHandle** &matches, ai::int32 &numMatches)
{
    AIMatchingArtSpec spec;
    spec.type = kPathArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;
    ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0) {
        matches = nullptr;
        numMatches = 0;
        return false;
    }
    return true;
}

//========================================================================================
//  Task #3: Mirror in Perspective
//========================================================================================

void IllToolPlugin::MirrorInPerspective(int axis, bool replace)
{
    if (!fPerspectiveGrid.valid) {
        fprintf(stderr, "[IllTool Persp] MirrorInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool Persp] MirrorInPerspective: missing suites\n");
        return;
    }

    // Build homography for the floor plane
    double H[9], Hinv[9];
    if (!fPerspectiveGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool Persp] MirrorInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool Persp] MirrorInPerspective: matrix inversion failed\n");
        return;
    }

    // Get selected paths
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool Persp] MirrorInPerspective: no selected paths\n");
        return;
    }

    bool axisVertical = (axis == 0);  // 0 = vertical axis (mirror left/right), 1 = horizontal

    fUndoStack.PushFrame();
    int mirroredCount = 0;

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        // Skip locked/hidden
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        // Read segments
        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        // Transform each segment through H -> mirror -> Hinv
        std::vector<AIPathSegment> mirroredSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& mir = mirroredSegs[s];

            // Project anchor to perspective space
            AIRealPoint pAnchor = ApplyHomography(Hinv, orig.p);
            // Mirror in perspective space
            if (axisVertical) {
                pAnchor.h = -pAnchor.h;  // reflect across vertical axis (negate X)
            } else {
                pAnchor.v = -pAnchor.v;  // reflect across horizontal axis (negate Y)
            }
            // Project back to artwork space
            mir.p = ApplyHomography(H, pAnchor);

            // Transform in-handle (relative direction from anchor)
            AIRealPoint inPt = {orig.in.h, orig.in.v};
            AIRealPoint inPersp = ApplyHomography(Hinv, inPt);
            if (axisVertical) inPersp.h = -inPersp.h;
            else              inPersp.v = -inPersp.v;
            AIRealPoint inBack = ApplyHomography(H, inPersp);
            mir.in = inBack;

            // Transform out-handle
            AIRealPoint outPt = {orig.out.h, orig.out.v};
            AIRealPoint outPersp = ApplyHomography(Hinv, outPt);
            if (axisVertical) outPersp.h = -outPersp.h;
            else              outPersp.v = -outPersp.v;
            AIRealPoint outBack = ApplyHomography(H, outPersp);
            mir.out = outBack;

            mir.corner = orig.corner;
        }

        // When mirroring, reverse segment order so winding stays consistent
        std::vector<AIPathSegment> reversed(segCount);
        for (int s = 0; s < segCount; s++) {
            int ri = segCount - 1 - s;
            reversed[s].p   = mirroredSegs[ri].p;
            // Swap in/out handles when reversing direction
            reversed[s].in  = mirroredSegs[ri].out;
            reversed[s].out = mirroredSegs[ri].in;
            reversed[s].corner = mirroredSegs[ri].corner;
        }

        if (replace) {
            // Replace original with mirrored version
            fUndoStack.SnapshotPath(art);
            sAIPath->SetPathSegments(art, 0, segCount, reversed.data());
        } else {
            // Create a duplicate with the mirrored segments
            AIArtHandle newArt = nullptr;
            ASErr dupErr = sAIArt->DuplicateArt(art, kPlaceAbove, art, &newArt);
            if (dupErr == kNoErr && newArt) {
                sAIPath->SetPathSegments(newArt, 0, segCount, reversed.data());
                // Copy path style from original
                AIPathStyle style;
                AIBoolean hasAdvFill = false;
                if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr) {
                    sAIPathStyle->SetPathStyle(newArt, &style);
                }
                mirroredCount++;
            }
        }
    }

    // Clean up
    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool Persp] MirrorInPerspective: %s %d paths, axis=%s\n",
            replace ? "replaced" : "created", replace ? numMatches : mirroredCount,
            axisVertical ? "vertical" : "horizontal");

    InvalidateFullView();
}

//========================================================================================
//  Task #4: Duplicate in Perspective
//========================================================================================

void IllToolPlugin::DuplicateInPerspective(int count, int spacing)
{
    if (!fPerspectiveGrid.valid) {
        fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: missing suites\n");
        return;
    }
    if (count < 1) count = 1;
    if (count > 50) count = 50;

    // Build homography
    double H[9], Hinv[9];
    if (!fPerspectiveGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: matrix inversion failed\n");
        return;
    }

    // Get selected paths
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: no selected paths\n");
        return;
    }

    // Default direction: toward VP2 (right vanishing point) in perspective space.
    // The direction is encoded in the spacing parameter's high bits:
    // Low 2 bits = spacing mode (0=equal in perspective, 1=equal on screen)
    // Bits 2-3 = direction (0=toward VP1, 1=toward VP2, 2=into screen, 3=away from horizon)
    int spacingMode = spacing & 0x03;
    int direction   = (spacing >> 2) & 0x03;

    double dirX = 0, dirY = 0;
    double baseOffset = 0.15;  // proportion of perspective space per step

    switch (direction) {
        case 0:  dirX = -baseOffset; dirY = 0; break;           // toward left VP
        case 1:  dirX =  baseOffset; dirY = 0; break;           // toward right VP
        case 2:  dirX = 0;           dirY = -baseOffset; break;  // into screen (toward horizon)
        case 3:  dirX = 0;           dirY =  baseOffset; break;  // away from horizon
        default: dirX = baseOffset;  dirY = 0; break;
    }

    int totalCreated = 0;

    for (ai::int32 mi = 0; mi < numMatches; mi++) {
        AIArtHandle art = (*matches)[mi];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        // Get path style for copying
        AIPathStyle style;
        AIBoolean hasAdvFill = false;
        bool hasStyle = (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr);

        // Compute centroid of original in perspective space for depth scaling
        AIRealPoint centroid = {0, 0};
        for (int s = 0; s < segCount; s++) {
            centroid.h += segs[s].p.h;
            centroid.v += segs[s].p.v;
        }
        centroid.h /= segCount;
        centroid.v /= segCount;
        AIRealPoint centroidPersp = ApplyHomography(Hinv, centroid);

        for (int ci = 1; ci <= count; ci++) {
            double stepScale = (double)ci;

            // For "equal in perspective" (mode 0): constant offset in perspective space
            // For "equal on screen" (mode 1): increasing offset to compensate foreshortening
            double perspOffX, perspOffY;
            if (spacingMode == 0) {
                perspOffX = dirX * stepScale;
                perspOffY = dirY * stepScale;
            } else {
                // Equal on screen: scale offset by depth ratio to counteract foreshortening
                // Objects farther from viewer need larger perspective-space offsets
                double depthFactor = 1.0 + stepScale * 0.15;
                perspOffX = dirX * stepScale * depthFactor;
                perspOffY = dirY * stepScale * depthFactor;
            }

            // Compute foreshortening scale factor based on distance to VP
            // Objects moving toward the VP should scale down
            AIRealPoint newCentroidPersp = {
                (AIReal)(centroidPersp.h + perspOffX),
                (AIReal)(centroidPersp.v + perspOffY)
            };
            AIRealPoint newCentroidArt = ApplyHomography(H, newCentroidPersp);
            AIRealPoint origCentroidArt = ApplyHomography(H, centroidPersp);

            // Depth ratio: compare W components for foreshortening
            double wOrig = Hinv[6] * origCentroidArt.h + Hinv[7] * origCentroidArt.v + Hinv[8];
            double wNew  = Hinv[6] * newCentroidArt.h  + Hinv[7] * newCentroidArt.v  + Hinv[8];
            double scaleFactor = (std::abs(wOrig) > 1e-12 && std::abs(wNew) > 1e-12) ?
                                 wNew / wOrig : 1.0;
            // Clamp scale factor to reasonable range
            if (scaleFactor < 0.1) scaleFactor = 0.1;
            if (scaleFactor > 5.0) scaleFactor = 5.0;

            // Transform each segment
            std::vector<AIPathSegment> dupSegs(segCount);
            for (int s = 0; s < segCount; s++) {
                const AIPathSegment& orig = segs[s];
                AIPathSegment& dup = dupSegs[s];

                // Anchor: project to perspective space, offset, project back
                AIRealPoint pPersp = ApplyHomography(Hinv, orig.p);
                pPersp.h = (AIReal)(pPersp.h + perspOffX);
                pPersp.v = (AIReal)(pPersp.v + perspOffY);
                dup.p = ApplyHomography(H, pPersp);

                // In-handle: project, offset (keeping handle-anchor delta scaled)
                AIRealPoint inPersp = ApplyHomography(Hinv, orig.in);
                AIRealPoint anchorPersp = ApplyHomography(Hinv, orig.p);
                double inDx = inPersp.h - anchorPersp.h;
                double inDy = inPersp.v - anchorPersp.v;
                AIRealPoint inOffPersp = {
                    (AIReal)(anchorPersp.h + perspOffX + inDx * scaleFactor),
                    (AIReal)(anchorPersp.v + perspOffY + inDy * scaleFactor)
                };
                dup.in = ApplyHomography(H, inOffPersp);

                // Out-handle: same approach
                AIRealPoint outPersp = ApplyHomography(Hinv, orig.out);
                double outDx = outPersp.h - anchorPersp.h;
                double outDy = outPersp.v - anchorPersp.v;
                AIRealPoint outOffPersp = {
                    (AIReal)(anchorPersp.h + perspOffX + outDx * scaleFactor),
                    (AIReal)(anchorPersp.v + perspOffY + outDy * scaleFactor)
                };
                dup.out = ApplyHomography(H, outOffPersp);

                dup.corner = orig.corner;
            }

            // Create duplicate art
            AIArtHandle newArt = nullptr;
            ASErr dupErr = sAIArt->DuplicateArt(art, kPlaceAbove, art, &newArt);
            if (dupErr == kNoErr && newArt) {
                sAIPath->SetPathSegments(newArt, 0, segCount, dupSegs.data());
                if (hasStyle) {
                    sAIPathStyle->SetPathStyle(newArt, &style);
                }
                totalCreated++;
            }
        }
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool Persp] DuplicateInPerspective: created %d copies (count=%d, dir=%d, spacing=%d)\n",
            totalCreated, count, direction, spacingMode);

    InvalidateFullView();
}

//========================================================================================
//  Task #5: Paste in Perspective
//========================================================================================

void IllToolPlugin::PasteInPerspective(int plane, float scale)
{
    if (!fPerspectiveGrid.valid) {
        fprintf(stderr, "[IllTool Persp] PasteInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool Persp] PasteInPerspective: missing suites\n");
        return;
    }
    if (scale < 0.01) scale = 0.01;
    if (scale > 10.0) scale = 10.0;

    // Build plane-specific homography
    // plane: 0 = floor, 1 = left wall, 2 = right wall
    double H[9], Hinv[9];
    bool gotH = false;

    if (plane == 0) {
        gotH = fPerspectiveGrid.ComputeFloorHomography(H);
    } else {
        gotH = ComputeWallHomography(fPerspectiveGrid, plane, H);
    }

    if (!gotH) {
        fprintf(stderr, "[IllTool Persp] PasteInPerspective: homography failed for plane %d\n", plane);
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool Persp] PasteInPerspective: matrix inversion failed\n");
        return;
    }

    // Get selected paths as the "paste source" (user selects source, triggers paste)
    // This is the pattern: user copies art, pastes it, selects it, then triggers
    // "paste in perspective" which transforms the current selection onto the plane.
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool Persp] PasteInPerspective: no selected paths\n");
        return;
    }

    fUndoStack.PushFrame();
    int transformedCount = 0;

    // Compute the centroid of all selected art (for scaling around center)
    AIRealPoint globalCentroid = {0, 0};
    int totalPoints = 0;
    for (ai::int32 i = 0; i < numMatches; i++) {
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr((*matches)[i], kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount((*matches)[i], &segCount) != kNoErr) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments((*matches)[i], 0, segCount, segs.data()) != kNoErr) continue;

        for (int s = 0; s < segCount; s++) {
            globalCentroid.h += segs[s].p.h;
            globalCentroid.v += segs[s].p.v;
            totalPoints++;
        }
    }
    if (totalPoints > 0) {
        globalCentroid.h /= totalPoints;
        globalCentroid.v /= totalPoints;
    }

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        fUndoStack.SnapshotPath(art);

        // Transform each segment:
        // 1. Center around origin (subtract centroid)
        // 2. Apply user scale factor
        // 3. Project through homography onto the perspective plane
        std::vector<AIPathSegment> projSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& proj = projSegs[s];

            // Center, scale, then project through H to place on perspective plane
            AIRealPoint centered = {
                (AIReal)((orig.p.h - globalCentroid.h) * scale),
                (AIReal)((orig.p.v - globalCentroid.v) * scale)
            };
            // Map through homography: centered coordinates become perspective-space UV,
            // homography maps them to artwork space on the chosen plane
            // Offset to place at center of the plane (0.5, 0.5 in normalized coords)
            // We normalize the centered coords to a range that maps sensibly
            // through the homography
            double normRange = 200.0;  // art coords → normalized
            AIRealPoint uv = {
                (AIReal)(0.5 + centered.h / normRange),
                (AIReal)(0.5 + centered.v / normRange)
            };
            proj.p = ApplyHomography(H, uv);

            // In-handle
            AIRealPoint inCentered = {
                (AIReal)((orig.in.h - globalCentroid.h) * scale),
                (AIReal)((orig.in.v - globalCentroid.v) * scale)
            };
            AIRealPoint inUV = {
                (AIReal)(0.5 + inCentered.h / normRange),
                (AIReal)(0.5 + inCentered.v / normRange)
            };
            proj.in = ApplyHomography(H, inUV);

            // Out-handle
            AIRealPoint outCentered = {
                (AIReal)((orig.out.h - globalCentroid.h) * scale),
                (AIReal)((orig.out.v - globalCentroid.v) * scale)
            };
            AIRealPoint outUV = {
                (AIReal)(0.5 + outCentered.h / normRange),
                (AIReal)(0.5 + outCentered.v / normRange)
            };
            proj.out = ApplyHomography(H, outUV);

            proj.corner = orig.corner;
        }

        sAIPath->SetPathSegments(art, 0, segCount, projSegs.data());
        transformedCount++;
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool Persp] PasteInPerspective: transformed %d paths onto plane %d (scale=%.2f)\n",
            transformedCount, plane, scale);

    InvalidateFullView();
}

//========================================================================================
//  Perspective Tool interaction handlers
//========================================================================================

/** Helper: compute distance between two points. */
static double PerspDist(AIRealPoint a, AIRealPoint b) {
    double dx = a.h - b.h;
    double dy = a.v - b.v;
    return std::sqrt(dx * dx + dy * dy);
}

//========================================================================================
//  Place VP3 (vertical vanishing point) at center of viewport
//  Called from the "Add Vertical" panel button.
//========================================================================================

void IllToolPlugin::PlaceVerticalVP()
{
    if (fPerspectiveGrid.verticalVP.active) {
        fprintf(stderr, "[IllTool Persp] PlaceVerticalVP: VP3 already placed\n");
        return;
    }

    // Get viewport bounds to find center
    AIRealRect viewBounds = {0, 0, 0, 0};
    if (sAIDocumentView) {
        sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
    }
    double viewCenterX = (viewBounds.left + viewBounds.right) * 0.5;
    double horizY = fPerspectiveGrid.horizonY;

    // Fallback if bounds are zero
    if (std::abs(viewBounds.right - viewBounds.left) < 1.0) viewCenterX = 400.0;

    // VP3 placed above horizon at center X, with a short vertical line
    // handle1 above horizon, handle2 below — line tilted slightly from vertical
    double yAbove = horizY - 200.0;  // above the horizon
    double yBelow = horizY + 50.0;   // slightly below horizon

    fPerspectiveGrid.verticalVP.handle1 = { (AIReal)viewCenterX, (AIReal)yAbove };
    fPerspectiveGrid.verticalVP.handle2 = { (AIReal)(viewCenterX + 10.0), (AIReal)yBelow };
    fPerspectiveGrid.verticalVP.active = true;

    BridgeSetPerspectiveLine(2,
        fPerspectiveGrid.verticalVP.handle1.h, fPerspectiveGrid.verticalVP.handle1.v,
        fPerspectiveGrid.verticalVP.handle2.h, fPerspectiveGrid.verticalVP.handle2.v);

    BridgeSetPerspectiveVisible(true);

    fPerspectiveGrid.Recompute();
    InvalidateFullView();

    fprintf(stderr, "[IllTool Persp] PlaceVerticalVP: VP3 at center (%.0f, %.0f)-(%.0f, %.0f)\n",
            viewCenterX, yAbove, viewCenterX + 10.0, yBelow);
}

void IllToolPlugin::PerspectiveToolMouseDown(AIToolMessage* message)
{
    AIRealPoint click = message->cursor;
    fprintf(stderr, "[IllTool Persp Tool] MouseDown at (%.1f, %.1f)\n", click.h, click.v);

    // If grid is locked, don't allow manipulation
    if (fPerspectiveGrid.locked) {
        fprintf(stderr, "[IllTool Persp Tool] Grid is locked — ignoring click\n");
        return;
    }

    // Hit-test existing handles
    PerspectiveLine* lines[3] = {
        &fPerspectiveGrid.leftVP,
        &fPerspectiveGrid.rightVP,
        &fPerspectiveGrid.verticalVP
    };

    // Convert artwork coords to view coords for hit-test radius
    // (handle positions are in artwork coords, click is in artwork coords,
    //  so we can compare directly — the hit radius is in artwork-space points)
    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;

        double d1 = PerspDist(click, lines[i]->handle1);
        double d2 = PerspDist(click, lines[i]->handle2);

        if (d1 <= kPerspHandleHitRadius) {
            fPerspDragLine = i;
            fPerspDragHandle = 1;
            fprintf(stderr, "[IllTool Persp Tool] Hit handle1 of line %d (dist=%.1f)\n", i, d1);
            return;
        }
        if (d2 <= kPerspHandleHitRadius) {
            fPerspDragLine = i;
            fPerspDragHandle = 2;
            fprintf(stderr, "[IllTool Persp Tool] Hit handle2 of line %d (dist=%.1f)\n", i, d2);
            return;
        }
    }

    // No handle hit — place VP1 and auto-mirror VP2 across horizontal center of viewport
    // Only VP1/VP2 are placed on click; VP3 uses "Add Vertical" button in the panel.
    if (fPerspNextLineIndex >= 2) {
        fprintf(stderr, "[IllTool Persp Tool] VP1+VP2 already placed (use Add Vertical for VP3)\n");
        return;
    }

    // Get the viewport (artboard) bounds to find the horizontal center
    AIRealRect viewBounds = {0, 0, 0, 0};
    if (sAIDocumentView) {
        sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
    }
    double viewCenterX = (viewBounds.left + viewBounds.right) * 0.5;
    // Fallback if bounds are zero (shouldn't happen in practice)
    if (std::abs(viewBounds.right - viewBounds.left) < 1.0) viewCenterX = 400.0;

    // VP1: place line at the click position (handle1=click, handle2 offset along direction)
    lines[0]->handle1 = click;
    lines[0]->handle2 = { (AIReal)(click.h + 100.0), click.v };
    lines[0]->active = true;
    BridgeSetPerspectiveLine(0,
        lines[0]->handle1.h, lines[0]->handle1.v,
        lines[0]->handle2.h, lines[0]->handle2.v);

    // VP2: auto-mirror across horizontal center of viewport
    // Mirror X positions: mirrorX = 2*viewCenterX - originalX
    AIRealPoint mirH1 = { (AIReal)(2.0 * viewCenterX - click.h), click.v };
    AIRealPoint mirH2 = { (AIReal)(2.0 * viewCenterX - (click.h + 100.0)), click.v };
    lines[1]->handle1 = mirH1;
    lines[1]->handle2 = mirH2;
    lines[1]->active = true;
    BridgeSetPerspectiveLine(1,
        lines[1]->handle1.h, lines[1]->handle1.v,
        lines[1]->handle2.h, lines[1]->handle2.v);

    // Ensure visibility
    BridgeSetPerspectiveVisible(true);

    fPerspDragLine = -1;
    fPerspDragHandle = 0;

    fPerspNextLineIndex = 2;  // VP1 and VP2 both placed
    fprintf(stderr, "[IllTool Persp Tool] Placed VP1 at (%.0f,%.0f), auto-mirrored VP2 at (%.0f,%.0f), viewCenterX=%.0f\n",
            click.h, click.v, mirH1.h, mirH1.v, viewCenterX);

    // Recompute and invalidate
    fPerspectiveGrid.Recompute();
    InvalidateFullView();

    // Switch back to arrow tool so user can immediately drag VPs or select paths
    if (sAITool) {
        AIToolHandle arrowTool = nullptr;
        AIToolType toolNum = 0;
        sAITool->GetToolNumberFromName("Adobe Select Tool", &toolNum);
        sAITool->GetToolHandleFromNumber(toolNum, &arrowTool);
        if (arrowTool) sAITool->SetSelectedTool(arrowTool);
    }
}

void IllToolPlugin::PerspectiveToolMouseDrag(AIToolMessage* message)
{
    if (fPerspDragLine < 0 || fPerspDragLine > 2 || fPerspDragHandle == 0) return;

    AIRealPoint pos = message->cursor;

    PerspectiveLine* lines[3] = {
        &fPerspectiveGrid.leftVP,
        &fPerspectiveGrid.rightVP,
        &fPerspectiveGrid.verticalVP
    };

    PerspectiveLine* line = lines[fPerspDragLine];

    if (fPerspDragHandle == 1) {
        line->handle1 = pos;
    } else {
        line->handle2 = pos;
    }

    // Sync to bridge
    BridgeSetPerspectiveLine(fPerspDragLine,
        line->handle1.h, line->handle1.v,
        line->handle2.h, line->handle2.v);

    // Recompute VPs and invalidate
    fPerspectiveGrid.Recompute();
    InvalidateFullView();
}

void IllToolPlugin::PerspectiveToolMouseUp(AIToolMessage* message)
{
    if (fPerspDragLine < 0) return;

    fprintf(stderr, "[IllTool Persp Tool] MouseUp — committed line %d handle %d at (%.1f, %.1f)\n",
            fPerspDragLine, fPerspDragHandle, message->cursor.h, message->cursor.v);

    // Final position update
    PerspectiveToolMouseDrag(message);

    // Clear drag state
    fPerspDragLine = -1;
    fPerspDragHandle = 0;

    // Final recompute and redraw
    fPerspectiveGrid.Recompute();
    InvalidateFullView();
}
