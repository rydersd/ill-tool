//========================================================================================
//  SelectionModule — Polygon Lasso + Smart Select
//  Ported from IllToolLasso.cpp + IllToolSmartSelect.cpp
//========================================================================================

#include "IllustratorSDK.h"
#include "SelectionModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "ShapeUtils.h"
#include "CleanupModule.h"
#include "DrawCommands.h"
#include <cstdio>
#include <cmath>
#include <chrono>
#include <string>
#include <algorithm>

extern IllToolPlugin* gPlugin;

static double CurrentTimeSeconds()
{
    auto now = std::chrono::steady_clock::now();
    auto ms  = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch());
    return (double)ms.count() / 1000.0;
}

//========================================================================================
//  Operation dispatch
//========================================================================================

bool SelectionModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::LassoClose:
            if (fPolygonVertices.size() >= 3) {
                fprintf(stderr, "[SelectionModule] Lasso close — closing polygon with %zu vertices\n",
                        fPolygonVertices.size());
                ExecutePolygonSelection();
                fPolygonVertices.clear();
                UpdatePolygonOverlay();
                InvalidateFullView();
            }
            return true;

        case OpType::LassoClear:
            if (!fPolygonVertices.empty()) {
                fprintf(stderr, "[SelectionModule] Lasso clear — discarding %zu vertices\n",
                        fPolygonVertices.size());
                fPolygonVertices.clear();
                UpdatePolygonOverlay();
                InvalidateFullView();
            }
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  Mouse events — Polygon Lasso (click-to-add-vertex, double-click-to-close)
//========================================================================================

bool SelectionModule::HandleMouseDown(AIToolMessage* msg)
{
    BridgeToolMode mode = BridgeGetToolMode();

    if (mode == BridgeToolMode::Smart) {
        // Smart Select mode: hit-test under cursor, compute signature, select matches
        try {
            AIRealPoint clickPt = msg->cursor;
            fprintf(stderr, "[SelectionModule Smart] Click at (%.1f, %.1f)\n", clickPt.h, clickPt.v);

            if (!sAIHitTest) {
                fprintf(stderr, "[SelectionModule Smart] AIHitTestSuite not available\n");
                return true;
            }

            AIHitRef hitRef = NULL;
            ASErr hitErr = sAIHitTest->HitTest(NULL, &clickPt, kAllHitRequest, &hitRef);
            if (hitErr == kNoErr && hitRef && sAIHitTest->IsHit(hitRef)) {
                AIArtHandle hitArt = sAIHitTest->GetArt(hitRef);
                if (hitArt) {
                    short artType = kUnknownArt;
                    sAIArt->GetArtType(hitArt, &artType);
                    if (artType == kPathArt) {
                        BoundarySignature sig = ComputeSignature(hitArt);
                        fprintf(stderr, "[SelectionModule Smart] Hit: path=%p, Signature: len=%.1f curv=%.3f segs=%d closed=%s\n",
                                (void*)hitArt, sig.totalLength, sig.avgCurvature,
                                sig.segmentCount, sig.isClosed ? "yes" : "no");
                        double threshold = BridgeGetSmartThreshold();
                        SelectMatchingPaths(sig, threshold, hitArt);
                    } else {
                        fprintf(stderr, "[SelectionModule Smart] Hit art is not a path (type=%d)\n", artType);
                    }
                }
                sAIHitTest->Release(hitRef);
            } else {
                fprintf(stderr, "[SelectionModule Smart] No hit at click location\n");
                if (hitRef) sAIHitTest->Release(hitRef);
            }
        }
        catch (...) {
            fprintf(stderr, "[SelectionModule Smart] HandleMouseDown error\n");
        }
        return true;
    }

    // If CleanupModule is in working mode, don't start a new lasso — defer to handle editing
    if (gPlugin) {
        auto* cleanup = gPlugin->GetModule<CleanupModule>();
        if (cleanup && cleanup->IsInWorkingMode()) return false;
    }

    // Lasso mode: click to add vertex, drag existing vertex, double-click to close
    try {
        AIRealPoint artPt = msg->cursor;

        // Double-click detection
        double now = CurrentTimeSeconds();

        bool isDoubleClick = (now - fLastClickTime < kDoubleClickThreshold)
                          && !fPolygonVertices.empty();
        fLastClickTime = now;

        // Hit-test existing vertices FIRST — prevents accidental double-click close
        if (!fPolygonVertices.empty() && sAIDocumentView) {
            for (int v = 0; v < (int)fPolygonVertices.size(); v++) {
                AIPoint va, vb;
                if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &va) == kNoErr &&
                    sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPolygonVertices[v], &vb) == kNoErr) {
                    double dx = va.h - vb.h, dy = va.v - vb.v;
                    if (sqrt(dx * dx + dy * dy) <= 7.0) {
                        fDragVertexIdx = v;
                        fLastClickTime = 0;  // reset double-click timer
                        fprintf(stderr, "[SelectionModule] Drag vertex %d\n", v);
                        return true;
                    }
                }
            }
        }

        // THEN double-click detection (only if no vertex was hit)
        if (isDoubleClick && fPolygonVertices.size() >= 3) {
            fprintf(stderr, "[SelectionModule] Double-click close, %zu vertices\n",
                    fPolygonVertices.size());
            ExecutePolygonSelection();
            fPolygonVertices.clear();
            fDragVertexIdx = -1;
            fHoverVertexIdx = -1;
            UpdatePolygonOverlay();
            InvalidateFullView();
            return true;
        }

        // No vertex hit — add new vertex
        fPolygonVertices.push_back(artPt);
        fLastCursorPos = artPt;
        fprintf(stderr, "[SelectionModule] Added vertex %zu at (%.1f, %.1f)\n",
                fPolygonVertices.size(), artPt.h, artPt.v);
        UpdatePolygonOverlay();
    }
    catch (...) {
        fprintf(stderr, "[SelectionModule] HandleMouseDown error\n");
    }
    return true;
}

bool SelectionModule::HandleMouseDrag(AIToolMessage* msg)
{
    if (gPlugin) {
        auto* cleanup = gPlugin->GetModule<CleanupModule>();
        if (cleanup && cleanup->IsInWorkingMode()) return false;
    }

    // Vertex drag
    if (fDragVertexIdx >= 0 && fDragVertexIdx < (int)fPolygonVertices.size()) {
        fPolygonVertices[fDragVertexIdx] = msg->cursor;
        fLastCursorPos = msg->cursor;
        UpdatePolygonOverlay();
        return true;
    }

    fLastCursorPos = msg->cursor;
    UpdatePolygonOverlay();
    return true;
}

bool SelectionModule::HandleMouseUp(AIToolMessage* msg)
{
    if (gPlugin) {
        auto* cleanup = gPlugin->GetModule<CleanupModule>();
        if (cleanup && cleanup->IsInWorkingMode()) return false;
    }

    if (fDragVertexIdx >= 0) {
        fprintf(stderr, "[SelectionModule] Drag vertex %d end\n", fDragVertexIdx);
        fDragVertexIdx = -1;
    }

    fLastCursorPos = msg->cursor;
    UpdatePolygonOverlay();
    return true;
}

//========================================================================================
//  Overlay drawing
//========================================================================================

void SelectionModule::DrawOverlay(AIAnnotatorMessage* msg)
{
    // Lasso overlay is drawn via DrawCommands (UpdatePolygonOverlay pushes them)
    // No direct annotator drawing needed — the annotator renders DrawCommands centrally
}

void SelectionModule::UpdateHoverVertex(AIRealPoint artPt)
{
    int prev = fHoverVertexIdx;
    fHoverVertexIdx = -1;

    if (!fPolygonVertices.empty() && sAIDocumentView) {
        for (int v = 0; v < (int)fPolygonVertices.size(); v++) {
            AIPoint va, vb;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &va) == kNoErr &&
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &fPolygonVertices[v], &vb) == kNoErr) {
                double dx = va.h - vb.h, dy = va.v - vb.v;
                if (sqrt(dx * dx + dy * dy) <= 7.0) {
                    fHoverVertexIdx = v;
                    break;
                }
            }
        }
    }

    if (fHoverVertexIdx != prev) {
        UpdatePolygonOverlay();
        InvalidateFullView();
    }
}

void SelectionModule::OnDocumentChanged()
{
    fPolygonVertices.clear();
    fLastCursorPos = {0, 0};
    fLastClickTime = 0;
}

//========================================================================================
//  Polygon overlay — builds draw commands for the polygon visualization
//========================================================================================

void SelectionModule::UpdatePolygonOverlay()
{
    std::vector<DrawCommand> commands = GetDrawCommands();

    // Remove any previous lasso overlay commands
    commands.erase(
        std::remove_if(commands.begin(), commands.end(),
            [](const DrawCommand& c) { return c.id.find("_lasso_") == 0; }),
        commands.end()
    );

    // Colors
    Color4 darkCyan    = {0.0, 0.6, 0.7, 1.0};
    Color4 lightCyan   = {0.4, 0.85, 0.95, 0.8};
    Color4 whiteBG     = {1.0, 1.0, 1.0, 0.35};
    Color4 rubberCyan  = {0.4, 0.85, 0.95, 0.5};
    Color4 rubberWhite = {1.0, 1.0, 1.0, 0.2};

    auto addDualLine = [&](const std::string& idBase, Point2D p1, Point2D p2,
                           Color4 bgColor, Color4 fgColor, bool dashed) {
        DrawCommand bg;
        bg.type = DrawCommandType::Line;
        bg.id = idBase + "_bg";
        bg.points = {p1, p2};
        bg.strokeColor = bgColor;
        bg.strokeWidth = 2.0;
        bg.dashed = false;
        commands.push_back(bg);

        DrawCommand fg;
        fg.type = DrawCommandType::Line;
        fg.id = idBase + "_fg";
        fg.points = {p1, p2};
        fg.strokeColor = fgColor;
        fg.strokeWidth = 1.0;
        fg.dashed = dashed;
        commands.push_back(fg);
    };

    // Dual lines between vertices
    for (size_t i = 1; i < fPolygonVertices.size(); i++) {
        Point2D p1 = {fPolygonVertices[i-1].h, fPolygonVertices[i-1].v};
        Point2D p2 = {fPolygonVertices[i].h, fPolygonVertices[i].v};
        addDualLine("_lasso_line_" + std::to_string(i), p1, p2, whiteBG, lightCyan, true);
    }

    // Rubber band from last vertex to cursor
    if (!fPolygonVertices.empty()) {
        Point2D pLast = {fPolygonVertices.back().h, fPolygonVertices.back().v};
        Point2D pCur  = {fLastCursorPos.h, fLastCursorPos.v};
        addDualLine("_lasso_rubber", pLast, pCur, rubberWhite, rubberCyan, true);

        if (fPolygonVertices.size() >= 3) {
            Point2D pFirst = {fPolygonVertices.front().h, fPolygonVertices.front().v};
            addDualLine("_lasso_closing", pLast, pFirst, rubberWhite, rubberCyan, true);
        }
    }

    // Filled box handles at vertices — hover highlighted
    Color4 hoverYellow = {1.0, 0.9, 0.3, 1.0};
    Color4 dragOrange  = {1.0, 0.6, 0.1, 1.0};
    for (size_t i = 0; i < fPolygonVertices.size(); i++) {
        bool isHovered = (fHoverVertexIdx == (int)i);
        bool isDragged = (fDragVertexIdx == (int)i);
        DrawCommand handle;
        handle.type = DrawCommandType::Rect;
        handle.id = "_lasso_handle_" + std::to_string(i);
        handle.center = {fPolygonVertices[i].h, fPolygonVertices[i].v};
        handle.width = (isHovered || isDragged) ? 9.0 : 6.0;
        handle.height = (isHovered || isDragged) ? 9.0 : 6.0;
        handle.strokeColor = darkCyan;
        handle.fillColor = isDragged ? dragOrange : (isHovered ? hoverYellow : darkCyan);
        handle.strokeWidth = 1.0;
        handle.filled = true;
        handle.stroked = true;
        commands.push_back(handle);
    }

    UpdateDrawCommands(std::move(commands));
    InvalidateFullView();
}

//========================================================================================
//  PointInPolygon — ray casting algorithm
//========================================================================================

bool SelectionModule::PointInPolygon(const AIRealPoint& pt,
                                      const std::vector<AIRealPoint>& polygon)
{
    bool inside = false;
    size_t n = polygon.size();
    for (size_t i = 0, j = n - 1; i < n; j = i++) {
        double xi = polygon[i].h, yi = polygon[i].v;
        double xj = polygon[j].h, yj = polygon[j].v;

        bool intersect = ((yi > pt.v) != (yj > pt.v)) &&
                          (pt.h < (xj - xi) * (pt.v - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

//========================================================================================
//  ExecutePolygonSelection — select segments inside polygon lasso
//========================================================================================

void SelectionModule::ExecutePolygonSelection()
{
    fprintf(stderr, "[SelectionModule] ExecutePolygonSelection: enter, polygon vertices=%zu\n",
            fPolygonVertices.size());
    if (fPolygonVertices.size() < 3) {
        fprintf(stderr, "[SelectionModule] ExecutePolygonSelection: <3 vertices, returning early\n");
        return;
    }

    ASErr result = kNoErr;
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        fprintf(stderr, "[SelectionModule] GetMatchingArtIsolationAware: err=%d, numMatches=%d\n",
                (int)result, (int)numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        // When Add to Selection is OFF, deselect all segments first
        bool addToSelection = BridgeGetAddToSelection();
        if (!addToSelection) {
            for (ai::int32 d = 0; d < numMatches; d++) {
                AIArtHandle dArt = (*matches)[d];
                ai::int32 dAttrs = 0;
                sAIArt->GetArtUserAttr(dArt, kArtLocked | kArtHidden, &dAttrs);
                if (dAttrs & (kArtLocked | kArtHidden)) continue;
                ai::int16 dSc = 0;
                sAIPath->GetPathSegmentCount(dArt, &dSc);
                for (ai::int16 ds = 0; ds < dSc; ds++) {
                    sAIPath->SetPathSegmentSelected(dArt, ds, kSegmentNotSelected);
                }
            }
            fprintf(stderr, "[SelectionModule] Deselected all segments (Add to Selection: OFF)\n");
        }

        int selectedCount = 0;
        int skippedLocked = 0;
        int skippedEmpty = 0;
        int totalSegsTested = 0;
        int totalInsidePolygon = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) {
                skippedEmpty++;
                continue;
            }

            for (ai::int16 s = 0; s < segCount; s++) {
                AIPathSegment seg;
                result = sAIPath->GetPathSegments(art, s, 1, &seg);
                if (result != kNoErr) continue;

                totalSegsTested++;

                if (PointInPolygon(seg.p, fPolygonVertices)) {
                    totalInsidePolygon++;
                    result = sAIPath->SetPathSegmentSelected(art, s, kSegmentPointSelected);
                    if (result == kNoErr) selectedCount++;
                }
            }
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        fprintf(stderr, "[SelectionModule] ExecutePolygonSelection SUMMARY:\n");
        fprintf(stderr, "[SelectionModule]   paths matched:     %d\n", (int)numMatches);
        fprintf(stderr, "[SelectionModule]   skipped locked:    %d\n", skippedLocked);
        fprintf(stderr, "[SelectionModule]   skipped empty:     %d\n", skippedEmpty);
        fprintf(stderr, "[SelectionModule]   segments tested:   %d\n", totalSegsTested);
        fprintf(stderr, "[SelectionModule]   inside polygon:    %d\n", totalInsidePolygon);
        fprintf(stderr, "[SelectionModule]   selected count:    %d\n", selectedCount);

        // If we selected anything and NOT already in working mode,
        // enter working mode (duplicate, dim, isolate).
        // After lasso selection, just log. User clicks "Average Selection" to cleanup.
        // Do NOT auto-enter working mode — that duplicates paths without averaging.
        if (selectedCount > 0) {
            fprintf(stderr, "[SelectionModule] Lasso selected %d paths — ready for Average Selection\n",
                    selectedCount);
        }

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[SelectionModule] ExecutePolygonSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[SelectionModule] ExecutePolygonSelection unknown error\n");
    }
}

//========================================================================================
//  Smart Select — Boundary Signature Matching (Stage 9)
//========================================================================================

SelectionModule::BoundarySignature SelectionModule::ComputeSignature(AIArtHandle path)
{
    BoundarySignature sig = {};

    if (!path || !sAIPath) return sig;

    try {
        ai::int16 segCount = 0;
        ASErr err = sAIPath->GetPathSegmentCount(path, &segCount);
        if (err != kNoErr || segCount == 0) return sig;
        sig.segmentCount = segCount;

        AIBoolean closed = false;
        sAIPath->GetPathClosed(path, &closed);
        sig.isClosed = (closed != 0);

        std::vector<AIPathSegment> segs(segCount);
        err = sAIPath->GetPathSegments(path, 0, segCount, segs.data());
        if (err != kNoErr) return sig;

        // Compute total path length using MeasureSegments
        ai::int16 numPieces = sig.isClosed
                            ? segCount
                            : (segCount > 1 ? (ai::int16)(segCount - 1) : (ai::int16)0);
        if (numPieces > 0) {
            std::vector<AIReal> pieceLengths(numPieces);
            std::vector<AIReal> accumLengths(numPieces);
            err = sAIPath->MeasureSegments(path, 0, numPieces,
                                           pieceLengths.data(), accumLengths.data());
            if (err == kNoErr) {
                sig.totalLength = (double)accumLengths[numPieces - 1]
                                + (double)pieceLengths[numPieces - 1];
            }
        }

        // Fallback: sum straight-line distances
        if (sig.totalLength <= 0.0 && segCount > 1) {
            double lenSum = 0.0;
            for (ai::int16 i = 1; i < segCount; i++) {
                double dx = (double)(segs[i].p.h - segs[i-1].p.h);
                double dy = (double)(segs[i].p.v - segs[i-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            if (sig.isClosed && segCount >= 2) {
                double dx = (double)(segs[0].p.h - segs[segCount-1].p.h);
                double dy = (double)(segs[0].p.v - segs[segCount-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            sig.totalLength = lenSum;
        }

        // Average curvature
        if (segCount >= 3 && sig.totalLength > 0.0) {
            double angleChangeSum = 0.0;
            int numInteriorPts = sig.isClosed ? segCount : (segCount - 2);
            for (int ci = 0; ci < numInteriorPts; ci++) {
                int idx  = sig.isClosed ? ci : (ci + 1);
                int prev = (idx - 1 + segCount) % segCount;
                int next = (idx + 1) % segCount;

                double dx1 = (double)(segs[idx].p.h - segs[prev].p.h);
                double dy1 = (double)(segs[idx].p.v - segs[prev].p.v);
                double dx2 = (double)(segs[next].p.h - segs[idx].p.h);
                double dy2 = (double)(segs[next].p.v - segs[idx].p.v);

                double a1 = std::atan2(dy1, dx1);
                double a2 = std::atan2(dy2, dx2);
                double ad = a2 - a1;
                while (ad >  M_PI) ad -= 2.0 * M_PI;
                while (ad < -M_PI) ad += 2.0 * M_PI;
                angleChangeSum += std::fabs(ad);
            }
            sig.avgCurvature = angleChangeSum / sig.totalLength;
        }

        // Start and end tangent directions
        if (segCount >= 2) {
            double sx = (double)(segs[0].out.h - segs[0].p.h);
            double sy = (double)(segs[0].out.v - segs[0].p.v);
            if (std::fabs(sx) < 0.001 && std::fabs(sy) < 0.001) {
                sx = (double)(segs[1].p.h - segs[0].p.h);
                sy = (double)(segs[1].p.v - segs[0].p.v);
            }
            sig.startAngle = std::atan2(sy, sx);

            int last = segCount - 1;
            double ex = (double)(segs[last].p.h - segs[last].in.h);
            double ey = (double)(segs[last].p.v - segs[last].in.v);
            if (std::fabs(ex) < 0.001 && std::fabs(ey) < 0.001) {
                ex = (double)(segs[last].p.h - segs[last-1].p.h);
                ey = (double)(segs[last].p.v - segs[last-1].p.v);
            }
            sig.endAngle = std::atan2(ey, ex);
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[SelectionModule Smart] ComputeSignature error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[SelectionModule Smart] ComputeSignature unknown error\n");
    }
    return sig;
}

void SelectionModule::SelectMatchingPaths(const BoundarySignature& refSig,
                                           double thresholdPct,
                                           AIArtHandle hitArt)
{
    try {
        double t = thresholdPct / 100.0;
        double lengthTol   = 0.05 + t * 0.75;
        double curvTol     = 0.10 + t * 1.90;
        int    maxSegDelta = 1 + (int)(t * 19.0);

        fprintf(stderr, "[SelectionModule Smart] Matching: threshold=%.0f%% lenTol=%.0f%% "
                "curvTol=%.0f%% segDelta=%d\n",
                thresholdPct, lengthTol * 100.0, curvTol * 100.0, maxSegDelta);

        AIMatchingArtSpec spec;
        spec.type = kPathArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err != kNoErr || numMatches == 0) {
            fprintf(stderr, "[SelectionModule Smart] No paths in document\n");
            return;
        }

        // Deselect all currently selected art
        {
            AIMatchingArtSpec selSpec;
            selSpec.type = kAnyArt;
            selSpec.whichAttr = kArtSelected;
            selSpec.attr = kArtSelected;
            AIArtHandle** selMatches = nullptr;
            ai::int32 numSelMatches = 0;
            ASErr selErr = sAIMatchingArt->GetMatchingArt(&selSpec, 1,
                                                          &selMatches, &numSelMatches);
            if (selErr == kNoErr && numSelMatches > 0) {
                for (ai::int32 si = 0; si < numSelMatches; si++) {
                    sAIArt->SetArtUserAttr((*selMatches)[si], kArtSelected, 0);
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)selMatches);
            }
        }

        int matchCount = 0;
        int skippedLocked = 0;
        int skippedMismatch = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            // Always select the originally clicked path
            if (art == hitArt) {
                sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
                matchCount++;
                continue;
            }

            BoundarySignature candSig = ComputeSignature(art);

            // Criteria 1: same open/closed status
            if (candSig.isClosed != refSig.isClosed) {
                skippedMismatch++;
                continue;
            }

            // Criteria 2: segment count within delta
            int segDiff = std::abs(candSig.segmentCount - refSig.segmentCount);
            if (segDiff > maxSegDelta) {
                skippedMismatch++;
                continue;
            }

            // Criteria 3: total length within tolerance
            if (refSig.totalLength > 0.001 || candSig.totalLength > 0.001) {
                double maxLen = std::max(refSig.totalLength, candSig.totalLength);
                if (maxLen > 0.001) {
                    double lenDiff = std::fabs(candSig.totalLength - refSig.totalLength)
                                   / maxLen;
                    if (lenDiff > lengthTol) {
                        skippedMismatch++;
                        continue;
                    }
                }
            }

            // Criteria 4: average curvature within tolerance
            double maxCurv = std::max(refSig.avgCurvature, candSig.avgCurvature);
            if (maxCurv > 0.0001) {
                double curvDiff = std::fabs(candSig.avgCurvature - refSig.avgCurvature)
                                / maxCurv;
                if (curvDiff > curvTol) {
                    skippedMismatch++;
                    continue;
                }
            }

            sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
            matchCount++;
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        fprintf(stderr, "[SelectionModule Smart] Matches: %d (skipped: %d locked, "
                "%d mismatch, %d total)\n",
                matchCount, skippedLocked, skippedMismatch, (int)numMatches);

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[SelectionModule Smart] SelectMatchingPaths error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[SelectionModule Smart] SelectMatchingPaths unknown error\n");
    }
}
