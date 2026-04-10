#ifndef __PENMODULE_H__
#define __PENMODULE_H__

//========================================================================================
//  PenModule — Ill Pen Tool (Stage 18)
//
//  Smart pen that auto-simplifies while drawing, supports chamfered corners,
//  and integrates with the grouping system.
//
//  Handles: PenPlacePoint, PenFinalize, PenCancel, PenSetChamfer, PenUndo
//  State: accumulated points, handles, chamfer radii, preview path
//  Mouse: click = place point, drag = set handle, double-click = finalize
//  Drawing: in-progress path with handles and chamfer preview arcs
//========================================================================================

#include "IllToolModule.h"
#include <vector>
#include <string>
#include <chrono>

class PenModule : public IllToolModule {
public:
    PenModule() = default;
    ~PenModule() override = default;

    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;

    bool HandleMouseDown(AIToolMessage* msg) override;
    bool HandleMouseDrag(AIToolMessage* msg) override;
    bool HandleMouseUp(AIToolMessage* msg) override;

    void DrawOverlay(AIAnnotatorMessage* msg) override;

    void OnSelectionChanged() override;
    void OnDocumentChanged() override;

    //------------------------------------------------------------------------------------
    //  Public accessors
    //------------------------------------------------------------------------------------

    /** Whether the pen is currently drawing (has placed points). */
    bool IsDrawing() const { return fDrawing; }

    /** Number of placed points in current path. */
    size_t GetPointCount() const { return fPoints.size(); }

private:
    //------------------------------------------------------------------------------------
    //  Drawing state
    //------------------------------------------------------------------------------------

    /** Accumulated click positions (artwork coords). */
    std::vector<AIRealPoint> fPoints;

    /** Drag handles for each point — set when user drags after clicking.
        Empty handle (0,0) = corner point (no smooth handle). */
    std::vector<AIRealPoint> fHandles;

    /** Per-anchor chamfer radius (0 = sharp corner). */
    std::vector<double> fChamferRadii;

    /** True while placing points (between first click and finalize/cancel). */
    bool fDrawing = false;

    /** True while user is dragging after placing a point (setting handle). */
    bool fDragging = false;

    /** Current mouse position during drag (for live handle preview). */
    AIRealPoint fDragCurrent = {0, 0};

    /** Preview path art handle — updated live as points are placed. */
    AIArtHandle fPreviewPath = nullptr;

    //------------------------------------------------------------------------------------
    //  Double-click detection
    //------------------------------------------------------------------------------------

    std::chrono::steady_clock::time_point fLastClickTime;
    AIRealPoint fLastClickPos = {0, 0};

    //------------------------------------------------------------------------------------
    //  Operations
    //------------------------------------------------------------------------------------

    /** Add a point at the given artwork position. */
    void PlacePoint(double x, double y);

    /** Remove the last placed point (undo within drawing). */
    void UndoLastPoint();

    /** Finalize the drawing: create actual AI path from accumulated points. */
    void Finalize();

    /** Discard the current drawing and reset state. */
    void Cancel();

    /** Set chamfer radius for all points (uniform) or last point only. */
    void SetChamfer(double radius);

    //------------------------------------------------------------------------------------
    //  Path building
    //------------------------------------------------------------------------------------

    /** Build path segments from accumulated points + handles + chamfer radii.
        Returns the segment array ready for AIPathSuite. */
    std::vector<AIPathSegment> BuildSegments() const;

    /** Apply chamfers to a segment array.
        Replaces sharp corners with bezier arcs where chamferRadii > 0. */
    static void ApplyChamfers(std::vector<AIPathSegment>& segs,
                              const std::vector<double>& radii);

    /** Compute a chamfer arc approximation for a corner.
        @param prev  Previous point
        @param corner  The corner point
        @param next  Next point
        @param radius  Chamfer radius
        @param outSeg1  First arc segment (transition from incoming edge)
        @param outSeg2  Second arc segment (transition to outgoing edge)
        @return true if chamfer was applied (false if radius too large for edges) */
    static bool ComputeChamferArc(AIRealPoint prev, AIRealPoint corner, AIRealPoint next,
                                  double radius,
                                  AIPathSegment& outSeg1, AIPathSegment& outSeg2);

    /** Update or create the preview path from current state. */
    void UpdatePreview();

    /** Delete the preview path if it exists. */
    void DeletePreview();

    //------------------------------------------------------------------------------------
    //  Grouping integration
    //------------------------------------------------------------------------------------

    /** Create the final path in the target group (from bridge state). */
    AIArtHandle CreateFinalPath(const std::vector<AIPathSegment>& segs, bool closed);

    //------------------------------------------------------------------------------------
    //  Overlay drawing helpers
    //------------------------------------------------------------------------------------

    /** Draw the in-progress path lines. */
    void DrawPathLines(AIAnnotatorMessage* msg);

    /** Draw anchor point squares at each placed point. */
    void DrawAnchorHandles(AIAnnotatorMessage* msg);

    /** Draw bezier direction handles for points that have them. */
    void DrawBezierHandles(AIAnnotatorMessage* msg);

    /** Draw chamfer preview arcs at corners with nonzero radius. */
    void DrawChamferPreviews(AIAnnotatorMessage* msg);

    //------------------------------------------------------------------------------------
    //  Constants
    //------------------------------------------------------------------------------------

    /** Bezier circle constant for circular arc chamfers. */
    static constexpr double kKappa = 0.5522847498;

    /** Double-click time threshold in milliseconds. */
    static constexpr int kDoubleClickMs = 400;

    /** Double-click distance threshold in artwork points. */
    static constexpr double kDoubleClickDist = 5.0;

    /** Handle size for anchor point squares (half-width in view pixels). */
    static constexpr double kAnchorSize = 4.0;

    /** Handle size for bezier direction handle circles (radius in view pixels). */
    static constexpr double kBezierHandleSize = 3.0;
};

#endif // __PENMODULE_H__
