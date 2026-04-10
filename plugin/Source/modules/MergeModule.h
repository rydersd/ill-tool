#ifndef __MERGEMODULE_H__
#define __MERGEMODULE_H__

//========================================================================================
//  MergeModule — Endpoint scanning, merging, and undo
//
//  Handles: ScanEndpoints, MergeEndpoints, UndoMerge
//  Matches CEP smart merge spec: sm_scanEndpoints, sm_executeMerge, sm_doUndoMerge
//========================================================================================

#include "IllToolModule.h"
#include <vector>
#include <cfloat>

class MergeModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    bool CanUndo() override;
    void Undo() override;
    void DrawOverlay(AIAnnotatorMessage* msg) override;
    void OnDocumentChanged() override;

private:
    //------------------------------------------------------------------------------------
    //  Types
    //------------------------------------------------------------------------------------

    struct EndpointPair {
        AIArtHandle artA;
        AIArtHandle artB;
        bool        endA_is_end;
        bool        endB_is_start;
        double      distance;
    };

    struct MergeSnapshot {
        struct PathData {
            std::vector<AIPathSegment> segments;
            AIBoolean                  closed;
            AIArtHandle                parentRef;
        };
        std::vector<PathData>    originals;
        std::vector<AIArtHandle> mergedPaths;
        bool                     valid = false;
    };

    //------------------------------------------------------------------------------------
    //  State
    //------------------------------------------------------------------------------------

    std::vector<EndpointPair> fMergePairs;
    double                    fLastScanTolerance = 5.0;
    MergeSnapshot             fMergeSnapshot;

    //------------------------------------------------------------------------------------
    //  Operations
    //------------------------------------------------------------------------------------

    void ScanEndpoints(double tolerance);
    void MergeEndpoints(bool chainMerge, bool preserveHandles);
    void UndoMerge();

    static double PointDistance(const AIRealPoint& a, const AIRealPoint& b);
};

#endif // __MERGEMODULE_H__
