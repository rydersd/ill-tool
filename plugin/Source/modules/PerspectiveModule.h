#ifndef __PERSPECTIVEMODULE_H__
#define __PERSPECTIVEMODULE_H__

//========================================================================================
//  PerspectiveModule — Perspective grid for projecting shapes into 1/2/3-point perspective
//
//  Owns: PerspectiveGrid struct, VP placement, grid overlay drawing,
//        handle dragging, mirror/duplicate/paste in perspective,
//        document persistence via AIDictionarySuite.
//
//  Ported from IllToolPerspective.cpp into the module system.
//========================================================================================

#include "IllToolModule.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include <vector>
#include <cmath>

class PerspectiveModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  PerspectiveLine — a user-placed line whose extension defines a VP
    //------------------------------------------------------------------------------------

    struct PerspectiveLine {
        AIRealPoint handle1 = {0, 0};   ///< First handle position (artwork coords)
        AIRealPoint handle2 = {0, 0};   ///< Second handle position (artwork coords)
        bool active = false;             ///< true when line has been placed
    };

    //------------------------------------------------------------------------------------
    //  PerspectiveGrid — lines placed by user, VPs derived from line extensions
    //------------------------------------------------------------------------------------

    struct PerspectiveGrid {
        PerspectiveLine leftVP;          ///< Line converging to left vanishing point
        PerspectiveLine rightVP;         ///< Line converging to right vanishing point
        PerspectiveLine verticalVP;      ///< Line converging to vertical VP (optional, 3-point)
        double horizonY = 400;           ///< Adjustable horizon line Y coordinate
        bool locked = false;             ///< true when user confirms the grid
        bool visible = false;            ///< show/hide overlay — off until user activates
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

    //------------------------------------------------------------------------------------
    //  Public accessors
    //------------------------------------------------------------------------------------

    PerspectiveGrid& GetGrid() { return fGrid; }
    const PerspectiveGrid& GetGrid() const { return fGrid; }

    /** Returns true if a VP handle is currently hovered (for cursor change). */
    bool IsHandleHovered() const { return fHoverLine >= 0; }

    /** Returns true if in perspective editing mode (arrow cursor, handles draggable). */
    bool IsInEditMode() const { return fEditMode; }

    /** Enter/exit perspective editing mode. */
    void SetEditMode(bool edit);

    /** Update hover state from cursor tracking (called from TrackToolCursor). */
    void HandleCursorTrack(AIRealPoint artPt);

    /** Project a set of points through the perspective grid.
        @param plane 0=floor, 1=left wall, 2=right wall. */
    std::vector<AIRealPoint> ProjectPointsThroughPerspective(
        const std::vector<AIRealPoint>& points, int plane = 0);

    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    bool HandleMouseDown(AIToolMessage* msg) override;
    bool HandleMouseDrag(AIToolMessage* msg) override;
    bool HandleMouseUp(AIToolMessage* msg) override;
    void DrawOverlay(AIAnnotatorMessage* msg) override;
    void OnDocumentChanged() override;

private:
    //------------------------------------------------------------------------------------
    //  Grid state
    //------------------------------------------------------------------------------------

    PerspectiveGrid fGrid;

    /** Cached artboard bounds — set on document open, stable across zoom/pan.
        Used for horizon % → Y conversion instead of view bounds. */
    AIRealRect fCachedArtboardBounds = {0, 0, 0, 0};

    //------------------------------------------------------------------------------------
    //  Drag interaction state
    //------------------------------------------------------------------------------------

    /** Which perspective line is being dragged (-1 = none, 0-2 = line index). */
    bool fEditMode = false;    ///< In perspective editing mode (arrow cursor, handles draggable)
    int fHoverLine = -1;       ///< Which line's handle is hovered (-1=none)
    int fHoverHandle = 0;      ///< Which handle (1 or 2) is hovered

    int fDragLine = -1;

    /** Which handle of the line is being dragged (1 = handle1, 2 = handle2, 0 = none). */
    int fDragHandle = 0;

    /** Track which line to place next when clicking empty space (cycles 0,1,2). */
    int fNextLineIndex = 0;

    /** When true, next click on canvas places VP1 + auto-mirrors VP2.
        Set by ActivatePerspectiveTool instead of switching to the perspective tool
        (which gets immediately deselected when the panel takes focus). */
    bool fPlacementMode = false;

    /** True if Smart Guides were enabled before we disabled them on grid lock. */
    bool fSmartGuidesWasEnabled = true;

    /** Hit-test radius for perspective handles in artwork-space points. */
    static constexpr double kHandleHitRadius = 8.0;

    //------------------------------------------------------------------------------------
    //  Undo
    //------------------------------------------------------------------------------------

    UndoStack fUndoStack;

    //------------------------------------------------------------------------------------
    //  Operation handlers
    //------------------------------------------------------------------------------------

    void ClearGrid();
    void LockGrid(bool lock);
    void SetGridDensity(int density);
    void PlaceVerticalVP();
    void DeleteGrid();
    void ActivatePerspectiveTool();

    void RegisterSnapConstraints();
    void ClearSnapConstraints();

    void SyncFromBridge();
    void SaveToDocument();
    void LoadFromDocument();
    void SavePreset(const std::string& name);
    void LoadPreset(const std::string& name);
    std::vector<std::string> ListPresets();

    void AutoMatchPerspective();
    void MirrorInPerspective(int axis, bool replace);
    void DuplicateInPerspective(int count, int spacing);
    void PasteInPerspective(int plane, float scale);

    //------------------------------------------------------------------------------------
    //  Mouse handlers
    //------------------------------------------------------------------------------------

    void ToolMouseDown(AIToolMessage* msg);
    void ToolMouseDrag(AIToolMessage* msg);
    void ToolMouseUp(AIToolMessage* msg);

    //------------------------------------------------------------------------------------
    //  Drawing
    //------------------------------------------------------------------------------------

    void DrawPerspectiveOverlay(AIAnnotatorMessage* msg);
};

#endif // __PERSPECTIVEMODULE_H__
