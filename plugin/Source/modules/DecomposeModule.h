#ifndef __DECOMPOSEMODULE_H__
#define __DECOMPOSEMODULE_H__

//========================================================================================
//  DecomposeModule — Auto-Decompose (Stage 14)
//
//  Handles: Decompose, DecomposeAccept, DecomposeAcceptOne, DecomposeSplit,
//           DecomposeMergeGroups, DecomposeCancel
//  State: clusters, active analysis flag
//  Drawing: color-coded cluster overlay (DrawDecomposeOverlay)
//========================================================================================

#include "IllToolModule.h"
#include <vector>

class IllToolPlugin;  // forward — for ComputeSignature access

class DecomposeModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    void DrawOverlay(AIAnnotatorMessage* msg) override;
    void OnDocumentChanged() override;

    //------------------------------------------------------------------------------------
    //  Query
    //------------------------------------------------------------------------------------

    /** Returns true if a decompose analysis is active. */
    bool IsActive() const { return fDecomposeActive; }

private:
    //------------------------------------------------------------------------------------
    //  Types
    //------------------------------------------------------------------------------------

    struct PathPairScore {
        size_t indexA;
        size_t indexB;
        float  endpointDist;
        float  signatureSim;
        float  bboxOverlap;
    };

    struct DecomposeCluster {
        std::vector<AIArtHandle> paths;
        const char* dominantType;
        float cleanupScore;
        int clusterIndex;
        AIRGBColor overlayColor;
    };

    //------------------------------------------------------------------------------------
    //  State
    //------------------------------------------------------------------------------------

    std::vector<DecomposeCluster> fClusters;
    bool fDecomposeActive = false;

    //------------------------------------------------------------------------------------
    //  Operations
    //------------------------------------------------------------------------------------

    void RunDecompose(float sensitivity);
    void AcceptDecompose();
    void AcceptCluster(int clusterIndex);
    void SplitCluster(int clusterIndex);
    void MergeDecomposeClusters(int clusterA, int clusterB);
    void CancelDecompose();

    //------------------------------------------------------------------------------------
    //  Internal helpers
    //------------------------------------------------------------------------------------

    static float ComputeEndpointDistance(AIArtHandle a, AIArtHandle b);
    float ComputeSignatureSimilarity(AIArtHandle a, AIArtHandle b);
    static float ComputeBBoxOverlap(AIArtHandle a, AIArtHandle b);
    void BuildProximityGraph(const std::vector<AIArtHandle>& paths,
                             float threshold,
                             std::vector<PathPairScore>& edges);
    void ClusterConnectedComponents(const std::vector<AIArtHandle>& paths,
                                     const std::vector<PathPairScore>& edges);
};

#endif // __DECOMPOSEMODULE_H__
