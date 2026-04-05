/**
 * tool.h — Custom tool registration and mouse event handling.
 *
 * Phase 4 implements the "IllTool Handle" tool which registers in
 * Illustrator's toolbox and dispatches mouse events (down/drag/up/hover)
 * to hit-test against draggable DrawCommands, emitting SSE events
 * via BridgeEmitEvent for the TypeScript layer to consume.
 */

#ifndef TOOL_H
#define TOOL_H

#include "sdk_includes.h"

/**
 * Register the custom tool with Illustrator's toolbox.
 * Called during plugin startup after AIToolSuite is acquired.
 */
ASErr RegisterTool();

/**
 * Handle a tool message from Illustrator.
 * Dispatches mouse/cursor events based on selector string.
 *
 * @param caller    Caller string (should be kCallerAITool).
 * @param selector  Selector string (mousedown, drag, up, track cursor).
 * @param message   Pointer to AIToolMessage.
 */
ASErr HandleToolMessage(const char* caller, const char* selector, void* message);

/**
 * Queue a tool activation state change for the main thread.
 * The actual activation happens via the tool suite on Illustrator's main thread.
 *
 * @param active  true = select this tool, false = deselect.
 */
void SetToolActiveQueued(bool active);

#endif /* TOOL_H */
