//========================================================================================
//
//  TraceModule — Bridge to MCP Python tracing backends (vtracer, OpenCV, StarVector)
//
//  HTTP POST to localhost MCP server, parse SVG path data, create Illustrator paths.
//  All heavy work (HTTP + parsing) happens in the SDK timer callback context.
//
//========================================================================================

#include "TraceModule.h"
#include "HttpBridge.h"
#include "IllToolSuites.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"

#include <cmath>
#include <sstream>

using json = nlohmann::json;

extern IllToolPlugin* gPlugin;

//========================================================================================
//  HandleOp
//========================================================================================

bool TraceModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::Trace:
            ExecuteTrace();
            return true;
        default:
            return false;
    }
}

//========================================================================================
//  ExecuteTrace — HTTP POST to MCP server, get SVG, create paths
//========================================================================================

void TraceModule::ExecuteTrace()
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace already in progress, skipping\n");
        return;
    }
    fTraceInProgress = true;
    BridgeSetTraceStatus("Tracing...");

    // Get the placed image path — find first placed art (selected or not)
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
        fprintf(stderr, "[TraceModule] Error getting placed image path\n");
    }

    if (imagePath.empty()) {
        BridgeSetTraceStatus("No placed image selected");
        fTraceInProgress = false;
        fprintf(stderr, "[TraceModule] No placed image selected\n");
        return;
    }

    fprintf(stderr, "[TraceModule] Tracing image: %s\n", imagePath.c_str());

    // HTTP POST to MCP server
    // The MCP server runs on localhost — we use httplib for the client call
    httplib::Client cli("127.0.0.1", 8787);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(120);  // ML tracing can be slow

    int speckle = BridgeGetTraceSpeckle();
    int colorPrec = BridgeGetTraceColorPrecision();

    json reqBody;
    reqBody["image_path"] = imagePath;
    reqBody["filter_speckle"] = speckle;
    reqBody["color_precision"] = colorPrec;
    reqBody["color_mode"] = "color";

    std::string endpoint = "/api/trace";  // Plugin-local trace endpoint

    auto res = cli.Post(endpoint.c_str(), reqBody.dump(), "application/json");

    if (!res || res->status != 200) {
        std::string err = res ? ("HTTP " + std::to_string(res->status)) : "connection failed";
        BridgeSetTraceStatus("Trace failed: " + err);
        fTraceInProgress = false;
        fprintf(stderr, "[TraceModule] Trace HTTP error: %s\n", err.c_str());
        return;
    }

    // Parse response — expecting { "svg": "<svg>...</svg>" } or { "paths": [...] }
    try {
        json resp = json::parse(res->body);

        if (resp.contains("svg")) {
            CreatePathsFromSVG(resp["svg"].get<std::string>());
        } else if (resp.contains("paths")) {
            // Array of SVG path data strings
            int created = 0;
            for (auto& pathData : resp["paths"]) {
                std::string d = pathData.get<std::string>();
                std::vector<AIPathSegment> segs;
                bool closed = false;
                if (ParseSVGPathToSegments(d, segs, closed) && !segs.empty()) {
                    AIArtHandle newPath = nullptr;
                    ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
                    if (err == kNoErr && newPath) {
                        ai::int16 nc = (ai::int16)segs.size();
                        sAIPath->SetPathSegmentCount(newPath, nc);
                        sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
                        sAIPath->SetPathClosed(newPath, closed);

                        // Set default stroke: 1pt black
                        AIPathStyle style;
                        memset(&style, 0, sizeof(style));
                        style.stroke.miterLimit = (AIReal)4.0;
                        style.fillPaint = false;
                        style.strokePaint = true;
                        style.stroke.width = (AIReal)1.0;
                        style.stroke.color.kind = kThreeColor;
                        style.stroke.color.c.rgb.red   = (AIReal)0.0;
                        style.stroke.color.c.rgb.green = (AIReal)0.0;
                        style.stroke.color.c.rgb.blue  = (AIReal)0.0;
                        sAIPathStyle->SetPathStyle(newPath, &style);
                        created++;
                    }
                }
            }
            fprintf(stderr, "[TraceModule] Created %d paths from trace response\n", created);
            BridgeSetTraceStatus("Traced: " + std::to_string(created) + " paths");
        } else {
            BridgeSetTraceStatus("Trace: unexpected response format");
            fprintf(stderr, "[TraceModule] Unexpected response: %s\n", res->body.substr(0, 200).c_str());
        }
    }
    catch (const std::exception& e) {
        BridgeSetTraceStatus(std::string("Parse error: ") + e.what());
        fprintf(stderr, "[TraceModule] JSON parse error: %s\n", e.what());
    }

    fTraceInProgress = false;
    sAIDocument->RedrawDocument();
}

//========================================================================================
//  ParseSVGPathToSegments — basic M/L/C/Z SVG path parser
//========================================================================================

bool TraceModule::ParseSVGPathToSegments(const std::string& svgPath,
                                          std::vector<AIPathSegment>& outSegs,
                                          bool& outClosed)
{
    outSegs.clear();
    outClosed = false;

    std::istringstream ss(svgPath);
    char cmd = 0;
    double x = 0, y = 0;
    double startX = 0, startY = 0;
    bool hasStart = false;

    // Simple SVG path parser: M, L, C, Z (absolute only)
    while (ss) {
        char c = 0;
        ss >> c;
        if (!ss) break;

        if (c == 'M' || c == 'm' || c == 'L' || c == 'l' ||
            c == 'C' || c == 'c' || c == 'Z' || c == 'z') {
            cmd = c;
        } else {
            ss.putback(c);
        }

        if (cmd == 'Z' || cmd == 'z') {
            outClosed = true;
            break;
        }

        if (cmd == 'M' || cmd == 'L') {
            if (!(ss >> x >> y)) break;
            // Skip optional comma
            if (ss.peek() == ',') ss.get();

            AIPathSegment seg = {};
            seg.p.h = (AIReal)x;
            seg.p.v = (AIReal)(-y);  // SVG Y is inverted vs AI Y
            seg.in = seg.p;
            seg.out = seg.p;
            seg.corner = true;

            if (cmd == 'M' && !hasStart) {
                startX = x;
                startY = y;
                hasStart = true;
            }
            outSegs.push_back(seg);
            // After M, implicit command becomes L
            if (cmd == 'M') cmd = 'L';

        } else if (cmd == 'C') {
            double x1, y1, x2, y2, x3, y3;
            if (!(ss >> x1)) break;
            if (ss.peek() == ',') ss.get();
            if (!(ss >> y1)) break;
            if (ss.peek() == ',') ss.get();
            if (!(ss >> x2)) break;
            if (ss.peek() == ',') ss.get();
            if (!(ss >> y2)) break;
            if (ss.peek() == ',') ss.get();
            if (!(ss >> x3)) break;
            if (ss.peek() == ',') ss.get();
            if (!(ss >> y3)) break;

            // Set the out-handle of the previous segment
            if (!outSegs.empty()) {
                auto& prev = outSegs.back();
                prev.out.h = (AIReal)x1;
                prev.out.v = (AIReal)(-y1);
                prev.corner = false;
            }

            AIPathSegment seg = {};
            seg.p.h = (AIReal)x3;
            seg.p.v = (AIReal)(-y3);
            seg.in.h = (AIReal)x2;
            seg.in.v = (AIReal)(-y2);
            seg.out = seg.p;  // will be set by next C command
            seg.corner = false;

            outSegs.push_back(seg);
            x = x3;
            y = y3;
        }
    }

    return !outSegs.empty();
}

//========================================================================================
//  CreatePathsFromSVG — parse full SVG document, extract <path> elements
//========================================================================================

void TraceModule::CreatePathsFromSVG(const std::string& svgContent)
{
    // Simple extraction: find all d="..." attributes in <path> elements
    int created = 0;
    size_t pos = 0;

    while (true) {
        size_t pathStart = svgContent.find("<path", pos);
        if (pathStart == std::string::npos) break;

        size_t dStart = svgContent.find("d=\"", pathStart);
        if (dStart == std::string::npos) break;
        dStart += 3;

        size_t dEnd = svgContent.find("\"", dStart);
        if (dEnd == std::string::npos) break;

        std::string pathData = svgContent.substr(dStart, dEnd - dStart);
        pos = dEnd;

        std::vector<AIPathSegment> segs;
        bool closed = false;
        if (ParseSVGPathToSegments(pathData, segs, closed) && !segs.empty()) {
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (err == kNoErr && newPath) {
                ai::int16 nc = (ai::int16)segs.size();
                sAIPath->SetPathSegmentCount(newPath, nc);
                sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
                sAIPath->SetPathClosed(newPath, closed);

                // Default stroke: 1pt black
                AIPathStyle style;
                memset(&style, 0, sizeof(style));
                style.fillPaint = false;
                style.strokePaint = true;
                style.stroke.width = (AIReal)1.0;
                style.stroke.color.kind = kThreeColor;
                style.stroke.color.c.rgb.red   = (AIReal)0.0;
                style.stroke.color.c.rgb.green = (AIReal)0.0;
                style.stroke.color.c.rgb.blue  = (AIReal)0.0;
                sAIPathStyle->SetPathStyle(newPath, &style);
                created++;
            }
        }
    }

    fprintf(stderr, "[TraceModule] Created %d paths from SVG\n", created);
    BridgeSetTraceStatus("Traced: " + std::to_string(created) + " paths");
}

//========================================================================================
//  DrawOverlay — no annotator overlay needed for trace
//========================================================================================

void TraceModule::DrawOverlay(AIAnnotatorMessage* /*message*/)
{
    // Trace module doesn't draw overlays
}

//========================================================================================
//  OnDocumentChanged
//========================================================================================

void TraceModule::OnDocumentChanged()
{
    fTraceInProgress = false;
    fStatusMessage.clear();
    BridgeSetTraceStatus("");
}
