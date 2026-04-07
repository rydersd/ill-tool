//========================================================================================
//
//  IllTool Plugin — Annotator implementation
//
//  Renders draw commands from the shared buffer via AIAnnotatorDrawerSuite.
//  Each draw command is converted from document (artwork) coordinates to
//  view (pixel) coordinates before drawing.
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolAnnotator.h"
#include "DrawCommands.h"
#include <cstdio>
#include <vector>

IllToolAnnotator::IllToolAnnotator()
{
    fprintf(stderr, "[IllTool] Annotator created\n");
}

/*
    TrackCursor — called on every mouse-move while our tool is selected.
*/
ASErr IllToolAnnotator::TrackCursor(AIToolMessage* /*message*/)
{
    return kNoErr;
}

//----------------------------------------------------------------------------------------
//  Coordinate conversion helper: artwork point -> view point
//----------------------------------------------------------------------------------------

static ASErr ArtToView(const AIRealPoint& artPt, AIPoint& viewPt)
{
    return sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &viewPt);
}

//----------------------------------------------------------------------------------------
//  Draw — render all buffered draw commands
//----------------------------------------------------------------------------------------

ASErr IllToolAnnotator::Draw(AIAnnotatorMessage* message)
{
    ASErr result = kNoErr;

    if (!message || !message->drawer) return kNoErr;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Get snapshot of current draw commands
    std::vector<DrawCommand> commands = GetDrawCommands();
    if (commands.empty()) return kNoErr;

    for (const auto& cmd : commands) {
        // Set stroke color (0-1 -> 0-65535)
        AIRGBColor strokeColor;
        strokeColor.red   = (ai::uint16)(cmd.strokeColor.r * 65535.0);
        strokeColor.green = (ai::uint16)(cmd.strokeColor.g * 65535.0);
        strokeColor.blue  = (ai::uint16)(cmd.strokeColor.b * 65535.0);

        AIRGBColor fillColor;
        fillColor.red   = (ai::uint16)(cmd.fillColor.r * 65535.0);
        fillColor.green = (ai::uint16)(cmd.fillColor.g * 65535.0);
        fillColor.blue  = (ai::uint16)(cmd.fillColor.b * 65535.0);

        // Set line width and dash pattern
        sAIAnnotatorDrawer->SetLineWidth(drawer, (AIReal)cmd.strokeWidth);
        if (cmd.dashed) {
            AIFloat dashArray[] = {4.0f, 3.0f};
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, dashArray, 2);
        } else {
            sAIAnnotatorDrawer->SetLineDashedEx(drawer, nullptr, 0);
        }

        // Set opacity from stroke alpha
        if (cmd.strokeColor.a < 1.0) {
            sAIAnnotatorDrawer->SetOpacity(drawer, (AIReal)cmd.strokeColor.a);
        } else {
            sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);
        }

        switch (cmd.type) {
            case DrawCommandType::Line: {
                if (cmd.points.size() >= 2) {
                    AIRealPoint artPt1 = {(AIReal)cmd.points[0].x, (AIReal)cmd.points[0].y};
                    AIRealPoint artPt2 = {(AIReal)cmd.points[1].x, (AIReal)cmd.points[1].y};
                    AIPoint vp1, vp2;
                    result = ArtToView(artPt1, vp1);
                    if (result) continue;
                    result = ArtToView(artPt2, vp2);
                    if (result) continue;

                    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
                    sAIAnnotatorDrawer->DrawLine(drawer, vp1, vp2);
                }
                break;
            }

            case DrawCommandType::Circle: {
                AIRealPoint artCenter = {(AIReal)cmd.center.x, (AIReal)cmd.center.y};
                AIPoint viewCenter;
                result = ArtToView(artCenter, viewCenter);
                if (result) continue;

                // Radius in view pixels: convert a second point offset by radius
                AIRealPoint artEdge = {(AIReal)(cmd.center.x + cmd.radius), (AIReal)cmd.center.y};
                AIPoint viewEdge;
                result = ArtToView(artEdge, viewEdge);
                if (result) continue;

                int rPx = abs(viewEdge.h - viewCenter.h);
                if (rPx < 1) rPx = 1;

                AIRect ellipseRect;
                ellipseRect.top    = viewCenter.v - rPx;
                ellipseRect.left   = viewCenter.h - rPx;
                ellipseRect.bottom = viewCenter.v + rPx;
                ellipseRect.right  = viewCenter.h + rPx;

                if (cmd.filled) {
                    sAIAnnotatorDrawer->SetColor(drawer, fillColor);
                    sAIAnnotatorDrawer->DrawEllipse(drawer, ellipseRect, true);
                }
                if (cmd.stroked) {
                    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
                    sAIAnnotatorDrawer->DrawEllipse(drawer, ellipseRect, false);
                }
                break;
            }

            case DrawCommandType::Rect: {
                AIRect rect;

                if (cmd.width > 0 && cmd.height > 0) {
                    // Center + width/height mode (for handle boxes)
                    AIRealPoint artCenter = {(AIReal)cmd.center.x, (AIReal)cmd.center.y};
                    AIPoint vpCenter;
                    result = ArtToView(artCenter, vpCenter);
                    if (result) continue;

                    int hw = (int)(cmd.width / 2.0);
                    int hh = (int)(cmd.height / 2.0);
                    rect.top    = vpCenter.v - hh;
                    rect.left   = vpCenter.h - hw;
                    rect.bottom = vpCenter.v + hh;
                    rect.right  = vpCenter.h + hw;
                } else if (cmd.points.size() >= 2) {
                    // Two-corner mode
                    AIRealPoint artTL = {(AIReal)cmd.points[0].x, (AIReal)cmd.points[0].y};
                    AIRealPoint artBR = {(AIReal)cmd.points[1].x, (AIReal)cmd.points[1].y};
                    AIPoint vpTL, vpBR;
                    result = ArtToView(artTL, vpTL);
                    if (result) continue;
                    result = ArtToView(artBR, vpBR);
                    if (result) continue;

                    rect.top    = std::min(vpTL.v, vpBR.v);
                    rect.left   = std::min(vpTL.h, vpBR.h);
                    rect.bottom = std::max(vpTL.v, vpBR.v);
                    rect.right  = std::max(vpTL.h, vpBR.h);
                } else {
                    continue;
                }

                if (cmd.filled) {
                    sAIAnnotatorDrawer->SetColor(drawer, fillColor);
                    sAIAnnotatorDrawer->DrawRect(drawer, rect, true);
                }
                if (cmd.stroked) {
                    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
                    sAIAnnotatorDrawer->DrawRect(drawer, rect, false);
                }
                break;
            }

            case DrawCommandType::Polygon: {
                if (cmd.points.size() >= 2) {
                    std::vector<AIPoint> viewPts;
                    viewPts.reserve(cmd.points.size());
                    bool ok = true;
                    for (const auto& p : cmd.points) {
                        AIRealPoint artPt = {(AIReal)p.x, (AIReal)p.y};
                        AIPoint vp;
                        if (ArtToView(artPt, vp) != kNoErr) {
                            ok = false;
                            break;
                        }
                        viewPts.push_back(vp);
                    }
                    if (!ok) continue;

                    if (cmd.filled) {
                        sAIAnnotatorDrawer->SetColor(drawer, fillColor);
                        sAIAnnotatorDrawer->DrawPolygon(drawer, viewPts.data(),
                            (ai::uint32)viewPts.size(), true);
                    }
                    if (cmd.stroked) {
                        sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
                        sAIAnnotatorDrawer->DrawPolygon(drawer, viewPts.data(),
                            (ai::uint32)viewPts.size(), false);
                    }
                }
                break;
            }

            case DrawCommandType::Text: {
                if (!cmd.text.empty() && cmd.points.size() >= 1) {
                    AIRealPoint artPt = {(AIReal)cmd.points[0].x, (AIReal)cmd.points[0].y};
                    AIPoint viewPt;
                    result = ArtToView(artPt, viewPt);
                    if (result) continue;

                    sAIAnnotatorDrawer->SetColor(drawer, strokeColor);
                    sAIAnnotatorDrawer->SetFontSize(drawer, (AIReal)cmd.fontSize);

                    ai::UnicodeString uText(cmd.text.c_str());

                    // Draw text at the converted view point
                    sAIAnnotatorDrawer->DrawText(drawer, uText, viewPt, false);
                }
                break;
            }
        }
    }

    // Reset opacity to full after drawing
    sAIAnnotatorDrawer->SetOpacity(drawer, 1.0);

    return kNoErr;
}

/*
    InvalidateRect (artwork coordinates) — converts to view coords, then
    asks the annotator system to repaint that region.
*/
ASErr IllToolAnnotator::InvalidateRect(const AIRealRect& invalRealRect)
{
    ASErr result = kNoErr;
    try {
        AIRect invalRect;
        result = this->ArtworkBoundsToViewBounds(invalRealRect, invalRect);
        aisdk::check_ai_error(result);

        SDK_ASSERT(sAIAnnotator);
        result = sAIAnnotator->InvalAnnotationRect(NULL, &invalRect);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    return result;
}

/*
    InvalidateRect (view coordinates) — directly invalidates.
*/
ASErr IllToolAnnotator::InvalidateRect(const AIRect& invalRect)
{
    ASErr result = kNoErr;
    try {
        SDK_ASSERT(sAIAnnotator);
        result = sAIAnnotator->InvalAnnotationRect(NULL, &invalRect);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    return result;
}

/*
    ArtworkBoundsToViewBounds — coordinate conversion helper.
*/
ASErr IllToolAnnotator::ArtworkBoundsToViewBounds(const AIRealRect& artworkBounds, AIRect& viewBounds)
{
    ASErr result = kNoErr;
    try {
        SDK_ASSERT(sAIDocumentView);
        result = sAIDocumentView->ArtworkRectToViewRect(NULL, &artworkBounds, &viewBounds);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    return result;
}
