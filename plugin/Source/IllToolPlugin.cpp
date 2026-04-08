//========================================================================================
//
//  IllTool Plugin — Main plugin implementation
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Key features:
//    - "IllTool Handle" tool in its own group
//    - Annotator renders draw commands from HTTP bridge + polygon lasso overlay
//    - HTTP bridge on port 8787 (started in PostStartupPlugin)
//    - Polygon lasso: click to add vertices, double-click to close and select
//    - stderr logging with [IllTool] prefix for debugging
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "AITool.h"
#include "LearningEngine.h"
#include <cstdio>
#include <cmath>
#include <chrono>
#include <algorithm>
#include <string>
#include <cfloat>

IllToolPlugin *gPlugin = NULL;

// Forward declarations for free functions in IllToolDecompose.cpp
void RunDecompose(float sensitivity);
void AcceptDecompose();
void AcceptCluster(int clusterIndex);
void SplitCluster(int clusterIndex);
void MergeDecomposeClusters(int clusterA, int clusterB);
void CancelDecompose();
void DrawDecomposeOverlay(AIAnnotatorMessage* message);
bool IsDecomposeActive();

//----------------------------------------------------------------------------------------
//  Helper: current time in seconds (monotonic clock)
//----------------------------------------------------------------------------------------

static double CurrentTimeSeconds()
{
    auto now = std::chrono::steady_clock::now();
    auto ms  = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch());
    return (double)ms.count() / 1000.0;
}

//========================================================================================
//  SDK entry points
//========================================================================================

Plugin *AllocatePlugin(SPPluginRef pluginRef)
{
    return new IllToolPlugin(pluginRef);
}

void FixupReload(Plugin* plugin)
{
    IllToolPlugin::FixupVTable((IllToolPlugin*) plugin);
}

ASErr IllToolPlugin::SetGlobal(Plugin* plugin)
{
    gPlugin = (IllToolPlugin*) plugin;
    return kNoErr;
}

//========================================================================================
//  Constructor
//========================================================================================

IllToolPlugin::IllToolPlugin(SPPluginRef pluginRef) :
    Plugin(pluginRef), fToolHandle(NULL), fPerspectiveToolHandle(NULL), fAboutPluginMenu(NULL),
    fAnnotatorHandle(NULL), fNotifySelectionChanged(NULL),
    fAnnotator(NULL),
    fResourceManagerHandle(NULL),
    fOperationTimer(NULL),
    fShutdownApplicationNotifier(NULL),
    fIsolationChangedNotifier(NULL),
    fSelectionPanel(NULL), fCleanupPanel(NULL),
    fGroupingPanel(NULL), fMergePanel(NULL),
    fShadingPanel(NULL), fBlendPanel(NULL), fPerspectivePanel(NULL),
    fSelectionMenuHandle(NULL), fCleanupMenuHandle(NULL),
    fGroupingMenuHandle(NULL), fMergeMenuHandle(NULL),
    fShadingMenuHandle(NULL), fBlendMenuHandle(NULL), fPerspectiveMenuHandle(NULL),
    fAppMenuRootHandle(NULL),
    fMenuLassoHandle(NULL), fMenuSmartHandle(NULL),
    fMenuCleanupHandle(NULL), fMenuGroupingHandle(NULL),
    fMenuMergeHandle(NULL), fMenuSelectionHandle(NULL),
    fSelectionController(NULL), fCleanupController(NULL),
    fGroupingController(NULL), fMergeController(NULL),
    fShadingController(NULL), fBlendController(NULL), fPerspectiveController(NULL),
    fLastClickTime(0.0)
{
    fLastCursorPos.h = 0;
    fLastCursorPos.v = 0;
    strncpy(fPluginName, kIllToolPluginName, kMaxStringLength);
    fprintf(stderr, "[IllTool] Plugin constructed: %s\n", kIllToolPluginName);
}

//========================================================================================
//  Lifecycle
//========================================================================================

ASErr IllToolPlugin::StartupPlugin(SPInterfaceMessage* message)
{
    ASErr result = kNoErr;
    try
    {
        fprintf(stderr, "[IllTool] StartupPlugin begin\n");

        fprintf(stderr, "[IllTool] Calling Plugin::StartupPlugin...\n");
        result = Plugin::StartupPlugin(message);
        fprintf(stderr, "[IllTool] Plugin::StartupPlugin returned %d\n", (int)result);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Adding About menu...\n");
        SDKAboutPluginsHelper aboutPluginsHelper;
        result = aboutPluginsHelper.AddAboutPluginsMenuItem(message,
                    kSDKDefAboutSDKCompanyPluginsGroupName,
                    ai::UnicodeString(kSDKDefAboutSDKCompanyPluginsGroupNameString),
                    "IllTool Overlay...",
                    &fAboutPluginMenu);
        fprintf(stderr, "[IllTool] AddAboutPluginsMenuItem returned %d\n", (int)result);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Adding tool...\n");
        result = this->AddTool(message);
        fprintf(stderr, "[IllTool] AddTool returned %d\n", (int)result);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Adding annotator...\n");
        result = this->AddAnnotator(message);
        fprintf(stderr, "[IllTool] AddAnnotator returned %d\n", (int)result);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Adding notifiers...\n");
        result = this->AddNotifier(message);
        fprintf(stderr, "[IllTool] AddNotifier returned %d\n", (int)result);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Adding panels...\n");
        result = this->AddPanels();
        fprintf(stderr, "[IllTool] AddPanels returned %d\n", (int)result);
        // Don't check_ai_error — panels are non-fatal if they fail
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] WARNING: Panel creation had errors (non-fatal)\n");
            result = kNoErr;  // Continue startup even if panels fail
        }

        // Register application menu (Window > IllTool submenu)
        fprintf(stderr, "[IllTool] Adding application menu...\n");
        result = this->AddAppMenu(message);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] WARNING: App menu creation had errors (non-fatal): %d\n",
                    (int)result);
            result = kNoErr;  // Non-fatal — panels still work via Window menu items
        } else {
            fprintf(stderr, "[IllTool] Application menu registered\n");
        }

        // Register operation timer — fires ~10 times/sec in SDK context.
        // This is the ONLY safe way to execute SDK API calls from panel buttons
        // and HTTP bridge requests, since those run outside SDK message dispatch.
        if (sAITimer) {
            result = sAITimer->AddTimer(message->d.self, "IllTool Ops",
                                        kTicksPerSecond / 10, &fOperationTimer);
            if (result) {
                fprintf(stderr, "[IllTool] Timer registration failed: %d\n", (int)result);
                result = kNoErr;  // Non-fatal — fall back to TrackToolCursor polling
            } else {
                fprintf(stderr, "[IllTool] Operation timer registered (period=%d ticks, ~10Hz)\n",
                        kTicksPerSecond / 10);
            }
        } else {
            fprintf(stderr, "[IllTool] WARNING: AITimerSuite not available — using TrackToolCursor only\n");
        }

        fprintf(stderr, "[IllTool] StartupPlugin complete\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] StartupPlugin error: %d\n", (int)ex);
        result = ex;
    }
    catch (...) {
        fprintf(stderr, "[IllTool] StartupPlugin unknown error\n");
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::PostStartupPlugin()
{
    ASErr result = kNoErr;
    try {
        fprintf(stderr, "[IllTool] PostStartupPlugin begin\n");

        if (fAnnotator == NULL) {
            fAnnotator = new IllToolAnnotator();
            SDK_ASSERT(fAnnotator);
        }

        result = sAIUser->CreateCursorResourceMgr(fPluginRef, &fResourceManagerHandle);
        aisdk::check_ai_error(result);

        // Start the HTTP bridge server
        if (StartHttpBridge(8787)) {
            fprintf(stderr, "[IllTool] HTTP bridge started on :8787\n");
        } else {
            fprintf(stderr, "[IllTool] HTTP bridge FAILED to start\n");
        }

        // Open the learning engine database
        LearningEngine::Instance().Open();

        fprintf(stderr, "[IllTool] PostStartupPlugin complete\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] PostStartupPlugin error: %d\n", (int)ex);
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::ShutdownPlugin(SPInterfaceMessage* message)
{
    ASErr result = kNoErr;
    try {
        fprintf(stderr, "[IllTool] ShutdownPlugin\n");

        // Deactivate operation timer before other cleanup
        if (sAITimer && fOperationTimer) {
            sAITimer->SetTimerActive(fOperationTimer, false);
            fprintf(stderr, "[IllTool] Operation timer deactivated\n");
        }

        // Destroy panels before other cleanup
        DestroyPanels();

        // Close learning engine before other cleanup
        LearningEngine::Instance().Close();

        // Stop HTTP bridge before cleanup
        StopHttpBridge();

        if (fAnnotator) {
            delete fAnnotator;
            fAnnotator = NULL;
        }

        result = Plugin::ShutdownPlugin(message);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Message dispatcher
//========================================================================================

ASErr IllToolPlugin::Message(char* caller, char* selector, void* message)
{
    ASErr result = kNoErr;
    try {
        result = Plugin::Message(caller, selector, message);

        if (result == kUnhandledMsgErr) {
            if (strcmp(caller, kCallerAITimer) == 0) {
                if (strcmp(selector, kSelectorAIGoTimer) == 0) {
                    ProcessOperationQueue();
                    result = kNoErr;
                }
            }
            else if (strcmp(caller, kCallerAITool) == 0) {
                // Handle tool messages not dispatched by the base Plugin class
                AIToolMessage* toolMsg = (AIToolMessage*)message;
                if (toolMsg->tool == fPerspectiveToolHandle) {
                    if (strcmp(selector, kSelectorAIToolMouseDrag) == 0) {
                        PerspectiveToolMouseDrag(toolMsg);
                        result = kNoErr;
                    }
                    else if (strcmp(selector, kSelectorAIToolMouseUp) == 0) {
                        PerspectiveToolMouseUp(toolMsg);
                        result = kNoErr;
                    }
                }
            }
            else if (strcmp(caller, kCallerAIAnnotation) == 0) {
                if (strcmp(selector, kSelectorAIDrawAnnotation) == 0) {
                    result = this->DrawAnnotation((AIAnnotatorMessage*)message);
                    aisdk::check_ai_error(result);
                }
                else if (strcmp(selector, kSelectorAIInvalAnnotation) == 0) {
                    result = this->InvalAnnotation((AIAnnotatorMessage*)message);
                    aisdk::check_ai_error(result);
                }
            }
        }
        else {
            aisdk::check_ai_error(result);
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Menu
//========================================================================================

ASErr IllToolPlugin::GoMenuItem(AIMenuMessage* message)
{
    ASErr result = kNoErr;
    try
    {
        if (message->menuItem == fAboutPluginMenu) {
            SDKAboutPluginsHelper aboutPluginsHelper;
            aboutPluginsHelper.PopAboutBox(message, "About IllTool Overlay",
                kSDKDefAboutSDKCompanyPluginsAlertString);
        }
        //----------------------------------------------------------------------
        // Application menu: Tool activation items (Window > IllTool submenu)
        //----------------------------------------------------------------------
        else if (message->menuItem == fMenuLassoHandle) {
            // Activate IllTool in Polygon Lasso mode
            fprintf(stderr, "[IllTool Menu] Polygon Lasso selected\n");
            BridgeSetToolMode(BridgeToolMode::Lasso);
            if (sAITool && fToolHandle) {
                sAITool->SetSelectedTool(fToolHandle);
            }
        }
        else if (message->menuItem == fMenuSmartHandle) {
            // Activate IllTool in Smart Select mode
            fprintf(stderr, "[IllTool Menu] Smart Select selected\n");
            BridgeSetToolMode(BridgeToolMode::Smart);
            if (sAITool && fToolHandle) {
                sAITool->SetSelectedTool(fToolHandle);
            }
        }
        //----------------------------------------------------------------------
        // Panel toggle items (both Window menu items AND submenu panel items)
        //----------------------------------------------------------------------
        else if (sAIPanel) {
            struct { AIMenuItemHandle menu; AIPanelRef panel; const char* name; } panels[] = {
                { fSelectionMenuHandle,    fSelectionPanel,    "Selection" },
                { fCleanupMenuHandle,      fCleanupPanel,      "Cleanup" },
                { fGroupingMenuHandle,     fGroupingPanel,     "Grouping" },
                { fMergeMenuHandle,        fMergePanel,        "Merge" },
                { fShadingMenuHandle,      fShadingPanel,      "Shading" },
                { fBlendMenuHandle,        fBlendPanel,        "Blend" },
                { fPerspectiveMenuHandle,  fPerspectivePanel,  "Perspective" },
                // Application submenu panel toggles (same panels, different menu items)
                { fMenuCleanupHandle,   fCleanupPanel,   "Cleanup (menu)" },
                { fMenuGroupingHandle,  fGroupingPanel,  "Grouping (menu)" },
                { fMenuMergeHandle,     fMergePanel,     "Merge (menu)" },
                { fMenuSelectionHandle, fSelectionPanel,  "Selection (menu)" },
            };
            for (auto& p : panels) {
                if (message->menuItem == p.menu && p.panel) {
                    AIBoolean isShown = false;
                    sAIPanel->IsShown(p.panel, isShown);
                    sAIPanel->Show(p.panel, !isShown);
                    fprintf(stderr, "[IllTool] %s panel toggled to %s\n",
                            p.name, isShown ? "hidden" : "visible");
                    break;
                }
            }
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::UpdateMenuItem(AIMenuMessage* message)
{
    ASErr result = kNoErr;
    try
    {
        // Update checkmarks for app menu items based on current state
        if (!sAIMenu) return kNoErr;

        // Check if our tool is currently selected
        AIToolHandle currentTool = nullptr;
        bool ourToolActive = false;
        if (sAITool) {
            sAITool->GetSelectedTool(&currentTool);
            ourToolActive = (currentTool == fToolHandle || currentTool == fPerspectiveToolHandle);
        }
        BridgeToolMode currentMode = BridgeGetToolMode();

        // Tool activation items -- checkmark when active in that mode
        if (message->menuItem == fMenuLassoHandle) {
            sAIMenu->CheckItem(fMenuLassoHandle,
                ourToolActive && currentMode == BridgeToolMode::Lasso);
        }
        else if (message->menuItem == fMenuSmartHandle) {
            sAIMenu->CheckItem(fMenuSmartHandle,
                ourToolActive && currentMode == BridgeToolMode::Smart);
        }
        // Panel toggle items -- checkmark when panel is shown
        else if (sAIPanel) {
            struct { AIMenuItemHandle menu; AIPanelRef panel; } items[] = {
                { fMenuCleanupHandle,      fCleanupPanel },
                { fMenuGroupingHandle,     fGroupingPanel },
                { fMenuMergeHandle,        fMergePanel },
                { fMenuSelectionHandle,    fSelectionPanel },
                { fShadingMenuHandle,      fShadingPanel },
                { fBlendMenuHandle,        fBlendPanel },
                { fPerspectiveMenuHandle,  fPerspectivePanel },
            };
            for (auto& item : items) {
                if (message->menuItem == item.menu && item.panel) {
                    AIBoolean isShown = false;
                    sAIPanel->IsShown(item.panel, isShown);
                    sAIMenu->CheckItem(item.menu, isShown);
                    break;
                }
            }
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

// Forward declaration — defined later in the file (non-static: shared across modules)
ASErr GetMatchingArtIsolationAware(
    AIMatchingArtSpec* spec, ai::int16 numSpecs,
    AIArtHandle*** matches, ai::int32* numMatches);

//========================================================================================
//  Notifiers
//========================================================================================

ASErr IllToolPlugin::Notify(AINotifierMessage* message)
{
    ASErr result = kNoErr;
    try
    {
        if (message->notifier == fNotifySelectionChanged) {
            // Invalidate the entire document view so annotations redraw.
            InvalidateFullView();

            // Update selection count from the notifier context (SDK calls work here)
            int count = 0;
            AIMatchingArtSpec spec(kPathArt, 0, 0);
            AIArtHandle** matches = nullptr;
            ai::int32 numMatches = 0;
            ASErr selErr = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
            if (selErr == kNoErr && numMatches > 0) {
                for (ai::int32 i = 0; i < numMatches; i++) {
                    AIArtHandle art = (*matches)[i];
                    ai::int32 attrs = 0;
                    sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
                    if (attrs & (kArtLocked | kArtHidden)) continue;
                    ai::int16 segCount = 0;
                    sAIPath->GetPathSegmentCount(art, &segCount);
                    for (ai::int16 s = 0; s < segCount; s++) {
                        ai::int16 sel = kSegmentNotSelected;
                        sAIPath->GetPathSegmentSelected(art, s, &sel);
                        if (sel & kSegmentPointSelected) count++;
                    }
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            }
            // Store the count so the panel timer can read it without SDK calls
            fLastKnownSelectionCount = count;
            fprintf(stderr, "[IllTool] SelectionChanged: %d anchors selected\n", count);

            // Auto-classify the selected shape when selection changes
            if (count > 0) {
                BridgeRequestClassify();
            } else {
                fLastDetectedShape = "---";
            }
        }
        if (message->notifier == fShutdownApplicationNotifier) {
            fprintf(stderr, "[IllTool] Application shutdown notifier received\n");
            StopHttpBridge();
            if (fResourceManagerHandle != NULL) {
                sAIUser->DisposeCursorResourceMgr(fResourceManagerHandle);
                fResourceManagerHandle = NULL;
            }
        }

        // Stage 8: Locked isolation mode — re-enter if user escapes while in working mode
        if (message->notifier == fIsolationChangedNotifier) {
            if (fInWorkingMode && fWorkingGroup && sAIIsolationMode) {
                AIIsolationModeChangedNotifierData* data =
                    (AIIsolationModeChangedNotifierData*)message->notifyData;
                if (data && !data->inIsolationMode) {
                    // User exited isolation while in working mode — re-enter immediately
                    fprintf(stderr, "[IllTool] Isolation breach detected (notifier) — re-entering isolation\n");
                    if (sAIIsolationMode->CanIsolateArt(fWorkingGroup)) {
                        ASErr isoErr = sAIIsolationMode->EnterIsolationMode(fWorkingGroup, false);
                        if (isoErr == kNoErr) {
                            fprintf(stderr, "[IllTool] Re-entered isolation mode via notifier\n");
                        } else {
                            fprintf(stderr, "[IllTool] Re-enter isolation failed: %d\n", (int)isoErr);
                        }
                    }
                }
            }
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Tool callbacks
//========================================================================================

/*
    ToolMouseDown — handle click for polygon lasso tool.
*/
ASErr IllToolPlugin::ToolMouseDown(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        // Perspective tool: dispatch to dedicated handler
        if (message->tool == fPerspectiveToolHandle) {
            PerspectiveToolMouseDown(message);
            return kNoErr;
        }

        // Blend pick mode: intercept clicks to store path A or B (P1 fix)
        int blendPickMode = BridgeGetBlendPickMode();
        if (blendPickMode == 1 || blendPickMode == 2) {
            AIRealPoint clickPt = message->cursor;
            if (sAIHitTest) {
                AIHitRef hitRef = NULL;
                ASErr hitErr = sAIHitTest->HitTest(NULL, &clickPt, kAllHitRequest, &hitRef);
                if (hitErr == kNoErr && hitRef && sAIHitTest->IsHit(hitRef)) {
                    AIArtHandle hitArt = sAIHitTest->GetArt(hitRef);
                    short artType = kUnknownArt;
                    if (hitArt) sAIArt->GetArtType(hitArt, &artType);
                    if (hitArt && artType == kPathArt) {
                        if (blendPickMode == 1) {
                            fBlendPathA = hitArt;
                            BridgeSetBlendPathASet(true);
                            fprintf(stderr, "[IllTool Blend] Picked path A: %p\n", (void*)hitArt);
                        } else {
                            fBlendPathB = hitArt;
                            BridgeSetBlendPathBSet(true);
                            fprintf(stderr, "[IllTool Blend] Picked path B: %p\n", (void*)hitArt);
                        }
                    } else {
                        fprintf(stderr, "[IllTool Blend] Click did not hit a path\n");
                    }
                    if (hitRef) sAIHitTest->Release(hitRef);
                } else if (hitRef) {
                    sAIHitTest->Release(hitRef);
                }
            }
            BridgeSetBlendPickMode(0);  // exit pick mode after click
            return kNoErr;
        }

        BridgeToolMode mode = BridgeGetToolMode();

        if (mode == BridgeToolMode::Lasso) {
            double now = CurrentTimeSeconds();
            bool isDoubleClick = (now - fLastClickTime) < kDoubleClickThreshold;
            fLastClickTime = now;

            if (isDoubleClick && fPolygonVertices.size() >= 3) {
                // Close polygon and select segments inside it
                fprintf(stderr, "[IllTool] Polygon closed with %zu vertices — selecting\n",
                        fPolygonVertices.size());
                ExecutePolygonSelection();
                fPolygonVertices.clear();
                UpdatePolygonOverlay();
            } else {
                // Add vertex
                fPolygonVertices.push_back(message->cursor);
                fprintf(stderr, "[IllTool] Polygon vertex added: (%.1f, %.1f) — %zu total\n",
                        message->cursor.h, message->cursor.v, fPolygonVertices.size());
                UpdatePolygonOverlay();
            }
        } else {
            // Smart mode: hit-test at click location, compute boundary signature,
            // find all paths with matching signature, and select them.
            AIRealPoint clickPt = message->cursor;
            fprintf(stderr, "[IllTool Smart] Click at (%.1f, %.1f)\n", clickPt.h, clickPt.v);

            if (!sAIHitTest) {
                fprintf(stderr, "[IllTool Smart] AIHitTestSuite not available\n");
            } else {
                AIHitRef hitRef = NULL;
                ASErr hitErr = sAIHitTest->HitTest(NULL, &clickPt, kAllHitRequest, &hitRef);
                if (hitErr == kNoErr && hitRef && sAIHitTest->IsHit(hitRef)) {
                    AIArtHandle hitArt = sAIHitTest->GetArt(hitRef);
                    if (hitArt) {
                        // Verify it's a path
                        short artType = kUnknownArt;
                        sAIArt->GetArtType(hitArt, &artType);
                        if (artType == kPathArt) {
                            // Compute boundary signature of the hit path
                            BoundarySignature sig = ComputeSignature(hitArt);
                            fprintf(stderr, "[IllTool Smart] Hit: path=%p, Signature: len=%.1f curv=%.3f segs=%d closed=%s\n",
                                    (void*)hitArt, sig.totalLength, sig.avgCurvature,
                                    sig.segmentCount, sig.isClosed ? "yes" : "no");

                            // Get threshold from panel slider
                            double threshold = BridgeGetSmartThreshold();

                            // Find and select all matching paths
                            SelectMatchingPaths(sig, threshold, hitArt);
                        } else {
                            fprintf(stderr, "[IllTool Smart] Hit art is not a path (type=%d)\n", artType);
                        }
                    } else {
                        fprintf(stderr, "[IllTool Smart] HitTest returned no art\n");
                    }
                    sAIHitTest->Release(hitRef);
                } else {
                    fprintf(stderr, "[IllTool Smart] No hit at click location\n");
                    if (hitRef) sAIHitTest->Release(hitRef);
                }
            }
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

/*
    ProcessOperationQueue — called from AITimerSuite at ~10Hz in SDK message context.
    Dequeues operations from the H1 operation queue and executes them.
    This is the ONLY safe place for SDK API calls triggered by non-SDK threads
    (Cocoa buttons, HTTP handlers).
*/
void IllToolPlugin::ProcessOperationQueue()
{
    // Stage 10: sync perspective grid state from bridge (continuous state, not queued)
    SyncPerspectiveFromBridge();

    // Check dirty flag for HTTP-sent draw commands
    if (IsDirty()) {
        SetDirty(false);
        InvalidateFullView();
    }

    // H1: Dequeue and process all pending operations
    PluginOp op;
    while (BridgeDequeueOp(op)) {
        switch (op.type) {
            case OpType::LassoClose:
                if (fPolygonVertices.size() >= 3) {
                    fprintf(stderr, "[IllTool Timer] Lasso close — closing polygon with %zu vertices\n",
                            fPolygonVertices.size());
                    ExecutePolygonSelection();
                    fPolygonVertices.clear();
                    UpdatePolygonOverlay();
                    InvalidateFullView();
                }
                break;

            case OpType::LassoClear:
                if (!fPolygonVertices.empty()) {
                    fprintf(stderr, "[IllTool Timer] Lasso clear — discarding %zu vertices\n",
                            fPolygonVertices.size());
                    fPolygonVertices.clear();
                    UpdatePolygonOverlay();
                    InvalidateFullView();
                }
                break;

            case OpType::WorkingApply:
                fprintf(stderr, "[IllTool Timer] Working Apply (deleteOriginals=%s)\n",
                        op.boolParam1 ? "true" : "false");
                ApplyWorkingMode(op.boolParam1);
                InvalidateFullView();
                break;

            case OpType::WorkingCancel:
                fprintf(stderr, "[IllTool Timer] Working Cancel\n");
                CancelWorkingMode();
                InvalidateFullView();
                break;

            case OpType::AverageSelection:
                fprintf(stderr, "[IllTool Timer] Average Selection\n");
                AverageSelection();
                InvalidateFullView();
                break;

            case OpType::Classify:
                fprintf(stderr, "[IllTool Timer] Classify Selection\n");
                ClassifySelection();
                break;

            case OpType::Reclassify:
                fprintf(stderr, "[IllTool Timer] Reclassify as type %d\n", op.intParam);
                ReclassifyAs(static_cast<BridgeShapeType>(op.intParam));
                InvalidateFullView();
                break;

            case OpType::Simplify: {
                if (fInWorkingMode && !fLODCache.empty()) {
                    // LOD scrubbing mode: use precomputed cache
                    int level = (int)op.param1;
                    fprintf(stderr, "[IllTool Timer] Simplify LOD (slider=%d)\n", level);
                    ApplyLODLevel(level);
                } else {
                    // Legacy mode: one-shot Douglas-Peucker
                    double tolerance = op.param1 * 0.5;
                    fprintf(stderr, "[IllTool Timer] Simplify (slider=%.0f, tolerance=%.1f)\n",
                            op.param1, tolerance);
                    SimplifySelection(tolerance);
                }
                InvalidateFullView();
                break;
            }

            case OpType::CopyToGroup:
                fprintf(stderr, "[IllTool Timer] Copy to Group '%s'\n", op.strParam.c_str());
                CopyToGroup(op.strParam);
                InvalidateFullView();
                break;

            case OpType::Detach:
                fprintf(stderr, "[IllTool Timer] Detach from Group\n");
                DetachFromGroup();
                InvalidateFullView();
                break;

            case OpType::Split:
                fprintf(stderr, "[IllTool Timer] Split to New Group\n");
                SplitToNewGroup();
                InvalidateFullView();
                break;

            case OpType::ScanEndpoints:
                fprintf(stderr, "[IllTool Timer] Scan Endpoints (tolerance=%.1f)\n", op.param1);
                ScanEndpoints(op.param1);
                InvalidateFullView();
                break;

            case OpType::MergeEndpoints:
                fprintf(stderr, "[IllTool Timer] Merge Endpoints (chain=%s, preserve=%s)\n",
                        op.boolParam1 ? "true" : "false", op.boolParam2 ? "true" : "false");
                MergeEndpoints(op.boolParam1, op.boolParam2);
                InvalidateFullView();
                break;

            case OpType::UndoMerge:
                fprintf(stderr, "[IllTool Timer] Undo Merge\n");
                UndoMerge();
                InvalidateFullView();
                break;

            case OpType::SelectSmall:
                fprintf(stderr, "[IllTool Timer] Select Small (threshold=%.1f)\n", op.param1);
                SelectSmall(op.param1);
                InvalidateFullView();
                break;

            case OpType::UndoShape:
                fprintf(stderr, "[IllTool Timer] Undo Shape\n");
                fUndoStack.Undo();
                InvalidateFullView();
                break;

            case OpType::ClearPerspective:
                ClearPerspectiveGrid();
                break;

            case OpType::LockPerspective:
                fPerspectiveGrid.locked = op.boolParam1;
                fprintf(stderr, "[IllTool Timer] Perspective grid %s\n",
                        op.boolParam1 ? "locked" : "unlocked");
                InvalidateFullView();
                break;

            case OpType::SetGridDensity:
                fPerspectiveGrid.gridDensity = op.intParam;
                if (fPerspectiveGrid.gridDensity < 2) fPerspectiveGrid.gridDensity = 2;
                if (fPerspectiveGrid.gridDensity > 20) fPerspectiveGrid.gridDensity = 20;
                fprintf(stderr, "[IllTool Timer] Set Grid Density: %d\n", fPerspectiveGrid.gridDensity);
                InvalidateFullView();
                break;

            // Stage 11: Blend Harmonization
            case OpType::BlendPickA:
                fprintf(stderr, "[IllTool Timer] Blend Pick A mode\n");
                BridgeSetBlendPickMode(1);
                break;

            case OpType::BlendPickB:
                fprintf(stderr, "[IllTool Timer] Blend Pick B mode\n");
                BridgeSetBlendPickMode(2);
                break;

            case OpType::BlendExecute:
                if (fBlendPathA && fBlendPathB) {
                    // Validate handles before use (P1 fix — paths could be stale)
                    short typeA = 0, typeB = 0;
                    if (sAIArt->GetArtType(fBlendPathA, &typeA) != kNoErr || typeA != kPathArt) {
                        fprintf(stderr, "[IllTool Timer] Blend Execute: path A is stale\n");
                        fBlendPathA = nullptr; BridgeSetBlendPathASet(false);
                        break;
                    }
                    if (sAIArt->GetArtType(fBlendPathB, &typeB) != kNoErr || typeB != kPathArt) {
                        fprintf(stderr, "[IllTool Timer] Blend Execute: path B is stale\n");
                        fBlendPathB = nullptr; BridgeSetBlendPathBSet(false);
                        break;
                    }
                    int steps = BridgeGetBlendSteps();
                    int easing = BridgeGetBlendEasing();
                    fprintf(stderr, "[IllTool Timer] Blend Execute (steps=%d, easing=%d)\n", steps, easing);
                    int created = ExecuteBlend(fBlendPathA, fBlendPathB, steps, easing);
                    fprintf(stderr, "[IllTool Timer] Blend created %d paths\n", created);
                    InvalidateFullView();
                } else {
                    fprintf(stderr, "[IllTool Timer] Blend Execute: paths not set (A=%p B=%p)\n",
                            (void*)fBlendPathA, (void*)fBlendPathB);
                }
                break;

            case OpType::BlendSetSteps:
                BridgeSetBlendSteps(op.intParam);
                fprintf(stderr, "[IllTool Timer] Blend set steps=%d\n", op.intParam);
                break;

            case OpType::BlendSetEasing:
                BridgeSetBlendEasing(op.intParam);
                fprintf(stderr, "[IllTool Timer] Blend set easing=%d\n", op.intParam);
                break;

            // Stage 12: Surface Shading
            case OpType::ShadingApplyBlend:
            case OpType::ShadingApplyMesh:
                fprintf(stderr, "[IllTool Timer] Shading %s\n",
                        op.type == OpType::ShadingApplyBlend ? "Apply Blend" : "Apply Mesh");
                DispatchShadingOp(op.type);
                InvalidateFullView();
                break;

            case OpType::ShadingSetMode:
                BridgeSetShadingMode(op.intParam);
                fprintf(stderr, "[IllTool Timer] Shading set mode=%d\n", op.intParam);
                break;

            // Stage 10b-d: Perspective operations
            case OpType::MirrorPerspective:
                fprintf(stderr, "[IllTool Timer] Mirror in Perspective (axis=%d, replace=%s)\n",
                        op.intParam, op.boolParam1 ? "true" : "false");
                MirrorInPerspective(op.intParam, op.boolParam1);
                InvalidateFullView();
                break;

            case OpType::DuplicatePerspective:
                fprintf(stderr, "[IllTool Timer] Duplicate in Perspective (count=%d, spacing=%d)\n",
                        op.intParam, (int)op.param1);
                DuplicateInPerspective(op.intParam, (int)op.param1);
                InvalidateFullView();
                break;

            case OpType::PastePerspective:
                fprintf(stderr, "[IllTool Timer] Paste in Perspective (plane=%d, scale=%.2f)\n",
                        op.intParam, op.param1);
                PasteInPerspective(op.intParam, (float)op.param1);
                InvalidateFullView();
                break;

            case OpType::PerspectiveSave:
                fprintf(stderr, "[IllTool Timer] Save Perspective to Document\n");
                SavePerspectiveToDocument();
                break;

            case OpType::PerspectiveLoad:
                fprintf(stderr, "[IllTool Timer] Load Perspective from Document\n");
                LoadPerspectiveFromDocument();
                InvalidateFullView();
                break;

            // Stage 14: Decompose operations
            case OpType::Decompose:
                fprintf(stderr, "[IllTool Timer] Decompose (sensitivity=%.2f)\n", op.param1);
                RunDecompose((float)op.param1);
                InvalidateFullView();
                break;

            case OpType::DecomposeAccept:
                fprintf(stderr, "[IllTool Timer] Decompose Accept\n");
                AcceptDecompose();
                InvalidateFullView();
                break;

            case OpType::DecomposeAcceptOne:
                fprintf(stderr, "[IllTool Timer] Decompose Accept One (cluster=%d)\n", op.intParam);
                AcceptCluster(op.intParam);
                InvalidateFullView();
                break;

            case OpType::DecomposeSplit:
                fprintf(stderr, "[IllTool Timer] Decompose Split (cluster=%d)\n", op.intParam);
                SplitCluster(op.intParam);
                InvalidateFullView();
                break;

            case OpType::DecomposeMergeGroups:
                fprintf(stderr, "[IllTool Timer] Decompose Merge Groups (%d + %d)\n",
                        op.intParam, (int)op.param1);
                MergeDecomposeClusters(op.intParam, (int)op.param1);
                InvalidateFullView();
                break;

            case OpType::DecomposeCancel:
                fprintf(stderr, "[IllTool Timer] Decompose Cancel\n");
                CancelDecompose();
                InvalidateFullView();
                break;
        }
    }

    // Stage 8: Enforce locked isolation mode (timer-based safety net).
    // If the user is in working mode but managed to exit isolation (e.g., double-click
    // outside, or the notifier missed it), re-enter isolation immediately.
    // The notifier handles most cases, but the timer catches edge cases.
    if (fInWorkingMode && fWorkingGroup && sAIIsolationMode) {
        if (!sAIIsolationMode->IsInIsolationMode()) {
            fprintf(stderr, "[IllTool Timer] Isolation breach detected — re-entering\n");
            if (sAIIsolationMode->CanIsolateArt(fWorkingGroup)) {
                ASErr isoErr = sAIIsolationMode->EnterIsolationMode(fWorkingGroup, false);
                if (isoErr == kNoErr) {
                    fprintf(stderr, "[IllTool Timer] Re-entered isolation mode\n");
                    sAIDocument->RedrawDocument();
                } else {
                    fprintf(stderr, "[IllTool Timer] Re-enter isolation failed: %d\n", (int)isoErr);
                }
            }
        }
    }
}

/*
    TrackToolCursor — called on every mouse-move while our tool is selected.
    Handles cursor position tracking, rubber-band polygon overlay, and
    dirty-flag checking for responsiveness when the tool is active.
    NOTE: Operation dispatch has moved to ProcessOperationQueue (AITimerSuite).
    The dirty check remains here for extra responsiveness when the tool is active.
*/
ASErr IllToolPlugin::TrackToolCursor(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        fLastCursorPos = message->cursor;

        // Check dirty flag for HTTP-sent draw commands (also checked by timer,
        // but checking here too gives immediate response when tool is active)
        if (IsDirty()) {
            SetDirty(false);
            InvalidateFullView();
        }

        if (message->tool == fPerspectiveToolHandle) {
            // Perspective tool: use crosshair cursor
            if (sAIUser != NULL) {
                result = sAIUser->SetSVGCursor(kIllToolIconResourceID, fResourceManagerHandle);
            }
        } else {
            // Update rubber band if drawing polygon
            if (BridgeGetToolMode() == BridgeToolMode::Lasso && !fPolygonVertices.empty()) {
                UpdatePolygonOverlay();
            }

            // Set cursor
            if (sAIUser != NULL) {
                result = sAIUser->SetSVGCursor(kIllToolIconResourceID, fResourceManagerHandle);
            }
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

/*
    SelectTool — activates the annotator when the user selects our tool.
*/
ASErr IllToolPlugin::SelectTool(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (message->tool == fPerspectiveToolHandle) {
            fprintf(stderr, "[IllTool] Perspective tool selected — activating annotator\n");
        } else {
            fprintf(stderr, "[IllTool] Tool selected — activating annotator\n");
        }
        result = sAIAnnotator->SetAnnotatorActive(fAnnotatorHandle, true);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

/*
    DeselectTool — deactivates the annotator when the user switches away.
    Clears any in-progress polygon.
*/
ASErr IllToolPlugin::DeselectTool(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (message->tool == fPerspectiveToolHandle) {
            fprintf(stderr, "[IllTool] Perspective tool deselected — deactivating annotator\n");
            // Clear perspective drag state
            fPerspDragLine = -1;
            fPerspDragHandle = 0;
        } else {
            fprintf(stderr, "[IllTool] Tool deselected — deactivating annotator\n");
            // Clear in-progress polygon
            if (!fPolygonVertices.empty()) {
                fPolygonVertices.clear();
                // Clear only the polygon overlay, keep HTTP draw commands
            }
        }

        result = sAIAnnotator->SetAnnotatorActive(fAnnotatorHandle, false);
        aisdk::check_ai_error(result);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Registration helpers
//========================================================================================

ASErr IllToolPlugin::AddTool(SPInterfaceMessage *message)
{
    ASErr result = kNoErr;
    try {
        AIAddToolData data;
        data.title = ai::UnicodeString::FromRoman("IllTool Handle");
        data.tooltip = ai::UnicodeString::FromRoman("IllTool Handle — overlay drawing tool");

        data.sameGroupAs = kNoTool;
        data.sameToolsetAs = kNoTool;

        data.normalIconResID = kIllToolIconResourceID;
        data.darkIconResID = kIllToolIconResourceID;
        data.iconType = ai::IconType::kSVG;

        ai::int32 options = kToolWantsToTrackCursorOption;

        result = sAITool->AddTool(message->d.self, kIllToolTool, data, options, &fToolHandle);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Tool registered: %s\n", kIllToolTool);

        // Register the Perspective tool in the same toolbox group
        AIAddToolData perspData;
        perspData.title = ai::UnicodeString::FromRoman("IllTool Perspective");
        perspData.tooltip = ai::UnicodeString::FromRoman("IllTool Perspective — place and drag perspective lines");

        AIToolType mainToolNum = kNoTool;
        sAITool->GetToolNumberFromHandle(fToolHandle, &mainToolNum);
        perspData.sameGroupAs = mainToolNum;    // join main tool's flyout group
        perspData.sameToolsetAs = mainToolNum;  // same toolset as the main tool

        perspData.normalIconResID = kIllToolIconResourceID;  // reuse icon for now
        perspData.darkIconResID = kIllToolIconResourceID;
        perspData.iconType = ai::IconType::kSVG;

        ai::int32 perspOptions = kToolWantsToTrackCursorOption;

        result = sAITool->AddTool(message->d.self, kIllToolPerspectiveTool, perspData,
                                   perspOptions, &fPerspectiveToolHandle);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Tool registered: %s\n", kIllToolPerspectiveTool);
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] AddTool error: %d\n", (int)ex);
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::AddAnnotator(SPInterfaceMessage *message)
{
    ASErr result = kNoErr;
    try {
        result = sAIAnnotator->AddAnnotator(message->d.self, "IllTool Overlay", &fAnnotatorHandle);
        aisdk::check_ai_error(result);

        result = sAIAnnotator->SetAnnotatorActive(fAnnotatorHandle, false);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Annotator registered (inactive)\n");
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::AddNotifier(SPInterfaceMessage *message)
{
    ASErr result = kNoErr;
    try {
        result = sAINotifier->AddNotifier(fPluginRef, "IllToolPlugin",
                    kAIArtSelectionChangedNotifier, &fNotifySelectionChanged);
        aisdk::check_ai_error(result);

        result = sAINotifier->AddNotifier(fPluginRef, "IllToolPlugin",
                    kAIApplicationShutdownNotifier, &fShutdownApplicationNotifier);
        aisdk::check_ai_error(result);

        // Stage 8: Register isolation mode change notifier for locked isolation
        result = sAINotifier->AddNotifier(fPluginRef, "IllToolPlugin",
                    kAIIsolationModeChangedNotifier, &fIsolationChangedNotifier);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] WARNING: IsolationModeChanged notifier failed: %d (non-fatal)\n",
                    (int)result);
            result = kNoErr;  // Non-fatal — timer fallback will still work
        }

        fprintf(stderr, "[IllTool] Notifiers registered\n");
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Application menu registration (Window > IllTool submenu)
//========================================================================================

/*
    AddAppMenu — Creates a "Window > IllTool" submenu with tool activation
    and panel toggle items. Follows the SDK pattern from MenuPlay sample:
    1. Create a root menu item in the Window menu
    2. Convert it to a submenu group via AddMenuGroupAsSubMenu
    3. Add child items to the new group
*/
ASErr IllToolPlugin::AddAppMenu(SPInterfaceMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (!sAIMenu) {
            fprintf(stderr, "[IllTool] AddAppMenu: AIMenuSuite not available\n");
            return kCantHappenErr;
        }

        // Step 1: Create the root "IllTool" item in the Window menu's Tool Palettes group.
        // This item will become the submenu header.
        AIPlatformAddMenuItemDataUS rootMenuData;
        rootMenuData.groupName = kToolPalettesMenuGroup;
        rootMenuData.itemText = ai::UnicodeString("IllTool");

        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuGroupName,
                                       &rootMenuData, kMenuItemWantsUpdateOption,
                                       &fAppMenuRootHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: AddMenuItem (root) failed: %d\n", (int)result);
            return result;
        }

        // Step 2: Convert the root item into a submenu group
        AIMenuGroup subMenuGroup = nullptr;
        result = sAIMenu->AddMenuGroupAsSubMenu(kIllToolSubMenuGroupName,
                                                  kMenuGroupNoOptions,
                                                  fAppMenuRootHandle,
                                                  &subMenuGroup);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: AddMenuGroupAsSubMenu failed: %d\n", (int)result);
            return result;
        }

        // Step 3: Add tool activation items to the submenu
        AIPlatformAddMenuItemDataUS itemData;
        itemData.groupName = kIllToolSubMenuGroupName;

        // Polygon Lasso
        itemData.itemText = ai::UnicodeString("Polygon Lasso");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuLassoItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuLassoHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Polygon Lasso item failed: %d\n", (int)result);
        }

        // Smart Select
        itemData.itemText = ai::UnicodeString("Smart Select");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuSmartItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuSmartHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Smart Select item failed: %d\n", (int)result);
        }

        // Separator
        AIMenuItemHandle sepHandle = nullptr;
        itemData.itemText = ai::UnicodeString("");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Sep1",
                                       &itemData, kMenuItemIsSeparator,
                                       &sepHandle);
        // Separator failure is non-fatal, continue

        // Step 4: Add panel toggle items to the submenu

        // Shape Cleanup
        itemData.itemText = ai::UnicodeString("Shape Cleanup");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuCleanupItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuCleanupHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Shape Cleanup item failed: %d\n", (int)result);
        }

        // Grouping Tools
        itemData.itemText = ai::UnicodeString("Grouping Tools");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuGroupingItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuGroupingHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Grouping Tools item failed: %d\n", (int)result);
        }

        // Smart Merge
        itemData.itemText = ai::UnicodeString("Smart Merge");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuMergeItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuMergeHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Smart Merge item failed: %d\n", (int)result);
        }

        // Selection Panel
        itemData.itemText = ai::UnicodeString("Selection Panel");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuSelectionItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuSelectionHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Selection Panel item failed: %d\n", (int)result);
        }

        // Shading Panel
        itemData.itemText = ai::UnicodeString("Shading");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Shading",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fShadingMenuHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Shading item failed: %d\n", (int)result);
        }

        // Blend Panel
        itemData.itemText = ai::UnicodeString("Blend");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Blend",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fBlendMenuHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Blend item failed: %d\n", (int)result);
        }

        // Perspective Panel
        itemData.itemText = ai::UnicodeString("Perspective");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Perspective",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fPerspectiveMenuHandle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] AddAppMenu: Perspective item failed: %d\n", (int)result);
        }

        fprintf(stderr, "[IllTool] AddAppMenu: submenu registered with 9 items + separator\n");
        result = kNoErr;  // Individual item failures are non-fatal
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] AddAppMenu error: %d\n", (int)ex);
        result = ex;
    }
    catch (...) {
        fprintf(stderr, "[IllTool] AddAppMenu unknown error\n");
        result = kCantHappenErr;
    }
    return result;
}

//========================================================================================
//  Annotation callbacks
//========================================================================================

ASErr IllToolPlugin::DrawAnnotation(AIAnnotatorMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (this->fAnnotator) {
            result = this->fAnnotator->Draw(message);
            aisdk::check_ai_error(result);
        }
        // Stage 10: draw perspective grid overlay
        DrawPerspectiveOverlay(message);

        // Stage 14: draw decompose cluster overlay
        DrawDecomposeOverlay(message);
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

ASErr IllToolPlugin::InvalAnnotation(AIAnnotatorMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (fAnnotator) {
            result = fAnnotator->InvalidateRect(*message->invalidationRects);
            aisdk::check_ai_error(result);
        }
    }
    catch (ai::Error& ex) {
        result = ex;
    }
    catch (...) {
        result = kCantHappenErr;
    }
    return result;
}

/*
    GetMatchingArtIsolationAware — returns matching art, scoped to the
    isolated art tree when in isolation mode.  When in our working mode
    the search root is the working group; otherwise falls through to the
    standard whole-document query.
*/
ASErr GetMatchingArtIsolationAware(
    AIMatchingArtSpec* spec, ai::int16 numSpecs,
    AIArtHandle*** matches, ai::int32* numMatches)
{
    fprintf(stderr, "[IllTool DEBUG] GetMatchingArtIsolationAware: enter\n");
    fprintf(stderr, "[IllTool DEBUG]   sAIIsolationMode=%p\n", (void*)sAIIsolationMode);

    // When in isolation mode, scope the search to the isolated art tree
    if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
        fprintf(stderr, "[IllTool DEBUG]   IsInIsolationMode=TRUE\n");

        // If the plugin has an active working group, search within it directly
        bool hasWorkingMode = gPlugin && gPlugin->IsInWorkingMode();
        AIArtHandle wg = gPlugin ? gPlugin->GetWorkingGroup() : nullptr;
        fprintf(stderr, "[IllTool DEBUG]   gPlugin=%p, IsInWorkingMode=%s, workingGroup=%p\n",
                (void*)gPlugin, hasWorkingMode ? "true" : "false", (void*)wg);

        if (hasWorkingMode && wg) {
            ASErr err = sAIMatchingArt->GetMatchingArtFromArt(
                wg, spec, numSpecs, matches, numMatches);
            fprintf(stderr, "[IllTool DEBUG]   GetMatchingArtFromArt(workingGroup): err=%d, numMatches=%d\n",
                    (int)err, (int)*numMatches);
            if (err == kNoErr && *numMatches > 0) {
                fprintf(stderr, "[IllTool DEBUG]   -> returning via working group path (%d matches)\n",
                        (int)*numMatches);
                return kNoErr;
            }
        }

        // Fallback: get the isolated art parent and search from there
        AIArtHandle isolatedArtParent = nullptr;
        sAIIsolationMode->GetIsolatedArtAndParents(&isolatedArtParent, nullptr);
        fprintf(stderr, "[IllTool DEBUG]   GetIsolatedArtAndParents: isolatedArtParent=%p\n",
                (void*)isolatedArtParent);
        if (isolatedArtParent) {
            ASErr err = sAIMatchingArt->GetMatchingArtFromArt(
                isolatedArtParent, spec, numSpecs, matches, numMatches);
            fprintf(stderr, "[IllTool DEBUG]   GetMatchingArtFromArt(isolatedParent): err=%d, numMatches=%d\n",
                    (int)err, (int)*numMatches);
            if (err == kNoErr && *numMatches > 0) {
                fprintf(stderr, "[IllTool DEBUG]   -> returning via isolated parent path (%d matches)\n",
                        (int)*numMatches);
                return kNoErr;
            }
        }
    } else {
        fprintf(stderr, "[IllTool DEBUG]   IsInIsolationMode=FALSE (or suite unavailable)\n");
    }

    // Not in isolation mode, or isolation search found nothing — search whole document
    fprintf(stderr, "[IllTool DEBUG]   -> falling through to whole-document GetMatchingArt\n");
    ASErr fallbackErr = sAIMatchingArt->GetMatchingArt(spec, numSpecs, matches, numMatches);
    fprintf(stderr, "[IllTool DEBUG]   GetMatchingArt(whole doc): err=%d, numMatches=%d\n",
            (int)fallbackErr, (int)*numMatches);
    return fallbackErr;
}

