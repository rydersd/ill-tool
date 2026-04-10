#ifndef __BLENDMODULE_H__
#define __BLENDMODULE_H__

//========================================================================================
//  BlendModule — Blend Harmonization (Stage 11)
//
//  Handles: BlendPickA, BlendPickB, BlendExecute, BlendSetSteps, BlendSetEasing
//  State: blend states vector, active blend group tracking
//  Mouse: pick A/B mode (intercept clicks to store path references)
//  Drawing: none (blend creates real art, not overlays)
//  Undo: snapshot blend intermediates for undo
//========================================================================================

#include "IllToolModule.h"
#include <vector>
#include <utility>

class BlendModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    bool HandleMouseDown(AIToolMessage* msg) override;
    void OnSelectionChanged() override;
    void OnDocumentChanged() override;
    bool CanUndo() override;
    void Undo() override;

    //------------------------------------------------------------------------------------
    //  Blend state
    //------------------------------------------------------------------------------------

    /** Persistent state for a single blend operation. */
    struct BlendState {
        AIArtHandle groupArt = nullptr;
        AIArtHandle pathA = nullptr;
        AIArtHandle pathB = nullptr;
        int steps = 5;
        int easingPreset = 0;
        std::vector<std::pair<double,double>> customEasingPoints;
        std::vector<AIArtHandle> intermediates;
    };

    /** The blend path pair — set by Pick A / Pick B tool mode. */
    AIArtHandle fBlendPathA = nullptr;
    AIArtHandle fBlendPathB = nullptr;

    /** Active blend states — one per blend group in the document. */
    std::vector<BlendState> fBlendStates;

    /** Running counter for blend group naming. */
    int fBlendGroupCounter = 0;

private:
    //------------------------------------------------------------------------------------
    //  Undo
    //------------------------------------------------------------------------------------

    UndoStack fUndoStack;

    //------------------------------------------------------------------------------------
    //  Blend operations
    //------------------------------------------------------------------------------------

    /** Execute blend: harmonize pathA and pathB, create N intermediate paths.
        Groups everything into a named blend group and stores state for re-editing.
        @return Number of paths created, or 0 on failure. */
    int ExecuteBlend(AIArtHandle pathA, AIArtHandle pathB, int steps, int easingPreset);

    /** Re-blend an existing blend group with new parameters.
        @return Number of new paths created, or 0 on failure. */
    int ReblendGroup(AIArtHandle groupArt, int steps, int easingPreset);

    /** Find BlendState for a given group art handle. Returns nullptr if not found. */
    BlendState* FindBlendState(AIArtHandle groupArt);

    /** Check if an art handle is (or is inside) a blend group.
        Returns the blend group handle, or nullptr. */
    AIArtHandle FindBlendGroupForArt(AIArtHandle art);
};

#endif // __BLENDMODULE_H__
