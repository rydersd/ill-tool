//========================================================================================
//
//  PerspectiveHandles.cpp — Mouse interaction, VP handle dragging, overlay drawing
//
//  Included by PerspectiveModule.cpp (not a separate compilation unit).
//  All mouse event handlers, cursor tracking, snap constraint management,
//  and annotator overlay rendering live here.
//
//========================================================================================

extern IllToolPlugin* gPlugin;

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
    sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HANDLE_FILL());
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
    sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HANDLE_FILL());
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

    // Per-line colors matching the panel legend (from design tokens)
    AIRGBColor vp1Color     = ITK_COLOR_VP1();       // VP1 (left): red
    AIRGBColor vp2Color     = ITK_COLOR_VP2();       // VP2 (right): green
    AIRGBColor vp3Color     = ITK_COLOR_VP3();       // VP3 (vertical): blue
    AIRGBColor horizonColor = ITK_COLOR_HORIZON();   // horizon line: orange
    AIRGBColor gridColor    = ITK_COLOR_GRID();      // grid lines: cyan

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
            sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HANDLE_FILL());
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
            sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HANDLE_FILL());
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 3.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
            // Colored extension line on top
            sAIAnnotatorDrawer->SetColor(drawer, extColor);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
            sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_SECONDARY);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtA, vh1);
        }
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &extB, &vExtB) == kNoErr) {
            // White outline pass
            sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HANDLE_FILL());
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.25);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 3.0);
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
            sAIAnnotatorDrawer->DrawLine(drawer, vExtB, vh2);
            // Colored extension line on top
            sAIAnnotatorDrawer->SetColor(drawer, extColor);
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.4);
            sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_SECONDARY);
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

        int crossSize = (int)ITK_SIZE_VP_MARKER;
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
    // (VPs at +-1M cause annotator overflow)
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
        sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_GRID);

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

    // --- Draw detected Hough lines (VP confidence visualization) ---
    if (BridgeGetShowVPLines() && !fDetectedLines.empty() &&
        fAutoMatchImgW > 0 && fAutoMatchImgH > 0)
    {
        // Find max votes for opacity scaling
        int maxVotes = 1;
        for (auto& dl : fDetectedLines) {
            if (dl.votes > maxVotes) maxVotes = dl.votes;
        }

        // Coordinate mapping: pixel -> artwork (same as AutoMatch)
        double artW = (double)(fAutoMatchArtBounds.right - fAutoMatchArtBounds.left);
        double artH = (double)(fAutoMatchArtBounds.top - fAutoMatchArtBounds.bottom);
        double scaleX = artW / (double)fAutoMatchImgW;
        double scaleY = artH / (double)fAutoMatchImgH;

        auto pixToArt = [&](double px, double py, AIRealPoint& out) {
            out.h = (AIReal)((double)fAutoMatchArtBounds.left + px * scaleX);
            out.v = (AIReal)((double)fAutoMatchArtBounds.top  - py * scaleY);
        };

        // Cluster colors: VP1=blue, VP2=red, VP3=green
        AIRGBColor clusterColors[3];
        clusterColors[0] = {0, 0, 65535};         // VP1: blue
        clusterColors[1] = {65535, 0, 0};          // VP2: red
        clusterColors[2] = {0, 52428, 0};          // VP3: green

        sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);

        double extLen = 2000.0;  // line extension in pixel space

        for (auto& dl : fDetectedLines) {
            if (dl.cluster < 0 || dl.cluster > 2) continue;

            // Convert Hough (rho, theta) to two pixel-space endpoints
            double cosT = std::cos(dl.theta);
            double sinT = std::sin(dl.theta);
            double x0 = dl.rho * cosT;
            double y0 = dl.rho * sinT;

            double px1 = x0 + extLen * (-sinT);
            double py1 = y0 + extLen * (cosT);
            double px2 = x0 - extLen * (-sinT);
            double py2 = y0 - extLen * (cosT);

            // Clamp endpoints to image bounds (sufficient for visualization)
            px1 = std::max(0.0, std::min((double)fAutoMatchImgW, px1));
            py1 = std::max(0.0, std::min((double)fAutoMatchImgH, py1));
            px2 = std::max(0.0, std::min((double)fAutoMatchImgW, px2));
            py2 = std::max(0.0, std::min((double)fAutoMatchImgH, py2));

            // Convert pixel endpoints to artwork coordinates
            AIRealPoint artP1, artP2;
            pixToArt(px1, py1, artP1);
            pixToArt(px2, py2, artP2);

            // Convert artwork to view coordinates
            AIPoint vP1, vP2;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artP1, &vP1) != kNoErr) continue;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artP2, &vP2) != kNoErr) continue;

            // Opacity proportional to votes
            double opacity = std::min(1.0, (double)dl.votes / (double)maxVotes);
            opacity = std::max(0.15, opacity * 0.7);  // floor at 15%, scale to 70% max

            sAIAnnotatorDrawer->SetColor(drawer, clusterColors[dl.cluster]);
            sAIAnnotatorDrawer->SetOpacity(drawer, (AIReal)opacity);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
            sAIAnnotatorDrawer->DrawLine(drawer, vP1, vP2);
        }
    }

    // Restore defaults
    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
    sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
}
