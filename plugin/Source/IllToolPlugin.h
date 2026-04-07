//========================================================================================
//
//  IllTool Plugin — Main plugin class
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Registers "IllTool Overlay" plugin with:
//    - "IllTool Handle" tool in its own toolbox group
//    - An annotator for overlay drawing
//    - Notifiers for selection change and app shutdown
//    - HTTP bridge on port 8787 for external draw commands
//    - Polygon lasso tool for segment selection
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

#include <vector>
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
    Computes the centroid of all selected anchors and moves them to it.
    Called from the Cleanup panel's "Average Selection" button. */
void PluginAverageSelection();

/** C-callable function to count currently selected anchor points.
    Iterates all path art and counts segments where the anchor is selected.
    Fast — no allocations, just counting.  Safe to call from NSTimer on main thread. */
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

/** IllTool Overlay plugin.
    Adds a tool to the toolbar and an annotator for overlay drawing.
    When the tool is selected the annotator activates; when deselected
    it deactivates.  Includes polygon lasso for segment selection and
    HTTP bridge for external draw commands.
*/
class IllToolPlugin : public Plugin
{
private:
    /** Handle for the IllTool Handle tool. */
    AIToolHandle            fToolHandle;

    /** Handle for the About SDK Plug-ins menu item. */
    AIMenuItemHandle        fAboutPluginMenu;

    /** Handle for the annotator added by this plug-in. */
    AIAnnotatorHandle       fAnnotatorHandle;

    /** Handle for the selection changed notifier. */
    AINotifierHandle        fNotifySelectionChanged;

    /** Handle for illustrator shutdown notifier. */
    AINotifierHandle        fShutdownApplicationNotifier;

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

    /** Menu item handles for panel show/hide in Window menu. */
    AIMenuItemHandle        fSelectionMenuHandle;
    AIMenuItemHandle        fCleanupMenuHandle;
    AIMenuItemHandle        fGroupingMenuHandle;
    AIMenuItemHandle        fMergeMenuHandle;
    AIMenuItemHandle        fShadingMenuHandle;
    AIMenuItemHandle        fBlendMenuHandle;
    AIMenuItemHandle        fPerspectiveMenuHandle;

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

    //------------------------------------------------------------------------------------
    //  Polygon lasso state
    //------------------------------------------------------------------------------------

    /** Vertices of the polygon being drawn by the lasso tool. */
    std::vector<AIRealPoint> fPolygonVertices;

    /** Last known cursor position in artwork coordinates. */
    AIRealPoint             fLastCursorPos;

    /** Timestamp of the last mouse-down for double-click detection. */
    double                  fLastClickTime;

    /** Double-click threshold in seconds. */
    static constexpr double kDoubleClickThreshold = 0.3;

    //------------------------------------------------------------------------------------
    //  Post-selection working mode state
    //------------------------------------------------------------------------------------

    /** Record of an original path that was dimmed and locked during working mode. */
    struct OriginalPathRecord {
        AIArtHandle art;
        AIReal      prevOpacity;
    };

    /** The original paths that were dimmed — restored on Cancel, optionally deleted on Apply. */
    std::vector<OriginalPathRecord> fOriginalPaths;

    /** The group containing duplicated paths for editing. */
    AIArtHandle             fWorkingGroup = nullptr;

    /** True when the user is in the duplicate-and-edit workflow. */
    bool                    fInWorkingMode = false;

    //------------------------------------------------------------------------------------
    //  Merge endpoint scan state (Stage 6)
    //------------------------------------------------------------------------------------

    /** Record of a matched endpoint pair between two open paths. */
    struct EndpointPair {
        AIArtHandle artA;           // first path
        AIArtHandle artB;           // second path
        bool        endA_is_end;    // true = end of A, false = start of A
        bool        endB_is_start;  // true = start of B, false = end of B
        double      distance;       // distance between the matched endpoints
    };

    /** Scanned endpoint pairs from the last ScanEndpoints call. */
    std::vector<EndpointPair> fMergePairs;

    /** Snapshot of original paths before merge, for undo. */
    struct MergeSnapshot {
        struct PathData {
            std::vector<AIPathSegment> segments;
            AIBoolean                  closed;
            AIArtHandle                parentRef;   // parent art (for placement on undo)
        };
        std::vector<PathData>      originals;       // original path data before merge
        std::vector<AIArtHandle>   mergedPaths;     // newly created merged paths (to delete on undo)
        bool                       valid = false;   // true if snapshot has data
    };

    MergeSnapshot fMergeSnapshot;

public:
    /** Generic undo stack for all destructive path operations (H3).
        Replaces per-feature ShapeSnapshot; supports multiple undo levels. */
    class UndoStack {
    public:
        struct PathSnapshot {
            AIArtHandle art;
            std::vector<AIPathSegment> segments;
            AIBoolean closed;
        };

        /** Begin a new undo frame. Call before a destructive operation. */
        void PushFrame();

        /** Save a path's current state into the top frame. Call for each path being modified. */
        void SnapshotPath(AIArtHandle art);

        /** Restore all paths in the top frame and pop it. Returns number of paths restored. */
        int Undo();

        /** Check if there's anything to undo. */
        bool CanUndo() const { return !stack.empty(); }

        /** Clear all frames (e.g., on document change). */
        void Clear() { stack.clear(); }

        /** Maximum number of undo frames to keep. */
        static const int kMaxFrames = 20;

    private:
        std::vector<std::vector<PathSnapshot>> stack;
    };

    UndoStack fUndoStack;

public:
    /** Cached selection count — updated from Notify (where SDK calls work).
        Public so PluginGetSelectedAnchorCount() can read it. */
    std::atomic<int>        fLastKnownSelectionCount{0};

    /** Returns the working group art handle (non-null when in working mode). */
    AIArtHandle GetWorkingGroup() const { return fWorkingGroup; }

    /** Returns true when the plugin is in the duplicate-and-edit workflow. */
    bool IsInWorkingMode() const { return fInWorkingMode; }

    /** Constructor. */
    IllToolPlugin(SPPluginRef pluginRef);

    /** Destructor. */
    virtual ~IllToolPlugin() {}

    /** Restores state of IllToolPlugin during reload. */
    FIXUP_VTABLE_EX(IllToolPlugin, Plugin);

public:
    /** Update a panel's Window menu checkmark when visibility changes. */
    void UpdatePanelMenu(AIPanelRef panel, AIBoolean isVisible);

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
        Called from AITimerSuite in SDK message context — SDK API calls are safe here. */
    void ProcessOperationQueue();

    //------------------------------------------------------------------------------------
    //  Polygon lasso helpers
    //------------------------------------------------------------------------------------

    /** Update the polygon overlay draw commands for annotator visualization. */
    void UpdatePolygonOverlay();

    /** Execute polygon selection: select all path segments whose anchors
        fall inside the polygon defined by fPolygonVertices. */
    void ExecutePolygonSelection();

    /** Point-in-polygon test (ray casting algorithm). */
    static bool PointInPolygon(const AIRealPoint& pt,
                               const std::vector<AIRealPoint>& polygon);

    /** Invalidate the full document view to force annotator repaint. */
    void InvalidateFullView();

public:
    /** Average selected anchor points: move all selected anchors to their centroid.
        This is the "Average Selection" cleanup operation. */
    void AverageSelection();

    /** Classify the currently selected path's shape type (line, arc, L, rect, S, ellipse, freeform).
        Reads path segments, runs a simple heuristic, and stores the result for panel display. */
    void ClassifySelection();

    /** Force-fit the selected path to a specific shape type and rewrite its segments. */
    void ReclassifyAs(BridgeShapeType shapeType);

    /** Simplify selected paths using Douglas-Peucker algorithm.
        @param tolerance  Drawing-space distance tolerance for point removal. */
    void SimplifySelection(double tolerance);

    /** Select all paths with total arc length below the given threshold.
        @param threshold  Maximum arc length in points to be selected. */
    void SelectSmall(double threshold);

    /** Last detected shape name — read by the Cleanup panel to update the "Detected:" label. */
    /** Only written by SDK thread, read by Cocoa thread.
        Pointer-sized writes are atomic on ARM64. String literals have static lifetime. */
    const char* fLastDetectedShape = "---";

    // Surface hint now stored in thread-safe bridge atomics (BridgeSet/GetSurfaceHint)

    /** Enter isolation mode for the parent group(s) of selected paths.
        Called after ExecutePolygonSelection selects segments. */
    void EnterIsolationForSelection();

    /** Enter working mode: duplicate selected paths into a "Working" layer group,
        dim and lock originals, enter isolation on the working group. */
    void EnterWorkingMode();

    /** Apply working mode: exit isolation, optionally delete originals, finalize duplicates. */
    void ApplyWorkingMode(bool deleteOriginals);

    /** Cancel working mode: exit isolation, delete duplicates, restore originals. */
    void CancelWorkingMode();

    //------------------------------------------------------------------------------------
    //  Grouping operations (Stage 5)
    //------------------------------------------------------------------------------------

    /** Copy selected paths into a new named group.
        Creates a kGroupArt, duplicates each selected path into it,
        names the group, and enters isolation mode on the new group. */
    void CopyToGroup(const std::string& groupName);

    /** Detach selected paths from their parent group.
        Moves each selected path that is inside a group to be a sibling
        after that group in the art tree. */
    void DetachFromGroup();

    /** Split selected paths into a new group.
        Creates a new group and moves (reorders) selected paths into it. */
    void SplitToNewGroup();

    //------------------------------------------------------------------------------------
    //  Merge operations (Stage 6)
    //------------------------------------------------------------------------------------

    /** Scan selected open paths for endpoint pairs within tolerance distance.
        Populates fMergePairs and updates the merge readout text via bridge. */
    void ScanEndpoints(double tolerance);

    /** Merge scanned endpoint pairs: join paths at matched endpoints.
        @param chainMerge       If true, re-scan and repeat until no more pairs.
        @param preserveHandles  If true, keep original handles at the junction. */
    void MergeEndpoints(bool chainMerge, bool preserveHandles);

    /** Undo last merge: restore original paths from snapshot, delete merged paths. */
    void UndoMerge();

    //------------------------------------------------------------------------------------
    //  Smart Select (Stage 9) — boundary signature matching
    //------------------------------------------------------------------------------------

    /** Signature capturing the geometric characteristics of a path for similarity matching. */
    struct BoundarySignature {
        double totalLength;      ///< Total path length (sum of segment arc lengths)
        double avgCurvature;     ///< Average curvature (sum of angle changes / totalLength)
        double startAngle;       ///< Tangent direction at the first anchor (radians)
        double endAngle;         ///< Tangent direction at the last anchor (radians)
        bool   isClosed;         ///< Whether the path is closed
        int    segmentCount;     ///< Number of path segments (anchor points)
    };

    /** Compute the boundary signature for a given path art object.
        Returns a BoundarySignature struct populated from path geometry. */
    BoundarySignature ComputeSignature(AIArtHandle path);

    /** Find all paths in the document with a similar signature and select them.
        @param refSig        The reference signature to match against.
        @param thresholdPct  Similarity threshold (0-100). Lower = stricter.
        @param hitArt        The originally hit art (always selected regardless of matching). */
    void SelectMatchingPaths(const BoundarySignature& refSig, double thresholdPct,
                             AIArtHandle hitArt);

    //------------------------------------------------------------------------------------
    //  Perspective Grid (Stage 10)
    //------------------------------------------------------------------------------------

    /** A user-placed perspective line: two draggable handles defining a direction.
        The vanishing point is computed by extending this line to infinity. */
    struct PerspectiveLine {
        AIRealPoint handle1 = {0, 0};   ///< First handle position (artwork coords)
        AIRealPoint handle2 = {0, 0};   ///< Second handle position (artwork coords)
        bool active = false;             ///< true when line has been placed
    };

    /** Perspective grid: lines placed by user, VPs derived from line extensions. */
    struct PerspectiveGrid {
        PerspectiveLine leftVP;          ///< Line converging to left vanishing point
        PerspectiveLine rightVP;         ///< Line converging to right vanishing point
        PerspectiveLine verticalVP;      ///< Line converging to vertical VP (optional, 3-point)
        double horizonY = 400;           ///< Adjustable horizon line Y coordinate
        bool locked = false;             ///< true when user confirms the grid
        bool visible = true;             ///< show/hide overlay without clearing grid
        int gridDensity = 5;             ///< Number of grid lines per axis (2-20)

        // Computed from lines (updated by Recompute):
        AIRealPoint computedVP1 = {0,0}; ///< Intersection point of leftVP line extension
        AIRealPoint computedVP2 = {0,0}; ///< Intersection point of rightVP line extension
        AIRealPoint computedVP3 = {0,0}; ///< Intersection point of verticalVP line extension
        bool valid = false;              ///< true when at least leftVP and rightVP are active

        /** Recompute VPs from line handles and validate. */
        void Recompute();

        /** Clear all lines and reset state. */
        void Clear();

        /** Return the number of active lines (0-3). */
        int ActiveLineCount() const;

        /** Save grid state to document dictionary (persists with file). */
        void SaveToDocument();

        /** Load grid state from document dictionary (on document open). */
        void LoadFromDocument();

        /** Compute a 3x3 homography matrix for the floor plane.
            Maps from grid-space (u,v) to artwork-space (x,y).
            Returns false if grid is not valid. */
        bool ComputeFloorHomography(double matrix[9]) const;

        /** Transform a point from artwork space through the perspective grid.
            @param artPt   Point in artwork coordinates.
            @param plane   0=floor, 1=left wall, 2=right wall
            @return Projected point. */
        AIRealPoint ProjectToPlane(AIRealPoint artPt, int plane) const;

        /** Mirror a point across a perspective-aware axis.
            @param artPt        Point to mirror.
            @param axisVertical true = mirror across vertical axis, false = horizontal.
            @return Mirrored point in artwork coords. */
        AIRealPoint MirrorInPerspective(AIRealPoint artPt, bool axisVertical) const;
    };

    PerspectiveGrid fPerspectiveGrid;

    //------------------------------------------------------------------------------------
    //  Blend Harmonization (Stage 11)
    //------------------------------------------------------------------------------------

    /** Persistent state for a single blend operation. Tracks the group, source paths,
        parameters, and intermediate art handles for non-destructive re-editing. */
    struct BlendState {
        AIArtHandle groupArt = nullptr;     ///< The containing "Blend Group N" group
        AIArtHandle pathA = nullptr;        ///< Source path A (inside group)
        AIArtHandle pathB = nullptr;        ///< Source path B (inside group)
        int steps = 5;                      ///< Number of intermediate paths
        int easingPreset = 0;               ///< 0=linear, 1=easeIn, 2=easeOut, 3=easeInOut, 4=custom
        std::vector<std::pair<double,double>> customEasingPoints;  ///< Custom easing CPs (for preset 4)
        std::vector<AIArtHandle> intermediates;  ///< Created intermediate paths (for re-blend deletion)
    };

    /** The blend path pair — set by Pick A / Pick B tool mode. */
    AIArtHandle fBlendPathA = nullptr;
    AIArtHandle fBlendPathB = nullptr;

    /** Active blend states — one per blend group in the document.
        Used for re-editing: select group, change params, re-blend. */
    std::vector<BlendState> fBlendStates;

    /** Running counter for blend group naming ("Blend Group 1", "Blend Group 2", ...). */
    int fBlendGroupCounter = 0;

    /** Execute blend: harmonize pathA and pathB, create N intermediate paths.
        Groups everything into a named blend group and stores state for re-editing.
        @param pathA        First path art handle.
        @param pathB        Second path art handle.
        @param steps        Number of intermediate paths (1-20).
        @param easingPreset 0=linear, 1=easeIn, 2=easeOut, 3=easeInOut.
        @return Number of paths created, or 0 on failure. */
    int ExecuteBlend(AIArtHandle pathA, AIArtHandle pathB, int steps, int easingPreset);

    /** Re-blend an existing blend group with new parameters.
        Deletes old intermediates, creates new ones, updates stored state.
        @param groupArt     The blend group art handle.
        @param steps        New step count.
        @param easingPreset New easing preset.
        @return Number of new paths created, or 0 on failure. */
    int ReblendGroup(AIArtHandle groupArt, int steps, int easingPreset);

    /** Find BlendState for a given group art handle. Returns nullptr if not found. */
    BlendState* FindBlendState(AIArtHandle groupArt);

    /** Check if an art handle is (or is inside) a blend group.
        If so, returns the blend group handle. Otherwise returns nullptr. */
    AIArtHandle FindBlendGroupForArt(AIArtHandle art);

    /** Sync perspective grid state from bridge state variables.
        Called from ProcessOperationQueue before drawing. */
    void SyncPerspectiveFromBridge();

    /** Clear the perspective grid and invalidate the view. */
    void ClearPerspectiveGrid();

    /** Draw perspective grid overlay via AIAnnotatorDrawerSuite.
        Draws: user lines with handles, dotted extensions, computed VP markers,
        horizon line, and grid lines (when locked). */
    void DrawPerspectiveOverlay(AIAnnotatorMessage* message);

    //------------------------------------------------------------------------------------
    //  Surface Shading (Stage 12)
    //------------------------------------------------------------------------------------

    /** Running counter for shading group naming ("Shading Group 1", etc.). */
    int fShadingGroupCounter = 0;

    /** Apply blend shading (stacked contours) to a closed path.
        Creates N scaled/offset copies with colors from shadow→highlight ramp.
        Colors are RGB 0-1 range. Intensity is 0-100 (slider value).
        @return Number of contour paths created, or 0 on failure. */
    int ApplyBlendShading(AIArtHandle path, int steps,
        double highlightR, double highlightG, double highlightB,
        double shadowR, double shadowG, double shadowB,
        double lightAngle, double intensity);

    /** Apply mesh gradient shading to a path.
        Creates a kMeshArt with vertex colors based on light direction.
        Colors are RGB 0-1 range. Intensity is 0-100 (slider value).
        @return 1 on success, 0 on failure. */
    int ApplyMeshShading(AIArtHandle path, int gridSize,
        double highlightR, double highlightG, double highlightB,
        double shadowR, double shadowG, double shadowB,
        double lightAngle, double intensity);

    /** Dispatch a shading operation from the operation queue.
        Reads current shading parameters from bridge state, finds the selected
        path, and calls ApplyBlendShading or ApplyMeshShading. */
    void DispatchShadingOp(OpType opType);
};

#endif // __ILLTOOLPLUGIN_H__
