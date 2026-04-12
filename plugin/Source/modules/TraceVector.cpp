//========================================================================================
//
//  TraceVector.cpp — Vector/path operations (trace, SVG parse, contours, pose, commit)
//  Part of TraceModule — included from TraceModule.cpp
//
//========================================================================================

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

    std::string traceInputPath = imagePath;

    // If the input image has alpha (e.g., a prior Subject Cutout result), flatten over
    // white BEFORE any mode-specific processing. Transparent pixels still carry their
    // original RGB (stbi leaves them), so centerline mode's Canny would see the old sky
    // as edges. Compositing over white gives all downstream paths a clean opaque image.
    {
        int chkW = 0, chkH = 0, chkC = 0;
        if (stbi_info(traceInputPath.c_str(), &chkW, &chkH, &chkC) && chkC == 4) {
            fprintf(stderr, "[TraceModule] Input has alpha (%d ch) — compositing over white for trace\n", chkC);
            unsigned char* rgba = stbi_load(traceInputPath.c_str(), &chkW, &chkH, nullptr, 4);
            if (rgba && chkW > 0 && chkH > 0) {
                int px = chkW * chkH;
                unsigned char* flat = (unsigned char*)malloc(px * 3);
                if (flat) {
                    for (int i = 0; i < px; i++) {
                        unsigned char a = rgba[i * 4 + 3];
                        flat[i * 3 + 0] = (unsigned char)((rgba[i * 4 + 0] * a + 255 * (255 - a)) / 255);
                        flat[i * 3 + 1] = (unsigned char)((rgba[i * 4 + 1] * a + 255 * (255 - a)) / 255);
                        flat[i * 3 + 2] = (unsigned char)((rgba[i * 4 + 2] * a + 255 * (255 - a)) / 255);
                    }
                    const char* flatPath = "/tmp/illtool_trace_flat.png";
                    if (stbi_write_png(flatPath, chkW, chkH, 3, flat, chkW * 3)) {
                        traceInputPath = flatPath;
                        fprintf(stderr, "[TraceModule] Wrote flattened RGB to %s (%dx%d)\n", flatPath, chkW, chkH);
                    }
                    free(flat);
                }
                stbi_image_free(rgba);
            }
        }
    }

    // --- Centerline mode: Canny edges → skeletonize → trace ---
    // Canny finds actual stroke edges (ignores gradual shading).
    // Skeleton of the edge image gives single-pixel centerlines of drawn strokes.
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

    // Signal completion so the panel status timer swaps progress bar → Run button.
    // Must include "Traced:" — one of the "done" patterns in TracePanelController.
    {
        char doneMsg[128];
        snprintf(doneMsg, sizeof(doneMsg), "Traced: %d paths", pathCount);
        BridgeSetTraceStatus(doneMsg);
    }

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
//  HitTestPreviewPoint — check if artPt is near any anchor in the preview paths JSON.
//  Sets fEditingPathIndex and fEditingPointIndex on hit; returns true if a hit was found.
//========================================================================================

bool TraceModule::HitTestPreviewPoint(AIRealPoint artPt, double tolerance)
{
    fEditingPathIndex  = -1;
    fEditingPointIndex = -1;

    std::string pathsJSON = BridgeGetCutoutPreviewPaths();
    if (pathsJSON.empty()) return false;

    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) return false;

        double bestDist = tolerance + 1.0;

        for (size_t pi = 0; pi < previewData.size(); pi++) {
            const auto& pathObj = previewData[pi];
            if (!pathObj.contains("points")) continue;
            const auto& points = pathObj["points"];
            if (!points.is_array()) continue;

            for (size_t qi = 0; qi < points.size(); qi++) {
                double px = points[qi].value("x", 0.0);
                double py = points[qi].value("y", 0.0);
                double dx = artPt.h - px;
                double dy = artPt.v - py;
                double dist = std::sqrt(dx * dx + dy * dy);
                if (dist < bestDist) {
                    bestDist = dist;
                    fEditingPathIndex  = (int)pi;
                    fEditingPointIndex = (int)qi;
                }
            }
        }

        if (bestDist <= tolerance) {
            fprintf(stderr, "[TraceModule] HitTest: path %d point %d (dist %.1f)\n",
                    fEditingPathIndex, fEditingPointIndex, bestDist);
            return true;
        }

        fEditingPathIndex  = -1;
        fEditingPointIndex = -1;
    }
    catch (const std::exception& ex) {
        fprintf(stderr, "[TraceModule] HitTest parse error: %s\n", ex.what());
    }
    return false;
}

//========================================================================================
//  DragPreviewPoint — update the editing point position (move or smooth).
//  Modifies the bridge JSON in-place and requests an annotator redraw.
//========================================================================================

void TraceModule::DragPreviewPoint(AIRealPoint artPt, bool cmdHeld)
{
    if (fEditingPathIndex < 0 || fEditingPointIndex < 0) return;

    // Clamp drag target to image bounds
    if (fArtRight > fArtLeft && fArtTop > fArtBottom) {
        artPt.h = std::max((AIReal)fArtLeft, std::min(artPt.h, (AIReal)fArtRight));
        artPt.v = std::max((AIReal)fArtBottom, std::min(artPt.v, (AIReal)fArtTop));
    }

    std::string pathsJSON = BridgeGetCutoutPreviewPaths();
    if (pathsJSON.empty()) return;

    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) return;
        if ((size_t)fEditingPathIndex >= previewData.size()) return;

        auto& pathObj = previewData[fEditingPathIndex];
        if (!pathObj.contains("points")) return;
        auto& points = pathObj["points"];
        if (!points.is_array() || (size_t)fEditingPointIndex >= points.size()) return;

        if (cmdHeld) {
            // ── Smooth mode: blend point toward average of neighbors ──
            auto& pt = points[fEditingPointIndex];
            int numPts = (int)points.size();
            bool closed = pathObj.value("closed", false);

            // Find neighbor indices (wrapping for closed paths)
            int prevIdx = fEditingPointIndex - 1;
            int nextIdx = fEditingPointIndex + 1;
            if (closed) {
                if (prevIdx < 0)       prevIdx = numPts - 1;
                if (nextIdx >= numPts) nextIdx = 0;
            }

            bool hasPrev = (prevIdx >= 0 && prevIdx < numPts);
            bool hasNext = (nextIdx >= 0 && nextIdx < numPts);

            if (!hasPrev && !hasNext) return;  // isolated point, nothing to smooth toward

            // Compute average of available neighbors
            double avgX = 0, avgY = 0;
            int count = 0;
            if (hasPrev) {
                avgX += points[prevIdx].value("x", 0.0);
                avgY += points[prevIdx].value("y", 0.0);
                count++;
            }
            if (hasNext) {
                avgX += points[nextIdx].value("x", 0.0);
                avgY += points[nextIdx].value("y", 0.0);
                count++;
            }
            avgX /= count;
            avgY /= count;

            // Drag distance controls blend amount (0.01 per point of drag)
            double dragDx = artPt.h - fEditDragStart.h;
            double dragDy = artPt.v - fEditDragStart.v;
            double dragDist = std::sqrt(dragDx * dragDx + dragDy * dragDy);
            double blend = std::min(dragDist * 0.01, 1.0);

            double curX = pt.value("x", 0.0);
            double curY = pt.value("y", 0.0);
            double newX = curX + (avgX - curX) * blend;
            double newY = curY + (avgY - curY) * blend;

            double deltaX = newX - curX;
            double deltaY = newY - curY;

            pt["x"] = newX;
            pt["y"] = newY;
            pt["inX"]  = pt.value("inX",  curX) + deltaX;
            pt["inY"]  = pt.value("inY",  curY) + deltaY;
            pt["outX"] = pt.value("outX", curX) + deltaX;
            pt["outY"] = pt.value("outY", curY) + deltaY;

            // Recompute smooth handles: set in/out to 1/3 distance along tangent to neighbors
            if (hasPrev && hasNext) {
                double prevX = points[prevIdx].value("x", 0.0);
                double prevY = points[prevIdx].value("y", 0.0);
                double nextX = points[nextIdx].value("x", 0.0);
                double nextY = points[nextIdx].value("y", 0.0);

                // Tangent direction: from prev neighbor to next neighbor
                double tx = nextX - prevX;
                double ty = nextY - prevY;
                double tLen = std::sqrt(tx * tx + ty * ty);
                if (tLen > 0.001) {
                    tx /= tLen;
                    ty /= tLen;

                    // Handle lengths: 1/3 of distance to each neighbor
                    double distPrev = std::sqrt((newX - prevX) * (newX - prevX) +
                                                (newY - prevY) * (newY - prevY));
                    double distNext = std::sqrt((newX - nextX) * (newX - nextX) +
                                                (newY - nextY) * (newY - nextY));

                    pt["inX"]  = newX - tx * (distPrev / 3.0);
                    pt["inY"]  = newY - ty * (distPrev / 3.0);
                    pt["outX"] = newX + tx * (distNext / 3.0);
                    pt["outY"] = newY + ty * (distNext / 3.0);
                }
                pt["corner"] = false;  // smoothed point is no longer a corner
            }
        }
        else {
            // ── Move mode: translate point + handles by cursor delta ──
            auto& pt = points[fEditingPointIndex];
            double curX = pt.value("x", 0.0);
            double curY = pt.value("y", 0.0);
            double deltaX = artPt.h - curX;
            double deltaY = artPt.v - curY;

            pt["x"] = (double)artPt.h;
            pt["y"] = (double)artPt.v;
            pt["inX"]  = pt.value("inX",  curX) + deltaX;
            pt["inY"]  = pt.value("inY",  curY) + deltaY;
            pt["outX"] = pt.value("outX", curX) + deltaX;
            pt["outY"] = pt.value("outY", curY) + deltaY;
        }

        // Write updated paths back to bridge state
        BridgeSetCutoutPreviewPaths(previewData.dump());

        // Request annotator redraw so the overlay updates immediately
        InvalidateFullView();
    }
    catch (const std::exception& ex) {
        fprintf(stderr, "[TraceModule] DragPreviewPoint error: %s\n", ex.what());
    }
}

//========================================================================================
//  CommitPreviewEdit — finalize the drag edit (reset editing state).
//  The actual data is already written during DragPreviewPoint, so this just cleans up.
//========================================================================================

void TraceModule::CommitPreviewEdit()
{
    if (fEditingPathIndex >= 0) {
        fprintf(stderr, "[TraceModule] CommitPreviewEdit: path %d point %d (smooth=%d)\n",
                fEditingPathIndex, fEditingPointIndex, (int)fEditingSmooth);
    }
    fEditingPathIndex  = -1;
    fEditingPointIndex = -1;
    fEditingSmooth     = false;

    // Final redraw to ensure overlay matches committed state
    InvalidateFullView();
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
        "hierarchical='cutout', "   // cutout mode produces real holes (reverse winding)
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

        // Split pathData at each M/m (move) command — cutout mode emits outer + holes
        // as one <path> separated by move commands. Parsing as one segs vector would
        // connect the outer's last point to the hole's first point with a seam line.
        std::vector<std::string> subPaths;
        {
            size_t sp = 0;
            // Find start of first M
            while (sp < pathData.size() && pathData[sp] != 'M' && pathData[sp] != 'm') sp++;
            while (sp < pathData.size()) {
                size_t nextM = sp + 1;
                while (nextM < pathData.size() &&
                       pathData[nextM] != 'M' && pathData[nextM] != 'm') nextM++;
                subPaths.push_back(pathData.substr(sp, nextM - sp));
                sp = nextM;
            }
        }

        for (const std::string& subData : subPaths) {
            std::vector<AIPathSegment> segs;
            bool closed = false;
            if (!ParseSVGPathToSegments(subData, segs, closed) || segs.empty()) continue;

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
        }  // end for-each-subpath
    }      // end while <path> element scan

    BridgeSetCutoutPreviewPaths(allPaths.dump());
    BridgeSetCutoutPreviewActive(true);

    return pathCount;
}
//========================================================================================
//  CommitCutout — create cut lines, clipping mask on image, and transparent cutout PNG
//
//  Three outputs:
//  1. Cut lines on "Cut Lines" layer (stroked outlines for artwork)
//  2. Clipping mask on the image (non-destructive visual mask via kGroupArt + kArtIsClipMask)
//  3. Cutout PNG with transparency (RGBA for normal pipeline and pixel-level ops)
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

    // Reload image bounds and cache image art handle
    std::string imagePath = FindImagePath();

    try {
        json previewData = json::parse(pathsJSON);
        if (!previewData.is_array()) {
            BridgeSetTraceStatus("Invalid cutout data");
            fTraceInProgress = false;
            return;
        }

        // ── Parse all path segments from preview data (shared by cut lines + clip) ──

        struct ParsedPath {
            std::vector<AIPathSegment> segs;
            bool closed;
        };
        std::vector<ParsedPath> parsedPaths;

        for (const auto& pathObj : previewData) {
            if (!pathObj.contains("points")) continue;
            const auto& points = pathObj["points"];
            if (!points.is_array() || points.size() < 3) continue;

            ParsedPath pp;
            pp.closed = pathObj.value("closed", true);

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
                pp.segs.push_back(seg);
            }

            if (pp.segs.size() >= 3)
                parsedPaths.push_back(std::move(pp));
        }

        if (parsedPaths.empty()) {
            BridgeSetTraceStatus("No valid cutout paths found");
            fTraceInProgress = false;
            return;
        }

        // ── Output 1: Cut lines on "Cut Lines" layer ──

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

        AIArtHandle layerArt = nullptr;
        sAIArt->GetFirstArtOfLayer(cutLayer, &layerArt);

        int created = 0;
        for (const auto& pp : parsedPaths) {
            AIArtHandle newPath = nullptr;
            ASErr err = sAIArt->NewArt(kPathArt,
                layerArt ? kPlaceInsideOnTop : kPlaceAboveAll,
                layerArt ? layerArt : nullptr,
                &newPath);
            if (err != kNoErr || !newPath) continue;

            ai::int16 nc = (ai::int16)pp.segs.size();
            sAIPath->SetPathSegmentCount(newPath, nc);
            sAIPath->SetPathSegments(newPath, 0, nc, pp.segs.data());
            sAIPath->SetPathClosed(newPath, pp.closed);

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

        fprintf(stderr, "[TraceModule] Created %d cut lines on Cut Lines layer\n", created);

        // ── Output 2: Build RGBA cutout PNG (RGB from image × alpha from mask) ──

        std::string compositePath = "/tmp/illtool_cutout_composite.png";
        std::string cutoutPath = "/tmp/illtool_cutout_rgba.png";
        int rgbaW = 0, rgbaH = 0;
        bool rgbaReady = false;

        if (!imagePath.empty()) {
            BridgeSetTraceStatus("Building transparent cutout...");

            int imgW = 0, imgH = 0, imgC = 0;
            unsigned char* img = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 3);

            int mskW = 0, mskH = 0, mskC = 0;
            unsigned char* mask = stbi_load(compositePath.c_str(), &mskW, &mskH, &mskC, 1);

            if (img && mask) {
                int w = std::min(imgW, mskW);
                int h = std::min(imgH, mskH);

                unsigned char* rgba = (unsigned char*)calloc(w * h * 4, 1);
                for (int y = 0; y < h; y++) {
                    for (int x = 0; x < w; x++) {
                        int iIdx = (y * imgW + x) * 3;
                        int mIdx = y * mskW + x;
                        int oIdx = (y * w + x) * 4;
                        unsigned char alpha = mask[mIdx];
                        rgba[oIdx]     = img[iIdx];
                        rgba[oIdx + 1] = img[iIdx + 1];
                        rgba[oIdx + 2] = img[iIdx + 2];
                        rgba[oIdx + 3] = alpha;
                    }
                }

                int wrote = stbi_write_png(cutoutPath.c_str(), w, h, 4, rgba, w * 4);
                free(rgba);

                if (wrote) {
                    rgbaReady = true;
                    rgbaW = w;
                    rgbaH = h;
                    ProjectStore::Instance().SaveNormalMap(cutoutPath);
                    fprintf(stderr, "[TraceModule] Built cutout RGBA: %s (%dx%d)\n",
                            cutoutPath.c_str(), w, h);
                } else {
                    fprintf(stderr, "[TraceModule] Failed to write cutout RGBA PNG\n");
                }
            } else {
                if (!img) fprintf(stderr, "[TraceModule] Cutout PNG: failed to load source image\n");
                if (!mask) fprintf(stderr, "[TraceModule] Cutout PNG: no composite mask at %s\n",
                                   compositePath.c_str());
            }
            if (img) stbi_image_free(img);
            if (mask) stbi_image_free(mask);
        }

        // ── Output 3: Replace the image with a kPlacedArt linked to the RGBA PNG ──
        //
        // kRasterArt + SetRasterTile does not reliably honor alpha in display (iterated 4x).
        // kPlacedArt linking a PNG file delegates all pixel format handling to Illustrator's
        // file importers, which DO honor PNG alpha correctly. This is the Apple Preview path.

        bool rasterReplaced = false;
        // kForceReplace inherits position from m_hOldArt, so we DON'T need fHasOrigMatrix.
        // Previously this blocked replacement for kPlacedArt (which never sets fHasOrigMatrix).
        if (rgbaReady && fImageArtHandle && sAIPlaced) {
            BridgeSetTraceStatus("Placing transparent cutout...");

            // Build ai::FilePath from /tmp/illtool_cutout_rgba.png
            CFStringRef cfPath = CFStringCreateWithCString(kCFAllocatorDefault,
                                                           cutoutPath.c_str(),
                                                           kCFStringEncodingUTF8);
            if (cfPath) {
                ai::FilePath pngPath(cfPath);
                CFRelease(cfPath);

                // Use ExecPlaceRequest with kVanillaPlace to place the PNG as a linked
                // object. Illustrator's PNG importer sets up matrix, color space, alpha,
                // and bounds automatically.
                // kForceReplace: swap the existing raster in-place with our PNG.
                // Illustrator keeps the old art's position/bounds automatically — no matrix math.
                // The original raster is disposed by ExecPlaceRequest (it IS the cutout now).
                AIPlaceRequestData placeReq;
                placeReq.m_lPlaceMode       = kForceReplace;
                placeReq.m_hOldArt          = fImageArtHandle;
                placeReq.m_pFilePath        = &pngPath;
                placeReq.m_filemethod       = 0;   // 0 = embed
                placeReq.m_disableTemplate  = true;
                placeReq.m_doShowParamDialog = false;
                placeReq.m_PlaceTransformType = kAIPlaceTransformTypeNone;

                ASErr err = sAIPlaced->ExecPlaceRequest(placeReq);
                if (err == kNoErr && placeReq.m_hNewArt) {
                    AIArtHandle newPlaced = placeReq.m_hNewArt;
                    sAIArt->SetArtName(newPlaced, ai::UnicodeString("Subject Cutout"));

                    AIRealRect finalBounds;
                    sAIArt->GetArtBounds(newPlaced, &finalBounds);
                    fprintf(stderr, "[TraceModule] Cutout replaced raster via kForceReplace: "
                            "final bounds (%.1f,%.1f)-(%.1f,%.1f)\n",
                            (double)finalBounds.left, (double)finalBounds.bottom,
                            (double)finalBounds.right, (double)finalBounds.top);

                    fImageArtHandle = newPlaced;
                    rasterReplaced = true;
                } else {
                    fprintf(stderr, "[TraceModule] ExecPlaceRequest(kForceReplace) failed: %d\n", (int)err);
                }
            } else {
                fprintf(stderr, "[TraceModule] Failed to build CFString for PNG path\n");
            }
        } else if (!rgbaReady) {
            fprintf(stderr, "[TraceModule] Skipping raster replacement: RGBA not ready\n");
        } else if (!fImageArtHandle) {
            fprintf(stderr, "[TraceModule] Skipping raster replacement: no image art handle\n");
        }

        // Clear the preview overlay and instance state
        BridgeSetCutoutPreviewActive(false);
        BridgeSetCutoutPreviewPaths("");
        BridgeSetCutoutInstanceCount(0);
        InvalidateFullView();

        std::string statusMsg = "Cutout committed: " + std::to_string(created) + " cut line(s)";
        if (rasterReplaced) statusMsg += " + transparent raster";
        else if (rgbaReady)  statusMsg += " + cutout PNG";
        BridgeSetTraceStatus(statusMsg);
        fprintf(stderr, "[TraceModule] %s\n", statusMsg.c_str());

        sAIDocument->RedrawDocument();

    } catch (std::exception& ex) {
        fprintf(stderr, "[TraceModule] CommitCutout error: %s\n", ex.what());
        BridgeSetTraceStatus(std::string("Cutout commit failed: ") + ex.what());
    }

    fTraceInProgress = false;
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
