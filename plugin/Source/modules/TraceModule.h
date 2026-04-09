#pragma once

#include "IllToolModule.h"
#include <string>

//========================================================================================
//  TraceModule — Bridge to MCP Python tracing backends (vtracer, OpenCV, StarVector)
//  HTTP POST to localhost MCP server, parse SVG path response, create AI paths.
//========================================================================================

class TraceModule : public IllToolModule {
public:
    TraceModule() = default;
    ~TraceModule() override = default;

    bool HandleOp(const PluginOp& op) override;
    void DrawOverlay(AIAnnotatorMessage* message) override;
    void OnDocumentChanged() override;

private:
    // Execute trace via HTTP POST to MCP server
    void ExecuteTrace();

    // Parse SVG path data string into AI path segments
    bool ParseSVGPathToSegments(const std::string& svgPath,
                                std::vector<AIPathSegment>& outSegs,
                                bool& outClosed);

    // Create AI paths from parsed SVG response
    void CreatePathsFromSVG(const std::string& svgContent);

    // Status for panel display
    std::string fStatusMessage;
    bool        fTraceInProgress = false;
};
