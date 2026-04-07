//========================================================================================
//
//  IllTool Plugin — ID definitions
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Modified for IllTool overlay + tool registration.
//
//========================================================================================

#ifndef __ILLTOOLID_H__
#define __ILLTOOLID_H__

#define kIllToolPluginName              "IllTool Overlay"
#define kIllToolIconResourceID          16051
#define kIllToolTool                    "IllTool Handle"

#define kIllToolCursorID                16060

// Panel internal IDs (must be unique strings)
#define kIllToolSelectionPanelID        "IllTool Selection"
#define kIllToolCleanupPanelID          "IllTool Cleanup"
#define kIllToolGroupingPanelID         "IllTool Grouping"
#define kIllToolMergePanelID            "IllTool Merge"

// Panel menu item identifiers
#define kIllToolSelectionMenuItem        "IllTool Selection Panel"
#define kIllToolCleanupMenuItem          "IllTool Cleanup Panel"
#define kIllToolGroupingMenuItem         "IllTool Grouping Panel"
#define kIllToolMergeMenuItem            "IllTool Merge Panel"

// Application menu (Window > IllTool submenu)
#define kIllToolMenuGroupName            "IllTool Menu Group"
#define kIllToolSubMenuGroupName         "IllTool SubMenu"
#define kIllToolMenuLassoItem            "IllTool Polygon Lasso"
#define kIllToolMenuSmartItem            "IllTool Smart Select"
#define kIllToolMenuCleanupItem          "IllTool Menu Cleanup"
#define kIllToolMenuGroupingItem         "IllTool Menu Grouping"
#define kIllToolMenuMergeItem            "IllTool Menu Merge"
#define kIllToolMenuSelectionItem        "IllTool Menu Selection"

#endif //__ILLTOOLID_H__
