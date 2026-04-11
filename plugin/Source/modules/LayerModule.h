#ifndef __LAYERMODULE_H__
#define __LAYERMODULE_H__

#include "IllToolModule.h"
#include <vector>
#include <string>
#include <unordered_map>
#include <chrono>

enum class LayerNodeType : int {
    Layer    = 0,
    Group    = 1,
    NamedPath = 2,
    Collapsed = 3   // "N unnamed paths" placeholder
};

struct LayerTreeNode {
    LayerNodeType type = LayerNodeType::Layer;
    std::string   name;
    AIArtHandle   artHandle   = nullptr;
    AILayerHandle layerHandle = nullptr;
    int           nodeID      = 0;
    bool          visible     = true;
    bool          locked      = false;
    bool          isSelected  = false;
    float         colorR = 0.5f, colorG = 0.5f, colorB = 0.5f;
    int           unnamedCount = 0;
    std::vector<LayerTreeNode> children;
};

struct ArtFeatureVector {
    int strokeWeightClass = -1;  // 0=none, 1=thin(<0.5), 2=medium(<2), 3=thick(<5), 4=heavy
    int fillType          = -1;  // 0=none, 1=solid, 2=gradient, 3=pattern
    int strokeColorClass  = -1;  // 0=none, 1=dark, 2=medium, 3=light, 4=chromatic
    int opacityClass      = -1;  // 0=full, 1=high(>70%), 2=medium(>30%), 3=low
    int zPosition         = -1;  // 0=bottom, 1=lower-mid, 2=upper-mid, 3=top
    int sizeClass         = -1;  // 0=tiny, 1=small, 2=medium, 3=large
    int artType           = -1;  // maps to AIArtType
};

/** A learning rule that maps art features to a suggested layer name. */
struct LearningRule {
    ArtFeatureVector conditions;
    std::string suggestedLayer;
    double confidence = 0.5;
    int applyCount    = 0;
    std::string lastApplied;  // ISO date string
};

class LayerModule : public IllToolModule {
public:
    LayerModule() = default;
    ~LayerModule() override = default;

    bool HandleOp(const PluginOp& op) override;
    void OnSelectionChanged() override;
    void OnDocumentChanged() override;

    /** Called from ProcessOperationQueue to check if tree needs refresh. */
    void TickRefresh();

    /** Mark tree as needing a rescan. */
    void MarkTreeDirty() { fTreeDirty = true; }

private:
    // Tree state
    std::vector<LayerTreeNode> fTree;
    std::unordered_map<int, AIArtHandle> fArtHandleMap;
    std::unordered_map<int, AILayerHandle> fLayerHandleMap;
    int fNextNodeID = 1;
    bool fTreeDirty = true;
    std::chrono::steady_clock::time_point fLastScanTime;

    // Core tree operations
    void ScanDocumentHierarchy();
    void WalkArtChildren(AIArtHandle parent, LayerTreeNode& parentNode);
    void SerializeTreeToJSON();

    // Node manipulation
    void SetNodeVisible(int nodeID, bool visible);
    void SetNodeLocked(int nodeID, bool locked);
    void ReorderNode(int srcID, int dstID, bool insertBefore);
    void RenameNode(int nodeID, const std::string& newName);
    void CreateLayer(const std::string& name);
    void DeleteNode(int nodeID);
    void MoveArtToLayer(int artNodeID, int layerNodeID);
    void AutoOrganize();
    void SelectNode(int nodeID);
    void GroupSelectedItems(const std::string& groupName);

    // Preset system
    void SavePreset(const std::string& name);
    void LoadPreset(const std::string& name);
    static std::string GetPresetDirectory();

    // Learning engine
    ArtFeatureVector ExtractArtFeatures(AIArtHandle art);
    void RecordRenameForLearning(AIArtHandle art, const std::string& newName);
    void RecordMoveForLearning(AIArtHandle art, int layerNodeID);
    std::string SuggestLayerForArt(AIArtHandle art);
    void LoadLearningRules();
    void SaveLearningRules();
    static std::string GetRulesPath();

    std::vector<LearningRule> fRules;
    bool fRulesLoaded = false;

    // Handle resolution
    AIArtHandle ResolveArt(int nodeID);
    AILayerHandle ResolveLayer(int nodeID);
};

#endif
