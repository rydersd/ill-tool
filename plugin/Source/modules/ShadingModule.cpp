//========================================================================================
//  ShadingModule — Surface Shading (Stage 12)
//  Two shading modes:
//    A) Blend Shading — stacked contours with highlight-to-shadow color ramp
//    B) Mesh Gradient Shading — AIMeshSuite programmatic mesh gradients
//
//  Ported from IllToolShading.cpp into module pattern.
//========================================================================================

#include "ShadingModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

//========================================================================================
//  Helpers
//========================================================================================

static double LerpColorF(double a, double b, double t)
{
    double val = a + t * (b - a);
    if (val < 0) val = 0;
    if (val > 1) val = 1;
    return val;
}

static void LightDirection(double lightAngleDeg, double& dx, double& dy)
{
    double rad = lightAngleDeg * M_PI / 180.0;
    dx = cos(rad);
    dy = sin(rad);
}

AIArtHandle ShadingModule::GetFirstSelectedPath()
{
    if (!sAIMatchingArt) return nullptr;

    AIMatchingArtSpec spec;
    spec.type = kPathArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;

    ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
    if (err || numMatches == 0 || !matches) return nullptr;

    AIArtHandle result = (*matches)[0];
    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    return result;
}

//========================================================================================
//  HandleOp — operation dispatch
//========================================================================================

bool ShadingModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::ShadingApplyBlend:
            DispatchShadingOp(OpType::ShadingApplyBlend);
            return true;
        case OpType::ShadingApplyMesh:
            DispatchShadingOp(OpType::ShadingApplyMesh);
            return true;
        case OpType::ShadingSetMode: {
            int mode = op.intParam;
            if (mode < 0) mode = 0;
            if (mode > 1) mode = 1;
            BridgeSetShadingMode(mode);
            fprintf(stderr, "[ShadingModule] Set mode: %d (%s)\n",
                    mode, mode == 0 ? "blend" : "mesh");
            return true;
        }
        default:
            return false;
    }
}

//========================================================================================
//  Notifications
//========================================================================================

void ShadingModule::OnDocumentChanged()
{
    fShadingGroupCounter = 0;
}

//========================================================================================
//  DispatchShadingOp
//========================================================================================

void ShadingModule::DispatchShadingOp(OpType opType)
{
    AIArtHandle path = GetFirstSelectedPath();
    if (!path) {
        fprintf(stderr, "[ShadingModule] No path selected for shading\n");
        return;
    }

    double hR, hG, hB, sR, sG, sB;
    BridgeGetShadingHighlight(hR, hG, hB);
    BridgeGetShadingShadow(sR, sG, sB);
    double lightAngle = BridgeGetShadingLightAngle();
    double intensity  = BridgeGetShadingIntensity();

    if (opType == OpType::ShadingApplyBlend) {
        int steps = BridgeGetShadingBlendSteps();
        fprintf(stderr, "[ShadingModule] Applying blend shading: steps=%d, "
                "angle=%.0f, intensity=%.0f\n", steps, lightAngle, intensity);
        int result = ApplyBlendShading(path, steps,
            hR, hG, hB, sR, sG, sB, lightAngle, intensity);
        fprintf(stderr, "[ShadingModule] Blend result: %d contours\n", result);
    }
    else if (opType == OpType::ShadingApplyMesh) {
        int gridSize = BridgeGetShadingMeshGrid();
        fprintf(stderr, "[ShadingModule] Applying mesh shading: grid=%d, "
                "angle=%.0f, intensity=%.0f\n", gridSize, lightAngle, intensity);
        int result = ApplyMeshShading(path, gridSize,
            hR, hG, hB, sR, sG, sB, lightAngle, intensity);
        fprintf(stderr, "[ShadingModule] Mesh result: %d\n", result);
    }
}

//========================================================================================
//  Mode A: Blend Shading
//========================================================================================

int ShadingModule::ApplyBlendShading(AIArtHandle path, int steps,
    double highlightR, double highlightG, double highlightB,
    double shadowR, double shadowG, double shadowB,
    double lightAngle, double intensity)
{
    if (!path || steps < 1) return 0;
    if (!sAIArt || !sAIPath || !sAIPathStyle) return 0;

    if (steps > 15) steps = 15;
    if (intensity < 0) intensity = 0;
    if (intensity > 100) intensity = 100;

    double intensityNorm = intensity / 100.0;

    short artType = 0;
    sAIArt->GetArtType(path, &artType);
    if (artType != kPathArt) {
        fprintf(stderr, "[ShadingModule] Blend: source is not a path (type=%d)\n", artType);
        return 0;
    }

    AIBoolean closed = false;
    sAIPath->GetPathClosed(path, &closed);
    if (!closed) {
        fprintf(stderr, "[ShadingModule] Blend: path is not closed\n");
        return 0;
    }

    AIRealRect bounds;
    ASErr err = sAIArt->GetArtBounds(path, &bounds);
    if (err) {
        fprintf(stderr, "[ShadingModule] Blend: GetArtBounds failed: %d\n", (int)err);
        return 0;
    }

    double cx = (bounds.left + bounds.right) / 2.0;
    double cy = (bounds.top + bounds.bottom) / 2.0;
    double halfW = (bounds.right - bounds.left) / 2.0;
    double halfH = (bounds.top - bounds.bottom) / 2.0;
    if (halfW < 1 || halfH < 1) return 0;

    double ldx, ldy;
    LightDirection(lightAngle, ldx, ldy);

    AIArtHandle groupArt = nullptr;
    err = sAIArt->NewArt(kGroupArt, kPlaceAbove, path, &groupArt);
    if (err || !groupArt) {
        fprintf(stderr, "[ShadingModule] Blend: failed to create group: %d\n", (int)err);
        return 0;
    }

    fShadingGroupCounter++;
    char groupName[64];
    snprintf(groupName, sizeof(groupName), "Shading Group %d", fShadingGroupCounter);
    ai::UnicodeString uname(groupName);
    sAIArt->SetArtName(groupArt, uname);

    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(path, &segCount);
    if (segCount < 2) return 0;

    std::vector<AIPathSegment> origSegs(segCount);
    sAIPath->GetPathSegments(path, 0, segCount, origSegs.data());

    int created = 0;

    for (int i = 0; i <= steps; i++) {
        double t = (steps > 0) ? (double)i / (double)steps : 0.5;
        double scale = 1.0 - t * 0.85;

        double offsetFactor = (t - 0.5) * halfW * 0.3 * intensityNorm;
        double offX = ldx * offsetFactor;
        double offY = ldy * offsetFactor;

        double colorT = t * intensityNorm + (1.0 - intensityNorm) * 0.5;
        double r = LerpColorF(shadowR, highlightR, colorT);
        double g = LerpColorF(shadowG, highlightG, colorT);
        double b = LerpColorF(shadowB, highlightB, colorT);

        AIArtHandle copy = nullptr;
        err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, groupArt, &copy);
        if (err || !copy) continue;

        std::vector<AIPathSegment> scaledSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            scaledSegs[s] = origSegs[s];
            scaledSegs[s].p.h   = (AIReal)(cx + (origSegs[s].p.h - cx)   * scale + offX);
            scaledSegs[s].p.v   = (AIReal)(cy + (origSegs[s].p.v - cy)   * scale + offY);
            scaledSegs[s].in.h  = (AIReal)(cx + (origSegs[s].in.h - cx)  * scale + offX);
            scaledSegs[s].in.v  = (AIReal)(cy + (origSegs[s].in.v - cy)  * scale + offY);
            scaledSegs[s].out.h = (AIReal)(cx + (origSegs[s].out.h - cx) * scale + offX);
            scaledSegs[s].out.v = (AIReal)(cy + (origSegs[s].out.v - cy) * scale + offY);
        }

        sAIPath->SetPathSegmentCount(copy, segCount);
        sAIPath->SetPathSegments(copy, 0, segCount, scaledSegs.data());
        sAIPath->SetPathClosed(copy, true);

        AIPathStyle style;
        memset(&style, 0, sizeof(style));
        style.fillPaint = true;
        style.fill.color.kind = kThreeColor;
        style.fill.color.c.rgb.red   = (AIReal)r;
        style.fill.color.c.rgb.green = (AIReal)g;
        style.fill.color.c.rgb.blue  = (AIReal)b;
        style.strokePaint = false;

        sAIPathStyle->SetPathStyle(copy, &style);
        created++;
    }

    fprintf(stderr, "[ShadingModule] Blend: created %d contours in '%s' "
            "(steps=%d, angle=%.0f, intensity=%.0f)\n",
            created, groupName, steps, lightAngle, intensity);
    return created;
}

//========================================================================================
//  Mode B: Mesh Gradient Shading
//========================================================================================

int ShadingModule::ApplyMeshShading(AIArtHandle path, int gridSize,
    double highlightR, double highlightG, double highlightB,
    double shadowR, double shadowG, double shadowB,
    double lightAngle, double intensity)
{
    if (!sAIMesh || !sAIMeshVertex) {
        fprintf(stderr, "[ShadingModule] Mesh mode: AIMeshSuite or "
                "AIMeshVertexIteratorSuite not available\n");
        return 0;
    }

    if (!path || gridSize < 2) return 0;
    if (!sAIArt) return 0;

    if (gridSize > 6) gridSize = 6;
    if (intensity < 0) intensity = 0;
    if (intensity > 100) intensity = 100;

    double intensityNorm = intensity / 100.0;

    AIRealRect bounds;
    ASErr err = sAIArt->GetArtBounds(path, &bounds);
    if (err) {
        fprintf(stderr, "[ShadingModule] Mesh: GetArtBounds failed: %d\n", (int)err);
        return 0;
    }

    double bWidth  = bounds.right - bounds.left;
    double bHeight = bounds.top - bounds.bottom;
    if (bWidth < 1 || bHeight < 1) {
        fprintf(stderr, "[ShadingModule] Mesh: path bounds too small\n");
        return 0;
    }

    AIArtHandle meshArt = nullptr;
    err = sAIArt->NewArt(kMeshArt, kPlaceAbove, path, &meshArt);
    if (err || !meshArt) {
        fprintf(stderr, "[ShadingModule] Mesh: NewArt(kMeshArt) failed: %d\n", (int)err);
        return 0;
    }

    err = sAIMesh->InitCartesian(meshArt, gridSize, gridSize);
    if (err) {
        fprintf(stderr, "[ShadingModule] Mesh: InitCartesian(%d,%d) failed: %d\n",
                gridSize, gridSize, (int)err);
        sAIArt->DisposeArt(meshArt);
        return 0;
    }

    double ldx, ldy;
    LightDirection(lightAngle, ldx, ldy);

    int nodeCount = gridSize + 1;
    int verticesSet = 0;

    for (int i = 0; i < nodeCount; i++) {
        for (int j = 0; j < nodeCount; j++) {
            AIMeshVertexIterator vertex = nullptr;
            err = sAIMesh->GetNode(meshArt, i, j, &vertex);
            if (err || !vertex) continue;

            double u = (double)i / (double)gridSize;
            double v = (double)j / (double)gridSize;

            AIRealPoint pt;
            pt.h = (AIReal)(bounds.left + u * bWidth);
            pt.v = (AIReal)(bounds.bottom + v * bHeight);
            sAIMeshVertex->SetPoint(vertex, &pt);

            double px = u * 2.0 - 1.0;
            double py = v * 2.0 - 1.0;

            double dot = px * ldx + py * ldy;
            double colorT = (dot + 1.0) * 0.5;
            colorT = 0.5 + (colorT - 0.5) * intensityNorm;
            colorT = std::max(0.0, std::min(1.0, colorT));

            double r = LerpColorF(shadowR, highlightR, colorT);
            double g = LerpColorF(shadowG, highlightG, colorT);
            double b = LerpColorF(shadowB, highlightB, colorT);

            AIColor color;
            color.kind = kThreeColor;
            color.c.rgb.red   = (AIReal)r;
            color.c.rgb.green = (AIReal)g;
            color.c.rgb.blue  = (AIReal)b;

            err = sAIMeshVertex->SetColor(vertex, &color);
            if (err) {
                fprintf(stderr, "[ShadingModule] Mesh: SetColor failed at (%d,%d): %d\n",
                        i, j, (int)err);
            }

            sAIMeshVertex->Release(vertex);
            verticesSet++;
        }
    }

    fprintf(stderr, "[ShadingModule] Mesh: %dx%d grid (%d nodes), angle=%.0f, intensity=%.0f\n",
            gridSize, gridSize, verticesSet, lightAngle, intensity);
    return 1;
}
