//========================================================================================
//
//  IllTool Plugin — Thin Router Implementation
//
//  Owns lifecycle, SDK registration, and operation dispatch.
//  All feature logic lives in modules (CleanupModule, PerspectiveModule, etc.).
//  This file routes operations, mouse events, and draw calls to modules.
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "AITool.h"
#include "LearningEngine.h"

// Module headers
#include "modules/CleanupModule.h"
#include "modules/PerspectiveModule.h"
#include "modules/SelectionModule.h"
#include "modules/MergeModule.h"
#include "modules/GroupingModule.h"
#include "modules/BlendModule.h"
#include "modules/ShadingModule.h"
#include "modules/DecomposeModule.h"

#include <cstdio>
#include <cmath>
#include <chrono>
#include <algorithm>
#include <string>

IllToolPlugin *gPlugin = NULL;

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
    fShadingController(NULL), fBlendController(NULL), fPerspectiveController(NULL)
{
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
        // Don't check_ai_error -- panels are non-fatal if they fail
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
            result = kNoErr;  // Non-fatal -- panels still work via Window menu items
        } else {
            fprintf(stderr, "[IllTool] Application menu registered\n");
        }

        // Create feature modules (order matters for HandleOp priority)
        fprintf(stderr, "[IllTool] Creating modules...\n");
        {
            auto addModule = [this](std::unique_ptr<IllToolModule> mod) {
                mod->SetPlugin(this);
                fModules.push_back(std::move(mod));
            };
            addModule(std::make_unique<SelectionModule>());
            addModule(std::make_unique<CleanupModule>());
            addModule(std::make_unique<PerspectiveModule>());
            addModule(std::make_unique<MergeModule>());
            addModule(std::make_unique<GroupingModule>());
            addModule(std::make_unique<BlendModule>());
            addModule(std::make_unique<ShadingModule>());
            addModule(std::make_unique<DecomposeModule>());
        }
        fprintf(stderr, "[IllTool] %zu modules created\n", fModules.size());

        // Register operation timer -- fires ~10 times/sec in SDK context.
        // This is the ONLY safe way to execute SDK API calls from panel buttons
        // and HTTP bridge requests, since those run outside SDK message dispatch.
        if (sAITimer) {
            result = sAITimer->AddTimer(message->d.self, "IllTool Ops",
                                        kTicksPerSecond / 10, &fOperationTimer);
            if (result) {
                fprintf(stderr, "[IllTool] Timer registration failed: %d\n", (int)result);
                result = kNoErr;  // Non-fatal -- fall back to TrackToolCursor polling
            } else {
                fprintf(stderr, "[IllTool] Operation timer registered (period=%d ticks, ~10Hz)\n",
                        kTicksPerSecond / 10);
            }
        } else {
            fprintf(stderr, "[IllTool] WARNING: AITimerSuite not available -- using TrackToolCursor only\n");
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

        // Notify all modules of initial document state
        for (auto& mod : fModules) {
            mod->OnDocumentChanged();
        }

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

        // Destroy modules
        fModules.clear();
        fprintf(stderr, "[IllTool] Modules destroyed\n");

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
                AIToolMessage* toolMsg = (AIToolMessage*)message;

                // Perspective tool: drag and up handled by PerspectiveModule
                if (toolMsg->tool == fPerspectiveToolHandle) {
                    auto* persp = GetModule<PerspectiveModule>();
                    if (persp) {
                        if (strcmp(selector, kSelectorAIToolMouseDrag) == 0) {
                            persp->HandleMouseDrag(toolMsg);
                            result = kNoErr;
                        }
                        else if (strcmp(selector, kSelectorAIToolMouseUp) == 0) {
                            persp->HandleMouseUp(toolMsg);
                            result = kNoErr;
                        }
                    }
                }
                else if (toolMsg->tool == fToolHandle) {
                    // Main tool: perspective VP drag forwarding
                    auto* persp = GetModule<PerspectiveModule>();
                    if (persp && persp->HandleMouseDrag(toolMsg)) {
                        // PerspectiveModule consumed the drag (VP handle drag in progress)
                        if (strcmp(selector, kSelectorAIToolMouseDrag) == 0) {
                            result = kNoErr;
                        }
                        else if (strcmp(selector, kSelectorAIToolMouseUp) == 0) {
                            persp->HandleMouseUp(toolMsg);
                            result = kNoErr;
                        }
                    }
                    else {
                        // Main tool: delegate drag/up to modules
                        // Priority: cleanup → perspective → others
                        if (strcmp(selector, kSelectorAIToolMouseDrag) == 0) {
                            bool handled = false;
                            auto* cleanup = GetModule<CleanupModule>();
                            if (cleanup && cleanup->IsInWorkingMode()) {
                                handled = cleanup->HandleMouseDrag(toolMsg);
                            }
                            if (!handled) {
                                auto* persp = GetModule<PerspectiveModule>();
                                if (persp) handled = persp->HandleMouseDrag(toolMsg);
                            }
                            if (!handled) {
                                for (auto& mod : fModules) {
                                    if (mod->HandleMouseDrag(toolMsg)) break;
                                }
                            }
                            result = kNoErr;
                        }
                        else if (strcmp(selector, kSelectorAIToolMouseUp) == 0) {
                            bool handled = false;
                            auto* cleanup = GetModule<CleanupModule>();
                            if (cleanup && cleanup->IsInWorkingMode()) {
                                handled = cleanup->HandleMouseUp(toolMsg);
                            }
                            if (!handled) {
                                auto* persp = GetModule<PerspectiveModule>();
                                if (persp) handled = persp->HandleMouseUp(toolMsg);
                            }
                            if (!handled) {
                                for (auto& mod : fModules) {
                                    if (mod->HandleMouseUp(toolMsg)) break;
                                }
                            }
                            result = kNoErr;
                        }
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
            fprintf(stderr, "[IllTool Menu] Polygon Lasso selected\n");
            BridgeSetToolMode(BridgeToolMode::Lasso);
            if (sAITool && fToolHandle) {
                sAITool->SetSelectedTool(fToolHandle);
            }
        }
        else if (message->menuItem == fMenuSmartHandle) {
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

            // Also push to CleanupModule so it can serve PluginGetSelectedAnchorCount
            auto* cleanup = GetModule<CleanupModule>();
            if (cleanup) cleanup->SetSelectedAnchorCount(count);

            fprintf(stderr, "[IllTool] SelectionChanged: %d anchors selected\n", count);

            // Auto-classify the selected shape when selection changes
            if (count > 0) {
                BridgeRequestClassify();
            }

            // Notify all modules
            for (auto& mod : fModules) {
                mod->OnSelectionChanged();
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

        // Stage 8: Locked isolation mode -- re-enter if user escapes while in working mode
        if (message->notifier == fIsolationChangedNotifier) {
            auto* cleanup = GetModule<CleanupModule>();
            if (cleanup && cleanup->IsInWorkingMode() && !cleanup->IsExitingWorkingMode()
                && cleanup->GetWorkingGroup() && sAIIsolationMode) {
                AIIsolationModeChangedNotifierData* data =
                    (AIIsolationModeChangedNotifierData*)message->notifyData;
                if (data && !data->inIsolationMode) {
                    fprintf(stderr, "[IllTool] Isolation breach detected (notifier) -- re-entering isolation\n");
                    AIArtHandle wg = cleanup->GetWorkingGroup();
                    if (sAIIsolationMode->CanIsolateArt(wg)) {
                        ASErr isoErr = sAIIsolationMode->EnterIsolationMode(wg, false);
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

ASErr IllToolPlugin::ToolMouseDown(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        // Perspective tool: dispatch to PerspectiveModule's dedicated handler
        if (message->tool == fPerspectiveToolHandle) {
            auto* persp = GetModule<PerspectiveModule>();
            if (persp) persp->HandleMouseDown(message);
            return kNoErr;
        }

        // Priority 1: if CleanupModule is in working mode, try it first (handle editing)
        {
            auto* cleanup = GetModule<CleanupModule>();
            if (cleanup && cleanup->IsInWorkingMode()) {
                if (cleanup->HandleMouseDown(message)) return kNoErr;
            }
        }

        // Priority 2: if perspective grid is visible+unlocked, try VP handle dragging
        // This lets the user drag VP handles with the main IllTool tool (no tool switch)
        {
            auto* persp = GetModule<PerspectiveModule>();
            if (persp && persp->HandleMouseDown(message)) return kNoErr;
        }

        // Try each module's HandleMouseDown (lasso, blend pick, etc.)
        for (auto& mod : fModules) {
            if (dynamic_cast<PerspectiveModule*>(mod.get())) continue;  // already tried at Priority 2
            if (mod->HandleMouseDown(message)) return kNoErr;
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
//  ProcessOperationQueue -- called from AITimerSuite at ~10Hz in SDK message context.
//  Dequeues operations from the H1 operation queue and dispatches to modules.
//========================================================================================

void IllToolPlugin::ProcessOperationQueue()
{
    // Check dirty flag for HTTP-sent draw commands
    if (IsDirty()) {
        SetDirty(false);
        InvalidateFullView();
    }

    // H1: Dequeue and dispatch all pending operations to modules
    PluginOp op;
    while (BridgeDequeueOp(op)) {
        bool handled = false;
        for (auto& mod : fModules) {
            if (mod->HandleOp(op)) { handled = true; break; }
        }
        if (!handled) {
            fprintf(stderr, "[IllTool] Unhandled op: %d\n", (int)op.type);
        }
    }

    // Stage 8: Isolation re-entry DISABLED.
    // User wants preview path to stay visible and adjustable without forced isolation.
    // The preview has an orange stroke and stays selected — no need to lock the user in.
    // Isolation re-entry was forcing the user back into isolation every time they clicked
    // outside the working group, preventing normal interaction with other tools.
}

/*
    TrackToolCursor -- called on every mouse-move while our tool is selected.
    Handles cursor position tracking, rubber-band polygon overlay, and
    dirty-flag checking for responsiveness when the tool is active.
*/
ASErr IllToolPlugin::TrackToolCursor(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        // Check dirty flag for HTTP-sent draw commands (also checked by timer,
        // but checking here too gives immediate response when tool is active)
        if (IsDirty()) {
            SetDirty(false);
            InvalidateFullView();
        }

        // Track cursor for handle hover highlighting (cleanup + perspective)
        auto* cleanup = GetModule<CleanupModule>();
        if (cleanup && cleanup->IsInWorkingMode()) {
            cleanup->HandleCursorTrack(message->cursor);
        }
        // Only track non-cleanup handles when cleanup is NOT in working mode
        if (!cleanup || !cleanup->IsInWorkingMode()) {
            auto* persp = GetModule<PerspectiveModule>();
            if (persp) {
                persp->HandleCursorTrack(message->cursor);
            }
            auto* selection = GetModule<SelectionModule>();
            if (selection) {
                selection->UpdateHoverVertex(message->cursor);
            }
        }

        // Set cursor — arrow when editing handles (cleanup or perspective), lasso icon otherwise
        if (sAIUser != NULL) {
            bool showArrow = false;
            if (cleanup && cleanup->IsInWorkingMode()) showArrow = true;

            // Show arrow when in perspective edit mode
            if (!showArrow) {
                auto* persp = GetModule<PerspectiveModule>();
                if (persp && persp->IsInEditMode()) showArrow = true;
            }

            if (showArrow) {
                sAIUser->SetCursor(kAIArrowCursorID, fResourceManagerHandle);
            } else {
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
    SelectTool -- activates the annotator when the user selects our tool.
*/
ASErr IllToolPlugin::SelectTool(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (message->tool == fPerspectiveToolHandle) {
            fprintf(stderr, "[IllTool] Perspective tool selected -- activating annotator\n");
        } else {
            fprintf(stderr, "[IllTool] Tool selected -- activating annotator\n");
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
    DeselectTool -- annotator stays active (never deactivated).
    Clears any tool-specific drag state.
*/
ASErr IllToolPlugin::DeselectTool(AIToolMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (message->tool == fPerspectiveToolHandle) {
            fprintf(stderr, "[IllTool] Perspective tool deselected\n");
        } else {
            fprintf(stderr, "[IllTool] Tool deselected\n");
        }

        // Do NOT deactivate the annotator -- perspective grid, bounding box,
        // and other overlays must remain visible regardless of active tool.
        InvalidateFullView();
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
        data.tooltip = ai::UnicodeString::FromRoman("IllTool Handle -- overlay drawing tool");

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
        perspData.tooltip = ai::UnicodeString::FromRoman("IllTool Perspective -- place and drag perspective lines");

        AIToolType mainToolNum = kNoTool;
        sAITool->GetToolNumberFromHandle(fToolHandle, &mainToolNum);
        perspData.sameGroupAs = mainToolNum;
        perspData.sameToolsetAs = mainToolNum;

        perspData.normalIconResID = kIllToolIconResourceID;
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

        // Activate immediately — overlays (perspective grid, bbox, lasso)
        // must be visible regardless of which tool is active
        result = sAIAnnotator->SetAnnotatorActive(fAnnotatorHandle, true);
        aisdk::check_ai_error(result);

        fprintf(stderr, "[IllTool] Annotator registered (ACTIVE)\n");
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
            result = kNoErr;  // Non-fatal -- timer fallback will still work
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

ASErr IllToolPlugin::AddAppMenu(SPInterfaceMessage* message)
{
    ASErr result = kNoErr;
    try {
        if (!sAIMenu) {
            fprintf(stderr, "[IllTool] AddAppMenu: AIMenuSuite not available\n");
            return kCantHappenErr;
        }

        // Step 1: Create the root "IllTool" item in the Window menu's Tool Palettes group.
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
        // Draw HTTP bridge draw commands via IllToolAnnotator
        if (this->fAnnotator) {
            result = this->fAnnotator->Draw(message);
            aisdk::check_ai_error(result);
        }

        // Delegate overlay drawing to all modules
        static int drawCount = 0;
        if (drawCount++ % 100 == 0) {
            fprintf(stderr, "[IllTool] DrawAnnotation called (%d modules, cycle %d)\n",
                    (int)fModules.size(), drawCount);
        }
        for (auto& mod : fModules) {
            mod->DrawOverlay(message);
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
//  InvalidateFullView
//========================================================================================

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
        // Silently ignore -- can happen during shutdown
    }
}

//========================================================================================
//  GetMatchingArtIsolationAware
//========================================================================================

ASErr GetMatchingArtIsolationAware(
    AIMatchingArtSpec* spec, ai::int16 numSpecs,
    AIArtHandle*** matches, ai::int32* numMatches)
{
    // When in isolation mode, scope the search to the isolated art tree
    if (sAIIsolationMode && sAIIsolationMode->IsInIsolationMode()) {
        // If the plugin has an active working group (via CleanupModule), search within it
        if (gPlugin) {
            auto* cleanup = gPlugin->GetModule<CleanupModule>();
            if (cleanup && cleanup->IsInWorkingMode() && cleanup->GetWorkingGroup()) {
                ASErr err = sAIMatchingArt->GetMatchingArtFromArt(
                    cleanup->GetWorkingGroup(), spec, numSpecs, matches, numMatches);
                if (err == kNoErr && *numMatches > 0) {
                    return kNoErr;
                }
            }
        }

        // Fallback: get the isolated art parent and search from there
        AIArtHandle isolatedArtParent = nullptr;
        sAIIsolationMode->GetIsolatedArtAndParents(&isolatedArtParent, nullptr);
        if (isolatedArtParent) {
            ASErr err = sAIMatchingArt->GetMatchingArtFromArt(
                isolatedArtParent, spec, numSpecs, matches, numMatches);
            if (err == kNoErr && *numMatches > 0) {
                return kNoErr;
            }
        }
    }

    // Not in isolation mode, or isolation search found nothing -- search whole document
    return sAIMatchingArt->GetMatchingArt(spec, numSpecs, matches, numMatches);
}

//========================================================================================
//  C-callable wrappers -- delegate to modules
//========================================================================================

void PluginAverageSelection()
{
    // Queue the operation -- it will be dispatched to CleanupModule by ProcessOperationQueue
    BridgeRequestAverageSelection();
}

void PluginApplyWorkingMode(bool deleteOriginals)
{
    BridgeRequestWorkingApply(deleteOriginals);
}

void PluginCancelWorkingMode()
{
    BridgeRequestWorkingCancel();
}

int PluginGetSelectedAnchorCount()
{
    // Return the cached count from CleanupModule (set by Notify handler)
    if (gPlugin) {
        auto* cleanup = gPlugin->GetModule<CleanupModule>();
        if (cleanup) return cleanup->GetSelectedAnchorCount();
        // Fallback to plugin-level atomic
        return gPlugin->fLastKnownSelectionCount.load();
    }
    return 0;
}
