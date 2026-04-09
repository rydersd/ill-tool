//========================================================================================
//
//  TransformModule — Batch transform selected shapes
//
//  Applies scale and/or rotation to every selected path art.
//  Reads parameters from bridge state (set by the TransformPanelController).
//  Transforms are applied at the segment level (no AITransformArtSuite dependency).
//
//========================================================================================

#include "TransformModule.h"
#include "IllToolPlugin.h"
#include <cstdio>
#include <cmath>
#include <vector>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

//========================================================================================
//  HandleOp — route TransformApply to ApplyTransform()
//========================================================================================

bool TransformModule::HandleOp(const PluginOp& op)
{
    if (op.type == OpType::TransformApply) {
        ApplyTransform();
        return true;
    }
    return false;
}

//========================================================================================
//  TransformPoint — apply scale + rotate around a center point
//========================================================================================

void TransformModule::TransformPoint(AIRealPoint& pt,
                                     double cx, double cy,
                                     double scaleX, double scaleY,
                                     double cosA, double sinA)
{
    // Translate to origin
    double dx = pt.h - cx;
    double dy = pt.v - cy;

    // Scale
    dx *= scaleX;
    dy *= scaleY;

    // Rotate
    double rx = dx * cosA - dy * sinA;
    double ry = dx * sinA + dy * cosA;

    // Translate back
    pt.h = (AIReal)(cx + rx);
    pt.v = (AIReal)(cy + ry);
}

//========================================================================================
//  ApplyTransform — batch transform all selected path art
//========================================================================================

void TransformModule::ApplyTransform()
{
    fprintf(stderr, "[TransformModule] ApplyTransform: begin\n");

    // Read bridge state
    double widthVal    = BridgeGetTransformWidth();
    double heightVal   = BridgeGetTransformHeight();
    double rotationVal = BridgeGetTransformRotation();
    int    mode        = BridgeGetTransformMode();      // 0=absolute, 1=relative
    bool   randomize   = BridgeGetTransformRandom();
    int    unitSize    = BridgeGetTransformUnitSize();   // 0=px, 1=%
    int    unitRot     = BridgeGetTransformUnitRotation(); // 0=degrees, 1=%

    fprintf(stderr, "[TransformModule] width=%.1f height=%.1f rot=%.1f mode=%d random=%d unitSize=%d unitRot=%d\n",
            widthVal, heightVal, rotationVal, mode, (int)randomize, unitSize, unitRot);

    // Get all selected path art
    AIMatchingArtSpec spec;
    spec.type = kPathArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0) {
        fprintf(stderr, "[TransformModule] No selected paths found\n");
        return;
    }

    fprintf(stderr, "[TransformModule] Found %d selected paths\n", (int)numMatches);

    int transformedCount = 0;

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        // Get path bounds for center + current size
        AIRealRect bounds;
        err = sAIArt->GetArtBounds(art, &bounds);
        if (err != kNoErr) continue;

        double cx = (bounds.left + bounds.right) / 2.0;
        double cy = (bounds.top + bounds.bottom) / 2.0;
        // Note: In AI coordinate system, top > bottom (Y increases upward)
        double currentW = bounds.right - bounds.left;
        double currentH = bounds.top - bounds.bottom;

        if (currentW < 0.001 && currentH < 0.001) continue;  // degenerate

        // Compute scale factors
        double scaleX = 1.0;
        double scaleY = 1.0;

        if (mode == 0) {
            // Absolute mode
            if (unitSize == 0) {
                // px: targetSize = widthVal, so scale = target / current
                if (widthVal > 0 && currentW > 0.001)
                    scaleX = widthVal / currentW;
                if (heightVal > 0 && currentH > 0.001)
                    scaleY = heightVal / currentH;
            } else {
                // %: treat value as percentage of current size
                // e.g., 150% means scale to 150% of current = 1.5x
                if (widthVal > 0)
                    scaleX = widthVal / 100.0;
                if (heightVal > 0)
                    scaleY = heightVal / 100.0;
            }
        } else {
            // Relative mode
            if (unitSize == 0) {
                // px: delta in points — scale = 1 + (delta / currentSize)
                if (currentW > 0.001)
                    scaleX = 1.0 + (widthVal / currentW);
                if (currentH > 0.001)
                    scaleY = 1.0 + (heightVal / currentH);
            } else {
                // %: delta as percentage — e.g., +20% means 1.2x
                scaleX = 1.0 + (widthVal / 100.0);
                scaleY = 1.0 + (heightVal / 100.0);
            }
        }

        // Compute rotation angle in radians
        double angleDeg = 0;
        if (mode == 0) {
            // Absolute mode: target angle
            if (unitRot == 0) {
                angleDeg = rotationVal;  // degrees
            } else {
                // %: treat as percentage of 360
                angleDeg = rotationVal / 100.0 * 360.0;
            }
        } else {
            // Relative mode: delta angle
            if (unitRot == 0) {
                angleDeg = rotationVal;  // degrees delta
            } else {
                // %: percentage of 360
                angleDeg = rotationVal / 100.0 * 360.0;
            }
        }

        double angleRad = angleDeg * M_PI / 180.0;

        // Aspect ratio lock: use uniform scale factor
        bool lockAspect = BridgeGetTransformLockAspectRatio();
        if (lockAspect) {
            double uniformScale = std::min(scaleX, scaleY);
            scaleX = uniformScale;
            scaleY = uniformScale;
        }

        // Apply random variance (+-20%) if enabled
        if (randomize) {
            double randFactorR = 0.8 + 0.4 * (arc4random() / (double)UINT32_MAX);
            if (lockAspect) {
                // Single random factor for uniform scale
                double randFactorS = 0.8 + 0.4 * (arc4random() / (double)UINT32_MAX);
                scaleX *= randFactorS;
                scaleY *= randFactorS;
            } else {
                double randFactorX = 0.8 + 0.4 * (arc4random() / (double)UINT32_MAX);
                double randFactorY = 0.8 + 0.4 * (arc4random() / (double)UINT32_MAX);
                scaleX *= randFactorX;
                scaleY *= randFactorY;
            }
            angleRad *= randFactorR;
        }

        // Skip identity transforms
        if (fabs(scaleX - 1.0) < 0.001 && fabs(scaleY - 1.0) < 0.001 && fabs(angleRad) < 0.001)
            continue;

        double cosA = cos(angleRad);
        double sinA = sin(angleRad);

        // Get all path segments
        ai::int16 segCount = 0;
        err = sAIPath->GetPathSegmentCount(art, &segCount);
        if (err != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        err = sAIPath->GetPathSegments(art, 0, segCount, segs.data());
        if (err != kNoErr) continue;

        // Transform each segment's anchor, in-handle, and out-handle
        for (int s = 0; s < segCount; s++) {
            TransformPoint(segs[s].p,   cx, cy, scaleX, scaleY, cosA, sinA);
            TransformPoint(segs[s].in,  cx, cy, scaleX, scaleY, cosA, sinA);
            TransformPoint(segs[s].out, cx, cy, scaleX, scaleY, cosA, sinA);
        }

        // Write transformed segments back
        err = sAIPath->SetPathSegments(art, 0, segCount, segs.data());
        if (err == kNoErr) {
            transformedCount++;
        }
    }

    // Free matched art array
    if (matches && *matches) {
        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    }

    fprintf(stderr, "[TransformModule] Transformed %d/%d paths\n",
            transformedCount, (int)numMatches);

    // Redraw document
    sAIDocument->RedrawDocument();
}
