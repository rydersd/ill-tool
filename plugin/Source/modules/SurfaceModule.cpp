//========================================================================================
//
//  SurfaceModule — Click-to-extract surface boundaries via MCP DSINE normals
//
//  When extract mode is active, clicking on the canvas sends the click position
//  to the MCP server which runs DSINE normal estimation, classifies the surface,
//  flood-fills the region, and returns boundary contours as AI paths.
//
//========================================================================================

#include "SurfaceModule.h"
#include "HttpBridge.h"
#include "IllToolSuites.h"
#include "VisionEngine.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"

#include <cmath>
#include <sstream>

using json = nlohmann::json;

extern IllToolPlugin* gPlugin;

//========================================================================================
//  HandleOp
//========================================================================================

bool SurfaceModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::SurfaceExtract:
            ExecuteExtract(op.param1, op.param2, op.strParam);
            return true;

        case OpType::SurfaceExtractToggle:
            SetExtractMode(op.boolParam1);
            return true;

        default:
            return false;
    }
}

//========================================================================================
//  SetExtractMode
//========================================================================================

void SurfaceModule::SetExtractMode(bool enable)
{
    fExtractMode = enable;
    BridgeSetSurfaceExtractMode(enable);
    fprintf(stderr, "[SurfaceModule] Extract mode %s\n", enable ? "enabled" : "disabled");
    if (enable) {
        BridgeSetExtractionStatus("Click on reference to extract surface");
    } else {
        BridgeSetExtractionStatus("");
    }
}

//========================================================================================
//  HandleExtractClick — called from ToolMouseDown when extract mode active
//========================================================================================

bool SurfaceModule::HandleExtractClick(AIRealPoint artPt)
{
    if (!fExtractMode) return false;

    // Enqueue extraction at click point
    BridgeRequestSurfaceExtract(artPt.h, artPt.v, "click_extract");
    BridgeSetExtractionStatus("Extracting...");
    fprintf(stderr, "[SurfaceModule] Extract click at (%.0f, %.0f)\n", artPt.h, artPt.v);
    return true;
}

//========================================================================================
//  ExecuteExtract — HTTP POST to MCP server
//========================================================================================

void SurfaceModule::ExecuteExtract(double x, double y, const std::string& action)
{
    BridgeSetExtractionStatus("Extracting surface...");

    // Find the placed image to get its file path
    std::string imagePath;
    try {
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        AIMatchingArtSpec spec;
        spec.type = kPlacedArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err == kNoErr && numMatches > 0 && matches && sAIPlaced) {
            AIArtHandle art = (*matches)[0];
            ai::FilePath filePath;
            sAIPlaced->GetPlacedFileSpecification(art, filePath);
            CFStringRef cfPath = filePath.GetAsCFString();
            if (cfPath) {
                char pathBuf[2048];
                if (CFStringGetCString(cfPath, pathBuf, sizeof(pathBuf), kCFStringEncodingUTF8)) {
                    imagePath = pathBuf;
                }
                CFRelease(cfPath);
            }
        }
    }
    catch (...) {
        fprintf(stderr, "[SurfaceModule] Error finding placed image\n");
    }

    if (imagePath.empty()) {
        BridgeSetExtractionStatus("No placed image found in document");
        fprintf(stderr, "[SurfaceModule] No placed image found\n");
        return;
    }

    double sensitivity = BridgeGetExtractionSensitivity();

    // HTTP POST to MCP server
    httplib::Client cli("127.0.0.1", 8787);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(120);

    json reqBody;
    reqBody["action"] = action;
    reqBody["image_path"] = imagePath;
    reqBody["point"] = {x, y};
    reqBody["sensitivity"] = sensitivity;

    auto res = cli.Post("/api/surface_extract", reqBody.dump(), "application/json");

    if (!res || res->status != 200) {
        std::string err = res ? ("HTTP " + std::to_string(res->status)) : "connection failed";
        BridgeSetExtractionStatus("Extract failed: " + err);
        fprintf(stderr, "[SurfaceModule] HTTP error: %s\n", err.c_str());
        return;
    }

    // Parse response — expecting { "contours": [...], "surface_type": "flat", "confidence": 0.82 }
    try {
        json resp = json::parse(res->body);

        std::string surfaceType = resp.value("surface_type", "unknown");
        double confidence = resp.value("confidence", 0.0);

        int created = 0;
        if (resp.contains("contours")) {
            for (auto& contour : resp["contours"]) {
                if (!contour.contains("points")) continue;
                auto& points = contour["points"];
                if (points.size() < 2) continue;

                std::vector<AIPathSegment> segs;
                for (auto& pt : points) {
                    AIPathSegment seg = {};
                    seg.p.h = (AIReal)pt[0].get<double>();
                    seg.p.v = (AIReal)pt[1].get<double>();
                    seg.in = seg.p;
                    seg.out = seg.p;
                    seg.corner = true;
                    segs.push_back(seg);
                }

                bool closed = contour.value("closed", true);

                AIArtHandle newPath = nullptr;
                ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
                if (err == kNoErr && newPath) {
                    ai::int16 nc = (ai::int16)segs.size();
                    sAIPath->SetPathSegmentCount(newPath, nc);
                    sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
                    sAIPath->SetPathClosed(newPath, closed);

                    // Stroke: 1pt, color by surface type
                    AIPathStyle style;
                    memset(&style, 0, sizeof(style));
                    style.stroke.miterLimit = (AIReal)4.0;
                    style.fillPaint = false;
                    style.strokePaint = true;
                    style.stroke.width = (AIReal)1.0;
                    style.stroke.color.kind = kThreeColor;

                    // Color-code by surface type
                    if (surfaceType == "flat") {
                        style.stroke.color.c.rgb.red   = (AIReal)0.0;
                        style.stroke.color.c.rgb.green = (AIReal)0.7;
                        style.stroke.color.c.rgb.blue  = (AIReal)0.7;
                    } else if (surfaceType == "cylindrical") {
                        style.stroke.color.c.rgb.red   = (AIReal)0.8;
                        style.stroke.color.c.rgb.green = (AIReal)0.3;
                        style.stroke.color.c.rgb.blue  = (AIReal)0.5;
                    } else {
                        style.stroke.color.c.rgb.red   = (AIReal)0.2;
                        style.stroke.color.c.rgb.green = (AIReal)0.2;
                        style.stroke.color.c.rgb.blue  = (AIReal)0.2;
                    }
                    sAIPathStyle->SetPathStyle(newPath, &style);

                    // Name the path with surface type
                    std::string name = surfaceType + " boundary";
                    sAIArt->SetArtName(newPath, ai::UnicodeString(name));
                    created++;
                }
            }
        }

        char statusBuf[128];
        snprintf(statusBuf, sizeof(statusBuf), "%s (%.0f%%) — %d contours",
                 surfaceType.c_str(), confidence * 100, created);
        BridgeSetExtractionStatus(statusBuf);
        fprintf(stderr, "[SurfaceModule] %s\n", statusBuf);
    }
    catch (const std::exception& e) {
        BridgeSetExtractionStatus(std::string("Parse error: ") + e.what());
        fprintf(stderr, "[SurfaceModule] JSON parse error: %s\n", e.what());
    }

    sAIDocument->RedrawDocument();
}

//========================================================================================
//  DrawOverlay — highlight extract cursor position
//========================================================================================

void SurfaceModule::DrawOverlay(AIAnnotatorMessage* message)
{
    // No persistent overlay — extract mode indicated by cursor and panel status
}

//========================================================================================
//  OnDocumentChanged
//========================================================================================

void SurfaceModule::OnDocumentChanged()
{
    fExtractMode = false;
    BridgeSetSurfaceExtractMode(false);
    BridgeSetExtractionStatus("");
}
