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
#include <condition_variable>
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

void BridgeRequeueOp(PluginOp op) {
    std::lock_guard<std::mutex> lock(gOpMutex);
    gOpQueue.push_front(std::move(op));
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
static double gPerspHorizonY = 33.0;
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

static std::atomic<bool> gShadingEyedropperMode{false};
static std::atomic<int>  gShadingEyedropperTarget{0};   // 0=highlight, 1=shadow

void BridgeSetShadingEyedropperMode(bool active) { gShadingEyedropperMode.store(active); }
bool BridgeGetShadingEyedropperMode()             { return gShadingEyedropperMode.load(); }

void BridgeSetShadingEyedropperTarget(int target) { gShadingEyedropperTarget.store(target); }
int  BridgeGetShadingEyedropperTarget()            { return gShadingEyedropperTarget.load(); }

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
static std::atomic<bool>  gSnapToPerspective{true}; // snap cleanup output to perspective grid

void BridgeSetSnapToPerspective(bool snap) { gSnapToPerspective.store(snap); }
bool BridgeGetSnapToPerspective()          { return gSnapToPerspective.load(); }

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
//  Transform state (Stage 15)
//----------------------------------------------------------------------------------------

static std::atomic<double> gTransformWidth{0};
static std::atomic<double> gTransformHeight{0};
static std::atomic<double> gTransformRotation{0};
static std::atomic<int>    gTransformMode{1};          // 0=absolute, 1=relative
static std::atomic<bool>   gTransformRandom{false};
static std::atomic<int>    gTransformUnitSize{0};      // 0=px, 1=%
static std::atomic<int>    gTransformUnitRotation{0};  // 0=degrees, 1=%

void BridgeSetTransformWidth(double w)         { gTransformWidth.store(w); }
double BridgeGetTransformWidth()               { return gTransformWidth.load(); }

void BridgeSetTransformHeight(double h)        { gTransformHeight.store(h); }
double BridgeGetTransformHeight()              { return gTransformHeight.load(); }

void BridgeSetTransformRotation(double deg)    { gTransformRotation.store(deg); }
double BridgeGetTransformRotation()            { return gTransformRotation.load(); }

void BridgeSetTransformMode(int mode)          { gTransformMode.store(mode); }
int  BridgeGetTransformMode()                  { return gTransformMode.load(); }

void BridgeSetTransformRandom(bool random)     { gTransformRandom.store(random); }
bool BridgeGetTransformRandom()                { return gTransformRandom.load(); }

void BridgeSetTransformUnitSize(int unit)      { gTransformUnitSize.store(unit); }
int  BridgeGetTransformUnitSize()              { return gTransformUnitSize.load(); }

void BridgeSetTransformUnitRotation(int unit)  { gTransformUnitRotation.store(unit); }
int  BridgeGetTransformUnitRotation()          { return gTransformUnitRotation.load(); }

static std::atomic<bool> gTransformLockAspectRatio{false};
void BridgeSetTransformLockAspectRatio(bool lock) { gTransformLockAspectRatio.store(lock); }
bool BridgeGetTransformLockAspectRatio()          { return gTransformLockAspectRatio.load(); }

//----------------------------------------------------------------------------------------
//  Trace state (Stage 16)
//----------------------------------------------------------------------------------------

static std::atomic<int>  gTraceSpeckle{4};
static std::atomic<int>  gTraceColorPrecision{6};
static std::mutex        gTraceStatusMutex;
static std::string       gTraceStatus;

void BridgeRequestTrace(const std::string& backend) {
    PluginOp op{OpType::Trace};
    op.strParam = backend;
    BridgeEnqueueOp(op);
}

void BridgeSetTraceSpeckle(int size)        { gTraceSpeckle.store(size); }
int  BridgeGetTraceSpeckle()                { return gTraceSpeckle.load(); }

void BridgeSetTraceColorPrecision(int p)    { gTraceColorPrecision.store(p); }
int  BridgeGetTraceColorPrecision()         { return gTraceColorPrecision.load(); }

void BridgeSetTraceStatus(const std::string& status) {
    std::lock_guard<std::mutex> lock(gTraceStatusMutex);
    gTraceStatus = status;
}
std::string BridgeGetTraceStatus() {
    std::lock_guard<std::mutex> lock(gTraceStatusMutex);
    return gTraceStatus;
}

static std::atomic<int> gTraceOutputMode{1};  // 0=outline, 1=fill, 2=centerline (default: fill)

void BridgeSetTraceOutputMode(int mode)  { gTraceOutputMode.store(mode); }
int  BridgeGetTraceOutputMode()          { return gTraceOutputMode.load(); }

//----------------------------------------------------------------------------------------
//  Surface extraction state (Stage 17)
//----------------------------------------------------------------------------------------

static std::atomic<bool>   gSurfaceExtractMode{false};
static std::atomic<double> gExtractionSensitivity{0.5};
static std::mutex          gExtractionStatusMutex;
static std::string         gExtractionStatus;

void BridgeRequestSurfaceExtract(double x, double y, const std::string& action) {
    PluginOp op{OpType::SurfaceExtract};
    op.param1 = x;
    op.param2 = y;
    op.strParam = action;
    BridgeEnqueueOp(op);
}

void BridgeRequestSurfaceExtractToggle(bool enable) {
    PluginOp op{OpType::SurfaceExtractToggle};
    op.boolParam1 = enable;
    BridgeEnqueueOp(op);
}

void BridgeSetExtractionSensitivity(double s) { gExtractionSensitivity.store(s); }
double BridgeGetExtractionSensitivity()       { return gExtractionSensitivity.load(); }

void BridgeSetExtractionStatus(const std::string& status) {
    std::lock_guard<std::mutex> lock(gExtractionStatusMutex);
    gExtractionStatus = status;
}
std::string BridgeGetExtractionStatus() {
    std::lock_guard<std::mutex> lock(gExtractionStatusMutex);
    return gExtractionStatus;
}

void BridgeSetSurfaceExtractMode(bool active) { gSurfaceExtractMode.store(active); }
bool BridgeGetSurfaceExtractMode()            { return gSurfaceExtractMode.load(); }

//----------------------------------------------------------------------------------------
//  MCP Synchronous Request/Response mechanism
//  HTTP handler thread posts a request + waits on condvar.
//  Timer callback (SDK context) processes it, posts result, signals condvar.
//----------------------------------------------------------------------------------------

static std::mutex              gMcpMutex;
static std::condition_variable gMcpCondVar;
static bool                    gMcpRequestPending = false;
static PluginOp                gMcpRequestOp;
static std::string             gMcpResponse;
static bool                    gMcpResponseReady = false;
static std::atomic<bool>       gMcpShuttingDown{false};

std::string BridgeMcpSyncRequest(PluginOp op, int timeoutMs)
{
    // Reject immediately if shutting down
    if (gMcpShuttingDown.load()) {
        return "{\"ok\":false,\"error\":\"Plugin shutting down\"}";
    }

    std::unique_lock<std::mutex> lock(gMcpMutex);

    // Only one sync request at a time
    if (gMcpRequestPending) {
        return "{\"ok\":false,\"error\":\"Another MCP request is in progress\"}";
    }

    gMcpRequestOp = std::move(op);
    gMcpRequestPending = true;
    gMcpResponseReady = false;
    gMcpResponse.clear();

    // Wait for the timer callback to fill the response, or shutdown
    bool timedOut = !gMcpCondVar.wait_for(lock,
        std::chrono::milliseconds(timeoutMs),
        [] { return gMcpResponseReady || gMcpShuttingDown.load(); });

    gMcpRequestPending = false;

    if (gMcpShuttingDown.load()) {
        return "{\"ok\":false,\"error\":\"Plugin shutting down\"}";
    }

    if (timedOut) {
        return "{\"ok\":false,\"error\":\"SDK timeout — no document open or timer inactive\"}";
    }

    return std::move(gMcpResponse);
}

void BridgeMcpPostResponse(const std::string& jsonResult)
{
    std::lock_guard<std::mutex> lock(gMcpMutex);
    gMcpResponse = jsonResult;
    gMcpResponseReady = true;
    gMcpCondVar.notify_one();
}

bool BridgeMcpPeekRequest(PluginOp& out)
{
    std::lock_guard<std::mutex> lock(gMcpMutex);
    if (!gMcpRequestPending || gMcpResponseReady) return false;
    out = gMcpRequestOp;
    return true;
}

void BridgeMcpClearRequest()
{
    // No-op: the response posting + condvar notify handles cleanup.
    // This exists for symmetry but isn't strictly needed.
}

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
    //  Feature routes — /draw, /status, /events, /tool/mode, /lasso/*, /cleanup/*,
    //  /working/*, /learning/*, /vision/*, /perspective/*, /shading/*,
    //  /api/decompose/*, /api/batch, /api/journal, /api/trace, /api/surface_extract
    //------------------------------------------------------------------------------------
#include "HttpBridgeRoutes.cpp"

    //------------------------------------------------------------------------------------
    //  MCP Tool Integration routes — /api/inspect, /api/create_path,
    //  /api/create_shape, /api/layers, /api/select, /api/modify
    //------------------------------------------------------------------------------------
#include "HttpBridgeMcp.cpp"

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

    // Wake any blocked MCP sync request so it can exit cleanly
    gMcpShuttingDown.store(true);
    gMcpCondVar.notify_all();

    if (gServer) {
        gServer->stop();
        // Detach immediately — don't block Illustrator quit
        if (gServerThread.joinable()) {
            gServerThread.detach();
            fprintf(stderr, "[IllTool] HTTP bridge thread detached\n");
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
