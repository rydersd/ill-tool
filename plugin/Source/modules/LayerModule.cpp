//========================================================================================
//  LayerModule — Full SDK-based layer tree management, learning engine, and presets
//  Replaces stubs with real AILayerSuite / AIArtSuite implementations.
//========================================================================================

#include "IllustratorSDK.h"
#include "LayerModule.h"
#include "IllToolPlugin.h"
#include "IllToolSuites.h"
#include "HttpBridge.h"
#include "vendor/json.hpp"

#include <cstdio>
#include <cmath>
#include <algorithm>
#include <sys/stat.h>

using json = nlohmann::json;

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Operation dispatch
//========================================================================================

bool LayerModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::LayerScanTree:
            fprintf(stderr, "[LayerModule] ScanTree\n");
            ScanDocumentHierarchy();
            return true;
        case OpType::LayerSetVisible:
            fprintf(stderr, "[LayerModule] SetVisible node=%d\n", op.intParam);
            SetNodeVisible(op.intParam, op.boolParam1);
            return true;
        case OpType::LayerSetLocked:
            fprintf(stderr, "[LayerModule] SetLocked node=%d\n", op.intParam);
            SetNodeLocked(op.intParam, op.boolParam1);
            return true;
        case OpType::LayerReorder:
            fprintf(stderr, "[LayerModule] Reorder src=%d dst=%.0f\n", op.intParam, op.param1);
            ReorderNode(op.intParam, (int)op.param1, op.boolParam1);
            return true;
        case OpType::LayerRename:
            fprintf(stderr, "[LayerModule] Rename node=%d name=%s\n", op.intParam, op.strParam.c_str());
            RenameNode(op.intParam, op.strParam);
            return true;
        case OpType::LayerCreate:
            fprintf(stderr, "[LayerModule] Create layer=%s\n", op.strParam.c_str());
            CreateLayer(op.strParam);
            return true;
        case OpType::LayerDelete:
            fprintf(stderr, "[LayerModule] Delete node=%d\n", op.intParam);
            DeleteNode(op.intParam);
            return true;
        case OpType::LayerMoveArt:
            fprintf(stderr, "[LayerModule] MoveArt art=%d layer=%.0f\n", op.intParam, op.param1);
            MoveArtToLayer(op.intParam, (int)op.param1);
            return true;
        case OpType::LayerAutoOrganize:
            fprintf(stderr, "[LayerModule] AutoOrganize\n");
            AutoOrganize();
            return true;
        case OpType::LayerPresetSave:
            fprintf(stderr, "[LayerModule] PresetSave name=%s\n", op.strParam.c_str());
            SavePreset(op.strParam);
            return true;
        case OpType::LayerPresetLoad:
            fprintf(stderr, "[LayerModule] PresetLoad name=%s\n", op.strParam.c_str());
            LoadPreset(op.strParam);
            return true;
        case OpType::LayerSelectNode:
            fprintf(stderr, "[LayerModule] SelectNode node=%d\n", op.intParam);
            SelectNode(op.intParam);
            return true;
        case OpType::LayerGroupSelected:
            fprintf(stderr, "[LayerModule] GroupSelected name=%s\n", op.strParam.c_str());
            GroupSelectedItems(op.strParam);
            return true;
        default:
            return false;
    }
}

//========================================================================================
//  Tick / Notification
//========================================================================================

void LayerModule::TickRefresh()
{
    if (!fTreeDirty) return;

    auto now = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - fLastScanTime).count();
    if (elapsed < 500) return;  // throttle to max 2Hz

    fTreeDirty = false;
    fLastScanTime = now;
    ScanDocumentHierarchy();
}

void LayerModule::OnSelectionChanged()
{
    fTreeDirty = true;
}

void LayerModule::OnDocumentChanged()
{
    fTree.clear();
    fArtHandleMap.clear();
    fLayerHandleMap.clear();
    fNextNodeID = 1;
    fTreeDirty = true;
    fRulesLoaded = false;  // reload rules for new document context
}

//========================================================================================
//  ScanDocumentHierarchy — walk all layers, groups, named paths and build the tree
//========================================================================================

void LayerModule::ScanDocumentHierarchy()
{
    fTree.clear();
    fArtHandleMap.clear();
    fLayerHandleMap.clear();
    fNextNodeID = 1;

    if (!sAILayer || !sAIArt) return;

    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);

    for (ai::int32 i = 0; i < layerCount; i++) {
        AILayerHandle layer = nullptr;
        if (sAILayer->GetNthLayer(i, &layer) != kNoErr || !layer) continue;

        LayerTreeNode layerNode;
        layerNode.type = LayerNodeType::Layer;
        layerNode.nodeID = fNextNodeID++;
        layerNode.layerHandle = layer;

        // Get layer title
        ai::UnicodeString title;
        sAILayer->GetLayerTitle(layer, title);
        layerNode.name = title.as_UTF8();

        // Get visibility/lock
        AIBoolean vis = true, edit = true;
        sAILayer->GetLayerVisible(layer, &vis);
        sAILayer->GetLayerEditable(layer, &edit);
        layerNode.visible = (vis != 0);
        layerNode.locked = (edit == 0);  // editable=false means locked

        // Get layer color (AIRGBColor uses ai::uint16 values 0-65535)
        AIRGBColor color;
        if (sAILayer->GetLayerColor(layer, &color) == kNoErr) {
            layerNode.colorR = color.red   / 65535.0f;
            layerNode.colorG = color.green / 65535.0f;
            layerNode.colorB = color.blue  / 65535.0f;
        }

        // Store handle mapping
        fLayerHandleMap[layerNode.nodeID] = layer;

        // Walk art inside this layer — GetFirstArtOfLayer gives the layer group
        AIArtHandle layerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(layer, &layerArt);
        if (layerArt) {
            WalkArtChildren(layerArt, layerNode);
        }

        fTree.push_back(std::move(layerNode));
    }

    // Serialize to JSON and push to bridge
    SerializeTreeToJSON();
}

//========================================================================================
//  WalkArtChildren — recursively walk children of an art group
//========================================================================================

void LayerModule::WalkArtChildren(AIArtHandle parent, LayerTreeNode& parentNode)
{
    AIArtHandle child = nullptr;
    sAIArt->GetArtFirstChild(parent, &child);

    int unnamedCount = 0;

    while (child) {
        short artType = 0;
        sAIArt->GetArtType(child, &artType);

        ai::UnicodeString artName;
        ASBoolean isDefaultName = true;
        sAIArt->GetArtName(child, artName, &isDefaultName);
        bool hasName = !isDefaultName;
        std::string name = hasName ? artName.as_UTF8() : "";

        // Container types: recurse into children (groups, symbols, plugins, compounds)
        bool isContainer = (artType == kGroupArt || artType == kSymbolArt ||
                           artType == kPluginArt || artType == kCompoundPathArt);

        if (isContainer) {
            // Always include container types in the tree
            LayerTreeNode groupNode;
            groupNode.type = LayerNodeType::Group;
            groupNode.nodeID = fNextNodeID++;
            groupNode.artHandle = child;

            if (name.empty()) {
                switch (artType) {
                    case kGroupArt:        groupNode.name = "Group"; break;
                    case kSymbolArt:       groupNode.name = "<Symbol>"; break;
                    case kPluginArt:       groupNode.name = "<Plugin>"; break;
                    case kCompoundPathArt: groupNode.name = "<Compound>"; break;
                    default:               groupNode.name = "Group"; break;
                }
            } else {
                groupNode.name = name;
            }

            // Check visibility/lock via art user attributes
            ai::int32 attrs = 0;
            sAIArt->GetArtUserAttr(child, kArtHidden | kArtLocked, &attrs);
            groupNode.visible = !(attrs & kArtHidden);
            groupNode.locked = (attrs & kArtLocked) != 0;

            // Check if selected
            ai::int32 selAttr = 0;
            sAIArt->GetArtUserAttr(child, kArtSelected, &selAttr);
            groupNode.isSelected = (selAttr & kArtSelected) != 0;

            fArtHandleMap[groupNode.nodeID] = child;

            // Recurse into children
            WalkArtChildren(child, groupNode);

            parentNode.children.push_back(std::move(groupNode));
        }
        else {
            // Leaf art: paths, rasters, placed, text, mesh, etc.
            // Generate a descriptive name for unnamed items based on type
            std::string displayName = name;
            if (displayName.empty()) {
                switch (artType) {
                    case kRasterArt:       displayName = "<Image>"; break;
                    case kPlacedArt:       displayName = "<Placed>"; break;
                    case kTextFrameArt:    displayName = "<Text>"; break;
                    case kMeshArt:         displayName = "<Mesh>"; break;
                    case kForeignArt:      displayName = "<Foreign>"; break;
                    case kChartArt:        displayName = "<Chart>"; break;
                    case kPathArt:
                    default:               break;  // unnamed paths stay collapsed
                }
            }

            if (!displayName.empty()) {
                // Named art or typed art (image, text, etc.) — include in tree
                LayerTreeNode artNode;
                artNode.type = LayerNodeType::NamedPath;
                artNode.nodeID = fNextNodeID++;
                artNode.artHandle = child;
                artNode.name = displayName;

                ai::int32 attrs = 0;
                sAIArt->GetArtUserAttr(child, kArtHidden | kArtLocked, &attrs);
                artNode.visible = !(attrs & kArtHidden);
                artNode.locked = (attrs & kArtLocked) != 0;

                ai::int32 selAttr = 0;
                sAIArt->GetArtUserAttr(child, kArtSelected, &selAttr);
                artNode.isSelected = (selAttr & kArtSelected) != 0;

                fArtHandleMap[artNode.nodeID] = child;
                parentNode.children.push_back(std::move(artNode));
            } else {
                unnamedCount++;
            }
        }

        AIArtHandle next = nullptr;
        sAIArt->GetArtSibling(child, &next);
        child = next;
    }

    // Add collapsed placeholder for unnamed paths
    if (unnamedCount > 0) {
        LayerTreeNode collapsed;
        collapsed.type = LayerNodeType::Collapsed;
        collapsed.nodeID = fNextNodeID++;
        collapsed.name = std::to_string(unnamedCount) + " unnamed paths";
        collapsed.unnamedCount = unnamedCount;
        parentNode.children.push_back(std::move(collapsed));
    }
}

//========================================================================================
//  NodeToJSON / SerializeTreeToJSON — convert tree to JSON and push to bridge
//========================================================================================

// NodeToJSON — convert a single tree node to JSON (recursive, file-local)
static json NodeToJSON(const LayerTreeNode& node)
{
    json j;
    j["id"] = node.nodeID;
    j["type"] = (int)node.type;
    j["name"] = node.name;
    j["visible"] = node.visible;
    j["locked"] = node.locked;
    j["selected"] = node.isSelected;
    j["color"] = { node.colorR, node.colorG, node.colorB };
    j["unnamed"] = node.unnamedCount;

    if (!node.children.empty()) {
        j["children"] = json::array();
        for (auto& child : node.children) {
            j["children"].push_back(NodeToJSON(child));
        }
    }
    return j;
}

void LayerModule::SerializeTreeToJSON()
{
    json root = json::array();
    for (auto& node : fTree) {
        root.push_back(NodeToJSON(node));
    }
    std::string jsonStr = root.dump();
    BridgeSetLayerTreeJSON(jsonStr);
    BridgeSetLayerTreeDirty(true);
    fprintf(stderr, "[LayerModule] Tree serialized: %d top-level layers, %zu bytes\n",
            (int)fTree.size(), jsonStr.size());
}

//========================================================================================
//  SetNodeVisible — toggle visibility for a layer or art object
//========================================================================================

void LayerModule::SetNodeVisible(int nodeID, bool visible)
{
    // Check if it's a layer
    auto layerIt = fLayerHandleMap.find(nodeID);
    if (layerIt != fLayerHandleMap.end()) {
        sAILayer->SetLayerVisible(layerIt->second, visible);
        fTreeDirty = true;
        InvalidateFullView();
        fprintf(stderr, "[LayerModule] SetNodeVisible: layer %d -> %s\n", nodeID, visible ? "true" : "false");
        return;
    }
    // Otherwise it's art
    AIArtHandle art = ResolveArt(nodeID);
    if (art) {
        sAIArt->SetArtUserAttr(art, kArtHidden, visible ? 0 : kArtHidden);
        fTreeDirty = true;
        InvalidateFullView();
        fprintf(stderr, "[LayerModule] SetNodeVisible: art %d -> %s\n", nodeID, visible ? "true" : "false");
    }
}

//========================================================================================
//  SetNodeLocked — toggle lock for a layer or art object
//========================================================================================

void LayerModule::SetNodeLocked(int nodeID, bool locked)
{
    auto layerIt = fLayerHandleMap.find(nodeID);
    if (layerIt != fLayerHandleMap.end()) {
        sAILayer->SetLayerEditable(layerIt->second, !locked);
        fTreeDirty = true;
        fprintf(stderr, "[LayerModule] SetNodeLocked: layer %d -> %s\n", nodeID, locked ? "true" : "false");
        return;
    }
    AIArtHandle art = ResolveArt(nodeID);
    if (art) {
        sAIArt->SetArtUserAttr(art, kArtLocked, locked ? kArtLocked : 0);
        fTreeDirty = true;
        fprintf(stderr, "[LayerModule] SetNodeLocked: art %d -> %s\n", nodeID, locked ? "true" : "false");
    }
}

//========================================================================================
//  RenameNode — rename a layer or art object
//========================================================================================

void LayerModule::RenameNode(int nodeID, const std::string& newName)
{
    auto layerIt = fLayerHandleMap.find(nodeID);
    if (layerIt != fLayerHandleMap.end()) {
        sAILayer->SetLayerTitle(layerIt->second, ai::UnicodeString(newName));
        fTreeDirty = true;
        fprintf(stderr, "[LayerModule] RenameNode: layer %d -> '%s'\n", nodeID, newName.c_str());
        return;
    }
    AIArtHandle art = ResolveArt(nodeID);
    if (art) {
        sAIArt->SetArtName(art, ai::UnicodeString(newName));
        RecordRenameForLearning(art, newName);
        fTreeDirty = true;
        fprintf(stderr, "[LayerModule] RenameNode: art %d -> '%s'\n", nodeID, newName.c_str());
    }
}

//========================================================================================
//  CreateLayer — insert a new top-level layer with the given name
//========================================================================================

void LayerModule::CreateLayer(const std::string& name)
{
    if (!sAILayer) return;

    AILayerHandle newLayer = nullptr;
    ASErr err = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &newLayer);
    if (err == kNoErr && newLayer) {
        sAILayer->SetLayerTitle(newLayer, ai::UnicodeString(name));
        sAILayer->SetCurrentLayer(newLayer);
        fTreeDirty = true;
        InvalidateFullView();
        fprintf(stderr, "[LayerModule] Created layer: %s\n", name.c_str());
    } else {
        fprintf(stderr, "[LayerModule] CreateLayer failed: %d\n", (int)err);
    }
}

//========================================================================================
//  DeleteNode — delete a layer or art object
//========================================================================================

void LayerModule::DeleteNode(int nodeID)
{
    auto layerIt = fLayerHandleMap.find(nodeID);
    if (layerIt != fLayerHandleMap.end()) {
        ASErr err = sAILayer->DeleteLayer(layerIt->second);
        if (err == kNoErr) {
            fLayerHandleMap.erase(layerIt);
            fTreeDirty = true;
            InvalidateFullView();
            fprintf(stderr, "[LayerModule] Deleted layer node %d\n", nodeID);
        } else {
            fprintf(stderr, "[LayerModule] DeleteLayer failed: %d (last layer?)\n", (int)err);
        }
        return;
    }
    AIArtHandle art = ResolveArt(nodeID);
    if (art) {
        ASErr err = sAIArt->DisposeArt(art);
        if (err == kNoErr) {
            fArtHandleMap.erase(nodeID);
            fTreeDirty = true;
            InvalidateFullView();
            fprintf(stderr, "[LayerModule] Deleted art node %d\n", nodeID);
        } else {
            fprintf(stderr, "[LayerModule] DisposeArt failed: %d\n", (int)err);
        }
    }
}

//========================================================================================
//  ReorderNode — move art or layers in the stacking order
//========================================================================================

void LayerModule::ReorderNode(int srcID, int dstID, bool insertBefore)
{
    // Art-to-art reorder
    AIArtHandle srcArt = ResolveArt(srcID);
    AIArtHandle dstArt = ResolveArt(dstID);

    if (srcArt && dstArt) {
        ASErr err = sAIArt->ReorderArt(srcArt, insertBefore ? kPlaceAbove : kPlaceBelow, dstArt);
        if (err == kNoErr) {
            fTreeDirty = true;
            InvalidateFullView();
            fprintf(stderr, "[LayerModule] Reordered art %d %s art %d\n", srcID,
                    insertBefore ? "before" : "after", dstID);
        } else {
            fprintf(stderr, "[LayerModule] ReorderArt failed: %d\n", (int)err);
        }
        return;
    }

    // Art-to-layer: move art into a layer
    if (srcArt) {
        auto dstLayerIt = fLayerHandleMap.find(dstID);
        if (dstLayerIt != fLayerHandleMap.end()) {
            AIArtHandle layerArt = nullptr;
            sAIArt->GetFirstArtOfLayer(dstLayerIt->second, &layerArt);
            if (layerArt) {
                ASErr err = sAIArt->ReorderArt(srcArt, kPlaceInsideOnTop, layerArt);
                if (err == kNoErr) {
                    fTreeDirty = true;
                    InvalidateFullView();
                    fprintf(stderr, "[LayerModule] Moved art %d into layer %d\n", srcID, dstID);
                }
            }
        }
        return;
    }

    // Layer-to-layer reorder: create new at target, move art, delete source
    auto srcLayerIt = fLayerHandleMap.find(srcID);
    auto dstLayerIt = fLayerHandleMap.find(dstID);
    if (srcLayerIt != fLayerHandleMap.end() && dstLayerIt != fLayerHandleMap.end()) {
        AILayerHandle newLayer = nullptr;
        ASErr err = sAILayer->InsertLayer(dstLayerIt->second,
            insertBefore ? kPlaceAbove : kPlaceBelow, &newLayer);
        if (err != kNoErr || !newLayer) {
            fprintf(stderr, "[LayerModule] Layer reorder InsertLayer failed: %d\n", (int)err);
            return;
        }

        // Copy properties from source to new layer
        ai::UnicodeString title;
        sAILayer->GetLayerTitle(srcLayerIt->second, title);
        sAILayer->SetLayerTitle(newLayer, title);

        AIBoolean vis = true, edit = true;
        sAILayer->GetLayerVisible(srcLayerIt->second, &vis);
        sAILayer->GetLayerEditable(srcLayerIt->second, &edit);
        sAILayer->SetLayerVisible(newLayer, vis);
        sAILayer->SetLayerEditable(newLayer, edit);

        AIRGBColor color;
        if (sAILayer->GetLayerColor(srcLayerIt->second, &color) == kNoErr) {
            sAILayer->SetLayerColor(newLayer, color);
        }

        // Move all art from source to new layer
        AIArtHandle srcLayerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(srcLayerIt->second, &srcLayerArt);
        AIArtHandle dstLayerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(newLayer, &dstLayerArt);

        if (srcLayerArt && dstLayerArt) {
            AIArtHandle child = nullptr;
            sAIArt->GetArtFirstChild(srcLayerArt, &child);
            while (child) {
                AIArtHandle next = nullptr;
                sAIArt->GetArtSibling(child, &next);
                sAIArt->ReorderArt(child, kPlaceInsideOnTop, dstLayerArt);
                child = next;
            }
        }

        // Delete source layer
        sAILayer->DeleteLayer(srcLayerIt->second);
        fTreeDirty = true;
        InvalidateFullView();
        fprintf(stderr, "[LayerModule] Reordered layer %d %s layer %d\n", srcID,
                insertBefore ? "before" : "after", dstID);
    }
}

//========================================================================================
//  MoveArtToLayer — move an art object into a target layer
//========================================================================================

void LayerModule::MoveArtToLayer(int artNodeID, int layerNodeID)
{
    AIArtHandle art = ResolveArt(artNodeID);
    auto layerIt = fLayerHandleMap.find(layerNodeID);
    if (!art || layerIt == fLayerHandleMap.end()) {
        fprintf(stderr, "[LayerModule] MoveArtToLayer: invalid art=%d or layer=%d\n", artNodeID, layerNodeID);
        return;
    }

    AIArtHandle layerArt = nullptr;
    sAIArt->GetFirstArtOfLayer(layerIt->second, &layerArt);
    if (layerArt) {
        ASErr err = sAIArt->ReorderArt(art, kPlaceInsideOnTop, layerArt);
        if (err == kNoErr) {
            RecordMoveForLearning(art, layerNodeID);
            fTreeDirty = true;
            InvalidateFullView();
            fprintf(stderr, "[LayerModule] Moved art %d to layer %d\n", artNodeID, layerNodeID);
        } else {
            fprintf(stderr, "[LayerModule] MoveArtToLayer ReorderArt failed: %d\n", (int)err);
        }
    }
}

//========================================================================================
//  AutoOrganize — use learning rules to assign selected art to appropriate layers
//========================================================================================

void LayerModule::AutoOrganize()
{
    LoadLearningRules();

    if (!sAIMatchingArt || !sAIArt) return;

    // Get selected art
    AIMatchingArtSpec spec(kAnyArt, kArtSelected, kArtSelected);
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0) {
        fprintf(stderr, "[LayerModule] AutoOrganize: no selected art\n");
        return;
    }

    int moved = 0;
    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];
        std::string suggestion = SuggestLayerForArt(art);
        if (suggestion.empty()) continue;  // no matching rule — leave in place

        // Find or create the target layer
        AILayerHandle targetLayer = nullptr;
        ai::UnicodeString uSuggestion(suggestion);
        sAILayer->GetLayerByTitle(&targetLayer, uSuggestion);

        if (!targetLayer) {
            // Create the layer
            ASErr layerErr = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &targetLayer);
            if (layerErr == kNoErr && targetLayer) {
                sAILayer->SetLayerTitle(targetLayer, uSuggestion);
                fprintf(stderr, "[LayerModule] AutoOrganize: created layer '%s'\n", suggestion.c_str());
            } else {
                continue;
            }
        }

        AIArtHandle layerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(targetLayer, &layerArt);
        if (layerArt) {
            ASErr moveErr = sAIArt->ReorderArt(art, kPlaceInsideOnTop, layerArt);
            if (moveErr == kNoErr) moved++;
        }
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    fTreeDirty = true;
    InvalidateFullView();
    fprintf(stderr, "[LayerModule] AutoOrganize: moved %d/%d items\n", moved, (int)numMatches);
}

//========================================================================================
//  ExtractArtFeatures — build a feature vector from an art object's visual properties
//========================================================================================

ArtFeatureVector LayerModule::ExtractArtFeatures(AIArtHandle art)
{
    ArtFeatureVector fv;
    if (!art || !sAIPathStyle) return fv;

    short artType = 0;
    sAIArt->GetArtType(art, &artType);
    fv.artType = artType;

    if (artType != kPathArt && artType != kCompoundPathArt) return fv;

    AIPathStyle style;
    AIBoolean hasAdvFill = false;
    memset(&style, 0, sizeof(style));
    if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) != kNoErr) return fv;

    // Stroke weight class
    if (!style.strokePaint) {
        fv.strokeWeightClass = 0;
    } else if (style.stroke.width < 0.5) {
        fv.strokeWeightClass = 1;
    } else if (style.stroke.width < 2.0) {
        fv.strokeWeightClass = 2;
    } else if (style.stroke.width < 5.0) {
        fv.strokeWeightClass = 3;
    } else {
        fv.strokeWeightClass = 4;
    }

    // Fill type
    if (!style.fillPaint) {
        fv.fillType = 0;
    } else if (style.fill.color.kind == kThreeColor || style.fill.color.kind == kFourColor) {
        fv.fillType = 1;  // solid
    } else if (style.fill.color.kind == kGradient) {
        fv.fillType = 2;
    } else if (style.fill.color.kind == kPattern) {
        fv.fillType = 3;
    } else {
        fv.fillType = 1;  // treat custom/gray as solid
    }

    // Stroke color class
    if (!style.strokePaint) {
        fv.strokeColorClass = 0;
    } else {
        float r = 0, g = 0, b = 0;
        if (style.stroke.color.kind == kThreeColor) {
            r = (float)style.stroke.color.c.rgb.red;
            g = (float)style.stroke.color.c.rgb.green;
            b = (float)style.stroke.color.c.rgb.blue;
        } else if (style.stroke.color.kind == kGrayColor) {
            float gray = (float)style.stroke.color.c.g.gray;
            r = g = b = 1.0f - gray;  // gray 0=black, 1=white in some contexts
        }

        float brightness = (r + g + b) / 3.0f;
        float maxC = std::max({r, g, b});
        float minC = std::min({r, g, b});
        bool chromatic = (maxC - minC) > 0.2f;

        if (chromatic) {
            fv.strokeColorClass = 4;
        } else if (brightness < 0.3f) {
            fv.strokeColorClass = 1;  // dark
        } else if (brightness < 0.6f) {
            fv.strokeColorClass = 2;  // medium
        } else {
            fv.strokeColorClass = 3;  // light
        }
    }

    // Opacity class — default to full; would need AIBlendStyleSuite for precision
    fv.opacityClass = 0;

    // Size class — from bounding box
    AIRealRect bounds;
    if (sAIArt->GetArtBounds(art, &bounds) == kNoErr) {
        double w = std::abs(bounds.right - bounds.left);
        double h = std::abs(bounds.top - bounds.bottom);
        double area = w * h;
        if (area < 100.0)       fv.sizeClass = 0;  // tiny
        else if (area < 2500.0) fv.sizeClass = 1;  // small
        else if (area < 25000.0) fv.sizeClass = 2; // medium
        else                     fv.sizeClass = 3; // large
    }

    return fv;
}

//========================================================================================
//  Learning Rules — Load / Save / Match
//========================================================================================

std::string LayerModule::GetRulesPath()
{
    const char* home = getenv("HOME");
    if (!home) return "";
    std::string dir = std::string(home) + "/Library/Application Support/illtool";
    mkdir(dir.c_str(), 0755);
    return dir + "/layer_rules.json";
}

void LayerModule::LoadLearningRules()
{
    if (fRulesLoaded) return;
    fRulesLoaded = true;

    std::string path = GetRulesPath();
    if (path.empty()) return;

    FILE* f = fopen(path.c_str(), "r");
    if (!f) {
        fprintf(stderr, "[LayerModule] No existing learning rules at %s\n", path.c_str());
        return;
    }

    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0) { fclose(f); return; }

    std::string content(sz, '\0');
    size_t bytesRead = fread(&content[0], 1, sz, f);
    fclose(f);
    if (bytesRead == 0) return;
    content.resize(bytesRead);

    try {
        json j = json::parse(content);
        if (!j.contains("rules") || !j["rules"].is_array()) return;

        for (auto& rule : j["rules"]) {
            LearningRule lr;
            if (rule.contains("conditions")) {
                auto& c = rule["conditions"];
                lr.conditions.strokeWeightClass = c.value("strokeWeightClass", -1);
                lr.conditions.fillType          = c.value("fillType", -1);
                lr.conditions.strokeColorClass  = c.value("strokeColorClass", -1);
                lr.conditions.opacityClass      = c.value("opacityClass", -1);
                lr.conditions.sizeClass         = c.value("sizeClass", -1);
                lr.conditions.artType           = c.value("artType", -1);
            }
            lr.suggestedLayer = rule.value("suggested_layer", "");
            lr.confidence     = rule.value("confidence", 0.5);
            lr.applyCount     = rule.value("apply_count", 0);
            lr.lastApplied    = rule.value("last_applied", "");
            fRules.push_back(lr);
        }
        fprintf(stderr, "[LayerModule] Loaded %d learning rules\n", (int)fRules.size());
    } catch (const std::exception& e) {
        fprintf(stderr, "[LayerModule] Failed to parse learning rules: %s\n", e.what());
    }
}

void LayerModule::SaveLearningRules()
{
    std::string path = GetRulesPath();
    if (path.empty()) return;

    json j;
    j["version"] = 1;
    j["rules"] = json::array();
    for (auto& lr : fRules) {
        json rule;
        rule["conditions"] = {
            {"strokeWeightClass", lr.conditions.strokeWeightClass},
            {"fillType",          lr.conditions.fillType},
            {"strokeColorClass",  lr.conditions.strokeColorClass},
            {"opacityClass",      lr.conditions.opacityClass},
            {"sizeClass",         lr.conditions.sizeClass},
            {"artType",           lr.conditions.artType}
        };
        rule["suggested_layer"] = lr.suggestedLayer;
        rule["confidence"]      = lr.confidence;
        rule["apply_count"]     = lr.applyCount;
        rule["last_applied"]    = lr.lastApplied;
        j["rules"].push_back(rule);
    }

    FILE* f = fopen(path.c_str(), "w");
    if (f) {
        std::string content = j.dump(2);
        fwrite(content.c_str(), 1, content.size(), f);
        fclose(f);
        fprintf(stderr, "[LayerModule] Saved %d learning rules\n", (int)fRules.size());
    } else {
        fprintf(stderr, "[LayerModule] Failed to write learning rules to %s\n", path.c_str());
    }
}

//========================================================================================
//  FeaturesMatch — check if two feature vectors match (ignoring -1 wildcard values)
//========================================================================================

static bool FeaturesMatch(const ArtFeatureVector& a, const ArtFeatureVector& b)
{
    if (a.strokeWeightClass != -1 && b.strokeWeightClass != -1 &&
        a.strokeWeightClass != b.strokeWeightClass) return false;
    if (a.fillType != -1 && b.fillType != -1 &&
        a.fillType != b.fillType) return false;
    if (a.strokeColorClass != -1 && b.strokeColorClass != -1 &&
        a.strokeColorClass != b.strokeColorClass) return false;
    if (a.opacityClass != -1 && b.opacityClass != -1 &&
        a.opacityClass != b.opacityClass) return false;
    if (a.sizeClass != -1 && b.sizeClass != -1 &&
        a.sizeClass != b.sizeClass) return false;
    return true;
}

//========================================================================================
//  RecordMoveForLearning — capture a user-initiated art-to-layer move as a training signal
//========================================================================================

void LayerModule::RecordMoveForLearning(AIArtHandle art, int layerNodeID)
{
    LoadLearningRules();
    ArtFeatureVector fv = ExtractArtFeatures(art);

    // Find the layer name from tree
    std::string layerName;
    for (auto& node : fTree) {
        if (node.nodeID == layerNodeID) { layerName = node.name; break; }
    }
    if (layerName.empty()) return;

    // Find existing rule with matching conditions and same target
    for (auto& rule : fRules) {
        if (FeaturesMatch(rule.conditions, fv) && rule.suggestedLayer == layerName) {
            rule.applyCount++;
            rule.confidence = std::min(1.0, rule.confidence + 0.05);
            SaveLearningRules();
            fprintf(stderr, "[LayerModule] Reinforced rule: -> %s (count=%d, conf=%.2f)\n",
                    layerName.c_str(), rule.applyCount, rule.confidence);
            return;
        }
    }

    // Create new rule
    LearningRule lr;
    lr.conditions = fv;
    lr.suggestedLayer = layerName;
    lr.confidence = 0.5;
    lr.applyCount = 1;
    fRules.push_back(lr);
    SaveLearningRules();
    fprintf(stderr, "[LayerModule] New learning rule: -> %s\n", layerName.c_str());
}

//========================================================================================
//  RecordRenameForLearning — log rename events for future naming heuristics
//========================================================================================

void LayerModule::RecordRenameForLearning(AIArtHandle art, const std::string& newName)
{
    // Renames teach us about naming patterns, not layer assignment.
    // For now, just log. Full naming heuristics in a future iteration.
    fprintf(stderr, "[LayerModule] Rename recorded for learning: %s\n", newName.c_str());
}

//========================================================================================
//  SuggestLayerForArt — find the best matching learning rule for an art object
//========================================================================================

std::string LayerModule::SuggestLayerForArt(AIArtHandle art)
{
    LoadLearningRules();
    ArtFeatureVector fv = ExtractArtFeatures(art);

    std::string bestSuggestion;
    double bestScore = 0;

    for (auto& rule : fRules) {
        // Only suggest from rules with enough confidence and usage
        if (rule.confidence < 0.6 || rule.applyCount < 3) continue;
        if (FeaturesMatch(rule.conditions, fv)) {
            double score = rule.confidence * rule.applyCount;
            if (score > bestScore) {
                bestScore = score;
                bestSuggestion = rule.suggestedLayer;
            }
        }
    }

    return bestSuggestion;
}

//========================================================================================
//  Preset System — Save / Load layer structure templates
//========================================================================================

std::string LayerModule::GetPresetDirectory()
{
    const char* home = getenv("HOME");
    if (!home) return "";
    std::string baseDir = std::string(home) + "/Library/Application Support/illtool";
    mkdir(baseDir.c_str(), 0755);
    std::string dir = baseDir + "/layer_presets";
    mkdir(dir.c_str(), 0755);
    return dir;
}

void LayerModule::SavePreset(const std::string& name)
{
    if (!sAILayer) return;

    std::string dir = GetPresetDirectory();
    if (dir.empty()) {
        fprintf(stderr, "[LayerModule] SavePreset: could not determine preset directory\n");
        return;
    }

    json preset;
    preset["name"] = name;
    preset["version"] = 1;
    preset["layers"] = json::array();

    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    for (ai::int32 i = 0; i < layerCount; i++) {
        AILayerHandle layer = nullptr;
        if (sAILayer->GetNthLayer(i, &layer) != kNoErr || !layer) continue;

        ai::UnicodeString title;
        sAILayer->GetLayerTitle(layer, title);

        AIBoolean vis = true, edit = true;
        sAILayer->GetLayerVisible(layer, &vis);
        sAILayer->GetLayerEditable(layer, &edit);

        AIRGBColor color = {};
        sAILayer->GetLayerColor(layer, &color);

        json layerJ;
        layerJ["name"]    = title.as_UTF8();
        layerJ["visible"] = (bool)vis;
        layerJ["locked"]  = !(bool)edit;
        layerJ["color"]   = { color.red / 65535.0f, color.green / 65535.0f, color.blue / 65535.0f };
        preset["layers"].push_back(layerJ);
    }

    std::string path = dir + "/" + name + ".json";
    FILE* f = fopen(path.c_str(), "w");
    if (f) {
        std::string content = preset.dump(2);
        fwrite(content.c_str(), 1, content.size(), f);
        fclose(f);
        fprintf(stderr, "[LayerModule] Saved preset: %s (%d layers)\n", name.c_str(), (int)layerCount);
    } else {
        fprintf(stderr, "[LayerModule] Failed to write preset: %s\n", path.c_str());
    }
}

void LayerModule::LoadPreset(const std::string& name)
{
    if (!sAILayer) return;

    std::string dir = GetPresetDirectory();
    if (dir.empty()) return;

    std::string path = dir + "/" + name + ".json";
    FILE* f = fopen(path.c_str(), "r");
    if (!f) {
        fprintf(stderr, "[LayerModule] Preset not found: %s\n", path.c_str());
        return;
    }

    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0) { fclose(f); return; }

    std::string content(sz, '\0');
    size_t bytesRead = fread(&content[0], 1, sz, f);
    fclose(f);
    if (bytesRead == 0) return;
    content.resize(bytesRead);

    try {
        json preset = json::parse(content);
        if (!preset.contains("layers") || !preset["layers"].is_array()) {
            fprintf(stderr, "[LayerModule] Invalid preset format: %s\n", name.c_str());
            return;
        }

        int created = 0;
        for (auto& layerJ : preset["layers"]) {
            std::string layerName = layerJ.value("name", "");
            if (layerName.empty()) continue;

            bool vis    = layerJ.value("visible", true);
            bool locked = layerJ.value("locked", false);

            // Check if layer already exists
            AILayerHandle existing = nullptr;
            ai::UnicodeString uName(layerName);
            sAILayer->GetLayerByTitle(&existing, uName);

            if (!existing) {
                // Create it
                AILayerHandle newLayer = nullptr;
                ASErr err = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &newLayer);
                if (err == kNoErr && newLayer) {
                    sAILayer->SetLayerTitle(newLayer, uName);
                    sAILayer->SetLayerVisible(newLayer, vis);
                    sAILayer->SetLayerEditable(newLayer, !locked);

                    if (layerJ.contains("color") && layerJ["color"].is_array() &&
                        layerJ["color"].size() == 3) {
                        AIRGBColor color;
                        color.red   = (ai::uint16)(layerJ["color"][0].get<float>() * 65535.0f);
                        color.green = (ai::uint16)(layerJ["color"][1].get<float>() * 65535.0f);
                        color.blue  = (ai::uint16)(layerJ["color"][2].get<float>() * 65535.0f);
                        sAILayer->SetLayerColor(newLayer, color);
                    }
                    created++;
                }
            }
        }
        fTreeDirty = true;
        InvalidateFullView();
        fprintf(stderr, "[LayerModule] Applied preset: %s (created %d layers)\n", name.c_str(), created);
    } catch (const std::exception& e) {
        fprintf(stderr, "[LayerModule] Failed to parse preset: %s — %s\n", name.c_str(), e.what());
    }
}

//========================================================================================
//  Handle resolution helpers
//========================================================================================

AIArtHandle LayerModule::ResolveArt(int nodeID)
{
    auto it = fArtHandleMap.find(nodeID);
    return (it != fArtHandleMap.end()) ? it->second : nullptr;
}

AILayerHandle LayerModule::ResolveLayer(int nodeID)
{
    auto it = fLayerHandleMap.find(nodeID);
    return (it != fLayerHandleMap.end()) ? it->second : nullptr;
}

//========================================================================================
//  SelectNode — click-to-select: set current layer or select art
//========================================================================================

void LayerModule::SelectNode(int nodeID)
{
    // Check if it's a layer
    auto layerIt = fLayerHandleMap.find(nodeID);
    if (layerIt != fLayerHandleMap.end()) {
        // Set as current/active layer in Illustrator
        sAILayer->SetCurrentLayer(layerIt->second);
        fprintf(stderr, "[LayerModule] Set current layer: node %d\n", nodeID);
        fTreeDirty = true;
        InvalidateFullView();
        return;
    }

    // It's art — deselect all, then select this art
    AIArtHandle art = ResolveArt(nodeID);
    if (!art) return;

    // Deselect all currently selected art
    AIMatchingArtSpec deselectSpec;
    deselectSpec.type = kAnyArt;
    deselectSpec.whichAttr = kArtSelected;
    deselectSpec.attr = kArtSelected;
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (sAIMatchingArt->GetMatchingArt(&deselectSpec, 1, &matches, &numMatches) == kNoErr && numMatches > 0) {
        for (ai::int32 i = 0; i < numMatches; i++) {
            sAIArt->SetArtUserAttr((*matches)[i], kArtSelected, 0);
        }
        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    }

    // Select this art
    sAIArt->SetArtUserAttr(art, kArtSelected, kArtSelected);
    fTreeDirty = true;
    InvalidateFullView();
    fprintf(stderr, "[LayerModule] Selected art: node %d\n", nodeID);
}

//========================================================================================
//  GroupSelectedItems — Cmd+G: group selected items into a new group
//========================================================================================

void LayerModule::GroupSelectedItems(const std::string& groupName)
{
    if (!sAIMatchingArt || !sAIArt) return;

    // Get all selected art
    AIMatchingArtSpec spec;
    spec.type = kAnyArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches < 1) {
        fprintf(stderr, "[LayerModule] GroupSelected: no selected art\n");
        return;
    }

    // Create a new group
    AIArtHandle groupArt = nullptr;
    err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groupArt);
    if (err != kNoErr || !groupArt) {
        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        fprintf(stderr, "[LayerModule] GroupSelected: failed to create group\n");
        return;
    }

    // Name the group
    std::string name = groupName.empty() ? "Group" : groupName;
    sAIArt->SetArtName(groupArt, ai::UnicodeString(name));

    // Move selected art into the group
    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];
        // Skip the group we just created
        if (art == groupArt) continue;
        sAIArt->ReorderArt(art, kPlaceInsideOnTop, groupArt);
    }

    sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    // Select the new group
    sAIArt->SetArtUserAttr(groupArt, kArtSelected, kArtSelected);

    fTreeDirty = true;
    InvalidateFullView();
    fprintf(stderr, "[LayerModule] Grouped %d items into '%s'\n", (int)numMatches, name.c_str());
}
