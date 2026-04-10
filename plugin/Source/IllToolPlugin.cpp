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
#include "ProjectStore.h"

// Module headers
#include "modules/CleanupModule.h"
#include "modules/PerspectiveModule.h"
#include "modules/SelectionModule.h"
#include "modules/MergeModule.h"
#include "modules/GroupingModule.h"
#include "modules/BlendModule.h"
#include "modules/ShadingModule.h"
#include "modules/DecomposeModule.h"
#include "modules/TransformModule.h"
#include "modules/TraceModule.h"
#include "modules/SurfaceModule.h"
#include "modules/PenModule.h"
#include "UISkinLoader.h"

// New modules not in Xcode pbxproj — compile them here
#include "modules/TransformModule.cpp"
#include "modules/TraceModule.cpp"
#include "modules/SurfaceModule.cpp"
#include "modules/PenModule.cpp"
#include "UISkinLoader.cpp"
#include "ProjectStore.cpp"

#include "vendor/json.hpp"

#include <cstdio>
#include <cmath>
#include <chrono>
#include <algorithm>
#include <string>
#include <set>

using json = nlohmann::json;

#import <AppKit/NSEvent.h>  // For modifier key state in TrackToolCursor

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
    fTransformPanel(NULL), fTracePanel(NULL), fSurfacePanel(NULL), fPenPanel(NULL),
    fSelectionMenuHandle(NULL), fCleanupMenuHandle(NULL),
    fGroupingMenuHandle(NULL), fMergeMenuHandle(NULL),
    fShadingMenuHandle(NULL), fBlendMenuHandle(NULL), fPerspectiveMenuHandle(NULL),
    fTransformMenuHandle(NULL), fTraceMenuHandle(NULL), fSurfaceMenuHandle(NULL), fPenMenuHandle(NULL),
    fAppMenuRootHandle(NULL),
    fMenuLassoHandle(NULL), fMenuSmartHandle(NULL),
    fMenuCleanupHandle(NULL), fMenuGroupingHandle(NULL),
    fMenuMergeHandle(NULL), fMenuSelectionHandle(NULL), fMenuPerspToggleHandle(NULL),
    fSelectionController(NULL), fCleanupController(NULL),
    fGroupingController(NULL), fMergeController(NULL),
    fShadingController(NULL), fBlendController(NULL), fPerspectiveController(NULL),
    fTransformController(NULL), fTraceController(NULL), fSurfaceController(NULL), fPenController(NULL)
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
            addModule(std::make_unique<TransformModule>());
            addModule(std::make_unique<TraceModule>());
            addModule(std::make_unique<SurfaceModule>());
            addModule(std::make_unique<PenModule>());
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

        // Load UI skin (handle sizes, colors, cursors)
        UISkinLoader::Instance().Load();

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

        // Initialize project store for current document
        ProjectStore::Instance().InitForDocument();

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

        // Upload telemetry if consent granted (fire-and-forget, non-blocking)
        LearningEngine::Instance().UploadTelemetry();

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
                            fDragInProgress = false;
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
                            fDragInProgress = false;
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
                            fDragInProgress = false;
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
        // Toggle Perspective Lock (Shift+Cmd+P)
        //----------------------------------------------------------------------
        else if (message->menuItem == fMenuPerspToggleHandle) {
            bool locked = BridgeGetPerspectiveLocked();
            BridgeSetPerspectiveLocked(!locked);
            PluginOp lockOp{OpType::LockPerspective};
            lockOp.boolParam1 = !locked;
            BridgeEnqueueOp(lockOp);
            fprintf(stderr, "[IllTool Menu] Perspective lock toggled to %s\n",
                    !locked ? "locked" : "unlocked");
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
                { fTransformMenuHandle, fTransformPanel,  "Transform (menu)" },
                { fTraceMenuHandle,     fTracePanel,      "Trace (menu)" },
                { fSurfaceMenuHandle,   fSurfacePanel,    "Surface (menu)" },
                { fPenMenuHandle,       fPenPanel,        "Pen" },
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
        fDragInProgress = true;  // Prevent ProcessOperationQueue from dequeueing Apply/Cancel mid-drag

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

        // Priority 2: Pen mode — intercept clicks for point placement
        {
            if (BridgeGetPenMode()) {
                auto* pen = GetModule<PenModule>();
                if (pen && pen->HandleMouseDown(message)) return kNoErr;
            }
        }

        // Priority 3: Blend pick mode — must run BEFORE lasso (which consumes all clicks)
        {
            int blendPick = BridgeGetBlendPickMode();
            if (blendPick > 0) {
                auto* blend = GetModule<BlendModule>();
                if (blend && blend->HandleMouseDown(message)) return kNoErr;
            }
        }

        // Priority 3: Surface extract mode — click-to-extract
        {
            if (BridgeGetSurfaceExtractMode()) {
                auto* surface = GetModule<SurfaceModule>();
                if (surface && surface->HandleExtractClick(message->cursor)) return kNoErr;
            }
        }

        // Priority 4: Shading eyedropper mode
        {
            if (BridgeGetShadingEyedropperMode()) {
                auto* shading = GetModule<ShadingModule>();
                if (shading && shading->HandleMouseDown(message)) return kNoErr;
            }
        }

        // Priority 5: if perspective grid is visible+unlocked, try VP handle dragging
        {
            auto* persp = GetModule<PerspectiveModule>();
            if (persp && persp->HandleMouseDown(message)) return kNoErr;
        }

        // Priority 7: remaining modules (lasso, selection, etc.)
        for (auto& mod : fModules) {
            if (dynamic_cast<PerspectiveModule*>(mod.get())) continue;  // already tried
            if (dynamic_cast<BlendModule*>(mod.get())) continue;        // already tried
            if (dynamic_cast<SurfaceModule*>(mod.get())) continue;      // already tried
            if (dynamic_cast<ShadingModule*>(mod.get())) continue;      // already tried
            if (dynamic_cast<PenModule*>(mod.get())) continue;          // already tried
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

    //------------------------------------------------------------------------
    //  MCP Synchronous Request/Response — handle pending sync requests first
    //  These are posted by HTTP handler threads and need a condvar signal back.
    //------------------------------------------------------------------------
    {
        PluginOp mcpOp;
        if (BridgeMcpPeekRequest(mcpOp)) {
            HandleMcpOperation(mcpOp);
        }
    }

    // H1: Dequeue and dispatch all pending operations to modules
    PluginOp op;
    while (BridgeDequeueOp(op)) {
        // Guard: don't process Apply/Cancel/Undo while a mouse drag is in progress.
        // The timer fires at ~10Hz and could dequeue these ops between mouse events.
        // Processing undo mid-drag corrupts the drag state and crashes.
        if (fDragInProgress &&
            (op.type == OpType::WorkingApply || op.type == OpType::WorkingCancel ||
             op.type == OpType::UndoShape)) {
            BridgeRequeueOp(op);  // put it back for next tick
            break;
        }
        // Set undo context for all mutating operations so Cmd+Z works globally.
        // Read-only ops (Classify) don't need this, but it's harmless to set it.
        if (sAIUndo) {
            const char* undoName = "Undo IllTool";
            switch (op.type) {
                case OpType::Trace:              undoName = "Undo Trace"; break;
                case OpType::AverageSelection:   undoName = "Undo Shape Cleanup"; break;
                case OpType::WorkingApply:       undoName = "Undo Apply"; break;
                case OpType::BlendExecute:       undoName = "Undo Blend"; break;
                case OpType::MergeEndpoints:     undoName = "Undo Merge"; break;
                case OpType::ShadingApplyBlend:
                case OpType::ShadingApplyMesh:   undoName = "Undo Shading"; break;
                case OpType::TransformApply:     undoName = "Undo Transform"; break;
                case OpType::Decompose:          undoName = "Undo Decompose"; break;
                case OpType::SurfaceExtract:     undoName = "Undo Extract"; break;
                case OpType::PenFinalize:        undoName = "Undo Pen Path"; break;
                default: break;
            }
            sAIUndo->SetUndoTextUS(ai::UnicodeString(undoName),
                                    ai::UnicodeString(undoName));  // redo text same
        }

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

//========================================================================================
//  HandleMcpOperation — synchronous SDK operations for MCP tool integration.
//  Runs in timer/SDK context. Posts JSON result back to HTTP thread via condvar.
//========================================================================================

void IllToolPlugin::HandleMcpOperation(const PluginOp& op)
{
    json resp;

    try {
        switch (op.type) {

        //----------------------------------------------------------------
        //  McpInspect — document + selection info
        //----------------------------------------------------------------
        case OpType::McpInspect: {
            resp["ok"] = true;

            // Document info
            json docInfo;
            if (sAIDocument) {
                ai::FilePath filePath;
                if (sAIDocument->GetDocumentFileSpecification(filePath) == kNoErr) {
                    ai::UnicodeString fileName = filePath.GetFileName();
                    std::string nameStr = fileName.as_UTF8();
                    docInfo["name"] = nameStr;
                } else {
                    docInfo["name"] = "Untitled";
                }

                AIDocumentSetup setup;
                memset(&setup, 0, sizeof(setup));
                if (sAIDocument->GetDocumentSetup(&setup) == kNoErr) {
                    docInfo["width"]  = (double)setup.width;
                    docInfo["height"] = (double)setup.height;
                }
            }

            // Artboard count — ai::ArtboardList wrappers need IAIArtboards.cpp linked,
            // which pulls in assertion stubs we don't have. Default to 1.
            docInfo["artboard_count"] = 1;
            resp["document"] = docInfo;

            // Selected art
            json selectedArr = json::array();
            int selectedCount = 0;

            // Check all art types for selection (not just paths)
            short artTypes[] = {kPathArt, kGroupArt, kPlacedArt, kCompoundPathArt, kTextFrameArt};
            const char* typeNames[] = {"path", "group", "placed", "compound_path", "text_frame"};

            for (int t = 0; t < 5; t++) {
                AIMatchingArtSpec spec;
                spec.type = artTypes[t];
                spec.whichAttr = kArtSelected;
                spec.attr = kArtSelected;

                AIArtHandle** matches = nullptr;
                ai::int32 numMatches = 0;
                ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
                if (err != kNoErr || numMatches == 0) continue;

                for (ai::int32 i = 0; i < numMatches; i++) {
                    AIArtHandle art = (*matches)[i];
                    json artObj;
                    artObj["type"] = typeNames[t];

                    // Name
                    ai::UnicodeString artName;
                    AIBoolean isDefaultName = true;
                    if (sAIArt->GetArtName(art, artName, &isDefaultName) == kNoErr && !isDefaultName) {
                        std::string nameStr;
                        nameStr = artName.as_UTF8();
                        artObj["name"] = nameStr;
                    } else {
                        artObj["name"] = nullptr;
                    }

                    // Bounds
                    AIRealRect bounds;
                    if (sAIArt->GetArtBounds(art, &bounds) == kNoErr) {
                        artObj["bounds"] = {
                            {"left",   (double)bounds.left},
                            {"top",    (double)bounds.top},
                            {"right",  (double)bounds.right},
                            {"bottom", (double)bounds.bottom}
                        };
                    }

                    // Segment count for paths
                    if (artTypes[t] == kPathArt) {
                        ai::int16 segCount = 0;
                        sAIPath->GetPathSegmentCount(art, &segCount);
                        artObj["segments"] = (int)segCount;

                        AIBoolean closed = false;
                        sAIPath->GetPathClosed(art, &closed);
                        artObj["closed"] = (bool)closed;
                    }

                    selectedArr.push_back(artObj);
                    selectedCount++;
                }
                sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            }

            resp["selected_count"] = selectedCount;
            resp["selected"] = selectedArr;

            fprintf(stderr, "[IllTool MCP] /api/inspect: %d selected items\n", selectedCount);
            break;
        }

        //----------------------------------------------------------------
        //  McpCreatePath — create path from point array
        //----------------------------------------------------------------
        case OpType::McpCreatePath: {
            json body = json::parse(op.strParam);
            auto& pointsArr = body["points"];
            bool closed = body.value("closed", false);

            int n = (int)pointsArr.size();
            if (n < 2) {
                resp["ok"] = false;
                resp["error"] = "Need at least 2 points";
                break;
            }

            // Create the path art
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (err != kNoErr || !newPath) {
                resp["ok"] = false;
                resp["error"] = "NewArt failed";
                break;
            }

            // Build segments
            std::vector<AIPathSegment> segs(n);
            for (int i = 0; i < n; i++) {
                double x = pointsArr[i][0].get<double>();
                double y = pointsArr[i][1].get<double>();
                segs[i].p.h = (AIReal)x;
                segs[i].p.v = (AIReal)y;
                segs[i].in  = segs[i].p;   // corner points (no handles)
                segs[i].out = segs[i].p;
                segs[i].corner = true;
            }

            sAIPath->SetPathSegmentCount(newPath, (ai::int16)n);
            sAIPath->SetPathSegments(newPath, 0, (ai::int16)n, segs.data());
            sAIPath->SetPathClosed(newPath, closed);

            // Apply stroke/fill style
            AIPathStyle style;
            memset(&style, 0, sizeof(style));
            style.stroke.miterLimit = (AIReal)4.0;  // Illustrator default

            // Stroke
            bool hasStroke = true;  // default: stroke on
            double strokeR = body.value("stroke_r", 0.0) / 255.0;
            double strokeG = body.value("stroke_g", 0.0) / 255.0;
            double strokeB = body.value("stroke_b", 0.0) / 255.0;
            double strokeW = body.value("stroke_width", 1.0);

            style.strokePaint = hasStroke;
            style.stroke.width = (AIReal)strokeW;
            style.stroke.color.kind = kThreeColor;
            style.stroke.color.c.rgb.red   = (AIReal)strokeR;
            style.stroke.color.c.rgb.green = (AIReal)strokeG;
            style.stroke.color.c.rgb.blue  = (AIReal)strokeB;

            // Fill (optional — null means no fill)
            if (body.contains("fill_r") && !body["fill_r"].is_null()) {
                style.fillPaint = true;
                style.fill.color.kind = kThreeColor;
                style.fill.color.c.rgb.red   = (AIReal)(body["fill_r"].get<double>() / 255.0);
                style.fill.color.c.rgb.green = (AIReal)(body["fill_g"].get<double>() / 255.0);
                style.fill.color.c.rgb.blue  = (AIReal)(body["fill_b"].get<double>() / 255.0);
            } else {
                style.fillPaint = false;
            }

            sAIPathStyle->SetPathStyle(newPath, &style);

            // Name (optional)
            if (body.contains("name") && body["name"].is_string()) {
                std::string name = body["name"].get<std::string>();
                sAIArt->SetArtName(newPath, ai::UnicodeString(name));
            }

            // Select the new path
            sAIArt->SetArtUserAttr(newPath, kArtSelected, kArtSelected);
            if (sAIDocument) sAIDocument->RedrawDocument();

            resp["ok"] = true;
            resp["segments"] = n;
            fprintf(stderr, "[IllTool MCP] /api/create_path: %d segments, closed=%d\n", n, (int)closed);
            break;
        }

        //----------------------------------------------------------------
        //  McpCreateShape — create rectangle or ellipse
        //----------------------------------------------------------------
        case OpType::McpCreateShape: {
            json body = json::parse(op.strParam);
            std::string shape = body.value("shape", "rectangle");
            double x = body.value("x", 0.0);
            double y = body.value("y", 0.0);
            double w = body.value("width", 100.0);
            double h = body.value("height", 100.0);

            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (err != kNoErr || !newPath) {
                resp["ok"] = false;
                resp["error"] = "NewArt failed";
                break;
            }

            if (shape == "rectangle") {
                // 4 corner points: top-left, top-right, bottom-right, bottom-left
                // AI coordinate system: Y increases upward, so top > bottom
                AIPathSegment segs[4];
                segs[0].p = {(AIReal)x,       (AIReal)y};
                segs[1].p = {(AIReal)(x + w),  (AIReal)y};
                segs[2].p = {(AIReal)(x + w),  (AIReal)(y - h)};
                segs[3].p = {(AIReal)x,        (AIReal)(y - h)};
                for (int i = 0; i < 4; i++) {
                    segs[i].in  = segs[i].p;
                    segs[i].out = segs[i].p;
                    segs[i].corner = true;
                }
                sAIPath->SetPathSegmentCount(newPath, 4);
                sAIPath->SetPathSegments(newPath, 0, 4, segs);
                sAIPath->SetPathClosed(newPath, true);
            } else {
                // Ellipse: 4 bezier points approximating an ellipse
                // Standard bezier circle constant: kappa = 4*(sqrt(2)-1)/3 ~ 0.5522847498
                const double kappa = 0.5522847498;
                double cx = x + w / 2.0;
                double cy = y - h / 2.0;
                double rx = w / 2.0;
                double ry = h / 2.0;

                AIPathSegment segs[4];
                // Top
                segs[0].p   = {(AIReal)cx,              (AIReal)(cy + ry)};
                segs[0].in  = {(AIReal)(cx + rx*kappa),  (AIReal)(cy + ry)};
                segs[0].out = {(AIReal)(cx - rx*kappa),  (AIReal)(cy + ry)};
                segs[0].corner = false;
                // Left
                segs[1].p   = {(AIReal)(cx - rx),        (AIReal)cy};
                segs[1].in  = {(AIReal)(cx - rx),        (AIReal)(cy + ry*kappa)};
                segs[1].out = {(AIReal)(cx - rx),        (AIReal)(cy - ry*kappa)};
                segs[1].corner = false;
                // Bottom
                segs[2].p   = {(AIReal)cx,              (AIReal)(cy - ry)};
                segs[2].in  = {(AIReal)(cx - rx*kappa),  (AIReal)(cy - ry)};
                segs[2].out = {(AIReal)(cx + rx*kappa),  (AIReal)(cy - ry)};
                segs[2].corner = false;
                // Right
                segs[3].p   = {(AIReal)(cx + rx),        (AIReal)cy};
                segs[3].in  = {(AIReal)(cx + rx),        (AIReal)(cy - ry*kappa)};
                segs[3].out = {(AIReal)(cx + rx),        (AIReal)(cy + ry*kappa)};
                segs[3].corner = false;

                sAIPath->SetPathSegmentCount(newPath, 4);
                sAIPath->SetPathSegments(newPath, 0, 4, segs);
                sAIPath->SetPathClosed(newPath, true);
            }

            // Style
            AIPathStyle style;
            memset(&style, 0, sizeof(style));

            if (body.contains("fill_r") && !body["fill_r"].is_null()) {
                style.fillPaint = true;
                style.fill.color.kind = kThreeColor;
                style.fill.color.c.rgb.red   = (AIReal)(body.value("fill_r", 0.0) / 255.0);
                style.fill.color.c.rgb.green = (AIReal)(body.value("fill_g", 0.0) / 255.0);
                style.fill.color.c.rgb.blue  = (AIReal)(body.value("fill_b", 0.0) / 255.0);
            } else {
                style.fillPaint = false;
            }

            if (body.contains("stroke_r") && !body["stroke_r"].is_null()) {
                style.strokePaint = true;
                style.stroke.width = (AIReal)body.value("stroke_width", 1.0);
                style.stroke.color.kind = kThreeColor;
                style.stroke.color.c.rgb.red   = (AIReal)(body.value("stroke_r", 0.0) / 255.0);
                style.stroke.color.c.rgb.green = (AIReal)(body.value("stroke_g", 0.0) / 255.0);
                style.stroke.color.c.rgb.blue  = (AIReal)(body.value("stroke_b", 0.0) / 255.0);
            } else {
                style.strokePaint = true;
                style.stroke.width = (AIReal)1.0;
                style.stroke.color.kind = kThreeColor;
                style.stroke.color.c.rgb.red   = 0;
                style.stroke.color.c.rgb.green = 0;
                style.stroke.color.c.rgb.blue  = 0;
            }

            sAIPathStyle->SetPathStyle(newPath, &style);

            // Name (optional)
            if (body.contains("name") && body["name"].is_string()) {
                sAIArt->SetArtName(newPath, ai::UnicodeString(body["name"].get<std::string>()));
            }

            sAIArt->SetArtUserAttr(newPath, kArtSelected, kArtSelected);
            if (sAIDocument) sAIDocument->RedrawDocument();

            resp["ok"] = true;
            resp["shape"] = shape;
            fprintf(stderr, "[IllTool MCP] /api/create_shape: %s at (%.0f,%.0f) %.0fx%.0f\n",
                    shape.c_str(), x, y, w, h);
            break;
        }

        //----------------------------------------------------------------
        //  McpLayers — list, create, or rename layers
        //----------------------------------------------------------------
        case OpType::McpLayers: {
            json body = json::parse(op.strParam);
            std::string action = body.value("action", "list");

            if (action == "list") {
                json layersArr = json::array();
                if (sAILayer) {
                    ai::int32 layerCount = 0;
                    sAILayer->CountLayers(&layerCount);
                    for (ai::int32 i = 0; i < layerCount; i++) {
                        AILayerHandle layer = nullptr;
                        if (sAILayer->GetNthLayer(i, &layer) != kNoErr) continue;

                        json layerObj;
                        ai::UnicodeString title;
                        sAILayer->GetLayerTitle(layer, title);
                        std::string titleStr;
                        titleStr = title.as_UTF8();
                        layerObj["name"] = titleStr;
                        layerObj["index"] = (int)i;

                        AIBoolean visible = true, editable = true;
                        sAILayer->GetLayerVisible(layer, &visible);
                        sAILayer->GetLayerEditable(layer, &editable);
                        layerObj["visible"]  = (bool)visible;
                        layerObj["editable"] = (bool)editable;

                        layersArr.push_back(layerObj);
                    }
                }
                resp["ok"] = true;
                resp["layers"] = layersArr;
                resp["count"] = (int)layersArr.size();
                fprintf(stderr, "[IllTool MCP] /api/layers list: %d layers\n", (int)layersArr.size());
            }
            else if (action == "create") {
                std::string name = body.value("name", "New Layer");
                if (sAILayer) {
                    AILayerHandle newLayer = nullptr;
                    ASErr err = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &newLayer);
                    if (err == kNoErr && newLayer) {
                        ai::UnicodeString uName(name);
                        sAILayer->SetLayerTitle(newLayer, uName);
                        resp["ok"] = true;
                        resp["name"] = name;
                        fprintf(stderr, "[IllTool MCP] /api/layers create: '%s'\n", name.c_str());
                    } else {
                        resp["ok"] = false;
                        resp["error"] = "InsertLayer failed";
                    }
                } else {
                    resp["ok"] = false;
                    resp["error"] = "AILayerSuite not available";
                }
            }
            else if (action == "rename") {
                std::string name = body.value("name", "");
                std::string newName = body.value("new_name", "");
                if (name.empty() || newName.empty()) {
                    resp["ok"] = false;
                    resp["error"] = "Both 'name' and 'new_name' required";
                    break;
                }
                if (sAILayer) {
                    AILayerHandle layer = nullptr;
                    ai::UnicodeString uName(name);
                    ASErr err = sAILayer->GetLayerByTitle(&layer, uName);
                    if (err == kNoErr && layer) {
                        ai::UnicodeString uNewName(newName);
                        sAILayer->SetLayerTitle(layer, uNewName);
                        resp["ok"] = true;
                        resp["old_name"] = name;
                        resp["new_name"] = newName;
                        fprintf(stderr, "[IllTool MCP] /api/layers rename: '%s' -> '%s'\n",
                                name.c_str(), newName.c_str());
                    } else {
                        resp["ok"] = false;
                        resp["error"] = "Layer not found: " + name;
                    }
                } else {
                    resp["ok"] = false;
                    resp["error"] = "AILayerSuite not available";
                }
            }
            break;
        }

        //----------------------------------------------------------------
        //  McpSelect — select art by criteria
        //----------------------------------------------------------------
        case OpType::McpSelect: {
            json body = json::parse(op.strParam);
            std::string action = body.value("action", "none");
            int affected = 0;

            if (action == "none") {
                // Deselect all — iterate all art types and clear selection
                short artTypes[] = {kPathArt, kGroupArt, kPlacedArt, kCompoundPathArt, kTextFrameArt};
                for (int t = 0; t < 5; t++) {
                    AIMatchingArtSpec spec;
                    spec.type = artTypes[t];
                    spec.whichAttr = kArtSelected;
                    spec.attr = kArtSelected;
                    AIArtHandle** matches = nullptr;
                    ai::int32 numMatches = 0;
                    if (GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
                        for (ai::int32 i = 0; i < numMatches; i++) {
                            sAIArt->SetArtUserAttr((*matches)[i], kArtSelected, 0);
                            affected++;
                        }
                        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                    }
                }
                resp["ok"] = true;
                resp["deselected"] = affected;
            }
            else if (action == "all") {
                // Select all visible/unlocked path art
                AIMatchingArtSpec spec;
                spec.type = kPathArt;
                spec.whichAttr = 0;
                spec.attr = 0;
                AIArtHandle** matches = nullptr;
                ai::int32 numMatches = 0;
                if (GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
                    for (ai::int32 i = 0; i < numMatches; i++) {
                        ai::int32 attrs = 0;
                        sAIArt->GetArtUserAttr((*matches)[i], kArtLocked | kArtHidden, &attrs);
                        if (attrs & (kArtLocked | kArtHidden)) continue;
                        sAIArt->SetArtUserAttr((*matches)[i], kArtSelected, kArtSelected);
                        affected++;
                    }
                    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                }
                resp["ok"] = true;
                resp["selected"] = affected;
            }
            else if (action == "by_name") {
                std::string targetName = body.value("name", "");
                if (targetName.empty()) {
                    resp["ok"] = false;
                    resp["error"] = "'name' required for by_name selection";
                    break;
                }
                // Search all art types
                short artTypes[] = {kPathArt, kGroupArt, kPlacedArt, kCompoundPathArt, kTextFrameArt};
                for (int t = 0; t < 5; t++) {
                    AIMatchingArtSpec spec;
                    spec.type = artTypes[t];
                    spec.whichAttr = 0;
                    spec.attr = 0;
                    AIArtHandle** matches = nullptr;
                    ai::int32 numMatches = 0;
                    if (GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
                        for (ai::int32 i = 0; i < numMatches; i++) {
                            ai::UnicodeString artName;
                            AIBoolean isDefault = true;
                            sAIArt->GetArtName((*matches)[i], artName, &isDefault);
                            if (!isDefault) {
                                std::string nameStr;
                                nameStr = artName.as_UTF8();
                                if (nameStr == targetName) {
                                    sAIArt->SetArtUserAttr((*matches)[i], kArtSelected, kArtSelected);
                                    affected++;
                                }
                            }
                        }
                        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                    }
                }
                resp["ok"] = true;
                resp["selected"] = affected;
            }
            else if (action == "by_type") {
                std::string typeName = body.value("type", "path");
                short artType = kPathArt;
                if (typeName == "group") artType = kGroupArt;
                else if (typeName == "placed") artType = kPlacedArt;
                else if (typeName == "compound_path") artType = kCompoundPathArt;
                else if (typeName == "text_frame") artType = kTextFrameArt;

                AIMatchingArtSpec spec;
                spec.type = artType;
                spec.whichAttr = 0;
                spec.attr = 0;
                AIArtHandle** matches = nullptr;
                ai::int32 numMatches = 0;
                if (GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
                    for (ai::int32 i = 0; i < numMatches; i++) {
                        ai::int32 attrs = 0;
                        sAIArt->GetArtUserAttr((*matches)[i], kArtLocked | kArtHidden, &attrs);
                        if (attrs & (kArtLocked | kArtHidden)) continue;
                        sAIArt->SetArtUserAttr((*matches)[i], kArtSelected, kArtSelected);
                        affected++;
                    }
                    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                }
                resp["ok"] = true;
                resp["selected"] = affected;
            }

            fprintf(stderr, "[IllTool MCP] /api/select %s: %d affected\n", action.c_str(), affected);
            break;
        }

        //----------------------------------------------------------------
        //  McpModify — transform/style/delete selected art
        //----------------------------------------------------------------
        case OpType::McpModify: {
            json body = json::parse(op.strParam);
            std::string action = body.value("action", "");
            int modified = 0;

            // Get selected art (paths, groups, placed, etc.)
            short artTypes[] = {kPathArt, kGroupArt, kPlacedArt, kCompoundPathArt};
            std::vector<AIArtHandle> selectedArt;
            for (int t = 0; t < 4; t++) {
                AIMatchingArtSpec spec;
                spec.type = artTypes[t];
                spec.whichAttr = kArtSelected;
                spec.attr = kArtSelected;
                AIArtHandle** matches = nullptr;
                ai::int32 numMatches = 0;
                if (GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
                    for (ai::int32 i = 0; i < numMatches; i++) {
                        selectedArt.push_back((*matches)[i]);
                    }
                    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                }
            }

            if (selectedArt.empty()) {
                resp["ok"] = true;
                resp["modified"] = 0;
                resp["message"] = "No art selected";
                break;
            }

            if (action == "move") {
                double dx = body.value("dx", 0.0);
                double dy = body.value("dy", 0.0);
                for (auto art : selectedArt) {
                    short artType = kAnyArt;
                    sAIArt->GetArtType(art, &artType);
                    if (artType == kPathArt) {
                        ai::int16 segCount = 0;
                        sAIPath->GetPathSegmentCount(art, &segCount);
                        if (segCount == 0) continue;
                        std::vector<AIPathSegment> segs(segCount);
                        sAIPath->GetPathSegments(art, 0, segCount, segs.data());
                        for (auto& seg : segs) {
                            seg.p.h   += (AIReal)dx;  seg.p.v   += (AIReal)dy;
                            seg.in.h  += (AIReal)dx;  seg.in.v  += (AIReal)dy;
                            seg.out.h += (AIReal)dx;  seg.out.v += (AIReal)dy;
                        }
                        sAIPath->SetPathSegments(art, 0, segCount, segs.data());
                        modified++;
                    }
                    // For non-path art, we would need AITransformArtSuite which we may not have.
                    // For now, only path art is transformed at the segment level.
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "scale") {
                double sx = body.value("sx", 1.0);
                double sy = body.value("sy", 1.0);
                for (auto art : selectedArt) {
                    short artType = kAnyArt;
                    sAIArt->GetArtType(art, &artType);
                    if (artType != kPathArt) continue;

                    AIRealRect bounds;
                    sAIArt->GetArtBounds(art, &bounds);
                    double cx = (bounds.left + bounds.right) / 2.0;
                    double cy = (bounds.top + bounds.bottom) / 2.0;

                    ai::int16 segCount = 0;
                    sAIPath->GetPathSegmentCount(art, &segCount);
                    if (segCount == 0) continue;
                    std::vector<AIPathSegment> segs(segCount);
                    sAIPath->GetPathSegments(art, 0, segCount, segs.data());
                    for (auto& seg : segs) {
                        auto scalePoint = [&](AIRealPoint& pt) {
                            pt.h = (AIReal)(cx + (pt.h - cx) * sx);
                            pt.v = (AIReal)(cy + (pt.v - cy) * sy);
                        };
                        scalePoint(seg.p);
                        scalePoint(seg.in);
                        scalePoint(seg.out);
                    }
                    sAIPath->SetPathSegments(art, 0, segCount, segs.data());
                    modified++;
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "rotate") {
                double degrees = body.value("degrees", 0.0);
                double rad = degrees * M_PI / 180.0;
                double cosA = std::cos(rad);
                double sinA = std::sin(rad);
                for (auto art : selectedArt) {
                    short artType = kAnyArt;
                    sAIArt->GetArtType(art, &artType);
                    if (artType != kPathArt) continue;

                    AIRealRect bounds;
                    sAIArt->GetArtBounds(art, &bounds);
                    double cx = (bounds.left + bounds.right) / 2.0;
                    double cy = (bounds.top + bounds.bottom) / 2.0;

                    ai::int16 segCount = 0;
                    sAIPath->GetPathSegmentCount(art, &segCount);
                    if (segCount == 0) continue;
                    std::vector<AIPathSegment> segs(segCount);
                    sAIPath->GetPathSegments(art, 0, segCount, segs.data());
                    for (auto& seg : segs) {
                        auto rotatePoint = [&](AIRealPoint& pt) {
                            double dx = pt.h - cx;
                            double dy = pt.v - cy;
                            pt.h = (AIReal)(cx + dx * cosA - dy * sinA);
                            pt.v = (AIReal)(cy + dx * sinA + dy * cosA);
                        };
                        rotatePoint(seg.p);
                        rotatePoint(seg.in);
                        rotatePoint(seg.out);
                    }
                    sAIPath->SetPathSegments(art, 0, segCount, segs.data());
                    modified++;
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "set_stroke") {
                double r = body.value("r", 0.0) / 255.0;
                double g = body.value("g", 0.0) / 255.0;
                double b = body.value("b", 0.0) / 255.0;
                double w = body.value("width", 1.0);
                for (auto art : selectedArt) {
                    short artType = kAnyArt;
                    sAIArt->GetArtType(art, &artType);
                    if (artType != kPathArt) continue;

                    AIPathStyle style;
                    AIBoolean hasAdvFill = false;
                    if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr) {
                        style.strokePaint = true;
                        style.stroke.width = (AIReal)w;
                        style.stroke.color.kind = kThreeColor;
                        style.stroke.color.c.rgb.red   = (AIReal)r;
                        style.stroke.color.c.rgb.green = (AIReal)g;
                        style.stroke.color.c.rgb.blue  = (AIReal)b;
                        sAIPathStyle->SetPathStyle(art, &style);
                        modified++;
                    }
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "set_fill") {
                bool removeFill = body.value("none", false);
                for (auto art : selectedArt) {
                    short artType = kAnyArt;
                    sAIArt->GetArtType(art, &artType);
                    if (artType != kPathArt) continue;

                    AIPathStyle style;
                    AIBoolean hasAdvFill = false;
                    if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr) {
                        if (removeFill) {
                            style.fillPaint = false;
                        } else {
                            style.fillPaint = true;
                            style.fill.color.kind = kThreeColor;
                            style.fill.color.c.rgb.red   = (AIReal)(body.value("r", 0.0) / 255.0);
                            style.fill.color.c.rgb.green = (AIReal)(body.value("g", 0.0) / 255.0);
                            style.fill.color.c.rgb.blue  = (AIReal)(body.value("b", 0.0) / 255.0);
                        }
                        sAIPathStyle->SetPathStyle(art, &style);
                        modified++;
                    }
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "set_name") {
                std::string name = body.value("name", "");
                for (auto art : selectedArt) {
                    sAIArt->SetArtName(art, ai::UnicodeString(name));
                    modified++;
                }
                resp["ok"] = true;
                resp["modified"] = modified;
            }
            else if (action == "delete") {
                // Deduplicate handles to prevent double-dispose
                // (same art can appear via multiple type queries or parent/child)
                std::set<AIArtHandle> unique(selectedArt.begin(), selectedArt.end());
                // Delete in reverse order of insertion (top-level first)
                std::vector<AIArtHandle> deduped(unique.begin(), unique.end());
                for (int i = (int)deduped.size() - 1; i >= 0; i--) {
                    short artType = 0;
                    ASErr dispErr = sAIArt->GetArtType(deduped[i], &artType);
                    if (dispErr == kNoErr) {
                        sAIArt->DisposeArt(deduped[i]);
                        modified++;
                    }
                }
                resp["ok"] = true;
                resp["deleted"] = modified;
            }

            if (modified > 0 && sAIDocument) {
                sAIDocument->RedrawDocument();
            }
            fprintf(stderr, "[IllTool MCP] /api/modify %s: %d modified\n", action.c_str(), modified);
            break;
        }

        default:
            resp["ok"] = false;
            resp["error"] = "Unknown MCP operation type";
            break;
        }
    }
    catch (const std::exception& e) {
        resp["ok"] = false;
        resp["error"] = std::string("SDK error: ") + e.what();
        fprintf(stderr, "[IllTool MCP] Exception: %s\n", e.what());
    }
    catch (...) {
        resp["ok"] = false;
        resp["error"] = "Unknown SDK error";
        fprintf(stderr, "[IllTool MCP] Unknown exception\n");
    }

    // Post the result back to the waiting HTTP thread
    BridgeMcpPostResponse(resp.dump());
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

        // Set cursor — context-dependent:
        //   Working mode + rotate zone → cross cursor (rotation)
        //   Working mode + Option held → IBeam cursor (add point affordance)
        //   Working mode + Shift held → cross cursor (toggle sharp/smooth)
        //   Working mode default → arrow cursor (handle editing)
        //   Perspective edit mode → arrow cursor
        //   Otherwise → custom lasso SVG cursor
        if (sAIUser != NULL) {
            // Check modifier keys via Cocoa (always available, unlike AIEvent)
            NSUInteger modFlags = [NSEvent modifierFlags];
            bool optionHeld = (modFlags & NSEventModifierFlagOption) != 0;
            bool shiftHeld  = (modFlags & NSEventModifierFlagShift) != 0;

            int cursorID = -1;  // -1 = use SVG cursor

            if (cleanup && cleanup->IsInWorkingMode()) {
                if (cleanup->fHoverBBoxIdx == 8) {
                    cursorID = kAICrossCursorID;   // rotate zone
                } else if (optionHeld) {
                    cursorID = kAIIBeamCursorID;   // add point (pen+ affordance)
                } else if (shiftHeld) {
                    cursorID = kAICrossCursorID;   // toggle sharp/smooth
                } else {
                    cursorID = kAIArrowCursorID;   // handle editing
                }
            }

            // Blend pick mode — custom SVG cursor with A/B badge
            if (cursorID < 0) {
                int blendPick = BridgeGetBlendPickMode();
                if (blendPick == 1) {
                    sAIUser->SetSVGCursor(kIllToolPickACursorID, fResourceManagerHandle);
                    cursorID = -2;  // sentinel: SVG cursor already set
                } else if (blendPick == 2) {
                    sAIUser->SetSVGCursor(kIllToolPickBCursorID, fResourceManagerHandle);
                    cursorID = -2;  // sentinel: SVG cursor already set
                }
            }

            // Surface extract mode — crosshair cursor
            if (cursorID < 0 && BridgeGetSurfaceExtractMode()) {
                cursorID = kAICrossCursorID;
            }

            // Shading eyedropper mode
            if (cursorID < 0 && BridgeGetShadingEyedropperMode()) {
                cursorID = kAIIBeamCursorID;  // eyedropper-like
            }

            // Show arrow when in perspective edit mode
            if (cursorID < 0) {
                auto* persp = GetModule<PerspectiveModule>();
                if (persp && persp->IsInEditMode()) cursorID = kAIArrowCursorID;
            }

            if (cursorID == -2) {
                // SVG cursor already set above (blend pick A/B)
            } else if (cursorID >= 0) {
                sAIUser->SetCursor(cursorID, fResourceManagerHandle);
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

        // Clear drag-in-progress flag — tool switch can interrupt a drag
        fDragInProgress = false;

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

        // Toggle Perspective Lock (shortcut: Shift+Cmd+P)
        itemData.itemText = ai::UnicodeString("Toggle Perspective Lock");
        result = sAIMenu->AddMenuItem(message->d.self, kIllToolMenuPerspToggleItem,
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fMenuPerspToggleHandle);
        if (result == kNoErr) {
            // Assign Cmd+Shift+P as default shortcut
            sAIMenu->SetItemCmd(fMenuPerspToggleHandle, 'P', kMenuItemCmdShiftModifier);
        }

        // Transform All
        itemData.itemText = ai::UnicodeString("Transform All");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Transform",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fTransformMenuHandle);

        // Ill Trace
        itemData.itemText = ai::UnicodeString("Ill Trace");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Trace",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fTraceMenuHandle);

        // Ill Surface
        itemData.itemText = ai::UnicodeString("Ill Surface");
        result = sAIMenu->AddMenuItem(message->d.self, "IllTool Menu Surface",
                                       &itemData, kMenuItemWantsUpdateOption,
                                       &fSurfaceMenuHandle);

        // Step 5: Assign default keyboard shortcuts
        // All shortcuts use Cmd+Shift+key (kMenuItemCmdShiftModifier = Cmd is implied).
        // These appear in Edit > Keyboard Shortcuts and can be customized by the user.
        if (fMenuLassoHandle)  sAIMenu->SetItemCmd(fMenuLassoHandle, 'L', kMenuItemCmdShiftModifier);
        if (fMenuSmartHandle)  sAIMenu->SetItemCmd(fMenuSmartHandle, 'J', kMenuItemCmdShiftModifier);

        fprintf(stderr, "[IllTool] AddAppMenu: submenu registered with shortcuts\n");
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
