#pragma once

#include "IllToolModule.h"
#include <string>

//========================================================================================
//  SurfaceModule — Click-to-extract surface boundaries via MCP DSINE normals
//
//  Click on canvas over reference image → HTTP POST to MCP adobe_ai_surface_extract →
//  receive boundary contours → create AI paths in Illustrator.
//========================================================================================

class SurfaceModule : public IllToolModule {
public:
    SurfaceModule() = default;
    ~SurfaceModule() override = default;

    bool HandleOp(const PluginOp& op) override;
    void DrawOverlay(AIAnnotatorMessage* message) override;
    void OnDocumentChanged() override;

    /** Called by ToolMouseDown when extract mode is active. */
    bool HandleExtractClick(AIRealPoint artPt);

private:
    // Execute surface extraction via HTTP POST to MCP
    void ExecuteExtract(double x, double y, const std::string& action);

    // Toggle extract mode
    void SetExtractMode(bool enable);

    bool fExtractMode = false;
};
