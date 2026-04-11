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
#include "IllToolTokens.h"
#include "VisionEngine.h"
#include "VisionCutout.h"
#include "VisionIntelligence.h"
#include "ProjectStore.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

// stb_image for reading PNG pixels (STB_IMAGE_IMPLEMENTATION defined in VisionEngine.cpp)
#include "vendor/stb_image.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <sstream>
#include <dirent.h>
#include <sys/stat.h>

using json = nlohmann::json;

extern IllToolPlugin* gPlugin;

namespace {

double gSvgViewBoxX = 0.0;
double gSvgViewBoxY = 0.0;

bool IsSVGCommandChar(char c)
{
    switch (c) {
        case 'M': case 'm':
        case 'L': case 'l':
        case 'H': case 'h':
        case 'V': case 'v':
        case 'C': case 'c':
        case 'S': case 's':
        case 'Q': case 'q':
        case 'T': case 't':
        case 'Z': case 'z':
        case 'A': case 'a':
            return true;
        default:
            return false;
    }
}

void SkipSVGSeparators(const std::string& text, size_t& pos)
{
    while (pos < text.size()) {
        unsigned char ch = static_cast<unsigned char>(text[pos]);
        if (std::isspace(ch) || ch == ',') {
            ++pos;
        } else {
            break;
        }
    }
}

bool ParseSVGNumber(const std::string& text, size_t& pos, double& outValue)
{
    SkipSVGSeparators(text, pos);
    if (pos >= text.size()) return false;

    const char* start = text.c_str() + pos;
    char* end = nullptr;
    outValue = std::strtod(start, &end);
    if (end == start) return false;

    pos += static_cast<size_t>(end - start);
    SkipSVGSeparators(text, pos);
    return true;
}

bool ParseSVGCoordinatePair(const std::string& text, size_t& pos, double& x, double& y)
{
    return ParseSVGNumber(text, pos, x) && ParseSVGNumber(text, pos, y);
}

bool ParseSVGTranslate(const std::string& transform, double& translateX, double& translateY)
{
    translateX = 0.0;
    translateY = 0.0;

    size_t searchPos = 0;
    while (searchPos < transform.size()) {
        size_t translatePos = transform.find("translate", searchPos);
        if (translatePos == std::string::npos) break;

        size_t openParen = transform.find('(', translatePos);
        if (openParen == std::string::npos) break;
        size_t closeParen = transform.find(')', openParen + 1);
        if (closeParen == std::string::npos) break;

        std::string args = transform.substr(openParen + 1, closeParen - openParen - 1);
        size_t argPos = 0;
        double tx = 0.0;
        double ty = 0.0;
        if (!ParseSVGNumber(args, argPos, tx)) {
            searchPos = closeParen + 1;
            continue;
        }
        if (!ParseSVGNumber(args, argPos, ty)) {
            ty = 0.0;
        }

        translateX += tx;
        translateY += ty;
        searchPos = closeParen + 1;
    }

    return translateX != 0.0 || translateY != 0.0;
}

bool ExtractSVGAttribute(const std::string& element, const std::string& attrName, std::string& outValue)
{
    outValue.clear();
    size_t pos = 0;

    while (pos < element.size()) {
        size_t found = element.find(attrName, pos);
        if (found == std::string::npos) return false;

        bool validPrefix = (found == 0) || !std::isalnum(static_cast<unsigned char>(element[found - 1]));
        size_t valuePos = found + attrName.size();
        while (valuePos < element.size() && std::isspace(static_cast<unsigned char>(element[valuePos]))) ++valuePos;
        if (!validPrefix || valuePos >= element.size() || element[valuePos] != '=') {
            pos = found + attrName.size();
            continue;
        }

        ++valuePos;
        while (valuePos < element.size() && std::isspace(static_cast<unsigned char>(element[valuePos]))) ++valuePos;
        if (valuePos >= element.size()) return false;

        char quote = element[valuePos];
        if (quote != '"' && quote != '\'') return false;
        ++valuePos;

        size_t valueEnd = element.find(quote, valuePos);
        if (valueEnd == std::string::npos) return false;

        outValue = element.substr(valuePos, valueEnd - valuePos);
        return true;
    }

    return false;
}

void ApplyArtTranslation(std::vector<AIPathSegment>& segs, double translateSvgX, double translateSvgY,
                         double artLeft, double artTop, double artRight, double artBottom,
                         double svgWidth, double svgHeight)
{
    if (segs.empty()) return;
    if (translateSvgX == 0.0 && translateSvgY == 0.0) return;

    double dx = translateSvgX;
    double dy = -translateSvgY;
    if (svgWidth > 0.0 && svgHeight > 0.0) {
        double artW = artRight - artLeft;
        double artH = artTop - artBottom;
        dx = translateSvgX * (artW / svgWidth);
        dy = -translateSvgY * (artH / svgHeight);
    }

    for (auto& seg : segs) {
        seg.p.h += (AIReal)dx;
        seg.p.v += (AIReal)dy;
        seg.in.h += (AIReal)dx;
        seg.in.v += (AIReal)dy;
        seg.out.h += (AIReal)dx;
        seg.out.v += (AIReal)dy;
    }
}

} // namespace

//========================================================================================
//  HandleOp
//========================================================================================

bool TraceModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::Trace: {
            // Set undo context so Cmd+Z can undo the entire trace operation
            if (sAIUndo) {
                sAIUndo->SetUndoTextUS(ai::UnicodeString("Undo Trace"),
                                        ai::UnicodeString("Redo Trace"));
            }
            // Dispatch based on backend name in strParam
            std::string backend = op.strParam;
            if (backend == "cutout") {
                PreviewCutout();
            } else if (backend == "cutout_commit") {
                CommitCutout();
            } else if (backend == "cutout_recomposite") {
                RecompositeCutout();
            } else if (backend == "apple_contours") {
                ExecuteAppleContours();
            } else if (backend == "detect_pose") {
                ExecuteDetectPose();
            } else if (backend == "depth_decompose") {
                ExecuteDepthDecompose();
            } else if (backend == "normal_ref" || backend == "form_edge") {
                ExecutePythonBackend(backend);
            } else {
                ExecuteTrace();  // vtracer and other SVG-output backends
            }
            return true;
        }
        default:
            return false;
    }
}

//========================================================================================
//  ExecuteTrace — HTTP POST to MCP server, get SVG, create paths
//========================================================================================

//========================================================================================
//  FindImagePath — extract image path from placed/raster art, populate art bounds
//========================================================================================

std::string TraceModule::FindImagePath()
{
    std::string imagePath;
    try {
        // Strategy 1: Placed art (linked file — has a file path)
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;
        AIMatchingArtSpec spec;
        spec.type = kPlacedArt;
        spec.whichAttr = 0;
        spec.attr = 0;
        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err == kNoErr && numMatches > 0 && matches && sAIPlaced) {
            AIArtHandle art = (*matches)[0];
            // Capture art bounds for coordinate mapping
            AIRealRect artBounds = {0,0,0,0};
            sAIArt->GetArtBounds(art, &artBounds);
            fArtLeft = artBounds.left; fArtTop = artBounds.top;
            fArtRight = artBounds.right; fArtBottom = artBounds.bottom;

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
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        // Strategy 2: Selected placed art
        if (imagePath.empty()) {
            AIMatchingArtSpec selSpec;
            selSpec.type = kPlacedArt;
            selSpec.whichAttr = kArtSelected;
            selSpec.attr = kArtSelected;
            matches = nullptr;
            numMatches = 0;
            err = sAIMatchingArt->GetMatchingArt(&selSpec, 1, &matches, &numMatches);
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
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
        }

        // Strategy 3: Raster art — embedded image, extract to temp PNG
        if (imagePath.empty()) {
            for (int pass = 0; pass < 2 && imagePath.empty(); pass++) {
                AIMatchingArtSpec rasterSpec;
                rasterSpec.type = kRasterArt;
                rasterSpec.whichAttr = (pass == 0) ? kArtSelected : 0;
                rasterSpec.attr = (pass == 0) ? kArtSelected : 0;
                matches = nullptr;
                numMatches = 0;
                err = sAIMatchingArt->GetMatchingArt(&rasterSpec, 1, &matches, &numMatches);
                if (err == kNoErr && numMatches > 0 && matches) {
                    // Find the first raster that's NOT on a hidden/locked layer
                    // (our embedded reference rasters are always hidden+locked)
                    AIArtHandle rasterArt = nullptr;
                    for (ai::int32 ri = 0; ri < numMatches; ri++) {
                        AIArtHandle candidate = (*matches)[ri];
                        ai::int32 attrs = 0;
                        sAIArt->GetArtUserAttr(candidate, kArtHidden | kArtLocked, &attrs);
                        if (!(attrs & kArtHidden) && !(attrs & kArtLocked)) {
                            rasterArt = candidate;
                            break;
                        }
                    }
                    if (!rasterArt) {
                        sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                        continue;
                    }

                    fprintf(stderr, "[TraceModule] Found raster art (pass %d, count %d)\n",
                            pass, (int)numMatches);

                    AIRealRect rBounds = {0,0,0,0};
                    sAIArt->GetArtBounds(rasterArt, &rBounds);
                    fArtLeft = rBounds.left; fArtTop = rBounds.top;
                    fArtRight = rBounds.right; fArtBottom = rBounds.bottom;
                    fprintf(stderr, "[TraceModule] FindImagePath: raster bounds L=%.0f T=%.0f R=%.0f B=%.0f\n",
                            fArtLeft, fArtTop, fArtRight, fArtBottom);

                    // Capture the original raster's matrix so we can replicate it exactly
                    if (sAIRaster->GetRasterMatrix(rasterArt, &fOrigRasterMatrix) == kNoErr) {
                        fHasOrigMatrix = true;
                        fprintf(stderr, "[TraceModule] Original raster matrix: a=%.4f b=%.4f c=%.4f d=%.4f tx=%.1f ty=%.1f\n",
                                fOrigRasterMatrix.a, fOrigRasterMatrix.b, fOrigRasterMatrix.c, fOrigRasterMatrix.d,
                                fOrigRasterMatrix.tx, fOrigRasterMatrix.ty);
                    }

                    AIRasterRecord rasterInfo;
                    if (sAIRaster) {
                        ai::FilePath rasterFilePath;
                        ASErr fileErr = sAIRaster->GetRasterFileSpecification(rasterArt, rasterFilePath);
                        if (fileErr == kNoErr) {
                            CFStringRef cfPath = rasterFilePath.GetAsCFString();
                            if (cfPath) {
                                char pathBuf[2048];
                                if (CFStringGetCString(cfPath, pathBuf, sizeof(pathBuf), kCFStringEncodingUTF8)) {
                                    imagePath = pathBuf;
                                    fprintf(stderr, "[TraceModule] Raster has linked file: %s\n", pathBuf);
                                }
                                CFRelease(cfPath);
                            }
                        }
                    }

                    memset(&rasterInfo, 0, sizeof(rasterInfo));
                    if (imagePath.empty() && sAIRaster && sAIRaster->GetRasterInfo(rasterArt, &rasterInfo) == kNoErr) {
                        int rW = rasterInfo.bounds.right - rasterInfo.bounds.left;
                        int rH = rasterInfo.bounds.bottom - rasterInfo.bounds.top;
                        fprintf(stderr, "[TraceModule] Raster: %dx%d, bps=%d\n",
                                rW, rH, (int)rasterInfo.bitsPerPixel);

                        if (rW > 0 && rH > 0 && rW < 16384 && rH < 16384) {
                            int colorSpace = rasterInfo.colorSpace;
                            int channelCount = 0;
                            switch (colorSpace) {
                                case kGrayColorSpace: channelCount = 1; break;
                                case kRGBColorSpace: channelCount = 3; break;
                                case kCMYKColorSpace: channelCount = 4; break;
                                case kAlphaGrayColorSpace: channelCount = 2; break;
                                case kAlphaRGBColorSpace: channelCount = 4; break;
                                case kAlphaCMYKColorSpace: channelCount = 5; break;
                                default: break;
                            }

                            int bytesPerPixel = (rasterInfo.bitsPerPixel > 0) ? (rasterInfo.bitsPerPixel / 8) : 0;
                            if (channelCount <= 0 || channelCount > 4 || bytesPerPixel <= 0 || bytesPerPixel < channelCount) {
                                fprintf(stderr, "[TraceModule] Unsupported raster format: colorSpace=%d bpp=%d\n",
                                        colorSpace, (int)rasterInfo.bitsPerPixel);
                                if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
                                continue;
                            }

                            int rowBytes = rW * bytesPerPixel;
                            size_t requiredBufferSize = static_cast<size_t>(rowBytes) * static_cast<size_t>(rH);
                            std::vector<unsigned char> pixels(requiredBufferSize, 0);

                            fprintf(stderr, "[TraceModule] Raster bounds: L=%d T=%d R=%d B=%d\n",
                                    rasterInfo.bounds.left, rasterInfo.bounds.top,
                                    rasterInfo.bounds.right, rasterInfo.bounds.bottom);

                            AITile tile;
                            memset(&tile, 0, sizeof(tile));
                            tile.bounds.top = 0;
                            tile.bounds.left = 0;
                            tile.bounds.bottom = rH;
                            tile.bounds.right = rW;
                            tile.bounds.front = 0;
                            tile.bounds.back = channelCount;
                            tile.data = pixels.data();
                            tile.rowBytes = rowBytes;
                            tile.colBytes = bytesPerPixel;
                            tile.planeBytes = 0;
                            for (int i = 0; i < channelCount && i < kMaxChannels; ++i) {
                                tile.channelInterleave[i] = static_cast<ai::int16>(i);
                            }

                            AISlice artSlice;
                            memset(&artSlice, 0, sizeof(artSlice));
                            artSlice.top = rasterInfo.bounds.top;
                            artSlice.left = rasterInfo.bounds.left;
                            artSlice.bottom = rasterInfo.bounds.bottom;
                            artSlice.right = rasterInfo.bounds.right;
                            artSlice.front = 0;
                            artSlice.back = channelCount;

                            AISlice workSlice;
                            memset(&workSlice, 0, sizeof(workSlice));
                            workSlice.top = 0;
                            workSlice.left = 0;
                            workSlice.bottom = rH;
                            workSlice.right = rW;
                            workSlice.front = 0;
                            workSlice.back = channelCount;

                            err = sAIRaster->GetRasterTile(rasterArt, &artSlice, &tile, &workSlice);
                            if (err == kNoErr) {
                                std::string tmpPath = "/tmp/illtool_trace_input.png";
                                int channels = channelCount;
                                int wrote = stbi_write_png(tmpPath.c_str(), rW, rH,
                                                           channels, pixels.data(), rowBytes);
                                if (wrote) {
                                    imagePath = tmpPath;
                                    fprintf(stderr, "[TraceModule] Exported raster to %s (%dx%d)\n",
                                            tmpPath.c_str(), rW, rH);
                                } else {
                                    fprintf(stderr, "[TraceModule] stbi_write_png failed\n");
                                }
                            } else {
                                fprintf(stderr, "[TraceModule] GetRasterTile failed: %d\n", (int)err);
                            }
                        }
                    }
                }
                if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            }
        }
    }
    catch (ai::Error& ex) {
        fprintf(stderr, "[TraceModule] AI Error getting image path: %d\n", (int)ex);
    }
    catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] Exception getting image path: %s\n", ex.what());
    }
    catch (...) {
        fprintf(stderr, "[TraceModule] Unknown error getting image path\n");
    }

    return imagePath;
}

//========================================================================================
//  ParseHexColor — convert "#RRGGBB" to normalized RGB (0.0-1.0)
//========================================================================================

bool TraceModule::ParseHexColor(const std::string& hex, double& r, double& g, double& b)
{
    // Expected format: "#RRGGBB" (7 chars) or "RRGGBB" (6 chars)
    const char* start = hex.c_str();
    if (*start == '#') start++;
    if (strlen(start) < 6) return false;

    unsigned int ri = 0, gi = 0, bi = 0;
    if (sscanf(start, "%02x%02x%02x", &ri, &gi, &bi) == 3) {
        r = ri / 255.0;
        g = gi / 255.0;
        b = bi / 255.0;
        return true;
    }
    return false;
}

//========================================================================================
//  ExecuteTrace — vtracer backend: run vtracer, parse SVG, create filled color paths
//========================================================================================

void TraceModule::ExecuteTrace()
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace already in progress, skipping\n");
        return;
    }
    fTraceInProgress = true;
    BridgeSetTraceStatus("Tracing...");

    std::string imagePath = FindImagePath();

    if (imagePath.empty()) {
        if (BridgeGetTraceStatus().find("embedded") == std::string::npos) {
            BridgeSetTraceStatus("No image found — use File > Place to add a linked image");
        }
        fTraceInProgress = false;
        fprintf(stderr, "[TraceModule] No image path found\n");
        return;
    }

    fprintf(stderr, "[TraceModule] Tracing image: %s\n", imagePath.c_str());

    int speckle = BridgeGetTraceSpeckle();
    int colorPrec = BridgeGetTraceColorPrecision();
    int outputMode = BridgeGetTraceOutputMode();  // 0=outline, 1=fill, 2=centerline

    // --- Centerline mode: Canny edges → skeletonize → trace ---
    // Canny finds actual stroke edges (ignores gradual shading).
    // Skeleton of the edge image gives single-pixel centerlines of drawn strokes.
    std::string traceInputPath = imagePath;
    if (outputMode == 2) {
        BridgeSetTraceStatus("Finding edges...");
        VisionEngine& ve = VisionEngine::Instance();

        int imgW = 0, imgH = 0, imgC = 0;
        unsigned char* gray = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 1);
        if (!gray) {
            BridgeSetTraceStatus("Failed to load image for centerline");
            fTraceInProgress = false;
            return;
        }

        // Step 1: Canny edge detection — finds actual drawn lines, not shaded regions
        // Thresholds are user-configurable via Centerline Settings sliders
        double cannyLow = BridgeGetTraceCannyLow();
        double cannyHigh = BridgeGetTraceCannyHigh();
        ve.LoadImage(imagePath.c_str());
        auto edges = ve.CannyEdges(cannyLow, cannyHigh);

        if (edges.empty() || (int)edges.size() != imgW * imgH) {
            fprintf(stderr, "[TraceModule] Canny failed (got %d pixels, expected %d)\n",
                    (int)edges.size(), imgW * imgH);
            stbi_image_free(gray);
            BridgeSetTraceStatus("Edge detection failed");
            fTraceInProgress = false;
            return;
        }

        // Step 2: Dilate edges so skeleton has material to work with
        // Kernel size = 2*dilRad+1; user-configurable via Edge Dilation slider
        int dilRad = BridgeGetTraceDilationRadius();
        std::vector<unsigned char> dilated(imgW * imgH, 0);
        if (dilRad <= 0) {
            // No dilation — copy edges directly
            for (int i = 0; i < imgW * imgH; i++)
                dilated[i] = edges[i];
        } else {
            for (int y = dilRad; y < imgH - dilRad; y++) {
                for (int x = dilRad; x < imgW - dilRad; x++) {
                    bool hasEdge = false;
                    for (int dy = -dilRad; dy <= dilRad && !hasEdge; dy++) {
                        for (int dx = -dilRad; dx <= dilRad && !hasEdge; dx++) {
                            if (edges[(y+dy) * imgW + (x+dx)] > 0) hasEdge = true;
                        }
                    }
                    dilated[y * imgW + x] = hasEdge ? 255 : 0;
                }
            }
        }

        // Morphological close: erode the dilated result to clean up spread
        // Keeps connected lines while removing dilation overshoot
        std::vector<unsigned char> closed(imgW * imgH, 0);
        for (int y = 1; y < imgH - 1; y++) {
            for (int x = 1; x < imgW - 1; x++) {
                // Keep pixel only if ALL 4-connected neighbors are set
                if (dilated[y * imgW + x] > 0 &&
                    dilated[(y-1) * imgW + x] > 0 &&
                    dilated[(y+1) * imgW + x] > 0 &&
                    dilated[y * imgW + (x-1)] > 0 &&
                    dilated[y * imgW + (x+1)] > 0) {
                    closed[y * imgW + x] = 255;
                }
            }
        }

        // Step 3: Skeletonize the closed edge image
        // Invert for Skeletonize (it expects dark=foreground): edges are white, need to flip
        std::vector<unsigned char> inverted(imgW * imgH);
        for (int i = 0; i < imgW * imgH; i++) {
            inverted[i] = (closed[i] > 0) ? 0 : 255;  // edge pixels become dark (foreground)
        }

        BridgeSetTraceStatus("Skeletonizing edges...");
        int skelThresh = BridgeGetTraceSkeletonThresh();
        unsigned char* skeleton = VisionEngine::Skeletonize(inverted.data(), imgW, imgH, skelThresh);
        stbi_image_free(gray);

        if (!skeleton) {
            BridgeSetTraceStatus("Skeletonization failed");
            fTraceInProgress = false;
            return;
        }

        const char* skelPath = "/tmp/illtool_skeleton.png";
        stbi_write_png(skelPath, imgW, imgH, 1, skeleton, imgW);
        delete[] skeleton;
        traceInputPath = skelPath;
        fprintf(stderr, "[TraceModule] Centerline params: canny=[%.0f,%.0f] dilRad=%d skelThresh=%d\n",
                cannyLow, cannyHigh, dilRad, skelThresh);
        fprintf(stderr, "[TraceModule] Centerline: skeleton saved to %s (%dx%d)\n",
                skelPath, imgW, imgH);
    }

    // Read new vtracer parameters from bridge
    int spliceThresh = BridgeGetTraceSpliceThresh();
    int maxIter = BridgeGetTraceMaxIter();
    int layerDiff = BridgeGetTraceLayerDiff();
    double lengthThresh = BridgeGetTraceLengthThresh();

    const char* colormode = (outputMode == 2) ? "bw" : (outputMode == 0) ? "bw" : "color";
    // Centerline uses higher speckle to filter remaining noise fragments
    int effectiveSpeckle = (outputMode == 2) ? 8 : speckle;
    // Centerline uses higher length threshold to drop tiny stray paths
    double effectiveLengthThresh = (outputMode == 2) ? std::max(lengthThresh, 12.0) : lengthThresh;
    // Centerline uses higher corner threshold for smoother curves
    int effectiveCornerThresh = (outputMode == 2) ? 90 : 60;

    // Call vtracer via the project Python venv directly
    // vtracer.convert_image_to_svg_py writes SVG to disk
    std::string svgPath = "/tmp/illtool_trace_output.svg";

    // Build Python one-liner that calls vtracer
    char cmd[4096];
    snprintf(cmd, sizeof(cmd),
        "cd /Users/ryders/Developer/GitHub/ill_tool && "
        ".venv/bin/python -c \""
        "import vtracer; "
        "vtracer.convert_image_to_svg_py("
        "image_path='%s', "
        "out_path='%s', "
        "colormode='%s', "
        "hierarchical='stacked', "
        "mode='spline', "
        "filter_speckle=%d, "
        "color_precision=%d, "
        "layer_difference=%d, "
        "corner_threshold=%d, "
        "length_threshold=%.1f, "
        "max_iterations=%d, "
        "splice_threshold=%d, "
        "path_precision=3"
        ")\" 2>&1",
        traceInputPath.c_str(), svgPath.c_str(), colormode, effectiveSpeckle, colorPrec,
        layerDiff, effectiveCornerThresh, effectiveLengthThresh, maxIter, spliceThresh);

    fprintf(stderr, "[TraceModule] Running: %s\n", cmd);
    BridgeSetTraceStatus("Running vtracer...");

    FILE* pipe = popen(cmd, "r");
    if (!pipe) {
        BridgeSetTraceStatus("Failed to launch vtracer");
        fTraceInProgress = false;
        return;
    }

    // Read output (errors)
    char outputBuf[4096] = {};
    size_t totalRead = 0;
    while (fgets(outputBuf + totalRead, (int)(sizeof(outputBuf) - totalRead), pipe)) {
        totalRead = strlen(outputBuf);
    }
    int exitCode = pclose(pipe);

    if (exitCode != 0) {
        fprintf(stderr, "[TraceModule] vtracer failed (exit %d): %s\n", exitCode, outputBuf);
        BridgeSetTraceStatus(std::string("vtracer failed: ") + outputBuf);
        fTraceInProgress = false;
        return;
    }

    // Read the SVG file and create paths
    FILE* svgFile = fopen(svgPath.c_str(), "r");
    if (!svgFile) {
        BridgeSetTraceStatus("vtracer produced no output");
        fTraceInProgress = false;
        return;
    }

    fseek(svgFile, 0, SEEK_END);
    long svgSize = ftell(svgFile);
    fseek(svgFile, 0, SEEK_SET);
    std::string svgContent(svgSize, '\0');
    fread(&svgContent[0], 1, svgSize, svgFile);
    fclose(svgFile);

    fprintf(stderr, "[TraceModule] vtracer output: %ld bytes SVG\n", svgSize);

    // Parse SVG and create AI paths
    CreatePathsFromSVG(svgContent);

    // Persist trace artifacts to project store
    ProjectStore::Instance().SaveTraceSVG(svgPath);

    // Extract image filename for manifest
    std::string imageBasename = imagePath;
    size_t lastSlash = imageBasename.rfind('/');
    if (lastSlash != std::string::npos) {
        imageBasename = imageBasename.substr(lastSlash + 1);
    }

    // Count <path elements roughly for manifest
    int pathCount = 0;
    {
        size_t searchPos = 0;
        while ((searchPos = svgContent.find("<path", searchPos)) != std::string::npos) {
            pathCount++;
            searchPos += 5;
        }
        if (pathCount > 0) pathCount--;  // subtract background path
    }

    ProjectStore::Instance().SaveManifest(imageBasename, "vtracer", 0, pathCount);

    fTraceInProgress = false;
    sAIDocument->RedrawDocument();
}

//========================================================================================
//  ParseSVGPathToSegments — SVG path parser for vtracer-style paths
//========================================================================================

bool TraceModule::ParseSVGPathToSegments(const std::string& svgPath,
                                          std::vector<AIPathSegment>& outSegs,
                                          bool& outClosed)
{
    outSegs.clear();
    outClosed = false;

    auto appendLineTo = [&](double x, double y, bool forceCorner) {
        AIPathSegment seg = {};
        double ax = 0.0, ay = 0.0;
        TransformSVGPoint(x, y, ax, ay);
        seg.p.h = (AIReal)ax;
        seg.p.v = (AIReal)ay;
        seg.in = seg.p;
        seg.out = seg.p;
        seg.corner = forceCorner;
        outSegs.push_back(seg);
    };

    auto appendCubicTo = [&](double x1, double y1, double x2, double y2, double x3, double y3) {
        if (outSegs.empty()) return false;

        double oh = 0.0, ov = 0.0;
        TransformSVGPoint(x1, y1, oh, ov);
        outSegs.back().out.h = (AIReal)oh;
        outSegs.back().out.v = (AIReal)ov;
        outSegs.back().corner = false;

        AIPathSegment seg = {};
        double px = 0.0, py = 0.0;
        double ih = 0.0, iv = 0.0;
        TransformSVGPoint(x3, y3, px, py);
        TransformSVGPoint(x2, y2, ih, iv);
        seg.p.h = (AIReal)px;
        seg.p.v = (AIReal)py;
        seg.in.h = (AIReal)ih;
        seg.in.v = (AIReal)iv;
        seg.out = seg.p;
        seg.corner = false;
        outSegs.push_back(seg);
        return true;
    };

    size_t pos = 0;
    char cmd = 0;
    char prevCmd = 0;
    double curX = 0.0, curY = 0.0;
    double startX = 0.0, startY = 0.0;
    double lastCubicCtrlX = 0.0, lastCubicCtrlY = 0.0;
    double lastQuadCtrlX = 0.0, lastQuadCtrlY = 0.0;
    bool hasCurrentPoint = false;

    while (true) {
        SkipSVGSeparators(svgPath, pos);
        if (pos >= svgPath.size()) break;

        char next = svgPath[pos];
        if (IsSVGCommandChar(next)) {
            cmd = next;
            ++pos;
        } else if (cmd == 0) {
            fprintf(stderr, "[TraceModule] SVG path parse failed: missing initial command near '%c'\n", next);
            return false;
        }

        switch (cmd) {
            case 'M':
            case 'm': {
                double x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, x, y)) return false;
                if (cmd == 'm' && hasCurrentPoint) {
                    x += curX;
                    y += curY;
                }

                appendLineTo(x, y, true);
                curX = startX = x;
                curY = startY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = curX;
                lastCubicCtrlY = curY;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                cmd = (cmd == 'm') ? 'l' : 'L';
                break;
            }

            case 'L':
            case 'l': {
                double x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, x, y)) return false;
                if (cmd == 'l') {
                    x += curX;
                    y += curY;
                }

                appendLineTo(x, y, true);
                curX = x;
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = curX;
                lastCubicCtrlY = curY;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;
            }

            case 'H':
            case 'h': {
                double x = 0.0;
                if (!ParseSVGNumber(svgPath, pos, x)) return false;
                if (cmd == 'h') x += curX;
                appendLineTo(x, curY, true);
                curX = x;
                hasCurrentPoint = true;
                lastCubicCtrlX = curX;
                lastCubicCtrlY = curY;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;
            }

            case 'V':
            case 'v': {
                double y = 0.0;
                if (!ParseSVGNumber(svgPath, pos, y)) return false;
                if (cmd == 'v') y += curY;
                appendLineTo(curX, y, true);
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = curX;
                lastCubicCtrlY = curY;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;
            }

            case 'C':
            case 'c': {
                double x1 = 0.0, y1 = 0.0, x2 = 0.0, y2 = 0.0, x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, x1, y1) ||
                    !ParseSVGCoordinatePair(svgPath, pos, x2, y2) ||
                    !ParseSVGCoordinatePair(svgPath, pos, x, y)) {
                    return false;
                }
                if (cmd == 'c') {
                    x1 += curX; y1 += curY;
                    x2 += curX; y2 += curY;
                    x += curX; y += curY;
                }

                if (!appendCubicTo(x1, y1, x2, y2, x, y)) return false;
                curX = x;
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = x2;
                lastCubicCtrlY = y2;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;
            }

            case 'S':
            case 's': {
                double x2 = 0.0, y2 = 0.0, x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, x2, y2) ||
                    !ParseSVGCoordinatePair(svgPath, pos, x, y)) {
                    return false;
                }

                double x1 = curX;
                double y1 = curY;
                if (prevCmd == 'C' || prevCmd == 'c' || prevCmd == 'S' || prevCmd == 's') {
                    x1 = 2.0 * curX - lastCubicCtrlX;
                    y1 = 2.0 * curY - lastCubicCtrlY;
                }
                if (cmd == 's') {
                    x2 += curX; y2 += curY;
                    x += curX; y += curY;
                }

                if (!appendCubicTo(x1, y1, x2, y2, x, y)) return false;
                curX = x;
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = x2;
                lastCubicCtrlY = y2;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;
            }

            case 'Q':
            case 'q': {
                double qx = 0.0, qy = 0.0, x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, qx, qy) ||
                    !ParseSVGCoordinatePair(svgPath, pos, x, y)) {
                    return false;
                }
                if (cmd == 'q') {
                    qx += curX; qy += curY;
                    x += curX; y += curY;
                }

                double c1x = curX + (2.0 / 3.0) * (qx - curX);
                double c1y = curY + (2.0 / 3.0) * (qy - curY);
                double c2x = x + (2.0 / 3.0) * (qx - x);
                double c2y = y + (2.0 / 3.0) * (qy - y);
                if (!appendCubicTo(c1x, c1y, c2x, c2y, x, y)) return false;

                curX = x;
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = c2x;
                lastCubicCtrlY = c2y;
                lastQuadCtrlX = qx;
                lastQuadCtrlY = qy;
                prevCmd = cmd;
                break;
            }

            case 'T':
            case 't': {
                double x = 0.0, y = 0.0;
                if (!ParseSVGCoordinatePair(svgPath, pos, x, y)) return false;
                if (cmd == 't') {
                    x += curX;
                    y += curY;
                }

                double qx = curX;
                double qy = curY;
                if (prevCmd == 'Q' || prevCmd == 'q' || prevCmd == 'T' || prevCmd == 't') {
                    qx = 2.0 * curX - lastQuadCtrlX;
                    qy = 2.0 * curY - lastQuadCtrlY;
                }

                double c1x = curX + (2.0 / 3.0) * (qx - curX);
                double c1y = curY + (2.0 / 3.0) * (qy - curY);
                double c2x = x + (2.0 / 3.0) * (qx - x);
                double c2y = y + (2.0 / 3.0) * (qy - y);
                if (!appendCubicTo(c1x, c1y, c2x, c2y, x, y)) return false;

                curX = x;
                curY = y;
                hasCurrentPoint = true;
                lastCubicCtrlX = c2x;
                lastCubicCtrlY = c2y;
                lastQuadCtrlX = qx;
                lastQuadCtrlY = qy;
                prevCmd = cmd;
                break;
            }

            case 'Z':
            case 'z':
                outClosed = true;
                curX = startX;
                curY = startY;
                hasCurrentPoint = true;
                lastCubicCtrlX = curX;
                lastCubicCtrlY = curY;
                lastQuadCtrlX = curX;
                lastQuadCtrlY = curY;
                prevCmd = cmd;
                break;

            case 'A':
            case 'a':
                fprintf(stderr, "[TraceModule] Unsupported SVG path command '%c' in traced SVG\n", cmd);
                return false;

            default:
                fprintf(stderr, "[TraceModule] Unknown SVG path command '%c'\n", cmd);
                return false;
        }
    }

    return hasCurrentPoint && !outSegs.empty();
}

//========================================================================================
//  CreatePathsFromSVG — parse full SVG document, extract <path> elements
//========================================================================================

void TraceModule::CreatePathsFromSVG(const std::string& svgContent)
{
    // Extract SVG viewBox to get pixel dimensions for coordinate mapping
    fSvgWidth = 0;
    fSvgHeight = 0;
    gSvgViewBoxX = 0.0;
    gSvgViewBoxY = 0.0;

    std::string viewBoxValue;
    if (ExtractSVGAttribute(svgContent, "viewBox", viewBoxValue)) {
        double vbX = 0, vbY = 0, vbW = 0, vbH = 0;
        if (sscanf(viewBoxValue.c_str(), "%lf %lf %lf %lf", &vbX, &vbY, &vbW, &vbH) >= 4) {
            gSvgViewBoxX = vbX;
            gSvgViewBoxY = vbY;
            fSvgWidth = vbW;
            fSvgHeight = vbH;
            fprintf(stderr, "[TraceModule] SVG viewBox: %.0f %.0f %.0f %.0f\n", vbX, vbY, vbW, vbH);
        }
    }
    // Fallback: try width/height attributes
    if (fSvgWidth <= 0) {
        std::string widthValue;
        std::string heightValue;
        if (ExtractSVGAttribute(svgContent, "width", widthValue) &&
            ExtractSVGAttribute(svgContent, "height", heightValue)) {
            fSvgWidth = atof(widthValue.c_str());
            fSvgHeight = atof(heightValue.c_str());
        }
    }
    fprintf(stderr, "[TraceModule] SVG dims: %.0fx%.0f, Art bounds: L=%.0f T=%.0f R=%.0f B=%.0f\n",
            fSvgWidth, fSvgHeight, fArtLeft, fArtTop, fArtRight, fArtBottom);

    // Try to find a normal map for surface-based grouping
    std::string imagePath = FindImagePath();
    std::string normalMapPath;
    if (!imagePath.empty()) {
        normalMapPath = FindOrComputeNormalMap(imagePath);
    }

    // Collect all created paths flat (no groups yet) along with their fill colors
    std::vector<AIArtHandle> allPaths;
    std::vector<double> allFillR, allFillG, allFillB;
    std::vector<bool> allHasFill;

    // Create a master group for all trace output
    AIArtHandle traceGroup = nullptr;
    {
        ASErr gErr = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &traceGroup);
        if (gErr == kNoErr && traceGroup) {
            sAIArt->SetArtName(traceGroup, ai::UnicodeString("vtracer"));
        }
    }

    // Extract all <path> elements with d="..." and optional fill="..." attributes
    int created = 0;
    int skipped = 0;
    size_t pos = 0;
    bool firstPath = true;

    while (true) {
        size_t pathStart = svgContent.find("<path", pos);
        if (pathStart == std::string::npos) break;

        size_t pathEnd = svgContent.find(">", pathStart);
        if (pathEnd == std::string::npos) break;

        std::string pathElement = svgContent.substr(pathStart, pathEnd - pathStart + 1);

        std::string pathData;
        if (!ExtractSVGAttribute(pathElement, "d", pathData)) {
            pos = pathEnd;
            continue;
        }

        // Extract fill and transform
        std::string fillColor;
        ExtractSVGAttribute(pathElement, "fill", fillColor);

        std::string transformValue;
        ExtractSVGAttribute(pathElement, "transform", transformValue);
        double translateX = 0.0, translateY = 0.0;
        ParseSVGTranslate(transformValue, translateX, translateY);

        pos = pathEnd;

        // Skip first path — vtracer background rectangle covering entire image
        if (firstPath) {
            firstPath = false;
            skipped++;
            continue;
        }

        // Parse fill color
        double fr = 0, fg = 0, fb = 0;
        bool hasFill = !fillColor.empty() && fillColor != "none" && ParseHexColor(fillColor, fr, fg, fb);

        std::vector<AIPathSegment> segs;
        bool closed = false;
        bool parsed = ParseSVGPathToSegments(pathData, segs, closed);
        if (created < 3) {
            fprintf(stderr, "[TraceModule] Path %d: parsed=%d segs=%d pathData[0..60]='%s'\n",
                    created + skipped, (int)parsed, (int)segs.size(),
                    pathData.substr(0, 60).c_str());
        }
        if (parsed && !segs.empty()) {
            ApplyArtTranslation(segs, translateX, translateY,
                                fArtLeft, fArtTop, fArtRight, fArtBottom,
                                fSvgWidth, fSvgHeight);

            // Create path inside the trace group
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceInsideOnTop,
                                        traceGroup ? traceGroup : nullptr, &newPath);
            if (err == kNoErr && newPath) {
                ai::int16 nc = (ai::int16)segs.size();
                sAIPath->SetPathSegmentCount(newPath, nc);
                sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
                sAIPath->SetPathClosed(newPath, closed);

                AIPathStyle style;
                memset(&style, 0, sizeof(style));
                style.stroke.miterLimit = (AIReal)4.0;

                int traceOutputMode = BridgeGetTraceOutputMode();  // 0=outline, 1=fill, 2=centerline
                if (traceOutputMode == 0 || traceOutputMode == 2) {
                    // Outline mode: 1pt black stroke, no fill
                    style.fillPaint = false;
                    style.strokePaint = true;
                    style.stroke.width = (AIReal)1.0;
                    style.stroke.color.kind = kThreeColor;
                    style.stroke.color.c.rgb.red   = (AIReal)0.0;
                    style.stroke.color.c.rgb.green = (AIReal)0.0;
                    style.stroke.color.c.rgb.blue  = (AIReal)0.0;
                } else if (hasFill) {
                    // Fill mode with color: fill color from SVG, no stroke
                    style.fillPaint = true;
                    style.fill.color.kind = kThreeColor;
                    style.fill.color.c.rgb.red   = (AIReal)fr;
                    style.fill.color.c.rgb.green = (AIReal)fg;
                    style.fill.color.c.rgb.blue  = (AIReal)fb;
                    style.strokePaint = false;
                } else {
                    // Fill mode without color: default stroke
                    style.fillPaint = false;
                    style.strokePaint = true;
                    style.stroke.width = (AIReal)1.0;
                    style.stroke.color.kind = kThreeColor;
                }

                sAIPathStyle->SetPathStyle(newPath, &style);

                allPaths.push_back(newPath);
                allFillR.push_back(fr);
                allFillG.push_back(fg);
                allFillB.push_back(fb);
                allHasFill.push_back(hasFill);
                created++;
            }
        }
    }

    fprintf(stderr, "[TraceModule] Created %d flat paths (skipped %d)\n", created, skipped);

    // Post-process: group paths by surface identity or fall back to luminance
    if (!normalMapPath.empty() && !allPaths.empty()) {
        // Surface-based grouping from DSINE normal map
        fprintf(stderr, "[TraceModule] Grouping %d paths by surface via normal map: %s\n",
                (int)allPaths.size(), normalMapPath.c_str());
        int kPlanes = BridgeGetTraceKPlanes();
        GroupPathsBySurface(normalMapPath, kPlanes, allPaths, allFillR, allFillG, allFillB, allHasFill);
        BridgeSetTraceStatus("Traced: " + std::to_string(created) + " paths in surface groups");
    } else {
        // Fallback: luminance-based grouping (original behavior)
        fprintf(stderr, "[TraceModule] No normal map — falling back to luminance grouping\n");

        const char* groupNames[] = {"Trace — Background", "Trace — Highlights",
                                     "Trace — Midtones", "Trace — Shadows", "Trace — Outlines"};
        // Place luminance groups inside the traceGroup
        AIArtHandle groups[5] = {};
        for (int g = 0; g < 5; g++) {
            ASErr gErr = sAIArt->NewArt(kGroupArt,
                traceGroup ? kPlaceInsideOnTop : kPlaceAboveAll,
                traceGroup, &groups[g]);
            if (gErr == kNoErr && groups[g]) {
                sAIArt->SetArtName(groups[g], ai::UnicodeString(groupNames[g]));
            }
        }

        for (size_t i = 0; i < allPaths.size(); i++) {
            double luminance = allHasFill[i]
                ? (0.299 * allFillR[i] + 0.587 * allFillG[i] + 0.114 * allFillB[i])
                : 0.0;
            int groupIdx;
            if (luminance > 0.85)      groupIdx = 0;  // Background (near-white)
            else if (luminance > 0.60) groupIdx = 1;  // Highlights
            else if (luminance > 0.35) groupIdx = 2;  // Midtones
            else if (luminance > 0.10) groupIdx = 3;  // Shadows
            else                       groupIdx = 4;  // Outlines (near-black)

            sAIArt->ReorderArt(allPaths[i], kPlaceInsideOnTop, groups[groupIdx]);
        }

        // Delete empty groups
        for (int g = 0; g < 5; g++) {
            if (groups[g]) {
                AIArtHandle child = nullptr;
                sAIArt->GetArtFirstChild(groups[g], &child);
                if (!child) {
                    sAIArt->DisposeArt(groups[g]);
                }
            }
        }

        BridgeSetTraceStatus("Traced: " + std::to_string(created) + " paths in luminance groups");
    }

    // Move any top-level groups that were created by grouping into the trace master group
    // The surface/luminance groups were created at kPlaceAboveAll — move them into traceGroup
    if (traceGroup) {
        // Collect all top-level group art that isn't the traceGroup itself
        AIArtHandle child = nullptr;
        // The trace group might be empty if all paths were moved out by GroupPathsBySurface
        // Just leave the hierarchy as-is — the surface groups contain the paths
        // and the traceGroup name serves as a marker
        fprintf(stderr, "[TraceModule] Trace output in group 'vtracer'\n");
    }
}

//========================================================================================
//  TransformSVGPoint — map SVG pixel coords to Illustrator artwork coords
//========================================================================================

void TraceModule::TransformSVGPoint(double svgX, double svgY, double& artX, double& artY)
{
    // SVG: (0,0) top-left, Y increases downward, units = pixels
    // AI:  (artLeft, artTop) top-left, Y increases upward
    // Scale: SVG pixel range → art bounds range
    double artW = fArtRight - fArtLeft;
    double artH = fArtTop - fArtBottom;  // Y-up: top > bottom

    if (fSvgWidth > 0 && fSvgHeight > 0) {
        double scaleX = artW / fSvgWidth;
        double scaleY = artH / fSvgHeight;
        artX = fArtLeft + (svgX - gSvgViewBoxX) * scaleX;
        artY = fArtTop  - (svgY - gSvgViewBoxY) * scaleY;  // flip Y
    } else {
        // No viewBox known — assume 1:1 pixel mapping with Y flip
        artX = fArtLeft + (svgX - gSvgViewBoxX);
        artY = fArtTop  - (svgY - gSvgViewBoxY);
    }
}

//========================================================================================
//  FindOrComputeNormalMap — locate or generate DSINE normal map for the current image
//========================================================================================

std::string TraceModule::FindOrComputeNormalMap(const std::string& imagePath)
{
    // Strategy 0: Check project store first (persisted from previous session)
    {
        std::string projectNormal = ProjectStore::Instance().GetNormalMapPath();
        if (!projectNormal.empty()) {
            fprintf(stderr, "[TraceModule] Found normal map in project store: %s\n", projectNormal.c_str());
            return projectNormal;
        }
    }

    // Strategy 1: Check if a prior Normal Reference run already produced a normal map
    // Normal ref outputs go to /tmp/illtool_normal_ref_output/ or /tmp/ai_normal_ref_*
    std::vector<std::string> searchDirs;
    searchDirs.push_back("/tmp/illtool_normal_ref_output");

    // Scan /tmp for ai_normal_ref_* directories
    DIR* tmpDir = opendir("/tmp");
    if (tmpDir) {
        struct dirent* entry;
        while ((entry = readdir(tmpDir)) != nullptr) {
            std::string name = entry->d_name;
            if (name.find("ai_normal_ref_") == 0) {
                searchDirs.push_back("/tmp/" + name);
            }
        }
        closedir(tmpDir);
    }

    // Check each directory for normal_map.png
    for (const auto& dir : searchDirs) {
        std::string candidate = dir + "/normal_map.png";
        struct stat st;
        if (stat(candidate.c_str(), &st) == 0 && st.st_size > 0) {
            fprintf(stderr, "[TraceModule] Found existing normal map: %s\n", candidate.c_str());
            // Persist to project store for future sessions
            ProjectStore::Instance().SaveNormalMap(candidate);
            return candidate;
        }
    }

    // Strategy 2: Generate normal map in C++ from the image as a height map (Sobel gradient)
    // This replaces the DSINE Python fallback — no external process needed.
    fprintf(stderr, "[TraceModule] No existing normal map found, computing via C++ Sobel...\n");
    BridgeSetTraceStatus("Computing normal map (C++)...");

    int grayW = 0, grayH = 0, grayCh = 0;
    unsigned char* gray = stbi_load(imagePath.c_str(), &grayW, &grayH, &grayCh, 1);
    if (!gray || grayW < 3 || grayH < 3) {
        fprintf(stderr, "[TraceModule] Failed to load image as grayscale for normal map: %s\n",
                imagePath.c_str());
        if (gray) stbi_image_free(gray);
        return "";
    }

    // Pre-blur the height map to smooth noise before Sobel gradient
    double normalBlur = BridgeGetTraceNormalBlur();
    if (normalBlur > 0.1) {
        int radius = (int)(normalBlur * 2);  // sigma to radius approximation
        if (radius < 1) radius = 1;
        if (radius > 10) radius = 10;

        // Two-pass box blur for approximate Gaussian smoothing
        std::vector<unsigned char> temp(grayW * grayH);
        for (int pass = 0; pass < 2; pass++) {
            unsigned char* src = (pass == 0) ? gray : temp.data();
            unsigned char* dst = (pass == 0) ? temp.data() : gray;
            for (int y = 0; y < grayH; y++) {
                for (int x = 0; x < grayW; x++) {
                    int sum = 0, count = 0;
                    for (int dy = -radius; dy <= radius; dy++) {
                        for (int dx = -radius; dx <= radius; dx++) {
                            int ny = y + dy, nx = x + dx;
                            if (ny >= 0 && ny < grayH && nx >= 0 && nx < grayW) {
                                sum += src[ny * grayW + nx];
                                count++;
                            }
                        }
                    }
                    dst[y * grayW + x] = (unsigned char)(sum / count);
                }
            }
        }
        fprintf(stderr, "[TraceModule] Normal pre-blur: sigma=%.1f radius=%d\n", normalBlur, radius);
    }

    double normalStrength = BridgeGetTraceNormalStrength();
    fprintf(stderr, "[TraceModule] Normal strength: %.1f\n", normalStrength);
    unsigned char* normals = VisionEngine::GenerateNormalFromHeight(gray, grayW, grayH, normalStrength);
    stbi_image_free(gray);

    if (!normals) {
        fprintf(stderr, "[TraceModule] GenerateNormalFromHeight failed\n");
        return "";
    }

    std::string resultPath = "/tmp/illtool_height_normal.png";
    int wrote = stbi_write_png(resultPath.c_str(), grayW, grayH, 3, normals, grayW * 3);
    delete[] normals;

    if (!wrote) {
        fprintf(stderr, "[TraceModule] stbi_write_png failed for normal map\n");
        return "";
    }

    fprintf(stderr, "[TraceModule] Generated C++ normal map: %s (%dx%d)\n",
            resultPath.c_str(), grayW, grayH);

    // Persist to project store for future sessions
    ProjectStore::Instance().SaveNormalMap(resultPath);

    return resultPath;
}

//========================================================================================
//  GroupPathsBySurface — cluster paths by DSINE normal map surface identity
//========================================================================================

void TraceModule::GroupPathsBySurface(const std::string& normalMapPath, int k,
                                      const std::vector<AIArtHandle>& paths,
                                      const std::vector<double>& fillR,
                                      const std::vector<double>& fillG,
                                      const std::vector<double>& fillB,
                                      const std::vector<bool>& hasFillVec)
{
    // 1. Load the normal map PNG (3 channels RGB)
    int nmW = 0, nmH = 0, nmC = 0;
    unsigned char* normalPixels = stbi_load(normalMapPath.c_str(), &nmW, &nmH, &nmC, 3);
    if (!normalPixels || nmW <= 0 || nmH <= 0) {
        fprintf(stderr, "[TraceModule] GroupPathsBySurface: failed to load normal map %s\n",
                normalMapPath.c_str());
        if (normalPixels) stbi_image_free(normalPixels);
        return;
    }

    fprintf(stderr, "[TraceModule] GroupPathsBySurface: normal map %dx%d, %d paths, k=%d\n",
            nmW, nmH, (int)paths.size(), k);

    // 2. Cluster normal map into K surface regions
    int kmeansStride = BridgeGetTraceKMeansStride();
    int kmeansIter   = BridgeGetTraceKMeansIter();
    auto regions = VisionEngine::Instance().ClusterNormalMapRegions(normalPixels, nmW, nmH, k,
                                                                    kmeansStride, kmeansIter);
    if (regions.empty()) {
        fprintf(stderr, "[TraceModule] GroupPathsBySurface: clustering returned 0 regions\n");
        stbi_image_free(normalPixels);
        return;
    }

    // 3. Create AI groups per cluster
    //    Each cluster: "Surface N: <label> (M paths)"
    //    Within each: sub-groups by path area (Large >5%, Medium 1-5%, Small <1%)
    std::vector<AIArtHandle> surfaceGroups(regions.size(), nullptr);
    std::vector<AIArtHandle> subLarge(regions.size(), nullptr);
    std::vector<AIArtHandle> subMedium(regions.size(), nullptr);
    std::vector<AIArtHandle> subSmall(regions.size(), nullptr);

    for (size_t r = 0; r < regions.size(); r++) {
        char groupName[256];
        snprintf(groupName, sizeof(groupName), "Surface %d: %s",
                 (int)(r + 1), regions[r].label.c_str());

        // Place surface groups inside the paths' parent (traceGroup if it exists)
        AIArtHandle parentGroup = nullptr;
        if (!paths.empty()) {
            sAIArt->GetArtParent(paths[0], &parentGroup);
        }
        ASErr err = sAIArt->NewArt(kGroupArt,
            parentGroup ? kPlaceInsideOnTop : kPlaceAboveAll,
            parentGroup, &surfaceGroups[r]);
        if (err == kNoErr && surfaceGroups[r]) {
            sAIArt->SetArtName(surfaceGroups[r], ai::UnicodeString(groupName));
        }

        // Create size sub-groups inside each surface group
        err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, surfaceGroups[r], &subLarge[r]);
        if (err == kNoErr && subLarge[r]) {
            sAIArt->SetArtName(subLarge[r], ai::UnicodeString("Large (>5%)"));
        }
        err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, surfaceGroups[r], &subMedium[r]);
        if (err == kNoErr && subMedium[r]) {
            sAIArt->SetArtName(subMedium[r], ai::UnicodeString("Medium (1-5%)"));
        }
        err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, surfaceGroups[r], &subSmall[r]);
        if (err == kNoErr && subSmall[r]) {
            sAIArt->SetArtName(subSmall[r], ai::UnicodeString("Small (<1%)"));
        }
    }

    // 4. Compute total artboard area for relative size classification
    double artW = fArtRight - fArtLeft;
    double artH = fArtTop - fArtBottom;
    double totalArea = artW * artH;
    if (totalArea <= 0) totalArea = 1.0;  // guard

    // 5. Assign each path to its nearest surface cluster
    int assigned = 0;
    for (size_t i = 0; i < paths.size(); i++) {
        AIArtHandle pathArt = paths[i];

        // Compute path centroid from its bounding box (fast approximation)
        AIRealRect bounds = {0, 0, 0, 0};
        sAIArt->GetArtBounds(pathArt, &bounds);
        double centroidArtX = (bounds.left + bounds.right) / 2.0;
        double centroidArtY = (bounds.top + bounds.bottom) / 2.0;

        // Reverse TransformSVGPoint: art coords → pixel coords in normal map space
        // artX = fArtLeft + svgX * (artW / svgW) → svgX = (artX - fArtLeft) * svgW / artW
        // artY = fArtTop  - svgY * (artH / svgH) → svgY = (fArtTop - artY) * svgH / artH
        // Then map SVG pixel coords to normal map pixel coords (they may differ in resolution)
        double pixX = 0, pixY = 0;
        if (fSvgWidth > 0 && fSvgHeight > 0 && artW > 0 && artH > 0) {
            double svgX = (centroidArtX - fArtLeft) / artW * fSvgWidth;
            double svgY = (fArtTop - centroidArtY) / artH * fSvgHeight;
            // SVG pixel → normal map pixel (normal map may be different resolution)
            pixX = svgX / fSvgWidth * nmW;
            pixY = svgY / fSvgHeight * nmH;
        } else {
            // Fallback: direct mapping
            pixX = (centroidArtX - fArtLeft) / artW * nmW;
            pixY = (fArtTop - centroidArtY) / artH * nmH;
        }

        // Clamp to valid pixel range
        int px = std::max(0, std::min(nmW - 1, (int)pixX));
        int py = std::max(0, std::min(nmH - 1, (int)pixY));

        // Sample normal map RGB at this pixel
        int nmIdx = (py * nmW + px) * 3;
        double sR = normalPixels[nmIdx]     / 255.0;
        double sG = normalPixels[nmIdx + 1] / 255.0;
        double sB = normalPixels[nmIdx + 2] / 255.0;

        // Find nearest cluster (smallest Euclidean distance in normal space)
        int bestCluster = 0;
        double bestDist = 1e30;
        for (size_t c = 0; c < regions.size(); c++) {
            double dr = sR - regions[c].nx;
            double dg = sG - regions[c].ny;
            double db = sB - regions[c].nz;
            double dist = dr * dr + dg * dg + db * db;
            if (dist < bestDist) {
                bestDist = dist;
                bestCluster = (int)c;
            }
        }

        // Classify by path area relative to total artboard
        double pathArea = std::abs((double)(bounds.right - bounds.left) *
                                   (double)(bounds.top - bounds.bottom));
        double areaPercent = (pathArea / totalArea) * 100.0;

        AIArtHandle targetGroup;
        if (areaPercent > 5.0)       targetGroup = subLarge[bestCluster];
        else if (areaPercent > 1.0)  targetGroup = subMedium[bestCluster];
        else                         targetGroup = subSmall[bestCluster];

        if (targetGroup) {
            sAIArt->ReorderArt(pathArt, kPlaceInsideOnTop, targetGroup);
            assigned++;

            // Write surface identity to path's dictionary for downstream modules
            AIDictionaryRef dict = nullptr;
            if (sAIArt->GetDictionary(pathArt, &dict) == kNoErr && dict) {
                static AIDictKey surfIdKey  = sAIDictionary->Key("IllToolSurfaceId");
                static AIDictKey normalXKey = sAIDictionary->Key("IllToolNormalX");
                static AIDictKey normalYKey = sAIDictionary->Key("IllToolNormalY");
                static AIDictKey normalZKey = sAIDictionary->Key("IllToolNormalZ");

                sAIDictionary->SetIntegerEntry(dict, surfIdKey, (ai::int32)bestCluster);
                sAIDictionary->SetRealEntry(dict, normalXKey, (AIReal)regions[bestCluster].nx);
                sAIDictionary->SetRealEntry(dict, normalYKey, (AIReal)regions[bestCluster].ny);
                sAIDictionary->SetRealEntry(dict, normalZKey, (AIReal)regions[bestCluster].nz);
                sAIDictionary->Release(dict);
            }
        }
    }

    // 6. Clean up empty sub-groups and surface groups
    for (size_t r = 0; r < regions.size(); r++) {
        AIArtHandle* subs[] = {&subLarge[r], &subMedium[r], &subSmall[r]};
        for (int s = 0; s < 3; s++) {
            if (*subs[s]) {
                AIArtHandle child = nullptr;
                sAIArt->GetArtFirstChild(*subs[s], &child);
                if (!child) {
                    sAIArt->DisposeArt(*subs[s]);
                    *subs[s] = nullptr;
                }
            }
        }

        // Rename surface group with path count
        if (surfaceGroups[r]) {
            AIArtHandle child = nullptr;
            sAIArt->GetArtFirstChild(surfaceGroups[r], &child);
            if (!child) {
                sAIArt->DisposeArt(surfaceGroups[r]);
                surfaceGroups[r] = nullptr;
            } else {
                // Count paths in this surface group (across sub-groups)
                int count = 0;
                AIArtHandle* remaining[] = {&subLarge[r], &subMedium[r], &subSmall[r]};
                for (int s = 0; s < 3; s++) {
                    if (*remaining[s]) {
                        AIArtHandle c = nullptr;
                        sAIArt->GetArtFirstChild(*remaining[s], &c);
                        while (c) {
                            count++;
                            AIArtHandle next = nullptr;
                            sAIArt->GetArtSibling(c, &next);
                            c = next;
                        }
                    }
                }
                char finalName[256];
                snprintf(finalName, sizeof(finalName), "Surface %d: %s (%d paths)",
                         (int)(r + 1), regions[r].label.c_str(), count);
                sAIArt->SetArtName(surfaceGroups[r], ai::UnicodeString(finalName));
            }
        }
    }

    stbi_image_free(normalPixels);

    fprintf(stderr, "[TraceModule] GroupPathsBySurface: assigned %d/%d paths to %d surface groups\n",
            assigned, (int)paths.size(), (int)regions.size());
}

//========================================================================================
//  ExecutePythonBackend — run normal_ref or form_edge via Python, place output PNGs
//========================================================================================

void TraceModule::ExecutePythonBackend(const std::string& backend)
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace already in progress, skipping\n");
        return;
    }
    fTraceInProgress = true;

    std::string displayName = (backend == "normal_ref") ? "Normal Reference" : "Form Edge Extract";
    BridgeSetTraceStatus("Running " + displayName + "...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found — use File > Place to add a linked image");
        fTraceInProgress = false;
        return;
    }

    // Snapshot art bounds BEFORE the backend runs — FindImagePath() just set them
    double refLeft = fArtLeft, refTop = fArtTop, refRight = fArtRight, refBottom = fArtBottom;

    fprintf(stderr, "[TraceModule] Running %s backend on: %s\n", backend.c_str(), imagePath.c_str());

    // Call the standalone Python script that wraps normal_reference and form_edge_extract
    std::string outputDir = "/tmp/illtool_" + backend + "_output";
    char cmd[4096];
    snprintf(cmd, sizeof(cmd),
        "cd /Users/ryders/Developer/GitHub/ill_tool && "
        ".venv/bin/python plugin/tools/run_trace_backend.py "
        "--backend %s "
        "--image '%s' "
        "--output-dir '%s' "
        "2>&1",
        backend.c_str(), imagePath.c_str(), outputDir.c_str());

    fprintf(stderr, "[TraceModule] Running: %s\n", cmd);

    FILE* pipe = popen(cmd, "r");
    if (!pipe) {
        BridgeSetTraceStatus("Failed to launch Python backend");
        fTraceInProgress = false;
        return;
    }

    // Read all output (the script prints JSON manifest on stdout)
    std::string output;
    char buf[4096];
    while (fgets(buf, sizeof(buf), pipe)) {
        output += buf;
    }
    int exitCode = pclose(pipe);

    if (exitCode != 0) {
        fprintf(stderr, "[TraceModule] Python backend failed (exit %d): %s\n", exitCode, output.c_str());
        BridgeSetTraceStatus(displayName + " failed: " + output.substr(0, 200));
        fTraceInProgress = false;
        return;
    }

    fprintf(stderr, "[TraceModule] Python backend output: %s\n", output.c_str());

    // Parse JSON manifest: {"files": [{"name": "...", "path": "..."}, ...]}
    // Find the JSON object in the output (skip any stderr lines that leaked through)
    size_t jsonStart = output.find("{");
    if (jsonStart == std::string::npos) {
        BridgeSetTraceStatus(displayName + " produced no JSON output");
        fTraceInProgress = false;
        return;
    }

    try {
        json manifest = json::parse(output.substr(jsonStart));

        if (manifest.contains("error")) {
            std::string errMsg = manifest["error"].get<std::string>();
            BridgeSetTraceStatus(displayName + ": " + errMsg);
            fTraceInProgress = false;
            return;
        }

        auto files = manifest["files"];
        int placed = 0;

        int tracedTotal = 0;

        // Collect file info for deferred raster placement (references go on TOP, after vectors)
        struct FileEntry { std::string name; std::string path; };
        std::vector<FileEntry> fileEntries;

        for (auto& entry : files) {
            std::string name = entry["name"].get<std::string>();
            std::string path = entry["path"].get<std::string>();
            fileEntries.push_back({name, path});
            placed++;

            // 2. Trace the rendering through vtracer → vector paths
            std::string svgOut = "/tmp/illtool_trace_" + std::to_string(placed) + ".svg";
            char traceCmd[4096];
            snprintf(traceCmd, sizeof(traceCmd),
                "cd /Users/ryders/Developer/GitHub/ill_tool && "
                ".venv/bin/python -c \""
                "import vtracer; "
                "vtracer.convert_image_to_svg_py("
                "image_path='%s', "
                "out_path='%s', "
                "colormode='bw', "
                "hierarchical='stacked', "
                "mode='spline', "
                "filter_speckle=1, "
                "color_precision=3, "
                "layer_difference=%d, "
                "corner_threshold=60, "
                "length_threshold=%.1f, "
                "max_iterations=%d, "
                "splice_threshold=%d, "
                "path_precision=3"
                ")\" 2>&1",
                path.c_str(), svgOut.c_str(),
                BridgeGetTraceLayerDiff(), BridgeGetTraceLengthThresh(),
                BridgeGetTraceMaxIter(), BridgeGetTraceSpliceThresh());

            fprintf(stderr, "[TraceModule] Tracing %s → vectors...\n", name.c_str());
            BridgeSetTraceStatus("Tracing " + name + "...");

            FILE* tracePipe = popen(traceCmd, "r");
            if (tracePipe) {
                char tbuf[1024];
                while (fgets(tbuf, sizeof(tbuf), tracePipe)) {}
                int traceExit = pclose(tracePipe);

                if (traceExit == 0) {
                    // Read SVG and create vector paths
                    FILE* svgFile = fopen(svgOut.c_str(), "r");
                    if (svgFile) {
                        fseek(svgFile, 0, SEEK_END);
                        long svgSize = ftell(svgFile);
                        fseek(svgFile, 0, SEEK_SET);
                        std::string svgContent(svgSize, '\0');
                        fread(&svgContent[0], 1, svgSize, svgFile);
                        fclose(svgFile);

                        // Use the same art bounds as the reference image
                        // (rendering PNGs are same dimensions as input)
                        CreatePathsFromSVG(svgContent);
                        tracedTotal++;
                        fprintf(stderr, "[TraceModule] Vectorized %s\n", name.c_str());
                    }
                } else {
                    fprintf(stderr, "[TraceModule] vtracer failed for %s (exit %d)\n",
                            name.c_str(), traceExit);
                }
            }
        }

        // Place raster references LAST so they're on top of the vector layers
        for (auto& fe : fileEntries) {
            fprintf(stderr, "[TraceModule] Placing reference: %s -> %s\n", fe.name.c_str(), fe.path.c_str());
            PlaceImageAsLayer(fe.path, fe.name + " (ref)", refLeft, refTop, refRight, refBottom);
        }

        char statusBuf[256];
        snprintf(statusBuf, sizeof(statusBuf), "%s: %d references + %d vectorized",
                 displayName.c_str(), placed, tracedTotal);
        BridgeSetTraceStatus(statusBuf);
        sAIDocument->RedrawDocument();

    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] JSON parse error: %s\n", ex.what());
        BridgeSetTraceStatus(displayName + " JSON error: " + std::string(ex.what()));
    }

    fTraceInProgress = false;
}

//========================================================================================
//  PlaceImageAsLayer — create a new layer with a placed PNG image, locked and hidden
//  Two-arg version: uses current member fArt* bounds (backward compat)
//========================================================================================

void TraceModule::PlaceImageAsLayer(const std::string& imagePath, const std::string& layerName)
{
    PlaceImageAsLayer(imagePath, layerName, fArtLeft, fArtTop, fArtRight, fArtBottom);
}

//========================================================================================
//  PlaceImageAsLayer (explicit bounds) — avoids re-querying member vars between calls
//========================================================================================

void TraceModule::PlaceImageAsLayer(const std::string& imagePath, const std::string& layerName,
                                     double artLeft, double artTop, double artRight, double artBottom)
{
    try {
        // Load PNG pixels via stb_image
        int imgW = 0, imgH = 0, imgChannels = 0;
        unsigned char* pixels = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgChannels, 0);
        if (!pixels || imgW <= 0 || imgH <= 0) {
            fprintf(stderr, "[TraceModule] stbi_load failed for %s\n", imagePath.c_str());
            if (pixels) stbi_image_free(pixels);
            return;
        }
        fprintf(stderr, "[TraceModule] Loaded %dx%d (%d ch) from %s\n",
                imgW, imgH, imgChannels, imagePath.c_str());

        // Create a new layer
        AILayerHandle newLayer = nullptr;
        ai::UnicodeString uLayerName(layerName.c_str());
        ASErr err = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &newLayer);
        if (err != kNoErr || !newLayer) {
            fprintf(stderr, "[TraceModule] Failed to create layer: %d\n", (int)err);
            stbi_image_free(pixels);
            return;
        }
        sAILayer->SetLayerTitle(newLayer, uLayerName);
        sAILayer->SetCurrentLayer(newLayer);

        // Determine AI color space from channel count
        // stbi returns 1=gray, 2=gray+alpha, 3=RGB, 4=RGBA
        int aiColorSpace = kRGBColorSpace;
        int aiChannels = imgChannels;
        if (imgChannels == 1) {
            aiColorSpace = kGrayColorSpace;
        } else if (imgChannels == 2) {
            aiColorSpace = kAlphaGrayColorSpace;
        } else if (imgChannels == 3) {
            aiColorSpace = kRGBColorSpace;
        } else if (imgChannels >= 4) {
            aiColorSpace = kAlphaRGBColorSpace;
            aiChannels = 4;
        }

        // Set up raster info
        AIRasterRecord rasterInfo;
        memset(&rasterInfo, 0, sizeof(rasterInfo));
        rasterInfo.colorSpace = aiColorSpace;
        rasterInfo.bitsPerPixel = (ai::int16)(aiChannels * 8);
        rasterInfo.bounds.left = 0;
        rasterInfo.bounds.top = 0;
        rasterInfo.bounds.right = imgW;
        rasterInfo.bounds.bottom = imgH;
        rasterInfo.byteWidth = imgW * aiChannels;
        rasterInfo.flags = 0;

        // Create raster art
        AIArtHandle rasterArt = nullptr;
        err = sAIArt->NewArt(kRasterArt, kPlaceAboveAll, nullptr, &rasterArt);
        if (err != kNoErr || !rasterArt) {
            fprintf(stderr, "[TraceModule] Failed to create raster art: %d\n", (int)err);
            stbi_image_free(pixels);
            return;
        }

        // Set raster info (dimensions, color space)
        err = sAIRaster->SetRasterInfo(rasterArt, &rasterInfo);
        if (err != kNoErr) {
            fprintf(stderr, "[TraceModule] SetRasterInfo failed: %d\n", (int)err);
            sAIArt->DisposeArt(rasterArt);
            stbi_image_free(pixels);
            return;
        }

        // Copy pixel data via SetRasterTile
        AITile tile;
        memset(&tile, 0, sizeof(tile));
        tile.bounds.left = 0;
        tile.bounds.top = 0;
        tile.bounds.right = imgW;
        tile.bounds.bottom = imgH;
        tile.bounds.front = 0;
        tile.bounds.back = aiChannels;
        tile.data = pixels;
        tile.rowBytes = imgW * aiChannels;
        tile.colBytes = aiChannels;
        tile.planeBytes = 0;
        for (int i = 0; i < aiChannels && i < kMaxChannels; ++i) {
            tile.channelInterleave[i] = static_cast<ai::int16>(i);
        }

        AISlice artSlice;
        memset(&artSlice, 0, sizeof(artSlice));
        artSlice.left = 0;
        artSlice.top = 0;
        artSlice.right = imgW;
        artSlice.bottom = imgH;
        artSlice.front = 0;
        artSlice.back = aiChannels;

        AISlice workSlice;
        memset(&workSlice, 0, sizeof(workSlice));
        workSlice.left = 0;
        workSlice.top = 0;
        workSlice.right = imgW;
        workSlice.bottom = imgH;
        workSlice.front = 0;
        workSlice.back = aiChannels;

        err = sAIRaster->SetRasterTile(rasterArt, &artSlice, &tile, &workSlice);
        stbi_image_free(pixels);  // Done with pixel data
        if (err != kNoErr) {
            fprintf(stderr, "[TraceModule] SetRasterTile failed: %d\n", (int)err);
            sAIArt->DisposeArt(rasterArt);
            return;
        }

        // Position the raster to match the reference art bounds
        if (artRight > artLeft && artTop > artBottom) {
            double targetW = artRight - artLeft;
            double targetH = artTop - artBottom;

            // Raster matrix maps pixel space to artwork space.
            // AI raster: pixel (0,0) at top-left, Y increases down.
            // AI artwork: Y increases up, origin at bottom-left.
            // The standard placement matrix for a raster at 72ppi:
            //   a  = width_in_points / pixel_width   (horizontal scale)
            //   d  = -height_in_points / pixel_height (negative = flip Y)
            //   tx = left edge in artwork coords
            //   ty = TOP edge in artwork coords (because d is negative, pixel 0 maps here)
            AIRealMatrix matrix;
            double sx = targetW / (double)imgW;
            double sy = targetH / (double)imgH;
            if (fHasOrigMatrix) {
                // Copy the original raster's matrix exactly — guaranteed correct positioning
                matrix = fOrigRasterMatrix;
                // Scale if our image has different pixel dimensions than the original
                AIRasterRecord origInfo;
                // The original matrix maps origPixels → artwork space.
                // Our image is imgW x imgH. Scale the matrix to map our pixels to same artwork area.
                double origPixW = targetW / fOrigRasterMatrix.a;  // original pixel width
                double origPixH = targetH / fOrigRasterMatrix.d;  // original pixel height
                if (std::abs(origPixW) > 0.001 && std::abs(origPixH) > 0.001) {
                    matrix.a = (AIReal)(fOrigRasterMatrix.a * (origPixW / (double)imgW));
                    matrix.d = (AIReal)(fOrigRasterMatrix.d * (origPixH / (double)imgH));
                }
                fprintf(stderr, "[TraceModule] Using original matrix: a=%.4f d=%.4f tx=%.1f ty=%.1f\n",
                        matrix.a, matrix.d, matrix.tx, matrix.ty);
            } else {
                // Fallback: identity-like matrix
                matrix.a = (AIReal)sx;
                matrix.b = (AIReal)0.0;
                matrix.c = (AIReal)0.0;
                matrix.d = (AIReal)sy;
                matrix.tx = (AIReal)artLeft;
                matrix.ty = (AIReal)artBottom;
            }

            err = sAIRaster->SetRasterMatrix(rasterArt, &matrix);
            if (err != kNoErr) {
                fprintf(stderr, "[TraceModule] SetRasterMatrix failed: %d\n", (int)err);
            } else {
                fprintf(stderr, "[TraceModule] Raster positioned: %dx%d -> %.0fx%.0f at (%.0f,%.0f)\n",
                        imgW, imgH, targetW, targetH, artLeft, artTop);
            }
        }

        // Lock and hide the layer
        sAILayer->SetLayerVisible(newLayer, false);
        sAILayer->SetLayerEditable(newLayer, false);

        fprintf(stderr, "[TraceModule] Embedded raster layer '%s' from %s (%dx%d)\n",
                layerName.c_str(), imagePath.c_str(), imgW, imgH);

    } catch (ai::Error& ex) {
        fprintf(stderr, "[TraceModule] AI Error placing raster: %d\n", (int)ex);
    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] Exception placing raster: %s\n", ex.what());
    } catch (...) {
        fprintf(stderr, "[TraceModule] Unknown error placing raster\n");
    }
}

//========================================================================================
//  DrawOverlay — draw cutout preview silhouette as an annotator overlay
//========================================================================================

void TraceModule::DrawOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer || !sAIDocumentView) return;

    // Draw pose overlay (body skeleton, face landmarks, hand joints)
    DrawPoseOverlay(message);

    // Draw cutout preview silhouette
    if (!BridgeGetCutoutPreviewActive()) return;

    std::string pathsJSON = BridgeGetCutoutPreviewPaths();
    if (pathsJSON.empty()) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Parse the preview paths JSON: array of {points: [{x,y,inX,inY,outX,outY}, ...], closed: bool}
    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) return;

        // Magenta overlay for the cutout silhouette
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_MASK());
        sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_MASK);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.85);

        for (const auto& pathObj : previewData) {
            if (!pathObj.contains("points")) continue;
            const auto& points = pathObj["points"];
            if (!points.is_array() || points.size() < 2) continue;
            bool closed = pathObj.value("closed", false);

            // Draw line segments between consecutive anchor points
            // For bezier curves, sample intermediate points for smooth drawing
            for (size_t i = 0; i + 1 < points.size(); i++) {
                const auto& p0 = points[i];
                const auto& p1 = points[i + 1];

                double x0 = p0.value("x", 0.0);
                double y0 = p0.value("y", 0.0);
                double ox0 = p0.value("outX", x0);
                double oy0 = p0.value("outY", y0);
                double ix1 = p1.value("inX", p1.value("x", 0.0));
                double iy1 = p1.value("inY", p1.value("y", 0.0));
                double x1 = p1.value("x", 0.0);
                double y1 = p1.value("y", 0.0);

                // Check if this is a straight line or a bezier curve
                bool isCurve = (std::abs(ox0 - x0) > 0.1 || std::abs(oy0 - y0) > 0.1 ||
                                std::abs(ix1 - x1) > 0.1 || std::abs(iy1 - y1) > 0.1);

                if (isCurve) {
                    // Sample cubic bezier curve at fixed intervals for smooth display
                    const int steps = 12;
                    AIPoint prevView;
                    bool havePrev = false;
                    for (int s = 0; s <= steps; s++) {
                        double t = (double)s / steps;
                        double u = 1.0 - t;
                        // Cubic bezier: B(t) = (1-t)^3*P0 + 3(1-t)^2*t*CP0 + 3(1-t)*t^2*CP1 + t^3*P1
                        double bx = u*u*u*x0 + 3*u*u*t*ox0 + 3*u*t*t*ix1 + t*t*t*x1;
                        double by = u*u*u*y0 + 3*u*u*t*oy0 + 3*u*t*t*iy1 + t*t*t*y1;

                        AIRealPoint artPt;
                        artPt.h = (AIReal)bx;
                        artPt.v = (AIReal)by;
                        AIPoint viewPt;
                        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &viewPt) != kNoErr)
                            continue;

                        if (havePrev) {
                            sAIAnnotatorDrawer->DrawLine(drawer, prevView, viewPt);
                        }
                        prevView = viewPt;
                        havePrev = true;
                    }
                } else {
                    // Straight line segment
                    AIRealPoint artA, artB;
                    artA.h = (AIReal)x0; artA.v = (AIReal)y0;
                    artB.h = (AIReal)x1; artB.v = (AIReal)y1;

                    AIPoint viewA, viewB;
                    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artA, &viewA) == kNoErr &&
                        sAIDocumentView->ArtworkPointToViewPoint(NULL, &artB, &viewB) == kNoErr) {
                        sAIAnnotatorDrawer->DrawLine(drawer, viewA, viewB);
                    }
                }
            }

            // Close the path: draw from last point back to first
            if (closed && points.size() >= 3) {
                const auto& pLast = points.back();
                const auto& pFirst = points[0];

                double x0 = pLast.value("x", 0.0);
                double y0 = pLast.value("y", 0.0);
                double ox0 = pLast.value("outX", x0);
                double oy0 = pLast.value("outY", y0);
                double ix1 = pFirst.value("inX", pFirst.value("x", 0.0));
                double iy1 = pFirst.value("inY", pFirst.value("y", 0.0));
                double x1 = pFirst.value("x", 0.0);
                double y1 = pFirst.value("y", 0.0);

                bool isCurve = (std::abs(ox0 - x0) > 0.1 || std::abs(oy0 - y0) > 0.1 ||
                                std::abs(ix1 - x1) > 0.1 || std::abs(iy1 - y1) > 0.1);

                if (isCurve) {
                    const int steps = 12;
                    AIPoint prevView;
                    bool havePrev = false;
                    for (int s = 0; s <= steps; s++) {
                        double t = (double)s / steps;
                        double u = 1.0 - t;
                        double bx = u*u*u*x0 + 3*u*u*t*ox0 + 3*u*t*t*ix1 + t*t*t*x1;
                        double by = u*u*u*y0 + 3*u*u*t*oy0 + 3*u*t*t*iy1 + t*t*t*y1;

                        AIRealPoint artPt;
                        artPt.h = (AIReal)bx;
                        artPt.v = (AIReal)by;
                        AIPoint viewPt;
                        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &viewPt) != kNoErr)
                            continue;

                        if (havePrev) {
                            sAIAnnotatorDrawer->DrawLine(drawer, prevView, viewPt);
                        }
                        prevView = viewPt;
                        havePrev = true;
                    }
                } else {
                    AIRealPoint artA, artB;
                    artA.h = (AIReal)x0; artA.v = (AIReal)y0;
                    artB.h = (AIReal)x1; artB.v = (AIReal)y1;

                    AIPoint viewA, viewB;
                    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artA, &viewA) == kNoErr &&
                        sAIDocumentView->ArtworkPointToViewPoint(NULL, &artB, &viewB) == kNoErr) {
                        sAIAnnotatorDrawer->DrawLine(drawer, viewA, viewB);
                    }
                }
            }
        }
    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] DrawOverlay cutout parse error: %s\n", ex.what());
    }
}

//========================================================================================
//  CompositeCutoutMasks — OR selected per-instance mask PNGs into a single composite
//  Returns path to composite mask or empty string if none selected.
//========================================================================================

std::string TraceModule::CompositeCutoutMasks()
{
    int count = BridgeGetCutoutInstanceCount();
    if (count == 0) return "";

    int firstW = 0, firstH = 0;
    unsigned char* composite = nullptr;

    for (int i = 0; i < count; i++) {
        if (!BridgeGetCutoutInstanceSelected(i)) continue;

        std::string maskPath = BridgeGetCutoutInstanceMaskPath(i);
        int w = 0, h = 0, c = 0;
        unsigned char* mask = stbi_load(maskPath.c_str(), &w, &h, &c, 1);
        if (!mask) {
            fprintf(stderr, "[TraceModule] CompositeMasks: failed to load instance %d mask: %s\n",
                    i, maskPath.c_str());
            continue;
        }

        if (!composite) {
            firstW = w;
            firstH = h;
            composite = (unsigned char*)calloc(w * h, 1);
        }

        // OR the mask into composite (only if dimensions match)
        if (w == firstW && h == firstH) {
            for (int p = 0; p < w * h; p++) {
                if (mask[p] > 128) composite[p] = 255;
            }
        } else {
            fprintf(stderr, "[TraceModule] CompositeMasks: instance %d size %dx%d != %dx%d, skipping\n",
                    i, w, h, firstW, firstH);
        }
        stbi_image_free(mask);
    }

    if (!composite) return "";

    std::string compositePath = "/tmp/illtool_cutout_composite.png";
    int wrote = stbi_write_png(compositePath.c_str(), firstW, firstH, 1, composite, firstW);
    free(composite);

    if (!wrote) {
        fprintf(stderr, "[TraceModule] CompositeMasks: stbi_write_png failed\n");
        return "";
    }

    fprintf(stderr, "[TraceModule] CompositeMasks: %dx%d composite written to %s\n",
            firstW, firstH, compositePath.c_str());
    return compositePath;
}

//========================================================================================
//  TraceMaskAndStorePreview — trace a mask PNG with vtracer, parse SVG, store preview paths
//  Shared by PreviewCutout and RecompositeCutout.
//  Uses member vars fArtLeft/Top/Right/Bottom and fSvgWidth/fSvgHeight.
//  Returns number of paths stored, or -1 on failure.
//========================================================================================

int TraceModule::TraceMaskAndStorePreview(const std::string& maskPath)
{
    std::string svgPath = "/tmp/illtool_cutout_output.svg";
    int smoothness = BridgeGetCutoutSmoothness();

    char cmd[4096];
    snprintf(cmd, sizeof(cmd),
        "cd /Users/ryders/Developer/GitHub/ill_tool && "
        ".venv/bin/python -c \""
        "import vtracer; "
        "vtracer.convert_image_to_svg_py("
        "image_path='%s', "
        "out_path='%s', "
        "colormode='bw', "
        "hierarchical='stacked', "
        "mode='spline', "
        "filter_speckle=%d, "
        "color_precision=6, "
        "layer_difference=25, "
        "corner_threshold=30, "
        "length_threshold=20.0, "
        "max_iterations=10, "
        "splice_threshold=45, "
        "path_precision=3"
        ")\" 2>&1",
        maskPath.c_str(), svgPath.c_str(), smoothness);

    fprintf(stderr, "[TraceModule] Cutout vtracer cmd: %s\n", cmd);
    FILE* pipe = popen(cmd, "r");
    if (!pipe) return -1;

    char outputBuf[4096] = {};
    size_t totalRead = 0;
    while (fgets(outputBuf + totalRead, (int)(sizeof(outputBuf) - totalRead), pipe)) {
        totalRead = strlen(outputBuf);
    }
    int exitCode = pclose(pipe);

    if (exitCode != 0) {
        fprintf(stderr, "[TraceModule] Cutout vtracer failed (exit %d): %s\n", exitCode, outputBuf);
        return -1;
    }

    FILE* svgFile = fopen(svgPath.c_str(), "r");
    if (!svgFile) return -1;

    fseek(svgFile, 0, SEEK_END);
    long svgSize = ftell(svgFile);
    fseek(svgFile, 0, SEEK_SET);
    std::string svgContent(svgSize, '\0');
    fread(&svgContent[0], 1, svgSize, svgFile);
    fclose(svgFile);

    fprintf(stderr, "[TraceModule] Cutout SVG: %ld bytes\n", svgSize);

    // Parse SVG viewBox — sets member vars used by TransformSVGPoint
    fSvgWidth = 0;
    fSvgHeight = 0;
    gSvgViewBoxX = 0;
    gSvgViewBoxY = 0;
    {
        std::string viewBoxValue;
        if (ExtractSVGAttribute(svgContent, "viewBox", viewBoxValue)) {
            double vbX = 0, vbY = 0, vbW = 0, vbH = 0;
            if (sscanf(viewBoxValue.c_str(), "%lf %lf %lf %lf", &vbX, &vbY, &vbW, &vbH) >= 4) {
                gSvgViewBoxX = vbX;
                gSvgViewBoxY = vbY;
                fSvgWidth = vbW;
                fSvgHeight = vbH;
            }
        }
        if (fSvgWidth <= 0) {
            std::string wVal, hVal;
            if (ExtractSVGAttribute(svgContent, "width", wVal) &&
                ExtractSVGAttribute(svgContent, "height", hVal)) {
                fSvgWidth = atof(wVal.c_str());
                fSvgHeight = atof(hVal.c_str());
            }
        }
    }

    if (fSvgWidth <= 0 || fSvgHeight <= 0) return -1;

    fprintf(stderr, "[TraceModule] Cutout mapping: SVG %.0fx%.0f -> Art (%.0f,%.0f)-(%.0f,%.0f)\n",
            fSvgWidth, fSvgHeight, fArtLeft, fArtTop, fArtRight, fArtBottom);

    // Parse <path d="..."> elements and store art-coordinate points
    json allPaths = json::array();
    int pathCount = 0;
    bool firstPath = true;
    size_t pos = 0;

    while (true) {
        size_t pathStart = svgContent.find("<path", pos);
        if (pathStart == std::string::npos) break;

        size_t pathEnd = svgContent.find(">", pathStart);
        if (pathEnd == std::string::npos) break;

        std::string pathElement = svgContent.substr(pathStart, pathEnd - pathStart + 1);
        pos = pathEnd;

        std::string pathData;
        if (!ExtractSVGAttribute(pathElement, "d", pathData)) continue;

        // Skip first path (vtracer background rectangle)
        if (firstPath) {
            firstPath = false;
            continue;
        }

        std::string transformValue;
        ExtractSVGAttribute(pathElement, "transform", transformValue);
        double txSvg = 0, tySvg = 0;
        ParseSVGTranslate(transformValue, txSvg, tySvg);

        std::vector<AIPathSegment> segs;
        bool closed = false;
        if (!ParseSVGPathToSegments(pathData, segs, closed) || segs.empty()) continue;

        if (txSvg != 0 || tySvg != 0) {
            ApplyArtTranslation(segs, txSvg, tySvg,
                                fArtLeft, fArtTop, fArtRight, fArtBottom,
                                fSvgWidth, fSvgHeight);
        }

        json pathPoints = json::array();
        for (const auto& seg : segs) {
            json pt;
            pt["x"] = (double)seg.p.h;
            pt["y"] = (double)seg.p.v;
            pt["inX"]  = (double)seg.in.h;
            pt["inY"]  = (double)seg.in.v;
            pt["outX"] = (double)seg.out.h;
            pt["outY"] = (double)seg.out.v;
            pt["corner"] = (bool)seg.corner;
            pathPoints.push_back(pt);
        }

        if (pathPoints.size() >= 3) {
            json pathObj;
            pathObj["points"] = pathPoints;
            pathObj["closed"] = closed;
            allPaths.push_back(pathObj);
            pathCount++;
        }
    }

    BridgeSetCutoutPreviewPaths(allPaths.dump());
    BridgeSetCutoutPreviewActive(true);

    return pathCount;
}

//========================================================================================
//  PreviewCutout — detect per-instance masks, save each as PNG, composite, trace, overlay
//========================================================================================

void TraceModule::PreviewCutout()
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace already in progress, skipping cutout preview\n");
        return;
    }
    fTraceInProgress = true;
    BridgeSetTraceStatus("Detecting instances...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found — use File > Place to add a linked image");
        fTraceInProgress = false;
        return;
    }

    fprintf(stderr, "[TraceModule] Cutout preview for: %s\n", imagePath.c_str());

    // Step 1: Detect per-instance foreground masks via VisionIntelligence
    VIInstanceMask* masks = nullptr;
    int instanceCount = VIDetectInstances(imagePath.c_str(), &masks);

    if (instanceCount <= 0 || !masks) {
        // Fallback: try the legacy merged-mask path
        fprintf(stderr, "[TraceModule] Instance detection returned 0, falling back to merged mask\n");
        BridgeSetTraceStatus("Extracting subject (merged)...");
        BridgeSetCutoutInstanceCount(0);

        const char* maskPath = "/tmp/illtool_cutout_mask.png";
        if (!VisionExtractSubjectMask(imagePath.c_str(), maskPath)) {
            BridgeSetTraceStatus("Subject extraction failed — is there a clear subject?");
            fTraceInProgress = false;
            return;
        }

        BridgeSetTraceStatus("Tracing silhouette...");
        int pathCount = TraceMaskAndStorePreview(maskPath);

        if (pathCount < 0) {
            BridgeSetTraceStatus("Cutout trace failed");
        } else {
            InvalidateFullView();
            BridgeSetTraceStatus("Cutout preview: " + std::to_string(pathCount) +
                                 " path(s) — Commit to create");
            fprintf(stderr, "[TraceModule] Cutout preview ready (merged): %d paths\n", pathCount);
        }
        fTraceInProgress = false;
        return;
    }

    // Cap at 16
    if (instanceCount > 16) instanceCount = 16;

    fprintf(stderr, "[TraceModule] Detected %d foreground instance(s)\n", instanceCount);

    // Step 2: Save each instance mask as a separate PNG, store paths in bridge
    BridgeSetCutoutInstanceCount(instanceCount);
    for (int i = 0; i < instanceCount; i++) {
        BridgeSetCutoutInstanceSelected(i, true);  // select all by default

        if (!masks[i].mask || masks[i].width == 0 || masks[i].height == 0) {
            BridgeSetCutoutInstanceMaskPath(i, "");
            continue;
        }

        char path[256];
        snprintf(path, sizeof(path), "/tmp/illtool_instance_%d.png", i);
        int wrote = stbi_write_png(path, masks[i].width, masks[i].height,
                                   1, masks[i].mask, masks[i].width);
        if (wrote) {
            BridgeSetCutoutInstanceMaskPath(i, path);
            fprintf(stderr, "[TraceModule] Instance %d mask saved: %s (%dx%d)\n",
                    i, path, masks[i].width, masks[i].height);
        } else {
            fprintf(stderr, "[TraceModule] Instance %d mask write failed\n", i);
            BridgeSetCutoutInstanceMaskPath(i, "");
        }
    }

    VIFreeInstanceMasks(masks, instanceCount);

    // Step 3: Composite all selected masks into one
    BridgeSetTraceStatus("Compositing masks...");
    std::string compositePath = CompositeCutoutMasks();
    if (compositePath.empty()) {
        BridgeSetTraceStatus("No valid instance masks to composite");
        fTraceInProgress = false;
        return;
    }

    // Step 4: Trace the composite mask
    BridgeSetTraceStatus("Tracing silhouette...");
    int pathCount = TraceMaskAndStorePreview(compositePath);

    if (pathCount < 0) {
        BridgeSetTraceStatus("Cutout trace failed");
    } else {
        InvalidateFullView();
        BridgeSetTraceStatus(std::to_string(instanceCount) + " instance(s), " +
                             std::to_string(pathCount) + " path(s) — toggle instances or Commit");
        fprintf(stderr, "[TraceModule] Cutout preview ready: %d instances, %d paths\n",
                instanceCount, pathCount);
    }

    // Activate IllTool Handle for click routing (once, at preview start)
    BridgeRequestToolActivation();
    fTraceInProgress = false;
}

//========================================================================================
//  RecompositeCutout — re-composite selected instance masks, re-trace, update overlay
//  Called when user toggles instance checkboxes in the panel.
//========================================================================================

void TraceModule::RecompositeCutout()
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace in progress, skipping recomposite\n");
        return;
    }

    int instanceCount = BridgeGetCutoutInstanceCount();
    if (instanceCount == 0) {
        fprintf(stderr, "[TraceModule] No instances to recomposite\n");
        return;
    }

    fTraceInProgress = true;
    BridgeSetTraceStatus("Recompositing...");

    // Re-read image bounds (FindImagePath populates fArtLeft/Top/Right/Bottom)
    std::string imagePath = FindImagePath();

    std::string compositePath = CompositeCutoutMasks();
    if (compositePath.empty()) {
        BridgeSetTraceStatus("No instances selected");
        BridgeSetCutoutPreviewPaths("");
        BridgeSetCutoutPreviewActive(false);
        InvalidateFullView();
        fTraceInProgress = false;
        return;
    }

    BridgeSetTraceStatus("Tracing silhouette...");
    int pathCount = TraceMaskAndStorePreview(compositePath);

    if (pathCount < 0) {
        BridgeSetTraceStatus("Recomposite trace failed");
    } else {
        InvalidateFullView();
        // Count how many instances are selected
        int selected = 0;
        for (int i = 0; i < instanceCount; i++) {
            if (BridgeGetCutoutInstanceSelected(i)) selected++;
        }
        BridgeSetTraceStatus(std::to_string(selected) + "/" + std::to_string(instanceCount) +
                             " instance(s), " + std::to_string(pathCount) + " path(s)");
        fprintf(stderr, "[TraceModule] Recomposite: %d/%d instances, %d paths\n",
                selected, instanceCount, pathCount);
    }
    fTraceInProgress = false;
}

//========================================================================================
//  CommitCutout — create actual AI paths from stored preview data on "Cut Lines" layer
//========================================================================================

void TraceModule::CommitCutout()
{
    if (fTraceInProgress) {
        fprintf(stderr, "[TraceModule] Trace in progress, skipping cutout commit\n");
        return;
    }

    if (!BridgeGetCutoutPreviewActive()) {
        BridgeSetTraceStatus("No cutout preview to commit — run Preview first");
        return;
    }

    std::string pathsJSON = BridgeGetCutoutPreviewPaths();
    if (pathsJSON.empty()) {
        BridgeSetTraceStatus("No cutout path data to commit");
        return;
    }

    fTraceInProgress = true;
    BridgeSetTraceStatus("Creating cut paths...");

    if (sAIUndo) {
        sAIUndo->SetUndoTextUS(ai::UnicodeString("Undo Subject Cutout"),
                                ai::UnicodeString("Redo Subject Cutout"));
    }

    // Reload image bounds for accurate positioning
    std::string imagePath = FindImagePath();

    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) {
            BridgeSetTraceStatus("Invalid cutout data");
            fTraceInProgress = false;
            return;
        }

        // Find or create the "Cut Lines" layer
        AILayerHandle cutLayer = nullptr;
        ai::UnicodeString cutLayerName("Cut Lines");
        ASErr result = sAILayer->GetLayerByTitle(&cutLayer, cutLayerName);

        if (result != kNoErr || !cutLayer) {
            result = sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &cutLayer);
            if (result != kNoErr || !cutLayer) {
                fprintf(stderr, "[TraceModule] Failed to create Cut Lines layer\n");
                BridgeSetTraceStatus("Failed to create Cut Lines layer");
                fTraceInProgress = false;
                return;
            }
            sAILayer->SetLayerTitle(cutLayer, cutLayerName);
        }

        // Get the layer's art group to insert paths into
        AIArtHandle layerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(cutLayer, &layerArt);

        int created = 0;

        for (const auto& pathObj : previewData) {
            if (!pathObj.contains("points")) continue;
            const auto& points = pathObj["points"];
            if (!points.is_array() || points.size() < 3) continue;
            bool closed = pathObj.value("closed", true);

            // Build path segments from the stored art-coordinate points
            // Restoring full bezier handle data (in/out control points)
            std::vector<AIPathSegment> segs;
            for (const auto& pt : points) {
                if (!pt.contains("x") || !pt.contains("y")) continue;

                AIPathSegment seg;
                memset(&seg, 0, sizeof(seg));
                seg.p.h  = (AIReal)pt["x"].get<double>();
                seg.p.v  = (AIReal)pt["y"].get<double>();
                seg.in.h  = (AIReal)pt.value("inX", (double)seg.p.h);
                seg.in.v  = (AIReal)pt.value("inY", (double)seg.p.v);
                seg.out.h = (AIReal)pt.value("outX", (double)seg.p.h);
                seg.out.v = (AIReal)pt.value("outY", (double)seg.p.v);
                seg.corner = pt.value("corner", true);
                segs.push_back(seg);
            }

            if (segs.size() < 3) continue;

            // Create the path art
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt,
                layerArt ? kPlaceInsideOnTop : kPlaceAboveAll,
                layerArt ? layerArt : nullptr,
                &newPath);

            if (err != kNoErr || !newPath) continue;

            ai::int16 nc = (ai::int16)segs.size();
            sAIPath->SetPathSegmentCount(newPath, nc);
            sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
            sAIPath->SetPathClosed(newPath, closed);

            // Style: 1pt black stroke, no fill — clean cut line
            AIPathStyle style;
            memset(&style, 0, sizeof(style));
            style.fillPaint   = false;
            style.strokePaint = true;
            style.stroke.width = (AIReal)1.0;
            style.stroke.color.kind = kThreeColor;
            style.stroke.color.c.rgb.red   = (AIReal)0.0;
            style.stroke.color.c.rgb.green = (AIReal)0.0;
            style.stroke.color.c.rgb.blue  = (AIReal)0.0;
            style.stroke.miterLimit = (AIReal)4.0;

            sAIPathStyle->SetPathStyle(newPath, &style);
            sAIArt->SetArtName(newPath, ai::UnicodeString("Subject Cutout"));
            created++;
        }

        // Clear the preview overlay and instance state
        BridgeSetCutoutPreviewActive(false);
        BridgeSetCutoutPreviewPaths("");
        BridgeSetCutoutInstanceCount(0);
        InvalidateFullView();

        BridgeSetTraceStatus("Cutout committed: " + std::to_string(created) + " path(s) on Cut Lines");
        fprintf(stderr, "[TraceModule] Cutout committed: %d paths on Cut Lines layer\n", created);

        sAIDocument->RedrawDocument();

    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] CommitCutout error: %s\n", ex.what());
        BridgeSetTraceStatus(std::string("Cutout commit failed: ") + ex.what());
    }

    fTraceInProgress = false;
}

//========================================================================================
//  OnDocumentChanged
//========================================================================================

void TraceModule::OnSelectionChanged()
{
    // Update status when user selects a raster or placed image.
    // Do NOT auto-execute trace — it loops (trace → selection change → trace → beachball).
    if (fTraceInProgress) return;

    try {
        AIArtHandle** matches = nullptr;
        ai::int32 numMatches = 0;

        AIMatchingArtSpec spec;
        spec.type = kPlacedArt;
        spec.whichAttr = kArtSelected;
        spec.attr = kArtSelected;
        ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err == kNoErr && numMatches > 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            BridgeSetTraceStatus("Image selected — click Run Selected");
            return;
        }
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

        spec.type = kRasterArt;
        matches = nullptr; numMatches = 0;
        err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
        if (err == kNoErr && numMatches > 0) {
            if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
            BridgeSetTraceStatus("Image selected — click Run Selected");
            return;
        }
        if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);
    }
    catch (...) {}
}

void TraceModule::OnDocumentChanged()
{
    fTraceInProgress = false;
    fStatusMessage.clear();
    BridgeSetTraceStatus("");

    // Clear cutout preview on document change
    BridgeSetCutoutPreviewActive(false);
    BridgeSetCutoutPreviewPaths("");

    // Clear pose preview on document change
    fPosePreviewActive = false;
    fPoseJoints.clear();
    fFacePoints.clear();
    fHandJoints.clear();
    BridgeSetPosePreviewActive(false);
    BridgeSetPosePreviewJSON("");
}

//========================================================================================
//  ReadSurfaceIdentity — read per-path surface metadata from AIDictionary
//========================================================================================

SurfaceIdentity ReadSurfaceIdentity(AIArtHandle art)
{
    SurfaceIdentity result;
    if (!art) return result;

    AIDictionaryRef dict = nullptr;
    if (sAIArt->GetDictionary(art, &dict) != kNoErr || !dict) return result;

    static AIDictKey surfIdKey  = sAIDictionary->Key("IllToolSurfaceId");
    static AIDictKey normalXKey = sAIDictionary->Key("IllToolNormalX");
    static AIDictKey normalYKey = sAIDictionary->Key("IllToolNormalY");
    static AIDictKey normalZKey = sAIDictionary->Key("IllToolNormalZ");

    ai::int32 surfId = -1;
    AIReal nx = 0, ny = 0, nz = 0;

    ASErr err = sAIDictionary->GetIntegerEntry(dict, surfIdKey, &surfId);
    if (err == kNoErr) {
        result.surfaceId = (int)surfId;
        sAIDictionary->GetRealEntry(dict, normalXKey, &nx);
        sAIDictionary->GetRealEntry(dict, normalYKey, &ny);
        sAIDictionary->GetRealEntry(dict, normalZKey, &nz);
        result.nx = (double)nx;
        result.ny = (double)ny;
        result.nz = (double)nz;
        result.valid = true;
    }

    sAIDictionary->Release(dict);
    return result;
}

//========================================================================================
//  ExecuteAppleContours — Apple Vision contour detection via VisionIntelligence
//
//  Uses VNDetectContoursRequest through the VI abstraction layer.
//  Converts normalized (0-1) contour points to artboard coordinates and creates AI paths.
//========================================================================================

void TraceModule::ExecuteAppleContours()
{
    if (fTraceInProgress) return;
    fTraceInProgress = true;
    BridgeSetTraceStatus("Running Apple Contours...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found");
        fTraceInProgress = false;
        return;
    }

    // Read params from bridge
    float contrast   = (float)BridgeGetTraceContourContrast();
    float pivot      = (float)BridgeGetTraceContourPivot();
    bool  darkOnLight = BridgeGetTraceContourDarkOnLight();

    fprintf(stderr, "[TraceModule] Apple Contours: contrast=%.2f pivot=%.2f darkOnLight=%s\n",
            contrast, pivot, darkOnLight ? "true" : "false");

    // If a cutout mask is active, apply it to the image first (masked contour tracing)
    std::string traceImagePath = imagePath;
    std::string maskedPath = ApplyActiveMaskToImage(imagePath);
    if (!maskedPath.empty()) {
        traceImagePath = maskedPath;
        fprintf(stderr, "[TraceModule] Masked contour tracing: using masked image\n");
    }

    VIContour* contours = nullptr;
    int count = VIDetectContours(traceImagePath.c_str(), contrast, pivot, darkOnLight, &contours);

    if (count <= 0 || !contours) {
        BridgeSetTraceStatus("No contours detected");
        fTraceInProgress = false;
        return;
    }

    fprintf(stderr, "[TraceModule] Apple Contours: %d contours detected\n", count);
    BridgeSetTraceStatus("Creating paths...");

    // Convert normalized contour points to artboard coordinates and create AI paths
    int created = 0;
    for (int i = 0; i < count; i++) {
        VIContour& c = contours[i];
        if (c.pointCount < 3) continue;  // skip degenerate contours

        // Build segments
        std::vector<AIPathSegment> segs;
        for (int j = 0; j < c.pointCount; j++) {
            double nx = c.points[j * 2];
            double ny = c.points[j * 2 + 1];

            // Convert normalized (0-1) to artboard coordinates
            // Vision uses bottom-left origin, AI uses top-left (Y up)
            double artX = fArtLeft + nx * (fArtRight - fArtLeft);
            double artY = fArtBottom + ny * (fArtTop - fArtBottom);  // Vision Y matches AI Y direction (both bottom-up in normalized space)

            AIPathSegment seg;
            memset(&seg, 0, sizeof(seg));
            seg.p.h = (AIReal)artX;
            seg.p.v = (AIReal)artY;
            seg.in  = seg.p;   // straight segments (no bezier handles)
            seg.out = seg.p;
            seg.corner = true;
            segs.push_back(seg);
        }

        if (segs.empty()) continue;

        // Create AI path
        AIArtHandle newPath = nullptr;
        ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
        if (err != kNoErr || !newPath) continue;

        sAIPath->SetPathSegmentCount(newPath, (ai::int16)segs.size());
        sAIPath->SetPathSegments(newPath, 0, (ai::int16)segs.size(), segs.data());
        sAIPath->SetPathClosed(newPath, c.closed);

        // Style: 1pt black stroke, no fill
        AIPathStyle style;
        memset(&style, 0, sizeof(style));
        style.fillPaint = false;
        style.strokePaint = true;
        style.stroke.width = 1.0;
        style.stroke.color.kind = kThreeColor;
        style.stroke.color.c.rgb.red   = 0.0f;
        style.stroke.color.c.rgb.green = 0.0f;
        style.stroke.color.c.rgb.blue  = 0.0f;
        style.stroke.miterLimit = 4.0;
        sAIPathStyle->SetPathStyle(newPath, &style);

        created++;
    }

    VIFreeContours(contours, count);

    std::string statusMsg = "Apple Contours: " + std::to_string(created) + " paths";
    BridgeSetTraceStatus(statusMsg);
    fTraceInProgress = false;

    // Force annotator redraw
    if (sAIAnnotator && gPlugin) {
        sAIAnnotator->InvalAnnotationRect(NULL, NULL);
    }

    fprintf(stderr, "[TraceModule] Apple Contours complete: %d paths created\n", created);
}

//========================================================================================
//  ExecuteDetectPose — run Vision body/face/hand pose detection, store results for overlay
//========================================================================================

void TraceModule::ExecuteDetectPose()
{
    BridgeSetTraceStatus("Detecting pose...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found — place a raster image first");
        fprintf(stderr, "[TraceModule] DetectPose: no image found\n");
        return;
    }

    fprintf(stderr, "[TraceModule] DetectPose: processing %s\n", imagePath.c_str());

    // Body pose detection
    VIJoint* joints = nullptr;
    int jointCount = VIDetectBodyPose(imagePath.c_str(), &joints);

    fPoseJoints.clear();
    for (int i = 0; i < jointCount; i++) {
        PoseJoint pj;
        pj.name = joints[i].jointName ? joints[i].jointName : "";
        pj.x = joints[i].x;
        pj.y = joints[i].y;
        pj.confidence = joints[i].confidence;
        fPoseJoints.push_back(pj);
    }
    VIFreeJoints(joints, jointCount);

    // Face landmarks (optional, controlled by bridge flag)
    fFacePoints.clear();
    int faceCount = 0;
    if (BridgeGetPoseIncludeFace()) {
        VIFacePoint* facePoints = nullptr;
        faceCount = VIDetectFaceLandmarks(imagePath.c_str(), &facePoints);

        for (int i = 0; i < faceCount; i++) {
            fFacePoints.push_back({facePoints[i].x, facePoints[i].y});
        }
        VIFreeFacePoints(facePoints, faceCount);
    }

    // Hand pose (optional, controlled by bridge flag)
    fHandJoints.clear();
    int handCount = 0;
    if (BridgeGetPoseIncludeHands()) {
        VIJoint* handJoints = nullptr;
        handCount = VIDetectHandPose(imagePath.c_str(), &handJoints);

        for (int i = 0; i < handCount; i++) {
            PoseJoint pj;
            pj.name = handJoints[i].jointName ? handJoints[i].jointName : "";
            pj.x = handJoints[i].x;
            pj.y = handJoints[i].y;
            pj.confidence = handJoints[i].confidence;
            fHandJoints.push_back(pj);
        }
        VIFreeJoints(handJoints, handCount);
    }

    // Build JSON for bridge (enables cross-module access if needed)
    json poseJSON;
    poseJSON["bodyJoints"] = json::array();
    for (auto& j : fPoseJoints) {
        poseJSON["bodyJoints"].push_back({
            {"name", j.name}, {"x", j.x}, {"y", j.y}, {"confidence", j.confidence}
        });
    }
    poseJSON["facePoints"] = json::array();
    for (auto& fp : fFacePoints) {
        poseJSON["facePoints"].push_back({{"x", fp.first}, {"y", fp.second}});
    }
    poseJSON["handJoints"] = json::array();
    for (auto& hj : fHandJoints) {
        poseJSON["handJoints"].push_back({
            {"name", hj.name}, {"x", hj.x}, {"y", hj.y}, {"confidence", hj.confidence}
        });
    }
    BridgeSetPosePreviewJSON(poseJSON.dump());

    fPosePreviewActive = true;
    BridgeSetPosePreviewActive(true);
    InvalidateFullView();

    std::string status = "Pose: " + std::to_string(jointCount) + " body joints";
    if (faceCount > 0) status += ", " + std::to_string(faceCount) + " face pts";
    if (handCount > 0) status += ", " + std::to_string(handCount) + " hand joints";
    BridgeSetTraceStatus(status);

    fprintf(stderr, "[TraceModule] DetectPose complete: %s\n", status.c_str());
}

//========================================================================================
//  DrawPoseOverlay — render skeleton lines + joint dots + face points as annotator overlay
//
//  Coordinate transform: Vision normalized (0-1, bottom-left origin) → artboard coords.
//  Vision X maps to fArtLeft..fArtRight, Vision Y (0=bottom) maps to fArtBottom..fArtTop.
//========================================================================================

void TraceModule::DrawPoseOverlay(AIAnnotatorMessage* message)
{
    if (!fPosePreviewActive || !BridgeGetPosePreviewActive()) return;
    if (!message || !message->drawer || !sAIDocumentView) return;
    if (fPoseJoints.empty() && fFacePoints.empty() && fHandJoints.empty()) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    // Need art bounds for coordinate mapping — use cached values from FindImagePath
    double artW = fArtRight - fArtLeft;
    double artH = fArtTop - fArtBottom;  // AI coords: top > bottom

    if (artW < 1.0 || artH < 1.0) {
        // Art bounds not populated — try to populate them
        FindImagePath();
        artW = fArtRight - fArtLeft;
        artH = fArtTop - fArtBottom;
        if (artW < 1.0 || artH < 1.0) return;  // still no image
    }

    // Lambda: convert Vision normalized coords to AI art coords, then to view
    auto toViewPoint = [&](float normX, float normY, AIPoint& viewPt) -> bool {
        // Vision: (0,0) = bottom-left, (1,1) = top-right
        // AI art coords: X = left..right, Y = top..bottom (top is larger)
        double artX = fArtLeft + normX * artW;
        double artY = fArtBottom + normY * artH;  // normY 0=bottom → fArtBottom, 1=top → fArtTop

        AIRealPoint artPt;
        artPt.h = (AIReal)artX;
        artPt.v = (AIReal)artY;
        return sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &viewPt) == kNoErr;
    };

    // --- Draw body skeleton ---
    if (!fPoseJoints.empty()) {
        // Cyan for skeleton lines
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_SKELETON());
        sAIAnnotatorDrawer->SetLineWidth(drawer, ITK_WIDTH_SKELETON);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.9);

        // Define skeleton bone connections (pairs of joint names)
        static const char* bones[][2] = {
            {"nose", "neck"},
            {"neck", "left_shoulder"}, {"neck", "right_shoulder"},
            {"left_shoulder", "left_elbow"}, {"left_elbow", "left_wrist"},
            {"right_shoulder", "right_elbow"}, {"right_elbow", "right_wrist"},
            {"neck", "root"},
            {"root", "left_hip"}, {"root", "right_hip"},
            {"left_hip", "left_knee"}, {"left_knee", "left_ankle"},
            {"right_hip", "right_knee"}, {"right_knee", "right_ankle"},
            {"nose", "left_eye"}, {"nose", "right_eye"},
            {"left_eye", "left_ear"}, {"right_eye", "right_ear"},
        };
        static const int boneCount = sizeof(bones) / sizeof(bones[0]);

        // Helper: find joint by name
        auto findJoint = [&](const char* name) -> PoseJoint* {
            for (auto& j : fPoseJoints) {
                if (j.name == name) return &j;
            }
            return nullptr;
        };

        // Draw each bone as a line
        for (int b = 0; b < boneCount; b++) {
            PoseJoint* j0 = findJoint(bones[b][0]);
            PoseJoint* j1 = findJoint(bones[b][1]);
            if (!j0 || !j1) continue;

            AIPoint v0, v1;
            if (toViewPoint(j0->x, j0->y, v0) && toViewPoint(j1->x, j1->y, v1)) {
                sAIAnnotatorDrawer->DrawLine(drawer, v0, v1);
            }
        }

        // Draw joint dots (small circles as cross-hairs)
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_JOINT());
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.5);

        for (auto& j : fPoseJoints) {
            AIPoint vp;
            if (!toViewPoint(j.x, j.y, vp)) continue;

            // Draw a small cross at each joint position
            int dotSize = (int)ITK_SIZE_JOINT_MARKER;
            AIPoint left  = {vp.h - dotSize, vp.v};
            AIPoint right = {vp.h + dotSize, vp.v};
            AIPoint top   = {vp.h, vp.v - dotSize};
            AIPoint bot   = {vp.h, vp.v + dotSize};

            sAIAnnotatorDrawer->DrawLine(drawer, left, right);
            sAIAnnotatorDrawer->DrawLine(drawer, top, bot);
        }
    }

    // --- Draw face landmark points ---
    if (!fFacePoints.empty()) {
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_FACE());
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.0);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.7);

        for (auto& fp : fFacePoints) {
            AIPoint vp;
            if (!toViewPoint(fp.first, fp.second, vp)) continue;

            // Draw a tiny dot
            int dotSize = (int)ITK_SIZE_FACE_DOT;
            AIPoint left  = {vp.h - dotSize, vp.v};
            AIPoint right = {vp.h + dotSize, vp.v};
            AIPoint top   = {vp.h, vp.v - dotSize};
            AIPoint bot   = {vp.h, vp.v + dotSize};

            sAIAnnotatorDrawer->DrawLine(drawer, left, right);
            sAIAnnotatorDrawer->DrawLine(drawer, top, bot);
        }
    }

    // --- Draw hand joint points ---
    if (!fHandJoints.empty()) {
        sAIAnnotatorDrawer->SetColor(drawer, ITK_COLOR_HAND());
        sAIAnnotatorDrawer->SetLineWidth(drawer, 1.5);
        sAIAnnotatorDrawer->SetOpacity(drawer, 0.85);

        for (auto& hj : fHandJoints) {
            AIPoint vp;
            if (!toViewPoint(hj.x, hj.y, vp)) continue;

            // Draw a small X at each hand joint
            int dotSize = 3;
            AIPoint tl = {vp.h - dotSize, vp.v - dotSize};
            AIPoint br = {vp.h + dotSize, vp.v + dotSize};
            AIPoint tr = {vp.h + dotSize, vp.v - dotSize};
            AIPoint bl = {vp.h - dotSize, vp.v + dotSize};

            sAIAnnotatorDrawer->DrawLine(drawer, tl, br);
            sAIAnnotatorDrawer->DrawLine(drawer, tr, bl);
        }
    }
}

//========================================================================================
//  ApplyActiveMaskToImage — if a cutout composite mask exists, mask the image
//  Returns path to masked image, or empty string if no mask is active.
//========================================================================================

std::string TraceModule::ApplyActiveMaskToImage(const std::string& imagePath)
{
    // Check if cutout preview is active with a composite mask
    if (!BridgeGetCutoutPreviewActive()) return "";

    std::string compositePath = "/tmp/illtool_cutout_composite.png";
    FILE* f = fopen(compositePath.c_str(), "r");
    if (!f) return "";
    fclose(f);

    // Load original image (RGB)
    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* img = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 3);
    if (!img) return "";

    // Load mask (grayscale)
    int mskW = 0, mskH = 0, mskC = 0;
    unsigned char* mask = stbi_load(compositePath.c_str(), &mskW, &mskH, &mskC, 1);
    if (!mask) { stbi_image_free(img); return ""; }

    // Dimensions must match (or close enough — use min)
    int w = std::min(imgW, mskW);
    int h = std::min(imgH, mskH);

    // Apply mask: zero out pixels outside the mask
    unsigned char* masked = (unsigned char*)calloc(w * h * 3, 1);
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int mIdx = y * mskW + x;
            int iIdx = (y * imgW + x) * 3;
            int oIdx = (y * w + x) * 3;
            if (mask[mIdx] > 128) {
                masked[oIdx]     = img[iIdx];
                masked[oIdx + 1] = img[iIdx + 1];
                masked[oIdx + 2] = img[iIdx + 2];
            }
            // else: stays black (calloc zeroed)
        }
    }

    stbi_image_free(img);
    stbi_image_free(mask);

    std::string maskedPath = "/tmp/illtool_masked_contour_input.png";
    stbi_write_png(maskedPath.c_str(), w, h, 3, masked, w * 3);
    free(masked);

    fprintf(stderr, "[TraceModule] Masked contour input: %dx%d saved to %s\n", w, h, maskedPath.c_str());
    return maskedPath;
}

//========================================================================================
//  ExecuteDepthDecompose — AI depth-based layer decomposition
//
//  Uses Depth Anything V2 (ONNX) to estimate per-pixel depth, then quantizes
//  the depth map into N bands (foreground → background). For each band,
//  masks the original image and runs contour detection to extract paths.
//  Creates one Illustrator layer per depth band with color-coded strokes.
//========================================================================================

void TraceModule::ExecuteDepthDecompose()
{
    if (fTraceInProgress) return;
    fTraceInProgress = true;
    BridgeSetTraceStatus("Analyzing depth...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found");
        fTraceInProgress = false;
        return;
    }

    // Run depth estimation via ONNX backend
    float* depthMap = nullptr;
    int depthW = 0, depthH = 0;
    if (!VIEstimateDepth(imagePath.c_str(), &depthMap, &depthW, &depthH)) {
        BridgeSetTraceStatus("Depth estimation failed");
        fTraceInProgress = false;
        return;
    }

    int numLayers = BridgeGetDepthLayerCount();
    if (numLayers < 2) numLayers = 2;
    if (numLayers > 8) numLayers = 8;

    fprintf(stderr, "[TraceModule] Depth decompose: %dx%d map, %d layers\n", depthW, depthH, numLayers);

    // Layer name table
    static const char* layerNames[] = {"FG", "MG-1", "MG-2", "MG-3", "MG-4", "MG-5", "MG-6", "BG"};

    // Load original image for masking
    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* origImg = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 3);
    if (!origImg) {
        fprintf(stderr, "[TraceModule] Depth decompose: failed to load original image\n");
        VIFreeDepthMap(depthMap);
        BridgeSetTraceStatus("Failed to load image");
        fTraceInProgress = false;
        return;
    }

    int totalContours = 0;

    for (int band = 0; band < numLayers; band++) {
        float lo = (float)band / numLayers;
        float hi = (float)(band + 1) / numLayers;

        // Pick layer name: first = FG, last = BG, middle = MG-N
        const char* name = (band == 0) ? "FG" :
                          (band == numLayers - 1) ? "BG" :
                          layerNames[std::min(band, 7)];

        char statusBuf[128];
        snprintf(statusBuf, sizeof(statusBuf), "Tracing depth layer %d/%d: %s", band+1, numLayers, name);
        BridgeSetTraceStatus(statusBuf);

        // Create binary mask for this depth band
        // Map each image pixel to the depth map and check if it falls in [lo, hi)
        std::vector<unsigned char> mask(imgW * imgH, 0);
        for (int y = 0; y < imgH; y++) {
            for (int x = 0; x < imgW; x++) {
                int dx = (int)((float)x / imgW * depthW);
                int dy = (int)((float)y / imgH * depthH);
                if (dx >= depthW) dx = depthW - 1;
                if (dy >= depthH) dy = depthH - 1;

                float d = depthMap[dy * depthW + dx];
                // Last band includes upper boundary (>=lo && <=1.0)
                if (band == numLayers - 1) {
                    if (d >= lo) mask[y * imgW + x] = 255;
                } else {
                    if (d >= lo && d < hi) mask[y * imgW + x] = 255;
                }
            }
        }

        // Apply mask to original image — zero out pixels outside the band
        std::vector<unsigned char> masked(imgW * imgH * 3, 0);
        for (int i = 0; i < imgW * imgH; i++) {
            if (mask[i] > 0) {
                masked[i * 3]     = origImg[i * 3];
                masked[i * 3 + 1] = origImg[i * 3 + 1];
                masked[i * 3 + 2] = origImg[i * 3 + 2];
            }
        }

        // Save masked image for contour detection
        char maskedPath[256];
        snprintf(maskedPath, sizeof(maskedPath), "/tmp/illtool_depth_band_%d.png", band);
        stbi_write_png(maskedPath, imgW, imgH, 3, masked.data(), imgW * 3);

        // Run contour detection on the masked image
        VIContour* contours = nullptr;
        float contrast = (float)BridgeGetTraceContourContrast();
        float pivot = (float)BridgeGetTraceContourPivot();
        bool darkOnLight = BridgeGetTraceContourDarkOnLight();
        int contourCount = VIDetectContours(maskedPath, contrast, pivot, darkOnLight, &contours);

        if (contourCount > 0 && contours) {
            // Create or find the layer for this depth band
            AILayerHandle layer = nullptr;
            ai::UnicodeString uName(name);
            sAILayer->GetLayerByTitle(&layer, uName);
            if (!layer) {
                sAILayer->InsertLayer(nullptr, kPlaceAboveAll, &layer);
                if (layer) sAILayer->SetLayerTitle(layer, uName);
            }

            // Get the first art of the layer as insertion parent
            AIArtHandle layerArt = nullptr;
            if (layer) sAIArt->GetFirstArtOfLayer(layer, &layerArt);

            // Create paths from contours
            for (int i = 0; i < contourCount; i++) {
                VIContour& c = contours[i];
                if (c.pointCount < 3) continue;

                std::vector<AIPathSegment> segs;
                for (int j = 0; j < c.pointCount; j++) {
                    double nx = c.points[j * 2];
                    double ny = c.points[j * 2 + 1];
                    // Map normalized coords (0-1) to artboard coords
                    double artX = fArtLeft + nx * (fArtRight - fArtLeft);
                    // Vision framework uses bottom-left origin (Y up), AI uses Y-down for artBounds
                    // artTop > artBottom in AI coords
                    double artY = fArtBottom + ny * (fArtTop - fArtBottom);

                    AIPathSegment seg;
                    memset(&seg, 0, sizeof(seg));
                    seg.p.h = (AIReal)artX;
                    seg.p.v = (AIReal)artY;
                    seg.in = seg.p;
                    seg.out = seg.p;
                    seg.corner = true;
                    segs.push_back(seg);
                }

                AIArtHandle newPath = nullptr;
                if (layerArt) {
                    sAIArt->NewArt(kPathArt, kPlaceInsideOnTop, layerArt, &newPath);
                } else {
                    sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
                }

                if (newPath) {
                    sAIPath->SetPathSegmentCount(newPath, (ai::int16)segs.size());
                    sAIPath->SetPathSegments(newPath, 0, (ai::int16)segs.size(), segs.data());
                    sAIPath->SetPathClosed(newPath, c.closed);

                    // Color-code strokes by depth band: FG=red → mid=yellow/green → BG=blue
                    AIPathStyle style;
                    memset(&style, 0, sizeof(style));
                    style.fillPaint = false;
                    style.strokePaint = true;
                    style.stroke.width = 1.0;
                    style.stroke.color.kind = kThreeColor;
                    float t = (numLayers > 1) ? (float)band / (numLayers - 1) : 0.0f;
                    style.stroke.color.c.rgb.red   = 1.0f - t;
                    style.stroke.color.c.rgb.green = (t < 0.5f) ? t * 2 : (1.0f - t) * 2;
                    style.stroke.color.c.rgb.blue  = t;
                    style.stroke.miterLimit = 4.0;
                    sAIPathStyle->SetPathStyle(newPath, &style);
                }
            }

            totalContours += contourCount;
            VIFreeContours(contours, contourCount);
            fprintf(stderr, "[TraceModule] Depth band %d (%s): %d contours\n", band, name, contourCount);
        }
    }

    stbi_image_free(origImg);
    VIFreeDepthMap(depthMap);

    fTraceInProgress = false;

    InvalidateFullView();

    char doneBuf[128];
    snprintf(doneBuf, sizeof(doneBuf), "Depth decomposition: %d layers, %d contours", numLayers, totalContours);
    BridgeSetTraceStatus(doneBuf);
    fprintf(stderr, "[TraceModule] %s\n", doneBuf);
}

//========================================================================================
//  HandleCutoutClick — Shift+click=add, Option+click=subtract from cutout mask
//
//  Uses flood-fill at click point with configurable threshold.
//  Shift: flood-fill region is ADDED to the composite mask (OR)
//  Option: flood-fill region is SUBTRACTED from the composite mask (AND NOT)
//  Threshold controls color tolerance for the flood fill.
//========================================================================================

bool TraceModule::HandleCutoutClick(AIRealPoint artPt, bool shiftHeld, bool optionHeld)
{
    if (!BridgeGetCutoutPreviewActive()) return false;
    if (!shiftHeld && !optionHeld) return false;  // require modifier key

    // Convert artboard coords to normalized image coords (0-1)
    double artW = fArtRight - fArtLeft;
    double artH = fArtTop - fArtBottom;
    if (artW < 1 || artH < 1) return false;

    double normX = (artPt.h - fArtLeft) / artW;
    double normY = (fArtTop - artPt.v) / artH;

    if (normX < 0 || normX > 1 || normY < 0 || normY > 1) return false;

    const char* mode = shiftHeld ? "ADD" : "SUBTRACT";
    fprintf(stderr, "[TraceModule] Cutout %s click at norm(%.3f, %.3f)\n", mode, normX, normY);

    // Load original image as RGB for color-aware flood fill
    std::string imagePath = FindImagePath();
    if (imagePath.empty()) return false;

    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* img = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 3);  // force RGB
    if (!img) return false;

    int seedX = (int)(normX * imgW);
    int seedY = (int)(normY * imgH);
    if (seedX < 0 || seedX >= imgW || seedY < 0 || seedY >= imgH) {
        stbi_image_free(img);
        return false;
    }

    // Flood fill using RGB color distance (Euclidean in color space)
    int tolerance = BridgeGetCutoutClickThreshold();
    int tolSq = tolerance * tolerance;  // squared threshold for color distance
    int seedIdx = (seedY * imgW + seedX) * 3;
    int seedR = img[seedIdx], seedG = img[seedIdx + 1], seedB = img[seedIdx + 2];

    // Cap fill to prevent runaway — max 25% of image
    int maxFill = imgW * imgH / 4;

    std::vector<unsigned char> fillMask(imgW * imgH, 0);
    std::vector<bool> visited(imgW * imgH, false);
    std::vector<std::pair<int,int>> fillStack;
    fillStack.push_back({seedX, seedY});
    visited[seedY * imgW + seedX] = true;
    int filledPixels = 0;

    while (!fillStack.empty() && filledPixels < maxFill) {
        auto [cx, cy] = fillStack.back();
        fillStack.pop_back();

        int pIdx = (cy * imgW + cx) * 3;
        int dr = (int)img[pIdx] - seedR;
        int dg = (int)img[pIdx + 1] - seedG;
        int db = (int)img[pIdx + 2] - seedB;
        int distSq = dr * dr + dg * dg + db * db;
        if (distSq > tolSq) continue;

        fillMask[cy * imgW + cx] = 255;
        filledPixels++;

        // 4-connected neighbors
        const int dxOff[] = {-1, 1, 0, 0};
        const int dyOff[] = {0, 0, -1, 1};
        for (int d = 0; d < 4; d++) {
            int nx2 = cx + dxOff[d];
            int ny2 = cy + dyOff[d];
            if (nx2 >= 0 && nx2 < imgW && ny2 >= 0 && ny2 < imgH) {
                int nIdx = ny2 * imgW + nx2;
                if (!visited[nIdx]) {
                    visited[nIdx] = true;
                    fillStack.push_back({nx2, ny2});
                }
            }
        }
    }

    stbi_image_free(img);

    fprintf(stderr, "[TraceModule] Flood fill: %d pixels (max %d), threshold=%d, mode=%s, seed=(%d,%d) rgb=(%d,%d,%d)\n",
            filledPixels, maxFill, tolerance, mode, seedX, seedY, seedR, seedG, seedB);

    if (filledPixels == 0) return true;  // consumed click but nothing to add

    // Load existing composite mask (or create blank)
    std::string compositePath = "/tmp/illtool_cutout_composite.png";
    int cW = 0, cH = 0, cC = 0;
    unsigned char* composite = stbi_load(compositePath.c_str(), &cW, &cH, &cC, 1);

    bool createdNew = false;
    if (!composite || cW != imgW || cH != imgH) {
        if (composite) stbi_image_free(composite);
        composite = (unsigned char*)calloc(imgW * imgH, 1);
        cW = imgW;
        cH = imgH;
        createdNew = true;

        // If not created new, start from the existing composite
        if (!createdNew) {
            // Already loaded above
        }
    }

    // Apply: Shift=OR (add), Option=AND NOT (subtract)
    for (int i = 0; i < imgW * imgH; i++) {
        if (fillMask[i] > 0) {
            if (shiftHeld) {
                composite[i] = 255;  // add
            } else {
                composite[i] = 0;    // subtract
            }
        }
    }

    // Count total white pixels in composite before and after
    int whiteCount = 0;
    for (int i = 0; i < imgW * imgH; i++) {
        if (composite[i] > 128) whiteCount++;
    }

    // Write updated composite
    stbi_write_png(compositePath.c_str(), imgW, imgH, 1, composite, imgW);
    if (createdNew) free(composite);
    else stbi_image_free(composite);

    fprintf(stderr, "[TraceModule] Composite mask: %d white pixels (%.1f%% of %dx%d)\n",
            whiteCount, 100.0 * whiteCount / (imgW * imgH), imgW, imgH);

    // Re-trace with lower speckle to preserve small additions
    // Temporarily override smoothness for this trace
    int origSmoothness = BridgeGetCutoutSmoothness();
    BridgeSetCutoutSmoothness(std::min(origSmoothness, 10));  // cap at 10 for click edits
    TraceMaskAndStorePreview(compositePath);
    BridgeSetCutoutSmoothness(origSmoothness);  // restore

    InvalidateFullView();

    fprintf(stderr, "[TraceModule] Cutout %s complete, re-traced (speckle capped at 10)\n", mode);
    return true;
}
