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
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>

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

    double bridgeHorizon = BridgeGetHorizonY();
    if (fGrid.horizonY != bridgeHorizon) {
        fGrid.horizonY = bridgeHorizon;
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

        default:
            return false;
    }
}

//========================================================================================
//  Simple operation handlers
//========================================================================================

void PerspectiveModule::ClearGrid()
{
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
    fGrid.locked = lock;
    BridgeSetPerspectiveLocked(lock);
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

void PerspectiveModule::SaveToDocument()
{
    fGrid.SaveToDocument();
}

void PerspectiveModule::LoadFromDocument()
{
    fGrid.LoadFromDocument();
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

    // Try to load persisted grid from new document
    fGrid.LoadFromDocument();
}

//========================================================================================
//  Mouse event handlers
//========================================================================================

/** Helper: compute distance between two points. */
static double PerspDist(AIRealPoint a, AIRealPoint b) {
    double dx = a.h - b.h;
    double dy = a.v - b.v;
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

        fprintf(stderr, "[IllTool PerspModule] Placement: VP1 at (%.0f,%.0f), auto-mirrored VP2 at (%.0f,%.0f)\n",
                click.h, click.v, mirH1.h, mirH1.v);

        fGrid.Recompute();
        InvalidateFullView();
        return true;
    }

    // Only consume handle drags if grid is visible and not locked
    if (!fGrid.visible) return false;
    if (fGrid.locked) return false;

    // Hit-test existing handles — works with ANY active tool
    PerspectiveLine* lines[3] = {
        &fGrid.leftVP,
        &fGrid.rightVP,
        &fGrid.verticalVP
    };

    for (int i = 0; i < 3; i++) {
        if (!lines[i]->active) continue;

        double d1 = PerspDist(click, lines[i]->handle1);
        double d2 = PerspDist(click, lines[i]->handle2);

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

        double d1 = PerspDist(click, lines[i]->handle1);
        double d2 = PerspDist(click, lines[i]->handle2);

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

    // Get the viewport bounds to find the horizontal center
    AIRealRect viewBounds = {0, 0, 0, 0};
    if (sAIDocumentView) {
        sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
    }
    double viewCenterX = (viewBounds.left + viewBounds.right) * 0.5;
    if (std::abs(viewBounds.right - viewBounds.left) < 1.0) viewCenterX = 400.0;

    // VP1: place line at click position
    lines[0]->handle1 = click;
    lines[0]->handle2 = { (AIReal)(click.h + 100.0), click.v };
    lines[0]->active = true;
    BridgeSetPerspectiveLine(0,
        lines[0]->handle1.h, lines[0]->handle1.v,
        lines[0]->handle2.h, lines[0]->handle2.v);

    // VP2: auto-mirror across horizontal center of viewport
    AIRealPoint mirH1 = { (AIReal)(2.0 * viewCenterX - click.h), click.v };
    AIRealPoint mirH2 = { (AIReal)(2.0 * viewCenterX - (click.h + 100.0)), click.v };
    lines[1]->handle1 = mirH1;
    lines[1]->handle2 = mirH2;
    lines[1]->active = true;
    BridgeSetPerspectiveLine(1,
        lines[1]->handle1.h, lines[1]->handle1.v,
        lines[1]->handle2.h, lines[1]->handle2.v);

    BridgeSetPerspectiveVisible(true);

    fDragLine = -1;
    fDragHandle = 0;
    fNextLineIndex = 2;

    fprintf(stderr, "[IllTool PerspModule Tool] Placed VP1 at (%.0f,%.0f), auto-mirrored VP2 at (%.0f,%.0f), viewCenterX=%.0f\n",
            click.h, click.v, mirH1.h, mirH1.v, viewCenterX);

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

    // --- Draw horizon line ---
    {
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.6);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
        AIFloat dashArray[] = {6.0f, 4.0f};
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
        sAIAnnotatorDrawer->SetColor(drawer, horizonColor);

        AIRealPoint artLeft  = {(AIReal)-5000.0, (AIReal)fGrid.horizonY};
        AIRealPoint artRight = {(AIReal)5000.0,  (AIReal)fGrid.horizonY};
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

        // Solid line between handles
        sAIAnnotatorDrawer->SetColor(drawer, color);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.8);
        sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0);
        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
        sAIAnnotatorDrawer->DrawLine(drawer, vh1, vh2);

        // Circle handles — hidden when grid is locked
        if (!fGrid.locked) {
            DrawHandleCircle(drawer, vh1, 5, color);
            DrawHandleCircle(drawer, vh2, 5, color);
        }

        // Dotted extension lines
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
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extA, &vExtA) == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
        }
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extB, &vExtB) == kNoErr) {
            sAIAnnotatorDrawer->DrawLine(drawer, vh2, vExtB);
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

    if (fGrid.valid) {
        drawVPMarker(fGrid.computedVP1, vp1Color);
        drawVPMarker(fGrid.computedVP2, vp2Color);
    }
    if (fGrid.verticalVP.active && fGrid.valid) {
        drawVPMarker(fGrid.computedVP3, vp3Color);
    }

    // --- Draw grid lines (only when locked) ---
    if (fGrid.locked && fGrid.valid) {
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
