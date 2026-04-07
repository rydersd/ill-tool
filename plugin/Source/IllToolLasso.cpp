//========================================================================================
//  IllTool — Polygon Lasso
//  Extracted from IllToolPlugin.cpp for modularity.
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include <cstdio>
#include <cmath>
#include <string>
#include <algorithm>

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Polygon lasso helpers
//========================================================================================

/*
    UpdatePolygonOverlay — builds draw commands for the polygon visualization
    and merges them with any existing HTTP draw commands.
*/
void IllToolPlugin::UpdatePolygonOverlay()
{
    // Get current HTTP draw commands as the base
    std::vector<DrawCommand> commands = GetDrawCommands();

    // Remove any previous lasso overlay commands (identified by id prefix)
    commands.erase(
        std::remove_if(commands.begin(), commands.end(),
            [](const DrawCommand& c) { return c.id.find("_lasso_") == 0; }),
        commands.end()
    );

    // Colors
    Color4 darkCyan    = {0.0, 0.6, 0.7, 1.0};     // filled handles
    Color4 lightCyan   = {0.4, 0.85, 0.95, 0.8};   // dashed lines on top
    Color4 whiteBG     = {1.0, 1.0, 1.0, 0.35};    // semi-opaque white underneath
    Color4 rubberCyan  = {0.4, 0.85, 0.95, 0.5};
    Color4 rubberWhite = {1.0, 1.0, 1.0, 0.2};

    // Helper lambda to add a dual-line (white bg + cyan dashed on top)
    auto addDualLine = [&](const std::string& idBase, Point2D p1, Point2D p2,
                           Color4 bgColor, Color4 fgColor, bool dashed) {
        // Layer 1: semi-opaque white background line
        DrawCommand bg;
        bg.type = DrawCommandType::Line;
        bg.id = idBase + "_bg";
        bg.points = {p1, p2};
        bg.strokeColor = bgColor;
        bg.strokeWidth = 2.0;
        bg.dashed = false;
        commands.push_back(bg);
        // Layer 2: cyan dashed on top
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

        // Closing line preview (last vertex -> first vertex)
        if (fPolygonVertices.size() >= 3) {
            Point2D pFirst = {fPolygonVertices.front().h, fPolygonVertices.front().v};
            addDualLine("_lasso_closing", pLast, pFirst, rubberWhite, rubberCyan, true);
        }
    }

    // Filled box handles at vertices (20% bigger: 6x6 instead of 5x5)
    for (size_t i = 0; i < fPolygonVertices.size(); i++) {
        DrawCommand handle;
        handle.type = DrawCommandType::Rect;
        handle.id = "_lasso_handle_" + std::to_string(i);
        handle.center = {fPolygonVertices[i].h, fPolygonVertices[i].v};
        handle.width = 6.0;
        handle.height = 6.0;
        handle.strokeColor = darkCyan;
        handle.fillColor = darkCyan;
        handle.strokeWidth = 1.0;
        handle.filled = true;
        handle.stroked = true;
        commands.push_back(handle);
    }

    UpdateDrawCommands(std::move(commands));
    InvalidateFullView();
}

/*
    PointInPolygon — ray casting algorithm.
    Returns true if pt is inside the polygon defined by the given vertices.
*/
bool IllToolPlugin::PointInPolygon(const AIRealPoint& pt,
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

/*
    ExecutePolygonSelection — select path segments whose anchor points
    fall inside the polygon lasso.
*/
void IllToolPlugin::ExecutePolygonSelection()
{
    fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: enter, polygon vertices=%zu\n",
            fPolygonVertices.size());
    if (fPolygonVertices.size() < 3) {
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: <3 vertices, returning early\n");
        return;
    }

    ASErr result = kNoErr;
    try {
        // Get all path art (isolation-aware — scoped to working group if active)
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: calling GetMatchingArtIsolationAware\n");
        result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: GetMatchingArtIsolationAware returned err=%d, numMatches=%d\n",
                (int)result, (int)numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: no path art found — aborting\n");
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        fprintf(stderr, "[IllTool] Testing %d paths against polygon\n", (int)numMatches);

        // Gap 4: When Add to Selection is OFF, deselect all segments first
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
            fprintf(stderr, "[IllTool] Deselected all segments (Add to Selection: OFF)\n");
        } else {
            fprintf(stderr, "[IllTool] Keeping existing selection (Add to Selection: ON)\n");
        }

        int selectedCount = 0;
        int skippedLocked = 0;
        int skippedEmpty = 0;
        int totalSegsTested = 0;
        int totalInsidePolygon = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            // Get segment count
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

                // Test if anchor point is inside the polygon
                if (PointInPolygon(seg.p, fPolygonVertices)) {
                    totalInsidePolygon++;
                    // Select this segment's anchor point
                    result = sAIPath->SetPathSegmentSelected(art, s, kSegmentPointSelected);
                    if (result == kNoErr) {
                        selectedCount++;
                    } else {
                        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: SetPathSegmentSelected FAILED for path %d seg %d, err=%d\n",
                                (int)i, (int)s, (int)result);
                    }
                }
            }
        }

        // Free the matches array (SDK allocates it; we must dispose)
        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection SUMMARY:\n");
        fprintf(stderr, "[IllTool DEBUG]   paths matched:     %d\n", (int)numMatches);
        fprintf(stderr, "[IllTool DEBUG]   skipped locked:    %d\n", skippedLocked);
        fprintf(stderr, "[IllTool DEBUG]   skipped empty:     %d\n", skippedEmpty);
        fprintf(stderr, "[IllTool DEBUG]   segments tested:   %d\n", totalSegsTested);
        fprintf(stderr, "[IllTool DEBUG]   inside polygon:    %d\n", totalInsidePolygon);
        fprintf(stderr, "[IllTool DEBUG]   selected count:    %d\n", selectedCount);
        fprintf(stderr, "[IllTool DEBUG]   fInWorkingMode:    %s\n", fInWorkingMode ? "true" : "false");

        // If we selected anything and NOT already in working mode,
        // enter working mode (duplicate, dim, isolate).
        // If already in working mode, the lasso is just selecting within
        // the isolated group — no need to re-enter.
        if (selectedCount > 0 && !fInWorkingMode) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: calling EnterWorkingMode\n");
            EnterWorkingMode();
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: EnterWorkingMode returned\n");
        } else if (selectedCount == 0) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: nothing selected, NOT entering working mode\n");
        } else {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: already in working mode, NOT re-entering\n");
        }

        // Redraw so selection is visible
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: RedrawDocument called, done\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] ExecutePolygonSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] ExecutePolygonSelection unknown error\n");
    }
}

/*
    InvalidateFullView — invalidate the entire document view.
*/
void IllToolPlugin::InvalidateFullView()
{
    try {
        AIRealRect viewBounds = {0, 0, 0, 0};
        ASErr result = sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
        if (result == kNoErr && fAnnotator) {
            fAnnotator->InvalidateRect(viewBounds);
        }
    }
    catch (...) {
        // Silently ignore — can happen during shutdown
    }
}
