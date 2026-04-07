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
#include "LearningEngine.h"
#include <cstdio>
#include <cmath>
#include <chrono>
#include <algorithm>
#include <string>
#include <cfloat>

IllToolPlugin *gPlugin = NULL;

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
    Plugin(pluginRef), fToolHandle(NULL), fAboutPluginMenu(NULL),
    fAnnotatorHandle(NULL), fNotifySelectionChanged(NULL),
    fAnnotator(NULL),
    fResourceManagerHandle(NULL),
    fOperationTimer(NULL),
    fShutdownApplicationNotifier(NULL),
    fIsolationChangedNotifier(NULL),
    fSelectionPanel(NULL), fCleanupPanel(NULL),
    fGroupingPanel(NULL), fMergePanel(NULL),
    fSelectionMenuHandle(NULL), fCleanupMenuHandle(NULL),
    fGroupingMenuHandle(NULL), fMergeMenuHandle(NULL),
    fAppMenuRootHandle(NULL),
    fMenuLassoHandle(NULL), fMenuSmartHandle(NULL),
    fMenuCleanupHandle(NULL), fMenuGroupingHandle(NULL),
    fMenuMergeHandle(NULL), fMenuSelectionHandle(NULL),
    fSelectionController(NULL), fCleanupController(NULL),
    fGroupingController(NULL), fMergeController(NULL),
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
                { fSelectionMenuHandle, fSelectionPanel, "Selection" },
                { fCleanupMenuHandle,   fCleanupPanel,   "Cleanup" },
                { fGroupingMenuHandle,  fGroupingPanel,  "Grouping" },
                { fMergeMenuHandle,     fMergePanel,     "Merge" },
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
            ourToolActive = (currentTool == fToolHandle);
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
                { fMenuCleanupHandle,   fCleanupPanel },
                { fMenuGroupingHandle,  fGroupingPanel },
                { fMenuMergeHandle,     fMergePanel },
                { fMenuSelectionHandle, fSelectionPanel },
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

// Forward declaration — defined later in the file
static ASErr GetMatchingArtIsolationAware(
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
    Checks all atomic flags set by HTTP bridge and panel buttons, then executes
    the corresponding SDK operations.  This is the ONLY safe place for SDK API calls
    triggered by non-SDK threads (Cocoa buttons, HTTP handlers).
*/
void IllToolPlugin::ProcessOperationQueue()
{
    // Check dirty flag for HTTP-sent draw commands
    if (IsDirty()) {
        SetDirty(false);
        InvalidateFullView();
    }

    // Check for lasso close request (Enter key or HTTP /lasso/close)
    if (BridgeIsLassoCloseRequested()) {
        BridgeClearLassoCloseRequest();
        if (fPolygonVertices.size() >= 3) {
            fprintf(stderr, "[IllTool Timer] Lasso close — closing polygon with %zu vertices\n",
                    fPolygonVertices.size());
            ExecutePolygonSelection();
            fPolygonVertices.clear();
            UpdatePolygonOverlay();
            InvalidateFullView();
        }
    }

    // Check for lasso clear request (Escape key or HTTP /lasso/clear)
    if (BridgeIsLassoClearRequested()) {
        BridgeClearLassoClearRequest();
        if (!fPolygonVertices.empty()) {
            fprintf(stderr, "[IllTool Timer] Lasso clear — discarding %zu vertices\n",
                    fPolygonVertices.size());
            fPolygonVertices.clear();
            UpdatePolygonOverlay();
            InvalidateFullView();
        }
    }

    // Check for working mode apply request (panel Apply button or HTTP /working/apply)
    if (BridgeIsWorkingApplyRequested()) {
        bool delOrig = BridgeGetWorkingApplyDeleteOriginals();
        BridgeClearWorkingApplyRequest();
        fprintf(stderr, "[IllTool Timer] Working Apply (deleteOriginals=%s)\n",
                delOrig ? "true" : "false");
        ApplyWorkingMode(delOrig);
        InvalidateFullView();
    }

    // Check for working mode cancel request (panel Cancel button or HTTP /working/cancel)
    if (BridgeIsWorkingCancelRequested()) {
        BridgeClearWorkingCancelRequest();
        fprintf(stderr, "[IllTool Timer] Working Cancel\n");
        CancelWorkingMode();
        InvalidateFullView();
    }

    // Check for average selection request (panel button)
    if (BridgeIsAverageSelectionRequested()) {
        BridgeClearAverageSelectionRequest();
        fprintf(stderr, "[IllTool Timer] Average Selection — executing in SDK context\n");
        AverageSelection();
        InvalidateFullView();
    }

    // Check for shape classification request
    if (BridgeIsClassifyRequested()) {
        BridgeClearClassifyRequest();
        fprintf(stderr, "[IllTool Timer] Classify Selection — executing in SDK context\n");
        ClassifySelection();
    }

    // Check for shape reclassification request (force-fit to shape type)
    if (BridgeIsReclassifyRequested()) {
        BridgeShapeType shapeType = BridgeGetReclassifyShapeType();
        BridgeClearReclassifyRequest();
        fprintf(stderr, "[IllTool Timer] Reclassify as type %d — executing in SDK context\n",
                (int)shapeType);
        ReclassifyAs(shapeType);
        InvalidateFullView();
    }

    // Check for simplification request (slider)
    if (BridgeIsSimplifyRequested()) {
        double sliderValue = BridgeGetSimplifySliderValue();
        BridgeClearSimplifyRequest();
        double tolerance = sliderValue * 0.5;  // slider 0-100 → tolerance 0-50pt
        fprintf(stderr, "[IllTool Timer] Simplify (slider=%.0f, tolerance=%.1f) — executing in SDK context\n",
                sliderValue, tolerance);
        SimplifySelection(tolerance);
        InvalidateFullView();
    }

    // Stage 5: Grouping operations
    if (BridgeIsCopyToGroupRequested()) {
        std::string name = BridgeGetCopyToGroupName();
        BridgeClearCopyToGroupRequest();
        fprintf(stderr, "[IllTool Timer] Copy to Group '%s' — executing in SDK context\n", name.c_str());
        CopyToGroup(name);
        InvalidateFullView();
    }

    if (BridgeIsDetachRequested()) {
        BridgeClearDetachRequest();
        fprintf(stderr, "[IllTool Timer] Detach from Group — executing in SDK context\n");
        DetachFromGroup();
        InvalidateFullView();
    }

    if (BridgeIsSplitRequested()) {
        BridgeClearSplitRequest();
        fprintf(stderr, "[IllTool Timer] Split to New Group — executing in SDK context\n");
        SplitToNewGroup();
        InvalidateFullView();
    }

    // Stage 6: Merge operations
    if (BridgeIsScanEndpointsRequested()) {
        double tolerance = BridgeGetScanTolerance();
        BridgeClearScanEndpointsRequest();
        fprintf(stderr, "[IllTool Timer] Scan Endpoints (tolerance=%.1f) — executing in SDK context\n",
                tolerance);
        ScanEndpoints(tolerance);
        InvalidateFullView();
    }

    if (BridgeIsMergeEndpointsRequested()) {
        bool chain = BridgeGetMergeChainMerge();
        bool preserve = BridgeGetMergePreserveHandles();
        BridgeClearMergeEndpointsRequest();
        fprintf(stderr, "[IllTool Timer] Merge Endpoints (chain=%s, preserve=%s) — executing in SDK context\n",
                chain ? "true" : "false", preserve ? "true" : "false");
        MergeEndpoints(chain, preserve);
        InvalidateFullView();
    }

    if (BridgeIsUndoMergeRequested()) {
        BridgeClearUndoMergeRequest();
        fprintf(stderr, "[IllTool Timer] Undo Merge — executing in SDK context\n");
        UndoMerge();
        InvalidateFullView();
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

        // Update rubber band if drawing polygon
        if (BridgeGetToolMode() == BridgeToolMode::Lasso && !fPolygonVertices.empty()) {
            UpdatePolygonOverlay();
        }

        // Set cursor
        if (sAIUser != NULL) {
            result = sAIUser->SetSVGCursor(kIllToolIconResourceID, fResourceManagerHandle);
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
ASErr IllToolPlugin::SelectTool(AIToolMessage* /*message*/)
{
    ASErr result = kNoErr;
    try {
        fprintf(stderr, "[IllTool] Tool selected — activating annotator\n");
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
ASErr IllToolPlugin::DeselectTool(AIToolMessage* /*message*/)
{
    ASErr result = kNoErr;
    try {
        fprintf(stderr, "[IllTool] Tool deselected — deactivating annotator\n");

        // Clear in-progress polygon
        if (!fPolygonVertices.empty()) {
            fPolygonVertices.clear();
            // Clear only the polygon overlay, keep HTTP draw commands
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

        fprintf(stderr, "[IllTool] AddAppMenu: submenu registered with 6 items + separator\n");
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

//========================================================================================
//  Polygon lasso helpers
//========================================================================================

/*
    UpdatePolygonOverlay — builds draw commands for the polygon visualization
    and merges them with any existing HTTP draw commands.
*/
void IllToolPlugin::UpdatePolygonOverlay()
{
    // Get current HTTP draw commands as the base
    std::vector<DrawCommand> commands = GetDrawCommands();

    // Remove any previous lasso overlay commands (identified by id prefix)
    commands.erase(
        std::remove_if(commands.begin(), commands.end(),
            [](const DrawCommand& c) { return c.id.find("_lasso_") == 0; }),
        commands.end()
    );

    // Colors
    Color4 darkCyan    = {0.0, 0.6, 0.7, 1.0};     // filled handles
    Color4 lightCyan   = {0.4, 0.85, 0.95, 0.8};   // dashed lines on top
    Color4 whiteBG     = {1.0, 1.0, 1.0, 0.35};    // semi-opaque white underneath
    Color4 rubberCyan  = {0.4, 0.85, 0.95, 0.5};
    Color4 rubberWhite = {1.0, 1.0, 1.0, 0.2};

    // Helper lambda to add a dual-line (white bg + cyan dashed on top)
    auto addDualLine = [&](const std::string& idBase, Point2D p1, Point2D p2,
                           Color4 bgColor, Color4 fgColor, bool dashed) {
        // Layer 1: semi-opaque white background line
        DrawCommand bg;
        bg.type = DrawCommandType::Line;
        bg.id = idBase + "_bg";
        bg.points = {p1, p2};
        bg.strokeColor = bgColor;
        bg.strokeWidth = 2.0;
        bg.dashed = false;
        commands.push_back(bg);
        // Layer 2: cyan dashed on top
        DrawCommand fg;
        fg.type = DrawCommandType::Line;
        fg.id = idBase + "_fg";
        fg.points = {p1, p2};
        fg.strokeColor = fgColor;
        fg.strokeWidth = 1.0;
        fg.dashed = dashed;
        commands.push_back(fg);
    };

    // Dual lines between vertices
    for (size_t i = 1; i < fPolygonVertices.size(); i++) {
        Point2D p1 = {fPolygonVertices[i-1].h, fPolygonVertices[i-1].v};
        Point2D p2 = {fPolygonVertices[i].h, fPolygonVertices[i].v};
        addDualLine("_lasso_line_" + std::to_string(i), p1, p2, whiteBG, lightCyan, true);
    }

    // Rubber band from last vertex to cursor
    if (!fPolygonVertices.empty()) {
        Point2D pLast = {fPolygonVertices.back().h, fPolygonVertices.back().v};
        Point2D pCur  = {fLastCursorPos.h, fLastCursorPos.v};
        addDualLine("_lasso_rubber", pLast, pCur, rubberWhite, rubberCyan, true);

        // Closing line preview (last vertex -> first vertex)
        if (fPolygonVertices.size() >= 3) {
            Point2D pFirst = {fPolygonVertices.front().h, fPolygonVertices.front().v};
            addDualLine("_lasso_closing", pLast, pFirst, rubberWhite, rubberCyan, true);
        }
    }

    // Filled box handles at vertices (20% bigger: 6x6 instead of 5x5)
    for (size_t i = 0; i < fPolygonVertices.size(); i++) {
        DrawCommand handle;
        handle.type = DrawCommandType::Rect;
        handle.id = "_lasso_handle_" + std::to_string(i);
        handle.center = {fPolygonVertices[i].h, fPolygonVertices[i].v};
        handle.width = 6.0;
        handle.height = 6.0;
        handle.strokeColor = darkCyan;
        handle.fillColor = darkCyan;
        handle.strokeWidth = 1.0;
        handle.filled = true;
        handle.stroked = true;
        commands.push_back(handle);
    }

    UpdateDrawCommands(std::move(commands));
    InvalidateFullView();
}

/*
    PointInPolygon — ray casting algorithm.
    Returns true if pt is inside the polygon defined by the given vertices.
*/
bool IllToolPlugin::PointInPolygon(const AIRealPoint& pt,
                                    const std::vector<AIRealPoint>& polygon)
{
    bool inside = false;
    size_t n = polygon.size();
    for (size_t i = 0, j = n - 1; i < n; j = i++) {
        double xi = polygon[i].h, yi = polygon[i].v;
        double xj = polygon[j].h, yj = polygon[j].v;

        bool intersect = ((yi > pt.v) != (yj > pt.v)) &&
                          (pt.h < (xj - xi) * (pt.v - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

/*
    GetMatchingArtIsolationAware — returns matching art, scoped to the
    isolated art tree when in isolation mode.  When in our working mode
    the search root is the working group; otherwise falls through to the
    standard whole-document query.
*/
static ASErr GetMatchingArtIsolationAware(
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

/*
    ExecutePolygonSelection — select path segments whose anchor points
    fall inside the polygon lasso.
*/
void IllToolPlugin::ExecutePolygonSelection()
{
    fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: enter, polygon vertices=%zu\n",
            fPolygonVertices.size());
    if (fPolygonVertices.size() < 3) {
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: <3 vertices, returning early\n");
        return;
    }

    ASErr result = kNoErr;
    try {
        // Get all path art (isolation-aware — scoped to working group if active)
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: calling GetMatchingArtIsolationAware\n");
        result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: GetMatchingArtIsolationAware returned err=%d, numMatches=%d\n",
                (int)result, (int)numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: no path art found — aborting\n");
            return;
        }

        fprintf(stderr, "[IllTool] Testing %d paths against polygon\n", (int)numMatches);

        int selectedCount = 0;
        int skippedLocked = 0;
        int skippedEmpty = 0;
        int totalSegsTested = 0;
        int totalInsidePolygon = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            // Get segment count
            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) {
                skippedEmpty++;
                continue;
            }

            for (ai::int16 s = 0; s < segCount; s++) {
                AIPathSegment seg;
                result = sAIPath->GetPathSegments(art, s, 1, &seg);
                if (result != kNoErr) continue;

                totalSegsTested++;

                // Test if anchor point is inside the polygon
                if (PointInPolygon(seg.p, fPolygonVertices)) {
                    totalInsidePolygon++;
                    // Select this segment's anchor point
                    result = sAIPath->SetPathSegmentSelected(art, s, kSegmentPointSelected);
                    if (result == kNoErr) {
                        selectedCount++;
                    } else {
                        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: SetPathSegmentSelected FAILED for path %d seg %d, err=%d\n",
                                (int)i, (int)s, (int)result);
                    }
                }
            }
        }

        // Free the matches array (SDK allocates it; we must dispose)
        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection SUMMARY:\n");
        fprintf(stderr, "[IllTool DEBUG]   paths matched:     %d\n", (int)numMatches);
        fprintf(stderr, "[IllTool DEBUG]   skipped locked:    %d\n", skippedLocked);
        fprintf(stderr, "[IllTool DEBUG]   skipped empty:     %d\n", skippedEmpty);
        fprintf(stderr, "[IllTool DEBUG]   segments tested:   %d\n", totalSegsTested);
        fprintf(stderr, "[IllTool DEBUG]   inside polygon:    %d\n", totalInsidePolygon);
        fprintf(stderr, "[IllTool DEBUG]   selected count:    %d\n", selectedCount);
        fprintf(stderr, "[IllTool DEBUG]   fInWorkingMode:    %s\n", fInWorkingMode ? "true" : "false");

        // If we selected anything and NOT already in working mode,
        // enter working mode (duplicate, dim, isolate).
        // If already in working mode, the lasso is just selecting within
        // the isolated group — no need to re-enter.
        if (selectedCount > 0 && !fInWorkingMode) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: calling EnterWorkingMode\n");
            EnterWorkingMode();
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: EnterWorkingMode returned\n");
        } else if (selectedCount == 0) {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: nothing selected, NOT entering working mode\n");
        } else {
            fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: already in working mode, NOT re-entering\n");
        }

        // Redraw so selection is visible
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool DEBUG] ExecutePolygonSelection: RedrawDocument called, done\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] ExecutePolygonSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] ExecutePolygonSelection unknown error\n");
    }
}

/*
    InvalidateFullView — invalidate the entire document view.
*/
void IllToolPlugin::InvalidateFullView()
{
    try {
        AIRealRect viewBounds = {0, 0, 0, 0};
        ASErr result = sAIDocumentView->GetDocumentViewBounds(NULL, &viewBounds);
        if (result == kNoErr && fAnnotator) {
            fAnnotator->InvalidateRect(viewBounds);
        }
    }
    catch (...) {
        // Silently ignore — can happen during shutdown
    }
}

//========================================================================================
//  Average Selection
//========================================================================================

/*
    AverageSelection — compute the centroid of all selected anchor points
    and move them to that centroid. This is the classic Illustrator "Average"
    operation but applied to the current point selection.
*/
void IllToolPlugin::AverageSelection()
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] AverageSelection: no path art found\n");
            return;
        }

        // First pass: collect selected anchor positions and compute centroid
        double sumX = 0.0, sumY = 0.0;
        int selectedCount = 0;

        struct SelectedSeg {
            AIArtHandle art;
            ai::int16   seg;
        };
        std::vector<SelectedSeg> selectedSegs;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) continue;

            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result != kNoErr) continue;

                if (selected & kSegmentPointSelected) {
                    AIPathSegment seg;
                    result = sAIPath->GetPathSegments(art, s, 1, &seg);
                    if (result != kNoErr) continue;

                    sumX += seg.p.h;
                    sumY += seg.p.v;
                    selectedCount++;
                    selectedSegs.push_back({art, s});
                }
            }
        }

        if (selectedCount < 2) {
            fprintf(stderr, "[IllTool] AverageSelection: need 2+ selected anchors (found %d)\n",
                    selectedCount);
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            return;
        }

        double avgX = sumX / selectedCount;
        double avgY = sumY / selectedCount;
        fprintf(stderr, "[IllTool] AverageSelection: centroid (%.2f, %.2f) from %d points\n",
                avgX, avgY, selectedCount);

        // Second pass: move all selected anchors to the centroid
        for (auto& ss : selectedSegs) {
            AIPathSegment seg;
            result = sAIPath->GetPathSegments(ss.art, ss.seg, 1, &seg);
            if (result != kNoErr) continue;

            // Adjust control handles relative to the anchor movement
            AIReal dx = (AIReal)avgX - seg.p.h;
            AIReal dy = (AIReal)avgY - seg.p.v;

            seg.p.h = (AIReal)avgX;
            seg.p.v = (AIReal)avgY;
            seg.in.h  += dx;
            seg.in.v  += dy;
            seg.out.h += dx;
            seg.out.v += dy;

            result = sAIPath->SetPathSegments(ss.art, ss.seg, 1, &seg);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool] AverageSelection: SetPathSegments failed: %d\n",
                        (int)result);
            }
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        fprintf(stderr, "[IllTool] AverageSelection: moved %d anchors to centroid\n", selectedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] AverageSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] AverageSelection unknown error\n");
    }
}


//========================================================================================
//  Shape Classification — heuristic shape detection (ported from shapes.jsx)
//========================================================================================

// Helper: perpendicular distance from point P to line segment AB
static double PointToSegmentDist(AIRealPoint p, AIRealPoint a, AIRealPoint b)
{
    double abx = b.h - a.h, aby = b.v - a.v;
    double apx = p.h - a.h, apy = p.v - a.v;
    double abLenSq = abx * abx + aby * aby;
    if (abLenSq < 1e-12) return sqrt(apx * apx + apy * apy);
    double t = (apx * abx + apy * aby) / abLenSq;
    if (t < 0) t = 0; if (t > 1) t = 1;
    double dx = p.h - (a.h + abx * t);
    double dy = p.v - (a.v + aby * t);
    return sqrt(dx * dx + dy * dy);
}

static double Dist2D(AIRealPoint a, AIRealPoint b) {
    double dx = b.h - a.h, dy = b.v - a.v;
    return sqrt(dx * dx + dy * dy);
}

static bool Circumcircle(AIRealPoint p1, AIRealPoint p2, AIRealPoint p3,
                          double& cx, double& cy, double& radius) {
    double ax = p1.h, ay = p1.v, bx = p2.h, by = p2.v, ccx = p3.h, ccy = p3.v;
    double D = 2.0 * (ax*(by-ccy) + bx*(ccy-ay) + ccx*(ay-by));
    if (fabs(D) < 1e-10) return false;
    cx = ((ax*ax+ay*ay)*(by-ccy) + (bx*bx+by*by)*(ccy-ay) + (ccx*ccx+ccy*ccy)*(ay-by)) / D;
    cy = ((ax*ax+ay*ay)*(ccx-bx) + (bx*bx+by*by)*(ax-ccx) + (ccx*ccx+ccy*ccy)*(bx-ax)) / D;
    double ddx = cx - p1.h, ddy = cy - p1.v;
    radius = sqrt(ddx*ddx + ddy*ddy);
    return true;
}

static const char* kShapeNames[] = {
    "LINE", "ARC", "L-SHAPE", "RECT", "S-CURVE", "ELLIPSE", "FREEFORM"
};

// Helper: find first path with segment-level or art-level selection
static AIArtHandle FindSelectedPath(AIArtHandle** matches, ai::int32 numMatches)
{
    AIArtHandle targetPath = nullptr;
    for (ai::int32 i = 0; i < numMatches && !targetPath; i++) {
        AIArtHandle art = (*matches)[i];
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;
        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(art, &segCount);
        if (segCount < 2) continue;
        for (ai::int16 s = 0; s < segCount; s++) {
            ai::int16 sel = kSegmentNotSelected;
            sAIPath->GetPathSegmentSelected(art, s, &sel);
            if (sel & kSegmentPointSelected) { targetPath = art; break; }
        }
        if (!targetPath) {
            ai::int32 selAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &selAttrs);
            if (selAttrs & kArtSelected) targetPath = art;
        }
    }
    return targetPath;
}

void IllToolPlugin::ClassifySelection()
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fLastDetectedShape = "---"; return;
        }
        AIArtHandle targetPath = FindSelectedPath(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (!targetPath) { fLastDetectedShape = "---"; return; }

        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(targetPath, &segCount);
        if (segCount < 2) { fLastDetectedShape = "FREEFORM"; return; }

        std::vector<AIRealPoint> pts(segCount);
        { std::vector<AIPathSegment> segs(segCount);
          sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
          for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p; }

        AIBoolean isClosed = false;
        sAIPath->GetPathClosed(targetPath, &isClosed);

        int n = (int)pts.size();
        AIRealPoint first = pts[0], last = pts[n-1];
        double span = Dist2D(first, last);

        // --- Test Line ---
        double lineDev = 0;
        for (int i = 1; i < n-1; i++) lineDev += PointToSegmentDist(pts[i], first, last);
        double avgLineDev = (n > 2) ? lineDev / (n-2) : 0;
        double lineConf = fmax(0, 1.0 - ((span > 1e-6) ? avgLineDev/span : 1.0) * 20.0);

        // --- Test Arc ---
        double arcConf = 0;
        if (n >= 3) {
            double ccxv, ccyv, r;
            if (Circumcircle(first, pts[n/2], last, ccxv, ccyv, r) && r > 1e-6) {
                double td = 0;
                for (int i = 0; i < n; i++)
                    td += fabs(sqrt((pts[i].h-ccxv)*(pts[i].h-ccxv)+(pts[i].v-ccyv)*(pts[i].v-ccyv)) - r);
                double sw = fabs(atan2(first.v-ccyv,first.h-ccxv) - atan2(last.v-ccyv,last.h-ccxv));
                if (sw > M_PI) sw = 2*M_PI - sw;
                arcConf = fmax(0, (1.0 - (td/n)/r*10.0) * (sw < 5.5 ? 1.0 : 0.3));
            }
        }

        // --- Test L-Shape ---
        double lConf = 0;
        if (n >= 3 && span > 1e-6) {
            double maxD = 0; int ci = 0;
            for (int i = 1; i < n-1; i++) { double d = PointToSegmentDist(pts[i],first,last); if (d>maxD){maxD=d;ci=i;} }
            AIRealPoint corner = pts[ci];
            double d1 = 0, d2 = 0;
            for (int a = 1; a < ci; a++) d1 += PointToSegmentDist(pts[a], first, corner);
            for (int b = ci+1; b < n-1; b++) d2 += PointToSegmentDist(pts[b], corner, last);
            double rd = ((d1+d2)/fmax(1,n-3)) / span;
            double v1x=first.h-corner.h, v1y=first.v-corner.v, v2x=last.h-corner.h, v2y=last.v-corner.v;
            double ll1=sqrt(v1x*v1x+v1y*v1y), ll2=sqrt(v2x*v2x+v2y*v2y);
            double dot = (ll1>1e-6&&ll2>1e-6) ? (v1x*v2x+v1y*v2y)/(ll1*ll2) : 0;
            lConf = fmax(0, (1.0-rd*15.0) * fmax(0,1.0-fabs(dot)));
        }

        // --- Test Rectangle ---
        double rectConf = 0;
        if (n >= 4 && isClosed && (n == 4 || n == 5)) {
            int ra = 0;
            for (int i = 0; i < n; i++) {
                int prv = (i==0)?n-1:i-1, nxt = (i+1)%n;
                double aax=pts[prv].h-pts[i].h, aay=pts[prv].v-pts[i].v;
                double bbx=pts[nxt].h-pts[i].h, bby=pts[nxt].v-pts[i].v;
                double la=sqrt(aax*aax+aay*aay), lb=sqrt(bbx*bbx+bby*bby);
                if (la>1e-6 && lb>1e-6 && fabs((aax*bbx+aay*bby)/(la*lb)) < 0.3) ra++;
            }
            rectConf = (double)ra / fmax(1,n) * 0.9;
        }

        // --- Test S-Curve ---
        double sConf = 0;
        if (n >= 4) {
            int sc = 0, ps = 0;
            for (int i = 1; i < n-1; i++) {
                double cp = (pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v) - (pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
                int sg = (cp>0)?1:((cp<0)?-1:0);
                if (sg && ps && sg!=ps) sc++;
                if (sg) ps = sg;
            }
            sConf = 0.6 * ((sc>=1&&sc<=3)?1.0:0.3) * ((lineConf<0.7)?1.0:0.3);
        }

        // --- Test Ellipse ---
        double ellConf = 0;
        if (n >= 5 && isClosed) {
            double ecx=0,ecy=0;
            for (int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
            double ar=0;
            for (int i=0;i<n;i++) ar += sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy));
            ar /= n; if (ar<1) ar=1;
            double td=0;
            for (int i=0;i<n;i++) td += fabs(sqrt((pts[i].h-ecx)*(pts[i].h-ecx)+(pts[i].v-ecy)*(pts[i].v-ecy))-ar);
            ellConf = fmax(0, (1.0-(td/n)/ar*5.0) * (isClosed ? 1.0 : 0.3));
        }

        struct { double conf; BridgeShapeType type; } cands[] = {
            {lineConf, BridgeShapeType::Line}, {arcConf, BridgeShapeType::Arc},
            {lConf, BridgeShapeType::LShape}, {rectConf, BridgeShapeType::Rect},
            {sConf, BridgeShapeType::SCurve}, {ellConf, BridgeShapeType::Ellipse},
        };
        BridgeShapeType bestType = BridgeShapeType::Freeform;
        double bestConf = 0.1;
        for (auto& c : cands) { if (c.conf > bestConf) { bestConf = c.conf; bestType = c.type; } }

        fLastDetectedShape = kShapeNames[(int)bestType];
        fprintf(stderr, "[IllTool Timer] ClassifySelection: detected=%s (conf=%.2f) "
                "[line=%.2f arc=%.2f L=%.2f rect=%.2f S=%.2f ell=%.2f]\n",
                fLastDetectedShape, bestConf, lineConf, arcConf, lConf, rectConf, sConf, ellConf);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] ClassifySelection error: %d\n", (int)ex); fLastDetectedShape = "ERROR"; }
    catch (...) { fprintf(stderr, "[IllTool Timer] ClassifySelection unknown error\n"); fLastDetectedShape = "ERROR"; }
}

//========================================================================================
//  Shape Reclassification — force-fit selection to a specific shape
//========================================================================================

void IllToolPlugin::ReclassifyAs(BridgeShapeType shapeType)
{
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: no path art\n"); return; }
        AIArtHandle targetPath = FindSelectedPath(matches, numMatches);
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        if (!targetPath) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: no selected path\n"); return; }

        ai::int16 segCount = 0;
        sAIPath->GetPathSegmentCount(targetPath, &segCount);
        if (segCount < 2) return;

        std::vector<AIPathSegment> segs(segCount);
        sAIPath->GetPathSegments(targetPath, 0, segCount, segs.data());
        std::vector<AIRealPoint> pts(segCount);
        for (ai::int16 s = 0; s < segCount; s++) pts[s] = segs[s].p;
        AIRealPoint first = pts[0], last = pts[segCount-1];

        std::vector<AIPathSegment> newSegs;

        switch (shapeType) {
            case BridgeShapeType::Line: {
                AIPathSegment s1={}, s2={};
                s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                s2.p=last;  s2.in=last;  s2.out=last;  s2.corner=true;
                newSegs.push_back(s1); newSegs.push_back(s2);
                break;
            }
            case BridgeShapeType::Arc: {
                int n=(int)pts.size();
                double ccxv,ccyv,r;
                if (!Circumcircle(first, pts[n/2], last, ccxv, ccyv, r) || r<1e-6) {
                    AIPathSegment s1={}, s2={};
                    s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                    s2.p=last;  s2.in=last;  s2.out=last;  s2.corner=true;
                    newSegs.push_back(s1); newSegs.push_back(s2);
                } else {
                    double a1=atan2(first.v-ccyv,first.h-ccxv), a3=atan2(last.v-ccyv,last.h-ccxv);
                    double sweep=a3-a1;
                    while(sweep>M_PI)sweep-=2*M_PI; while(sweep<-M_PI)sweep+=2*M_PI;
                    double am=a1+sweep*0.5;
                    AIRealPoint ap[3]={
                        {(AIReal)(ccxv+r*cos(a1)),(AIReal)(ccyv+r*sin(a1))},
                        {(AIReal)(ccxv+r*cos(am)),(AIReal)(ccyv+r*sin(am))},
                        {(AIReal)(ccxv+r*cos(a1+sweep)),(AIReal)(ccyv+r*sin(a1+sweep))}};
                    double sa=fabs(sweep/2), hLen=(4.0/3.0)*tan(sa/4.0)*r;
                    double ss=(sweep>=0)?1.0:-1.0;
                    double angs[3]={a1,am,a1+sweep};
                    for(int i=0;i<3;i++){
                        double th=angs[i], tx=-sin(th)*ss, ty=cos(th)*ss;
                        AIPathSegment seg={}; seg.p=ap[i]; seg.corner=false;
                        if(i==0){seg.in=ap[i]; seg.out.h=(AIReal)(ap[i].h+tx*hLen); seg.out.v=(AIReal)(ap[i].v+ty*hLen);}
                        else if(i==2){seg.in.h=(AIReal)(ap[i].h-tx*hLen); seg.in.v=(AIReal)(ap[i].v-ty*hLen); seg.out=ap[i];}
                        else{seg.in.h=(AIReal)(ap[i].h-tx*hLen); seg.in.v=(AIReal)(ap[i].v-ty*hLen);
                             seg.out.h=(AIReal)(ap[i].h+tx*hLen); seg.out.v=(AIReal)(ap[i].v+ty*hLen);}
                        newSegs.push_back(seg);
                    }
                }
                break;
            }
            case BridgeShapeType::LShape: {
                int ci=0; double md=0; int n=(int)pts.size();
                for(int i=1;i<n-1;i++){double d=PointToSegmentDist(pts[i],first,last);if(d>md){md=d;ci=i;}}
                AIRealPoint corner=pts[ci];
                AIPathSegment s1={},s2={},s3={};
                s1.p=first; s1.in=first; s1.out=first; s1.corner=true;
                s2.p=corner; s2.in=corner; s2.out=corner; s2.corner=true;
                s3.p=last; s3.in=last; s3.out=last; s3.corner=true;
                newSegs.push_back(s1); newSegs.push_back(s2); newSegs.push_back(s3);
                break;
            }
            case BridgeShapeType::Rect: {
                double mnH=pts[0].h, mxH=pts[0].h, mnV=pts[0].v, mxV=pts[0].v;
                for(int i=1;i<(int)pts.size();i++){
                    if(pts[i].h<mnH)mnH=pts[i].h; if(pts[i].h>mxH)mxH=pts[i].h;
                    if(pts[i].v<mnV)mnV=pts[i].v; if(pts[i].v>mxV)mxV=pts[i].v;
                }
                AIRealPoint co[4]={{(AIReal)mnH,(AIReal)mnV},{(AIReal)mxH,(AIReal)mnV},
                                   {(AIReal)mxH,(AIReal)mxV},{(AIReal)mnH,(AIReal)mxV}};
                for(int i=0;i<4;i++){AIPathSegment sg={}; sg.p=co[i]; sg.in=co[i]; sg.out=co[i]; sg.corner=true; newSegs.push_back(sg);}
                break;
            }
            case BridgeShapeType::SCurve: {
                int n=(int)pts.size(), ii=n/2, ps=0;
                for(int i=1;i<n-1;i++){
                    double cp=(pts[i].h-pts[i-1].h)*(pts[i+1].v-pts[i].v)-(pts[i].v-pts[i-1].v)*(pts[i+1].h-pts[i].h);
                    int sg=(cp>0)?1:((cp<0)?-1:0);
                    if(sg&&ps&&sg!=ps){ii=i;break;} if(sg)ps=sg;
                }
                AIRealPoint ip=pts[ii]; double tn=1.0/6.0;
                auto ms=[](AIRealPoint p,AIRealPoint ih,AIRealPoint oh){AIPathSegment sg={}; sg.p=p; sg.in=ih; sg.out=oh; sg.corner=false; return sg;};
                double t0x=(ip.h-first.h)*tn, t0y=(ip.v-first.v)*tn;
                newSegs.push_back(ms(first, first, {(AIReal)(first.h+t0x),(AIReal)(first.v+t0y)}));
                double t1x=(last.h-first.h)*tn, t1y=(last.v-first.v)*tn;
                newSegs.push_back(ms(ip, {(AIReal)(ip.h-t1x),(AIReal)(ip.v-t1y)}, {(AIReal)(ip.h+t1x),(AIReal)(ip.v+t1y)}));
                double t2x=(last.h-ip.h)*tn, t2y=(last.v-ip.v)*tn;
                newSegs.push_back(ms(last, {(AIReal)(last.h-t2x),(AIReal)(last.v-t2y)}, last));
                break;
            }
            case BridgeShapeType::Ellipse: {
                int n=(int)pts.size(); double ecx=0,ecy=0;
                for(int i=0;i<n;i++){ecx+=pts[i].h;ecy+=pts[i].v;} ecx/=n; ecy/=n;
                double cxx=0,cxy=0,cyy=0;
                for(int i=0;i<n;i++){double dx=pts[i].h-ecx,dy=pts[i].v-ecy; cxx+=dx*dx; cxy+=dx*dy; cyy+=dy*dy;}
                cxx/=n; cxy/=n; cyy/=n;
                double tr=cxx+cyy, dt=cxx*cyy-cxy*cxy, disc=fmax(0,tr*tr/4-dt);
                double ev1=tr/2+sqrt(disc), ev2=tr/2-sqrt(disc);
                double ssa=sqrt(fmax(0,2*ev1)), ssb=sqrt(fmax(0,2*ev2));
                if(ssa<1)ssa=1; if(ssb<1)ssb=1;
                double ang = fabs(cxy)>1e-10 ? atan2(ev1-cxx,cxy) : (cxx>=cyy?0:M_PI/2);
                double ca=cos(ang), sna=sin(ang), kp=(4.0/3.0)*(sqrt(2.0)-1.0);
                double cAng[4]={0,M_PI/2,M_PI,3*M_PI/2};
                for(int j=0;j<4;j++){
                    double t=cAng[j], exx=ssa*cos(t), eyy=ssb*sin(t);
                    double px=exx*ca-eyy*sna+ecx, py=exx*sna+eyy*ca+ecy;
                    double ltx=-ssa*sin(t), lty=ssb*cos(t);
                    double wtx=ltx*ca-lty*sna, wty=ltx*sna+lty*ca;
                    double tl=sqrt(wtx*wtx+wty*wty); if(tl>1e-10){wtx/=tl;wty/=tl;}
                    double hl=(j%2==0)?kp*ssb:kp*ssa;
                    AIPathSegment sg={}; sg.p.h=(AIReal)px; sg.p.v=(AIReal)py;
                    sg.in.h=(AIReal)(px-wtx*hl); sg.in.v=(AIReal)(py-wty*hl);
                    sg.out.h=(AIReal)(px+wtx*hl); sg.out.v=(AIReal)(py+wty*hl);
                    sg.corner=false; newSegs.push_back(sg);
                }
                break;
            }
            case BridgeShapeType::Freeform: default:
                fLastDetectedShape = "FREEFORM";
                fprintf(stderr, "[IllTool Timer] ReclassifyAs: freeform — no modification\n");
                return;
        }

        if (!newSegs.empty()) {
            ai::int16 nc = (ai::int16)newSegs.size();
            result = sAIPath->SetPathSegmentCount(targetPath, nc);
            if (result != kNoErr) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: SetPathSegmentCount failed: %d\n", (int)result); return; }
            result = sAIPath->SetPathSegments(targetPath, 0, nc, newSegs.data());
            if (result != kNoErr) { fprintf(stderr, "[IllTool Timer] ReclassifyAs: SetPathSegments failed: %d\n", (int)result); return; }
            if (shapeType == BridgeShapeType::Rect || shapeType == BridgeShapeType::Ellipse)
                sAIPath->SetPathClosed(targetPath, true);
            else if (shapeType != BridgeShapeType::Freeform)
                sAIPath->SetPathClosed(targetPath, false);
            fLastDetectedShape = kShapeNames[(int)shapeType];
            fprintf(stderr, "[IllTool Timer] ReclassifyAs: wrote %d segments as %s\n", (int)nc, fLastDetectedShape);
            sAIDocument->RedrawDocument();
        }
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] ReclassifyAs error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool Timer] ReclassifyAs unknown error\n"); }
}

//========================================================================================
//  Simplification — Douglas-Peucker on selected paths
//========================================================================================

void IllToolPlugin::SimplifySelection(double tolerance)
{
    if (tolerance < 0.01) {
        fprintf(stderr, "[IllTool Timer] SimplifySelection: tolerance too small (%.2f), skipping\n", tolerance);
        return;
    }
    try {
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool Timer] SimplifySelection: no path art\n"); return; }

        int totalSimplified = 0, totalBefore = 0, totalAfter = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden | kArtSelected, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            bool hasSel = false;
            if (attrs & kArtSelected) { hasSel = true; }
            else {
                ai::int16 sc = 0; sAIPath->GetPathSegmentCount(art, &sc);
                for (ai::int16 s = 0; s < sc; s++) {
                    ai::int16 sel = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &sel);
                    if (sel & kSegmentPointSelected) { hasSel = true; break; }
                }
            }
            if (!hasSel) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 3) continue;

            std::vector<AIPathSegment> segs(segCount);
            result = sAIPath->GetPathSegments(art, 0, segCount, segs.data());
            if (result != kNoErr) continue;
            totalBefore += segCount;

            // Douglas-Peucker iterative
            std::vector<bool> keep(segCount, false);
            keep[0] = true; keep[segCount-1] = true;
            std::vector<std::pair<int,int>> stk;
            stk.push_back({0, segCount-1});
            while (!stk.empty()) {
                auto rng = stk.back(); stk.pop_back();
                if (rng.second - rng.first < 2) continue;
                double md = 0; int mi = rng.first;
                for (int j = rng.first+1; j < rng.second; j++) {
                    double d = PointToSegmentDist(segs[j].p, segs[rng.first].p, segs[rng.second].p);
                    if (d > md) { md = d; mi = j; }
                }
                if (md > tolerance) { keep[mi]=true; stk.push_back({rng.first,mi}); stk.push_back({mi,rng.second}); }
            }

            std::vector<AIPathSegment> ns;
            for (int j=0; j<segCount; j++) if (keep[j]) ns.push_back(segs[j]);
            ai::int16 nc = (ai::int16)ns.size();
            if (nc >= 2 && nc < segCount) {
                sAIPath->SetPathSegmentCount(art, nc);
                sAIPath->SetPathSegments(art, 0, nc, ns.data());
                totalSimplified++; totalAfter += nc;
                fprintf(stderr, "[IllTool Timer] SimplifySelection: path %d: %d -> %d points\n", (int)i, (int)segCount, (int)nc);
            } else { totalAfter += segCount; }
        }
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[IllTool Timer] SimplifySelection: %d paths, %d -> %d pts (tol=%.1f)\n",
                totalSimplified, totalBefore, totalAfter, tolerance);
        if (totalSimplified > 0) sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool Timer] SimplifySelection error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool Timer] SimplifySelection unknown error\n"); }
}

//========================================================================================
//  Enter isolation mode for the parent group(s) of selected paths
//========================================================================================

void IllToolPlugin::EnterIsolationForSelection()
{
    if (!sAIIsolationMode) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection: AIIsolationModeSuite not available\n");
        return;
    }

    // Already in isolation mode? Don't double-enter.
    if (sAIIsolationMode->IsInIsolationMode()) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection: already in isolation mode\n");
        return;
    }

    try {
        // Find the first selected path and get its parent group
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] EnterIsolationForSelection: no paths found\n");
            return;
        }

        // Find the first path that has selected segments
        AIArtHandle targetGroup = nullptr;
        for (ai::int32 i = 0; i < numMatches && !targetGroup; i++) {
            AIArtHandle art = (*matches)[i];

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) continue;

            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    // Found a selected segment — get its parent
                    AIArtHandle parent = nullptr;
                    result = sAIArt->GetArtParent(art, &parent);
                    if (result == kNoErr && parent) {
                        // Check if the parent is a group (not a layer)
                        short artType = kUnknownArt;
                        sAIArt->GetArtType(parent, &artType);
                        if (artType == kGroupArt) {
                            targetGroup = parent;
                        }
                    }
                    break;
                }
            }
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        if (targetGroup) {
            // Verify isolation is legal for this art
            if (sAIIsolationMode->CanIsolateArt(targetGroup)) {
                result = sAIIsolationMode->EnterIsolationMode(targetGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[IllTool] Entered isolation mode for parent group\n");
                } else {
                    fprintf(stderr, "[IllTool] EnterIsolationMode failed: %d\n", (int)result);
                }
            } else {
                fprintf(stderr, "[IllTool] Cannot isolate target group (CanIsolateArt returned false)\n");
            }
        } else {
            fprintf(stderr, "[IllTool] EnterIsolationForSelection: no isolatable parent group found\n");
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] EnterIsolationForSelection unknown error\n");
    }
}

//========================================================================================
//  C-callable wrapper for panel buttons
//========================================================================================

void PluginAverageSelection()
{
    if (gPlugin) {
        gPlugin->AverageSelection();
    }
}

void PluginApplyWorkingMode(bool deleteOriginals)
{
    if (gPlugin) {
        gPlugin->ApplyWorkingMode(deleteOriginals);
    }
}

void PluginCancelWorkingMode()
{
    if (gPlugin) {
        gPlugin->CancelWorkingMode();
    }
}

//========================================================================================
//  C-callable: count selected anchor points (for panel polling)
//========================================================================================

int PluginGetSelectedAnchorCount()
{
    // Return the cached count from the selection-changed notifier.
    // SDK calls (GetMatchingArt) don't work from NSTimer callbacks —
    // they return DOC? error because the callback runs outside the SDK
    // message dispatch context. The notifier updates fLastKnownSelectionCount
    // during the SDK's own message dispatch, where the calls work.
    if (!gPlugin) return 0;
    return gPlugin->fLastKnownSelectionCount;

    // --- OLD POLLING CODE (doesn't work from timer context) ---
    // Kept for reference, dead code below
    static int pollCallCount = 0;
    pollCallCount++;
    bool verboseThisCall = (pollCallCount % 10 == 1);

    if (!gPlugin) {
        return 0;
    }
    if (!sAIMatchingArt || !sAIPath || !sAIArt || !sAIMdMemory) {
        if (verboseThisCall) fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: suite(s) missing — sAIMatchingArt=%p sAIPath=%p sAIArt=%p sAIMdMemory=%p\n",
                (void*)sAIMatchingArt, (void*)sAIPath, (void*)sAIArt, (void*)sAIMdMemory);
        return 0;
    }

    int count = 0;
    try {
        bool inIso = sAIIsolationMode && sAIIsolationMode->IsInIsolationMode();
        bool inWorking = gPlugin->IsInWorkingMode();
        if (verboseThisCall) {
            fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: poll#%d, inIsolationMode=%s, inWorkingMode=%s, workingGroup=%p\n",
                    pollCallCount, inIso ? "true" : "false", inWorking ? "true" : "false",
                    (void*)gPlugin->GetWorkingGroup());
        }

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            if (verboseThisCall) fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: GetMatchingArtIsolationAware returned err=%d, numMatches=%d — returning 0\n",
                    (int)result, (int)numMatches);
            return 0;
        }

        if (verboseThisCall) {
            fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: scanning %d paths\n", (int)numMatches);
        }

        int lockedSkipped = 0;
        int emptySkipped = 0;
        int pathsWithSelection = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            // Skip locked / hidden art
            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                lockedSkipped++;
                continue;
            }

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) {
                emptySkipped++;
                continue;
            }

            bool thisPathHasSelection = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    count++;
                    thisPathHasSelection = true;
                }
            }
            if (thisPathHasSelection) pathsWithSelection++;
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        if (verboseThisCall || count > 0) {
            fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: result=%d (paths=%d, locked=%d, empty=%d, withSel=%d)\n",
                    count, (int)numMatches, lockedSkipped, emptySkipped, pathsWithSelection);
        }
    }
    catch (...) {
        fprintf(stderr, "[IllTool DEBUG] PluginGetSelectedAnchorCount: EXCEPTION caught, returning %d\n", count);
    }
    return count;
}

//========================================================================================
//  Working Mode — duplicate, dim originals, isolate working group
//========================================================================================

/*
    FindOrCreateWorkingLayer — find a layer titled "Working", or create one at the top.
    Returns the AIArtHandle for the layer group (the container for art on that layer).
*/
static AIArtHandle FindOrCreateWorkingLayer()
{
    if (!sAILayer || !sAIArt) return nullptr;

    ASErr result = kNoErr;
    AILayerHandle layer = nullptr;

    // Try to find existing "Working" layer
    ai::UnicodeString workingTitle("Working");
    result = sAILayer->GetLayerByTitle(&layer, workingTitle);

    if (result != kNoErr || layer == nullptr) {
        // Create a new layer at the top of the stack
        result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
        if (result != kNoErr || layer == nullptr) {
            fprintf(stderr, "[IllTool] Failed to create Working layer: %d\n", (int)result);
            return nullptr;
        }
        result = sAILayer->SetLayerTitle(layer, workingTitle);
        if (result != kNoErr) {
            fprintf(stderr, "[IllTool] Failed to set Working layer title: %d\n", (int)result);
        }
        fprintf(stderr, "[IllTool] Created 'Working' layer\n");
    } else {
        fprintf(stderr, "[IllTool] Found existing 'Working' layer\n");
    }

    // Get the layer's art group (container for art on that layer)
    AIArtHandle layerGroup = nullptr;
    result = sAIArt->GetFirstArtOfLayer(layer, &layerGroup);
    if (result != kNoErr || layerGroup == nullptr) {
        fprintf(stderr, "[IllTool] Failed to get Working layer art group: %d\n", (int)result);
        return nullptr;
    }

    return layerGroup;
}

void IllToolPlugin::EnterWorkingMode()
{
    if (fInWorkingMode) {
        fprintf(stderr, "[IllTool] EnterWorkingMode: already in working mode — no-op\n");
        return;
    }

    if (!sAIBlendStyle) {
        fprintf(stderr, "[IllTool] EnterWorkingMode: AIBlendStyleSuite not available\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: begin\n");

        // Step 1: Collect all paths that have any selected segments
        // NOTE: Using whole-document GetMatchingArt here (NOT isolation-aware)
        // because we're collecting originals BEFORE entering isolation mode
        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: calling GetMatchingArt (whole doc)\n");
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: GetMatchingArt returned err=%d, numMatches=%d\n",
                (int)result, (int)numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: no path art found — aborting\n");
            return;
        }

        // Find paths with selected segments
        std::vector<AIArtHandle> selectedPaths;
        int totalChecked = 0;
        int lockedHiddenSkipped = 0;
        int emptySkipped = 0;
        int noSelectedSegs = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            totalChecked++;

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            result = sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (result != kNoErr) continue;
            if (attrs & (kArtLocked | kArtHidden)) {
                lockedHiddenSkipped++;
                continue;
            }

            ai::int16 segCount = 0;
            result = sAIPath->GetPathSegmentCount(art, &segCount);
            if (result != kNoErr || segCount == 0) {
                emptySkipped++;
                continue;
            }

            bool hasSelected = false;
            int selectedInThisPath = 0;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 selected = kSegmentNotSelected;
                result = sAIPath->GetPathSegmentSelected(art, s, &selected);
                if (result == kNoErr && (selected & kSegmentPointSelected)) {
                    hasSelected = true;
                    selectedInThisPath++;
                }
            }

            if (hasSelected) {
                fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: path[%d]=%p has %d/%d selected segs\n",
                        (int)i, (void*)art, selectedInThisPath, (int)segCount);
                selectedPaths.push_back(art);
            } else {
                noSelectedSegs++;
            }
        }

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: scan summary — checked=%d, locked/hidden=%d, empty=%d, no-sel=%d, WITH-sel=%zu\n",
                totalChecked, lockedHiddenSkipped, emptySkipped, noSelectedSegs, selectedPaths.size());

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }

        if (selectedPaths.empty()) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: no paths with selected segments — aborting\n");
            return;
        }

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: %zu paths with selected segments\n",
                selectedPaths.size());

        // Step 2: Find or create the "Working" layer
        AIArtHandle layerGroup = FindOrCreateWorkingLayer();
        if (!layerGroup) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: could not get Working layer group — aborting\n");
            return;
        }
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: layerGroup=%p\n", (void*)layerGroup);

        // Step 3: Create a group inside the Working layer to hold duplicates
        AIArtHandle workGroup = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &workGroup);
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: NewArt(group) err=%d, workGroup=%p\n",
                (int)result, (void*)workGroup);
        if (result != kNoErr || !workGroup) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: failed to create working group — aborting\n");
            return;
        }

        // Step 4: For each selected path, store original state, duplicate, dim, lock
        fOriginalPaths.clear();
        int dupeIndex = 0;
        for (AIArtHandle art : selectedPaths) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: processing path %d/%zu (art=%p)\n",
                    dupeIndex, selectedPaths.size(), (void*)art);

            // Store the original's current opacity
            AIReal prevOpacity = sAIBlendStyle->GetOpacity(art);
            fOriginalPaths.push_back({art, prevOpacity});
            fprintf(stderr, "[IllTool DEBUG]   prevOpacity=%.2f\n", (double)prevOpacity);

            // Duplicate the path into the working group
            AIArtHandle dupe = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, workGroup, &dupe);
            fprintf(stderr, "[IllTool DEBUG]   DuplicateArt: err=%d, dupe=%p\n",
                    (int)result, (void*)dupe);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   DuplicateArt FAILED — skipping this path\n");
                continue;
            }

            // Copy selection state from original to duplicate
            {
                ai::int16 origSegCount = 0;
                sAIPath->GetPathSegmentCount(art, &origSegCount);
                ai::int16 dupeSegCount = 0;
                sAIPath->GetPathSegmentCount(dupe, &dupeSegCount);
                fprintf(stderr, "[IllTool DEBUG]   origSegCount=%d, dupeSegCount=%d\n",
                        (int)origSegCount, (int)dupeSegCount);
                if (origSegCount != dupeSegCount) {
                    fprintf(stderr, "[IllTool DEBUG]   WARNING: segment count MISMATCH after DuplicateArt!\n");
                }
                ai::int16 copyCount = std::min(origSegCount, dupeSegCount);
                int copiedSelections = 0;
                for (ai::int16 s = 0; s < copyCount; s++) {
                    ai::int16 selState = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &selState);
                    if (selState != kSegmentNotSelected) {
                        ASErr selErr = sAIPath->SetPathSegmentSelected(dupe, s, selState);
                        if (selErr == kNoErr) {
                            copiedSelections++;
                        } else {
                            fprintf(stderr, "[IllTool DEBUG]   SetPathSegmentSelected(dupe, %d) FAILED: err=%d\n",
                                    (int)s, (int)selErr);
                        }
                    }
                }
                fprintf(stderr, "[IllTool DEBUG]   copied %d segment selections to dupe\n", copiedSelections);
            }

            // Mark the duplicate as selected in the document selection model
            // (segment-level selection alone is not enough for queries that
            //  check art-level selection attributes)
            result = sAIArt->SetArtUserAttr(dupe, kArtSelected, kArtSelected);
            fprintf(stderr, "[IllTool DEBUG]   SetArtUserAttr(kArtSelected) on dupe: err=%d\n", (int)result);

            // Dim the original to 30% opacity
            result = sAIBlendStyle->SetOpacity(art, 0.30);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   SetOpacity(0.30) on original FAILED: err=%d\n", (int)result);
            } else {
                fprintf(stderr, "[IllTool DEBUG]   SetOpacity(0.30) on original: OK\n");
            }

            // Lock the original so it can't be accidentally selected
            result = sAIArt->SetArtUserAttr(art, kArtLocked, kArtLocked);
            if (result != kNoErr) {
                fprintf(stderr, "[IllTool DEBUG]   SetArtUserAttr(kArtLocked) on original FAILED: err=%d\n", (int)result);
            } else {
                fprintf(stderr, "[IllTool DEBUG]   locked original: OK\n");
            }

            dupeIndex++;
        }

        fWorkingGroup = workGroup;
        fInWorkingMode = true;

        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: %zu originals dimmed, working group=%p, fInWorkingMode=true\n",
                fOriginalPaths.size(), (void*)fWorkingGroup);

        // Step 5: Enter isolation mode on the working group
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: checking isolation mode — sAIIsolationMode=%p\n",
                (void*)sAIIsolationMode);
        if (sAIIsolationMode && !sAIIsolationMode->IsInIsolationMode()) {
            bool canIsolate = sAIIsolationMode->CanIsolateArt(workGroup);
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: CanIsolateArt(workGroup)=%s\n",
                    canIsolate ? "true" : "false");
            if (canIsolate) {
                result = sAIIsolationMode->EnterIsolationMode(workGroup, false);
                if (result == kNoErr) {
                    fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: entered isolation on working group — SUCCESS\n");
                } else {
                    fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: EnterIsolationMode FAILED: err=%d\n",
                            (int)result);
                }
            } else {
                fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: cannot isolate working group\n");
            }
        } else if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: already in isolation mode — skipping\n");
        } else {
            fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: sAIIsolationMode is NULL — cannot isolate\n");
        }

        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool DEBUG] EnterWorkingMode: complete\n");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] EnterWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] EnterWorkingMode unknown error\n");
    }
}

void IllToolPlugin::ApplyWorkingMode(bool deleteOriginals)
{
    if (!fInWorkingMode) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode: not in working mode — no-op\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool] ApplyWorkingMode: begin (deleteOriginals=%s)\n",
                deleteOriginals ? "true" : "false");

        // Step 1: Exit isolation mode
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            ASErr result = sAIIsolationMode->ExitIsolationMode();
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] ApplyWorkingMode: exited isolation mode\n");
            } else {
                fprintf(stderr, "[IllTool] ApplyWorkingMode: ExitIsolationMode failed: %d\n",
                        (int)result);
            }
        }

        // Step 2: Handle originals
        for (auto& rec : fOriginalPaths) {
            if (deleteOriginals) {
                // Unlock first (DisposeArt may fail on locked art)
                sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
                ASErr result = sAIArt->DisposeArt(rec.art);
                if (result != kNoErr) {
                    fprintf(stderr, "[IllTool] ApplyWorkingMode: DisposeArt failed: %d\n",
                            (int)result);
                }
            } else {
                // Restore opacity and unlock
                if (sAIBlendStyle) {
                    sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
                }
                sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
            }
        }

        int origCount = (int)fOriginalPaths.size();

        // Step 3: Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fInWorkingMode = false;

        // Step 4: Redraw
        sAIDocument->RedrawDocument();

        fprintf(stderr, "[IllTool] ApplyWorkingMode: complete (%d originals %s)\n",
                origCount, deleteOriginals ? "deleted" : "restored");
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] ApplyWorkingMode unknown error\n");
    }
}

void IllToolPlugin::CancelWorkingMode()
{
    if (!fInWorkingMode) {
        fprintf(stderr, "[IllTool] CancelWorkingMode: not in working mode — no-op\n");
        return;
    }

    try {
        fprintf(stderr, "[IllTool] CancelWorkingMode: begin\n");

        // Step 1: Exit isolation mode
        if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
            ASErr result = sAIIsolationMode->ExitIsolationMode();
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] CancelWorkingMode: exited isolation mode\n");
            } else {
                fprintf(stderr, "[IllTool] CancelWorkingMode: ExitIsolationMode failed: %d\n",
                        (int)result);
            }
        }

        // Step 2: Delete the working group (all duplicates)
        if (fWorkingGroup) {
            ASErr result = sAIArt->DisposeArt(fWorkingGroup);
            if (result == kNoErr) {
                fprintf(stderr, "[IllTool] CancelWorkingMode: disposed working group\n");
            } else {
                fprintf(stderr, "[IllTool] CancelWorkingMode: DisposeArt(workingGroup) failed: %d\n",
                        (int)result);
            }
        }

        // Step 3: Restore originals — unlock and restore opacity
        for (auto& rec : fOriginalPaths) {
            if (sAIBlendStyle) {
                sAIBlendStyle->SetOpacity(rec.art, rec.prevOpacity);
            }
            sAIArt->SetArtUserAttr(rec.art, kArtLocked, 0);
        }

        int origCount = (int)fOriginalPaths.size();

        // Step 4: Clear state
        fOriginalPaths.clear();
        fWorkingGroup = nullptr;
        fInWorkingMode = false;

        // Step 5: Redraw
        sAIDocument->RedrawDocument();

        fprintf(stderr, "[IllTool] CancelWorkingMode: complete (%d originals restored)\n",
                origCount);
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool] CancelWorkingMode error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool] CancelWorkingMode unknown error\n");
    }
}

// Stage 3-4 stubs removed — real implementations are above (ClassifySelection, ReclassifyAs, SimplifySelection).
// Stage 5-6 full implementations follow below (CopyToGroup, DetachFromGroup, SplitToNewGroup, ScanEndpoints, MergeEndpoints, UndoMerge).

//========================================================================================
//  Smart Select — Boundary Signature Matching (Stage 9)
//========================================================================================

/*
    ComputeSignature — compute a geometric fingerprint of a path that captures
    its length, curvature profile, direction, closure, and complexity.
    Used by Smart Select to find visually similar paths.
*/
IllToolPlugin::BoundarySignature IllToolPlugin::ComputeSignature(AIArtHandle path)
{
    BoundarySignature sig = {0.0, 0.0, 0.0, 0.0, false, 0};

    if (!path || !sAIPath) return sig;

    try {
        // Get segment count
        ai::int16 segCount = 0;
        ASErr err = sAIPath->GetPathSegmentCount(path, &segCount);
        if (err != kNoErr || segCount == 0) return sig;
        sig.segmentCount = segCount;

        // Check if path is closed
        AIBoolean closed = false;
        sAIPath->GetPathClosed(path, &closed);
        sig.isClosed = (closed != 0);

        // Read all segments
        std::vector<AIPathSegment> segs(segCount);
        err = sAIPath->GetPathSegments(path, 0, segCount, segs.data());
        if (err != kNoErr) return sig;

        // Compute total path length using MeasureSegments (accurate arc lengths).
        // Number of pieces: open path = segCount-1, closed path = segCount.
        ai::int16 numPieces = sig.isClosed
                            ? segCount
                            : (segCount > 1 ? (ai::int16)(segCount - 1) : (ai::int16)0);
        if (numPieces > 0) {
            std::vector<AIReal> pieceLengths(numPieces);
            std::vector<AIReal> accumLengths(numPieces);
            err = sAIPath->MeasureSegments(path, 0, numPieces,
                                           pieceLengths.data(), accumLengths.data());
            if (err == kNoErr) {
                sig.totalLength = (double)accumLengths[numPieces - 1]
                                + (double)pieceLengths[numPieces - 1];
            }
        }

        // Fallback: sum straight-line distances if MeasureSegments yielded zero
        if (sig.totalLength <= 0.0 && segCount > 1) {
            double lenSum = 0.0;
            for (ai::int16 i = 1; i < segCount; i++) {
                double dx = (double)(segs[i].p.h - segs[i-1].p.h);
                double dy = (double)(segs[i].p.v - segs[i-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            if (sig.isClosed && segCount >= 2) {
                double dx = (double)(segs[0].p.h - segs[segCount-1].p.h);
                double dy = (double)(segs[0].p.v - segs[segCount-1].p.v);
                lenSum += std::sqrt(dx * dx + dy * dy);
            }
            sig.totalLength = lenSum;
        }

        // Average curvature: sum of absolute angle changes at interior anchors,
        // divided by total length (curvature density).
        if (segCount >= 3 && sig.totalLength > 0.0) {
            double angleChangeSum = 0.0;
            int numInteriorPts = sig.isClosed ? segCount : (segCount - 2);
            for (int ci = 0; ci < numInteriorPts; ci++) {
                int idx  = sig.isClosed ? ci : (ci + 1);
                int prev = (idx - 1 + segCount) % segCount;
                int next = (idx + 1) % segCount;

                double dx1 = (double)(segs[idx].p.h - segs[prev].p.h);
                double dy1 = (double)(segs[idx].p.v - segs[prev].p.v);
                double dx2 = (double)(segs[next].p.h - segs[idx].p.h);
                double dy2 = (double)(segs[next].p.v - segs[idx].p.v);

                double a1 = std::atan2(dy1, dx1);
                double a2 = std::atan2(dy2, dx2);
                double ad = a2 - a1;
                while (ad >  M_PI) ad -= 2.0 * M_PI;
                while (ad < -M_PI) ad += 2.0 * M_PI;
                angleChangeSum += std::fabs(ad);
            }
            sig.avgCurvature = angleChangeSum / sig.totalLength;
        }

        // Start and end tangent directions
        if (segCount >= 2) {
            double sx = (double)(segs[0].out.h - segs[0].p.h);
            double sy = (double)(segs[0].out.v - segs[0].p.v);
            if (std::fabs(sx) < 0.001 && std::fabs(sy) < 0.001) {
                sx = (double)(segs[1].p.h - segs[0].p.h);
                sy = (double)(segs[1].p.v - segs[0].p.v);
            }
            sig.startAngle = std::atan2(sy, sx);

            int last = segCount - 1;
            double ex = (double)(segs[last].p.h - segs[last].in.h);
            double ey = (double)(segs[last].p.v - segs[last].in.v);
            if (std::fabs(ex) < 0.001 && std::fabs(ey) < 0.001) {
                ex = (double)(segs[last].p.h - segs[last-1].p.h);
                ey = (double)(segs[last].p.v - segs[last-1].p.v);
            }
            sig.endAngle = std::atan2(ey, ex);
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Smart] ComputeSignature error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Smart] ComputeSignature unknown error\n");
    }
    return sig;
}

/*
    SelectMatchingPaths — find all paths in the document with a similar
    boundary signature, and select them.

    The threshold slider (0-100) controls matching strictness:
    - 0  = very strict (nearly identical paths only)
    - 100 = very loose (anything vaguely similar)
*/
void IllToolPlugin::SelectMatchingPaths(const BoundarySignature& refSig,
                                        double thresholdPct,
                                        AIArtHandle hitArt)
{
    try {
        // Map threshold 0-100 to tolerances
        double t = thresholdPct / 100.0;
        double lengthTol   = 0.05 + t * 0.75;
        double curvTol     = 0.10 + t * 1.90;
        int    maxSegDelta = 1 + (int)(t * 19.0);

        fprintf(stderr, "[IllTool Smart] Matching: threshold=%.0f%% lenTol=%.0f%% "
                "curvTol=%.0f%% segDelta=%d\n",
                thresholdPct, lengthTol * 100.0, curvTol * 100.0, maxSegDelta);

        // Get all path art in document
        AIMatchingArtSpec spec;
        spec.type = kPathArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool Smart] No paths in document\n");
            return;
        }

        // Deselect all currently selected art (clean slate)
        {
            AIMatchingArtSpec selSpec;
            selSpec.type = kAnyArt;
            selSpec.whichAttr = kArtSelected;
            selSpec.attr = kArtSelected;
            AIArtHandle** selMatches = nullptr;
            ai::int32 numSelMatches = 0;
            ASErr selErr = sAIMatchingArt->GetMatchingArt(&selSpec, 1,
                                                          &selMatches, &numSelMatches);
            if (selErr == kNoErr && numSelMatches > 0) {
                for (ai::int32 si = 0; si < numSelMatches; si++) {
                    sAIArt->SetArtUserAttr((*selMatches)[si], kArtSelected, 0);
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)selMatches);
            }
        }

        int matchCount = 0;
        int skippedLocked = 0;
        int skippedMismatch = 0;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];

            // Skip hidden or locked art
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) {
                skippedLocked++;
                continue;
            }

            // Always select the originally clicked path
            if (art == hitArt) {
                sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
                matchCount++;
                continue;
            }

            // Compute candidate signature
            BoundarySignature candSig = ComputeSignature(art);

            // Criteria 1: same open/closed status
            if (candSig.isClosed != refSig.isClosed) {
                skippedMismatch++;
                continue;
            }

            // Criteria 2: segment count within delta
            int segDiff = std::abs(candSig.segmentCount - refSig.segmentCount);
            if (segDiff > maxSegDelta) {
                skippedMismatch++;
                continue;
            }

            // Criteria 3: total length within tolerance
            if (refSig.totalLength > 0.001 || candSig.totalLength > 0.001) {
                double maxLen = std::max(refSig.totalLength, candSig.totalLength);
                if (maxLen > 0.001) {
                    double lenDiff = std::fabs(candSig.totalLength - refSig.totalLength)
                                   / maxLen;
                    if (lenDiff > lengthTol) {
                        skippedMismatch++;
                        continue;
                    }
                }
            }

            // Criteria 4: average curvature within tolerance
            double maxCurv = std::max(refSig.avgCurvature, candSig.avgCurvature);
            if (maxCurv > 0.0001) {
                double curvDiff = std::fabs(candSig.avgCurvature - refSig.avgCurvature)
                                / maxCurv;
                if (curvDiff > curvTol) {
                    skippedMismatch++;
                    continue;
                }
            }

            // All criteria passed
            sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
            matchCount++;
        }

        if (matches) {
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        fprintf(stderr, "[IllTool Smart] Matches: %d (skipped: %d locked, "
                "%d mismatch, %d total)\n",
                matchCount, skippedLocked, skippedMismatch, (int)numMatches);

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[IllTool Smart] SelectMatchingPaths error: %d\n", (int)ex);
    }
    catch (...) {
        fprintf(stderr, "[IllTool Smart] SelectMatchingPaths unknown error\n");
    }
}

//========================================================================================
//  Stage 5: Grouping Operations
//========================================================================================

void IllToolPlugin::CopyToGroup(const std::string& groupName)
{
    try {
        fprintf(stderr, "[IllTool] CopyToGroup: begin (name='%s')\n", groupName.c_str());

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            fprintf(stderr, "[IllTool] CopyToGroup: no path art found\n");
            return;
        }

        std::vector<AIArtHandle> selectedPaths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (hasSelected) selectedPaths.push_back(art);
        }

        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }

        if (selectedPaths.empty()) {
            fprintf(stderr, "[IllTool] CopyToGroup: no paths with selected segments\n");
            return;
        }

        fprintf(stderr, "[IllTool] CopyToGroup: %zu paths with selections\n", selectedPaths.size());

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) {
            fprintf(stderr, "[IllTool] CopyToGroup: NewArt(kGroupArt) failed: %d\n", (int)result);
            return;
        }

        ai::UnicodeString uName(groupName.c_str());
        sAIArt->SetArtName(groupArt, uName);

        int dupeCount = 0;
        for (AIArtHandle art : selectedPaths) {
            AIArtHandle dupArt = nullptr;
            result = sAIArt->DuplicateArt(art, kPlaceInsideOnTop, groupArt, &dupArt);
            if (result == kNoErr && dupArt) dupeCount++;
            else fprintf(stderr, "[IllTool] CopyToGroup: DuplicateArt failed: %d\n", (int)result);
        }

        fprintf(stderr, "[IllTool] CopyToGroup: duplicated %d paths into group '%s'\n", dupeCount, groupName.c_str());

        if (sAIIsolationMode && sAIIsolationMode->CanIsolateArt(groupArt)) {
            result = sAIIsolationMode->EnterIsolationMode(groupArt, false);
            if (result == kNoErr) fprintf(stderr, "[IllTool] CopyToGroup: entered isolation\n");
            else fprintf(stderr, "[IllTool] CopyToGroup: EnterIsolationMode failed: %d\n", (int)result);
        }

        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] CopyToGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] CopyToGroup unknown error\n"); }
}

void IllToolPlugin::DetachFromGroup()
{
    try {
        fprintf(stderr, "[IllTool] DetachFromGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool] DetachFromGroup: no paths\n"); return; }

        int detachedCount = 0;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;

            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (!hasSelected) continue;

            AIArtHandle parent = nullptr;
            result = sAIArt->GetArtParent(art, &parent);
            if (result != kNoErr || !parent) continue;

            short parentType = kUnknownArt;
            sAIArt->GetArtType(parent, &parentType);
            if (parentType != kGroupArt) continue;

            result = sAIArt->ReorderArt(art, kPlaceAbove, parent);
            if (result == kNoErr) detachedCount++;
            else fprintf(stderr, "[IllTool] DetachFromGroup: ReorderArt failed: %d\n", (int)result);
        }

        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[IllTool] DetachFromGroup: detached %d paths\n", detachedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] DetachFromGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] DetachFromGroup unknown error\n"); }
}

void IllToolPlugin::SplitToNewGroup()
{
    try {
        fprintf(stderr, "[IllTool] SplitToNewGroup: begin\n");

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) { fprintf(stderr, "[IllTool] SplitToNewGroup: no paths\n"); return; }

        std::vector<AIArtHandle> selectedPaths;
        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;
            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount == 0) continue;
            bool hasSelected = false;
            for (ai::int16 s = 0; s < segCount; s++) {
                ai::int16 sel = kSegmentNotSelected;
                sAIPath->GetPathSegmentSelected(art, s, &sel);
                if (sel & kSegmentPointSelected) { hasSelected = true; break; }
            }
            if (hasSelected) selectedPaths.push_back(art);
        }
        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }
        if (selectedPaths.empty()) { fprintf(stderr, "[IllTool] SplitToNewGroup: no selected paths\n"); return; }

        AIArtHandle groupArt = nullptr;
        result = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
        if (result != kNoErr || !groupArt) { fprintf(stderr, "[IllTool] SplitToNewGroup: NewArt failed: %d\n", (int)result); return; }

        ai::UnicodeString uName("Split Group");
        sAIArt->SetArtName(groupArt, uName);

        int movedCount = 0;
        for (AIArtHandle art : selectedPaths) {
            result = sAIArt->ReorderArt(art, kPlaceInsideOnTop, groupArt);
            if (result == kNoErr) movedCount++;
            else fprintf(stderr, "[IllTool] SplitToNewGroup: ReorderArt failed: %d\n", (int)result);
        }
        fprintf(stderr, "[IllTool] SplitToNewGroup: moved %d paths\n", movedCount);
        sAIDocument->RedrawDocument();
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] SplitToNewGroup error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] SplitToNewGroup unknown error\n"); }
}

//========================================================================================
//  Stage 6: Merge Operations
//========================================================================================

static double PointDistance(const AIRealPoint& a, const AIRealPoint& b)
{
    double dx = (double)a.h - (double)b.h;
    double dy = (double)a.v - (double)b.v;
    return sqrt(dx * dx + dy * dy);
}

void IllToolPlugin::ScanEndpoints(double tolerance)
{
    try {
        fprintf(stderr, "[IllTool] ScanEndpoints: begin (tolerance=%.1f)\n", tolerance);
        fMergePairs.clear();

        AIMatchingArtSpec spec(kPathArt, 0, 0);
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        ASErr result = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (result != kNoErr || numMatches == 0) {
            BridgeSetMergeReadout("0 pairs found, 0 paths");
            return;
        }

        struct OpenPath { AIArtHandle art; AIRealPoint startPt; AIRealPoint endPt; };
        std::vector<OpenPath> openPaths;

        for (ai::int32 i = 0; i < numMatches; i++) {
            AIArtHandle art = (*matches)[i];
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
            if (attrs & (kArtLocked | kArtHidden)) continue;

            AIBoolean closed = false;
            sAIPath->GetPathClosed(art, &closed);
            if (closed) continue;

            // Check selection (art-level or segment-level)
            ai::int32 artAttrs = 0;
            sAIArt->GetArtUserAttr(art, kArtSelected, &artAttrs);
            if (!(artAttrs & kArtSelected)) {
                ai::int16 sc = 0;
                sAIPath->GetPathSegmentCount(art, &sc);
                bool hasSel = false;
                for (ai::int16 s = 0; s < sc; s++) {
                    ai::int16 sel = kSegmentNotSelected;
                    sAIPath->GetPathSegmentSelected(art, s, &sel);
                    if (sel & kSegmentPointSelected) { hasSel = true; break; }
                }
                if (!hasSel) continue;
            }

            ai::int16 segCount = 0;
            sAIPath->GetPathSegmentCount(art, &segCount);
            if (segCount < 2) continue;

            AIPathSegment firstSeg, lastSeg;
            sAIPath->GetPathSegments(art, 0, 1, &firstSeg);
            sAIPath->GetPathSegments(art, segCount - 1, 1, &lastSeg);
            openPaths.push_back({art, firstSeg.p, lastSeg.p});
        }
        if (matches) { sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches); matches = nullptr; }

        fprintf(stderr, "[IllTool] ScanEndpoints: %zu open paths\n", openPaths.size());
        if (openPaths.size() < 2) {
            char buf[64]; snprintf(buf, sizeof(buf), "0 pairs found, %d paths", (int)openPaths.size());
            BridgeSetMergeReadout(buf); return;
        }

        std::vector<bool> used(openPaths.size(), false);
        for (size_t i = 0; i < openPaths.size(); i++) {
            if (used[i]) continue;
            int bestJ = -1; double bestDist = DBL_MAX;
            bool bestEA = true, bestEB = true;

            for (size_t j = i + 1; j < openPaths.size(); j++) {
                if (used[j]) continue;
                struct { double d; bool ea; bool eb; } combos[4] = {
                    {PointDistance(openPaths[i].endPt,   openPaths[j].startPt), true,  true},
                    {PointDistance(openPaths[i].endPt,   openPaths[j].endPt),   true,  false},
                    {PointDistance(openPaths[i].startPt, openPaths[j].startPt), false, true},
                    {PointDistance(openPaths[i].startPt, openPaths[j].endPt),   false, false},
                };
                for (int c = 0; c < 4; c++) {
                    if (combos[c].d <= tolerance && combos[c].d < bestDist) {
                        bestJ = (int)j; bestDist = combos[c].d;
                        bestEA = combos[c].ea; bestEB = combos[c].eb;
                    }
                }
            }
            if (bestJ >= 0) {
                fMergePairs.push_back({openPaths[i].art, openPaths[(size_t)bestJ].art, bestEA, bestEB, bestDist});
                used[i] = true; used[(size_t)bestJ] = true;
            }
        }

        char readout[128];
        snprintf(readout, sizeof(readout), "%d pairs found, %d paths", (int)fMergePairs.size(), (int)openPaths.size());
        BridgeSetMergeReadout(readout);
        fprintf(stderr, "[IllTool] ScanEndpoints: %zu pairs among %zu paths\n", fMergePairs.size(), openPaths.size());
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] ScanEndpoints error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] ScanEndpoints unknown error\n"); }
}

void IllToolPlugin::MergeEndpoints(bool chainMerge, bool preserveHandles)
{
    try {
        if (fMergePairs.empty()) { fprintf(stderr, "[IllTool] MergeEndpoints: no pairs\n"); return; }

        fprintf(stderr, "[IllTool] MergeEndpoints: begin (chain=%s, preserve=%s, %zu pairs)\n",
                chainMerge ? "true" : "false", preserveHandles ? "true" : "false", fMergePairs.size());

        fMergeSnapshot = MergeSnapshot();
        fMergeSnapshot.valid = true;
        int totalMerged = 0;
        int maxIterations = chainMerge ? 10 : 1;

        for (int iteration = 0; iteration < maxIterations; iteration++) {
            if (fMergePairs.empty()) break;
            std::vector<AIArtHandle> toDispose;

            for (auto& pair : fMergePairs) {
                ai::int16 segCountA = 0;
                sAIPath->GetPathSegmentCount(pair.artA, &segCountA);
                if (segCountA == 0) continue;
                std::vector<AIPathSegment> segsA(segCountA);
                sAIPath->GetPathSegments(pair.artA, 0, segCountA, segsA.data());

                ai::int16 segCountB = 0;
                sAIPath->GetPathSegmentCount(pair.artB, &segCountB);
                if (segCountB == 0) continue;
                std::vector<AIPathSegment> segsB(segCountB);
                sAIPath->GetPathSegments(pair.artB, 0, segCountB, segsB.data());

                // Snapshot for undo
                {
                    MergeSnapshot::PathData pdA;
                    pdA.segments = segsA;
                    AIBoolean cA = false; sAIPath->GetPathClosed(pair.artA, &cA); pdA.closed = cA;
                    AIArtHandle pA = nullptr; sAIArt->GetArtParent(pair.artA, &pA); pdA.parentRef = pA;
                    fMergeSnapshot.originals.push_back(pdA);

                    MergeSnapshot::PathData pdB;
                    pdB.segments = segsB;
                    AIBoolean cB = false; sAIPath->GetPathClosed(pair.artB, &cB); pdB.closed = cB;
                    AIArtHandle pB = nullptr; sAIArt->GetArtParent(pair.artB, &pB); pdB.parentRef = pB;
                    fMergeSnapshot.originals.push_back(pdB);
                }

                // Orient so matched ends meet
                if (!pair.endA_is_end) {
                    std::reverse(segsA.begin(), segsA.end());
                    for (auto& seg : segsA) std::swap(seg.in, seg.out);
                }
                if (!pair.endB_is_start) {
                    std::reverse(segsB.begin(), segsB.end());
                    for (auto& seg : segsB) std::swap(seg.in, seg.out);
                }

                // Build junction
                AIPathSegment& jA = segsA.back();
                AIPathSegment& jB = segsB.front();
                AIPathSegment junction;
                if (preserveHandles) {
                    junction.p = jA.p; junction.in = jA.in; junction.out = jB.out; junction.corner = false;
                } else {
                    junction.p.h = (jA.p.h + jB.p.h) / 2.0f;
                    junction.p.v = (jA.p.v + jB.p.v) / 2.0f;
                    junction.in = jA.in; junction.out = jB.out; junction.corner = false;
                }

                // Concatenate: A[0..n-2] + junction + B[1..end]
                std::vector<AIPathSegment> merged;
                for (int k = 0; k < (int)segsA.size() - 1; k++) merged.push_back(segsA[k]);
                merged.push_back(junction);
                for (int k = 1; k < (int)segsB.size(); k++) merged.push_back(segsB[k]);

                AIArtHandle newPath = nullptr;
                ASErr nr = sAIArt->NewArt(kPathArt, kPlaceAbove, pair.artA, &newPath);
                if (nr != kNoErr || !newPath) { fprintf(stderr, "[IllTool] MergeEndpoints: NewArt failed: %d\n", (int)nr); continue; }

                sAIPath->SetPathSegmentCount(newPath, (ai::int16)merged.size());
                sAIPath->SetPathSegments(newPath, 0, (ai::int16)merged.size(), merged.data());
                sAIPath->SetPathClosed(newPath, false);

                fMergeSnapshot.mergedPaths.push_back(newPath);
                toDispose.push_back(pair.artA);
                toDispose.push_back(pair.artB);
                totalMerged++;
            }

            for (AIArtHandle art : toDispose) sAIArt->DisposeArt(art);

            // Chain merge: re-scan
            if (chainMerge && iteration < maxIterations - 1) {
                double tol = BridgeGetScanTolerance();
                fMergePairs.clear();

                AIMatchingArtSpec reSpec(kPathArt, 0, 0);
                AIArtHandle** reM = nullptr; ai::int32 reN = 0;
                if (sAIMatchingArt->GetMatchingArt(&reSpec, 1, &reM, &reN) != kNoErr || reN == 0) break;

                struct COP { AIArtHandle art; AIRealPoint s, e; };
                std::vector<COP> cp;
                for (ai::int32 ri = 0; ri < reN; ri++) {
                    AIArtHandle art = (*reM)[ri];
                    ai::int32 at = 0; sAIArt->GetArtUserAttr(art, kArtLocked|kArtHidden, &at);
                    if (at & (kArtLocked|kArtHidden)) continue;
                    AIBoolean cl = false; sAIPath->GetPathClosed(art, &cl); if (cl) continue;
                    ai::int16 sc = 0; sAIPath->GetPathSegmentCount(art, &sc); if (sc < 2) continue;
                    AIPathSegment f, l; sAIPath->GetPathSegments(art, 0, 1, &f); sAIPath->GetPathSegments(art, sc-1, 1, &l);
                    cp.push_back({art, f.p, l.p});
                }
                if (reM) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)reM);
                if (cp.size() < 2) break;

                std::vector<bool> cu(cp.size(), false);
                for (size_t ci = 0; ci < cp.size(); ci++) {
                    if (cu[ci]) continue;
                    int bJ = -1; double bD = DBL_MAX; bool bEA = true, bEB = true;
                    for (size_t cj = ci+1; cj < cp.size(); cj++) {
                        if (cu[cj]) continue;
                        struct { double d; bool ea, eb; } cm[4] = {
                            {PointDistance(cp[ci].e, cp[cj].s), true, true},
                            {PointDistance(cp[ci].e, cp[cj].e), true, false},
                            {PointDistance(cp[ci].s, cp[cj].s), false, true},
                            {PointDistance(cp[ci].s, cp[cj].e), false, false},
                        };
                        for (int c = 0; c < 4; c++) {
                            if (cm[c].d <= tol && cm[c].d < bD) { bJ=(int)cj; bD=cm[c].d; bEA=cm[c].ea; bEB=cm[c].eb; }
                        }
                    }
                    if (bJ >= 0) {
                        fMergePairs.push_back({cp[ci].art, cp[(size_t)bJ].art, bEA, bEB, bD});
                        cu[ci] = true; cu[(size_t)bJ] = true;
                    }
                }
                if (fMergePairs.empty()) break;
            } else {
                fMergePairs.clear();
            }
        }

        char readout[128];
        snprintf(readout, sizeof(readout), "Merged %d pairs", totalMerged);
        BridgeSetMergeReadout(readout);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool] MergeEndpoints: merged %d pairs\n", totalMerged);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] MergeEndpoints error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] MergeEndpoints unknown error\n"); }
}

void IllToolPlugin::UndoMerge()
{
    try {
        if (!fMergeSnapshot.valid) { fprintf(stderr, "[IllTool] UndoMerge: no snapshot\n"); return; }

        fprintf(stderr, "[IllTool] UndoMerge: %zu originals, %zu merged\n",
                fMergeSnapshot.originals.size(), fMergeSnapshot.mergedPaths.size());

        for (AIArtHandle art : fMergeSnapshot.mergedPaths) {
            ASErr r = sAIArt->DisposeArt(art);
            if (r != kNoErr) fprintf(stderr, "[IllTool] UndoMerge: DisposeArt failed: %d\n", (int)r);
        }

        int restoredCount = 0;
        for (auto& pd : fMergeSnapshot.originals) {
            if (pd.segments.empty()) continue;
            AIArtHandle newPath = nullptr;
            ASErr r = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (r != kNoErr || !newPath) { fprintf(stderr, "[IllTool] UndoMerge: NewArt failed: %d\n", (int)r); continue; }

            sAIPath->SetPathSegmentCount(newPath, (ai::int16)pd.segments.size());
            sAIPath->SetPathSegments(newPath, 0, (ai::int16)pd.segments.size(),
                                     const_cast<AIPathSegment*>(pd.segments.data()));
            sAIPath->SetPathClosed(newPath, pd.closed);
            restoredCount++;
        }

        fMergeSnapshot = MergeSnapshot();
        char readout[128];
        snprintf(readout, sizeof(readout), "Undo: restored %d paths", restoredCount);
        BridgeSetMergeReadout(readout);
        sAIDocument->RedrawDocument();
        fprintf(stderr, "[IllTool] UndoMerge: restored %d paths\n", restoredCount);
    }
    catch (ai::Error& ex) { fprintf(stderr, "[IllTool] UndoMerge error: %d\n", (int)ex); }
    catch (...) { fprintf(stderr, "[IllTool] UndoMerge unknown error\n"); }
}
