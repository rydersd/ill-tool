//========================================================================================
//
//  IllTool Plugin — HTTP Bridge implementation
//
//  Uses cpp-httplib (header-only) for the HTTP server.
//  Runs on a joinable std::thread; communicates with the main thread
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
#include <future>
#include <vector>
#include <deque>
#include <string>
#include <cstdio>
#include <sstream>

using json = nlohmann::json;

//========================================================================================
//  H1: Operation Queue
//========================================================================================

static std::mutex gOpMutex;
static std::deque<PluginOp> gOpQueue;

void BridgeEnqueueOp(PluginOp op) {
    std::lock_guard<std::mutex> lock(gOpMutex);
    gOpQueue.push_back(std::move(op));
}

bool BridgeDequeueOp(PluginOp& out) {
    std::lock_guard<std::mutex> lock(gOpMutex);
    if (gOpQueue.empty()) return false;
    out = std::move(gOpQueue.front());
    gOpQueue.pop_front();
    return true;
}

//========================================================================================
//  H2: Result Queue
//========================================================================================

static std::mutex gResultMutex;
static std::deque<PluginResult> gResultQueue;

void BridgePostResult(PluginResult result) {
    std::lock_guard<std::mutex> lock(gResultMutex);
    gResultQueue.push_back(std::move(result));
}

bool BridgePollResult(PluginResult& out) {
    std::lock_guard<std::mutex> lock(gResultMutex);
    if (gResultQueue.empty()) return false;
    out = std::move(gResultQueue.front());
    gResultQueue.pop_front();
    return true;
}

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

// Tool mode (continuous state — NOT an operation)
static std::mutex               gModeMutex;
static BridgeToolMode           gToolMode = BridgeToolMode::Lasso;

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
//  Operation request wrappers (H1: enqueue into operation queue)
//  The BridgeRequest* API is preserved for callers (panels, HTTP endpoints).
//  Deprecated BridgeIs*Requested, BridgeClear*, and BridgeGet* param accessors
//  have been removed — the H1 queue handles the full lifecycle.
//----------------------------------------------------------------------------------------

// Lasso
void BridgeRequestLassoClose()          { BridgeEnqueueOp({OpType::LassoClose}); }
void BridgeRequestLassoClear()          { BridgeEnqueueOp({OpType::LassoClear}); }

// Working mode
void BridgeRequestWorkingApply(bool deleteOriginals) {
    BridgeEnqueueOp({OpType::WorkingApply, 0, 0, 0, deleteOriginals});
}
void BridgeRequestWorkingCancel()       { BridgeEnqueueOp({OpType::WorkingCancel}); }

// Average selection
void BridgeRequestAverageSelection()       { BridgeEnqueueOp({OpType::AverageSelection}); }

// Shape classification
void BridgeRequestClassify()          { BridgeEnqueueOp({OpType::Classify}); }

// Shape reclassification
void BridgeRequestReclassify(BridgeShapeType shapeType) {
    BridgeEnqueueOp({OpType::Reclassify, 0, 0, static_cast<int>(shapeType)});
}

// Simplification
void BridgeRequestSimplify(double sliderValue) {
    BridgeEnqueueOp({OpType::Simplify, sliderValue});
}

// Grouping: Copy to Group
void BridgeRequestCopyToGroup(const std::string& groupName) {
    PluginOp op{OpType::CopyToGroup};
    op.strParam = groupName;
    BridgeEnqueueOp(std::move(op));
}

// Grouping: Detach
void BridgeRequestDetach()      { BridgeEnqueueOp({OpType::Detach}); }

// Grouping: Split
void BridgeRequestSplit()       { BridgeEnqueueOp({OpType::Split}); }

// Merge: Scan Endpoints
void BridgeRequestScanEndpoints(double tolerance) {
    BridgeEnqueueOp({OpType::ScanEndpoints, tolerance});
}

// Merge: Merge Endpoints
void BridgeRequestMergeEndpoints(bool chainMerge, bool preserveHandles) {
    BridgeEnqueueOp({OpType::MergeEndpoints, 0, 0, 0, chainMerge, preserveHandles});
}

// Merge: Undo Merge
void BridgeRequestUndoMerge()      { BridgeEnqueueOp({OpType::UndoMerge}); }

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
//  Curve tension (Gap 2 — controls bezier handle length in ReclassifyAs)
//----------------------------------------------------------------------------------------

static std::atomic<double> gTension{50.0};  // 0-100, default midpoint

void BridgeSetTension(double value) { gTension.store(value); }
double BridgeGetTension()           { return gTension.load(); }

//----------------------------------------------------------------------------------------
//  Add to Selection toggle (Gap 4 — shift-select mode for polygon lasso)
//----------------------------------------------------------------------------------------

static std::atomic<bool> gAddToSelection{false};

void BridgeSetAddToSelection(bool enabled) { gAddToSelection.store(enabled); }
bool BridgeGetAddToSelection()             { return gAddToSelection.load(); }

//----------------------------------------------------------------------------------------
//  Select Small (H1: queue-based)
//----------------------------------------------------------------------------------------

void BridgeRequestSelectSmall(double threshold) {
    BridgeEnqueueOp({OpType::SelectSmall, threshold});
}

//----------------------------------------------------------------------------------------
//  Surface hint (continuous state — NOT an operation, kept as-is)
//----------------------------------------------------------------------------------------

static std::atomic<int>    gSurfaceType{-1};
static std::atomic<double> gSurfaceConfidence{0.0};
static std::atomic<double> gSurfaceGradientAngle{0.0};

void BridgeSetSurfaceHint(int surfaceType, double confidence, double gradientAngle) {
    gSurfaceType.store(surfaceType);
    gSurfaceConfidence.store(confidence);
    gSurfaceGradientAngle.store(gradientAngle);
}
int    BridgeGetSurfaceType()       { return gSurfaceType.load(); }
double BridgeGetSurfaceConfidence() { return gSurfaceConfidence.load(); }
double BridgeGetGradientAngle()     { return gSurfaceGradientAngle.load(); }

//----------------------------------------------------------------------------------------
//  Shape undo (H1: queue-based)
//----------------------------------------------------------------------------------------

void BridgeRequestUndoShape()       { BridgeEnqueueOp({OpType::UndoShape}); }

//----------------------------------------------------------------------------------------
//  Perspective grid line state (Stage 10) — continuous state, mutex-protected
//----------------------------------------------------------------------------------------

static std::mutex gPerspMutex;
static BridgePerspectiveLine gPerspLines[3];   // 0=left, 1=right, 2=vertical
static double gPerspHorizonY = 400.0;
static bool   gPerspLocked = false;

void BridgeSetPerspectiveLine(int lineIndex, double h1x, double h1y, double h2x, double h2y) {
    if (lineIndex < 0 || lineIndex > 2) return;
    std::lock_guard<std::mutex> lock(gPerspMutex);
    gPerspLines[lineIndex] = {h1x, h1y, h2x, h2y, true};
    fprintf(stderr, "[IllTool Bridge] SetPerspectiveLine(%d) h1=[%.0f,%.0f] h2=[%.0f,%.0f]\n",
            lineIndex, h1x, h1y, h2x, h2y);
}

void BridgeClearPerspectiveLine(int lineIndex) {
    if (lineIndex < 0 || lineIndex > 2) return;
    std::lock_guard<std::mutex> lock(gPerspMutex);
    gPerspLines[lineIndex] = {};
}

BridgePerspectiveLine BridgeGetPerspectiveLine(int lineIndex) {
    if (lineIndex < 0 || lineIndex > 2) return {};
    std::lock_guard<std::mutex> lock(gPerspMutex);
    return gPerspLines[lineIndex];
}

void BridgeSetHorizonY(double y) {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    gPerspHorizonY = y;
}

double BridgeGetHorizonY() {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    return gPerspHorizonY;
}

void BridgeSetPerspectiveLocked(bool locked) {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    gPerspLocked = locked;
}

bool BridgeGetPerspectiveLocked() {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    return gPerspLocked;
}

static bool gPerspVisible = true;

void BridgeSetPerspectiveVisible(bool visible) {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    gPerspVisible = visible;
}

bool BridgeGetPerspectiveVisible() {
    std::lock_guard<std::mutex> lock(gPerspMutex);
    return gPerspVisible;
}

//----------------------------------------------------------------------------------------
//  Blend state (Stage 11)
//----------------------------------------------------------------------------------------

static std::atomic<int>  gBlendSteps{5};
static std::atomic<int>  gBlendEasing{0};
static std::atomic<int>  gBlendPickMode{0};   // 0=none, 1=pickA, 2=pickB
static std::atomic<bool> gBlendHasPathA{false};
static std::atomic<bool> gBlendHasPathB{false};

void BridgeSetBlendSteps(int steps)    { gBlendSteps.store(steps); }
int  BridgeGetBlendSteps()             { return gBlendSteps.load(); }
void BridgeSetBlendEasing(int preset)  { gBlendEasing.store(preset); }
int  BridgeGetBlendEasing()            { return gBlendEasing.load(); }
// Custom easing control points (for preset 4)
static std::mutex gCustomEasingMutex;
static std::vector<double> gCustomEasingXY;  // [x1,y1,x2,y2,...] pairs

void BridgeSetCustomEasingPoints(int count, const double* xyPairs) {
    std::lock_guard<std::mutex> lock(gCustomEasingMutex);
    gCustomEasingXY.assign(xyPairs, xyPairs + count * 2);
}

int BridgeGetCustomEasingPoints(double* xyPairs, int maxPairs) {
    std::lock_guard<std::mutex> lock(gCustomEasingMutex);
    int count = (int)(gCustomEasingXY.size() / 2);
    if (count > maxPairs) count = maxPairs;
    for (int i = 0; i < count * 2; i++) xyPairs[i] = gCustomEasingXY[i];
    return count;
}

void BridgeSetBlendPickMode(int mode)  { gBlendPickMode.store(mode); }
int  BridgeGetBlendPickMode()          { return gBlendPickMode.load(); }
bool BridgeHasBlendPathA()             { return gBlendHasPathA.load(); }
bool BridgeHasBlendPathB()             { return gBlendHasPathB.load(); }
void BridgeSetBlendPathASet(bool set)  { gBlendHasPathA.store(set); }
void BridgeSetBlendPathBSet(bool set)  { gBlendHasPathB.store(set); }

//----------------------------------------------------------------------------------------
//  Shading state (Stage 12) — continuous state, mutex-protected
//----------------------------------------------------------------------------------------

static std::atomic<int> gShadingMode{0};  // 0=blend, 1=mesh

static std::mutex gShadingColorMutex;
static double gShadingHighR = 1.0, gShadingHighG = 1.0, gShadingHighB = 1.0;
static double gShadingShadR = 0.0, gShadingShadG = 0.0, gShadingShadB = 0.0;

static std::atomic<double> gShadingLightAngle{315.0};  // degrees, 0=right, CCW
static std::atomic<double> gShadingIntensity{70.0};     // 0-100
static std::atomic<int>    gShadingBlendSteps{7};       // 3-15
static std::atomic<int>    gShadingMeshGrid{3};         // 2-6

void BridgeSetShadingMode(int mode)       { gShadingMode.store(mode); }
int  BridgeGetShadingMode()               { return gShadingMode.load(); }

void BridgeSetShadingHighlight(double r, double g, double b) {
    std::lock_guard<std::mutex> lock(gShadingColorMutex);
    gShadingHighR = r; gShadingHighG = g; gShadingHighB = b;
}
void BridgeGetShadingHighlight(double& r, double& g, double& b) {
    std::lock_guard<std::mutex> lock(gShadingColorMutex);
    r = gShadingHighR; g = gShadingHighG; b = gShadingHighB;
}

void BridgeSetShadingShadow(double r, double g, double b) {
    std::lock_guard<std::mutex> lock(gShadingColorMutex);
    gShadingShadR = r; gShadingShadG = g; gShadingShadB = b;
}
void BridgeGetShadingShadow(double& r, double& g, double& b) {
    std::lock_guard<std::mutex> lock(gShadingColorMutex);
    r = gShadingShadR; g = gShadingShadG; b = gShadingShadB;
}

void BridgeSetShadingLightAngle(double angle) { gShadingLightAngle.store(angle); }
double BridgeGetShadingLightAngle()           { return gShadingLightAngle.load(); }

void BridgeSetShadingIntensity(double intensity) { gShadingIntensity.store(intensity); }
double BridgeGetShadingIntensity()               { return gShadingIntensity.load(); }

void BridgeSetShadingBlendSteps(int steps) { gShadingBlendSteps.store(steps); }
int  BridgeGetShadingBlendSteps()          { return gShadingBlendSteps.load(); }

void BridgeSetShadingMeshGrid(int size) { gShadingMeshGrid.store(size); }
int  BridgeGetShadingMeshGrid()         { return gShadingMeshGrid.load(); }

//----------------------------------------------------------------------------------------
//  Decompose state (Stage 14)
//----------------------------------------------------------------------------------------

static std::mutex  gDecomposeReadoutMutex;
static std::string gDecomposeReadoutText = "---";
static std::atomic<float> gDecomposeSensitivity{0.5f};

void BridgeSetDecomposeReadout(const std::string& text) {
    std::lock_guard<std::mutex> lock(gDecomposeReadoutMutex);
    gDecomposeReadoutText = text;
}

std::string BridgeGetDecomposeReadout() {
    std::lock_guard<std::mutex> lock(gDecomposeReadoutMutex);
    return gDecomposeReadoutText;
}

void BridgeSetDecomposeSensitivity(float value) { gDecomposeSensitivity.store(value); }
float BridgeGetDecomposeSensitivity()           { return gDecomposeSensitivity.load(); }

//----------------------------------------------------------------------------------------
//  Perspective mirror/duplicate/paste state (Stage 10b-d)
//----------------------------------------------------------------------------------------

static std::atomic<int>   gMirrorAxis{0};        // 0=vertical, 1=horizontal, 2=custom
static std::atomic<bool>  gMirrorReplace{false};
static std::atomic<int>   gDuplicateCount{3};
static std::atomic<int>   gDuplicateSpacing{0};   // 0=equal in perspective, 1=equal on screen
static std::atomic<int>   gPastePlane{0};          // 0=floor, 1=left wall, 2=right wall, 3=custom
static std::atomic<float> gPasteScale{1.0f};

void BridgeSetMirrorAxis(int axis)        { gMirrorAxis.store(axis); }
int  BridgeGetMirrorAxis()                { return gMirrorAxis.load(); }
void BridgeSetMirrorReplace(bool replace) { gMirrorReplace.store(replace); }
bool BridgeGetMirrorReplace()             { return gMirrorReplace.load(); }
void BridgeSetDuplicateCount(int count)   { gDuplicateCount.store(count); }
int  BridgeGetDuplicateCount()            { return gDuplicateCount.load(); }
void BridgeSetDuplicateSpacing(int spacing) { gDuplicateSpacing.store(spacing); }
int  BridgeGetDuplicateSpacing()          { return gDuplicateSpacing.load(); }
void BridgeSetPastePlane(int plane)       { gPastePlane.store(plane); }
int  BridgeGetPastePlane()                { return gPastePlane.load(); }
void BridgeSetPasteScale(float scale)     { gPasteScale.store(scale); }
float BridgeGetPasteScale()               { return gPasteScale.load(); }

void BridgeRequestMirrorPerspective(int axis, bool replace) {
    PluginOp op{OpType::MirrorPerspective};
    op.intParam = axis;
    op.boolParam1 = replace;
    BridgeEnqueueOp(op);
}

void BridgeRequestDuplicatePerspective(int count, int spacing) {
    PluginOp op{OpType::DuplicatePerspective};
    op.intParam = count;
    op.param1 = (double)spacing;
    BridgeEnqueueOp(op);
}

void BridgeRequestPastePerspective(int plane, float scale) {
    PluginOp op{OpType::PastePerspective};
    op.intParam = plane;
    op.param1 = (double)scale;
    BridgeEnqueueOp(op);
}

void BridgeRequestPerspectiveSave() { BridgeEnqueueOp({OpType::PerspectiveSave}); }
void BridgeRequestPerspectiveLoad() { BridgeEnqueueOp({OpType::PerspectiveLoad}); }

//----------------------------------------------------------------------------------------
//  Decompose request wrappers (Stage 14) — state lives above with readout
//----------------------------------------------------------------------------------------

void BridgeRequestDecompose(float sensitivity) {
    PluginOp op{OpType::Decompose};
    op.param1 = (double)sensitivity;
    BridgeEnqueueOp(op);
}
void BridgeRequestDecomposeAccept()     { BridgeEnqueueOp({OpType::DecomposeAccept}); }
void BridgeRequestDecomposeAcceptOne(int clusterIndex) {
    PluginOp op{OpType::DecomposeAcceptOne};
    op.intParam = clusterIndex;
    BridgeEnqueueOp(op);
}
void BridgeRequestDecomposeSplit(int clusterIndex) {
    PluginOp op{OpType::DecomposeSplit};
    op.intParam = clusterIndex;
    BridgeEnqueueOp(op);
}
void BridgeRequestDecomposeMergeGroups(int clusterA, int clusterB) {
    PluginOp op{OpType::DecomposeMergeGroups};
    op.intParam = clusterA;
    op.param1 = (double)clusterB;
    BridgeEnqueueOp(op);
}
void BridgeRequestDecomposeCancel()    { BridgeEnqueueOp({OpType::DecomposeCancel}); }

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
        BridgeRequestAverageSelection();
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
    //  POST /vision/set-mapping — set artwork-to-pixel coordinate mapping
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/set-mapping", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            double artLeft   = body.value("art_left", 0.0);
            double artTop    = body.value("art_top", 0.0);
            double artRight  = body.value("art_right", 0.0);
            double artBottom = body.value("art_bottom", 0.0);

            VisionEngine::Instance().SetArtToPixelMapping(artLeft, artTop, artRight, artBottom);

            json resp;
            resp["ok"] = true;
            resp["mapping_valid"] = VisionEngine::Instance().GetMapping().valid;
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
    //  GET /vision/surface-hint — get last computed surface hint
    //------------------------------------------------------------------------------------
    gServer->Get("/vision/surface-hint", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        const char* typeNames[] = {"flat", "convex", "concave", "saddle", "cylindrical"};
        int st = BridgeGetSurfaceType();
        json resp;
        resp["ok"] = true;
        resp["surface_type"] = (st >= 0 && st <= 4) ? typeNames[st] : "unknown";
        resp["surface_type_id"] = st;
        resp["confidence"]      = BridgeGetSurfaceConfidence();
        resp["gradient_angle"]  = BridgeGetGradientAngle();
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /vision/infer-surface — infer surface type for a region
    //------------------------------------------------------------------------------------
    gServer->Post("/vision/infer-surface", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        VisionEngine& ve = VisionEngine::Instance();
        if (!ve.IsLoaded()) {
            json resp;
            resp["ok"] = false;
            resp["error"] = "No image loaded";
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
            return;
        }
        try {
            json body = json::parse(req.body);
            int px = body.value("x", 0);
            int py = body.value("y", 0);
            int pw = body.value("w", 100);
            int ph = body.value("h", 100);

            auto hint = ve.InferSurfaceType(px, py, pw, ph);

            const char* typeNames[] = {"flat", "convex", "concave", "saddle", "cylindrical"};
            int st = (int)hint.type;
            json resp;
            resp["ok"] = true;
            resp["surface_type"] = (st >= 0 && st <= 4) ? typeNames[st] : "unknown";
            resp["surface_type_id"] = st;
            resp["confidence"] = hint.confidence;
            resp["gradient_angle"] = hint.gradientAngle;
            res.set_content(resp.dump(), "application/json");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  Perspective Grid endpoints (Stage 10) — line-based model
    //------------------------------------------------------------------------------------

    gServer->Post("/perspective/set-line", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int index = body.value("index", 0);
            double h1x = body.value("h1x", 0.0);
            double h1y = body.value("h1y", 0.0);
            double h2x = body.value("h2x", 0.0);
            double h2y = body.value("h2y", 0.0);
            if (index < 0 || index > 2) {
                json resp;
                resp["ok"] = false;
                resp["error"] = "index must be 0-2";
                res.status = 400;
                res.set_content(resp.dump(), "application/json");
                return;
            }
            BridgeSetPerspectiveLine(index, h1x, h1y, h2x, h2y);
            json resp;
            resp["ok"] = true;
            resp["index"] = index;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /perspective/set-line index=%d\n", index);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/perspective/clear-line", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int index = body.value("index", 0);
            BridgeClearPerspectiveLine(index);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /perspective/clear-line index=%d\n", index);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/perspective/clear", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        PluginOp op;
        op.type = OpType::ClearPerspective;
        BridgeEnqueueOp(op);
        for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);
        BridgeSetPerspectiveLocked(false);
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool HTTP] POST /perspective/clear\n");
    });

    gServer->Post("/perspective/horizon", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            double y = body.value("y", 400.0);
            BridgeSetHorizonY(y);
            json resp;
            resp["ok"] = true;
            resp["horizon_y"] = y;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /perspective/horizon y=%.0f\n", y);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/perspective/lock", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            bool lock = body.value("locked", true);
            BridgeSetPerspectiveLocked(lock);
            PluginOp op;
            op.type = OpType::LockPerspective;
            op.boolParam1 = lock;
            BridgeEnqueueOp(op);
            json resp;
            resp["ok"] = true;
            resp["locked"] = lock;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /perspective/lock locked=%d\n", (int)lock);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Get("/perspective/status", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        // Read ONLY from thread-safe bridge state — never touch gPlugin directly (P0/P1 fix)
        json resp;
        int activeCount = 0;
        for (int i = 0; i < 3; i++) {
            BridgePerspectiveLine bl = BridgeGetPerspectiveLine(i);
            std::string key = (i == 0) ? "left_vp" : (i == 1) ? "right_vp" : "vertical_vp";
            if (bl.active) {
                activeCount++;
                resp[key] = {
                    {"active", true},
                    {"h1", {{"x", bl.h1x}, {"y", bl.h1y}}},
                    {"h2", {{"x", bl.h2x}, {"y", bl.h2y}}}
                };
            } else {
                resp[key] = {{"active", false}};
            }
        }
        resp["line_count"] = activeCount;
        resp["valid"] = (activeCount >= 2);
        resp["locked"] = BridgeGetPerspectiveLocked();
        resp["visible"] = BridgeGetPerspectiveVisible();
        resp["horizon_y"] = BridgeGetHorizonY();
        res.set_content(resp.dump(), "application/json");
    });

    gServer->Post("/perspective/density", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int density = body.value("density", 5);
            PluginOp op;
            op.type = OpType::SetGridDensity;
            op.intParam = density;
            BridgeEnqueueOp(op);
            json resp;
            resp["ok"] = true;
            resp["density"] = density;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /perspective/density density=%d\n", density);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    //------------------------------------------------------------------------------------
    //  POST /shading/apply — apply shading to selected path
    //------------------------------------------------------------------------------------
    gServer->Post("/shading/apply", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            int mode = body.value("mode", BridgeGetShadingMode());

            PluginOp op;
            if (mode == 1) {
                op.type = OpType::ShadingApplyMesh;
            } else {
                op.type = OpType::ShadingApplyBlend;
            }
            BridgeEnqueueOp(op);

            json resp;
            resp["ok"]   = true;
            resp["mode"] = (mode == 1) ? "mesh" : "blend";
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /shading/apply mode=%s\n",
                    (mode == 1) ? "mesh" : "blend");
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
    //  POST /shading/mode — set shading mode (0=blend, 1=mesh)
    //------------------------------------------------------------------------------------
    gServer->Post("/shading/mode", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            int mode = body.value("mode", 0);
            BridgeSetShadingMode(mode);
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
    //  POST /shading/colors — set highlight and shadow colors
    //------------------------------------------------------------------------------------
    gServer->Post("/shading/colors", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);
            if (body.contains("highlight")) {
                auto hl = body["highlight"];
                double r = hl.value("r", 1.0);
                double g = hl.value("g", 0.93);
                double b = hl.value("b", 0.80);
                BridgeSetShadingHighlight(r, g, b);
            }
            if (body.contains("shadow")) {
                auto sh = body["shadow"];
                double r = sh.value("r", 0.15);
                double g = sh.value("g", 0.10);
                double b = sh.value("b", 0.25);
                BridgeSetShadingShadow(r, g, b);
            }
            if (body.contains("light_angle")) {
                BridgeSetShadingLightAngle(body["light_angle"].get<double>());
            }
            if (body.contains("intensity")) {
                BridgeSetShadingIntensity(body["intensity"].get<double>());
            }
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /shading/colors updated\n");
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
    //  GET /shading/state — get current shading state
    //------------------------------------------------------------------------------------
    gServer->Get("/shading/state", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        double hR, hG, hB, sR, sG, sB;
        BridgeGetShadingHighlight(hR, hG, hB);
        BridgeGetShadingShadow(sR, sG, sB);

        json resp;
        resp["mode"]       = BridgeGetShadingMode();
        resp["highlight"]  = { {"r", hR}, {"g", hG}, {"b", hB} };
        resp["shadow"]     = { {"r", sR}, {"g", sG}, {"b", sB} };
        resp["lightAngle"] = BridgeGetShadingLightAngle();
        resp["intensity"]  = BridgeGetShadingIntensity();
        resp["blendSteps"] = BridgeGetShadingBlendSteps();
        resp["gridSize"]   = BridgeGetShadingMeshGrid();
        res.set_content(resp.dump(), "application/json");
    });

    //------------------------------------------------------------------------------------
    //  POST /shading/params — set shading parameters (partial update)
    //------------------------------------------------------------------------------------
    gServer->Post("/shading/params", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            json body = json::parse(req.body);

            // Each field is optional — only set what's provided
            if (body.contains("lightAngle")) {
                BridgeSetShadingLightAngle(body["lightAngle"].get<double>());
            }
            if (body.contains("intensity")) {
                BridgeSetShadingIntensity(body["intensity"].get<double>());
            }
            if (body.contains("blendSteps")) {
                BridgeSetShadingBlendSteps(body["blendSteps"].get<int>());
            }
            if (body.contains("gridSize")) {
                BridgeSetShadingMeshGrid(body["gridSize"].get<int>());
            }
            if (body.contains("highlight")) {
                auto& h = body["highlight"];
                double r = h.value("r", 1.0);
                double g = h.value("g", 1.0);
                double b = h.value("b", 1.0);
                BridgeSetShadingHighlight(r, g, b);
            }
            if (body.contains("shadow")) {
                auto& s = body["shadow"];
                double r = s.value("r", 0.0);
                double g = s.value("g", 0.0);
                double b = s.value("b", 0.0);
                BridgeSetShadingShadow(r, g, b);
            }
            if (body.contains("mode")) {
                BridgeSetShadingMode(body["mode"].get<int>());
            }

            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /shading/params updated\n");
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
    //  Stage 10b-d: Perspective mirror/duplicate/paste endpoints
    //------------------------------------------------------------------------------------

    gServer->Post("/api/perspective/mirror", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int axis = body.value("axis", 0);
            bool replace = body.value("replace", false);
            BridgeSetMirrorAxis(axis);
            BridgeSetMirrorReplace(replace);
            BridgeRequestMirrorPerspective(axis, replace);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/perspective/mirror axis=%d replace=%s\n",
                    axis, replace ? "true" : "false");
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/perspective/duplicate", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int count = body.value("count", 3);
            int spacing = body.value("spacing", 0);
            BridgeSetDuplicateCount(count);
            BridgeSetDuplicateSpacing(spacing);
            BridgeRequestDuplicatePerspective(count, spacing);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/perspective/duplicate count=%d spacing=%d\n",
                    count, spacing);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/perspective/paste", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int plane = body.value("plane", 0);
            float scale = body.value("scale", 1.0f);
            BridgeSetPastePlane(plane);
            BridgeSetPasteScale(scale);
            BridgeRequestPastePerspective(plane, scale);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/perspective/paste plane=%d scale=%.2f\n",
                    plane, scale);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/perspective/save", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestPerspectiveSave();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool HTTP] POST /api/perspective/save\n");
    });

    gServer->Post("/api/perspective/load", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestPerspectiveLoad();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool HTTP] POST /api/perspective/load\n");
    });

    //------------------------------------------------------------------------------------
    //  Stage 14: Decompose endpoints
    //------------------------------------------------------------------------------------

    gServer->Post("/api/decompose/analyze", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            float sensitivity = body.value("sensitivity", 0.5f);
            BridgeSetDecomposeSensitivity(sensitivity);
            BridgeRequestDecompose(sensitivity);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/decompose/analyze sensitivity=%.2f\n", sensitivity);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/decompose/accept", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestDecomposeAccept();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool HTTP] POST /api/decompose/accept\n");
    });

    gServer->Post("/api/decompose/split", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int clusterIndex = body.value("clusterIndex", 0);
            BridgeRequestDecomposeSplit(clusterIndex);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/decompose/split index=%d\n", clusterIndex);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/decompose/merge", [](const httplib::Request& req, httplib::Response& res) {
        AddCorsHeaders(res);
        try {
            auto body = json::parse(req.body);
            int clusterA = body.value("clusterA", 0);
            int clusterB = body.value("clusterB", 1);
            BridgeRequestDecomposeMergeGroups(clusterA, clusterB);
            json resp;
            resp["ok"] = true;
            res.set_content(resp.dump(), "application/json");
            fprintf(stderr, "[IllTool HTTP] POST /api/decompose/merge A=%d B=%d\n", clusterA, clusterB);
        }
        catch (const json::exception& e) {
            json resp;
            resp["ok"] = false;
            resp["error"] = e.what();
            res.status = 400;
            res.set_content(resp.dump(), "application/json");
        }
    });

    gServer->Post("/api/decompose/cancel", [](const httplib::Request& /*req*/, httplib::Response& res) {
        AddCorsHeaders(res);
        BridgeRequestDecomposeCancel();
        json resp;
        resp["ok"] = true;
        res.set_content(resp.dump(), "application/json");
        fprintf(stderr, "[IllTool HTTP] POST /api/decompose/cancel\n");
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
    // P0: do NOT detach — StopHttpBridge joins this thread for clean shutdown

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
        // Join with timeout — don't block Illustrator quit indefinitely
        if (gServerThread.joinable()) {
            // Use a detached watchdog: wait up to 2 seconds, then give up
            auto future = std::async(std::launch::async, [] {
                if (gServerThread.joinable()) gServerThread.join();
            });
            if (future.wait_for(std::chrono::seconds(2)) == std::future_status::timeout) {
                fprintf(stderr, "[IllTool] HTTP bridge thread join timed out — detaching\n");
                gServerThread.detach();
            }
        }
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
