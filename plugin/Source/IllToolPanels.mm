//========================================================================================
//
//  IllTool — Panel Registration (Objective-C++)
//
//  Creates the four SDK panels and attaches programmatic Cocoa views.
//  Called from IllToolPlugin.cpp via C++ (the .mm extension ensures
//  Objective-C++ compilation so we can use Cocoa classes).
//
//========================================================================================

#include "IllustratorSDK.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "IllToolID.h"

#import <Cocoa/Cocoa.h>
#import "panels/SelectionPanelController.h"
#import "panels/CleanupPanelController.h"
#import "panels/GroupingPanelController.h"
#import "panels/MergePanelController.h"

#include <cstdio>

// Access the global plugin pointer (defined in IllToolPlugin.cpp)
extern IllToolPlugin *gPlugin;

//========================================================================================
//  Panel visibility callback — updates the Window menu checkmark
//========================================================================================

static void SelectionPanelVisibilityChanged(AIPanelRef inPanel, AIBoolean isVisible)
{
    AIPanelUserData ud = NULL;
    sAIPanel->GetUserData(inPanel, ud);
    if (ud) {
        IllToolPlugin* plugin = reinterpret_cast<IllToolPlugin*>(ud);
        plugin->UpdatePanelMenu(inPanel, isVisible);
    }
}

static void CleanupPanelVisibilityChanged(AIPanelRef inPanel, AIBoolean isVisible)
{
    AIPanelUserData ud = NULL;
    sAIPanel->GetUserData(inPanel, ud);
    if (ud) {
        IllToolPlugin* plugin = reinterpret_cast<IllToolPlugin*>(ud);
        plugin->UpdatePanelMenu(inPanel, isVisible);
    }
}

static void GroupingPanelVisibilityChanged(AIPanelRef inPanel, AIBoolean isVisible)
{
    AIPanelUserData ud = NULL;
    sAIPanel->GetUserData(inPanel, ud);
    if (ud) {
        IllToolPlugin* plugin = reinterpret_cast<IllToolPlugin*>(ud);
        plugin->UpdatePanelMenu(inPanel, isVisible);
    }
}

static void MergePanelVisibilityChanged(AIPanelRef inPanel, AIBoolean isVisible)
{
    AIPanelUserData ud = NULL;
    sAIPanel->GetUserData(inPanel, ud);
    if (ud) {
        IllToolPlugin* plugin = reinterpret_cast<IllToolPlugin*>(ud);
        plugin->UpdatePanelMenu(inPanel, isVisible);
    }
}

//========================================================================================
//  Panel resize callback — resize the Cocoa view to fill the panel
//========================================================================================

static void PanelSizeChanged(AIPanelRef inPanel)
{
    AISize panelSize = {0, 0};
    AIErr error = sAIPanel->GetSize(inPanel, panelSize);
    if (error) return;

    AIPanelPlatformWindow platformWindow = nullptr;
    error = sAIPanel->GetPlatformWindow(inPanel, platformWindow);
    if (error || !platformWindow) return;

    NSView *hostView = (__bridge NSView*)((void*)platformWindow);
    // Resize the first subview (our controller's root view) to fill
    if (hostView.subviews.count > 0) {
        NSView *childView = hostView.subviews[0];
        [childView setFrame:NSMakeRect(0, 0, panelSize.width, panelSize.height)];
    }
}

//========================================================================================
//  Helper: create one panel, its menu item, and attach the Cocoa view
//========================================================================================

static ASErr CreateOnePanel(
    SPPluginRef pluginRef,
    IllToolPlugin* plugin,
    const char* panelID,
    const char* menuLabel,
    CGFloat panelHeight,
    AIPanelVisibilityChangedNotifyProc visProc,
    NSObject* controller,   // the panel controller
    NSView* controllerView, // the controller's rootView
    AIPanelRef& outPanel,
    AIMenuItemHandle& outMenuHandle)
{
    ASErr error = kNoErr;

    // Create flyout menu (empty for now — can be populated later)
    AIPanelFlyoutMenuRef flyoutMenu = NULL;
    // Passing NULL hides the flyout icon, which is fine for now

    // Create the panel
    AISize minSize = {240.0, panelHeight};
    error = sAIPanel->Create(
        pluginRef,
        ai::UnicodeString(panelID),     // internal ID
        ai::UnicodeString(panelID),     // display title
        1,                               // state count (1 = single layout)
        minSize,
        true,                            // resizable
        flyoutMenu,                      // flyout menu (NULL = no flyout)
        (AIPanelUserData)plugin,         // user data = plugin pointer
        outPanel);

    if (error) {
        fprintf(stderr, "[IllTool] Failed to create panel '%s': %d\n", panelID, (int)error);
        return error;
    }

    // Set size constraints
    AISize maxSize = {500.0, 800.0};
    AISize prefSize = {240.0, panelHeight};
    error = sAIPanel->SetSizes(outPanel, minSize, prefSize, prefSize, maxSize);
    if (error) {
        fprintf(stderr, "[IllTool] SetSizes failed for '%s': %d\n", panelID, (int)error);
    }

    // Set callbacks
    sAIPanel->SetVisibilityChangedNotifyProc(outPanel, visProc);
    sAIPanel->SetSizeChangedNotifyProc(outPanel, PanelSizeChanged);

    // Show the panel initially
    sAIPanel->Show(outPanel, true);

    // Get the platform window (NSView*) and add our controller's view
    AIPanelPlatformWindow platformWindow = nullptr;
    error = sAIPanel->GetPlatformWindow(outPanel, platformWindow);
    if (error || !platformWindow) {
        fprintf(stderr, "[IllTool] GetPlatformWindow failed for '%s': %d\n", panelID, (int)error);
        return error;
    }

    NSView *hostView = (__bridge NSView*)((void*)platformWindow);
    NSRect hostFrame = hostView.frame;

    // Size our view to fill the host
    [controllerView setFrame:NSMakeRect(0, 0, hostFrame.size.width, hostFrame.size.height)];
    controllerView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    [hostView addSubview:controllerView];

    fprintf(stderr, "[IllTool] Panel '%s' created (%.0f x %.0f)\n",
            panelID, hostFrame.size.width, hostFrame.size.height);

    // Create Window menu item for show/hide
    error = sAIMenu->AddMenuItemZString(
        pluginRef,
        menuLabel,                          // internal name for menu item
        kOtherPalettesMenuGroup,            // Window > Extensions group
        ZREF(menuLabel),                    // display string
        kMenuItemNoOptions,
        &outMenuHandle);

    if (error) {
        fprintf(stderr, "[IllTool] AddMenuItemZString failed for '%s': %d\n", menuLabel, (int)error);
    }

    return kNoErr;
}

//========================================================================================
//  AddPanels — called from StartupPlugin
//========================================================================================

ASErr IllToolPlugin::AddPanels()
{
    ASErr error = kNoErr;

    fprintf(stderr, "[IllTool] AddPanels begin\n");

    // Verify panel suite is available
    if (!sAIPanel) {
        fprintf(stderr, "[IllTool] ERROR: AIPanelSuite not available\n");
        return kCantHappenErr;
    }
    if (!sAIMenu) {
        fprintf(stderr, "[IllTool] ERROR: AIMenuSuite not available\n");
        return kCantHappenErr;
    }

    // --- Selection Panel ---
    {
        SelectionPanelController *ctrl = [[SelectionPanelController alloc] init];
        fSelectionController = (void*)[ctrl retain];

        error = CreateOnePanel(
            fPluginRef, this,
            kIllToolSelectionPanelID,
            kIllToolSelectionMenuItem,
            260.0,
            SelectionPanelVisibilityChanged,
            ctrl, ctrl.rootView,
            fSelectionPanel, fSelectionMenuHandle);

        if (error) {
            fprintf(stderr, "[IllTool] Selection panel creation failed: %d\n", (int)error);
        } else {
            fprintf(stderr, "[IllTool] Selection panel registered\n");
        }
    }

    // --- Cleanup Panel ---
    {
        CleanupPanelController *ctrl = [[CleanupPanelController alloc] init];
        fCleanupController = (void*)[ctrl retain];

        error = CreateOnePanel(
            fPluginRef, this,
            kIllToolCleanupPanelID,
            kIllToolCleanupMenuItem,
            448.0,  // 420 + 28 for Delete Originals checkbox row
            CleanupPanelVisibilityChanged,
            ctrl, ctrl.rootView,
            fCleanupPanel, fCleanupMenuHandle);

        if (error) {
            fprintf(stderr, "[IllTool] Cleanup panel creation failed: %d\n", (int)error);
        } else {
            fprintf(stderr, "[IllTool] Cleanup panel registered\n");
        }
    }

    // --- Grouping Panel ---
    {
        GroupingPanelController *ctrl = [[GroupingPanelController alloc] init];
        fGroupingController = (void*)[ctrl retain];

        error = CreateOnePanel(
            fPluginRef, this,
            kIllToolGroupingPanelID,
            kIllToolGroupingMenuItem,
            340.0,
            GroupingPanelVisibilityChanged,
            ctrl, ctrl.rootView,
            fGroupingPanel, fGroupingMenuHandle);

        if (error) {
            fprintf(stderr, "[IllTool] Grouping panel creation failed: %d\n", (int)error);
        } else {
            fprintf(stderr, "[IllTool] Grouping panel registered\n");
        }
    }

    // --- Merge Panel ---
    {
        MergePanelController *ctrl = [[MergePanelController alloc] init];
        fMergeController = (void*)[ctrl retain];

        error = CreateOnePanel(
            fPluginRef, this,
            kIllToolMergePanelID,
            kIllToolMergeMenuItem,
            300.0,
            MergePanelVisibilityChanged,
            ctrl, ctrl.rootView,
            fMergePanel, fMergeMenuHandle);

        if (error) {
            fprintf(stderr, "[IllTool] Merge panel creation failed: %d\n", (int)error);
        } else {
            fprintf(stderr, "[IllTool] Merge panel registered\n");
        }
    }

    fprintf(stderr, "[IllTool] AddPanels complete\n");
    return kNoErr;
}

//========================================================================================
//  DestroyPanels — called from ShutdownPlugin
//========================================================================================

void IllToolPlugin::DestroyPanels()
{
    fprintf(stderr, "[IllTool] DestroyPanels\n");

    if (sAIPanel) {
        if (fSelectionPanel) { sAIPanel->Destroy(fSelectionPanel); fSelectionPanel = NULL; }
        if (fCleanupPanel)   { sAIPanel->Destroy(fCleanupPanel);   fCleanupPanel = NULL; }
        if (fGroupingPanel)  { sAIPanel->Destroy(fGroupingPanel);  fGroupingPanel = NULL; }
        if (fMergePanel)     { sAIPanel->Destroy(fMergePanel);     fMergePanel = NULL; }
    }

    // Release retained Objective-C controllers
    if (fSelectionController) { [(id)fSelectionController release]; fSelectionController = NULL; }
    if (fCleanupController)   { [(id)fCleanupController release];   fCleanupController = NULL; }
    if (fGroupingController)  { [(id)fGroupingController release];  fGroupingController = NULL; }
    if (fMergeController)     { [(id)fMergeController release];     fMergeController = NULL; }
}

//========================================================================================
//  UpdatePanelMenu — called from visibility-changed callbacks
//========================================================================================

void IllToolPlugin::UpdatePanelMenu(AIPanelRef panel, AIBoolean isVisible)
{
    AIMenuItemHandle menuHandle = NULL;

    if (panel == fSelectionPanel)      menuHandle = fSelectionMenuHandle;
    else if (panel == fCleanupPanel)   menuHandle = fCleanupMenuHandle;
    else if (panel == fGroupingPanel)  menuHandle = fGroupingMenuHandle;
    else if (panel == fMergePanel)     menuHandle = fMergeMenuHandle;

    if (menuHandle && sAIMenu) {
        sAIMenu->CheckItem(menuHandle, isVisible);
    }
}
