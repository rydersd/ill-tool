//========================================================================================
//
//  PerspectiveModule — Perspective grid implementation (core)
//
//  Ported from IllToolPerspective.cpp into the module system.
//  This file contains: PerspectiveGrid struct methods, HandleOp dispatch,
//  SyncFromBridge, OnDocumentChanged, and simple operation handlers.
//
//  Mouse interaction and overlay drawing are in PerspectiveHandles.cpp.
//  Auto VP detection, presets, and perspective transforms are in PerspectiveAutoMatch.cpp.
//  Both are #included at the bottom (not separate compilation units).
//
//========================================================================================

#include "IllustratorSDK.h"
#include "PerspectiveModule.h"
#include "CleanupModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "IllToolTokens.h"
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
    fDetectedLines.clear();
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

void PerspectiveModule::SaveToDocument()
{
    fGrid.SaveToDocument();
}

void PerspectiveModule::LoadFromDocument()
{
    fGrid.LoadFromDocument();
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
//  Included sub-files (not separate compilation units)
//========================================================================================

#include "PerspectiveHandles.cpp"
#include "PerspectiveAutoMatch.cpp"
