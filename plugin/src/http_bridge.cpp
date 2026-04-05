/**
 * http_bridge.cpp — HTTP server for external control of the IllTool plugin.
 *
 * Uses cpp-httplib (single-header) for the HTTP server.
 * Runs on a background thread, binds to 127.0.0.1 only.
 *
 * Endpoints:
 *   POST /draw           — receive JSON draw commands
 *   POST /clear          — clear all draw commands
 *   GET  /status         — plugin status JSON
 *   GET  /events         — SSE stream (mouse events, state changes)
 *   POST /annotator/activate   — enable overlay drawing
 *   POST /annotator/deactivate — disable overlay drawing
 *   POST /tool/activate        — enable custom tool (Phase 4)
 *   POST /tool/deactivate      — disable custom tool (Phase 4)
 *   POST /llm/query            — query Claude API (Phase 6)
 */

#include "http_bridge.h"
#include "draw_commands.h"
#include "json_parse.h"
#include "annotator.h"
#include "plugin_globals.h"
#include "llm_client.h"

#include "httplib.h"
#include "json.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

#include <sys/stat.h>
#include <unistd.h>
#include <pwd.h>

using json = nlohmann::json;

/* -------------------------------------------------------------------------- */
/*  SSE event queue                                                           */
/* -------------------------------------------------------------------------- */

static std::mutex              sEventMutex;
static std::condition_variable sEventCv;
static std::queue<std::string> sEventQueue;
static std::atomic<bool>       sServerRunning{false};

/* -------------------------------------------------------------------------- */
/*  Server state                                                              */
/* -------------------------------------------------------------------------- */

static httplib::Server* sServer    = nullptr;
static std::thread      sServerThread;

/* -------------------------------------------------------------------------- */
/*  Helper: JSON error response                                               */
/* -------------------------------------------------------------------------- */

static void RespondError(httplib::Response& res, int status, const std::string& msg)
{
    json j;
    j["error"] = msg;
    res.status = status;
    res.set_content(j.dump(), "application/json");
}

/* -------------------------------------------------------------------------- */
/*  Helper: JSON success response                                             */
/* -------------------------------------------------------------------------- */

static void RespondOk(httplib::Response& res, const json& extra = json::object())
{
    json j = extra;
    j["ok"] = true;
    res.status = 200;
    res.set_content(j.dump(), "application/json");
}

/* -------------------------------------------------------------------------- */
/*  Interaction logging — append JSONL to ~/Library/Application Support/       */
/*  illtool/interactions/plugin_YYYYMMDD.jsonl                                */
/* -------------------------------------------------------------------------- */

static std::mutex sLogMutex;

/**
 * Get the user's home directory reliably (env HOME or passwd entry).
 */
static std::string GetHomeDir()
{
    const char* home = std::getenv("HOME");
    if (home && home[0] != '\0') return std::string(home);

    struct passwd* pw = getpwuid(getuid());
    if (pw && pw->pw_dir) return std::string(pw->pw_dir);

    return "/tmp";  /* last resort */
}

/**
 * Ensure a directory exists, creating intermediate directories as needed.
 * Returns true on success.
 */
static bool EnsureDirectory(const std::string& path)
{
    struct stat st;
    if (stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) return true;

    /* Recursively ensure parent exists */
    auto lastSlash = path.rfind('/');
    if (lastSlash != std::string::npos && lastSlash > 0) {
        EnsureDirectory(path.substr(0, lastSlash));
    }

    return mkdir(path.c_str(), 0755) == 0 || errno == EEXIST;
}

/**
 * Log an interaction event as a JSONL line.
 *
 * @param panel   - which panel/component triggered this ("bridge", "draw", etc.)
 * @param action  - the action name ("draw", "mouse_event", "llm_query", etc.)
 * @param context - additional context as a json object (merged into the entry)
 */
static void LogInteraction(const std::string& panel, const std::string& action,
                           const json& context = json::object())
{
    try {
        /* Build timestamp string: ISO 8601 */
        auto now = std::chrono::system_clock::now();
        auto time_t_now = std::chrono::system_clock::to_time_t(now);
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now.time_since_epoch()) % 1000;

        struct tm tm_buf;
        localtime_r(&time_t_now, &tm_buf);

        char timestamp[64];
        std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S", &tm_buf);

        char timestamp_ms[80];
        std::snprintf(timestamp_ms, sizeof(timestamp_ms), "%s.%03d", timestamp,
                      static_cast<int>(ms.count()));

        /* Build date string for filename: YYYYMMDD */
        char dateStr[16];
        std::strftime(dateStr, sizeof(dateStr), "%Y%m%d", &tm_buf);

        /* Build log directory and file path */
        std::string homeDir = GetHomeDir();
        std::string logDir = homeDir + "/Library/Application Support/illtool/interactions";
        EnsureDirectory(logDir);

        std::string logFile = logDir + "/plugin_" + std::string(dateStr) + ".jsonl";

        /* Build JSON entry */
        json entry;
        entry["timestamp"] = std::string(timestamp_ms);
        entry["panel"]     = panel;
        entry["action"]    = action;

        /* Merge context fields into entry */
        if (context.is_object()) {
            for (auto it = context.begin(); it != context.end(); ++it) {
                entry[it.key()] = it.value();
            }
        }

        /* Append to file (thread-safe) */
        std::string line = entry.dump() + "\n";
        {
            std::lock_guard<std::mutex> lock(sLogMutex);
            std::ofstream ofs(logFile, std::ios::app);
            if (ofs.is_open()) {
                ofs.write(line.data(), static_cast<std::streamsize>(line.size()));
            }
        }
    } catch (...) {
        /* Logging must never crash the plugin */
    }
}

/* -------------------------------------------------------------------------- */
/*  Route handlers                                                            */
/* -------------------------------------------------------------------------- */

static void HandleDraw(const httplib::Request& req, httplib::Response& res)
{
    if (req.body.empty()) {
        RespondError(res, 400, "Empty request body");
        return;
    }

    auto cmds = ParseDrawCommands(req.body);
    UpdateDrawCommands(std::move(cmds));

    size_t count = GetDrawCommandCount();
    fprintf(stderr, "[IllTool] HTTP /draw — updated with %zu commands.\n", count);

    LogInteraction("bridge", "draw", {{"command_count", count}});

    json extra;
    extra["count"] = count;
    RespondOk(res, extra);
}

static void HandleClear(const httplib::Request& /*req*/, httplib::Response& res)
{
    UpdateDrawCommands({});
    fprintf(stderr, "[IllTool] HTTP /clear — all draw commands cleared.\n");
    RespondOk(res);
}

static void HandleStatus(const httplib::Request& /*req*/, httplib::Response& res)
{
    json j;
    j["annotatorActive"] = IsAnnotatorActive();
    j["toolActive"]      = gPlugin.toolActive;
    j["commandCount"]    = GetDrawCommandCount();
    j["version"]         = "1.0.0";
    res.status = 200;
    res.set_content(j.dump(), "application/json");
}

static void HandleAnnotatorActivate(const httplib::Request& /*req*/, httplib::Response& res)
{
    SetAnnotatorActive(true);
    fprintf(stderr, "[IllTool] HTTP /annotator/activate\n");
    RespondOk(res);
}

static void HandleAnnotatorDeactivate(const httplib::Request& /*req*/, httplib::Response& res)
{
    SetAnnotatorActive(false);
    fprintf(stderr, "[IllTool] HTTP /annotator/deactivate\n");
    RespondOk(res);
}

static void HandleToolActivate(const httplib::Request& /*req*/, httplib::Response& res)
{
    /* Phase 4 stub — tool activation via HTTP */
    gPlugin.toolActive = true;
    fprintf(stderr, "[IllTool] HTTP /tool/activate — stub (Phase 4)\n");
    LogInteraction("bridge", "tool_activate");
    RespondOk(res);
}

static void HandleToolDeactivate(const httplib::Request& /*req*/, httplib::Response& res)
{
    /* Phase 4 stub — tool deactivation via HTTP */
    gPlugin.toolActive = false;
    fprintf(stderr, "[IllTool] HTTP /tool/deactivate — stub (Phase 4)\n");
    LogInteraction("bridge", "tool_deactivate");
    RespondOk(res);
}

/* -------------------------------------------------------------------------- */
/*  LLM /llm/query endpoint (Phase 6)                                        */
/* -------------------------------------------------------------------------- */

static void HandleLLMQuery(const httplib::Request& req, httplib::Response& res)
{
    if (req.body.empty()) {
        RespondError(res, 400, "Empty request body");
        return;
    }

    fprintf(stderr, "[IllTool] HTTP /llm/query — processing request.\n");

    std::string responseJson = QueryLLM(req.body);

    /* Log interaction with token counts from the response */
    try {
        json respData = json::parse(responseJson);
        json ctx;
        ctx["input_tokens"]  = respData.value("input_tokens", 0);
        ctx["output_tokens"] = respData.value("output_tokens", 0);
        ctx["model"]         = respData.value("model", "unknown");
        ctx["success"]       = respData.value("success", false);
        LogInteraction("bridge", "llm_query", ctx);
    } catch (...) {
        LogInteraction("bridge", "llm_query", {{"parse_error", true}});
    }

    res.status = 200;
    res.set_content(responseJson, "application/json");
}

/* -------------------------------------------------------------------------- */
/*  SSE /events endpoint                                                      */
/* -------------------------------------------------------------------------- */

static void HandleEvents(const httplib::Request& /*req*/, httplib::Response& res)
{
    fprintf(stderr, "[IllTool] HTTP /events — SSE client connected.\n");

    res.set_header("Cache-Control", "no-cache");
    res.set_header("Connection", "keep-alive");
    res.set_header("Access-Control-Allow-Origin", "*");

    res.set_chunked_content_provider(
        "text/event-stream",
        [](size_t /*offset*/, httplib::DataSink& sink) -> bool {
            /* Send initial connection event */
            std::string connectEvent = "event: connected\ndata: {\"status\":\"ok\"}\n\n";
            sink.write(connectEvent.data(), connectEvent.size());

            while (sServerRunning.load()) {
                std::string event;
                {
                    std::unique_lock<std::mutex> lock(sEventMutex);

                    /* Wait for an event or timeout for keepalive */
                    bool gotEvent = sEventCv.wait_for(lock, std::chrono::seconds(15), [] {
                        return !sEventQueue.empty() || !sServerRunning.load();
                    });

                    if (!sServerRunning.load()) {
                        /* Server shutting down — close the stream */
                        return false;
                    }

                    if (gotEvent && !sEventQueue.empty()) {
                        event = std::move(sEventQueue.front());
                        sEventQueue.pop();
                    }
                }

                if (!event.empty()) {
                    /* Send the queued event */
                    if (!sink.write(event.data(), event.size())) {
                        fprintf(stderr, "[IllTool] SSE write failed — client disconnected.\n");
                        return false;
                    }
                } else {
                    /* Keepalive comment — prevents proxy/browser timeout */
                    std::string keepalive = ": keepalive\n\n";
                    if (!sink.write(keepalive.data(), keepalive.size())) {
                        fprintf(stderr, "[IllTool] SSE keepalive failed — client disconnected.\n");
                        return false;
                    }
                }
            }

            return false;  /* end stream */
        },
        [](bool success) {
            fprintf(stderr, "[IllTool] SSE stream ended (success=%s).\n",
                    success ? "true" : "false");
        }
    );
}

/* -------------------------------------------------------------------------- */
/*  Public API: BridgeEmitEvent                                               */
/* -------------------------------------------------------------------------- */

void BridgeEmitEvent(const char* type, const std::string& id, double x, double y)
{
    if (!sServerRunning.load()) return;

    json data;
    data["type"] = type;
    data["id"]   = id;
    data["x"]    = x;
    data["y"]    = y;

    /* Log mouse events — only log mousedown/mouseup to keep volume manageable.
     * Drag events are too frequent to log individually. */
    std::string typeStr(type);
    if (typeStr == "mousedown" || typeStr == "mouseup") {
        LogInteraction("bridge", "mouse_event", {{"type", typeStr}, {"command_id", id}});
    }

    /* Format as SSE */
    std::string event = "event: " + typeStr + "\n"
                      + "data: " + data.dump() + "\n\n";

    {
        std::lock_guard<std::mutex> lock(sEventMutex);
        sEventQueue.push(std::move(event));
    }
    sEventCv.notify_all();
}

/* -------------------------------------------------------------------------- */
/*  Public API: StartHttpBridge / StopHttpBridge                              */
/* -------------------------------------------------------------------------- */

bool StartHttpBridge(int port)
{
    if (sServerRunning.load()) {
        fprintf(stderr, "[IllTool] HTTP bridge already running.\n");
        return true;
    }

    /* Check environment variable for port override */
    const char* envPort = std::getenv("ILLTOOL_PLUGIN_PORT");
    if (envPort) {
        int parsed = std::atoi(envPort);
        if (parsed > 0 && parsed <= 65535) {
            port = parsed;
            fprintf(stderr, "[IllTool] Using port %d from ILLTOOL_PLUGIN_PORT.\n", port);
        } else {
            fprintf(stderr, "[IllTool] Invalid ILLTOOL_PLUGIN_PORT '%s', using default %d.\n",
                    envPort, port);
        }
    }

    sServer = new httplib::Server();

    /* CORS preflight support for browser-based clients */
    sServer->Options(".*", [](const httplib::Request& /*req*/, httplib::Response& res) {
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type");
        res.status = 204;
    });

    /* Add CORS headers to all responses */
    sServer->set_post_routing_handler([](const httplib::Request& /*req*/, httplib::Response& res) {
        res.set_header("Access-Control-Allow-Origin", "*");
    });

    /* Register routes */
    sServer->Post("/draw",  HandleDraw);
    sServer->Post("/clear", HandleClear);
    sServer->Get("/status", HandleStatus);
    sServer->Get("/events", HandleEvents);
    sServer->Post("/annotator/activate",   HandleAnnotatorActivate);
    sServer->Post("/annotator/deactivate", HandleAnnotatorDeactivate);
    sServer->Post("/tool/activate",   HandleToolActivate);
    sServer->Post("/tool/deactivate", HandleToolDeactivate);
    sServer->Post("/llm/query",       HandleLLMQuery);

    /* Error handler for unmatched routes */
    sServer->set_error_handler([](const httplib::Request& req, httplib::Response& res) {
        json j;
        j["error"] = "Not found: " + req.method + " " + req.path;
        res.status = 404;
        res.set_content(j.dump(), "application/json");
    });

    /* Start server on background thread — bind to localhost only */
    sServerRunning.store(true);

    sServerThread = std::thread([port]() {
        fprintf(stderr, "[IllTool] HTTP bridge starting on 127.0.0.1:%d...\n", port);
        if (!sServer->listen("127.0.0.1", port)) {
            fprintf(stderr, "[IllTool] ERROR: HTTP bridge failed to bind to 127.0.0.1:%d.\n", port);
            sServerRunning.store(false);
        }
        fprintf(stderr, "[IllTool] HTTP bridge stopped.\n");
    });

    /* Give the server a moment to bind — check it started */
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    if (!sServerRunning.load()) {
        fprintf(stderr, "[IllTool] ERROR: HTTP bridge failed to start.\n");
        if (sServerThread.joinable()) {
            sServerThread.join();
        }
        delete sServer;
        sServer = nullptr;
        return false;
    }

    fprintf(stderr, "[IllTool] HTTP bridge running on 127.0.0.1:%d.\n", port);
    return true;
}

void StopHttpBridge()
{
    if (!sServerRunning.load()) return;

    fprintf(stderr, "[IllTool] Stopping HTTP bridge...\n");

    sServerRunning.store(false);

    /* Wake any SSE waiters so they exit their loops */
    sEventCv.notify_all();

    /* Tell cpp-httplib to stop accepting connections */
    if (sServer) {
        sServer->stop();
    }

    /* Wait for the server thread to finish */
    if (sServerThread.joinable()) {
        sServerThread.join();
    }

    /* Clean up */
    delete sServer;
    sServer = nullptr;

    /* Drain the event queue */
    {
        std::lock_guard<std::mutex> lock(sEventMutex);
        std::queue<std::string> empty;
        sEventQueue.swap(empty);
    }

    fprintf(stderr, "[IllTool] HTTP bridge stopped and cleaned up.\n");
}
