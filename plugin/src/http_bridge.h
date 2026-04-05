/**
 * http_bridge.h — HTTP server for external control of the IllTool plugin.
 *
 * Runs a localhost-only HTTP server on a background thread. TypeScript/CEP
 * sends draw commands via POST /draw, receives mouse events via GET /events (SSE).
 *
 * The bridge is the primary interface between the TypeScript orchestration
 * layer and the C++ annotator rendering engine.
 */

#ifndef HTTP_BRIDGE_H
#define HTTP_BRIDGE_H

#include <string>

/**
 * Start the HTTP bridge server on the given port.
 * Spawns a background thread. Safe to call from plugin startup (main thread).
 *
 * Port resolution order:
 *   1. env var ILLTOOL_PLUGIN_PORT (if set and valid)
 *   2. The port parameter
 *   3. Default 8787
 *
 * Returns true if the server started, false on error.
 */
bool StartHttpBridge(int port = 8787);

/**
 * Stop the HTTP bridge server and join the background thread.
 * Blocks until the server has fully shut down. Safe to call from plugin shutdown.
 */
void StopHttpBridge();

/**
 * Push an SSE event to all connected /events clients.
 *
 * Events are formatted as SSE: "event: <type>\ndata: {json}\n\n"
 * The JSON payload contains the event type, id, and coordinates.
 *
 * Thread-safe — can be called from any thread (typically the tool handler
 * on Illustrator's main thread when mouse events arrive).
 */
void BridgeEmitEvent(const char* type, const std::string& id, double x, double y);

#endif /* HTTP_BRIDGE_H */
