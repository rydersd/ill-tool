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
#include "VisionEngine.h"
#include "vendor/httplib.h"
#include "vendor/json.hpp"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

// stb_image for reading PNG pixels (STB_IMAGE_IMPLEMENTATION defined in VisionEngine.cpp)
#include "vendor/stb_image.h"

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
            // Dispatch based on backend name in strParam
            std::string backend = op.strParam;
            if (backend == "normal_ref" || backend == "form_edge") {
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
                    AIArtHandle rasterArt = (*matches)[0];
                    fprintf(stderr, "[TraceModule] Found raster art (pass %d, count %d)\n",
                            pass, (int)numMatches);

                    AIRealRect rBounds = {0,0,0,0};
                    sAIArt->GetArtBounds(rasterArt, &rBounds);
                    fArtLeft = rBounds.left; fArtTop = rBounds.top;
                    fArtRight = rBounds.right; fArtBottom = rBounds.bottom;

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
    int outputMode = BridgeGetTraceOutputMode();  // 0=outline, 1=fill
    const char* colormode = (outputMode == 0) ? "bw" : "color";

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
        "layer_difference=25, "
        "corner_threshold=60, "
        "length_threshold=4.0, "
        "max_iterations=10, "
        "splice_threshold=45, "
        "path_precision=3"
        ")\" 2>&1",
        imagePath.c_str(), svgPath.c_str(), colormode, speckle, colorPrec);

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
        if (ParseSVGPathToSegments(pathData, segs, closed) && !segs.empty()) {
            ApplyArtTranslation(segs, translateX, translateY,
                                fArtLeft, fArtTop, fArtRight, fArtBottom,
                                fSvgWidth, fSvgHeight);

            // Create path flat (no parent group — placed at top of art tree)
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt, kPlaceAboveAll, nullptr, &newPath);
            if (err == kNoErr && newPath) {
                ai::int16 nc = (ai::int16)segs.size();
                sAIPath->SetPathSegmentCount(newPath, nc);
                sAIPath->SetPathSegments(newPath, 0, nc, segs.data());
                sAIPath->SetPathClosed(newPath, closed);

                AIPathStyle style;
                memset(&style, 0, sizeof(style));
                style.stroke.miterLimit = (AIReal)4.0;

                int traceOutputMode = BridgeGetTraceOutputMode();  // 0=outline, 1=fill
                if (traceOutputMode == 0) {
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
        GroupPathsBySurface(normalMapPath, 5, allPaths, allFillR, allFillG, allFillB, allHasFill);
        BridgeSetTraceStatus("Traced: " + std::to_string(created) + " paths in surface groups");
    } else {
        // Fallback: luminance-based grouping (original behavior)
        fprintf(stderr, "[TraceModule] No normal map — falling back to luminance grouping\n");

        const char* groupNames[] = {"Trace — Background", "Trace — Highlights",
                                     "Trace — Midtones", "Trace — Shadows", "Trace — Outlines"};
        AIArtHandle groups[5] = {};
        for (int g = 0; g < 5; g++) {
            ASErr gErr = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &groups[g]);
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

    unsigned char* normals = VisionEngine::GenerateNormalFromHeight(gray, grayW, grayH, 2.0);
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
    auto regions = VisionEngine::Instance().ClusterNormalMapRegions(normalPixels, nmW, nmH, k);
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

        ASErr err = sAIArt->NewArt(kGroupArt, kPlaceAboveAll, nullptr, &surfaceGroups[r]);
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
        for (auto& entry : files) {
            std::string name = entry["name"].get<std::string>();
            std::string path = entry["path"].get<std::string>();

            // 1. Place raster as hidden reference layer (use saved bounds so all
            //    images land at the same position instead of stacking vertically)
            fprintf(stderr, "[TraceModule] Placing reference: %s -> %s\n", name.c_str(), path.c_str());
            PlaceImageAsLayer(path, name + " (ref)", refLeft, refTop, refRight, refBottom);
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
                "filter_speckle=8, "
                "color_precision=3, "
                "layer_difference=25, "
                "corner_threshold=60, "
                "length_threshold=4.0, "
                "max_iterations=10, "
                "splice_threshold=45, "
                "path_precision=3"
                ")\" 2>&1",
                path.c_str(), svgOut.c_str());

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

            // Raster matrix maps pixel space to artwork space
            // Pixel (0,0) is top-left; in AI coords, Y increases upward
            // Matrix: [scaleX  0      0     ]
            //         [0       scaleY 0     ]
            //         [tx      ty     1     ]
            AIRealMatrix matrix;
            matrix.a = (AIReal)(targetW / (double)imgW);    // scaleX
            matrix.b = (AIReal)0.0;
            matrix.c = (AIReal)0.0;
            matrix.d = (AIReal)(-(targetH / (double)imgH)); // scaleY (negative for Y flip)
            matrix.tx = (AIReal)artLeft;                      // translate X
            matrix.ty = (AIReal)artTop;                       // translate Y (top, since d is negative)

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
//  DrawOverlay — no annotator overlay needed for trace
//========================================================================================

void TraceModule::DrawOverlay(AIAnnotatorMessage* /*message*/)
{
    // Trace module doesn't draw overlays
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
