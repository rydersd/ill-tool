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
#include "DrawCommands.h"
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
#include <fstream>
#include <sstream>
#include <dirent.h>
#include <sys/stat.h>

using json = nlohmann::json;

extern IllToolPlugin* gPlugin;

namespace {

double gSvgViewBoxX = 0.0;
double gSvgViewBoxY = 0.0;

//========================================================================================
//  IllTool Document State — hidden marker art for per-document persistence
//========================================================================================

static const char* kIllToolDocStateMarker = "IllToolDocState";

// Dictionary keys (short, prefixed with itds_)
static const char* kItdsSymActive   = "itds_sym_active";
static const char* kItdsSymAxisX    = "itds_sym_axisX";
static const char* kItdsSymSide     = "itds_sym_side";
static const char* kItdsSymBlendPct = "itds_sym_blendPct";
static const char* kItdsCutActive   = "itds_cut_active";

/** Find the hidden marker group for IllTool doc state. Returns nullptr if not found. */
static AIArtHandle FindIllToolMarkerArt()
{
    if (!sAIArt || !sAIDictionary || !sAILayer) return nullptr;

    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    for (ai::int32 li = 0; li < layerCount; li++) {
        AILayerHandle layer = nullptr;
        if (sAILayer->GetNthLayer(li, &layer) != kNoErr) continue;
        AIArtHandle layerGroup = nullptr;
        if (sAIArt->GetFirstArtOfLayer(layer, &layerGroup) != kNoErr || !layerGroup) continue;

        AIArtHandle child = nullptr;
        sAIArt->GetArtFirstChild(layerGroup, &child);
        while (child) {
            AIBoolean hasDict = sAIArt->HasDictionary(child);
            if (hasDict) {
                AIDictionaryRef dict = nullptr;
                if (sAIArt->GetDictionary(child, &dict) == kNoErr && dict) {
                    AIDictKey key = sAIDictionary->Key(kIllToolDocStateMarker);
                    AIBoolean isMarker = false;
                    ASErr gErr = sAIDictionary->GetBooleanEntry(dict, key, &isMarker);
                    sAIDictionary->Release(dict);
                    if (gErr == kNoErr && isMarker) {
                        return child;
                    }
                }
            }
            AIArtHandle next = nullptr;
            sAIArt->GetArtSibling(child, &next);
            child = next;
        }
    }
    return nullptr;
}

/** Create a hidden marker group for IllTool doc state in the first layer. */
static AIArtHandle CreateIllToolMarkerArt()
{
    if (!sAIArt || !sAIDictionary || !sAILayer) return nullptr;

    ai::int32 layerCount = 0;
    sAILayer->CountLayers(&layerCount);
    if (layerCount == 0) return nullptr;

    AILayerHandle layer = nullptr;
    sAILayer->GetNthLayer(0, &layer);
    if (!layer) return nullptr;

    AIArtHandle layerGroup = nullptr;
    if (sAIArt->GetFirstArtOfLayer(layer, &layerGroup) != kNoErr || !layerGroup) return nullptr;

    AIArtHandle markerArt = nullptr;
    ASErr err = sAIArt->NewArt(kGroupArt, kPlaceInsideOnTop, layerGroup, &markerArt);
    if (err != kNoErr || !markerArt) {
        fprintf(stderr, "[IllTool DocState] CreateIllToolMarkerArt: NewArt failed %d\n", (int)err);
        return nullptr;
    }

    // Hide and lock so user can't accidentally interact
    sAIArt->SetArtUserAttr(markerArt, kArtHidden | kArtLocked, kArtHidden | kArtLocked);

    // Set the marker flag
    AIDictionaryRef dict = nullptr;
    err = sAIArt->GetDictionary(markerArt, &dict);
    if (err == kNoErr && dict) {
        AIDictKey key = sAIDictionary->Key(kIllToolDocStateMarker);
        sAIDictionary->SetBooleanEntry(dict, key, true);
        sAIDictionary->Release(dict);
    }

    fprintf(stderr, "[IllTool DocState] Created marker art %p\n", (void*)markerArt);
    return markerArt;
}

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
//  EnsureImageBounds — refresh fArt* from document, clearing stale state first
//========================================================================================

void TraceModule::EnsureImageBounds()
{
    // Clear stale state before refresh
    fArtLeft = fArtTop = fArtRight = fArtBottom = 0;
    fImageArtHandle = nullptr;
    fHasOrigMatrix = false;
    // Refresh — FindImagePath populates fArt* as side effect
    FindImagePath();
}

//========================================================================================
//  HandleOp
//========================================================================================

bool TraceModule::HandleOp(const PluginOp& op)
{
    switch (op.type) {
        case OpType::TracePreprocessPreview:
            GeneratePreprocessPreview();
            return true;

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
        case OpType::SymmetryPreview:
            GenerateSymmetryPreview();
            return true;

        case OpType::CommitSymmetry:
            ExecuteSymmetryCommit();
            return true;

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
    fImageArtHandle = nullptr;  // Reset cached handle
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
            fImageArtHandle = art;  // Cache for clipping mask creation
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
                fImageArtHandle = art;  // Cache for clipping mask creation
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
                    fImageArtHandle = rasterArt;  // Cache for clipping mask creation

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
//  DrawOverlay — draw cutout preview silhouette as an annotator overlay
//========================================================================================

void TraceModule::DrawOverlay(AIAnnotatorMessage* message)
{
    if (!message || !message->drawer || !sAIDocumentView) return;

    // Draw pose overlay (body skeleton, face landmarks, hand joints)
    DrawPoseOverlay(message);

    // Draw preprocess preview — semi-transparent PNG overlay showing what the trace will see
    if (BridgeGetPreprocessPreviewActive()) {
        std::vector<unsigned char> pngData = BridgeGetPreprocessPreviewData();
        if (!pngData.empty() && fArtRight > fArtLeft && fArtTop > fArtBottom) {
            AIAnnotatorDrawer* drawer = message->drawer;

            // Convert art bounds to view coordinates for the overlay rect
            AIRealPoint artTL, artBR;
            artTL.h = (AIReal)fArtLeft;  artTL.v = (AIReal)fArtTop;
            artBR.h = (AIReal)fArtRight; artBR.v = (AIReal)fArtBottom;

            AIPoint viewTL, viewBR;
            if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTL, &viewTL) == kNoErr &&
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artBR, &viewBR) == kNoErr) {

                // Set semi-transparent opacity so user can see original beneath
                sAIAnnotatorDrawer->SetOpacity(drawer, 0.70f);

                // Build the bounding rect (view coords: top < bottom)
                AIRect viewRect;
                viewRect.left   = std::min(viewTL.h, viewBR.h);
                viewRect.top    = std::min(viewTL.v, viewBR.v);
                viewRect.right  = std::max(viewTL.h, viewBR.h);
                viewRect.bottom = std::max(viewTL.v, viewBR.v);

                // Draw the preprocessed image as a PNG overlay
                ASErr err = sAIAnnotatorDrawer->DrawPNGImageCentered(
                    drawer,
                    pngData.data(),
                    (ai::uint32)pngData.size(),
                    viewRect);

                if (err != kNoErr) {
                    fprintf(stderr, "[TraceModule] DrawPNGImageCentered failed: %d\n", (int)err);
                }

                // Reset opacity for subsequent drawing
                sAIAnnotatorDrawer->SetOpacity(drawer, 1.0f);

                // Draw border around the preview to make it visually distinct
                AIRGBColor borderColor;
                borderColor.red = 0; borderColor.green = 50000; borderColor.blue = 50000;
                sAIAnnotatorDrawer->SetColor(drawer, borderColor);
                sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0f);
                sAIAnnotatorDrawer->DrawRect(drawer, viewRect, false);
            }
        }
    }

    // Draw symmetry midline and preview overlay
    if (BridgeGetSymmetryActive() && fArtRight > fArtLeft && fArtTop > fArtBottom) {
        AIAnnotatorDrawer* drawer = message->drawer;

        // Compute midline position in art coordinates
        float axisNorm = BridgeGetSymmetryAxisX();
        double artW = fArtRight - fArtLeft;
        double midArtX = fArtLeft + axisNorm * artW;

        // Convert to view coordinates
        AIRealPoint artTop, artBot;
        artTop.h = (AIReal)midArtX; artTop.v = (AIReal)fArtTop;
        artBot.h = (AIReal)midArtX; artBot.v = (AIReal)fArtBottom;

        AIPoint viewTop, viewBot;
        if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTop, &viewTop) == kNoErr &&
            sAIDocumentView->ArtworkPointToViewPoint(NULL, &artBot, &viewBot) == kNoErr) {

            // Draw the symmetry preview PNG overlay (if available)
            if (!fSymmetryPreviewData.empty()) {
                AIRealPoint artTL, artBR;
                artTL.h = (AIReal)fArtLeft;  artTL.v = (AIReal)fArtTop;
                artBR.h = (AIReal)fArtRight; artBR.v = (AIReal)fArtBottom;

                AIPoint vTL, vBR;
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artTL, &vTL);
                sAIDocumentView->ArtworkPointToViewPoint(NULL, &artBR, &vBR);

                sAIAnnotatorDrawer->SetOpacity(drawer, 0.80f);

                AIRect previewRect;
                previewRect.left   = std::min(vTL.h, vBR.h);
                previewRect.top    = std::min(vTL.v, vBR.v);
                previewRect.right  = std::max(vTL.h, vBR.h);
                previewRect.bottom = std::max(vTL.v, vBR.v);

                sAIAnnotatorDrawer->DrawPNGImageCentered(
                    drawer,
                    fSymmetryPreviewData.data(),
                    (ai::uint32)fSymmetryPreviewData.size(),
                    previewRect);

                sAIAnnotatorDrawer->SetOpacity(drawer, 1.0f);
            }

            // Draw midline — orange, 2px
            AIRGBColor orange;
            orange.red = 65535; orange.green = 34952; orange.blue = 0;  // #FF8800
            sAIAnnotatorDrawer->SetColor(drawer, orange);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0f);
            sAIAnnotatorDrawer->DrawLine(drawer, viewTop, viewBot);

            // Draw drag handles — filled circles at top and bottom
            AIRect handleTop, handleBot;
            int r = 6;
            handleTop.left = viewTop.h - r; handleTop.top = viewTop.v - r;
            handleTop.right = viewTop.h + r; handleTop.bottom = viewTop.v + r;
            handleBot.left = viewBot.h - r; handleBot.top = viewBot.v - r;
            handleBot.right = viewBot.h + r; handleBot.bottom = viewBot.v + r;
            sAIAnnotatorDrawer->DrawEllipse(drawer, handleTop, true);
            sAIAnnotatorDrawer->DrawEllipse(drawer, handleBot, true);

            // Draw "L" / "R" labels near the midline
            int side = BridgeGetSymmetrySide();
            AIRGBColor labelColor;
            labelColor.red = 65535; labelColor.green = 65535; labelColor.blue = 65535;
            sAIAnnotatorDrawer->SetColor(drawer, labelColor);

            AIPoint labelL, labelR;
            int midY = (viewTop.v + viewBot.v) / 2;
            labelL.h = viewTop.h - 20; labelL.v = midY;
            labelR.h = viewTop.h + 10; labelR.v = midY;

            // Indicate which side is "good" with a filled circle marker
            AIRGBColor goodColor;
            goodColor.red = 0; goodColor.green = 52428; goodColor.blue = 0;  // green
            AIRGBColor fadeColor;
            fadeColor.red = 39321; fadeColor.green = 39321; fadeColor.blue = 39321;  // gray

            AIRect markerL, markerR;
            int mr = 4;
            markerL.left = labelL.h - mr; markerL.top = labelL.v - mr;
            markerL.right = labelL.h + mr; markerL.bottom = labelL.v + mr;
            markerR.left = labelR.h - mr; markerR.top = labelR.v - mr;
            markerR.right = labelR.h + mr; markerR.bottom = labelR.v + mr;

            sAIAnnotatorDrawer->SetColor(drawer, side == 0 ? goodColor : fadeColor);
            sAIAnnotatorDrawer->DrawEllipse(drawer, markerL, true);
            sAIAnnotatorDrawer->SetColor(drawer, side == 1 ? goodColor : fadeColor);
            sAIAnnotatorDrawer->DrawEllipse(drawer, markerR, true);
        }
    }

    // Draw cutout preview — green filled bezier paths showing what STAYS.
    // Outline is opaque, fill is 10% opacity green.
    if (!BridgeGetCutoutPreviewActive()) return;

    std::string pathsJSON = BridgeGetCutoutPreviewPaths();
    if (pathsJSON.empty()) return;

    AIAnnotatorDrawer* drawer = message->drawer;

    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) return;

        for (const auto& pathObj : previewData) {
            if (!pathObj.contains("points")) continue;
            const auto& points = pathObj["points"];
            if (!points.is_array() || points.size() < 2) continue;

            // Build view-space polygon by sampling all bezier segments
            std::vector<AIPoint> viewPoly;
            for (size_t i = 0; i + 1 < points.size(); i++) {
                const auto& p0 = points[i];
                const auto& p1 = points[i + 1];

                double x0 = p0.value("x", 0.0), y0 = p0.value("y", 0.0);
                double ox0 = p0.value("outX", x0), oy0 = p0.value("outY", y0);
                double ix1 = p1.value("inX", p1.value("x", 0.0));
                double iy1 = p1.value("inY", p1.value("y", 0.0));
                double x1 = p1.value("x", 0.0), y1 = p1.value("y", 0.0);

                bool isCurve = (std::abs(ox0 - x0) > 0.1 || std::abs(oy0 - y0) > 0.1 ||
                                std::abs(ix1 - x1) > 0.1 || std::abs(iy1 - y1) > 0.1);

                int steps = isCurve ? 20 : 1;
                for (int s = (i == 0 ? 0 : 1); s <= steps; s++) {
                    double t = (double)s / steps;
                    double u = 1.0 - t;
                    double bx, by;
                    if (isCurve) {
                        bx = u*u*u*x0 + 3*u*u*t*ox0 + 3*u*t*t*ix1 + t*t*t*x1;
                        by = u*u*u*y0 + 3*u*u*t*oy0 + 3*u*t*t*iy1 + t*t*t*y1;
                    } else {
                        bx = x0 + t * (x1 - x0);
                        by = y0 + t * (y1 - y0);
                    }

                    AIRealPoint artPt;
                    artPt.h = (AIReal)bx; artPt.v = (AIReal)by;
                    AIPoint viewPt;
                    if (sAIDocumentView->ArtworkPointToViewPoint(NULL, &artPt, &viewPt) == kNoErr) {
                        viewPoly.push_back(viewPt);
                    }
                }
            }

            if (viewPoly.size() < 3) continue;

            // Signed area (shoelace) in view space detects hole vs outer.
            // vtracer-cutout + Y-down view coords: outer CCW = positive, hole CW = negative.
            // (Previously verified working in runtime — "it's working" per user feedback
            //  after switching to hierarchical='cutout' + subpath M-split.)
            double signedArea = 0.0;
            for (size_t i = 0; i < viewPoly.size(); i++) {
                size_t j = (i + 1) % viewPoly.size();
                signedArea += (double)viewPoly[i].h * (double)viewPoly[j].v
                            - (double)viewPoly[j].h * (double)viewPoly[i].v;
            }
            bool isHole = (signedArea > 0);

            AIRGBColor green;
            green.red = 0; green.green = 52428; green.blue = 0;
            sAIAnnotatorDrawer->SetColor(drawer, green);

            if (!isHole) {
                sAIAnnotatorDrawer->SetOpacity(drawer, 0.10f);
                sAIAnnotatorDrawer->DrawPolygon(drawer, viewPoly.data(), (ai::int32)viewPoly.size(), true);
            }
            // Outline always visible
            sAIAnnotatorDrawer->SetOpacity(drawer, 0.80f);
            sAIAnnotatorDrawer->SetLineWidth(drawer, 2.0f);
            sAIAnnotatorDrawer->DrawPolygon(drawer, viewPoly.data(), (ai::int32)viewPoly.size(), false);
        }
    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] DrawOverlay cutout parse error: %s\n", ex.what());
    }
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

    // Clear preprocess preview on document change
    BridgeSetPreprocessPreviewActive(false);
    BridgeSetPreprocessPreviewData({});

    // Load persisted state for the incoming document
    LoadDocState();
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
//  SaveDocState / LoadDocState — persist symmetry + cutout state in art dictionary
//========================================================================================

void TraceModule::SaveDocState()
{
    if (!sAIDictionary || !sAIArt) return;

    // Only save if there's meaningful state to persist
    bool symActive  = BridgeGetSymmetryActive();
    bool cutActive  = BridgeGetCutoutPreviewActive();
    if (!symActive && !cutActive) {
        // Nothing active — no need to write (avoid creating marker art for empty state)
        return;
    }

    AIArtHandle marker = FindIllToolMarkerArt();
    if (!marker) marker = CreateIllToolMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool DocState] SaveDocState: no marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kItdsSymActive),   symActive);
    sAIDictionary->SetRealEntry(dict,    sAIDictionary->Key(kItdsSymAxisX),    (AIReal)BridgeGetSymmetryAxisX());
    sAIDictionary->SetIntegerEntry(dict, sAIDictionary->Key(kItdsSymSide),     (ai::int32)BridgeGetSymmetrySide());
    sAIDictionary->SetRealEntry(dict,    sAIDictionary->Key(kItdsSymBlendPct), (AIReal)BridgeGetSymmetryBlendPct());
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key(kItdsCutActive),   cutActive);

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool DocState] SaveDocState: sym=%d cut=%d\n", (int)symActive, (int)cutActive);
}

void TraceModule::LoadDocState()
{
    if (!sAIDictionary || !sAIArt) return;

    AIArtHandle marker = FindIllToolMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool DocState] LoadDocState: no marker found — fresh doc\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    AIBoolean symActive = false;
    AIReal    symAxisX  = 0.5f;
    ai::int32 symSide   = 0;
    AIReal    symBlend  = 1.0f;
    AIBoolean cutActive = false;

    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(kItdsSymActive),   &symActive);
    sAIDictionary->GetRealEntry(dict,    sAIDictionary->Key(kItdsSymAxisX),    &symAxisX);
    sAIDictionary->GetIntegerEntry(dict, sAIDictionary->Key(kItdsSymSide),     &symSide);
    sAIDictionary->GetRealEntry(dict,    sAIDictionary->Key(kItdsSymBlendPct), &symBlend);
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(kItdsCutActive),   &cutActive);

    sAIDictionary->Release(dict);

    BridgeSetSymmetryActive(symActive);
    BridgeSetSymmetryAxisX((float)symAxisX);
    BridgeSetSymmetrySide((int)symSide);
    BridgeSetSymmetryBlendPct((float)symBlend);
    BridgeSetCutoutPreviewActive(cutActive);

    fprintf(stderr, "[IllTool DocState] LoadDocState: sym=%d axis=%.2f side=%d blend=%.1f cut=%d\n",
            (int)symActive, (float)symAxisX, (int)symSide, (float)symBlend, (int)cutActive);
}

//========================================================================================
//  Include split implementation files — not separate compilation units
//========================================================================================

#include "TraceImage.cpp"
#include "TraceVector.cpp"
#include "TraceSymmetry.cpp"
