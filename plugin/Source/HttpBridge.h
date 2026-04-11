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
#include <condition_variable>

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
    SetPerspEditMode,    // boolParam1 = enter/exit edit mode
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
    PerspectivePresetSave,  // strParam = preset name; save current grid as named preset
    PerspectivePresetLoad,  // strParam = preset name; load named preset into grid
    // Stage 14: Decompose
    Decompose,           // param1 = sensitivity (0.0-1.0)
    DecomposeAccept,     // accept all clusters → create named groups
    DecomposeAcceptOne,  // intParam = cluster index
    DecomposeSplit,      // intParam = cluster index to split
    DecomposeMergeGroups,// intParam = clusterA, param1 = (double)clusterB
    DecomposeCancel,     // cancel decompose overlay
    PlaceVerticalVP,     // place VP3 at center of viewport
    DeletePerspective,   // clear grid and delete entirely
    ActivatePerspectiveTool, // clear existing lines and activate the perspective tool
    AutoMatchPerspective,    // auto-detect VPs from placed reference image
    InvalidateOverlay,       // force annotator redraw (used by sliders that set bridge values directly)
    Resmooth,                // re-smooth preview path with current tension slider value
    ShadingEyedropper,       // intParam = target (0=highlight, 1=shadow); sample fill color from selection
    // Stage 15: Transform All
    TransformApply,          // apply batch transform to all selected shapes
    // Stage 16: Trace
    Trace,                   // strParam = backend ("vtracer","opencv","starvector"); execute trace on placed image
    // Stage 17: Surface Extraction
    SurfaceExtract,          // param1 = x, param2 = y (click point); strParam = action (click_extract/region_extract)
    SurfaceExtractToggle,    // boolParam1 = enable/disable extract mode
    // MCP Tool Integration (synchronous request/response ops)
    McpInspect,              // synchronous: returns document + selection info as JSON
    McpCreatePath,           // strParam = JSON body (points, stroke, fill, name)
    McpCreateShape,          // strParam = JSON body (shape type, position, size, colors)
    McpLayers,               // strParam = JSON body (action: list/create/rename)
    McpSelect,               // strParam = JSON body (action: all/none/by_name/by_type)
    McpModify,               // strParam = JSON body (action: move/scale/rotate/set_stroke/set_fill/set_name/delete)
    // Stage 18: Ill Pen Tool
    PenPlacePoint,           // param1 = x, param2 = y (artwork coords)
    PenFinalize,             // create path from accumulated points
    PenCancel,               // discard current drawing
    PenSetChamfer,           // param1 = radius
    PenUndo,                 // remove last point
    // Stage 19: Ill Layers
    LayerScanTree,
    LayerSetVisible,
    LayerSetLocked,
    LayerReorder,
    LayerRename,
    LayerCreate,
    LayerDelete,
    LayerMoveArt,
    LayerAutoOrganize,
    LayerPresetSave,
    LayerPresetLoad,
    LayerAutoAssign,
    LayerLLMLookup,
    LayerSelectNode,     // click-to-select: set current layer or select art
    LayerGroupSelected   // Cmd+G: group selected items
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

/** Re-enqueue an operation at the front of the queue (for retry on next tick).
    Used when an op can't be processed yet (e.g. drag in progress). */
void BridgeRequeueOp(PluginOp op);

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

/** Set/get shading eyedropper mode (true = active, next click samples). Thread-safe. */
void BridgeSetShadingEyedropperMode(bool active);
bool BridgeGetShadingEyedropperMode();

/** Set/get shading eyedropper target (0=highlight, 1=shadow). Thread-safe. */
void BridgeSetShadingEyedropperTarget(int target);
int  BridgeGetShadingEyedropperTarget();

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

/** Snap-to-perspective toggle — when true, cleanup output is projected through perspective grid. */
void BridgeSetSnapToPerspective(bool snap);
bool BridgeGetSnapToPerspective();

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

//----------------------------------------------------------------------------------------
//  Transform state (Stage 15)
//----------------------------------------------------------------------------------------

/** Set/get transform width value. Thread-safe. */
void BridgeSetTransformWidth(double w);
double BridgeGetTransformWidth();

/** Set/get transform height value. Thread-safe. */
void BridgeSetTransformHeight(double h);
double BridgeGetTransformHeight();

/** Set/get transform rotation in degrees. Thread-safe. */
void BridgeSetTransformRotation(double deg);
double BridgeGetTransformRotation();

/** Set/get transform mode (0=absolute, 1=relative). Thread-safe. */
void BridgeSetTransformMode(int mode);
int BridgeGetTransformMode();

/** Set/get transform random variance toggle. Thread-safe. */
void BridgeSetTransformRandom(bool random);
bool BridgeGetTransformRandom();

/** Set/get transform size unit (0=px, 1=%). Thread-safe. */
void BridgeSetTransformUnitSize(int unit);
int BridgeGetTransformUnitSize();

/** Set/get transform rotation unit (0=degrees, 1=%). Thread-safe. */
void BridgeSetTransformUnitRotation(int unit);
int BridgeGetTransformUnitRotation();

/** Set/get transform aspect ratio lock (true = uniform scale). Thread-safe. */
void BridgeSetTransformLockAspectRatio(bool lock);
bool BridgeGetTransformLockAspectRatio();

//----------------------------------------------------------------------------------------
//  Trace state (Stage 16) — backend selection + parameters
//----------------------------------------------------------------------------------------

/** Request trace operation with current settings. Thread-safe. */
void BridgeRequestTrace(const std::string& backend);

/** Set/get trace speckle filter size (1-100). Thread-safe. */
void BridgeSetTraceSpeckle(int size);
int  BridgeGetTraceSpeckle();

/** Set/get trace color precision (1-10). Thread-safe. */
void BridgeSetTraceColorPrecision(int precision);
int  BridgeGetTraceColorPrecision();

/** Set/get trace status text (written from SDK context, read by panel). Thread-safe. */
void BridgeSetTraceStatus(const std::string& status);
std::string BridgeGetTraceStatus();

/** Set/get trace output mode (0=outline, 1=fill, 2=centerline). Thread-safe. */
void BridgeSetTraceOutputMode(int mode);
int  BridgeGetTraceOutputMode();

/** Set/get trace length threshold (min path length to keep). Thread-safe. */
void BridgeSetTraceLengthThresh(double val);
double BridgeGetTraceLengthThresh();

/** Set/get trace splice threshold in degrees (angle for joining paths). Thread-safe. */
void BridgeSetTraceSpliceThresh(int val);
int  BridgeGetTraceSpliceThresh();

/** Set/get trace max iterations (curve fitting passes). Thread-safe. */
void BridgeSetTraceMaxIter(int val);
int  BridgeGetTraceMaxIter();

/** Set/get trace layer difference (color difference for layer separation). Thread-safe. */
void BridgeSetTraceLayerDiff(int val);
int  BridgeGetTraceLayerDiff();

/** Set/get Canny edge low threshold (centerline mode). Thread-safe. */
void BridgeSetTraceCannyLow(double val);
double BridgeGetTraceCannyLow();

/** Set/get Canny edge high threshold (centerline mode). Thread-safe. */
void BridgeSetTraceCannyHigh(double val);
double BridgeGetTraceCannyHigh();

/** Set/get normal map generation strength (centerline mode). Thread-safe. */
void BridgeSetTraceNormalStrength(double val);
double BridgeGetTraceNormalStrength();

/** Set/get skeletonization brightness threshold (centerline mode). Thread-safe. */
void BridgeSetTraceSkeletonThresh(int val);
int  BridgeGetTraceSkeletonThresh();

/** Set/get dilation kernel radius for centerline edge thickening. Thread-safe.
    Kernel size = 2*radius+1, so radius=2 means 5x5 kernel. */
void BridgeSetTraceDilationRadius(int val);
int  BridgeGetTraceDilationRadius();

/** Set/get K planes for normal-map surface clustering. Thread-safe. */
void BridgeSetTraceKPlanes(int val);
int  BridgeGetTraceKPlanes();

/** Set/get pre-blur sigma for height-to-normal conversion. 0 = no blur. Thread-safe. */
void BridgeSetTraceNormalBlur(double val);
double BridgeGetTraceNormalBlur();

/** Set/get k-means sampling stride for normal clustering. Thread-safe. */
void BridgeSetTraceKMeansStride(int val);
int  BridgeGetTraceKMeansStride();

/** Set/get k-means max iterations for normal clustering. Thread-safe. */
void BridgeSetTraceKMeansIter(int val);
int  BridgeGetTraceKMeansIter();

//----------------------------------------------------------------------------------------
//  Surface extraction state (Stage 17) — click-to-extract mode
//----------------------------------------------------------------------------------------

/** Request surface extraction at click point. Thread-safe. */
void BridgeRequestSurfaceExtract(double x, double y, const std::string& action);

/** Toggle surface extraction mode. Thread-safe. */
void BridgeRequestSurfaceExtractToggle(bool enable);

/** Set/get extraction sensitivity (0.0-1.0). Thread-safe. */
void BridgeSetExtractionSensitivity(double sensitivity);
double BridgeGetExtractionSensitivity();

/** Set/get extraction status text. Thread-safe. */
void BridgeSetExtractionStatus(const std::string& status);
std::string BridgeGetExtractionStatus();

/** Set/get surface extraction mode active. Thread-safe. */
void BridgeSetSurfaceExtractMode(bool active);
bool BridgeGetSurfaceExtractMode();

//----------------------------------------------------------------------------------------
//  Pen tool state (Stage 18) — continuous state for Ill Pen drawing tool
//----------------------------------------------------------------------------------------

/** Set/get pen mode active. Thread-safe. */
void BridgeSetPenMode(bool active);
bool BridgeGetPenMode();

/** Set/get pen chamfer radius (0-20). Thread-safe. */
void BridgeSetPenChamferRadius(double radius);
double BridgeGetPenChamferRadius();

/** Set/get uniform edges flag (all anchors get same radius). Thread-safe. */
void BridgeSetPenUniformEdges(bool uniform);
bool BridgeGetPenUniformEdges();

/** Set/get path name for next created path. Thread-safe. */
void BridgeSetPenPathName(const std::string& name);
std::string BridgeGetPenPathName();

/** Set/get target group name for path placement. Thread-safe. */
void BridgeSetPenTargetGroup(const std::string& groupName);
std::string BridgeGetPenTargetGroup();

//----------------------------------------------------------------------------------------
//  MCP Synchronous Request/Response — HTTP thread enqueues op, waits on condvar,
//  ProcessOperationQueue fills result and signals. Timeout = 5 seconds.
//----------------------------------------------------------------------------------------

/** Enqueue an MCP operation and block until the timer callback posts a result.
    Returns the JSON result string, or an error JSON on timeout.
    Thread-safe. Called from HTTP handler threads only. */
std::string BridgeMcpSyncRequest(PluginOp op, int timeoutMs = 5000);

/** Called from ProcessOperationQueue (SDK timer context) to post a result
    for a pending synchronous MCP request. Wakes the waiting HTTP thread. */
void BridgeMcpPostResponse(const std::string& jsonResult);

/** Check if there is a pending synchronous MCP request. Returns false if none.
    If true, fills 'out' with the pending op. Called from ProcessOperationQueue only. */
bool BridgeMcpPeekRequest(PluginOp& out);

/** Clear the pending request after processing. Called from ProcessOperationQueue only. */
void BridgeMcpClearRequest();

//----------------------------------------------------------------------------------------
//  Layer tree state (Stage 19)
//----------------------------------------------------------------------------------------

/** Set/get the layer tree JSON (written from SDK context, read by panel). Thread-safe. */
void BridgeSetLayerTreeJSON(const std::string& json);
std::string BridgeGetLayerTreeJSON();

/** Set/get layer tree dirty flag. Thread-safe. */
void BridgeSetLayerTreeDirty(bool dirty);
bool BridgeGetLayerTreeDirty();

/** Set/get layer target for GroupingModule integration. Thread-safe. */
void BridgeSetLayerTarget(const std::string& layerName);
std::string BridgeGetLayerTarget();

/** Set/get layer auto-assign toggle. Thread-safe. */
void BridgeSetLayerAutoAssign(bool enabled);
bool BridgeGetLayerAutoAssign();

/** Set/get layer suggestion text. Thread-safe. */
void BridgeSetLayerSuggestion(const std::string& suggestion);
std::string BridgeGetLayerSuggestion();

//----------------------------------------------------------------------------------------
//  Subject Cutout preview state (Stage 20) — non-destructive Vision framework cutout
//----------------------------------------------------------------------------------------

/** Set/get cutout preview active flag. Thread-safe. */
void BridgeSetCutoutPreviewActive(bool active);
bool BridgeGetCutoutPreviewActive();

/** Set/get cutout preview path data (JSON array of {x,y} points in art coords).
    Written by PreviewCutout(), read by DrawOverlay(). Thread-safe. */
void BridgeSetCutoutPreviewPaths(const std::string& json);
std::string BridgeGetCutoutPreviewPaths();

/** Set/get cutout smoothness (vtracer speckle for outline tracing, 1-100). Thread-safe. */
void BridgeSetCutoutSmoothness(int val);
int  BridgeGetCutoutSmoothness();

/** Set/get the number of detected cutout instances (0-16). Thread-safe. */
void BridgeSetCutoutInstanceCount(int count);
int  BridgeGetCutoutInstanceCount();

/** Set/get per-instance selected state for add/subtract compositing. Thread-safe. */
void BridgeSetCutoutInstanceSelected(int index, bool selected);
bool BridgeGetCutoutInstanceSelected(int index);

/** Set/get file path for a per-instance mask PNG. Thread-safe. */
void BridgeSetCutoutInstanceMaskPath(int index, const std::string& path);
std::string BridgeGetCutoutInstanceMaskPath(int index);

//----------------------------------------------------------------------------------------
//  Apple Contours state (VisionIntelligence contour detection params)
//----------------------------------------------------------------------------------------

/** Set/get contour contrast adjustment (0.0-3.0, default 1.5). Thread-safe. */
void BridgeSetTraceContourContrast(double val);
double BridgeGetTraceContourContrast();

/** Set/get contour contrast pivot point (0.0-1.0, default 0.5). Thread-safe. */
void BridgeSetTraceContourPivot(double val);
double BridgeGetTraceContourPivot();

/** Set/get contour dark-on-light detection mode (default true). Thread-safe. */
void BridgeSetTraceContourDarkOnLight(bool val);
bool BridgeGetTraceContourDarkOnLight();

//----------------------------------------------------------------------------------------
//  Pose Detection state (Stage 22) — body/face/hand pose overlay
//----------------------------------------------------------------------------------------

/** Set/get pose preview active flag. Thread-safe. */
void BridgeSetPosePreviewActive(bool active);
bool BridgeGetPosePreviewActive();

/** Set/get pose preview JSON data (body joints + face points). Thread-safe. */
void BridgeSetPosePreviewJSON(const std::string& json);
std::string BridgeGetPosePreviewJSON();

/** Set/get include-face-landmarks flag. Thread-safe. */
void BridgeSetPoseIncludeFace(bool include);
bool BridgeGetPoseIncludeFace();

/** Set/get include-hand-pose flag. Thread-safe. */
void BridgeSetPoseIncludeHands(bool include);
bool BridgeGetPoseIncludeHands();

//----------------------------------------------------------------------------------------
//  Hardware capability flags (set once at startup, read by panels for UI gating)
//----------------------------------------------------------------------------------------

/** Set/get Neural Engine availability (Apple Silicon). Thread-safe. */
void BridgeSetHasNeuralEngine(bool has);
bool BridgeGetHasNeuralEngine();

/** Set/get contour detection availability (macOS 11+). Thread-safe. */
void BridgeSetHasContourDetection(bool has);
bool BridgeGetHasContourDetection();

/** Set/get instance segmentation availability (Apple Silicon required). Thread-safe. */
void BridgeSetHasInstanceSegmentation(bool has);
bool BridgeGetHasInstanceSegmentation();

/** Set/get pose detection availability (macOS 11+). Thread-safe. */
void BridgeSetHasPoseDetection(bool has);
bool BridgeGetHasPoseDetection();

//----------------------------------------------------------------------------------------
//  Depth Layers state (ONNX Depth Anything V2) — depth decomposition parameters
//----------------------------------------------------------------------------------------

/** Set/get depth layer count (2-8, default 4). Thread-safe. */
void BridgeSetDepthLayerCount(int count);
int  BridgeGetDepthLayerCount();

/** Set/get depth estimation availability (ONNX model loaded). Thread-safe. */
void BridgeSetHasDepthEstimation(bool has);
bool BridgeGetHasDepthEstimation();

/** Set/get cutout click threshold (brightness tolerance for flood fill). Thread-safe. */
void BridgeSetCutoutClickThreshold(int val);
int  BridgeGetCutoutClickThreshold();

/** Request that the IllTool Handle tool be activated (for click routing). Thread-safe. */
void BridgeRequestToolActivation();
bool BridgeConsumeToolActivationRequest();

#endif // __HTTPBRIDGE_H__
