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
    void OnSelectionChanged() override;

private:
    // Execute trace via vtracer (SVG path output)
    void ExecuteTrace();

    // Execute Python-based backends (normal_ref, form_edge) that produce PNG images
    void ExecutePythonBackend(const std::string& backend);

    // Parse SVG path data string into AI path segments
    bool ParseSVGPathToSegments(const std::string& svgPath,
                                std::vector<AIPathSegment>& outSegs,
                                bool& outClosed);

    // Create AI paths from parsed SVG response, mapped to artboard position
    void CreatePathsFromSVG(const std::string& svgContent);

    // Place output PNG images as locked reference layers in the document
    void PlaceImageAsLayer(const std::string& imagePath, const std::string& layerName);

    // Transform SVG pixel coordinates to artboard coordinates
    // SVG: (0,0) top-left, Y down, pixel units
    // AI:  artBounds with Y up
    void TransformSVGPoint(double svgX, double svgY, double& artX, double& artY);

    // Parse hex color string (#RRGGBB) to RGB components (0.0-1.0)
    bool ParseHexColor(const std::string& hex, double& r, double& g, double& b);

    // Find the image path from placed/raster art in the document
    // Populates fArtLeft/Top/Right/Bottom as side effect
    std::string FindImagePath();

    // Status for panel display
    std::string fStatusMessage;
    bool        fTraceInProgress = false;

    // Coordinate mapping: SVG viewBox → Illustrator art bounds
    double fSvgWidth = 0, fSvgHeight = 0;      // from SVG viewBox
    double fArtLeft = 0, fArtTop = 0;           // placed image position in AI coords
    double fArtRight = 0, fArtBottom = 0;
};
