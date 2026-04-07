//========================================================================================
//  IllTool — Surface Shading (Stage 12)
//  Two shading modes:
//    A) Blend Shading — stacked contours with highlight-to-shadow color ramp
//    B) Mesh Gradient Shading — AIMeshSuite programmatic mesh gradients
//
//  NOTE: This file must be added to the Xcode project's pbxproj
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Helpers
//========================================================================================

/** Linearly interpolate between two 0-1 color components. */
static double LerpColorF(double a, double b, double t)
{
    double val = a + t * (b - a);
    if (val < 0) val = 0;
    if (val > 1) val = 1;
    return val;
}

/** Compute the offset direction from light angle.
    lightAngle is in degrees, 0=right, 90=top (CCW).
    Returns a unit vector (dx, dy) pointing FROM the shadow side TOWARD the light. */
static void LightDirection(double lightAngleDeg, double& dx, double& dy)
{
    double rad = lightAngleDeg * M_PI / 180.0;
    dx = cos(rad);
    dy = sin(rad);
}

/** Get the first selected path art (kPathArt) from the document.
    Returns nullptr if nothing suitable is selected. */
static AIArtHandle GetFirstSelectedPath()
{
    if (!sAIMatchingArt) return nullptr;

    AIMatchingArtSpec spec;
    spec.type = kPathArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;

    // Use isolation-aware matching (declared in IllToolPlugin.h)
    ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
    if (err || numMatches == 0 || !matches) return nullptr;

    AIArtHandle result = (*matches)[0];
    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    return result;
}

//========================================================================================
//  Mode A: Blend Shading — stacked scaled-down contour copies
//
//  Select a closed path, create N scaled/offset copies toward centroid.
//  Each copy gets a color step from shadow→highlight ramp.
//  Light direction determines the offset bias. Intensity controls ramp spread.
//  Everything grouped into a "Shading Group N".
//========================================================================================

int IllToolPlugin::ApplyBlendShading(AIArtHandle path, int steps,
    double highlightR, double highlightG, double highlightB,
    double shadowR, double shadowG, double shadowB,
    double lightAngle, double intensity)
{
    if (!path || steps < 1) return 0;
    if (!sAIArt || !sAIPath || !sAIPathStyle) return 0;

    // Clamp parameters
    if (steps > 15) steps = 15;
    if (intensity < 0) intensity = 0;
    if (intensity > 100) intensity = 100;

    // Intensity controls the ramp spread: 0 = all midtone, 100 = full highlight-to-shadow
    double intensityNorm = intensity / 100.0;

    // Validate source is a closed path
    short artType = 0;
    sAIArt->GetArtType(path, &artType);
    if (artType != kPathArt) {
        fprintf(stderr, "[IllTool Shading] Blend: source is not a path (type=%d)\n", artType);
        return 0;
    }

    AIBoolean closed = false;
    sAIPath->GetPathClosed(path, &closed);
    if (!closed) {
        fprintf(stderr, "[IllTool Shading] Blend: path is not closed\n");
        return 0;
    }

    // Get path bounding box for centroid
    AIRealRect bounds;
    ASErr err = sAIArt->GetArtBounds(path, &bounds);
    if (err) {
        fprintf(stderr, "[IllTool Shading] Blend: GetArtBounds failed: %d\n", (int)err);
        return 0;
    }

    double cx = (bounds.left + bounds.right) / 2.0;
    double cy = (bounds.top + bounds.bottom) / 2.0;
    double halfW = (bounds.right - bounds.left) / 2.0;
    double halfH = (bounds.top - bounds.bottom) / 2.0;
    if (halfW < 1 || halfH < 1) return 0;

    // Light direction for offset
    double ldx, ldy;
    LightDirection(lightAngle, ldx, ldy);

    // Create a group to hold the shading contours
    AIArtHandle groupArt = nullptr;
    err = sAIArt->NewArt(kGroupArt, kPlaceAbove, path, &groupArt);
    if (err || !groupArt) {
        fprintf(stderr, "[IllTool Shading] Blend: failed to create group: %d\n", (int)err);
        return 0;
    }

    // Name the group
    fShadingGroupCounter++;
    char groupName[64];
    snprintf(groupName, sizeof(groupName), "Shading Group %d", fShadingGroupCounter);
    ai::UnicodeString uname(groupName);
    sAIArt->SetArtName(groupArt, uname);

    // Get original path segments
    ai::int16 segCount = 0;
    sAIPath->GetPathSegmentCount(path, &segCount);
    if (segCount < 2) return 0;

    std::vector<AIPathSegment> origSegs(segCount);
    sAIPath->GetPathSegments(path, 0, segCount, origSegs.data());

    int created = 0;

    for (int i = 0; i <= steps; i++) {
        // t goes from 0 (outermost = shadow side) to 1 (innermost = highlight side)
        double t = (steps > 0) ? (double)i / (double)steps : 0.5;

        // Scale factor: outermost is full size, innermost is small
        double scale = 1.0 - t * 0.85;  // scale from 1.0 down to 0.15

        // Offset: light direction biases the position
        // At t=0 (shadow), offset away from light; at t=1 (highlight), offset toward light
        double offsetFactor = (t - 0.5) * halfW * 0.3 * intensityNorm;
        double offX = ldx * offsetFactor;
        double offY = ldy * offsetFactor;

        // Color: ramp from shadow (t=0) to highlight (t=1), modulated by intensity
        double colorT = t * intensityNorm + (1.0 - intensityNorm) * 0.5;
        double r = LerpColorF(shadowR, highlightR, colorT);
        double g = LerpColorF(shadowG, highlightG, colorT);
        double b = LerpColorF(shadowB, highlightB, colorT);

        // Create scaled + offset copy of the path
        AIArtHandle copy = nullptr;
        err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, groupArt, &copy);
        if (err || !copy) continue;

        // Scale segments around center and apply offset
        std::vector<AIPathSegment> scaledSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            scaledSegs[s] = origSegs[s];
            // Scale anchor
            scaledSegs[s].p.h   = (AIReal)(cx + (origSegs[s].p.h - cx)   * scale + offX);
            scaledSegs[s].p.v   = (AIReal)(cy + (origSegs[s].p.v - cy)   * scale + offY);
            // Scale handles
            scaledSegs[s].in.h  = (AIReal)(cx + (origSegs[s].in.h - cx)  * scale + offX);
            scaledSegs[s].in.v  = (AIReal)(cy + (origSegs[s].in.v - cy)  * scale + offY);
            scaledSegs[s].out.h = (AIReal)(cx + (origSegs[s].out.h - cx) * scale + offX);
            scaledSegs[s].out.v = (AIReal)(cy + (origSegs[s].out.v - cy) * scale + offY);
        }

        sAIPath->SetPathSegmentCount(copy, segCount);
        sAIPath->SetPathSegments(copy, 0, segCount, scaledSegs.data());
        sAIPath->SetPathClosed(copy, true);

        // Set fill color (RGB 0-1), no stroke
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

    fprintf(stderr, "[IllTool Shading] Blend: created %d contours in '%s' "
            "(steps=%d, angle=%.0f, intensity=%.0f)\n",
            created, groupName, steps, lightAngle, intensity);
    return created;
}

//========================================================================================
//  Mode B: Mesh Gradient Shading — AIMeshSuite
//
//  Creates a kMeshArt object, initializes a Cartesian grid, positions vertices
//  to match the source path's bounding box, and sets vertex colors based on
//  position relative to the light direction.
//========================================================================================

int IllToolPlugin::ApplyMeshShading(AIArtHandle path, int gridSize,
    double highlightR, double highlightG, double highlightB,
    double shadowR, double shadowG, double shadowB,
    double lightAngle, double intensity)
{
    // Check that mesh suites are available
    if (!sAIMesh || !sAIMeshVertex) {
        fprintf(stderr, "[IllTool Shading] Mesh mode: AIMeshSuite or "
                "AIMeshVertexIteratorSuite not available — "
                "mesh gradient shading requires SDK mesh support\n");
        return 0;
    }

    if (!path || gridSize < 2) return 0;
    if (!sAIArt) return 0;

    // Clamp
    if (gridSize > 6) gridSize = 6;
    if (intensity < 0) intensity = 0;
    if (intensity > 100) intensity = 100;

    double intensityNorm = intensity / 100.0;

    // Get path bounding box for positioning the mesh
    AIRealRect bounds;
    ASErr err = sAIArt->GetArtBounds(path, &bounds);
    if (err) {
        fprintf(stderr, "[IllTool Shading] Mesh: GetArtBounds failed: %d\n", (int)err);
        return 0;
    }

    double bWidth  = bounds.right - bounds.left;
    double bHeight = bounds.top - bounds.bottom;
    if (bWidth < 1 || bHeight < 1) {
        fprintf(stderr, "[IllTool Shading] Mesh: path bounds too small\n");
        return 0;
    }

    // Create mesh art above the path
    AIArtHandle meshArt = nullptr;
    err = sAIArt->NewArt(kMeshArt, kPlaceAbove, path, &meshArt);
    if (err || !meshArt) {
        fprintf(stderr, "[IllTool Shading] Mesh: NewArt(kMeshArt) failed: %d\n", (int)err);
        return 0;
    }

    // Initialize cartesian grid (gridSize patches along each axis)
    err = sAIMesh->InitCartesian(meshArt, gridSize, gridSize);
    if (err) {
        fprintf(stderr, "[IllTool Shading] Mesh: InitCartesian(%d,%d) failed: %d\n",
                gridSize, gridSize, (int)err);
        sAIArt->DisposeArt(meshArt);
        return 0;
    }

    // Light direction vector
    double ldx, ldy;
    LightDirection(lightAngle, ldx, ldy);

    // Number of nodes = gridSize + 1 along each axis
    int nodeCount = gridSize + 1;
    int verticesSet = 0;

    // Position vertices and set colors
    for (int i = 0; i < nodeCount; i++) {
        for (int j = 0; j < nodeCount; j++) {
            AIMeshVertexIterator vertex = nullptr;
            err = sAIMesh->GetNode(meshArt, i, j, &vertex);
            if (err || !vertex) continue;

            // Map (i,j) to bounding box position
            double u = (double)i / (double)gridSize;  // 0..1 across I axis
            double v = (double)j / (double)gridSize;  // 0..1 across J axis

            AIRealPoint pt;
            pt.h = (AIReal)(bounds.left + u * bWidth);
            pt.v = (AIReal)(bounds.bottom + v * bHeight);
            sAIMeshVertex->SetPoint(vertex, &pt);

            // Compute shading: dot product of normalized position with light direction
            // u,v are in [0,1]; map to [-1,1] for the dot product
            double px = u * 2.0 - 1.0;
            double py = v * 2.0 - 1.0;

            // Dot product: positive = on light side (highlight), negative = shadow
            double dot = px * ldx + py * ldy;
            // Map from [-1,1] to [0,1]: 0 = shadow, 1 = highlight
            double colorT = (dot + 1.0) * 0.5;
            // Apply intensity: blend toward midtone at low intensity
            colorT = 0.5 + (colorT - 0.5) * intensityNorm;
            colorT = std::max(0.0, std::min(1.0, colorT));

            // Set vertex color (RGB 0-1)
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
                fprintf(stderr, "[IllTool Shading] Mesh: SetColor failed at (%d,%d): %d\n",
                        i, j, (int)err);
            }

            sAIMeshVertex->Release(vertex);
            verticesSet++;
        }
    }

    fprintf(stderr, "[IllTool Shading] Mesh: %dx%d grid (%d nodes), angle=%.0f, intensity=%.0f\n",
            gridSize, gridSize, verticesSet, lightAngle, intensity);
    return 1;
}

//========================================================================================
//  Dispatch: called from ProcessOperationQueue for ShadingApplyBlend/Mesh
//========================================================================================

void IllToolPlugin::DispatchShadingOp(OpType opType)
{
    // Get the first selected path
    AIArtHandle path = GetFirstSelectedPath();
    if (!path) {
        fprintf(stderr, "[IllTool Shading] No path selected for shading\n");
        return;
    }

    // Read shading parameters from bridge state (colors are doubles 0.0-1.0)
    double hR, hG, hB, sR, sG, sB;
    BridgeGetShadingHighlight(hR, hG, hB);
    BridgeGetShadingShadow(sR, sG, sB);
    double lightAngle = BridgeGetShadingLightAngle();
    double intensity  = BridgeGetShadingIntensity();

    if (opType == OpType::ShadingApplyBlend) {
        int steps = BridgeGetShadingBlendSteps();
        fprintf(stderr, "[IllTool Shading] Applying blend shading: steps=%d, "
                "angle=%.0f, intensity=%.0f\n", steps, lightAngle, intensity);
        int result = ApplyBlendShading(path, steps,
            hR, hG, hB, sR, sG, sB, lightAngle, intensity);
        fprintf(stderr, "[IllTool Shading] Blend result: %d contours\n", result);
    }
    else if (opType == OpType::ShadingApplyMesh) {
        int gridSize = BridgeGetShadingMeshGrid();
        fprintf(stderr, "[IllTool Shading] Applying mesh shading: grid=%d, "
                "angle=%.0f, intensity=%.0f\n", gridSize, lightAngle, intensity);
        int result = ApplyMeshShading(path, gridSize,
            hR, hG, hB, sR, sG, sB, lightAngle, intensity);
        fprintf(stderr, "[IllTool Shading] Mesh result: %d\n", result);
    }
}
