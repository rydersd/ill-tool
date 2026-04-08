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

    /** The working group art handle (non-null when in working mode). */
    AIArtHandle GetWorkingGroup() const { return fWorkingGroup; }

    /** Cached selection count — updated from OnSelectionChanged. */
    int GetSelectedAnchorCount() const { return fLastKnownSelectionCount.load(); }

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
        int dragHandle = -1;        ///< -1=none, 0-3=corners, 4-7=midpoints
        AIRealPoint dragStart;      ///< Mouse position at drag start (artwork coords)
    };

    BoundingBoxState fBBox;

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
    void ApplyBBoxTransform(int handleIdx, AIRealPoint newPos);

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
    bool                            fInWorkingMode = false;

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
