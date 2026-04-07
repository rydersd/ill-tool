//========================================================================================
//
//  IllTool Plugin — HTTP Bridge implementation
//
//  Uses cpp-httplib (header-only) for the HTTP server.
//  Runs on a detached std::thread; communicates with the main thread
//  through the DrawCommands buffer (mutex-protected).
//
//========================================================================================

// Ensure OpenSSL support is NOT enabled (we only need plain HTTP on localhost)
#ifdef CPPHTTPLIB_OPENSSL_SUPPORT
#undef CPPHTTPLIB_OPENSSL_SUPPORT
#endif

#include "HttpBridge.h"
#include "IllToolPlugin.h"
#include "DrawCommands.h"
#include "LearningEngine.h"
#include "VisionEngine.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"

#include <thread>
#include <mutex>
#include <atomic>
#include <vector>
#include <string>
#include <cstdio>
#include <sstream>

using json = nlohmann::json;

//----------------------------------------------------------------------------------------
//  Globals
//----------------------------------------------------------------------------------------

static httplib::Server*         gServer     = nullptr;
static std::thread              gServerThread;
static std::atomic<bool>        gRunning{false};

// SSE client list
static std::mutex               gSSEMutex;
struct SSEClient {
    httplib::DataSink*  sink;
    bool                alive;
};
static std::vector<SSEClient>   gSSEClients;

// Tool mode
static std::mutex               gModeMutex;
static BridgeToolMode           gToolMode = BridgeToolMode::Lasso;

// Lasso close/clear request flags (set from HTTP or panel, consumed by TrackToolCursor)
static std::atomic<bool>        gLassoCloseRequested{false};
static std::atomic<bool>        gLassoClearRequested{false};

// Working mode apply/cancel request flags
static std::atomic<bool>        gWorkingApplyRequested{false};
static std::atomic<bool>        gWorkingApplyDeleteOriginals{true};
static std::atomic<bool>        gWorkingCancelRequested{false};

//----------------------------------------------------------------------------------------
//  CORS helper — adds headers to every response
//----------------------------------------------------------------------------------------

static void AddCorsHeaders(httplib::Response& res)
{
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type");
}

//----------------------------------------------------------------------------------------
//  Tool mode accessors
//----------------------------------------------------------------------------------------

void BridgeSetToolMode(BridgeToolMode mode)
{
    std::lock_guard<std::mutex> lock(gModeMutex);
    gToolMode = mode;
}

BridgeToolMode BridgeGetToolMode()
{
    std::lock_guard<std::mutex> lock(gModeMutex);
    return gToolMode;
}

//----------------------------------------------------------------------------------------
//  Lasso close/clear request accessors
//----------------------------------------------------------------------------------------

void BridgeRequestLassoClose()
{
    gLassoCloseRequested.store(true);
}

bool BridgeIsLassoCloseRequested()
{
    return gLassoCloseRequested.load();
}

void BridgeClearLassoCloseRequest()
{
    gLassoCloseRequested.store(false);
}

void BridgeRequestLassoClear()
{
    gLassoClearRequested.store(true);
}

bool BridgeIsLassoClearRequested()
{
    return gLassoClearRequested.load();
}

void BridgeClearLassoClearRequest()
{
    gLassoClearRequested.store(false);
}

//----------------------------------------------------------------------------------------
//  Working mode apply/cancel request accessors
//----------------------------------------------------------------------------------------

void BridgeRequestWorkingApply(bool deleteOriginals)
{
    gWorkingApplyDeleteOriginals.store(deleteOriginals);
    gWorkingApplyRequested.store(true);
}

bool BridgeIsWorkingApplyRequested()
{
    return gWorkingApplyRequested.load();
}

bool BridgeGetWorkingApplyDeleteOriginals()
{
    return gWorkingApplyDeleteOriginals.load();
}

void BridgeClearWorkingApplyRequest()
{
    gWorkingApplyRequested.store(false);
}

void BridgeRequestWorkingCancel()
{
    gWorkingCancelRequested.store(true);
}

bool BridgeIsWorkingCancelRequested()
{
    return gWorkingCancelRequested.load();
}

void BridgeClearWorkingCancelRequest()
{
    gWorkingCancelRequested.store(false);
}

//----------------------------------------------------------------------------------------
//  Average selection request
//----------------------------------------------------------------------------------------

static std::atomic<bool> gAverageSelectionRequested{false};

void BridgeRequestAverageSelection()  { gAverageSelectionRequested.store(true); }
bool BridgeIsAverageSelectionRequested() { return gAverageSelectionRequested.load(); }
void BridgeClearAverageSelectionRequest() { gAverageSelectionRequested.store(false); }

//----------------------------------------------------------------------------------------
//  Shape classification request
//----------------------------------------------------------------------------------------

static std::atomic<bool> gClassifyRequested{false};

void BridgeRequestClassify()          { gClassifyRequested.store(true); }
bool BridgeIsClassifyRequested()      { return gClassifyRequested.load(); }
void BridgeClearClassifyRequest()     { gClassifyRequested.store(false); }

//----------------------------------------------------------------------------------------
//  Shape reclassification request
//----------------------------------------------------------------------------------------

static std::atomic<bool>          gReclassifyRequested{false};
static std::atomic<int>           gReclassifyShapeType{0};

void BridgeRequestReclassify(BridgeShapeType shapeType) {
    gReclassifyShapeType.store(static_cast<int>(shapeType));
    gReclassifyRequested.store(true);
}

bool BridgeIsReclassifyRequested()    { return gReclassifyRequested.load(); }

BridgeShapeType BridgeGetReclassifyShapeType() {
    return static_cast<BridgeShapeType>(gReclassifyShapeType.load());
}

void BridgeClearReclassifyRequest()   { gReclassifyRequested.store(false); }

//----------------------------------------------------------------------------------------
//  Simplification request
//----------------------------------------------------------------------------------------

static std::atomic<bool>   gSimplifyRequested{false};
static std::atomic<double> gSimplifySliderValue{50.0};

void BridgeRequestSimplify(double sliderValue) {
    gSimplifySliderValue.store(sliderValue);
    gSimplifyRequested.store(true);
}

bool BridgeIsSimplifyRequested()      { return gSimplifyRequested.load(); }
double BridgeGetSimplifySliderValue() { return gSimplifySliderValue.load(); }
void BridgeClearSimplifyRequest()     { gSimplifyRequested.store(false); }

//----------------------------------------------------------------------------------------
//  Grouping operations (Stage 5)
//----------------------------------------------------------------------------------------

static std::atomic<bool>  gCopyToGroupRequested{false};
static std::mutex         gCopyToGroupMutex;
static std::string        gCopyToGroupName;

void BridgeRequestCopyToGroup(const std::string& groupName) {
    {
        std::lock_guard<std::mutex> lock(gCopyToGroupMutex);
        gCopyToGroupName = groupName;
    }
    gCopyToGroupRequested.store(true);
}

bool BridgeIsCopyToGroupRequested() { return gCopyToGroupRequested.load(); }

std::string BridgeGetCopyToGroupName() {
    std::lock_guard<std::mutex> lock(gCopyToGroupMutex);
    return gCopyToGroupName;
}

void BridgeClearCopyToGroupRequest() { gCopyToGroupRequested.store(false); }

static std::atomic<bool> gDetachRequested{false};

void BridgeRequestDetach()      { gDetachRequested.store(true); }
bool BridgeIsDetachRequested()  { return gDetachRequested.load(); }
void BridgeClearDetachRequest() { gDetachRequested.store(false); }

static std::atomic<bool> gSplitRequested{false};

void BridgeRequestSplit()       { gSplitRequested.store(true); }
bool BridgeIsSplitRequested()   { return gSplitRequested.load(); }
void BridgeClearSplitRequest()  { gSplitRequested.store(false); }

//----------------------------------------------------------------------------------------
//  Merge operations (Stage 6)
//----------------------------------------------------------------------------------------

static std::atomic<bool>   gScanEndpointsRequested{false};
static std::mutex          gScanToleranceMutex;
static double              gScanTolerance = 5.0;

void BridgeRequestScanEndpoints(double tolerance) {
    {
        std::lock_guard<std::mutex> lock(gScanToleranceMutex);
        gScanTolerance = tolerance;
    }
    gScanEndpointsRequested.store(true);
}

bool BridgeIsScanEndpointsRequested() { return gScanEndpointsRequested.load(); }

double BridgeGetScanTolerance() {
    std::lock_guard<std::mutex> lock(gScanToleranceMutex);
    return gScanTolerance;
}

void BridgeClearScanEndpointsRequest() { gScanEndpointsRequested.store(false); }

static std::atomic<bool> gMergeEndpointsRequested{false};
static std::atomic<bool> gMergeChainMerge{false};
static std::atomic<bool> gMergePreserveHandles{false};

void BridgeRequestMergeEndpoints(bool chainMerge, bool preserveHandles) {
    gMergeChainMerge.store(chainMerge);
    gMergePreserveHandles.store(preserveHandles);
    gMergeEndpointsRequested.store(true);
}

bool BridgeIsMergeEndpointsRequested() { return gMergeEndpointsRequested.load(); }
bool BridgeGetMergeChainMerge()        { return gMergeChainMerge.load(); }
bool BridgeGetMergePreserveHandles()   { return gMergePreserveHandles.load(); }
void BridgeClearMergeEndpointsRequest(){ gMergeEndpointsRequested.store(false); }

static std::atomic<bool> gUndoMergeRequested{false};

void BridgeRequestUndoMerge()      { gUndoMergeRequested.store(true); }
bool BridgeIsUndoMergeRequested()  { return gUndoMergeRequested.load(); }
void BridgeClearUndoMergeRequest() { gUndoMergeRequested.store(false); }

// Merge readout text — written from SDK context, read by panel timer
static std::mutex  gMergeReadoutMutex;
static std::string gMergeReadoutText = "0 pairs found, 0 paths";

void BridgeSetMergeReadout(const std::string& text) {
    std::lock_guard<std::mutex> lock(gMergeReadoutMutex);
    gMergeReadoutText = text;
}

std::string BridgeGetMergeReadout() {
    std::lock_guard<std::mutex> lock(gMergeReadoutMutex);
    return gMergeReadoutText;
}

//----------------------------------------------------------------------------------------
//  Smart select threshold (Stage 9)
//----------------------------------------------------------------------------------------

static std::atomic<double> gSmartThreshold{50.0};

void BridgeSetSmartThreshold(double value) { gSmartThreshold.store(value); }
double BridgeGetSmartThreshold()           { return gSmartThreshold.load(); }

//----------------------------------------------------------------------------------------
//  SSE event emitter
//----------------------------------------------------------------------------------------

void BridgeEmitEvent(const char* type, const std::string& id, double x, double y)
{
    json evt;
    evt["type"] = type;
    evt["id"]   = id;
    evt["x"]    = x;
    evt["y"]    = y;

    std::string data = "data: " + evt.dump() + "\n\n";

    std::lock_guard<std::mutex> lock(gSSEMutex);
    for (auto& client : gSSEClients) {
        if (client.alive && client.sink) {
            // Write returns false if the client disconnected
            if (!client.sink->write(data.data(), data.size())) {
                client.alive = false;
            }
        }
    }
}

//----------------------------------------------------------------------------------------
//  StartHttpBridge
//----------------------------------------------------------------------------------------

bool StartHttpBridge(int port)
{
    if (gRunning.load()) {
        fprintf(stderr, "[IllTool] HTTP bridge already running\n");
        return true;
    }

    gServer = new httplib::Server();

    // OPTIONS preflight for all routes
    gServer->Options("/(.*)", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        res.status = 204;
    });

    //------------------------------------------------------------------------------------
    //  POST /draw — receive draw commands
    //------------------------------------------------------------------------------------
    gServer->Post("/draw", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        auto commands = ParseDrawCommands(req.body);
        UpdateDrawCommands(std::move(commands));
        SetDirty(true);

        json resp;
        resp["ok"]    = true;
        resp["count"] = (int)GetDrawCommandCount();
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /clear — clear all draw commands
    //------------------------------------------------------------------------------------
    gServer->Post("/clear", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        UpdateDrawCommands({});
        SetDirty(true);

        json resp;
        resp["ok"]      = true;
        resp["count"]   = 0;
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  GET /status — plugin status
    //------------------------------------------------------------------------------------
    gServer->Get("/status", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);

        json resp;
        resp["version"]         = "0.1.0";
        resp["commandCount"]    = (int)GetDrawCommandCount();
        resp["annotatorActive"] = true;  // If HTTP is up, annotator is live

        std::string modeStr;
        {
            BridgeToolMode m = BridgeGetToolMode();
            modeStr = (m == BridgeToolMode::Lasso) ? "lasso" : "smart";
        }
        resp["toolMode"] = modeStr;

        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  GET /events — Server-Sent Events stream
    //------------------------------------------------------------------------------------
    gServer->Get("/events", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        res.set_header("Content-Type", "text/event-stream");
        res.set_header("Cache-Control", "no-cache");
        res.set_header("Connection", "keep-alive");

        // Use chunked content provider for SSE
        res.set_chunked_content_provider(
            "text/event-stream",
            [](size_t /*offset*/, httplib::DataSink& sink) -> bool {
                // Register this sink as an SSE client
                {
                    std::lock_guard<std::mutex> lock(gSSEMutex);
                    gSSEClients.push_back({&sink, true});
                }

                // Send initial keepalive
                std::string keepalive = ": keepalive\n\n";
                sink.write(keepalive.data(), keepalive.size());

                // Block until client disconnects or server stops
                // The sink.write() calls from BridgeEmitEvent push data
                while (gRunning.load()) {
                    std::this_thread::sleep_for(std::chrono::seconds(15));
                    // Periodic keepalive
                    std::string ka = ": keepalive\n\n";
                    if (!sink.write(ka.data(), ka.size())) {
                        break;  // Client disconnected
                    }
                }

                // Remove from client list
                {
                    std::lock_guard<std::mutex> lock(gSSEMutex);
                    for (auto it = gSSEClients.begin(); it != gSSEClients.end(); ++it) {
                        if (it->sink == &sink) {
                            gSSEClients.erase(it);
                            break;
                        }
                    }
                }
                return false;  // Done
            },
            [](bool /*success*/) {
                // Content provider done callback
            }
        );
    });

    //------------------------------------------------------------------------------------
    //  POST /tool/mode — set tool mode
    //------------------------------------------------------------------------------------
    gServer->Post("/tool/mode", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string mode = body.value("mode", "lasso");
            if (mode == "smart") {
                BridgeSetToolMode(BridgeToolMode::Smart);
            } else {
                BridgeSetToolMode(BridgeToolMode::Lasso);
            }
            json resp;
            resp["ok"]   = true;
            resp["mode"] = mode;
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  GET /tool/mode — get current tool mode
    //------------------------------------------------------------------------------------
    gServer->Get("/tool/mode", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeToolMode m = BridgeGetToolMode();
        json resp;
        resp["mode"] = (m == BridgeToolMode::Lasso) ? "lasso" : "smart";
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /lasso/close — close the polygon lasso and run selection
    //------------------------------------------------------------------------------------
    gServer->Post("/lasso/close", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestLassoClose();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool] HTTP /lasso/close requested\n");
    });

    //------------------------------------------------------------------------------------
    //  POST /lasso/clear — cancel/clear the polygon lasso
    //------------------------------------------------------------------------------------
    gServer->Post("/lasso/clear", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestLassoClear();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool] HTTP /lasso/clear requested\n");
    });

    //------------------------------------------------------------------------------------
    //  POST /cleanup/average — trigger Average Selection from the panel
    //------------------------------------------------------------------------------------
    gServer->Post("/cleanup/average", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        PluginAverageSelection();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool] HTTP /cleanup/average executed\n");
    });

    //------------------------------------------------------------------------------------
    //  POST /working/apply — apply working mode edits
    //------------------------------------------------------------------------------------
    gServer->Post("/working/apply", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        bool deleteOriginals = true;
        try {
            if (!req.body.empty()) {
                json body = json::parse(req.body);
                deleteOriginals = body.value("deleteOriginals", true);
            }
        } catch (...) {
            // Default to true if body parsing fails
        }
        BridgeRequestWorkingApply(deleteOriginals);
        json resp;
        resp["ok"] = true;
        resp["deleteOriginals"] = deleteOriginals;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool] HTTP /working/apply requested (deleteOriginals=%s)\n",
                deleteOriginals ? "true" : "false");
    });

    //------------------------------------------------------------------------------------
    //  POST /working/cancel — cancel working mode, discard duplicates
    //------------------------------------------------------------------------------------
    gServer->Post("/working/cancel", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestWorkingCancel();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool] HTTP /working/cancel requested\n");
    });

    //------------------------------------------------------------------------------------
    //  GET /learning/stats — learning engine statistics
    //------------------------------------------------------------------------------------
    gServer->Get("/learning/stats", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);

        LearningEngine& le = LearningEngine::Instance();
        json resp;
        resp["ok"]           = le.IsOpen();
        resp["total"]        = le.GetTotalInteractionCount();
        resp["shape_overrides"] = le.GetActionCount("shape_override");
        resp["simplify"]     = le.GetActionCount("simplify");
        resp["delete_noise"] = le.GetActionCount("delete_noise");
        resp["group"]        = le.GetActionCount("group");

        // Include current predictions for common surface types
        json predictions;
        const char* surfaces[] = {"flat", "cylindrical", "convex", "concave", "saddle"};
        for (const char* s : surfaces) {
            json p;
            std::string shape = le.PredictShape(s, 0, 0.0);
            double simplifyLevel = le.PredictSimplifyLevel(s);
            p["predicted_shape"] = shape.empty() ? nullptr : json(shape);
            p["predicted_simplify"] = (simplifyLevel < 0) ? nullptr : json(simplifyLevel);
            predictions[s] = p;
        }
        resp["predictions"] = predictions;

        double noiseThreshold = le.GetNoiseThreshold();
        resp["noise_threshold"] = (noiseThreshold < 0) ? nullptr : json(noiseThreshold);

        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /learning/predict-shape — predict shape for a surface type
    //------------------------------------------------------------------------------------
    gServer->Post("/learning/predict-shape", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string surfaceType = body.value("surface_type", "");

            LearningEngine& le = LearningEngine::Instance();
            std::string shape = le.PredictShape(surfaceType.c_str(), 0, 0.0);

            // Compute confidence: count for this shape / total shape overrides for this surface
            double confidence = 0.0;
            int totalOverrides = le.GetActionCount("shape_override");
            if (totalOverrides > 0 && !shape.empty()) {
                // Rough confidence based on sample count (caps at 0.95 with 20+ samples)
                int count = totalOverrides; // conservative estimate
                confidence = 1.0 - (1.0 / (1.0 + count * 0.15));
                if (confidence > 0.95) confidence = 0.95;
            }

            json resp;
            resp["ok"] = true;
            resp["shape"] = shape.empty() ? nullptr : json(shape);
            resp["confidence"] = shape.empty() ? 0.0 : confidence;
            resp["surface_type"] = surfaceType;
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  GET /learning/noise-threshold — learned noise threshold
    //------------------------------------------------------------------------------------
    gServer->Get("/learning/noise-threshold", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        LearningEngine& le = LearningEngine::Instance();
        double threshold = le.GetNoiseThreshold();

        json resp;
        resp["ok"] = true;
        resp["threshold"] = (threshold < 0) ? nullptr : json(threshold);
        resp["has_data"] = (threshold >= 0);
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/load — load image into vision engine
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/load", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            std::string imagePath = body.value("image_path", "");

            if (imagePath.empty()) {
                json resp;
                resp["ok"]    = false;
                resp["error"] = "image_path is required";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }

            VisionEngine& ve = VisionEngine::Instance();
            bool loaded = ve.LoadImage(imagePath.c_str());

            json resp;
            resp["ok"]     = loaded;
            resp["width"]  = ve.Width();
            resp["height"] = ve.Height();
            if (!loaded) {
                resp["error"] = "Failed to load image";
                res.status = 400;
            }
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  GET /vision/status — vision engine status
    //------------------------------------------------------------------------------------
    gServer->Get("/vision/status", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        json resp;
        resp["loaded"] = ve.IsLoaded();
        resp["width"]  = ve.Width();
        resp["height"] = ve.Height();
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/edges — run edge detection and return contours
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/edges", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);
            std::string method = body.value("method", "canny");

            std::vector<uint8_t> edges;

            if (method == "canny") {
                double low  = body.value("low", 50.0);
                double high = body.value("high", 150.0);
                edges = ve.CannyEdges(low, high);
            } else if (method == "sobel") {
                double threshold = body.value("threshold", 128.0);
                edges = ve.SobelEdges(threshold);
            } else if (method == "multiscale") {
                int numScales      = body.value("num_scales", 5);
                double voteThresh  = body.value("vote_threshold", 3.0);
                edges = ve.MultiScaleEdges(numScales, voteThresh);
            } else {
                json resp;
                resp["ok"]    = false;
                resp["error"] = "Unknown method: " + method;
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }

            // Extract contours from edges
            int minLength = body.value("min_length", 10);
            auto contours = ve.FindContours(edges, ve.Width(), ve.Height(), minLength);

            // Also run Douglas-Peucker if requested
            double simplifyEpsilon = body.value("simplify", 0.0);

            // Convert contours to JSON
            json contoursJson = json::array();
            for (const auto& c : contours) {
                json cj;

                auto pts = c.points;
                if (simplifyEpsilon > 0.0) {
                    pts = VisionEngine::DouglasPeucker(pts, simplifyEpsilon);
                }

                json pointsJson = json::array();
                for (const auto& p : pts) {
                    json pj;
                    pj["x"] = p.first;
                    pj["y"] = p.second;
                    pointsJson.push_back(pj);
                }
                cj["points"]    = pointsJson;
                cj["area"]      = c.area;
                cj["arcLength"] = c.arcLength;
                cj["closed"]    = c.closed;
                contoursJson.push_back(cj);
            }

            json resp;
            resp["ok"]       = true;
            resp["method"]   = method;
            resp["contours"] = contoursJson;
            resp["count"]    = (int)contours.size();
            resp["edge_pixels"] = 0;
            // Count edge pixels
            int edgeCount = 0;
            for (auto v : edges) { if (v) ++edgeCount; }
            resp["edge_pixels"] = edgeCount;
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/detect-lines — Hough line detection
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/detect-lines", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);
            double rhoRes   = body.value("rho_res", 1.0);
            double thetaRes = body.value("theta_res", M_PI / 180.0);
            int threshold   = body.value("threshold", 50);
            double edgeLow  = body.value("edge_low", 50.0);
            double edgeHigh = body.value("edge_high", 150.0);

            // First run edge detection
            auto edges = ve.CannyEdges(edgeLow, edgeHigh);
            auto lines = ve.DetectLines(edges, rhoRes, thetaRes, threshold);

            json linesJson = json::array();
            for (const auto& l : lines) {
                json lj;
                lj["rho"]   = l.rho;
                lj["theta"] = l.theta;
                lj["votes"] = l.votes;
                // Also provide endpoint form for convenience
                double a = std::cos(l.theta);
                double b = std::sin(l.theta);
                double x0 = a * l.rho;
                double y0 = b * l.rho;
                lj["x1"] = x0 + 1000.0 * (-b);
                lj["y1"] = y0 + 1000.0 * a;
                lj["x2"] = x0 - 1000.0 * (-b);
                lj["y2"] = y0 - 1000.0 * a;
                linesJson.push_back(lj);
            }

            json resp;
            resp["ok"]    = true;
            resp["lines"] = linesJson;
            resp["count"] = (int)lines.size();
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/detect-circles — Hough circle detection
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/detect-circles", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);
            double minRadius = body.value("min_radius", 5.0);
            double maxRadius = body.value("max_radius", 100.0);
            int threshold    = body.value("threshold", 30);
            double edgeLow   = body.value("edge_low", 50.0);
            double edgeHigh  = body.value("edge_high", 150.0);

            auto edges   = ve.CannyEdges(edgeLow, edgeHigh);
            auto circles = ve.DetectCircles(edges, minRadius, maxRadius, threshold);

            json circlesJson = json::array();
            for (const auto& c : circles) {
                json cj;
                cj["cx"]     = c.cx;
                cj["cy"]     = c.cy;
                cj["radius"] = c.radius;
                cj["votes"]  = c.votes;
                circlesJson.push_back(cj);
            }

            json resp;
            resp["ok"]      = true;
            resp["circles"] = circlesJson;
            resp["count"]   = (int)circles.size();
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/suggest-groups — learning-integrated grouping suggestions
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/suggest-groups", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);
            double edgeLow     = body.value("edge_low", 50.0);
            double edgeHigh    = body.value("edge_high", 150.0);
            int minLength      = body.value("min_length", 10);
            double simplifyEps = body.value("simplify", 2.0);

            // Run edge detection and contour extraction
            auto edges    = ve.CannyEdges(edgeLow, edgeHigh);
            auto contours = ve.FindContours(edges, ve.Width(), ve.Height(), minLength);

            // Detect noise
            auto noiseIndices = ve.DetectNoise(contours);

            // Suggest groups
            auto groups = ve.SuggestGroups(contours);

            // Build response
            json noiseJson = json::array();
            for (int idx : noiseIndices) {
                noiseJson.push_back(idx);
            }

            json groupsJson = json::array();
            for (const auto& g : groups) {
                json gj;
                gj["name"]       = g.suggestedName;
                gj["confidence"] = g.confidence;
                json membersJson = json::array();
                for (int idx : g.memberIndices) {
                    membersJson.push_back(idx);
                }
                gj["members"] = membersJson;
                gj["size"]    = (int)g.memberIndices.size();
                groupsJson.push_back(gj);
            }

            json resp;
            resp["ok"]              = true;
            resp["total_contours"]  = (int)contours.size();
            resp["noise_indices"]   = noiseJson;
            resp["noise_count"]     = (int)noiseIndices.size();
            resp["groups"]          = groupsJson;
            resp["group_count"]     = (int)groups.size();
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/snap-to-edge — active contour snapping
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/snap-to-edge", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);

            // Parse input points
            std::vector<std::pair<double,double>> inputPoints;
            if (body.contains("points") && body["points"].is_array()) {
                for (const auto& pj : body["points"]) {
                    double x = pj.value("x", 0.0);
                    double y = pj.value("y", 0.0);
                    inputPoints.push_back({x, y});
                }
            }

            if (inputPoints.size() < 3) {
                json resp;
                resp["ok"]    = false;
                resp["error"] = "Need at least 3 points";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }

            double alpha      = body.value("alpha", 1.0);
            double beta       = body.value("beta", 1.0);
            double gamma      = body.value("gamma", 1.0);
            int iterations    = body.value("iterations", 50);
            double simplifyEps = body.value("simplify", 0.0);

            auto snapped = ve.SnapToEdge(inputPoints, alpha, beta, gamma, iterations);

            if (simplifyEps > 0.0) {
                snapped = VisionEngine::DouglasPeucker(snapped, simplifyEps);
            }

            json pointsJson = json::array();
            for (const auto& p : snapped) {
                json pj;
                pj["x"] = p.first;
                pj["y"] = p.second;
                pointsJson.push_back(pj);
            }

            json resp;
            resp["ok"]              = true;
            resp["points"]          = pointsJson;
            resp["point_count"]     = (int)snapped.size();
            resp["input_count"]     = (int)inputPoints.size();
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/flood-fill — flood fill from seed point
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/flood-fill", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();

        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }

        try {
            json body = json::parse(req.body);
            int seedX     = body.value("seed_x", 0);
            int seedY     = body.value("seed_y", 0);
            int tolerance = body.value("tolerance", 10);

            auto mask = ve.FloodFillMask(seedX, seedY, tolerance);

            // Count filled pixels
            int filledCount = 0;
            for (auto v : mask) { if (v) ++filledCount; }

            // Optionally extract contours from the mask
            bool extractContours = body.value("extract_contours", false);
            json contoursJson = json::array();
            if (extractContours && !mask.empty()) {
                int minLength = body.value("min_length", 10);
                auto contours = ve.FindContours(mask, ve.Width(), ve.Height(), minLength);
                for (const auto& c : contours) {
                    json cj;
                    json pointsJson = json::array();
                    for (const auto& p : c.points) {
                        json pj;
                        pj["x"] = p.first;
                        pj["y"] = p.second;
                        pointsJson.push_back(pj);
                    }
                    cj["points"]    = pointsJson;
                    cj["area"]      = c.area;
                    cj["arcLength"] = c.arcLength;
                    cj["closed"]    = c.closed;
                    contoursJson.push_back(cj);
                }
            }

            json resp;
            resp["ok"]           = true;
            resp["filled_pixels"] = filledCount;
            resp["total_pixels"]  = ve.Width() * ve.Height();
            if (extractContours) {
                resp["contours"] = contoursJson;
            }
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"]    = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  Launch server on detached thread
    //------------------------------------------------------------------------------------
    gRunning.store(true);
    gServerThread = std::thread([port]() {
        fprintf(stderr, "[IllTool] HTTP server thread starting on 127.0.0.1:%d\n", port);
        if (!gServer->listen("127.0.0.1", port)) {
            fprintf(stderr, "[IllTool] HTTP server failed to bind to port %d\n", port);
        }
        fprintf(stderr, "[IllTool] HTTP server thread exiting\n");
        gRunning.store(false);
    });
    gServerThread.detach();

    fprintf(stderr, "[IllTool] HTTP bridge started on 127.0.0.1:%d\n", port);
    return true;
}

//----------------------------------------------------------------------------------------
//  StopHttpBridge
//----------------------------------------------------------------------------------------

void StopHttpBridge()
{
    if (!gRunning.load() && gServer == nullptr) {
        return;
    }

    fprintf(stderr, "[IllTool] Stopping HTTP bridge...\n");
    gRunning.store(false);

    if (gServer) {
        gServer->stop();
        // Thread is detached, so we just delete the server
        // after stopping — the thread will exit its listen() call
        delete gServer;
        gServer = nullptr;
    }

    // Clear SSE clients
    {
        std::lock_guard<std::mutex> lock(gSSEMutex);
        gSSEClients.clear();
    }

    fprintf(stderr, "[IllTool] HTTP bridge stopped\n");
}
