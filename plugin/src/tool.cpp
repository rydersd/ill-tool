/**
 * tool.cpp — Custom tool implementation for the IllTool plugin.
 *
 * Registers "IllTool Handle" in Illustrator's toolbox and handles
 * mouse events: mousedown, mousedrag, mouseup, and cursor tracking.
 *
 * Hit testing is performed against draggable DrawCommands in document
 * space. For Circle types, a simple distance-to-center check is used.
 *
 * All mouse events are emitted as SSE events via BridgeEmitEvent()
 * so the TypeScript orchestration layer can react to user interaction.
 *
 * Thread safety:
 *   - Tool messages arrive on Illustrator's main/UI thread.
 *   - GetDrawCommands() returns a thread-safe snapshot.
 *   - BridgeEmitEvent() is thread-safe.
 */

#include "tool.h"
#include "plugin_globals.h"
#include "draw_commands.h"
#include "http_bridge.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

/* -------------------------------------------------------------------------- */
/*  Drag state                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Tracks the current drag operation. Only one drag can be active at a time
 * since Illustrator serializes mouse events on the main thread.
 */
struct DragState {
    bool        active    = false;
    std::string commandId;         /* id of the DrawCommand being dragged */
    Point2D     startDoc;          /* document coords where drag began */
};

static DragState sDragState;

/* -------------------------------------------------------------------------- */
/*  Hit testing                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Hit-test a document-space cursor position against all draggable commands.
 *
 * Currently supports Circle type: distance from cursor to center < hitRadius.
 * Draw commands with viewSpace == true are skipped (no coordinate conversion
 * available without AIDocumentViewSuite wired).
 *
 * Returns the id of the hit command, or empty string if no hit.
 */
static std::string HitTestDraggables(double cursorDocH, double cursorDocV)
{
    std::vector<DrawCommand> snapshot = GetDrawCommands();

    for (const auto& cmd : snapshot) {
        if (!cmd.draggable) continue;

        /* Skip view-space commands — we only have document coords from the cursor.
         * When AIDocumentViewSuite is wired (Phase 5+), we can convert. */
        if (cmd.viewSpace) continue;

        switch (cmd.type) {
            case DrawCommandType::Circle:
            case DrawCommandType::Handle: {
                double dx = cursorDocH - cmd.center.x;
                double dy = cursorDocV - cmd.center.y;
                double dist = std::sqrt(dx * dx + dy * dy);
                if (dist <= cmd.hitRadius) {
                    return cmd.id;
                }
                break;
            }

            case DrawCommandType::Rect: {
                /* Simple bounding-box hit test for draggable rects */
                double hw = cmd.width  / 2.0;
                double hh = cmd.height / 2.0;
                if (cursorDocH >= cmd.center.x - hw &&
                    cursorDocH <= cmd.center.x + hw &&
                    cursorDocV >= cmd.center.y - hh &&
                    cursorDocV <= cmd.center.y + hh) {
                    return cmd.id;
                }
                break;
            }

            default:
                /* Other types: point-distance to center as fallback */
                if (cmd.hitRadius > 0.0) {
                    double dx = cursorDocH - cmd.center.x;
                    double dy = cursorDocV - cmd.center.y;
                    double dist = std::sqrt(dx * dx + dy * dy);
                    if (dist <= cmd.hitRadius) {
                        return cmd.id;
                    }
                }
                break;
        }
    }

    return "";  /* no hit */
}

/* -------------------------------------------------------------------------- */
/*  Invalidate annotator overlay                                              */
/* -------------------------------------------------------------------------- */

/**
 * Request a full redraw of the annotator overlay.
 * Real SDK: InvalAnnotationRect takes (AIDocumentViewHandle view, const AIRect* rect).
 * Passing nullptr for both invalidates the entire current view.
 */
static void InvalidateAnnotations()
{
    if (gPlugin.annotatorSuite) {
        gPlugin.annotatorSuite->InvalAnnotationRect(nullptr, nullptr);
    }
}

/* -------------------------------------------------------------------------- */
/*  Mouse event handlers                                                      */
/* -------------------------------------------------------------------------- */

static AIErr OnMouseDown(AIToolMessage* msg)
{
    double h = msg->cursor.h;
    double v = msg->cursor.v;

    std::string hitId = HitTestDraggables(h, v);

    if (!hitId.empty()) {
        /* Start drag */
        sDragState.active    = true;
        sDragState.commandId = hitId;
        sDragState.startDoc  = {h, v};

        fprintf(stderr, "[IllTool] Tool mousedown — hit '%s' at (%.1f, %.1f)\n",
                hitId.c_str(), h, v);
    } else {
        sDragState.active = false;
        sDragState.commandId.clear();

        fprintf(stderr, "[IllTool] Tool mousedown — no hit at (%.1f, %.1f)\n", h, v);
    }

    /* Emit SSE event regardless — the TS layer may want click-on-empty-space too */
    BridgeEmitEvent("mousedown", hitId, h, v);

    return kNoErr;
}

static AIErr OnMouseDrag(AIToolMessage* msg)
{
    double h = msg->cursor.h;
    double v = msg->cursor.v;

    if (sDragState.active) {
        /* Emit drag event with the command id being dragged */
        BridgeEmitEvent("mousedrag", sDragState.commandId, h, v);

        /* Request annotator redraw for live visual feedback */
        InvalidateAnnotations();
    }

    return kNoErr;
}

static AIErr OnMouseUp(AIToolMessage* msg)
{
    double h = msg->cursor.h;
    double v = msg->cursor.v;

    if (sDragState.active) {
        fprintf(stderr, "[IllTool] Tool mouseup — drag end for '%s' at (%.1f, %.1f)\n",
                sDragState.commandId.c_str(), h, v);

        BridgeEmitEvent("mouseup", sDragState.commandId, h, v);

        /* Clear drag state */
        sDragState.active = false;
        sDragState.commandId.clear();

        /* Final redraw after drag completes */
        InvalidateAnnotations();
    } else {
        BridgeEmitEvent("mouseup", "", h, v);
    }

    return kNoErr;
}

static AIErr OnTrackCursor(AIToolMessage* msg)
{
    if (!gPlugin.toolSuite) return kNoErr;

    double h = msg->cursor.h;
    double v = msg->cursor.v;

    std::string hitId = HitTestDraggables(h, v);

    if (!hitId.empty()) {
        /* Hovering over a draggable — emit hover event.
         * Cursor setting requires AIUserSuite (not yet wired). */
        BridgeEmitEvent("hover", hitId, h, v);
    }
    /* else: default arrow cursor is used by Illustrator */

    return kNoErr;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

AIErr RegisterTool()
{
    if (!gPlugin.toolSuite) {
        fprintf(stderr, "[IllTool] RegisterTool: toolSuite is null — cannot register.\n");
        return kUnhandledMsgErr;
    }

    /* Real SDK: AIAddToolData uses ai::UnicodeString for title/tooltip.
     * AddTool signature: AddTool(SPPluginRef self, const char* name,
     *                            const AIAddToolData& data, ai::int32 options,
     *                            AIToolHandle* tool)
     * The 'name' parameter is a unique tool identifier (not the display title). */

    AIAddToolData toolData;
    toolData.title   = ai::UnicodeString("IllTool Handle");
    toolData.tooltip = ai::UnicodeString("IllTool interactive handle — drag overlay control points");
    toolData.sameGroupAs   = kNoTool;
    toolData.sameToolsetAs = kNoTool;

    AIErr err = gPlugin.toolSuite->AddTool(
        gPlugin.pluginRef,
        "IllTool Handle",   /* unique name identifier */
        toolData,           /* passed by reference in real SDK */
        kToolWantsToTrackCursorOption,
        &gPlugin.tool
    );

    if (err != kNoErr) {
        fprintf(stderr, "[IllTool] AddTool failed: %d\n", err);
        return err;
    }

    fprintf(stderr, "[IllTool] Tool registered: handle=%p\n",
            static_cast<void*>(gPlugin.tool));

    return kNoErr;
}

ASErr HandleToolMessage(const char* /*caller*/, const char* selector, void* message)
{
    auto* msg = static_cast<AIToolMessage*>(message);
    if (!msg) {
        fprintf(stderr, "[IllTool] HandleToolMessage: null message.\n");
        return kUnhandledMsgErr;
    }

    if (std::strcmp(selector, kSelectorAIToolMouseDown) == 0) {
        return OnMouseDown(msg);
    }
    else if (std::strcmp(selector, kSelectorAIToolMouseDrag) == 0) {
        return OnMouseDrag(msg);
    }
    else if (std::strcmp(selector, kSelectorAIToolMouseUp) == 0) {
        return OnMouseUp(msg);
    }
    else if (std::strcmp(selector, kSelectorAITrackToolCursor) == 0) {
        return OnTrackCursor(msg);
    }

    /* Unrecognized selector — let Illustrator handle it */
    fprintf(stderr, "[IllTool] Unhandled tool selector: %s\n", selector);
    return kUnhandledMsgErr;
}

void SetToolActiveQueued(bool active)
{
    /* For now, just set the flag. In a real integration with the SDK,
     * tool activation would need to be dispatched to Illustrator's main
     * thread via an idle notification or similar mechanism.
     * The HTTP endpoints /tool/activate and /tool/deactivate already
     * set gPlugin.toolActive — this function provides a programmatic path. */
    gPlugin.toolActive = active;
    fprintf(stderr, "[IllTool] Tool active queued: %s\n", active ? "true" : "false");
}
