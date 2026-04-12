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

static std::atomic<bool>  gAdaptiveCanny{false}; // use Otsu-derived Canny thresholds for VP estimation
void BridgeSetAdaptiveCanny(bool adaptive) { gAdaptiveCanny.store(adaptive); }
bool BridgeGetAdaptiveCanny()              { return gAdaptiveCanny.load(); }

static std::atomic<bool>  gShowVPLines{false};   // show detected Hough lines color-coded by VP cluster
void BridgeSetShowVPLines(bool show) { gShowVPLines.store(show); }
bool BridgeGetShowVPLines()           { return gShowVPLines.load(); }

static std::atomic<bool>  g3PointPerspective{false}; // enable 3-point (vertical) VP detection
void BridgeSet3PointPerspective(bool enable) { g3PointPerspective.store(enable); }
bool BridgeGet3PointPerspective()            { return g3PointPerspective.load(); }

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

// New vtracer parameters: length threshold, splice threshold, max iterations, layer difference
static std::atomic<double> gTraceLengthThresh{4.0};
static std::atomic<int>    gTraceSpliceThresh{45};
static std::atomic<int>    gTraceMaxIter{10};
static std::atomic<int>    gTraceLayerDiff{25};

void BridgeSetTraceLengthThresh(double v)  { gTraceLengthThresh.store(v); }
double BridgeGetTraceLengthThresh()        { return gTraceLengthThresh.load(); }

void BridgeSetTraceSpliceThresh(int v)     { gTraceSpliceThresh.store(v); }
int  BridgeGetTraceSpliceThresh()          { return gTraceSpliceThresh.load(); }

void BridgeSetTraceMaxIter(int v)          { gTraceMaxIter.store(v); }
int  BridgeGetTraceMaxIter()               { return gTraceMaxIter.load(); }

void BridgeSetTraceLayerDiff(int v)        { gTraceLayerDiff.store(v); }
int  BridgeGetTraceLayerDiff()             { return gTraceLayerDiff.load(); }

// Centerline preprocessing parameters
static std::atomic<double> gTraceCannyLow{80.0};
static std::atomic<double> gTraceCannyHigh{200.0};
static std::atomic<double> gTraceNormalStrength{2.0};
static std::atomic<int>    gTraceSkeletonThresh{128};
static std::atomic<int>    gTraceDilationRadius{2};   // kernel = 2*radius+1

void BridgeSetTraceCannyLow(double v)      { gTraceCannyLow.store(v); }
double BridgeGetTraceCannyLow()            { return gTraceCannyLow.load(); }

void BridgeSetTraceCannyHigh(double v)     { gTraceCannyHigh.store(v); }
double BridgeGetTraceCannyHigh()           { return gTraceCannyHigh.load(); }

void BridgeSetTraceNormalStrength(double v) { gTraceNormalStrength.store(v); }
double BridgeGetTraceNormalStrength()       { return gTraceNormalStrength.load(); }

void BridgeSetTraceSkeletonThresh(int v)   { gTraceSkeletonThresh.store(v); }
int  BridgeGetTraceSkeletonThresh()        { return gTraceSkeletonThresh.load(); }

void BridgeSetTraceDilationRadius(int v)   { gTraceDilationRadius.store(v); }
int  BridgeGetTraceDilationRadius()        { return gTraceDilationRadius.load(); }

static std::atomic<int>    gTraceKPlanes{6};
void BridgeSetTraceKPlanes(int v)          { gTraceKPlanes.store(v); }
int  BridgeGetTraceKPlanes()               { return gTraceKPlanes.load(); }

static std::atomic<double> gTraceNormalBlur{1.5};
static std::atomic<int>    gTraceKMeansStride{4};
static std::atomic<int>    gTraceKMeansIter{20};

void BridgeSetTraceNormalBlur(double v)    { gTraceNormalBlur.store(v); }
double BridgeGetTraceNormalBlur()          { return gTraceNormalBlur.load(); }
void BridgeSetTraceKMeansStride(int v)     { gTraceKMeansStride.store(v); }
int  BridgeGetTraceKMeansStride()          { return gTraceKMeansStride.load(); }
void BridgeSetTraceKMeansIter(int v)       { gTraceKMeansIter.store(v); }
int  BridgeGetTraceKMeansIter()            { return gTraceKMeansIter.load(); }

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
//  Pen tool state (Stage 18) — continuous state for Ill Pen drawing tool
//----------------------------------------------------------------------------------------

static std::atomic<bool>   gPenModeActive{false};
static std::atomic<double> gPenChamferRadius{0.0};
static std::atomic<bool>   gPenUniformEdges{true};

static std::mutex          gPenNameMutex;
static std::string         gPenPathName;

static std::mutex          gPenGroupMutex;
static std::string         gPenTargetGroup;

void BridgeSetPenMode(bool active)       { gPenModeActive.store(active); }
bool BridgeGetPenMode()                  { return gPenModeActive.load(); }

void BridgeSetPenChamferRadius(double r) { gPenChamferRadius.store(r); }
double BridgeGetPenChamferRadius()       { return gPenChamferRadius.load(); }

void BridgeSetPenUniformEdges(bool u)    { gPenUniformEdges.store(u); }
bool BridgeGetPenUniformEdges()          { return gPenUniformEdges.load(); }

void BridgeSetPenPathName(const std::string& name) {
    std::lock_guard<std::mutex> lock(gPenNameMutex);
    gPenPathName = name;
}
std::string BridgeGetPenPathName() {
    std::lock_guard<std::mutex> lock(gPenNameMutex);
    return gPenPathName;
}

void BridgeSetPenTargetGroup(const std::string& groupName) {
    std::lock_guard<std::mutex> lock(gPenGroupMutex);
    gPenTargetGroup = groupName;
}
std::string BridgeGetPenTargetGroup() {
    std::lock_guard<std::mutex> lock(gPenGroupMutex);
    return gPenTargetGroup;
}

//----------------------------------------------------------------------------------------
//  Layer tree state (Stage 19)
//----------------------------------------------------------------------------------------

static std::mutex gLayerTreeMutex;
static std::string gLayerTreeJSON;
static std::atomic<bool> gLayerTreeDirty{false};
static std::string gLayerTarget;
static std::atomic<bool> gLayerAutoAssign{false};
static std::string gLayerSuggestion;

void BridgeSetLayerTreeJSON(const std::string& json) {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    gLayerTreeJSON = json;
}
std::string BridgeGetLayerTreeJSON() {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    return gLayerTreeJSON;
}
void BridgeSetLayerTreeDirty(bool dirty) { gLayerTreeDirty.store(dirty); }
bool BridgeGetLayerTreeDirty() { return gLayerTreeDirty.load(); }

void BridgeSetLayerTarget(const std::string& name) {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    gLayerTarget = name;
}
std::string BridgeGetLayerTarget() {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    return gLayerTarget;
}
void BridgeSetLayerAutoAssign(bool e) { gLayerAutoAssign.store(e); }
bool BridgeGetLayerAutoAssign() { return gLayerAutoAssign.load(); }

void BridgeSetLayerSuggestion(const std::string& s) {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    gLayerSuggestion = s;
}
std::string BridgeGetLayerSuggestion() {
    std::lock_guard<std::mutex> lock(gLayerTreeMutex);
    return gLayerSuggestion;
}

//----------------------------------------------------------------------------------------
//  Subject Cutout preview state (Stage 20)
//----------------------------------------------------------------------------------------

static std::atomic<bool> gCutoutPreviewActive{false};
static std::mutex        gCutoutPreviewMutex;
static std::string       gCutoutPreviewPaths;
static std::atomic<int>  gCutoutSmoothness{50};

void BridgeSetCutoutPreviewActive(bool active) { gCutoutPreviewActive.store(active); }
bool BridgeGetCutoutPreviewActive()            { return gCutoutPreviewActive.load(); }

void BridgeSetCutoutPreviewPaths(const std::string& json) {
    std::lock_guard<std::mutex> lock(gCutoutPreviewMutex);
    gCutoutPreviewPaths = json;
}
std::string BridgeGetCutoutPreviewPaths() {
    std::lock_guard<std::mutex> lock(gCutoutPreviewMutex);
    return gCutoutPreviewPaths;
}

void BridgeSetCutoutSmoothness(int val)  { gCutoutSmoothness.store(val); }
int  BridgeGetCutoutSmoothness()         { return gCutoutSmoothness.load(); }

// Per-instance cutout state (max 16 instances)
static std::atomic<int>  gCutoutInstanceCount{0};
static std::atomic<bool> gCutoutInstanceSelected[16] = {};
static std::mutex        gCutoutMaskMutex;
static std::string       gCutoutInstanceMaskPaths[16];

void BridgeSetCutoutInstanceCount(int count) {
    if (count < 0)  count = 0;
    if (count > 16) count = 16;
    gCutoutInstanceCount.store(count);
}
int BridgeGetCutoutInstanceCount() { return gCutoutInstanceCount.load(); }

void BridgeSetCutoutInstanceSelected(int index, bool selected) {
    if (index >= 0 && index < 16)
        gCutoutInstanceSelected[index].store(selected);
}
bool BridgeGetCutoutInstanceSelected(int index) {
    if (index >= 0 && index < 16)
        return gCutoutInstanceSelected[index].load();
    return false;
}

void BridgeSetCutoutInstanceMaskPath(int index, const std::string& path) {
    if (index < 0 || index >= 16) return;
    std::lock_guard<std::mutex> lock(gCutoutMaskMutex);
    gCutoutInstanceMaskPaths[index] = path;
}
std::string BridgeGetCutoutInstanceMaskPath(int index) {
    if (index < 0 || index >= 16) return "";
    std::lock_guard<std::mutex> lock(gCutoutMaskMutex);
    return gCutoutInstanceMaskPaths[index];
}

//----------------------------------------------------------------------------------------
//  Apple Contours state (VisionIntelligence contour detection params)
//----------------------------------------------------------------------------------------

static std::atomic<double> gTraceContourContrast{1.5};
static std::atomic<double> gTraceContourPivot{0.5};
static std::atomic<bool>   gTraceContourDarkOnLight{true};

void BridgeSetTraceContourContrast(double val)   { gTraceContourContrast.store(val); }
double BridgeGetTraceContourContrast()           { return gTraceContourContrast.load(); }

void BridgeSetTraceContourPivot(double val)      { gTraceContourPivot.store(val); }
double BridgeGetTraceContourPivot()              { return gTraceContourPivot.load(); }

void BridgeSetTraceContourDarkOnLight(bool val)  { gTraceContourDarkOnLight.store(val); }
bool BridgeGetTraceContourDarkOnLight()          { return gTraceContourDarkOnLight.load(); }

//----------------------------------------------------------------------------------------
//  Pose Detection preview state (Stage 22)
//----------------------------------------------------------------------------------------

static std::atomic<bool> gPosePreviewActive{false};
static std::mutex        gPosePreviewMutex;
static std::string       gPosePreviewJSON;
static std::atomic<bool> gPoseIncludeFace{true};
static std::atomic<bool> gPoseIncludeHands{false};

void BridgeSetPosePreviewActive(bool active) { gPosePreviewActive.store(active); }
bool BridgeGetPosePreviewActive()            { return gPosePreviewActive.load(); }

void BridgeSetPosePreviewJSON(const std::string& json) {
    std::lock_guard<std::mutex> lock(gPosePreviewMutex);
    gPosePreviewJSON = json;
}
std::string BridgeGetPosePreviewJSON() {
    std::lock_guard<std::mutex> lock(gPosePreviewMutex);
    return gPosePreviewJSON;
}

void BridgeSetPoseIncludeFace(bool include) { gPoseIncludeFace.store(include); }
bool BridgeGetPoseIncludeFace()             { return gPoseIncludeFace.load(); }

void BridgeSetPoseIncludeHands(bool include) { gPoseIncludeHands.store(include); }
bool BridgeGetPoseIncludeHands()             { return gPoseIncludeHands.load(); }

//----------------------------------------------------------------------------------------
//  Hardware capability flags (set once at startup, read by panels for UI gating)
//----------------------------------------------------------------------------------------

static std::atomic<bool> gHasNeuralEngine{false};
static std::atomic<bool> gHasContourDetection{false};
static std::atomic<bool> gHasInstanceSegmentation{false};
static std::atomic<bool> gHasPoseDetection{false};

void BridgeSetHasNeuralEngine(bool has)          { gHasNeuralEngine.store(has); }
bool BridgeGetHasNeuralEngine()                  { return gHasNeuralEngine.load(); }

void BridgeSetHasContourDetection(bool has)      { gHasContourDetection.store(has); }
bool BridgeGetHasContourDetection()              { return gHasContourDetection.load(); }

void BridgeSetHasInstanceSegmentation(bool has)  { gHasInstanceSegmentation.store(has); }
bool BridgeGetHasInstanceSegmentation()          { return gHasInstanceSegmentation.load(); }

void BridgeSetHasPoseDetection(bool has)         { gHasPoseDetection.store(has); }
bool BridgeGetHasPoseDetection()                 { return gHasPoseDetection.load(); }

//----------------------------------------------------------------------------------------
//  Depth Layers state (ONNX Depth Anything V2)
//----------------------------------------------------------------------------------------

static std::atomic<int>  gDepthLayerCount{4};
static std::atomic<bool> gHasDepthEstimation{false};

void BridgeSetDepthLayerCount(int count)         { gDepthLayerCount.store(count); }
int  BridgeGetDepthLayerCount()                  { return gDepthLayerCount.load(); }
void BridgeSetHasDepthEstimation(bool has)       { gHasDepthEstimation.store(has); }
bool BridgeGetHasDepthEstimation()               { return gHasDepthEstimation.load(); }

static std::atomic<int>  gDepthModel{0};   // 0=DA V2 (relative), 1=Metric3D v2 (metric)
void BridgeSetDepthModel(int model)              { gDepthModel.store(model); }
int  BridgeGetDepthModel()                       { return gDepthModel.load(); }

static std::atomic<bool> gHasMetricDepth{false};
void BridgeSetHasMetricDepth(bool has)           { gHasMetricDepth.store(has); }
bool BridgeGetHasMetricDepth()                   { return gHasMetricDepth.load(); }

static std::atomic<int>  gCutoutClickThreshold{30};
void BridgeSetCutoutClickThreshold(int v) { gCutoutClickThreshold.store(v); }
int  BridgeGetCutoutClickThreshold()      { return gCutoutClickThreshold.load(); }

static std::atomic<bool> gToolActivationRequested{false};
void BridgeRequestToolActivation()               { gToolActivationRequested.store(true); }
bool BridgeConsumeToolActivationRequest()         {
    bool expected = true;
    return gToolActivationRequested.compare_exchange_strong(expected, false);
}

// Prior tool number — saved before auto-activating IllTool Handle, restored on cutout clear
static std::atomic<int> gPriorToolNumber{0};

void BridgeSetPriorToolNumber(int toolNum) { gPriorToolNumber.store(toolNum); }
int  BridgeGetPriorToolNumber()            { return gPriorToolNumber.load(); }

//----------------------------------------------------------------------------------------
//  Preprocess Preview state — raw PNG data for annotator overlay
//----------------------------------------------------------------------------------------

static std::atomic<bool>          gPreprocessPreviewActive{false};
static std::mutex                 gPreprocessPreviewMutex;
static std::vector<unsigned char> gPreprocessPreviewData;

void BridgeSetPreprocessPreviewData(const std::vector<unsigned char>& data) {
    std::lock_guard<std::mutex> lock(gPreprocessPreviewMutex);
    gPreprocessPreviewData = data;
}
std::vector<unsigned char> BridgeGetPreprocessPreviewData() {
    std::lock_guard<std::mutex> lock(gPreprocessPreviewMutex);
    return gPreprocessPreviewData;
}

void BridgeSetPreprocessPreviewActive(bool active) { gPreprocessPreviewActive.store(active); }
bool BridgeGetPreprocessPreviewActive()            { return gPreprocessPreviewActive.load(); }

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
//  Symmetry Correction state (Stage 23)
//----------------------------------------------------------------------------------------

static std::atomic<float> gSymmetryAxisX{0.5f};     // 0.0-1.0 normalized
static std::atomic<int>   gSymmetrySide{0};          // 0=left, 1=right
static std::atomic<float> gSymmetryBlendPct{1.0f};   // 0.5-3.0% of image width
static std::atomic<bool>  gSymmetryActive{false};

static std::mutex         gSymmetryPathMutex;
static std::string        gSymmetryPreviewPath;
static std::string        gSymmetryOutputPath;

void BridgeSetSymmetryAxisX(float x)   { gSymmetryAxisX.store(x); }
float BridgeGetSymmetryAxisX()         { return gSymmetryAxisX.load(); }
void BridgeSetSymmetrySide(int side)   { gSymmetrySide.store(side); }
int  BridgeGetSymmetrySide()           { return gSymmetrySide.load(); }
void BridgeSetSymmetryBlendPct(float p){ gSymmetryBlendPct.store(p); }
float BridgeGetSymmetryBlendPct()      { return gSymmetryBlendPct.load(); }
void BridgeSetSymmetryActive(bool a)   { gSymmetryActive.store(a); }
bool BridgeGetSymmetryActive()         { return gSymmetryActive.load(); }

void BridgeSetSymmetryPreviewPath(const std::string& path) {
    std::lock_guard<std::mutex> lock(gSymmetryPathMutex);
    gSymmetryPreviewPath = path;
}
std::string BridgeGetSymmetryPreviewPath() {
    std::lock_guard<std::mutex> lock(gSymmetryPathMutex);
    return gSymmetryPreviewPath;
}
void BridgeSetSymmetryOutputPath(const std::string& path) {
    std::lock_guard<std::mutex> lock(gSymmetryPathMutex);
    gSymmetryOutputPath = path;
}
std::string BridgeGetSymmetryOutputPath() {
    std::lock_guard<std::mutex> lock(gSymmetryPathMutex);
    return gSymmetryOutputPath;
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
