/**
 * annotator.cpp — Annotator registration, draw callback, and rendering.
 *
 * Registers an Illustrator annotator via AIAnnotatorSuite, and on each
 * draw callback reads the shared command list (draw_commands.h) and
 * translates DrawCommands into AIAnnotatorDrawerSuite calls.
 *
 * Thread safety:
 *   - The draw callback runs on the main/UI thread.
 *   - The HTTP bridge (Phase 3) writes commands via UpdateDrawCommands().
 *   - GetDrawCommands() returns a snapshot — safe to iterate without locks.
 */

#include "annotator.h"
#include "plugin_globals.h"
#include "draw_commands.h"

#include <cstdio>
#include <cstring>
#include <cmath>
#include <vector>

/* ========================================================================== */
/*  Rendering helpers                                                         */
/* ========================================================================== */

/**
 * Convert a Color (0.0-1.0 per channel) to AIRGBColor (0-65535 per channel).
 */
static AIRGBColor ColorToAIRGB(const Color& c)
{
    AIRGBColor rgb;
    rgb.red   = static_cast<uint16_t>(c.r * 65535.0);
    rgb.green = static_cast<uint16_t>(c.g * 65535.0);
    rgb.blue  = static_cast<uint16_t>(c.b * 65535.0);
    return rgb;
}

/**
 * Apply stroke style (color + line width) to the drawer.
 * Real SDK: SetColor and SetLineWidth return void, not ASErr.
 * Real SDK: SetColor takes AIRGBColor by reference, not pointer.
 */
static void ApplyStrokeStyle(AIAnnotatorDrawer* drawer,
                              const AIAnnotatorDrawerSuite* suite,
                              const DrawCommand& cmd)
{
    AIRGBColor rgb = ColorToAIRGB(cmd.strokeColor);
    suite->SetColor(drawer, rgb);
    suite->SetLineWidth(drawer, cmd.strokeWidth);
}

/**
 * Apply fill color to the drawer.
 * Real SDK: SetColor returns void, takes AIRGBColor by reference.
 */
static void ApplyFillStyle(AIAnnotatorDrawer* drawer,
                            const AIAnnotatorDrawerSuite* suite,
                            const DrawCommand& cmd)
{
    AIRGBColor rgb = ColorToAIRGB(cmd.fillColor);
    suite->SetColor(drawer, rgb);
}

/* -------------------------------------------------------------------------- */
/*  Per-type renderers                                                        */
/* -------------------------------------------------------------------------- */

static void RenderLine(AIAnnotatorDrawer* drawer,
                       const AIAnnotatorDrawerSuite* suite,
                       const DrawCommand& cmd)
{
    if (cmd.points.size() < 2) {
        fprintf(stderr, "[IllTool] Line command needs >= 2 points, got %zu\n",
                cmd.points.size());
        return;
    }

    ApplyStrokeStyle(drawer, suite, cmd);

    AIPoint start;
    start.h = static_cast<int32_t>(cmd.points[0].x);
    start.v = static_cast<int32_t>(cmd.points[0].y);

    AIPoint end;
    end.h = static_cast<int32_t>(cmd.points[1].x);
    end.v = static_cast<int32_t>(cmd.points[1].y);

    suite->DrawLine(drawer, start, end);
}

static void RenderPolyline(AIAnnotatorDrawer* drawer,
                           const AIAnnotatorDrawerSuite* suite,
                           const DrawCommand& cmd)
{
    if (cmd.points.size() < 2) {
        fprintf(stderr, "[IllTool] Polyline needs >= 2 points, got %zu\n",
                cmd.points.size());
        return;
    }

    ApplyStrokeStyle(drawer, suite, cmd);

    for (size_t i = 0; i + 1 < cmd.points.size(); ++i) {
        AIPoint start;
        start.h = static_cast<int32_t>(cmd.points[i].x);
        start.v = static_cast<int32_t>(cmd.points[i].y);

        AIPoint end;
        end.h = static_cast<int32_t>(cmd.points[i + 1].x);
        end.v = static_cast<int32_t>(cmd.points[i + 1].y);

        suite->DrawLine(drawer, start, end);
    }
}

static void RenderCircle(AIAnnotatorDrawer* drawer,
                         const AIAnnotatorDrawerSuite* suite,
                         const DrawCommand& cmd)
{
    int32_t cx = static_cast<int32_t>(cmd.center.x);
    int32_t cy = static_cast<int32_t>(cmd.center.y);
    int32_t r  = static_cast<int32_t>(std::round(cmd.radius));

    AIRect bounds;
    bounds.left   = cx - r;
    bounds.top    = cy - r;
    bounds.right  = cx + r;
    bounds.bottom = cy + r;

    if (cmd.filled) {
        ApplyFillStyle(drawer, suite, cmd);
        suite->DrawEllipse(drawer, bounds, true);
    }
    if (cmd.stroked) {
        ApplyStrokeStyle(drawer, suite, cmd);
        suite->DrawEllipse(drawer, bounds, false);
    }
}

static void RenderEllipse(AIAnnotatorDrawer* drawer,
                          const AIAnnotatorDrawerSuite* suite,
                          const DrawCommand& cmd)
{
    int32_t cx = static_cast<int32_t>(cmd.center.x);
    int32_t cy = static_cast<int32_t>(cmd.center.y);
    int32_t hw = static_cast<int32_t>(std::round(cmd.width  / 2.0));
    int32_t hh = static_cast<int32_t>(std::round(cmd.height / 2.0));

    AIRect bounds;
    bounds.left   = cx - hw;
    bounds.top    = cy - hh;
    bounds.right  = cx + hw;
    bounds.bottom = cy + hh;

    if (cmd.filled) {
        ApplyFillStyle(drawer, suite, cmd);
        suite->DrawEllipse(drawer, bounds, true);
    }
    if (cmd.stroked) {
        ApplyStrokeStyle(drawer, suite, cmd);
        suite->DrawEllipse(drawer, bounds, false);
    }
}

static void RenderRect(AIAnnotatorDrawer* drawer,
                       const AIAnnotatorDrawerSuite* suite,
                       const DrawCommand& cmd)
{
    int32_t cx = static_cast<int32_t>(cmd.center.x);
    int32_t cy = static_cast<int32_t>(cmd.center.y);
    int32_t hw = static_cast<int32_t>(std::round(cmd.width  / 2.0));
    int32_t hh = static_cast<int32_t>(std::round(cmd.height / 2.0));

    AIRect rect;
    rect.left   = cx - hw;
    rect.top    = cy - hh;
    rect.right  = cx + hw;
    rect.bottom = cy + hh;

    if (cmd.filled) {
        ApplyFillStyle(drawer, suite, cmd);
        suite->DrawRect(drawer, rect, true);
    }
    if (cmd.stroked) {
        ApplyStrokeStyle(drawer, suite, cmd);
        suite->DrawRect(drawer, rect, false);
    }
}

static void RenderPolygon(AIAnnotatorDrawer* drawer,
                          const AIAnnotatorDrawerSuite* suite,
                          const DrawCommand& cmd)
{
    if (cmd.points.empty()) {
        fprintf(stderr, "[IllTool] Polygon needs >= 3 points, got 0\n");
        return;
    }

    std::vector<AIPoint> aiPoints;
    aiPoints.reserve(cmd.points.size());
    for (const auto& p : cmd.points) {
        AIPoint ap;
        ap.h = static_cast<int32_t>(p.x);
        ap.v = static_cast<int32_t>(p.y);
        aiPoints.push_back(ap);
    }

    if (cmd.filled) {
        ApplyFillStyle(drawer, suite, cmd);
        suite->DrawPolygon(drawer, aiPoints.data(),
                           static_cast<ai::uint32>(aiPoints.size()), true);
    }
    if (cmd.stroked) {
        ApplyStrokeStyle(drawer, suite, cmd);
        suite->DrawPolygon(drawer, aiPoints.data(),
                           static_cast<ai::uint32>(aiPoints.size()), false);
    }
}

/**
 * Render a single DrawCommand via the AIAnnotatorDrawerSuite.
 */
static void RenderCommand(AIAnnotatorDrawer* drawer,
                          const AIAnnotatorDrawerSuite* suite,
                          const DrawCommand& cmd)
{
    if (!drawer || !suite) {
        fprintf(stderr, "[IllTool] RenderCommand: null drawer or suite.\n");
        return;
    }

    switch (cmd.type) {
        case DrawCommandType::Line:
            RenderLine(drawer, suite, cmd);
            break;
        case DrawCommandType::Polyline:
            RenderPolyline(drawer, suite, cmd);
            break;
        case DrawCommandType::Circle:
            RenderCircle(drawer, suite, cmd);
            break;
        case DrawCommandType::Ellipse:
            RenderEllipse(drawer, suite, cmd);
            break;
        case DrawCommandType::Rect:
            RenderRect(drawer, suite, cmd);
            break;
        case DrawCommandType::Polygon:
            RenderPolygon(drawer, suite, cmd);
            break;

        /* --- Not yet implemented --- */
        case DrawCommandType::Bezier:
            /* TODO: Bezier rendering — Phase 3+ */
            break;
        case DrawCommandType::Text:
            /* TODO: Text rendering — Phase 3+ */
            break;
        case DrawCommandType::Arc:
            /* TODO: Arc rendering — Phase 3+ */
            break;
        case DrawCommandType::Handle:
            /* TODO: Handle (draggable point) — Phase 4 */
            break;
        case DrawCommandType::Crosshair:
            /* TODO: Crosshair rendering — Phase 3+ */
            break;
        case DrawCommandType::Grid:
            /* TODO: Grid rendering — Phase 3+ */
            break;
        case DrawCommandType::Image:
            /* TODO: Image rendering — Phase 3+ */
            break;
        case DrawCommandType::Unknown:
            fprintf(stderr, "[IllTool] RenderCommand: unknown command type.\n");
            break;
    }
}

/* ========================================================================== */
/*  Annotator lifecycle                                                       */
/* ========================================================================== */

ASErr RegisterAnnotator()
{
    if (!gPlugin.annotatorSuite) {
        fprintf(stderr, "[IllTool] RegisterAnnotator: annotatorSuite is null — cannot register.\n");
        return kUnhandledMsgErr;
    }

    ASErr err = gPlugin.annotatorSuite->AddAnnotator(
        gPlugin.pluginRef,
        "IllTool Overlay",
        &gPlugin.annotator
    );

    if (err != kNoErr) {
        fprintf(stderr, "[IllTool] AddAnnotator failed: %d\n", err);
        return err;
    }

    fprintf(stderr, "[IllTool] Annotator registered: handle=%p\n",
            static_cast<void*>(gPlugin.annotator));

    /* Activate immediately so it starts drawing.
     * Real SDK: SetAnnotatorActive takes AIBoolean (unsigned char on Mac), not bool. */
    SetAnnotatorActive(true);

    /* Annotator starts with no draw commands — CEP panels send commands via HTTP bridge */

    return kNoErr;
}

/* -------------------------------------------------------------------------- */

void SetAnnotatorActive(bool active)
{
    if (!gPlugin.annotatorSuite || !gPlugin.annotator) {
        fprintf(stderr, "[IllTool] SetAnnotatorActive: suite or handle is null.\n");
        return;
    }

    AIErr err = gPlugin.annotatorSuite->SetAnnotatorActive(gPlugin.annotator,
        static_cast<AIBoolean>(active));
    if (err == kNoErr) {
        gPlugin.annotatorActive = active;
        fprintf(stderr, "[IllTool] Annotator %s.\n", active ? "activated" : "deactivated");
    } else {
        fprintf(stderr, "[IllTool] SetAnnotatorActive failed: %d\n", err);
    }
}

/* -------------------------------------------------------------------------- */

bool IsAnnotatorActive()
{
    return gPlugin.annotatorActive;
}

/* -------------------------------------------------------------------------- */

ASErr HandleAnnotatorMessage(const char* selector, void* message)
{
    if (std::strcmp(selector, kSelectorAIDrawAnnotation) == 0) {
        auto* msg = static_cast<AIAnnotatorMessage*>(message);
        if (!msg || !msg->drawer) {
            fprintf(stderr, "[IllTool] Draw annotation: null message or drawer.\n");
            return kUnhandledMsgErr;
        }

        if (!gPlugin.annotatorDrawerSuite) {
            fprintf(stderr, "[IllTool] Draw annotation: drawer suite is null.\n");
            return kUnhandledMsgErr;
        }

        /* GetDrawCommands returns a snapshot — safe to iterate. */
        std::vector<DrawCommand> snapshot = GetDrawCommands();

        for (const auto& cmd : snapshot) {
            RenderCommand(msg->drawer, gPlugin.annotatorDrawerSuite, cmd);
        }

        return kNoErr;
    }

    if (std::strcmp(selector, kSelectorAIInvalAnnotation) == 0) {
        /* Invalidation notification — nothing to do on our side. */
        return kNoErr;
    }

    fprintf(stderr, "[IllTool] Unhandled annotator selector: %s\n", selector);
    return kUnhandledMsgErr;
}
