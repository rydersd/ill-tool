//========================================================================================
//
//  IllTool Plugin — Main plugin class (thin router)
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Routes operations, mouse events, and draw calls to feature modules.
//  Owns: SDK handles, panel refs, module vector, lifecycle.
//
//========================================================================================

#ifndef __ILLTOOLPLUGIN_H__
#define __ILLTOOLPLUGIN_H__

#include "IllToolID.h"
#include "SDKDef.h"
#include "SDKAboutPluginsHelper.h"
#include "AIAnnotator.h"
#include "AIPanel.h"
#include "AIMenu.h"
#include "IllToolSuites.h"
#include "IllToolAnnotator.h"
#include "DrawCommands.h"
#include "HttpBridge.h"
#include "SDKErrors.h"
#include "AITimer.h"
#include "IllToolModule.h"

#include <vector>
#include <memory>
#include <atomic>

/** Creates a new IllToolPlugin.
    @param pluginRef IN unique reference to this plugin.
    @return pointer to new IllToolPlugin.
*/
Plugin* AllocatePlugin(SPPluginRef pluginRef);

/** Isolation-aware art matching: scopes GetMatchingArt to the isolated
    art tree (or working group) when in isolation mode.
    Defined in IllToolPlugin.cpp, used by multiple extracted modules. */
ASErr GetMatchingArtIsolationAware(
    AIMatchingArtSpec* spec, ai::int16 numSpecs,
    AIArtHandle*** matches, ai::int32* numMatches);

/** C-callable function to average selected anchor points.
    PCA sort -> classify -> LOD -> preview. Full CEP pipeline.
    Called from the Cleanup panel's "Average Selection" button. */
void PluginAverageSelection();

/** C-callable function to count currently selected anchor points.
    Iterates all path art and counts segments where the anchor is selected.
    Fast -- no allocations, just counting.  Safe to call from NSTimer on main thread. */
extern "C" int PluginGetSelectedAnchorCount();

/** C-callable wrappers for the working mode workflow.
    Called from CleanupPanelController Apply/Cancel buttons and HTTP endpoints. */
extern "C" void PluginApplyWorkingMode(bool deleteOriginals);
extern "C" void PluginCancelWorkingMode();

/** Reloads the IllToolPlugin class state when the plugin is
    reloaded by the application.
    @param plugin IN pointer to plugin being reloaded.
*/
void FixupReload(Plugin* plugin);

/** IllTool Overlay plugin — thin router.
    Owns SDK handles and module vector. Routes operations, mouse events,
    and draw calls to feature modules. No feature logic lives here.
*/
class IllToolPlugin : public Plugin
{
private:
    //------------------------------------------------------------------------------------
    //  SDK handles
    //------------------------------------------------------------------------------------

    /** Handle for the IllTool Handle tool. */
    AIToolHandle            fToolHandle;

    /** Handle for the IllTool Perspective tool (separate tool in the same toolbox group). */
    AIToolHandle            fPerspectiveToolHandle;

    /** Handle for the IllTool Pen tool (drawing tool). */
    AIToolHandle            fPenToolHandle;

    /** Handle for the About SDK Plug-ins menu item. */
    AIMenuItemHandle        fAboutPluginMenu;

    /** Handle for the annotator added by this plug-in. */
    AIAnnotatorHandle       fAnnotatorHandle;

    /** Handle for the selection changed notifier. */
    AINotifierHandle        fNotifySelectionChanged;

    /** Handle for illustrator shutdown notifier. */
    AINotifierHandle        fShutdownApplicationNotifier;

    /** Handle for effective tool changed notifier (space-to-pan cursor restore). */
    AINotifierHandle        fEffectiveToolChangedNotifier;

    /** Handle for document changed notifier (clear per-doc state on switch). */
    AINotifierHandle        fDocumentChangedNotifier;

    /** Pointer to IllToolAnnotator object. */
    IllToolAnnotator*       fAnnotator;

    /** Handle for the resource manager used for tool cursor. */
    AIResourceManagerHandle fResourceManagerHandle;

    /** Handle for the operation dispatch timer (AITimerSuite). */
    AITimerHandle           fOperationTimer;

    //------------------------------------------------------------------------------------
    //  Panel state
    //------------------------------------------------------------------------------------

    /** Panel refs for the tool panels. */
    AIPanelRef              fSelectionPanel;
    AIPanelRef              fCleanupPanel;
    AIPanelRef              fGroupingPanel;
    AIPanelRef              fMergePanel;
    AIPanelRef              fShadingPanel;
    AIPanelRef              fBlendPanel;
    AIPanelRef              fPerspectivePanel;
    AIPanelRef              fTransformPanel;
    AIPanelRef              fTracePanel;
    AIPanelRef              fSurfacePanel;
    AIPanelRef              fPenPanel;
    AIPanelRef              fLayerPanel;

    /** Menu item handles for panel show/hide in Window menu. */
    AIMenuItemHandle        fSelectionMenuHandle;
    AIMenuItemHandle        fCleanupMenuHandle;
    AIMenuItemHandle        fGroupingMenuHandle;
    AIMenuItemHandle        fMergeMenuHandle;
    AIMenuItemHandle        fShadingMenuHandle;
    AIMenuItemHandle        fBlendMenuHandle;
    AIMenuItemHandle        fPerspectiveMenuHandle;
    AIMenuItemHandle        fTransformMenuHandle;
    AIMenuItemHandle        fTraceMenuHandle;
    AIMenuItemHandle        fSurfaceMenuHandle;
    AIMenuItemHandle        fPenMenuHandle;
    AIMenuItemHandle        fLayerMenuHandle;

    //------------------------------------------------------------------------------------
    //  Application menu (Window > IllTool submenu)
    //------------------------------------------------------------------------------------

    /** Root menu item that appears as "IllTool" in the Window menu. */
    AIMenuItemHandle        fAppMenuRootHandle;

    /** Menu items inside the IllTool submenu. */
    AIMenuItemHandle        fMenuLassoHandle;     // Polygon Lasso (activates tool)
    AIMenuItemHandle        fMenuSmartHandle;     // Smart Select  (activates tool in smart mode)
    AIMenuItemHandle        fMenuCleanupHandle;   // Shape Cleanup  (toggle panel)
    AIMenuItemHandle        fMenuGroupingHandle;  // Grouping Tools (toggle panel)
    AIMenuItemHandle        fMenuMergeHandle;     // Smart Merge    (toggle panel)
    AIMenuItemHandle        fMenuSelectionHandle; // Selection Panel (toggle panel)
    AIMenuItemHandle        fMenuPerspToggleHandle; // Toggle Perspective lock

    //------------------------------------------------------------------------------------
    //  Isolation mode lock notifier
    //------------------------------------------------------------------------------------

    /** Handle for isolation-mode-changed notifier (locked isolation mode). */
    AINotifierHandle        fIsolationChangedNotifier;

    /** Opaque pointers to Objective-C panel controllers (cast in .mm code). */
    void*                   fSelectionController;
    void*                   fCleanupController;
    void*                   fGroupingController;
    void*                   fMergeController;
    void*                   fShadingController;
    void*                   fBlendController;
    void*                   fPerspectiveController;
    void*                   fTransformController;
    void*                   fTraceController;
    void*                   fSurfaceController;
    void*                   fPenController;
    void*                   fLayerController;

    //------------------------------------------------------------------------------------
    //  Module system
    //------------------------------------------------------------------------------------

    /** Feature modules — each owns its own state and handles its own operations. */
    std::vector<std::unique_ptr<IllToolModule>> fModules;

public:
    /** Get a specific module by type. Returns nullptr if not found. */
    template<typename T>
    T* GetModule() {
        for (auto& mod : fModules) {
            T* typed = dynamic_cast<T*>(mod.get());
            if (typed) return typed;
        }
        return nullptr;
    }

    /** Cached selection count -- updated from Notify (where SDK calls work).
        Public so PluginGetSelectedAnchorCount() can read it. */
    std::atomic<int>        fLastKnownSelectionCount{0};

    /** True while a mouse drag is in progress. Prevents ProcessOperationQueue
        from dequeueing WorkingApply/Cancel mid-drag (timer-race). */
    std::atomic<bool>       fDragInProgress{false};

    /** Returns the perspective tool handle (for panel tool activation). */
    AIToolHandle GetPerspectiveToolHandle() const { return fPerspectiveToolHandle; }

    /** Constructor. */
    IllToolPlugin(SPPluginRef pluginRef);

    /** Destructor. */
    virtual ~IllToolPlugin() {}

    /** Restores state of IllToolPlugin during reload. */
    FIXUP_VTABLE_EX(IllToolPlugin, Plugin);

public:
    /** Update a panel's Window menu checkmark when visibility changes. */
    void UpdatePanelMenu(AIPanelRef panel, AIBoolean isVisible);

    /** Invalidate the full document view to force annotator repaint. */
    void InvalidateFullView();

    /** Get the main IllTool tool handle (for auto-activation from modules). */
    AIToolHandle GetToolHandle() const { return fToolHandle; }

protected:
    virtual ASErr SetGlobal(Plugin* plugin);
    virtual ASErr StartupPlugin(SPInterfaceMessage* message);
    virtual ASErr PostStartupPlugin();
    virtual ASErr ShutdownPlugin(SPInterfaceMessage* message);
    virtual ASErr Message(char* caller, char* selector, void* message);

    virtual ASErr GoMenuItem(AIMenuMessage* message);
    virtual ASErr UpdateMenuItem(AIMenuMessage* message);
    virtual ASErr Notify(AINotifierMessage* message);

    virtual ASErr ToolMouseDown(AIToolMessage* message);
    virtual ASErr TrackToolCursor(AIToolMessage* message);
    virtual ASErr SelectTool(AIToolMessage* message);
    virtual ASErr DeselectTool(AIToolMessage* message);

    ASErr AddTool(SPInterfaceMessage* message);
    ASErr AddAnnotator(SPInterfaceMessage* message);
    ASErr AddNotifier(SPInterfaceMessage* message);
    ASErr AddPanels();
    ASErr AddAppMenu(SPInterfaceMessage* message);
    void  DestroyPanels();

    ASErr DrawAnnotation(AIAnnotatorMessage* message);
    ASErr InvalAnnotation(AIAnnotatorMessage* message);

private:
    //------------------------------------------------------------------------------------
    //  Timer-based operation dispatch
    //------------------------------------------------------------------------------------

    /** Process queued operations from HTTP bridge and panel buttons.
        Called from AITimerSuite in SDK message context -- SDK API calls are safe here. */
    void ProcessOperationQueue();

    /** Handle a synchronous MCP operation (inspect, create_path, etc.).
        Called from ProcessOperationQueue when a sync request is pending.
        Posts the JSON result back to the waiting HTTP thread via condvar. */
    void HandleMcpOperation(const PluginOp& op);
};

#endif // __ILLTOOLPLUGIN_H__
