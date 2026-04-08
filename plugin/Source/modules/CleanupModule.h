#ifndef __CLEANUPMODULE_H__
#define __CLEANUPMODULE_H__

//========================================================================================
//  CleanupModule — Shape cleanup: average, classify, reclassify, simplify, working mode
//
//  Ported from IllToolWorkingMode.cpp and IllToolShapes.cpp.
//  All math delegated to ShapeUtils.h; no direct geometry in this file.
//========================================================================================

#include "IllToolModule.h"
#include "ShapeUtils.h"
#include "LearningEngine.h"

#include <vector>
#include <string>
#include <atomic>

class CleanupModule : public IllToolModule {
public:
    CleanupModule() = default;
    ~CleanupModule() override = default;

    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;

    bool HandleMouseDown(AIToolMessage* msg) override;
    bool HandleMouseDrag(AIToolMessage* msg) override;
    bool HandleMouseUp(AIToolMessage* msg) override;
    void HandleCursorTrack(AIRealPoint artPt);

    void DrawOverlay(AIAnnotatorMessage* msg) override;

    void OnSelectionChanged() override;
    void OnDocumentChanged() override;

    bool CanUndo() override;
    void Undo() override;

    //------------------------------------------------------------------------------------
    //  Public accessors (read by panel / plugin router)
    //------------------------------------------------------------------------------------

    /** Last detected shape label — read by panel to update "Detected:" display.
        Pointer to static string; arm64 pointer writes are atomic. */
    const char* GetLastDetectedShape() const { return fLastDetectedShape; }

    /** Whether the module is in working mode (preview active). */
    bool IsInWorkingMode() const { return fInWorkingMode; }

    /** True while Apply/Cancel is running — suppresses isolation re-entry. */
    bool IsExitingWorkingMode() const { return fExitingWorkingMode; }

    /** The working group art handle (non-null when in working mode). */
    AIArtHandle GetWorkingGroup() const { return fWorkingGroup; }

    /** Cached selection count — updated from OnSelectionChanged. */
    int GetSelectedAnchorCount() const { return fLastKnownSelectionCount.load(); }

    /** Source group name (empty if at document root). Read by panel for context display. */
    const std::string& GetSourceGroupName() const { return fSourceGroupName; }

    /** Source layer name. Read by panel for auto-naming. */
    const std::string& GetSourceLayerName() const { return fSourceLayerName; }

    /** Set cached selection count — called by plugin's Notify handler. */
    void SetSelectedAnchorCount(int count) { fLastKnownSelectionCount.store(count); }

    //------------------------------------------------------------------------------------
    //  Custom bounding box state (public for annotator access)
    //------------------------------------------------------------------------------------

    struct BoundingBoxState {
        AIRealPoint corners[4];     ///< Rotated bbox corners (artwork coords)
        AIRealPoint midpoints[4];   ///< Midpoints of each edge
        AIRealPoint center;         ///< Center of the bbox
        double rotation = 0;        ///< Rotation angle in radians (from PCA eigenvector)
        bool visible = false;       ///< Shown when in working mode with preview path
        int dragHandle = -1;        ///< -1=none, 0-3=corners, 4-7=midpoints, 8=rotating
        AIRealPoint dragStart;      ///< Mouse position at drag start (artwork coords)
        double dragStartAngle = 0;  ///< Angle at rotation drag start
        bool freeDistort = false;   ///< true=free distort, false=scale (perspective if available)
    };

    BoundingBoxState fBBox;

    /// Which anchor point is being dragged (-1 = none)
    int fDragAnchorIdx = -1;
    /// Mouse position at start of anchor drag
    AIRealPoint fAnchorDragStart;
    /// Original segment position at start of drag (for delta calculation)
    AIPathSegment fAnchorDragOrigSeg;

    /// Hover state for handle pre-highlighting (-1 = none)
    int fHoverAnchorIdx = -1;    ///< Hovered path anchor point (square)
    int fHoverBBoxIdx = -1;      ///< Hovered bbox handle (-1=none, 0-7=handles, 8=rotate zone)
    int fHoverBezierIdx = -1;    ///< Hovered bezier handle endpoint (circle): seg*2+0=in, seg*2+1=out

    /// Bezier handle drag state
    int fDragBezierIdx = -1;     ///< Which bezier handle is being dragged (-1=none, seg*2+0=in, seg*2+1=out)
    AIRealPoint fBezierDragStart;

private:
    //------------------------------------------------------------------------------------
    //  Operations
    //------------------------------------------------------------------------------------

    void ClassifySelection();
    void ReclassifyAs(BridgeShapeType shapeType);
    void SimplifySelection(double tolerance);
    void ApplyLODLevel(int level);
    void SelectSmall(double threshold);

public:
    void AverageSelection();
    void ApplyWorkingMode(bool deleteOriginals);
    void CancelWorkingMode();
    void EnterWorkingMode();

private:

    //------------------------------------------------------------------------------------
    //  Bounding box
    //------------------------------------------------------------------------------------

    void ComputeBoundingBox();
    void DrawBoundingBoxOverlay(AIAnnotatorMessage* msg);
    int  HitTestBBoxHandle(AIRealPoint artPt, double hitRadius = 6.0);
    bool HitTestBBoxRotateZone(AIRealPoint artPt, double innerRadius = 6.0, double outerRadius = 16.0);
    void ApplyBBoxTransform(int handleIdx, AIRealPoint newPos);
    void ApplyBBoxRotation(AIRealPoint newPos);

    void DrawPathAnchorHandles(AIAnnotatorMessage* msg);
    int  HitTestAnchorHandle(AIRealPoint artPt, double hitRadius = 6.0);
    int  HitTestBezierHandle(AIRealPoint artPt, double hitRadius = 5.0);
    void ApplyAnchorDrag(int anchorIdx, AIRealPoint newPos);
    void ApplyBezierDrag(int bezierIdx, AIRealPoint newPos);

    //------------------------------------------------------------------------------------
    //  Surface type helper
    //------------------------------------------------------------------------------------

    static const char* SurfaceTypeName(int surfaceType);

    //------------------------------------------------------------------------------------
    //  Working mode state
    //------------------------------------------------------------------------------------

    struct OriginalPathRecord {
        AIArtHandle art;
        AIReal      prevOpacity;
    };

    std::vector<OriginalPathRecord> fOriginalPaths;
    AIArtHandle                     fWorkingGroup = nullptr;
    AIArtHandle                     fSourceGroup = nullptr;   ///< Parent group of selected paths (nullptr = document root)
    std::string                     fSourceGroupName;         ///< Name of source group (for UI + auto-naming)
    std::string                     fSourceLayerName;         ///< Name of source layer
    bool                            fInWorkingMode = false;
    bool                            fExitingWorkingMode = false;  ///< Suppress isolation re-entry during Apply/Cancel

    //------------------------------------------------------------------------------------
    //  AverageSelection pipeline cache
    //------------------------------------------------------------------------------------

    std::vector<AIRealPoint>     fCachedSortedPoints;
    ShapeFitResult               fCachedShapeFit;
    std::vector<LODLevel>        fLODCache;
    AIArtHandle                  fPreviewPath = nullptr;

    //------------------------------------------------------------------------------------
    //  Detection + undo
    //------------------------------------------------------------------------------------

    const char*                  fLastDetectedShape = "---";
    UndoStack                    fUndoStack;
    std::atomic<int>             fLastKnownSelectionCount{0};
};

#endif // __CLEANUPMODULE_H__
