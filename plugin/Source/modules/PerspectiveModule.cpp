//========================================================================================
//
//  PerspectiveModule — Perspective grid implementation
//
//  Ported from IllToolPerspective.cpp into the module system.
//  All perspective logic: grid computation, VP placement, handle dragging,
//  mirror/duplicate/paste, overlay drawing, document persistence.
//
//========================================================================================

#include "IllustratorSDK.h"
#include "PerspectiveModule.h"
#include "CleanupModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include "VisionEngine.h"

// Link ai::FilePath implementation (needed for AIPlacedSuite::GetPlacedFileSpecification).
// The Xcode project doesn't include IAIFilePath.cpp in its build sources.
#include "IAIFilePath.cpp"

// NOTE: Do NOT include IAIArtboards.cpp — it pulls in assertion dependencies.
// Use raw AIArtboardSuite C API instead of C++ wrappers.

#include <cstdio>
#include <cmath>
#include <vector>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  PerspectiveGrid method implementations
//========================================================================================

void PerspectiveModule::PerspectiveGrid::Recompute()
{
    // A grid is valid when at least the left and right VP lines are active
    valid = leftVP.active && rightVP.active;

    if (leftVP.active && rightVP.active) {
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
        double len = std::sqrt(vdx * vdx + vdy * vdy);
        if (len > 1e-6) {
            double scale = 10000.0 / len;
            // Extend in the direction that goes away from horizon (upward = negative v)
            if (vdy > 0) scale = -scale;
            computedVP3.h = (AIReal)(verticalVP.handle1.h + vdx * scale);
            computedVP3.v = (AIReal)(verticalVP.handle1.v + vdy * scale);
        }
    }

    fprintf(stderr, "[IllTool PerspModule] Recompute valid=%d lines=%d VP1=[%.0f,%.0f] VP2=[%.0f,%.0f]\n",
            valid, ActiveLineCount(),
            (double)computedVP1.h, (double)computedVP1.v,
            (double)computedVP2.h, (double)computedVP2.v);
}

void PerspectiveModule::PerspectiveGrid::Clear()
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

int PerspectiveModule::PerspectiveGrid::ActiveLineCount() const
{
    return (leftVP.active ? 1 : 0) + (rightVP.active ? 1 : 0) + (verticalVP.active ? 1 : 0);
}

bool PerspectiveModule::PerspectiveGrid::ComputeFloorHomography(double matrix[9]) const
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

AIRealPoint PerspectiveModule::PerspectiveGrid::ProjectToPlane(AIRealPoint artPt, int plane) const
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

AIRealPoint PerspectiveModule::PerspectiveGrid::MirrorInPerspective(AIRealPoint artPt, bool axisVertical) const
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
//  Project a set of points through the perspective grid
//========================================================================================

std::vector<AIRealPoint> PerspectiveModule::ProjectPointsThroughPerspective(
    const std::vector<AIRealPoint>& points, int plane)
{
    if (!fGrid.valid || points.empty()) return points;

    std::vector<AIRealPoint> projected(points.size());
    for (int i = 0; i < (int)points.size(); i++) {
        projected[i] = fGrid.ProjectToPlane(points[i], plane);
    }
    return projected;
}

//========================================================================================
//  Document persistence — AIDictionarySuite on a hidden marker art object
//========================================================================================

static const char* kPerspGridMarker     = "IllToolPerspGrid";
static const char* kPerspKeyHorizonY    = "IllToolPerspGrid_horizonY";
static const char* kPerspKeyLocked      = "IllToolPerspGrid_locked";
static const char* kPerspKeyVisible     = "IllToolPerspGrid_visible";
static const char* kPerspKeyDensity     = "IllToolPerspGrid_density";
static const char* kPerspLinePrefix[3]  = {"_L0", "_L1", "_L2"};

/** Find the hidden marker group in the document. Returns nullptr if not found. */
static AIArtHandle FindPerspMarkerArt()
{
    if (!sAIArt || !sAIDictionary || !sAILayer) return nullptr;

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

    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    if (layerCount == 0) return nullptr;

    AILayerHandle layer = nullptr;
    sAILayer->GetNthLayer(0, &layer);
    if (!layer) return nullptr;

    AIArtHandle layerGroup = nullptr;
    if (sAIArt->GetFirstArtOfLayer(layer, &layerGroup) != kNoErr || !layerGroup) return nullptr;

    AIArtHandle markerArt = nullptr;
    ASErr err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &markerArt);
    if (err != kNoErr || !markerArt) {
        fprintf(stderr, "[IllTool PerspModule] CreatePerspMarkerArt: NewArt failed %d\n", (int)err);
        return nullptr;
    }

    // Hide and lock so user can't accidentally interact
    sAIArt->SetArtUserAttr(markerArt, kArtHidden | kArtLocked, kArtHidden | kArtLocked);

    // Set the marker flag
    AIDictionaryRef dict = nullptr;
    err = sAIArt->GetDictionary(markerArt, &dict);
    if (err == kNoErr && dict) {
        AIDictKey key = sAIDictionary->Key(kPerspGridMarker);
        sAIDictionary->SetBooleanEntry(dict, key, true);
        sAIDictionary->Release(dict);
    }

    fprintf(stderr, "[IllTool PerspModule] Created marker art %p\n", (void*)markerArt);
    return markerArt;
}

void PerspectiveModule::PerspectiveGrid::SaveToDocument()
{
    if (!sAIDictionary || !sAIArt) return;

    fprintf(stderr, "[IllTool PerspModule] SaveToDocument — grid valid=%d lines=%d\n",
            valid, ActiveLineCount());

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) marker = CreatePerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] SaveToDocument: could not create marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) {
        fprintf(stderr, "[IllTool PerspModule] SaveToDocument: GetDictionary failed %d\n", (int)err);
        return;
    }

    sAIDictionary->SetRealEntry(dict, sAIDictionary->Key(kPerspKeyHorizonY), (AIReal)horizonY);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyLocked), locked);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kPerspKeyVisible), visible);
    sAIDictionary->SetIntegerEntry(dict, sAIDictionary->Key(kPerspKeyDensity), (ai::int32)gridDensity);

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
    fprintf(stderr, "[IllTool PerspModule] SaveToDocument: wrote %d lines, horizon=%.0f, locked=%d, visible=%d, density=%d\n",
            ActiveLineCount(), horizonY, locked, visible, gridDensity);
}

void PerspectiveModule::PerspectiveGrid::LoadFromDocument()
{
    fprintf(stderr, "[IllTool PerspModule] LoadFromDocument — checking for saved grid\n");

    if (!sAIDictionary || !sAIArt) return;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] LoadFromDocument: no marker art found\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) {
        fprintf(stderr, "[IllTool PerspModule] LoadFromDocument: GetDictionary failed %d\n", (int)err);
        return;
    }

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

    fprintf(stderr, "[IllTool PerspModule] LoadFromDocument: loaded %d lines, horizon=%.0f, locked=%d, visible=%d, density=%d\n",
            ActiveLineCount(), horizonY, locked, visible, gridDensity);
}

//========================================================================================
//  Sync from bridge (called every timer tick)
//========================================================================================

void PerspectiveModule::SyncFromBridge()
{
    bool anyChanged = false;

    for (int i = 0; i < 3; i++) {
        BridgePerspectiveLine bl = BridgeGetPerspectiveLine(i);
        PerspectiveLine* target = nullptr;
        switch (i) {
            case 0: target = &fGrid.leftVP; break;
            case 1: target = &fGrid.rightVP; break;
            case 2: target = &fGrid.verticalVP; break;
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

    // Horizon is stored as percentage (0-100). Convert to artboard Y coordinate.
    // Use cached artboard bounds (stable) instead of view bounds (shift on zoom/pan).
    // fCachedArtboardBounds is set in OnDocumentChanged (at document open/switch).
    double horizonPct = BridgeGetHorizonY();
    double horizonY = horizonPct;  // fallback: treat as absolute
    {
        double top = std::min((double)fCachedArtboardBounds.top, (double)fCachedArtboardBounds.bottom);
        double bot = std::max((double)fCachedArtboardBounds.top, (double)fCachedArtboardBounds.bottom);
        if (bot - top > 1.0) {
            horizonY = top + (bot - top) * (1.0 - horizonPct / 100.0);
        }
    }
    if (fGrid.horizonY != horizonY) {
        fGrid.horizonY = horizonY;
        anyChanged = true;
    }

    bool bridgeLocked = BridgeGetPerspectiveLocked();
    if (fGrid.locked != bridgeLocked) {
        fGrid.locked = bridgeLocked;
        anyChanged = true;
    }

    bool bridgeVisible = BridgeGetPerspectiveVisible();
    if (fGrid.visible != bridgeVisible) {
        fGrid.visible = bridgeVisible;
        anyChanged = true;
    }

    if (anyChanged) {
        fGrid.Recompute();
        InvalidateFullView();
    }
}

//========================================================================================
//  Operation dispatch
//========================================================================================

bool PerspectiveModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::ClearPerspective:
            ClearGrid();
            return true;

        case OpType::LockPerspective:
            LockGrid(op.boolParam1);
            return true;

        case OpType::SetPerspEditMode:
            SetEditMode(op.boolParam1);
            return true;

        case OpType::SetGridDensity:
            SetGridDensity(op.intParam);
            return true;

        case OpType::PlaceVerticalVP:
            PlaceVerticalVP();
            return true;

        case OpType::DeletePerspective:
            DeleteGrid();
            return true;

        case OpType::ActivatePerspectiveTool:
            ActivatePerspectiveTool();
            return true;

        case OpType::AutoMatchPerspective:
            AutoMatchPerspective();
            return true;

        case OpType::MirrorPerspective:
            MirrorInPerspective(op.intParam, op.boolParam1);
            return true;

        case OpType::DuplicatePerspective:
            DuplicateInPerspective(op.intParam, (int)op.param1);
            return true;

        case OpType::PastePerspective:
            PasteInPerspective(op.intParam, (float)op.param1);
            return true;

        case OpType::PerspectiveSave:
            SaveToDocument();
            return true;

        case OpType::PerspectiveLoad:
            LoadFromDocument();
            return true;

        case OpType::PerspectivePresetSave:
            SavePreset(op.strParam);
            return true;

        case OpType::PerspectivePresetLoad:
            LoadPreset(op.strParam);
            return true;

        case OpType::InvalidateOverlay:
            // Force a sync + redraw cycle — used by sliders that set bridge values directly
            SyncFromBridge();
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  Snap constraint helpers
//========================================================================================

void PerspectiveModule::RegisterSnapConstraints()
{
    if (!sAICursorSnap) {
        fprintf(stderr, "[IllTool PerspModule] AICursorSnapSuite not available\n");
        return;
    }

    // Count active perspective lines to size the constraint buffer
    int count = 0;
    PerspectiveLine* lines[3] = { &fGrid.leftVP, &fGrid.rightVP, &fGrid.verticalVP };
    for (int i = 0; i < 3; i++) {
        if (lines[i]->active) count++;
    }

    if (count == 0) {
        fprintf(stderr, "[IllTool PerspModule] No active lines — skipping snap registration\n");
        return;
    }

    // Build constraint buffer: one kLinearConstraintAbs per active VP line
    ai::AutoBuffer<AICursorConstraint> constraints(count);
    int idx = 0;
    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;

        AIReal dx = lines[i]->handle2.h - lines[i]->handle1.h;
        AIReal dy = lines[i]->handle2.v - lines[i]->handle1.v;
        AIReal theta = static_cast<AIReal>(atan2(dy, dx));

        // Use the computed VP as the constraint origin (the point the line converges to)
        AIRealPoint origin;
        if (i == 0)      origin = fGrid.computedVP1;
        else if (i == 1) origin = fGrid.computedVP2;
        else             origin = fGrid.computedVP3;

        constraints[idx] = AICursorConstraint(
            kLinearConstraintAbs,   // kind: absolute angle
            0,                      // flags: always active (no shift required)
            origin,                 // origin point (the VP)
            theta,                  // angle of the line
            ai::UnicodeString(),    // no label
            NULL                    // no custom annotation callback
        );
        idx++;
    }

    AIErr err = sAICursorSnap->SetCustom(constraints);
    if (err) {
        fprintf(stderr, "[IllTool PerspModule] SetCustom failed: %d\n", (int)err);
    } else {
        fprintf(stderr, "[IllTool PerspModule] Registered %d snap constraints\n", count);
    }
}

void PerspectiveModule::ClearSnapConstraints()
{
    if (!sAICursorSnap) return;

    AIErr err = sAICursorSnap->ClearCustom();
    if (err) {
        fprintf(stderr, "[IllTool PerspModule] ClearCustom failed: %d\n", (int)err);
    } else {
        fprintf(stderr, "[IllTool PerspModule] Snap constraints cleared\n");
    }
}

//========================================================================================
//  Simple operation handlers
//========================================================================================

void PerspectiveModule::ClearGrid()
{
    ClearSnapConstraints();

    // Restore Smart Guides if we disabled them
    if (sAIPreference && fSmartGuidesWasEnabled) {
        sAIPreference->PutBooleanPreference(NULL, "smartGuides/showToolGuides", true);
        fprintf(stderr, "[IllTool PerspModule] Smart Guides restored\n");
    }

    fGrid.Clear();
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    BridgeSetPerspectiveLocked(false);
    fNextLineIndex = 0;
    fPlacementMode = false;
    fprintf(stderr, "[IllTool PerspModule] Grid cleared\n");
    InvalidateFullView();
}

void PerspectiveModule::LockGrid(bool lock)
{
    if (lock) {
        fGrid.locked = true;
        BridgeSetPerspectiveLocked(true);

        // Register perspective-line snap constraints
        RegisterSnapConstraints();

        // Disable Smart Guides to avoid interference with perspective snapping
        if (sAIPreference) {
            AIBoolean wasEnabled = true;
            sAIPreference->GetBooleanPreference(NULL, "smartGuides/showToolGuides", &wasEnabled);
            fSmartGuidesWasEnabled = wasEnabled;
            if (wasEnabled) {
                sAIPreference->PutBooleanPreference(NULL, "smartGuides/showToolGuides", false);
                fprintf(stderr, "[IllTool PerspModule] Smart Guides disabled (was enabled)\n");
            }
        }
    } else {
        // Clear snap constraints before unlocking
        ClearSnapConstraints();

        // Restore Smart Guides if we disabled them
        if (sAIPreference && fSmartGuidesWasEnabled) {
            sAIPreference->PutBooleanPreference(NULL, "smartGuides/showToolGuides", true);
            fprintf(stderr, "[IllTool PerspModule] Smart Guides restored\n");
        }

        fGrid.locked = false;
        BridgeSetPerspectiveLocked(false);
    }

    fprintf(stderr, "[IllTool PerspModule] Grid %s\n", lock ? "locked" : "unlocked");
    InvalidateFullView();
}

void PerspectiveModule::SetGridDensity(int density)
{
    if (density < 2) density = 2;
    if (density > 20) density = 20;
    fGrid.gridDensity = density;
    fprintf(stderr, "[IllTool PerspModule] Grid density set to %d\n", density);
    InvalidateFullView();
}

void PerspectiveModule::DeleteGrid()
{
    ClearGrid();
    BridgeSetPerspectiveVisible(false);
    fGrid.visible = false;
    fprintf(stderr, "[IllTool PerspModule] Grid deleted\n");
}

void PerspectiveModule::ActivatePerspectiveTool()
{
    // Clear existing lines so user starts fresh
    fGrid.Clear();
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
    fNextLineIndex = 0;
    fGrid.visible = true;
    BridgeSetPerspectiveVisible(true);

    fPlacementMode = true;

    // Activate our main tool so we receive mouse events from the canvas.
    // (SDK only sends ToolMouseDown to the plugin that owns the active tool.)
    if (fPlugin && sAITool) {
        AIToolHandle perspTool = fPlugin->GetPerspectiveToolHandle();
        if (perspTool) {
            sAITool->SetSelectedTool(perspTool);
            fprintf(stderr, "[IllTool PerspModule] Activated perspective tool for VP placement\n");
        }
    }

    fprintf(stderr, "[IllTool PerspModule] Placement mode activated (click canvas to place VP)\n");
    InvalidateFullView();
}

//========================================================================================
//  Auto Match Perspective — detect VPs from placed reference image
//========================================================================================

void PerspectiveModule::AutoMatchPerspective()
{
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: starting\n");

    // --- Find the first placed art in the document ---
    if (!sAIMatchingArt || !sAIArt || !sAIPlaced) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: missing suites (matching=%p art=%p placed=%p)\n",
                (void*)sAIMatchingArt, (void*)sAIArt, (void*)sAIPlaced);
        return;
    }

    // Search for placed art (linked images)
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    AIMatchingArtSpec spec;
    spec.type = kPlacedArt;
    spec.whichAttr = 0;
    spec.attr = 0;
    ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0 || !matches) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: no placed art found (err=%d count=%d)\n",
                (int)err, (int)numMatches);
        return;
    }

    // Use the first placed art
    AIArtHandle placedArt = (*matches)[0];
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: found %d placed art(s), using first\n",
            (int)numMatches);

    // --- Get the linked file path ---
    ai::FilePath filePath;
    err = sAIPlaced->GetPlacedFileSpecification(placedArt, filePath);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get file spec (err=%d)\n", (int)err);
        return;
    }

    // Convert FilePath to POSIX path via CFStringRef (avoids ai::UnicodeString linker dependency)
    CFStringRef cfPath = filePath.GetAsCFString();
    if (!cfPath) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: GetAsCFString returned null\n");
        return;
    }
    char pathBuf[2048];
    if (!CFStringGetCString(cfPath, pathBuf, sizeof(pathBuf), kCFStringEncodingUTF8)) {
        CFRelease(cfPath);
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to convert path to UTF8\n");
        return;
    }
    CFRelease(cfPath);
    std::string pathCStr(pathBuf);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: placed image path: %s\n", pathCStr.c_str());

    // --- Get the placed art bounds (artwork coordinates) ---
    AIRealRect artBounds = {0, 0, 0, 0};
    err = sAIArt->GetArtBounds(placedArt, &artBounds);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get art bounds (err=%d)\n", (int)err);
        return;
    }
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: art bounds L=%.1f T=%.1f R=%.1f B=%.1f\n",
            (double)artBounds.left, (double)artBounds.top,
            (double)artBounds.right, (double)artBounds.bottom);

    // --- Get the placed art transform matrix ---
    AIRealMatrix placedMatrix;
    err = sAIPlaced->GetPlacedMatrix(placedArt, &placedMatrix);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get placed matrix (err=%d)\n", (int)err);
        // Fall back to using art bounds for coordinate mapping
    }

    // --- Load image into VisionEngine ---
    VisionEngine& ve = VisionEngine::Instance();
    if (!ve.LoadImage(pathCStr.c_str())) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to load image\n");
        return;
    }

    int imgW = ve.Width();
    int imgH = ve.Height();
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: loaded image %dx%d\n", imgW, imgH);

    // Set up coordinate mapping for pixel <-> artwork conversion
    ve.SetArtToPixelMapping(
        (double)artBounds.left, (double)artBounds.top,
        (double)artBounds.right, (double)artBounds.bottom);

    // --- Estimate vanishing points using dual approach ---
    // Method 1: Hough line convergence (traditional)
    auto houghVPs = ve.EstimateVanishingPoints(2, 50.0, 150.0, 30);

    // Method 2: Normal direction clustering (surface-aware)
    auto normalVPs = ve.EstimateVPsFromNormals(2);

    // Method 3: Surface type analysis for confidence weighting
    auto surfaceHint = ve.InferSurfaceType(0, 0, imgW, imgH);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: surface=%d conf=%.2f angle=%.1f°\n",
            (int)surfaceHint.type, surfaceHint.confidence,
            surfaceHint.gradientAngle * 180.0 / M_PI);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: Hough found %d VPs, Normals found %d VPs\n",
            (int)houghVPs.size(), (int)normalVPs.size());

    // Combine: prefer Hough VPs (more precise position), but use normal VPs as fallback
    // or to validate Hough results. Weight by surface confidence.
    std::vector<VisionEngine::VanishingPointEstimate> vps;

    if (houghVPs.size() >= 2) {
        // Hough found enough — use them, boost confidence if normals agree
        vps = houghVPs;
        for (auto& vp : vps) {
            // Check if any normal VP has a similar angle (within 15°)
            for (auto& nvp : normalVPs) {
                double angleDiff = std::abs(vp.dominantAngle - nvp.dominantAngle);
                if (angleDiff > M_PI) angleDiff = 2.0 * M_PI - angleDiff;
                if (angleDiff < M_PI / 12.0) {  // within 15°
                    vp.confidence = std::min(1.0, vp.confidence * 1.5);  // boost
                    fprintf(stderr, "[IllTool PerspModule] VP angle %.1f° confirmed by normals (boosted)\n",
                            vp.dominantAngle * 180.0 / M_PI);
                    break;
                }
            }
        }
    } else if (normalVPs.size() >= 2) {
        // Hough failed but normals found planes — use normal-derived VPs
        vps = normalVPs;
        fprintf(stderr, "[IllTool PerspModule] Using normal-derived VPs (Hough insufficient)\n");
    } else if (houghVPs.size() == 1 && normalVPs.size() >= 1) {
        // Combine: one from each
        vps.push_back(houghVPs[0]);
        vps.push_back(normalVPs[0]);
        fprintf(stderr, "[IllTool PerspModule] Combining 1 Hough + 1 Normal VP\n");
    } else {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: insufficient VPs (Hough=%d Normal=%d)\n",
                (int)houghVPs.size(), (int)normalVPs.size());
        return;
    }

    if (vps.size() < 2) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: only %d VP(s) after combining, need 2\n",
                (int)vps.size());
        return;
    }

    // --- Convert VP pixel coordinates to artwork coordinates ---
    // Pixel (0,0) = top-left, artwork uses Y-up from artBounds
    double artW = (double)(artBounds.right - artBounds.left);
    double artH = (double)(artBounds.top - artBounds.bottom);  // Y-up: top > bottom
    double scaleX = artW / (double)imgW;
    double scaleY = artH / (double)imgH;

    // Convert pixel VP to artwork coordinates
    // px -> art:  artX = artBounds.left + px * scaleX
    //             artY = artBounds.top  - py * scaleY  (flip Y)
    auto pixToArt = [&](double px, double py, double& ax, double& ay) {
        ax = (double)artBounds.left + px * scaleX;
        ay = (double)artBounds.top  - py * scaleY;
    };

    double vp1ArtX, vp1ArtY, vp2ArtX, vp2ArtY;
    pixToArt(vps[0].x, vps[0].y, vp1ArtX, vp1ArtY);
    pixToArt(vps[1].x, vps[1].y, vp2ArtX, vp2ArtY);

    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 art=(%.1f, %.1f) VP2 art=(%.1f, %.1f)\n",
            vp1ArtX, vp1ArtY, vp2ArtX, vp2ArtY);

    // --- Set up perspective grid handles ---
    // For each VP, create a line from the image center toward the VP.
    // The handle1 is near the image center, handle2 extends toward the VP.
    double imgCenterPx = imgW * 0.5;
    double imgCenterPy = imgH * 0.5;
    double centerArtX, centerArtY;
    pixToArt(imgCenterPx, imgCenterPy, centerArtX, centerArtY);

    // VP1 line: from image center toward VP1
    double dir1X = vp1ArtX - centerArtX;
    double dir1Y = vp1ArtY - centerArtY;
    double len1 = std::sqrt(dir1X * dir1X + dir1Y * dir1Y);
    if (len1 < 1e-6) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 too close to center\n");
        return;
    }
    // Handle2 is 30% of the way from center to VP
    double h2_1x = centerArtX + dir1X * 0.3;
    double h2_1y = centerArtY + dir1Y * 0.3;

    // VP2 line: from image center toward VP2
    double dir2X = vp2ArtX - centerArtX;
    double dir2Y = vp2ArtY - centerArtY;
    double len2 = std::sqrt(dir2X * dir2X + dir2Y * dir2Y);
    if (len2 < 1e-6) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP2 too close to center\n");
        return;
    }
    double h2_2x = centerArtX + dir2X * 0.3;
    double h2_2y = centerArtY + dir2Y * 0.3;

    // Clear existing grid
    fGrid.Clear();
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);

    // Set VP1 (left VP)
    fGrid.leftVP.handle1.h = (AIReal)centerArtX;
    fGrid.leftVP.handle1.v = (AIReal)centerArtY;
    fGrid.leftVP.handle2.h = (AIReal)h2_1x;
    fGrid.leftVP.handle2.v = (AIReal)h2_1y;
    fGrid.leftVP.active = true;
    BridgeSetPerspectiveLine(0, centerArtX, centerArtY, h2_1x, h2_1y);

    // Set VP2 (right VP)
    fGrid.rightVP.handle1.h = (AIReal)centerArtX;
    fGrid.rightVP.handle1.v = (AIReal)centerArtY;
    fGrid.rightVP.handle2.h = (AIReal)h2_2x;
    fGrid.rightVP.handle2.v = (AIReal)h2_2y;
    fGrid.rightVP.active = true;
    BridgeSetPerspectiveLine(1, centerArtX, centerArtY, h2_2x, h2_2y);

    // Estimate horizon Y from the two VPs:
    // If both VPs are at roughly the same Y, that is the horizon.
    // Otherwise, average the VP Y coordinates.
    double avgVpY = (vp1ArtY + vp2ArtY) * 0.5;
    fGrid.horizonY = avgVpY;
    BridgeSetHorizonY(avgVpY);

    // Make grid visible
    fGrid.visible = true;
    BridgeSetPerspectiveVisible(true);

    fGrid.Recompute();
    InvalidateFullView();

    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: grid set with 2 VPs, horizon=%.1f\n",
            fGrid.horizonY);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 conf=%.2f (%d lines), VP2 conf=%.2f (%d lines)\n",
            vps[0].confidence, vps[0].lineCount, vps[1].confidence, vps[1].lineCount);
}

void PerspectiveModule::SaveToDocument()
{
    fGrid.SaveToDocument();
}

void PerspectiveModule::LoadFromDocument()
{
    fGrid.LoadFromDocument();
}

//========================================================================================
//  Preset Save/Load — named presets stored in document dictionary
//========================================================================================

void PerspectiveModule::SavePreset(const std::string& name)
{
    if (!sAIDictionary || !sAIArt) return;
    if (name.empty()) {
        fprintf(stderr, "[IllTool PerspModule] SavePreset: empty name\n");
        return;
    }

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) marker = CreatePerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] SavePreset: no marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    // Build key prefix: "IllToolPerspPreset_<name>_"
    std::string prefix = "IllToolPerspPreset_" + name + "_";

    // Store a marker so we can enumerate presets later
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "exists").c_str()), true);

    // Save grid values with preset prefix
    sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((prefix + "horizonY").c_str()), (AIReal)fGrid.horizonY);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "locked").c_str()), fGrid.locked);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "visible").c_str()), fGrid.visible);
    sAIDictionary->SetIntegerEntry(dict, sAIDictionary->Key((prefix + "density").c_str()), (ai::int32)fGrid.gridDensity);

    const PerspectiveLine* lines[3] = {&fGrid.leftVP, &fGrid.rightVP, &fGrid.verticalVP};
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        char idx[4]; snprintf(idx, sizeof(idx), "L%d", i);
        std::string lp = prefix + idx;

        sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((lp + "_active").c_str()), line.active);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h1x").c_str()), line.handle1.h);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h1y").c_str()), line.handle1.v);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h2x").c_str()), line.handle2.h);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h2y").c_str()), line.handle2.v);
    }

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool PerspModule] SavePreset '%s': saved %d lines, horizon=%.0f\n",
            name.c_str(), fGrid.ActiveLineCount(), fGrid.horizonY);
}

void PerspectiveModule::LoadPreset(const std::string& name)
{
    if (!sAIDictionary || !sAIArt) return;
    if (name.empty()) return;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] LoadPreset: no marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    std::string prefix = "IllToolPerspPreset_" + name + "_";

    // Check that preset exists
    AIBoolean exists = false;
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "exists").c_str()), &exists);
    if (!exists) {
        sAIDictionary->Release(dict);
        fprintf(stderr, "[IllTool PerspModule] LoadPreset '%s': not found\n", name.c_str());
        return;
    }

    // Load grid values
    AIReal hY = 400;
    sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((prefix + "horizonY").c_str()), &hY);
    fGrid.horizonY = (double)hY;

    AIBoolean bLocked = false, bVisible = true;
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "locked").c_str()), &bLocked);
    fGrid.locked = bLocked;

    if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "visible").c_str()), &bVisible) == kNoErr)
        fGrid.visible = bVisible;
    else
        fGrid.visible = true;

    ai::int32 dens = 5;
    sAIDictionary->GetIntegerEntry(dict, sAIDictionary->Key((prefix + "density").c_str()), &dens);
    fGrid.gridDensity = (int)dens;

    PerspectiveLine* lines[3] = {&fGrid.leftVP, &fGrid.rightVP, &fGrid.verticalVP};
    for (int i = 0; i < 3; i++) {
        PerspectiveLine& line = *lines[i];
        char idx[4]; snprintf(idx, sizeof(idx), "L%d", i);
        std::string lp = prefix + idx;

        AIBoolean bActive = false;
        sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((lp + "_active").c_str()), &bActive);
        line.active = bActive;

        if (line.active) {
            AIReal val = 0;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h1x").c_str()), &val); line.handle1.h = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h1y").c_str()), &val); line.handle1.v = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h2x").c_str()), &val); line.handle2.h = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h2y").c_str()), &val); line.handle2.v = val;
        }
    }

    sAIDictionary->Release(dict);

    // Recompute and sync to bridge
    fGrid.Recompute();
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        if (line.active) {
            BridgeSetPerspectiveLine(i, line.handle1.h, line.handle1.v,
                                        line.handle2.h, line.handle2.v);
        } else {
            BridgeClearPerspectiveLine(i);
        }
    }
    BridgeSetHorizonY(fGrid.horizonY);
    BridgeSetPerspectiveLocked(fGrid.locked);
    BridgeSetPerspectiveVisible(fGrid.visible);
    InvalidateFullView();

    fprintf(stderr, "[IllTool PerspModule] LoadPreset '%s': loaded %d lines, horizon=%.0f\n",
            name.c_str(), fGrid.ActiveLineCount(), fGrid.horizonY);
}

std::vector<std::string> PerspectiveModule::ListPresets()
{
    std::vector<std::string> names;
    if (!sAIDictionary || !sAIArt) return names;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) return names;

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return names;

    // Scan up to 20 well-known preset slots
    for (int i = 1; i <= 20; i++) {
        char nameBuf[32];
        snprintf(nameBuf, sizeof(nameBuf), "preset%d", i);
        std::string prefix = std::string("IllToolPerspPreset_") + nameBuf + "_exists";
        AIBoolean exists = false;
        if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(prefix.c_str()), &exists) == kNoErr && exists) {
            names.push_back(nameBuf);
        }
    }
    // Also check named presets with common names
    const char* commonNames[] = {"default", "low", "high", "bird", "worm"};
    for (const char* cn : commonNames) {
        std::string prefix = std::string("IllToolPerspPreset_") + cn + "_exists";
        AIBoolean exists = false;
        if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(prefix.c_str()), &exists) == kNoErr && exists) {
            // Avoid duplicates
            bool found = false;
            for (const auto& n : names) { if (n == cn) { found = true; break; } }
            if (!found) names.push_back(cn);
        }
    }

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool PerspModule] ListPresets: %zu presets found\n", names.size());
    return names;
}

void PerspectiveModule::PlaceVerticalVP()
{
    if (fGrid.verticalVP.active) {
        fprintf(stderr, "[IllTool PerspModule] PlaceVerticalVP: VP3 already placed\n");
        return;
    }

    // Get viewport bounds to find center
    AIRealRect viewBounds = {0, 0, 0, 0};
    if (sAIDocumentView) {
        sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
    }
    double viewCenterX = (viewBounds.left + viewBounds.right) * 0.5;
    double horizY = fGrid.horizonY;

    if (std::abs(viewBounds.right - viewBounds.left) < 1.0) viewCenterX = 400.0;

    // VP3 placed above horizon at center X, with a short vertical line
    double yAbove = horizY - 200.0;
    double yBelow = horizY + 50.0;

    fGrid.verticalVP.handle1 = { (AIReal)viewCenterX, (AIReal)yAbove };
    fGrid.verticalVP.handle2 = { (AIReal)(viewCenterX + 10.0), (AIReal)yBelow };
    fGrid.verticalVP.active = true;

    BridgeSetPerspectiveLine(2,
        fGrid.verticalVP.handle1.h, fGrid.verticalVP.handle1.v,
        fGrid.verticalVP.handle2.h, fGrid.verticalVP.handle2.v);

    BridgeSetPerspectiveVisible(true);

    fGrid.Recompute();
    InvalidateFullView();

    fprintf(stderr, "[IllTool PerspModule] PlaceVerticalVP: VP3 at center (%.0f, %.0f)-(%.0f, %.0f)\n",
            viewCenterX, yAbove, viewCenterX + 10.0, yBelow);
}

//========================================================================================
//  Document change — reload perspective from document
//========================================================================================

void PerspectiveModule::OnDocumentChanged()
{
    fGrid.Clear();
    fDragLine = -1;
    fDragHandle = 0;
    fNextLineIndex = 0;
    fPlacementMode = false;
    fUndoStack.Clear();

    // Cache artboard bounds — use document crop area style to get stable bounds.
    // AIArtboardSuite C++ wrappers (ai::ArtboardList) pull in assertion dependencies,
    // so we use a simpler approach: get all art bounds as a proxy for artboard extent,
    // or use GetDocumentViewBounds on first open (when zoom=fit, view = artboard).
    fCachedArtboardBounds = {0, 0, 0, 0};
    bool gotBounds = false;

    // Strategy: use document's crop style bounds if available via the C suite
    if (sAIArtboard) {
        // The raw C API still needs the wrapper types. Fall back to view bounds
        // but cache at document open when the view typically fits the artboard.
        // This is acceptable because the horizon only needs the vertical range.
    }

    if (!gotBounds && sAIDocumentView) {
        sAIDocumentView->GetDocumentViewBounds(NULL, &fCachedArtboardBounds);
        gotBounds = true;
    }
    fprintf(stderr, "[IllTool PerspModule] Cached artboard bounds: top=%.0f bot=%.0f left=%.0f right=%.0f\n",
            fCachedArtboardBounds.top, fCachedArtboardBounds.bottom,
            fCachedArtboardBounds.left, fCachedArtboardBounds.right);

    // Try to load persisted grid from new document
    fGrid.LoadFromDocument();
}

//========================================================================================
//  Mouse event handlers
//========================================================================================

/** Helper: view-space distance for perspective handles (zoom-independent). */
static double PerspViewDist(AIRealPoint a, AIRealPoint b) {
    AIPoint va, vb;
    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &a, &va) != kNoErr) return 1e20;
    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &b, &vb) != kNoErr) return 1e20;
    double dx = va.h - vb.h, dy = va.v - vb.v;
    return std::sqrt(dx * dx + dy * dy);
}

bool PerspectiveModule::HandleMouseDown(AIToolMessage* msg)
{
    AIRealPoint click = msg->cursor;

    // Placement mode: click places VP1 + auto-mirrors VP2, then exits placement mode
    if (fPlacementMode && !fGrid.locked) {
        // Get viewport bounds to find horizontal center for mirroring
        AIRealRect viewBounds = {0, 0, 0, 0};
        if (sAIDocumentView) {
            sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
        }
        double viewCenterX = (viewBounds.left + viewBounds.right) * 0.5;
        if (std::abs(viewBounds.right - viewBounds.left) < 1.0) viewCenterX = 400.0;

        // VP1: place line at click position
        fGrid.leftVP.handle1 = click;
        fGrid.leftVP.handle2 = { (AIReal)(click.h + 100.0), click.v };
        fGrid.leftVP.active = true;
        BridgeSetPerspectiveLine(0,
            fGrid.leftVP.handle1.h, fGrid.leftVP.handle1.v,
            fGrid.leftVP.handle2.h, fGrid.leftVP.handle2.v);

        // VP2: auto-mirror across horizontal center of viewport
        AIRealPoint mirH1 = { (AIReal)(2.0 * viewCenterX - click.h), click.v };
        AIRealPoint mirH2 = { (AIReal)(2.0 * viewCenterX - (click.h + 100.0)), click.v };
        fGrid.rightVP.handle1 = mirH1;
        fGrid.rightVP.handle2 = mirH2;
        fGrid.rightVP.active = true;
        BridgeSetPerspectiveLine(1,
            fGrid.rightVP.handle1.h, fGrid.rightVP.handle1.v,
            fGrid.rightVP.handle2.h, fGrid.rightVP.handle2.v);

        BridgeSetPerspectiveVisible(true);
        fNextLineIndex = 2;
        fPlacementMode = false;
        fEditMode = true;  // Auto-enter edit mode after VP placement

        fprintf(stderr, "[IllTool PerspModule] Placement: VP1 at (%.0f,%.0f), auto-mirrored VP2 at (%.0f,%.0f) — entering edit mode\n",
                click.h, click.v, mirH1.h, mirH1.v);

        fGrid.Recompute();
        InvalidateFullView();
        return true;
    }

    // Only consume handle drags if in edit mode (or grid visible and not locked)
    if (!fEditMode && (!fGrid.visible || fGrid.locked)) return false;

    // Hit-test existing handles — works with ANY active tool
    PerspectiveLine* lines[3] = {
        &fGrid.leftVP,
        &fGrid.rightVP,
        &fGrid.verticalVP
    };

    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;

        double d1 = PerspViewDist(click, lines[i]->handle1);
        double d2 = PerspViewDist(click, lines[i]->handle2);

        if (d1 <= kHandleHitRadius) {
            fDragLine = i;
            fDragHandle = 1;
            fprintf(stderr, "[IllTool PerspModule] Hit handle1 of line %d (dist=%.1f)\n", i, d1);
            return true;
        }
        if (d2 <= kHandleHitRadius) {
            fDragLine = i;
            fDragHandle = 2;
            fprintf(stderr, "[IllTool PerspModule] Hit handle2 of line %d (dist=%.1f)\n", i, d2);
            return true;
        }
    }

    // No handle hit — not consumed (let other tools handle the click)
    return false;
}

bool PerspectiveModule::HandleMouseDrag(AIToolMessage* msg)
{
    if (fDragLine < 0 || fDragLine > 2 || fDragHandle == 0) return false;

    AIRealPoint pos = msg->cursor;

    PerspectiveLine* lines[3] = {
        &fGrid.leftVP,
        &fGrid.rightVP,
        &fGrid.verticalVP
    };

    PerspectiveLine* line = lines[fDragLine];

    if (fDragHandle == 1) {
        line->handle1 = pos;
    } else {
        line->handle2 = pos;
    }

    // Sync to bridge
    BridgeSetPerspectiveLine(fDragLine,
        line->handle1.h, line->handle1.v,
        line->handle2.h, line->handle2.v);

    fGrid.Recompute();
    InvalidateFullView();
    return true;
}

bool PerspectiveModule::HandleMouseUp(AIToolMessage* msg)
{
    if (fDragLine < 0) return false;

    fprintf(stderr, "[IllTool PerspModule] MouseUp — committed line %d handle %d at (%.1f, %.1f)\n",
            fDragLine, fDragHandle, msg->cursor.h, msg->cursor.v);

    // Final position update
    HandleMouseDrag(msg);

    // Clear drag state
    fDragLine = -1;
    fDragHandle = 0;

    fGrid.Recompute();
    InvalidateFullView();
    return true;
}

//========================================================================================
//  Edit mode — enter/exit perspective editing
//========================================================================================

void PerspectiveModule::SetEditMode(bool edit)
{
    fEditMode = edit;
    if (edit) {
        // Mutual exclusion: cancel cleanup working mode when entering perspective edit
        if (gPlugin) {
            auto* cleanup = gPlugin->GetModule<CleanupModule>();
            if (cleanup && cleanup->IsInWorkingMode()) {
                cleanup->CancelWorkingMode();
                fprintf(stderr, "[IllTool PerspModule] SetEditMode: cancelled cleanup working mode\n");
            }
        }
        fGrid.locked = false;
        BridgeSetPerspectiveLocked(false);
        fprintf(stderr, "[IllTool PerspModule] Entered edit mode\n");
    } else {
        fGrid.locked = true;
        BridgeSetPerspectiveLocked(true);
        fHoverLine = -1;
        fHoverHandle = 0;
        fprintf(stderr, "[IllTool PerspModule] Exited edit mode (grid locked)\n");
    }
    InvalidateFullView();
}

//========================================================================================
//  Cursor tracking — hover highlighting for VP handles
//========================================================================================

void PerspectiveModule::HandleCursorTrack(AIRealPoint artPt)
{
    if (!fGrid.visible || fGrid.locked) {
        fHoverLine = -1;
        fHoverHandle = 0;
        return;
    }

    int prevLine = fHoverLine;
    int prevHandle = fHoverHandle;
    fHoverLine = -1;
    fHoverHandle = 0;

    PerspectiveLine* lines[3] = {
        &fGrid.leftVP,
        &fGrid.rightVP,
        &fGrid.verticalVP
    };

    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;
        double d1 = PerspViewDist(artPt, lines[i]->handle1);
        double d2 = PerspViewDist(artPt, lines[i]->handle2);
        if (d1 <= kHandleHitRadius) {
            fHoverLine = i; fHoverHandle = 1; break;
        }
        if (d2 <= kHandleHitRadius) {
            fHoverLine = i; fHoverHandle = 2; break;
        }
    }

    if (fHoverLine != prevLine || fHoverHandle != prevHandle) {
        InvalidateFullView();
    }
}

//========================================================================================
//  Perspective tool mouse handlers (called when perspective tool is active)
//  These handle VP placement on click + auto-mirror + switch to arrow tool
//========================================================================================

void PerspectiveModule::ToolMouseDown(AIToolMessage* msg)
{
    AIRealPoint click = msg->cursor;
    fprintf(stderr, "[IllTool PerspModule Tool] MouseDown at (%.1f, %.1f)\n", click.h, click.v);

    if (fGrid.locked) {
        fprintf(stderr, "[IllTool PerspModule Tool] Grid is locked — ignoring click\n");
        return;
    }

    // Hit-test existing handles first
    PerspectiveLine* lines[3] = {
        &fGrid.leftVP,
        &fGrid.rightVP,
        &fGrid.verticalVP
    };

    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;

        double d1 = PerspViewDist(click, lines[i]->handle1);
        double d2 = PerspViewDist(click, lines[i]->handle2);

        if (d1 <= kHandleHitRadius) {
            fDragLine = i;
            fDragHandle = 1;
            fprintf(stderr, "[IllTool PerspModule Tool] Hit handle1 of line %d (dist=%.1f)\n", i, d1);
            return;
        }
        if (d2 <= kHandleHitRadius) {
            fDragLine = i;
            fDragHandle = 2;
            fprintf(stderr, "[IllTool PerspModule Tool] Hit handle2 of line %d (dist=%.1f)\n", i, d2);
            return;
        }
    }

    // No handle hit — place VP1 and auto-mirror VP2
    if (fNextLineIndex >= 2) {
        fprintf(stderr, "[IllTool PerspModule Tool] VP1+VP2 already placed (use Add Vertical for VP3)\n");
        return;
    }

    // Get artboard center X from cached bounds (stable across zoom/pan).
    // Fall back to view center if cached bounds are zero (no artboard loaded yet).
    double centerX = (fCachedArtboardBounds.left + fCachedArtboardBounds.right) * 0.5;
    if (std::abs(fCachedArtboardBounds.right - fCachedArtboardBounds.left) < 1.0) {
        AIRealRect viewBounds = {0, 0, 0, 0};
        if (sAIDocumentView) {
            sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
        }
        centerX = (viewBounds.left + viewBounds.right) * 0.5;
        if (std::abs(viewBounds.right - viewBounds.left) < 1.0) centerX = 400.0;
    }

    // VP1: place line at click position
    lines[0]->handle1 = click;
    lines[0]->handle2 = { (AIReal)(click.h + 100.0), click.v };
    lines[0]->active = true;
    BridgeSetPerspectiveLine(0,
        lines[0]->handle1.h, lines[0]->handle1.v,
        lines[0]->handle2.h, lines[0]->handle2.v);

    // VP2: auto-mirror across artboard center X
    AIRealPoint mirH1 = { (AIReal)(2.0 * centerX - lines[0]->handle1.h), lines[0]->handle1.v };
    AIRealPoint mirH2 = { (AIReal)(2.0 * centerX - lines[0]->handle2.h), lines[0]->handle2.v };
    lines[1]->handle1 = mirH1;
    lines[1]->handle2 = mirH2;
    lines[1]->active = true;
    BridgeSetPerspectiveLine(1,
        lines[1]->handle1.h, lines[1]->handle1.v,
        lines[1]->handle2.h, lines[1]->handle2.v);

    BridgeSetPerspectiveVisible(true);

    fDragLine = -1;
    fDragHandle = 0;
    fNextLineIndex = 2;  // skip rightVP, go straight to vertical

    fprintf(stderr, "[IllTool PerspModule] Auto-mirrored VP2 from VP1 — centerX=%.0f, VP1=(%.0f,%.0f)-(%.0f,%.0f), VP2=(%.0f,%.0f)-(%.0f,%.0f)\n",
            centerX,
            lines[0]->handle1.h, lines[0]->handle1.v, lines[0]->handle2.h, lines[0]->handle2.v,
            mirH1.h, mirH1.v, mirH2.h, mirH2.v);

    fGrid.Recompute();
    InvalidateFullView();

    // Switch back to arrow tool
    if (sAITool) {
        AIToolHandle arrowTool = nullptr;
        AIToolType toolNum = 0;
        sAITool->GetToolNumberFromName("Adobe Select Tool", &toolNum);
        sAITool->GetToolHandleFromNumber(toolNum, &arrowTool);
        if (arrowTool) sAITool->SetSelectedTool(arrowTool);
    }
}

void PerspectiveModule::ToolMouseDrag(AIToolMessage* msg)
{
    // Delegate to the generic handle drag
    HandleMouseDrag(msg);
}

void PerspectiveModule::ToolMouseUp(AIToolMessage* msg)
{
    // Delegate to the generic handle up
    HandleMouseUp(msg);
}

//========================================================================================
//  Annotator overlay drawing
//========================================================================================

/** Helper: draw a circle handle marker at a view point. */
static void DrawHandleCircle(AIAnnotatorDrawer* drawer, AIPoint center, int radius,
                              const AIRGBColor& color)
{
    AIRect r;
    r.left   = center.h - radius;
    r.top    = center.v - radius;
    r.right  = center.h + radius;
    r.bottom = center.v + radius;

    // White fill + colored outline — matches cleanup bbox handle style
    AIRGBColor white;
    white.red = white.green = white.blue = 65535;
    sAIAnnotatorDrawer->SetColor(drawer, white);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, true);
    sAIAnnotatorDrawer->SetColor(drawer, color);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.5);
    sAIAnnotatorDrawer->DrawEllipse(drawer, r, false);
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

/** Helper: draw a white outline stroke behind a colored line for visibility.
    Draws a wider white line first, then the colored line on top.
    Caller is responsible for setting dash state before calling this. */
static void DrawOutlinedLine(AIAnnotatorDrawer* drawer, AIPoint p1, AIPoint p2,
                              const AIRGBColor& color, AIReal colorWidth, AIReal opacity)
{
    // White outline (wider, behind)
    AIRGBColor white;
    white.red = white.green = white.blue = 65535;
    sAIAnnotatorDrawer->SetColor(drawer, white);
    sAIAnnotatorDrawer->SetOpacity(drawer, opacity * 0.7);
    sAIAnnotatorDrawer->SetLineWidth(drawer, colorWidth + 2.0);
    sAIAnnotatorDrawer->DrawLine(drawer, p1, p2);

    // Colored line on top
    sAIAnnotatorDrawer->SetColor(drawer, color);
    sAIAnnotatorDrawer->SetOpacity(drawer, opacity);
    sAIAnnotatorDrawer->SetLineWidth(drawer, colorWidth);
    sAIAnnotatorDrawer->DrawLine(drawer, p1, p2);
}

void PerspectiveModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    // Sync from bridge before drawing (replaces the timer-based SyncPerspectiveFromBridge)
    SyncFromBridge();
    DrawPerspectiveOverlay(msg);
}

void PerspectiveModule::DrawPerspectiveOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer) return;

    if (!fGrid.visible) return;

    bool hasAnyLine = fGrid.leftVP.active ||
                      fGrid.rightVP.active ||
                      fGrid.verticalVP.active;
    if (!hasAnyLine && !fGrid.valid) return;

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

    // --- Draw horizon line (white outline + colored dashed line) ---
    {
        // Horizon line extends across visible canvas
        double horizExtend = 2000.0;
        if (sAIDocumentView) {
            AIRealRect vb = {0, 0, 0, 0};
            if (sAIDocumentView->GetDocumentViewBounds(NULL, &vb) == kNoErr) {
                horizExtend = fabs(vb.right - vb.left) * 0.6;
            }
        }
        AIRealPoint artLeft  = {(AIReal)(-horizExtend), (AIReal)fGrid.horizonY};
        AIRealPoint artRight = {(AIReal)(horizExtend),  (AIReal)fGrid.horizonY};
        AIPoint vLeft, vRight;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artLeft, &vLeft) == kNoErr &&
            sAIDocumentView->ArtworkPointToViewPoint(NULL, &artRight, &vRight) == kNoErr) {
            AIFloat dashArray[] = {6.0f, 4.0f};

            // White outline pass (wider, behind)
            AIRGBColor white;
            white.red = white.green = white.blue = 65535;
            sAIAnnotatorDrawer->SetColor(drawer, white);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 3.5);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vLeft, vRight);

            // Colored horizon line on top
            sAIAnnotatorDrawer->SetColor(drawer, horizonColor);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.6);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 1.5);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
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

        // Solid line between handles (white outline + colored line)
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
        DrawOutlinedLine(drawer, vh1, vh2, color, 2.0, 0.8);

        // Circle handles — hidden when grid is locked, hover-highlighted
        if (!fGrid.locked) {
            // Find which line index this is (for hover check)
            int lineIdx = -1;
            if (&line == &fGrid.leftVP) lineIdx = 0;
            else if (&line == &fGrid.rightVP) lineIdx = 1;
            else if (&line == &fGrid.verticalVP) lineIdx = 2;

            bool h1Hover = (fHoverLine == lineIdx && fHoverHandle == 1);
            bool h2Hover = (fHoverLine == lineIdx && fHoverHandle == 2);
            bool h1Drag  = (fDragLine == lineIdx && fDragHandle == 1);
            bool h2Drag  = (fDragLine == lineIdx && fDragHandle == 2);

            AIRGBColor hoverColor;
            hoverColor.red = (ai::uint16)(1.0 * 65535);
            hoverColor.green = (ai::uint16)(1.0 * 65535);
            hoverColor.blue = (ai::uint16)(0.5 * 65535);

            // Fixed screen-space handle sizes (8px normal, 10px hover/drag)
            DrawHandleCircle(drawer, vh1, (h1Hover || h1Drag) ? 10 : 8,
                             (h1Hover || h1Drag) ? hoverColor : color);
            DrawHandleCircle(drawer, vh2, (h2Hover || h2Drag) ? 10 : 8,
                             (h2Hover || h2Drag) ? hoverColor : color);
        }

        // Dotted extension lines
        double dx = line.handle2.h - line.handle1.h;
        double dy = line.handle2.v - line.handle1.v;
        double len = std::sqrt(dx * dx + dy * dy);
        if (len < 1e-6) return;

        double nx = dx / len;
        double ny = dy / len;
        // Extend lines to fill the visible canvas
        double extendDist = 2000.0;  // default
        if (sAIDocumentView) {
            AIRealRect vb = {0, 0, 0, 0};
            if (sAIDocumentView->GetDocumentViewBounds(NULL, &vb) == kNoErr) {
                double vw = fabs(vb.right - vb.left);
                double vh = fabs(vb.top - vb.bottom);
                extendDist = std::max(vw, vh) * 1.2;
            }
        }

        AIRealPoint extA = {(AIReal)(line.handle1.h - nx * extendDist),
                            (AIReal)(line.handle1.v - ny * extendDist)};
        AIRealPoint extB = {(AIReal)(line.handle2.h + nx * extendDist),
                            (AIReal)(line.handle2.v + ny * extendDist)};

        AIRGBColor extColor = DimColor(color, 0.6);
        AIFloat dashArray[] = {4.0f, 6.0f};

        AIPoint vExtA, vExtB;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extA, &vExtA) == kNoErr) {
            // White outline pass
            AIRGBColor white;
            white.red = white.green = white.blue = 65535;
            sAIAnnotatorDrawer->SetColor(drawer, white);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 3.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
            // Colored extension line on top
            sAIAnnotatorDrawer->SetColor(drawer, extColor);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
        }
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extB, &vExtB) == kNoErr) {
            // White outline pass
            AIRGBColor white;
            white.red = white.green = white.blue = 65535;
            sAIAnnotatorDrawer->SetColor(drawer, white);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 3.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtB, vh2);
            // Colored extension line on top
            sAIAnnotatorDrawer->SetColor(drawer, extColor);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtB, vh2);
        }
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
    };

    drawPerspectiveLine(fGrid.leftVP, vp1Color);
    drawPerspectiveLine(fGrid.rightVP, vp2Color);
    drawPerspectiveLine(fGrid.verticalVP, vp3Color);

    // --- Draw computed VP markers (crosses with circles) ---
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

    // Draw VP markers only if they're within a reasonable screen range
    // (VPs at ±1M cause annotator overflow)
    if (fGrid.valid) {
        if (std::abs(fGrid.computedVP1.h) < 50000 && std::abs(fGrid.computedVP1.v) < 50000) {
            drawVPMarker(fGrid.computedVP1, vp1Color);
        }
        if (std::abs(fGrid.computedVP2.h) < 50000 && std::abs(fGrid.computedVP2.v) < 50000) {
            drawVPMarker(fGrid.computedVP2, vp2Color);
        }
    }
    if (fGrid.verticalVP.active && fGrid.valid) {
        if (std::abs(fGrid.computedVP3.h) < 50000 && std::abs(fGrid.computedVP3.v) < 50000) {
            drawVPMarker(fGrid.computedVP3, vp3Color);
        }
    }

    // --- Draw grid lines (only when locked) ---
    // Draw grid lines when valid (in edit mode or locked)
    if (fGrid.valid) {
        sAIAnnotatorDrawer->SetColor(drawer, gridColor);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.3);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 0.5);

        int density = fGrid.gridDensity;

        double cx = (fGrid.computedVP1.h + fGrid.computedVP2.h) * 0.5;
        double span = std::abs(fGrid.computedVP2.h - fGrid.computedVP1.h);
        if (span < 10.0) span = 10.0;
        double gridExtent = span * 0.5;
        double gridBottom = fGrid.horizonY + gridExtent;

        // Lines from VP1 fanning out
        for (int i = 0; i <= density; i++) {
            double t = (double)i / (double)density;
            double targetX = cx - gridExtent * 0.3 + t * gridExtent * 1.3;
            AIRealPoint artFrom = fGrid.computedVP1;
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
            AIRealPoint artFrom = fGrid.computedVP2;
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
            double y = fGrid.horizonY + t * (gridBottom - fGrid.horizonY);
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
        if (fGrid.verticalVP.active) {
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            for (int i = 0; i <= density; i++) {
                double t = (double)i / (double)density;
                double targetX = cx - gridExtent * 0.5 + t * gridExtent;
                AIRealPoint artFrom = fGrid.computedVP3;
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

/** Build a wall-plane homography (left wall or right wall). */
static bool ComputeWallHomography(const PerspectiveModule::PerspectiveGrid& grid, int plane, double matrix[9])
{
    if (!grid.ComputeFloorHomography(matrix)) return false;

    double cx = (grid.computedVP1.h + grid.computedVP2.h) * 0.5;
    double span = std::abs(grid.computedVP2.h - grid.computedVP1.h);
    if (span < 1.0) span = 1.0;
    double halfSpan = span * 0.25;

    double wallWidth = halfSpan * 0.8;
    double wallHeight = halfSpan * 1.0;
    double farScale = 0.7;

    double p0x, p0y, p1x, p1y, p2x, p2y, p3x, p3y;
    if (plane == 1) {
        // Left wall
        p0x = cx;                   p0y = grid.horizonY;
        p1x = cx - wallWidth;       p1y = grid.horizonY;
        p2x = cx - wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale;
        p3x = cx;                   p3y = grid.horizonY + wallHeight;
    } else {
        // Right wall
        p0x = cx;                   p0y = grid.horizonY;
        p1x = cx + wallWidth;       p1y = grid.horizonY;
        p2x = cx + wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale;
        p3x = cx;                   p3y = grid.horizonY + wallHeight;
    }

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

/** Get selected path art handles using isolation-aware matching. */
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
//  Mirror in Perspective
//========================================================================================

void PerspectiveModule::MirrorInPerspective(int axis, bool replace)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: missing suites\n");
        return;
    }

    double H[9], Hinv[9];
    if (!fGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: no selected paths\n");
        return;
    }

    bool axisVertical = (axis == 0);

    fUndoStack.PushFrame();
    int mirroredCount = 0;

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        // Transform each segment through H -> mirror -> Hinv
        std::vector<AIPathSegment> mirroredSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& mir = mirroredSegs[s];

            AIRealPoint pAnchor = ApplyHomography(Hinv, orig.p);
            if (axisVertical) pAnchor.h = -pAnchor.h;
            else              pAnchor.v = -pAnchor.v;
            mir.p = ApplyHomography(H, pAnchor);

            AIRealPoint inPt = {orig.in.h, orig.in.v};
            AIRealPoint inPersp = ApplyHomography(Hinv, inPt);
            if (axisVertical) inPersp.h = -inPersp.h;
            else              inPersp.v = -inPersp.v;
            mir.in = ApplyHomography(H, inPersp);

            AIRealPoint outPt = {orig.out.h, orig.out.v};
            AIRealPoint outPersp = ApplyHomography(Hinv, outPt);
            if (axisVertical) outPersp.h = -outPersp.h;
            else              outPersp.v = -outPersp.v;
            mir.out = ApplyHomography(H, outPersp);

            mir.corner = orig.corner;
        }

        // Reverse segment order so winding stays consistent
        std::vector<AIPathSegment> reversed(segCount);
        for (int s = 0; s < segCount; s++) {
            int ri = segCount - 1 - s;
            reversed[s].p   = mirroredSegs[ri].p;
            reversed[s].in  = mirroredSegs[ri].out;
            reversed[s].out = mirroredSegs[ri].in;
            reversed[s].corner = mirroredSegs[ri].corner;
        }

        if (replace) {
            fUndoStack.SnapshotPath(art);
            sAIPath->SetPathSegments(art, 0, segCount, reversed.data());
        } else {
            AIArtHandle newArt = nullptr;
            ASErr dupErr = sAIArt->DuplicateArt(art, kPlaceAbove, art, &newArt);
            if (dupErr == kNoErr && newArt) {
                sAIPath->SetPathSegments(newArt, 0, segCount, reversed.data());
                AIPathStyle style;
                AIBoolean hasAdvFill = false;
                if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr) {
                    sAIPathStyle->SetPathStyle(newArt, &style);
                }
                mirroredCount++;
            }
        }
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: %s %d paths, axis=%s\n",
            replace ? "replaced" : "created", replace ? numMatches : mirroredCount,
            axisVertical ? "vertical" : "horizontal");

    InvalidateFullView();
}

//========================================================================================
//  Duplicate in Perspective
//========================================================================================

void PerspectiveModule::DuplicateInPerspective(int count, int spacing)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: missing suites\n");
        return;
    }
    if (count < 1) count = 1;
    if (count > 50) count = 50;

    double H[9], Hinv[9];
    if (!fGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: no selected paths\n");
        return;
    }

    int spacingMode = spacing & 0x03;
    int direction   = (spacing >> 2) & 0x03;

    double dirX = 0, dirY = 0;
    double baseOffset = 0.15;

    switch (direction) {
        case 0:  dirX = -baseOffset; dirY = 0; break;
        case 1:  dirX =  baseOffset; dirY = 0; break;
        case 2:  dirX = 0;           dirY = -baseOffset; break;
        case 3:  dirX = 0;           dirY =  baseOffset; break;
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

        AIPathStyle style;
        AIBoolean hasAdvFill = false;
        bool hasStyle = (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr);

        // Compute centroid in perspective space for depth scaling
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

            double perspOffX, perspOffY;
            if (spacingMode == 0) {
                perspOffX = dirX * stepScale;
                perspOffY = dirY * stepScale;
            } else {
                double depthFactor = 1.0 + stepScale * 0.15;
                perspOffX = dirX * stepScale * depthFactor;
                perspOffY = dirY * stepScale * depthFactor;
            }

            AIRealPoint newCentroidPersp = {
                (AIReal)(centroidPersp.h + perspOffX),
                (AIReal)(centroidPersp.v + perspOffY)
            };
            AIRealPoint newCentroidArt = ApplyHomography(H, newCentroidPersp);
            AIRealPoint origCentroidArt = ApplyHomography(H, centroidPersp);

            double wOrig = Hinv[6] * origCentroidArt.h + Hinv[7] * origCentroidArt.v + Hinv[8];
            double wNew  = Hinv[6] * newCentroidArt.h  + Hinv[7] * newCentroidArt.v  + Hinv[8];
            double scaleFactor = (std::abs(wOrig) > 1e-12 && std::abs(wNew) > 1e-12) ?
                                 wNew / wOrig : 1.0;
            if (scaleFactor < 0.1) scaleFactor = 0.1;
            if (scaleFactor > 5.0) scaleFactor = 5.0;

            std::vector<AIPathSegment> dupSegs(segCount);
            for (int s = 0; s < segCount; s++) {
                const AIPathSegment& orig = segs[s];
                AIPathSegment& dup = dupSegs[s];

                AIRealPoint pPersp = ApplyHomography(Hinv, orig.p);
                pPersp.h = (AIReal)(pPersp.h + perspOffX);
                pPersp.v = (AIReal)(pPersp.v + perspOffY);
                dup.p = ApplyHomography(H, pPersp);

                AIRealPoint inPersp = ApplyHomography(Hinv, orig.in);
                AIRealPoint anchorPersp = ApplyHomography(Hinv, orig.p);
                double inDx = inPersp.h - anchorPersp.h;
                double inDy = inPersp.v - anchorPersp.v;
                AIRealPoint inOffPersp = {
                    (AIReal)(anchorPersp.h + perspOffX + inDx * scaleFactor),
                    (AIReal)(anchorPersp.v + perspOffY + inDy * scaleFactor)
                };
                dup.in = ApplyHomography(H, inOffPersp);

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

    fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: created %d copies (count=%d, dir=%d, spacing=%d)\n",
            totalCreated, count, direction, spacingMode);

    InvalidateFullView();
}

//========================================================================================
//  Paste in Perspective
//========================================================================================

void PerspectiveModule::PasteInPerspective(int plane, float scale)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: missing suites\n");
        return;
    }
    if (scale < 0.01f) scale = 0.01f;
    if (scale > 10.0f) scale = 10.0f;

    double H[9], Hinv[9];
    bool gotH = false;

    if (plane == 0) {
        gotH = fGrid.ComputeFloorHomography(H);
    } else {
        gotH = ComputeWallHomography(fGrid, plane, H);
    }

    if (!gotH) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: homography failed for plane %d\n", plane);
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: no selected paths\n");
        return;
    }

    fUndoStack.PushFrame();
    int transformedCount = 0;

    // Compute global centroid
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

        std::vector<AIPathSegment> projSegs(segCount);
        double normRange = 200.0;
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& proj = projSegs[s];

            AIRealPoint centered = {
                (AIReal)((orig.p.h - globalCentroid.h) * scale),
                (AIReal)((orig.p.v - globalCentroid.v) * scale)
            };
            AIRealPoint uv = {
                (AIReal)(0.5 + centered.h / normRange),
                (AIReal)(0.5 + centered.v / normRange)
            };
            proj.p = ApplyHomography(H, uv);

            AIRealPoint inCentered = {
                (AIReal)((orig.in.h - globalCentroid.h) * scale),
                (AIReal)((orig.in.v - globalCentroid.v) * scale)
            };
            AIRealPoint inUV = {
                (AIReal)(0.5 + inCentered.h / normRange),
                (AIReal)(0.5 + inCentered.v / normRange)
            };
            proj.in = ApplyHomography(H, inUV);

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

    fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: transformed %d paths onto plane %d (scale=%.2f)\n",
            transformedCount, plane, scale);

    InvalidateFullView();
}
