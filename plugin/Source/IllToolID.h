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
#define kIllToolPerspectiveTool         "IllTool Perspective"
#define kIllToolPenTool                 "IllTool Pen"

#define kIllToolCursorID                16060
#define kIllToolPerspectiveCursorID     16061
#define kIllToolPickACursorID           16062
#define kIllToolPickBCursorID           16063

// Panel internal IDs (must be unique strings)
#define kIllToolSelectionPanelID        "IllTool Selection"
#define kIllToolCleanupPanelID          "IllTool Cleanup"
#define kIllToolGroupingPanelID         "IllTool Grouping"
#define kIllToolMergePanelID            "IllTool Merge"
#define kIllToolShadingPanelID          "IllTool Shading"
#define kIllToolBlendPanelID            "IllTool Blend"
#define kIllToolPerspectivePanelID      "IllTool Perspective"
#define kIllToolTransformPanelID        "IllTool Transform"
#define kIllToolTracePanelID            "Ill Trace"
#define kIllToolSurfacePanelID          "Ill Surface"
#define kIllToolPenPanelID              "Ill Pen"

// Panel menu item identifiers
#define kIllToolSelectionMenuItem        "IllTool Selection Panel"
#define kIllToolCleanupMenuItem          "IllTool Cleanup Panel"
#define kIllToolGroupingMenuItem         "IllTool Grouping Panel"
#define kIllToolMergeMenuItem            "IllTool Merge Panel"
#define kIllToolShadingMenuItem          "IllTool Shading Panel"
#define kIllToolBlendMenuItem            "IllTool Blend Panel"
#define kIllToolPerspectiveMenuItem      "IllTool Perspective Panel"
#define kIllToolTransformMenuItem        "IllTool Transform Panel"
#define kIllToolTraceMenuItem            "IllTool Trace Panel"
#define kIllToolSurfaceMenuItem          "IllTool Surface Panel"
#define kIllToolPenMenuItem              "IllTool Pen Panel"

// Application menu (Window > IllTool submenu)
#define kIllToolMenuGroupName            "IllTool Menu Group"
#define kIllToolSubMenuGroupName         "IllTool SubMenu"
#define kIllToolMenuLassoItem            "IllTool Polygon Lasso"
#define kIllToolMenuSmartItem            "IllTool Smart Select"
#define kIllToolMenuCleanupItem          "IllTool Menu Cleanup"
#define kIllToolMenuGroupingItem         "IllTool Menu Grouping"
#define kIllToolMenuMergeItem            "IllTool Menu Merge"
#define kIllToolMenuSelectionItem        "IllTool Menu Selection"
#define kIllToolMenuShadingItem          "IllTool Menu Shading"
#define kIllToolMenuPerspToggleItem      "IllTool Toggle Perspective"

#endif //__ILLTOOLID_H__
