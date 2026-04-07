//========================================================================================
//
//  IllTool Plugin — HTTP Bridge
//
//  Lightweight HTTP server on 127.0.0.1:8787 for receiving draw commands
//  and emitting events (SSE) from the Illustrator plugin.
//  Runs on a joinable background thread; all shared state is mutex-protected.
//
//========================================================================================

#ifndef __HTTPBRIDGE_H__
#define __HTTPBRIDGE_H__

#include <string>

/** Start the HTTP bridge server on the given port.
    Returns true if the server started successfully.
    Safe to call multiple times; subsequent calls are no-ops if already running.
*/
bool StartHttpBridge(int port);

/** Stop the HTTP bridge server and join its thread.
    Safe to call if not running.
*/
void StopHttpBridge();

/** Emit an event to all connected SSE clients.
    @param type  Event type string (e.g. "click", "drag", "hover").
    @param id    The draw command ID that was interacted with.
    @param x     Artwork X coordinate of the event.
    @param y     Artwork Y coordinate of the event.
*/
void BridgeEmitEvent(const char* type, const std::string& id, double x, double y);

//----------------------------------------------------------------------------------------
//  Operation Queue (H1) — replaces per-operation atomic flags
//----------------------------------------------------------------------------------------

/** All operations that can be queued for SDK-context execution. */
enum class OpType : int {
    LassoClose = 0,
    LassoClear,
    WorkingApply,
    WorkingCancel,
    AverageSelection,
    Classify,
    Reclassify,
    Simplify,
    CopyToGroup,
    Detach,
    Split,
    ScanEndpoints,
    MergeEndpoints,
    UndoMerge,
    SelectSmall,
    UndoShape,
    ClearPerspective,
    LockPerspective,     // boolParam1 = lock/unlock
    SetGridDensity,      // intParam = density (2-20)
    // Stage 11: Blend Harmonization
    BlendPickA,          // enter pick-A mode (next click stores path A)
    BlendPickB,          // enter pick-B mode (next click stores path B)
    BlendExecute,        // run blend with current settings
    BlendSetSteps,       // intParam = step count (1-20)
    BlendSetEasing,      // intParam = preset (0=linear,1=easeIn,2=easeOut,3=easeInOut,4=custom)
    // Stage 12: Surface Shading
    ShadingApplyBlend,   // apply blend shading to selected path
    ShadingApplyMesh,    // apply mesh gradient shading to selected path
    ShadingSetMode,      // intParam = 0 (blend) or 1 (mesh)
    // Stage 10b-d: Perspective operations
    MirrorPerspective,   // intParam = axis (0=vert,1=horiz,2=custom), boolParam1 = replace
    DuplicatePerspective,// intParam = count, param1 = spacing (0=perspective,1=screen)
    PastePerspective,    // intParam = plane (0-3), param1 = scale
    PerspectiveSave,     // save grid to document dictionary
    PerspectiveLoad,     // load grid from document dictionary
    // Stage 14: Decompose
    Decompose,           // param1 = sensitivity (0.0-1.0)
    DecomposeAccept,     // accept all clusters → create named groups
    DecomposeAcceptOne,  // intParam = cluster index
    DecomposeSplit,      // intParam = cluster index to split
    DecomposeMergeGroups,// intParam = clusterA, param1 = (double)clusterB
    DecomposeCancel      // cancel decompose overlay
};

/** A queued operation with parameters. Pushed by panels/HTTP, popped by timer. */
struct PluginOp {
    OpType type;
    double param1 = 0;          // tolerance, threshold, slider value
    double param2 = 0;          // secondary param
    int    intParam = 0;        // shape type, grid size
    bool   boolParam1 = false;  // deleteOriginals, chainMerge
    bool   boolParam2 = false;  // preserveHandles
    std::string strParam;       // group name
};

/** Enqueue an operation. Thread-safe (mutex-protected). Called from any thread. */
void BridgeEnqueueOp(PluginOp op);

/** Dequeue the next operation. Returns false if queue is empty.
    Called from ProcessOperationQueue (timer/SDK context only). */
bool BridgeDequeueOp(PluginOp& out);

//----------------------------------------------------------------------------------------
//  Result Queue (H2) — replaces per-feature readout variables
//----------------------------------------------------------------------------------------

/** Result types matching operations that produce output. */
enum class PluginResultType : int {
    ShapeDetected = 0,    // text = shape name, doubleValue = confidence
    MergeReadout,         // text = "N pairs, M paths"
    SurfaceHint,          // intValue = surface type, doubleValue = confidence, param2 = angle
    SelectionCount,       // intValue = count
};

/** A result posted by an operation for panel consumption. */
struct PluginResult {
    PluginResultType type;
    std::string text;
    int    intValue = 0;
    double doubleValue = 0;
    double param2 = 0;
};

/** Post a result from SDK context. Thread-safe. */
void BridgePostResult(PluginResult result);

/** Poll for the next result. Returns false if empty. Thread-safe. */
bool BridgePollResult(PluginResult& out);

//----------------------------------------------------------------------------------------
//  Tool mode (lasso vs smart)
//----------------------------------------------------------------------------------------

enum class BridgeToolMode { Lasso, Smart };

/** Set the current tool mode. Thread-safe. */
void BridgeSetToolMode(BridgeToolMode mode);

/** Get the current tool mode. Thread-safe. */
BridgeToolMode BridgeGetToolMode();

//----------------------------------------------------------------------------------------
//  Lasso close/clear requests (Enter/Escape key / HTTP endpoint)
//----------------------------------------------------------------------------------------

/** Signal the plugin to close the current polygon lasso. Thread-safe. */
void BridgeRequestLassoClose();

/** Signal the plugin to clear (cancel) the current polygon lasso. Thread-safe. */
void BridgeRequestLassoClear();

//----------------------------------------------------------------------------------------
//  Working mode apply/cancel requests (HTTP endpoints)
//----------------------------------------------------------------------------------------

/** Signal the plugin to apply working mode. Thread-safe. */
void BridgeRequestWorkingApply(bool deleteOriginals);

/** Signal the plugin to cancel working mode. Thread-safe. */
void BridgeRequestWorkingCancel();

//----------------------------------------------------------------------------------------
//  Average selection request (button -> queued for SDK context)
//----------------------------------------------------------------------------------------

void BridgeRequestAverageSelection();

//----------------------------------------------------------------------------------------
//  Shape classification request (auto-detect shape of selection)
//----------------------------------------------------------------------------------------

/** Signal the plugin to classify the currently selected path. Thread-safe. */
void BridgeRequestClassify();

//----------------------------------------------------------------------------------------
//  Shape reclassification request (force-fit selection to specific shape type)
//----------------------------------------------------------------------------------------

/** Shape type enum matching the panel button tags. */
enum class BridgeShapeType : int {
    Line     = 0,
    Arc      = 1,
    LShape   = 2,
    Rect     = 3,
    SCurve   = 4,
    Ellipse  = 5,
    Freeform = 6
};

/** Signal the plugin to reclassify (force-fit) the selection to a shape type. Thread-safe. */
void BridgeRequestReclassify(BridgeShapeType shapeType);

//----------------------------------------------------------------------------------------
//  Simplification request (Douglas-Peucker, slider value 0-100)
//----------------------------------------------------------------------------------------

/** Signal the plugin to simplify the selection with given tolerance (0-100 slider). Thread-safe. */
void BridgeRequestSimplify(double sliderValue);

//----------------------------------------------------------------------------------------
//  Grouping operations (Stage 5)
//----------------------------------------------------------------------------------------

/** Request Copy to Group -- duplicates selected paths into a named group. Thread-safe. */
void BridgeRequestCopyToGroup(const std::string& groupName);

/** Request Detach -- move selected paths out of their parent group. Thread-safe. */
void BridgeRequestDetach();

/** Request Split -- move selected paths into a new group. Thread-safe. */
void BridgeRequestSplit();

//----------------------------------------------------------------------------------------
//  Merge operations (Stage 6)
//----------------------------------------------------------------------------------------

/** Request Scan Endpoints -- find open path endpoint pairs within tolerance. Thread-safe. */
void BridgeRequestScanEndpoints(double tolerance);

/** Request Merge Endpoints -- join scanned pairs. Thread-safe. */
void BridgeRequestMergeEndpoints(bool chainMerge, bool preserveHandles);

/** Request Undo Merge -- restore originals from snapshot. Thread-safe. */
void BridgeRequestUndoMerge();

/** Set the merge readout text (called from SDK context, read by panel timer). Thread-safe. */
void BridgeSetMergeReadout(const std::string& text);
std::string BridgeGetMergeReadout();

//----------------------------------------------------------------------------------------
//  Smart select threshold (slider value 0-100, read by ToolMouseDown in Smart mode)
//----------------------------------------------------------------------------------------

/** Set the smart select similarity threshold (0-100). Thread-safe. */
void BridgeSetSmartThreshold(double value);

/** Get the current smart select similarity threshold (0-100). Thread-safe. */
double BridgeGetSmartThreshold();

//----------------------------------------------------------------------------------------
//  Tension value (slider 0-100, used by ReclassifyAs for bezier handle length)
//----------------------------------------------------------------------------------------

/** Set the curve tension value (0-100). Thread-safe. */
void BridgeSetTension(double value);

/** Get the current curve tension value (0-100). Thread-safe. */
double BridgeGetTension();

//----------------------------------------------------------------------------------------
//  Add to Selection toggle (shift-select mode for polygon lasso)
//----------------------------------------------------------------------------------------

/** Set the add-to-selection mode. Thread-safe. */
void BridgeSetAddToSelection(bool enabled);

/** Get whether add-to-selection mode is active. Thread-safe. */
bool BridgeGetAddToSelection();

//----------------------------------------------------------------------------------------
//  Select Small request (select paths with arc length below threshold)
//----------------------------------------------------------------------------------------

/** Signal the plugin to select all paths with arc length below threshold. Thread-safe. */
void BridgeRequestSelectSmall(double threshold);

//----------------------------------------------------------------------------------------
//  Shape undo request (restore paths modified by ReclassifyAs or SimplifySelection)
//----------------------------------------------------------------------------------------

/** Signal the plugin to undo the last shape operation. Thread-safe. */
void BridgeRequestUndoShape();

/** Store surface hint result from ClassifySelection. Thread-safe. */
void BridgeSetSurfaceHint(int surfaceType, double confidence, double gradientAngle);

/** Get the last stored surface type (-1 = unknown, 0-4 per SurfaceType enum). Thread-safe. */
int BridgeGetSurfaceType();

/** Get the last stored surface confidence. Thread-safe. */
double BridgeGetSurfaceConfidence();

/** Get the last stored gradient angle. Thread-safe. */
double BridgeGetGradientAngle();

//----------------------------------------------------------------------------------------
//  Perspective grid line state (Stage 10)
//  Continuous state — read every frame by annotator, written by panel/HTTP.
//----------------------------------------------------------------------------------------

/** Perspective line data: two handles defining a direction that converges at a VP. */
struct BridgePerspectiveLine {
    double h1x = 0, h1y = 0;   // handle 1 position (artwork coords)
    double h2x = 0, h2y = 0;   // handle 2 position (artwork coords)
    bool   active = false;       // true when line has been placed
};

/** Set a perspective line (0=left VP, 1=right VP, 2=vertical VP). Thread-safe. */
void BridgeSetPerspectiveLine(int lineIndex, double h1x, double h1y, double h2x, double h2y);

/** Clear a perspective line (set inactive). Thread-safe. */
void BridgeClearPerspectiveLine(int lineIndex);

/** Get a perspective line. Thread-safe. */
BridgePerspectiveLine BridgeGetPerspectiveLine(int lineIndex);

/** Set the horizon Y position. Thread-safe. */
void BridgeSetHorizonY(double y);

/** Get the horizon Y position. Thread-safe. */
double BridgeGetHorizonY();

/** Set/get perspective lock state. Thread-safe. */
void BridgeSetPerspectiveLocked(bool locked);
bool BridgeGetPerspectiveLocked();

/** Set/get perspective grid visibility (show/hide without clearing). Thread-safe. */
void BridgeSetPerspectiveVisible(bool visible);
bool BridgeGetPerspectiveVisible();

//----------------------------------------------------------------------------------------
//  Blend state (Stage 11)
//----------------------------------------------------------------------------------------

/** Set/get blend step count. Thread-safe. */
void BridgeSetBlendSteps(int steps);
int  BridgeGetBlendSteps();

/** Set/get blend easing preset (0-3 = presets, 4 = custom). Thread-safe. */
void BridgeSetBlendEasing(int preset);
int  BridgeGetBlendEasing();

/** Set/get custom easing control points (for preset 4). Thread-safe. */
void BridgeSetCustomEasingPoints(int count, const double* xyPairs);
int  BridgeGetCustomEasingPoints(double* xyPairs, int maxPairs);

/** Set/get blend pick mode (0=none, 1=pickA, 2=pickB). Thread-safe. */
void BridgeSetBlendPickMode(int mode);
int  BridgeGetBlendPickMode();

/** Set/get whether blend paths A and B are set. Thread-safe. */
bool BridgeHasBlendPathA();
bool BridgeHasBlendPathB();
void BridgeSetBlendPathASet(bool set);
void BridgeSetBlendPathBSet(bool set);

//----------------------------------------------------------------------------------------
//  Shading state (Stage 12) — continuous state, read by panel/ProcessOperationQueue
//----------------------------------------------------------------------------------------

/** Set/get shading mode (0=blend, 1=mesh). Thread-safe. */
void BridgeSetShadingMode(int mode);
int  BridgeGetShadingMode();

/** Set/get highlight color (RGB 0-1). Thread-safe. */
void BridgeSetShadingHighlight(double r, double g, double b);
void BridgeGetShadingHighlight(double& r, double& g, double& b);

/** Set/get shadow color (RGB 0-1). Thread-safe. */
void BridgeSetShadingShadow(double r, double g, double b);
void BridgeGetShadingShadow(double& r, double& g, double& b);

/** Set/get light angle in degrees (0-360). Thread-safe. */
void BridgeSetShadingLightAngle(double angle);
double BridgeGetShadingLightAngle();

/** Set/get shading intensity (0-100). Thread-safe. */
void BridgeSetShadingIntensity(double intensity);
double BridgeGetShadingIntensity();

/** Set/get blend step count for shading mode A (3-15). Thread-safe. */
void BridgeSetShadingBlendSteps(int steps);
int  BridgeGetShadingBlendSteps();

/** Set/get mesh grid size for shading mode B (2-6). Thread-safe. */
void BridgeSetShadingMeshGrid(int size);
int  BridgeGetShadingMeshGrid();

//----------------------------------------------------------------------------------------
//  Perspective mirror/duplicate/paste state (Stage 10b-d)
//----------------------------------------------------------------------------------------

/** Set/get mirror axis (0=vertical, 1=horizontal, 2=custom). Thread-safe. */
void BridgeSetMirrorAxis(int axis);
int  BridgeGetMirrorAxis();

/** Set/get mirror replace mode (true = replace original). Thread-safe. */
void BridgeSetMirrorReplace(bool replace);
bool BridgeGetMirrorReplace();

/** Set/get duplicate count (1-10). Thread-safe. */
void BridgeSetDuplicateCount(int count);
int  BridgeGetDuplicateCount();

/** Set/get duplicate spacing mode (0=equal in perspective, 1=equal on screen). Thread-safe. */
void BridgeSetDuplicateSpacing(int spacing);
int  BridgeGetDuplicateSpacing();

/** Set/get paste plane (0=floor, 1=left wall, 2=right wall, 3=custom). Thread-safe. */
void BridgeSetPastePlane(int plane);
int  BridgeGetPastePlane();

/** Set/get paste scale factor. Thread-safe. */
void BridgeSetPasteScale(float scale);
float BridgeGetPasteScale();

/** Request mirror in perspective. Thread-safe. */
void BridgeRequestMirrorPerspective(int axis, bool replace);

/** Request duplicate in perspective. Thread-safe. */
void BridgeRequestDuplicatePerspective(int count, int spacing);

/** Request paste in perspective. Thread-safe. */
void BridgeRequestPastePerspective(int plane, float scale);

/** Request save/load perspective to/from document. Thread-safe. */
void BridgeRequestPerspectiveSave();
void BridgeRequestPerspectiveLoad();

//----------------------------------------------------------------------------------------
//  Decompose state (Stage 14)
//----------------------------------------------------------------------------------------

/** Set/get decompose sensitivity (0.0-1.0). Thread-safe. */
void BridgeSetDecomposeSensitivity(float sensitivity);
float BridgeGetDecomposeSensitivity();

/** Set the decompose readout text (written from SDK context, read by panel timer). Thread-safe. */
void BridgeSetDecomposeReadout(const std::string& text);
std::string BridgeGetDecomposeReadout();

/** Request decompose operations. Thread-safe. */
void BridgeRequestDecompose(float sensitivity);
void BridgeRequestDecomposeAccept();
void BridgeRequestDecomposeAcceptOne(int clusterIndex);
void BridgeRequestDecomposeSplit(int clusterIndex);
void BridgeRequestDecomposeMergeGroups(int clusterA, int clusterB);
void BridgeRequestDecomposeCancel();

#endif // __HTTPBRIDGE_H__
