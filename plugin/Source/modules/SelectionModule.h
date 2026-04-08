#ifndef __SELECTIONMODULE_H__
#define __SELECTIONMODULE_H__

//========================================================================================
//  SelectionModule — Polygon Lasso + Smart Select (Boundary Signature Matching)
//
//  Handles: LassoClose, LassoClear, SmartSelect
//  Mouse: polygon lasso click-to-add-vertex, double-click-to-close
//  Drawing: lasso polygon outline overlay
//========================================================================================

#include "IllToolModule.h"
#include "DrawCommands.h"
#include <vector>

class SelectionModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    bool HandleMouseDown(AIToolMessage* msg) override;
    bool HandleMouseDrag(AIToolMessage* msg) override;
    bool HandleMouseUp(AIToolMessage* msg) override;
    void DrawOverlay(AIAnnotatorMessage* msg) override;
    void OnDocumentChanged() override;

    //------------------------------------------------------------------------------------
    //  Boundary signature for Smart Select (Stage 9)
    //------------------------------------------------------------------------------------

    struct BoundarySignature {
        double totalLength   = 0;
        double avgCurvature  = 0;
        double startAngle    = 0;
        double endAngle      = 0;
        bool   isClosed      = false;
        int    segmentCount  = 0;
    };

private:
    //------------------------------------------------------------------------------------
    //  Polygon lasso state
    //------------------------------------------------------------------------------------

    std::vector<AIRealPoint> fPolygonVertices;
    AIRealPoint              fLastCursorPos = {0, 0};
    double                   fLastClickTime = 0;

    static constexpr double kDoubleClickThreshold = 0.3;

    //------------------------------------------------------------------------------------
    //  Polygon lasso helpers
    //------------------------------------------------------------------------------------

    void UpdatePolygonOverlay();
    void ExecutePolygonSelection();
    static bool PointInPolygon(const AIRealPoint& pt,
                               const std::vector<AIRealPoint>& polygon);

    //------------------------------------------------------------------------------------
    //  Smart Select helpers (public — DecomposeModule needs ComputeSignature)
    //------------------------------------------------------------------------------------
public:
    BoundarySignature ComputeSignature(AIArtHandle path);

private:
    void SelectMatchingPaths(const BoundarySignature& refSig,
                             double thresholdPct,
                             AIArtHandle hitArt);
};

#endif // __SELECTIONMODULE_H__
