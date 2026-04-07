//========================================================================================
//
//  IllTool Plugin — HTTP Bridge
//
//  Lightweight HTTP server on 127.0.0.1:8787 for receiving draw commands
//  and emitting events (SSE) from the Illustrator plugin.
//  Runs on a detached background thread; all shared state is mutex-protected.
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
    UndoShape
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
//  Lasso close request (Enter key / HTTP endpoint)
//----------------------------------------------------------------------------------------

/** Signal the plugin to close the current polygon lasso.
    Called from the HTTP handler or from the panel's key monitor.
    Thread-safe (atomic flag). */
void BridgeRequestLassoClose();

/** Check whether a lasso-close request is pending. Thread-safe. */
bool BridgeIsLassoCloseRequested();

/** Clear the lasso-close request flag after handling it. Thread-safe. */
void BridgeClearLassoCloseRequest();

//----------------------------------------------------------------------------------------
//  Lasso clear request (Escape key)
//----------------------------------------------------------------------------------------

/** Signal the plugin to clear (cancel) the current polygon lasso. Thread-safe. */
void BridgeRequestLassoClear();

/** Check whether a lasso-clear request is pending. Thread-safe. */
bool BridgeIsLassoClearRequested();

/** Clear the lasso-clear request flag after handling it. Thread-safe. */
void BridgeClearLassoClearRequest();

//----------------------------------------------------------------------------------------
//  Working mode apply/cancel requests (HTTP endpoints)
//----------------------------------------------------------------------------------------

/** Signal the plugin to apply working mode. Thread-safe (atomic flags). */
void BridgeRequestWorkingApply(bool deleteOriginals);

/** Check whether a working-apply request is pending. Thread-safe. */
bool BridgeIsWorkingApplyRequested();

/** Get the deleteOriginals flag for the pending apply request. */
bool BridgeGetWorkingApplyDeleteOriginals();

/** Clear the working-apply request flag after handling it. Thread-safe. */
void BridgeClearWorkingApplyRequest();

/** Signal the plugin to cancel working mode. Thread-safe. */
void BridgeRequestWorkingCancel();

/** Check whether a working-cancel request is pending. Thread-safe. */
bool BridgeIsWorkingCancelRequested();

/** Clear the working-cancel request flag after handling it. Thread-safe. */
void BridgeClearWorkingCancelRequest();

//----------------------------------------------------------------------------------------
//  Average selection request (button → queued for SDK context)
//----------------------------------------------------------------------------------------

void BridgeRequestAverageSelection();
bool BridgeIsAverageSelectionRequested();
void BridgeClearAverageSelectionRequest();

//----------------------------------------------------------------------------------------
//  Shape classification request (auto-detect shape of selection)
//----------------------------------------------------------------------------------------

/** Signal the plugin to classify the currently selected path. Thread-safe. */
void BridgeRequestClassify();

/** Check whether a classify request is pending. Thread-safe. */
bool BridgeIsClassifyRequested();

/** Clear the classify request flag after handling it. Thread-safe. */
void BridgeClearClassifyRequest();

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

/** Check whether a reclassify request is pending. Thread-safe. */
bool BridgeIsReclassifyRequested();

/** Get the requested shape type for the pending reclassify request. */
BridgeShapeType BridgeGetReclassifyShapeType();

/** Clear the reclassify request flag after handling it. Thread-safe. */
void BridgeClearReclassifyRequest();

//----------------------------------------------------------------------------------------
//  Simplification request (Douglas-Peucker, slider value 0-100)
//----------------------------------------------------------------------------------------

/** Signal the plugin to simplify the selection with given tolerance (0-100 slider). Thread-safe. */
void BridgeRequestSimplify(double sliderValue);

/** Check whether a simplify request is pending. Thread-safe. */
bool BridgeIsSimplifyRequested();

/** Get the slider value (0-100) for the pending simplify request. */
double BridgeGetSimplifySliderValue();

/** Clear the simplify request flag after handling it. Thread-safe. */
void BridgeClearSimplifyRequest();

//----------------------------------------------------------------------------------------
//  Grouping operations (Stage 5)
//----------------------------------------------------------------------------------------

/** Request Copy to Group — duplicates selected paths into a named group.
    Group name is stored in a mutex-protected string. Thread-safe. */
void BridgeRequestCopyToGroup(const std::string& groupName);
bool BridgeIsCopyToGroupRequested();
std::string BridgeGetCopyToGroupName();
void BridgeClearCopyToGroupRequest();

/** Request Detach — move selected paths out of their parent group. Thread-safe. */
void BridgeRequestDetach();
bool BridgeIsDetachRequested();
void BridgeClearDetachRequest();

/** Request Split — move selected paths into a new group. Thread-safe. */
void BridgeRequestSplit();
bool BridgeIsSplitRequested();
void BridgeClearSplitRequest();

//----------------------------------------------------------------------------------------
//  Merge operations (Stage 6)
//----------------------------------------------------------------------------------------

/** Request Scan Endpoints — find open path endpoint pairs within tolerance.
    Tolerance stored via mutex-protected double. Thread-safe. */
void BridgeRequestScanEndpoints(double tolerance);
bool BridgeIsScanEndpointsRequested();
double BridgeGetScanTolerance();
void BridgeClearScanEndpointsRequest();

/** Request Merge Endpoints — join scanned pairs.
    Chain merge and preserve handles flags stored as atomics. Thread-safe. */
void BridgeRequestMergeEndpoints(bool chainMerge, bool preserveHandles);
bool BridgeIsMergeEndpointsRequested();
bool BridgeGetMergeChainMerge();
bool BridgeGetMergePreserveHandles();
void BridgeClearMergeEndpointsRequest();

/** Request Undo Merge — restore originals from snapshot. Thread-safe. */
void BridgeRequestUndoMerge();
bool BridgeIsUndoMergeRequested();
void BridgeClearUndoMergeRequest();

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

/** Check whether a select-small request is pending. Thread-safe. */
bool BridgeIsSelectSmallRequested();

/** Get the threshold for the pending select-small request. */
double BridgeGetSelectSmallThreshold();

/** Clear the select-small request flag after handling it. Thread-safe. */
void BridgeClearSelectSmallRequest();

//----------------------------------------------------------------------------------------
//  Shape undo request (restore paths modified by ReclassifyAs or SimplifySelection)
//----------------------------------------------------------------------------------------

/** Store surface hint result from ClassifySelection. Thread-safe. */
void BridgeSetSurfaceHint(int surfaceType, double confidence, double gradientAngle);

/** Get the last stored surface type (-1 = unknown, 0-4 per SurfaceType enum). Thread-safe. */
int BridgeGetSurfaceType();

/** Get the last stored surface confidence. Thread-safe. */
double BridgeGetSurfaceConfidence();

/** Get the last stored gradient angle. Thread-safe. */
double BridgeGetGradientAngle();

/** Signal the plugin to undo the last shape operation. Thread-safe. */
void BridgeRequestUndoShape();

/** Check whether a shape-undo request is pending. Thread-safe. */
bool BridgeIsUndoShapeRequested();

/** Clear the shape-undo request flag after handling it. Thread-safe. */
void BridgeClearUndoShapeRequest();

#endif // __HTTPBRIDGE_H__
