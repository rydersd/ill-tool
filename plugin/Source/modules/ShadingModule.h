#ifndef __SHADINGMODULE_H__
#define __SHADINGMODULE_H__

//========================================================================================
//  ShadingModule — Surface Shading (Stage 12)
//
//  Handles: ShadingApplyBlend, ShadingApplyMesh, ShadingSetMode
//  State: shading mode, light angle, intensity, colors (read from bridge)
//  No mouse handling (uses panel controls only)
//  No drawing (creates real art)
//========================================================================================

#include "IllToolModule.h"

class ShadingModule : public IllToolModule {
public:
    //------------------------------------------------------------------------------------
    //  IllToolModule interface
    //------------------------------------------------------------------------------------

    bool HandleOp(const PluginOp& op) override;
    void OnDocumentChanged() override;

    /** Eyedropper state — when active, samples fill color from selected path. */
    bool fEyedropperMode = false;
    int  fEyedropperTarget = 0;  // 0=highlight, 1=shadow

private:
    /** Running counter for shading group naming. */
    int fShadingGroupCounter = 0;

    /** Apply blend shading (stacked contours) to a closed path.
        @return Number of contour paths created, or 0 on failure. */
    int ApplyBlendShading(AIArtHandle path, int steps,
        double highlightR, double highlightG, double highlightB,
        double shadowR, double shadowG, double shadowB,
        double lightAngle, double intensity);

    /** Apply mesh gradient shading to a path.
        @return 1 on success, 0 on failure. */
    int ApplyMeshShading(AIArtHandle path, int gridSize,
        double highlightR, double highlightG, double highlightB,
        double shadowR, double shadowG, double shadowB,
        double lightAngle, double intensity);

    /** Dispatch a shading operation. Reads parameters from bridge state. */
    void DispatchShadingOp(OpType opType);

    /** Get the first selected path art from the document. */
    static AIArtHandle GetFirstSelectedPath();
};

#endif // __SHADINGMODULE_H__
