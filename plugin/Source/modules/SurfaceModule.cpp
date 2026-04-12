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
#include "VisionIntelligence.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"
// stb_image / stb_image_write declarations pulled in via VisionEngine.h

#include <cmath>
#include <sstream>
#include <cstdlib>
#include <cstdio>
#include <vector>

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
//  ExecuteExtract — in-plugin Metric3D normal-based surface extraction
//
//  Flow:
//   1. Locate placed image + its artboard bounds
//   2. Run Metric3D v2 ONNX → get per-pixel surface normals
//   3. Convert click (artboard coords) → image pixel → normal map coord
//   4. Sample target normal at click, build similarity mask (dot > threshold)
//   5. Flood-fill from click to isolate the clicked surface region
//   6. Write mask PNG, run vtracer to trace the boundary
//   7. Parse SVG, transform pixel coords → artboard, create AI path
//
//  No external MCP server required. Uses the same Metric3D/vtracer pipeline
//  already used by Trace's normal_ref / depth_decompose backends.
//========================================================================================

void SurfaceModule::ExecuteExtract(double x, double y, const std::string& action)
{
    (void)action;
    BridgeSetExtractionStatus("Extracting surface...");

    if (!VIHasMetricDepth()) {
        BridgeSetExtractionStatus("Metric3D v2 not available — place model in plugin/models/");
        fprintf(stderr, "[SurfaceModule] VIHasMetricDepth=false, cannot extract\n");
        return;
    }

    // ── 1. Find placed/raster image + its artboard bounds ─────────────────────────────
    std::string imagePath;
    double artL = 0, artT = 0, artR = 0, artB = 0;
    {
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        AIMatchingArtSpec spec;
        spec.type = kPlacedArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        AIArtHandle art = nullptr;
        if (err == kNoErr && numMatches > 0 && matches) {
            art = (*matches)[0];
            if (sAIPlaced) {
                ai::FilePath fp;
                sAIPlaced->GetPlacedFileSpecification(art, fp);
                CFStringRef cfPath = fp.GetAsCFString();
                if (cfPath) {
                    char buf[2048];
                    if (CFStringGetCString(cfPath, buf, sizeof(buf), kCFStringEncodingUTF8)) imagePath = buf;
                    CFRelease(cfPath);
                }
            }
            sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            matches = nullptr;
        }
        // Raster fallback intentionally omitted — Surface Extract requires a placed
        // (linked) image so Metric3D can read from its file path. Embedded rasters
        // don't expose a stable path via AIRasterSuite.
        if (art) {
            AIRealRect bounds;
            if (sAIArt->GetArtBounds(art, &bounds) == kNoErr) {
                artL = bounds.left; artR = bounds.right;
                artT = bounds.top;  artB = bounds.bottom;
            }
        }
    }

    if (imagePath.empty() || artR <= artL || artT <= artB) {
        BridgeSetExtractionStatus("No placed image found");
        fprintf(stderr, "[SurfaceModule] No placed image or invalid bounds\n");
        return;
    }

    // ── 2. Load source image to get pixel dims ────────────────────────────────────────
    int imgW = 0, imgH = 0, imgC = 0;
    if (!stbi_info(imagePath.c_str(), &imgW, &imgH, &imgC) || imgW <= 0 || imgH <= 0) {
        BridgeSetExtractionStatus("Failed to read image");
        fprintf(stderr, "[SurfaceModule] stbi_info failed for %s\n", imagePath.c_str());
        return;
    }

    // ── 3. Convert artboard click → image pixel coords ───────────────────────────────
    double normX = (x - artL) / (artR - artL);
    double normY = (artT - y) / (artT - artB);
    if (normX < 0 || normX > 1 || normY < 0 || normY > 1) {
        BridgeSetExtractionStatus("Click outside image");
        return;
    }
    int clickPxX = (int)(normX * imgW);
    int clickPxY = (int)(normY * imgH);

    // ── 4. Run Metric3D v2 to get normals ────────────────────────────────────────────
    BridgeSetExtractionStatus("Computing normals (Metric3D v2)...");
    float* depth = nullptr;
    float* normals = nullptr;
    float* confidence = nullptr;
    int nW = 0, nH = 0;
    if (!VIEstimateMetricDepth(imagePath.c_str(), &depth, &nW, &nH, &normals, &confidence) ||
        !normals || nW <= 0 || nH <= 0) {
        if (depth) free(depth);
        if (normals) free(normals);
        if (confidence) free(confidence);
        BridgeSetExtractionStatus("Normal estimation failed");
        return;
    }
    if (depth) { free(depth); depth = nullptr; }
    if (confidence) { free(confidence); confidence = nullptr; }

    // ── 5. Sample target normal at click (map click px → normal map px) ──────────────
    int nClickX = (int)((double)clickPxX * nW / imgW);
    int nClickY = (int)((double)clickPxY * nH / imgH);
    if (nClickX < 0) nClickX = 0; if (nClickX >= nW) nClickX = nW - 1;
    if (nClickY < 0) nClickY = 0; if (nClickY >= nH) nClickY = nH - 1;
    int nidx = (nClickY * nW + nClickX) * 3;
    float tnx = normals[nidx], tny = normals[nidx + 1], tnz = normals[nidx + 2];

    // ── 6. Build similarity mask (dot > threshold scaled by sensitivity) ────────────
    double sensitivity = BridgeGetExtractionSensitivity();
    if (sensitivity < 0.0) sensitivity = 0.5;
    if (sensitivity > 1.0) sensitivity = 1.0;
    // Sensitivity 0 = very tight (dot > 0.95), 1 = loose (dot > 0.70)
    float threshold = (float)(0.95 - 0.25 * sensitivity);

    std::vector<unsigned char> mask((size_t)nW * nH, 0);
    for (int i = 0; i < nW * nH; i++) {
        float nx = normals[i * 3], ny = normals[i * 3 + 1], nz = normals[i * 3 + 2];
        float d = nx * tnx + ny * tny + nz * tnz;
        if (d > threshold) mask[i] = 255;
    }
    free(normals);

    // ── 7. Flood-fill from click to isolate connected region ─────────────────────────
    std::vector<unsigned char> region((size_t)nW * nH, 0);
    if (mask[nClickY * nW + nClickX]) {
        std::vector<std::pair<int,int>> stack;
        stack.reserve(4096);
        stack.push_back({nClickX, nClickY});
        region[nClickY * nW + nClickX] = 255;
        int filled = 1;
        const int dx4[4] = {-1, 1, 0, 0};
        const int dy4[4] = {0, 0, -1, 1};
        while (!stack.empty()) {
            auto [cx, cy] = stack.back();
            stack.pop_back();
            for (int d = 0; d < 4; d++) {
                int xx = cx + dx4[d], yy = cy + dy4[d];
                if (xx < 0 || xx >= nW || yy < 0 || yy >= nH) continue;
                size_t i = (size_t)yy * nW + xx;
                if (region[i]) continue;
                if (!mask[i]) continue;
                region[i] = 255;
                stack.push_back({xx, yy});
                filled++;
            }
        }
        fprintf(stderr, "[SurfaceModule] Flood: %d pixels, target=(%.3f,%.3f,%.3f) thresh=%.3f\n",
                filled, tnx, tny, tnz, threshold);
    } else {
        fprintf(stderr, "[SurfaceModule] Click pixel not in mask — normal variance too high\n");
    }

    // ── 8. Write region PNG and trace with vtracer ───────────────────────────────────
    const char* maskPath = "/tmp/illtool_surface_region.png";
    if (!stbi_write_png(maskPath, nW, nH, 1, region.data(), nW)) {
        BridgeSetExtractionStatus("Failed to write region mask");
        return;
    }

    const char* svgPath = "/tmp/illtool_surface_region.svg";
    char cmd[2048];
    snprintf(cmd, sizeof(cmd),
        "cd /Users/ryders/Developer/GitHub/ill_tool && "
        ".venv/bin/python -c \""
        "import vtracer; vtracer.convert_image_to_svg_py("
        "image_path='%s', out_path='%s', colormode='bw', hierarchical='cutout', "
        "mode='spline', filter_speckle=20, color_precision=6, layer_difference=25, "
        "corner_threshold=60, length_threshold=8.0, max_iterations=10, "
        "splice_threshold=45, path_precision=3)\" 2>&1",
        maskPath, svgPath);
    int rc = system(cmd);
    if (rc != 0) {
        BridgeSetExtractionStatus("vtracer failed");
        fprintf(stderr, "[SurfaceModule] vtracer exit=%d\n", rc);
        return;
    }

    // ── 9. Read SVG, extract path d-attributes, convert pixel coords → artboard ──────
    FILE* sf = fopen(svgPath, "r");
    if (!sf) { BridgeSetExtractionStatus("vtracer output missing"); return; }
    fseek(sf, 0, SEEK_END); long sz = ftell(sf); fseek(sf, 0, SEEK_SET);
    std::string svg(sz, '\0'); fread(&svg[0], 1, sz, sf); fclose(sf);

    // Simple parser: find each `d="M x,y L x,y ... Z"` and extract points.
    // vtracer cutout mode emits compound paths; we approximate with straight segments.
    int created = 0;
    double pxToArtX = (artR - artL) / (double)nW;
    double pxToArtY = (artT - artB) / (double)nH;

    size_t pos = 0;
    bool firstPath = true;
    while (true) {
        size_t d = svg.find("d=\"", pos);
        if (d == std::string::npos) break;
        size_t e = svg.find("\"", d + 3);
        if (e == std::string::npos) break;
        std::string pd = svg.substr(d + 3, e - (d + 3));
        pos = e + 1;

        // Skip first path — vtracer emits a full-image background rect first
        if (firstPath) { firstPath = false; continue; }

        // Parse by simple tokenization: M/L/C commands + coord pairs.
        std::vector<AIPathSegment> segs;
        double curX = 0, curY = 0;
        size_t i = 0;
        auto skipSep = [&]() {
            while (i < pd.size() && (pd[i] == ' ' || pd[i] == ',' || pd[i] == '\n' || pd[i] == '\t')) i++;
        };
        auto readNum = [&](double& out) -> bool {
            skipSep();
            char* endp = nullptr;
            double v = strtod(pd.c_str() + i, &endp);
            if (endp == pd.c_str() + i) return false;
            i = endp - pd.c_str();
            out = v;
            return true;
        };
        char lastCmd = 0;
        while (i < pd.size()) {
            skipSep();
            if (i >= pd.size()) break;
            char c = pd[i];
            if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')) {
                lastCmd = c;
                i++;
            }
            if (lastCmd == 'M' || lastCmd == 'L') {
                double px, py;
                if (!readNum(px) || !readNum(py)) break;
                curX = px; curY = py;
                AIPathSegment seg = {};
                seg.p.h = (AIReal)(artL + curX * pxToArtX);
                seg.p.v = (AIReal)(artT - curY * pxToArtY);
                seg.in = seg.p; seg.out = seg.p; seg.corner = true;
                segs.push_back(seg);
                // L repeats; M becomes implicit L after first pair
                if (lastCmd == 'M') lastCmd = 'L';
            } else if (lastCmd == 'C') {
                double c1x, c1y, c2x, c2y, px, py;
                if (!readNum(c1x) || !readNum(c1y) ||
                    !readNum(c2x) || !readNum(c2y) ||
                    !readNum(px)  || !readNum(py)) break;
                // Treat as straight segment through endpoint (good enough for region hull).
                // Using only anchor points keeps the path simple and stable.
                if (!segs.empty()) {
                    segs.back().out.h = (AIReal)(artL + c1x * pxToArtX);
                    segs.back().out.v = (AIReal)(artT - c1y * pxToArtY);
                    segs.back().corner = false;
                }
                AIPathSegment seg = {};
                seg.p.h = (AIReal)(artL + px * pxToArtX);
                seg.p.v = (AIReal)(artT - py * pxToArtY);
                seg.in.h = (AIReal)(artL + c2x * pxToArtX);
                seg.in.v = (AIReal)(artT - c2y * pxToArtY);
                seg.out = seg.p;
                seg.corner = false;
                segs.push_back(seg);
                curX = px; curY = py;
            } else if (lastCmd == 'Z' || lastCmd == 'z') {
                // close — handled below
            } else {
                // Unknown command — skip a number to avoid infinite loop
                double dummy;
                if (!readNum(dummy)) break;
            }
        }

        if (segs.size() < 3) continue;

        AIArtHandle newPath = nullptr;
        ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
        if (err != kNoErr || !newPath) continue;

        sAIPath->SetPathSegmentCount(newPath, (ai::int16)segs.size());
        sAIPath->SetPathSegments(newPath, 0, (ai::int16)segs.size(), segs.data());
        sAIPath->SetPathClosed(newPath, true);

        AIPathStyle style;
        memset(&style, 0, sizeof(style));
        style.stroke.miterLimit = (AIReal)4.0;
        style.fillPaint = false;
        style.strokePaint = true;
        style.stroke.width = (AIReal)1.0;
        style.stroke.color.kind = kThreeColor;
        // Color by surface orientation: map normal to HSV-like coloring
        float hue = 0.5f + 0.5f * tnx;  // left/right facing
        style.stroke.color.c.rgb.red   = (AIReal)(0.3 + 0.6 * (1.0 - tnz));  // dark for floor, bright for wall
        style.stroke.color.c.rgb.green = (AIReal)(0.3 + 0.5 * hue);
        style.stroke.color.c.rgb.blue  = (AIReal)(0.5 + 0.4 * tny);
        sAIPathStyle->SetPathStyle(newPath, &style);
        sAIArt->SetArtName(newPath, ai::UnicodeString("Surface boundary"));
        created++;
    }

    char status[128];
    snprintf(status, sizeof(status), "Extracted %d contour(s) — normal (%.2f,%.2f,%.2f)",
             created, tnx, tny, tnz);
    BridgeSetExtractionStatus(status);
    fprintf(stderr, "[SurfaceModule] %s\n", status);

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
