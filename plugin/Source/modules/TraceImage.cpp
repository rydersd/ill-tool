//========================================================================================
//
//  TraceImage.cpp — Image processing operations (cutout, depth, normals, preprocessing)
//  Part of TraceModule — included from TraceModule.cpp
//
//========================================================================================

//========================================================================================
//  FindOrComputeNormalMap — locate or generate DSINE normal map for the current image
//========================================================================================

std::string TraceModule::FindOrComputeNormalMap(const std::string& imagePath)
{
    // Strategy 0 (ML): If Metric3D v2 is available, use it for high-quality predicted normals
    if (VIHasMetricDepth()) {
        fprintf(stderr, "[TraceModule] Trying Metric3D v2 for normal map...\n");
        BridgeSetTraceStatus("Computing normals (Metric3D v2)...");

        float* depth = nullptr;
        float* normals = nullptr;
        float* confidence = nullptr;
        int nW = 0, nH = 0;

        if (VIEstimateMetricDepth(imagePath.c_str(), &depth, &nW, &nH, &normals, &confidence)) {
            // Save normal map PNG
            std::string normalPath = "/tmp/illtool_metric3d_normals.png";
            if (VISaveNormalMapPNG(normals, nW, nH, normalPath.c_str(), confidence, 0.3f)) {
                fprintf(stderr, "[TraceModule] Metric3D normal map: %dx%d saved to %s\n",
                        nW, nH, normalPath.c_str());
                // Also save depth map for reference
                VISaveDepthMapPNG(depth, nW, nH, "/tmp/illtool_metric3d_depth.png", 0, 0);
                // Persist to project store
                ProjectStore::Instance().SaveNormalMap(normalPath);

                if (depth) free(depth);
                if (normals) free(normals);
                if (confidence) free(confidence);
                return normalPath;
            }
            if (depth) free(depth);
            if (normals) free(normals);
            if (confidence) free(confidence);
        }
        fprintf(stderr, "[TraceModule] Metric3D normal estimation failed, falling back...\n");
    }

    // Strategy 0b: Check project store first (persisted from previous session)
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
    // Prefer the cutout RGBA PNG if available — normals only on the subject, not background
    fprintf(stderr, "[TraceModule] No existing normal map found, computing via C++ Sobel...\n");
    BridgeSetTraceStatus("Computing normal map (C++)...");

    // Check for cutout RGBA — if subject was extracted, use it for cleaner normals
    std::string cutoutPath = "/tmp/illtool_cutout_rgba.png";
    unsigned char* alphaMask = nullptr;
    bool hasCutout = false;

    int grayW = 0, grayH = 0, grayCh = 0;
    unsigned char* gray = nullptr;

    {
        struct stat st;
        if (stat(cutoutPath.c_str(), &st) == 0 && st.st_size > 0) {
            // Load cutout as RGBA to get alpha channel
            int cW = 0, cH = 0, cC = 0;
            unsigned char* rgba = stbi_load(cutoutPath.c_str(), &cW, &cH, &cC, 4);
            if (rgba && cW >= 3 && cH >= 3) {
                grayW = cW;
                grayH = cH;
                gray = (unsigned char*)malloc(grayW * grayH);
                alphaMask = (unsigned char*)malloc(grayW * grayH);

                for (int i = 0; i < grayW * grayH; i++) {
                    // Luminance from RGB
                    int r = rgba[i * 4];
                    int g = rgba[i * 4 + 1];
                    int b = rgba[i * 4 + 2];
                    gray[i] = (unsigned char)((r * 77 + g * 150 + b * 29) >> 8);
                    alphaMask[i] = rgba[i * 4 + 3];

                    // Set transparent pixels to mid-gray to avoid false Sobel edges
                    if (alphaMask[i] < 128) {
                        gray[i] = 128;
                    }
                }

                hasCutout = true;
                fprintf(stderr, "[TraceModule] Using cutout RGBA for normals: %dx%d\n", grayW, grayH);
                stbi_image_free(rgba);
            } else {
                if (rgba) stbi_image_free(rgba);
            }
        }
    }

    // Fallback: load original image as grayscale
    if (!gray) {
        gray = stbi_load(imagePath.c_str(), &grayW, &grayH, &grayCh, 1);
    }

    if (!gray || grayW < 3 || grayH < 3) {
        fprintf(stderr, "[TraceModule] Failed to load image as grayscale for normal map: %s\n",
                imagePath.c_str());
        if (gray) stbi_image_free(gray);
        if (alphaMask) free(alphaMask);
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
                                // Only include opaque pixels in blur when cutout is active
                                if (!alphaMask || alphaMask[ny * grayW + nx] >= 128) {
                                    sum += src[ny * grayW + nx];
                                    count++;
                                }
                            }
                        }
                    }
                    dst[y * grayW + x] = (count > 0)
                        ? (unsigned char)(sum / count)
                        : (unsigned char)128;
                }
            }
        }
        fprintf(stderr, "[TraceModule] Normal pre-blur: sigma=%.1f radius=%d\n", normalBlur, radius);
    }

    double normalStrength = BridgeGetTraceNormalStrength();
    fprintf(stderr, "[TraceModule] Normal strength: %.1f\n", normalStrength);
    unsigned char* normals = VisionEngine::GenerateNormalFromHeight(gray, grayW, grayH, normalStrength);

    // Free grayscale — if it was from cutout it was malloc'd, otherwise stbi_load'd
    if (hasCutout)
        free(gray);
    else
        stbi_image_free(gray);

    if (!normals) {
        fprintf(stderr, "[TraceModule] GenerateNormalFromHeight failed\n");
        if (alphaMask) free(alphaMask);
        return "";
    }

    // If cutout is active, mask out transparent pixels — set to neutral flat normal (128,128,255)
    if (alphaMask) {
        for (int i = 0; i < grayW * grayH; i++) {
            if (alphaMask[i] < 128) {
                normals[i * 3]     = 128;  // nx = 0
                normals[i * 3 + 1] = 128;  // ny = 0
                normals[i * 3 + 2] = 255;  // nz = 1 (flat, facing camera)
            }
        }
        free(alphaMask);
        fprintf(stderr, "[TraceModule] Applied cutout mask to normal map — transparent = flat normal\n");
    }

    std::string resultPath = "/tmp/illtool_height_normal.png";
    int wrote = stbi_write_png(resultPath.c_str(), grayW, grayH, 3, normals, grayW * 3);
    delete[] normals;

    if (!wrote) {
        fprintf(stderr, "[TraceModule] stbi_write_png failed for normal map\n");
        return "";
    }

    fprintf(stderr, "[TraceModule] Generated C++ normal map: %s (%dx%d)%s\n",
            resultPath.c_str(), grayW, grayH, hasCutout ? " (cutout-masked)" : "");

    // Persist to project store for future sessions
    ProjectStore::Instance().SaveNormalMap(resultPath);

    return resultPath;
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

    // Activate IllTool Handle so shift/option click routing works.
    // The cursor shows as an arrow (not crosshair) to avoid confusion.
    // This is required because Illustrator only dispatches mouse events to the active tool.
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

    // Run depth estimation via ONNX backend — model selected by bridge flag
    float* depthMap = nullptr;
    int depthW = 0, depthH = 0;
    bool isMetricDepth = false;

    int depthModel = BridgeGetDepthModel();
    if (depthModel == 1 && VIHasMetricDepth()) {
        // Metric3D v2 — metric depth in meters (also produces normals, ignored here)
        BridgeSetTraceStatus("Analyzing metric depth (Metric3D v2)...");
        if (!VIEstimateMetricDepth(imagePath.c_str(), &depthMap, &depthW, &depthH, nullptr, nullptr)) {
            BridgeSetTraceStatus("Metric depth estimation failed, trying DA V2...");
            // Fall back to Depth Anything V2
            if (!VIEstimateDepth(imagePath.c_str(), &depthMap, &depthW, &depthH)) {
                BridgeSetTraceStatus("Depth estimation failed");
                fTraceInProgress = false;
                return;
            }
        } else {
            isMetricDepth = true;
            // Normalize metric depth to 0-1 for band quantization (same as DA V2 output)
            float minD = 1e30f, maxD = -1e30f;
            int total = depthW * depthH;
            for (int i = 0; i < total; i++) {
                if (depthMap[i] < minD) minD = depthMap[i];
                if (depthMap[i] > maxD) maxD = depthMap[i];
            }
            float range = maxD - minD;
            if (range < 1e-6f) range = 1.0f;
            for (int i = 0; i < total; i++) {
                depthMap[i] = (depthMap[i] - minD) / range;
            }
            fprintf(stderr, "[TraceModule] Metric3D depth normalized: [%.3f, %.3f]m → [0, 1]\n", minD, maxD);
            // Save metric depth visualization
            VISaveDepthMapPNG(depthMap, depthW, depthH, "/tmp/illtool_depth_decompose_metric.png", 0, 1.0f);
        }
    } else {
        // Depth Anything V2 — relative depth (0=near, 1=far)
        if (!VIEstimateDepth(imagePath.c_str(), &depthMap, &depthW, &depthH)) {
            BridgeSetTraceStatus("Depth estimation failed");
            fTraceInProgress = false;
            return;
        }
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
    snprintf(doneBuf, sizeof(doneBuf), "Depth decomposition (%s): %d layers, %d contours",
             isMetricDepth ? "Metric3D" : "DA V2", numLayers, totalContours);
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

    // Refresh image bounds BEFORE any coordinate math — fArt* may be stale/zero
    std::string imagePath = FindImagePath();
    if (imagePath.empty()) return false;

    // Convert artboard coords to normalized image coords (0-1)
    double artW = fArtRight - fArtLeft;
    double artH = fArtTop - fArtBottom;
    if (artW < 1 || artH < 1) return false;

    double normX = (artPt.h - fArtLeft) / artW;
    double normY = (fArtTop - artPt.v) / artH;

    if (normX < 0 || normX > 1 || normY < 0 || normY > 1) return false;

    const char* mode = shiftHeld ? "ADD" : "SUBTRACT";
    fprintf(stderr, "[TraceModule] Cutout %s click at norm(%.3f, %.3f)\n", mode, normX, normY);

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
    int tolSq = tolerance * tolerance;
    int seedIdx = (seedY * imgW + seedX) * 3;
    int seedR = img[seedIdx], seedG = img[seedIdx + 1], seedB = img[seedIdx + 2];

    std::string compositePath2 = "/tmp/illtool_cutout_composite.png";
    int cmpW = 0, cmpH = 0, cmpC = 0;
    unsigned char* existingMask = stbi_load(compositePath2.c_str(), &cmpW, &cmpH, &cmpC, 1);
    bool hasMask = (existingMask && cmpW == imgW && cmpH == imgH);

    // Allow flood to cover a large fraction of the image so users can add/subtract
    // whole background regions in one click. Hard cap prevents OOM on huge sources.
    // At 16M pixels we use ~20 MB for fillMask + visited (bitset) which is safe.
    const int kMaxFloodPixels = 16 * 1024 * 1024;  // ~16 megapixels
    int maxFill = std::min(imgW * imgH, kMaxFloodPixels);
    int maxRadius = std::max(imgW, imgH);  // effectively no radius cap
    int maxRadiusSq = maxRadius * maxRadius;

    std::vector<unsigned char> fillMask(imgW * imgH, 0);
    std::vector<bool> visited(imgW * imgH, false);
    std::vector<std::pair<int,int>> fillStack;
    fillStack.push_back({seedX, seedY});
    visited[seedY * imgW + seedX] = true;
    int filledPixels = 0;

    while (!fillStack.empty() && filledPixels < maxFill) {
        auto [cx, cy] = fillStack.back();
        fillStack.pop_back();

        int dx2 = cx - seedX, dy2 = cy - seedY;
        if (dx2 * dx2 + dy2 * dy2 > maxRadiusSq) continue;

        if (hasMask) {
            bool inMask = (existingMask[cy * imgW + cx] > 128);
            if (!shiftHeld && !inMask) continue;   // subtract: skip pixels already outside
            if (shiftHeld && inMask) continue;      // add: skip pixels already inside
        }

        int pIdx = (cy * imgW + cx) * 3;
        int dr = (int)img[pIdx] - seedR;
        int dg = (int)img[pIdx + 1] - seedG;
        int db = (int)img[pIdx + 2] - seedB;
        int distSq = dr * dr + dg * dg + db * db;
        if (distSq > tolSq) continue;

        fillMask[cy * imgW + cx] = 255;
        filledPixels++;

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
    if (existingMask) stbi_image_free(existingMask);

    fprintf(stderr, "[TraceModule] Flood fill: %d pixels, threshold=%d, mode=%s\n",
            filledPixels, tolerance, mode);

    if (filledPixels == 0) return true;

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
    }

    // Apply: Shift=ADD to selection (Adobe convention), Option=SUBTRACT from selection
    for (int i = 0; i < imgW * imgH; i++) {
        if (fillMask[i] > 0) {
            if (shiftHeld) {
                composite[i] = 255;  // shift: add to selection (Adobe convention)
            } else {
                composite[i] = 0;    // option: subtract from selection
            }
        }
    }

    // Count total white pixels in composite before and after
    int whiteCount = 0;
    for (int i = 0; i < imgW * imgH; i++) {
        if (composite[i] > 128) whiteCount++;
    }

    // Write updated composite — guard against write failure
    int wrote = stbi_write_png(compositePath.c_str(), imgW, imgH, 1, composite, imgW);
    if (!wrote) {
        fprintf(stderr, "[TraceModule] FAILED to write composite mask to %s\n", compositePath.c_str());
        if (createdNew) free(composite);
        else stbi_image_free(composite);
        return true;  // consumed click but can't proceed
    }
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

    // Defer annotator redraw to the next timer tick (~100ms).
    // Synchronous InvalidateFullView/RedrawDocument inside ToolMouseDown has no effect
    // because the SDK defers annotator repaints until the handler returns.
    // SetDirty(true) causes ProcessOperationQueue (10Hz timer) to call InvalidateFullView
    // in SDK message context where annotator invalidation actually takes effect.
    SetDirty(true);

    fprintf(stderr, "[TraceModule] Cutout %s complete, re-traced (speckle capped at 10)\n", mode);
    return true;
}

//========================================================================================
//  GeneratePreprocessPreview — render the preprocessing chain to a PNG overlay
//  Shows what the tracing algorithm will see before running the full trace.
//  Output mode determines the preprocessing chain:
//    0 (Outline) : Canny edge detection
//    1 (Fill)    : Grayscale (no edges)
//    2 (Centerline) : Canny → dilation → skeletonization
//========================================================================================

void TraceModule::GeneratePreprocessPreview()
{
    // Toggle off if already showing
    if (BridgeGetPreprocessPreviewActive()) {
        BridgeSetPreprocessPreviewActive(false);
        BridgeSetPreprocessPreviewData({});
        BridgeSetTraceStatus("Preview cleared");
        InvalidateFullView();
        fprintf(stderr, "[TraceModule] Preprocess preview cleared\n");
        return;
    }

    BridgeSetTraceStatus("Generating preview...");

    std::string imagePath = FindImagePath();
    if (imagePath.empty()) {
        BridgeSetTraceStatus("No image found — use File > Place to add a linked image");
        fprintf(stderr, "[TraceModule] PreprocessPreview: no image path found\n");
        return;
    }

    fprintf(stderr, "[TraceModule] PreprocessPreview: loading %s\n", imagePath.c_str());

    // Load the image as grayscale
    int imgW = 0, imgH = 0, imgC = 0;
    unsigned char* gray = stbi_load(imagePath.c_str(), &imgW, &imgH, &imgC, 1);
    if (!gray || imgW <= 0 || imgH <= 0) {
        BridgeSetTraceStatus("Failed to load image for preview");
        if (gray) stbi_image_free(gray);
        return;
    }

    int outputMode = BridgeGetTraceOutputMode();  // 0=outline, 1=fill, 2=centerline

    // Result buffer — single-channel grayscale, will be converted to PNG at the end
    std::vector<unsigned char> result(imgW * imgH, 0);

    if (outputMode == 1) {
        // --- Fill mode: just show grayscale ---
        memcpy(result.data(), gray, imgW * imgH);
        fprintf(stderr, "[TraceModule] PreprocessPreview: fill mode (grayscale)\n");

    } else {
        // --- Outline or Centerline: run Canny edge detection ---
        double cannyLow  = BridgeGetTraceCannyLow();
        double cannyHigh = BridgeGetTraceCannyHigh();

        VisionEngine& ve = VisionEngine::Instance();
        ve.LoadImage(imagePath.c_str());
        auto edges = ve.CannyEdges(cannyLow, cannyHigh);

        if (edges.empty() || (int)edges.size() != imgW * imgH) {
            fprintf(stderr, "[TraceModule] PreprocessPreview: Canny failed (got %d, expected %d)\n",
                    (int)edges.size(), imgW * imgH);
            BridgeSetTraceStatus("Edge detection failed");
            stbi_image_free(gray);
            return;
        }

        if (outputMode == 0) {
            // --- Outline mode: just Canny edges ---
            memcpy(result.data(), edges.data(), imgW * imgH);
            fprintf(stderr, "[TraceModule] PreprocessPreview: outline mode (Canny low=%.0f high=%.0f)\n",
                    cannyLow, cannyHigh);

        } else {
            // --- Centerline mode: Canny → dilation → morphological close → skeletonize ---
            int dilRad = BridgeGetTraceDilationRadius();

            // Step 1: Dilate edges
            std::vector<unsigned char> dilated(imgW * imgH, 0);
            if (dilRad <= 0) {
                memcpy(dilated.data(), edges.data(), imgW * imgH);
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

            // Step 2: Morphological close (erode dilated result)
            std::vector<unsigned char> closed(imgW * imgH, 0);
            for (int y = 1; y < imgH - 1; y++) {
                for (int x = 1; x < imgW - 1; x++) {
                    if (dilated[y * imgW + x] > 0 &&
                        dilated[(y-1) * imgW + x] > 0 &&
                        dilated[(y+1) * imgW + x] > 0 &&
                        dilated[y * imgW + (x-1)] > 0 &&
                        dilated[y * imgW + (x+1)] > 0) {
                        closed[y * imgW + x] = 255;
                    }
                }
            }

            // Step 3: Invert for skeletonization (expects dark=foreground)
            std::vector<unsigned char> inverted(imgW * imgH);
            for (int i = 0; i < imgW * imgH; i++) {
                inverted[i] = (closed[i] > 0) ? 0 : 255;
            }

            // Step 4: Skeletonize
            int skelThresh = BridgeGetTraceSkeletonThresh();
            unsigned char* skeleton = VisionEngine::Skeletonize(inverted.data(), imgW, imgH, skelThresh);

            if (skeleton) {
                memcpy(result.data(), skeleton, imgW * imgH);
                delete[] skeleton;
            } else {
                // Fallback: show the closed edges
                memcpy(result.data(), closed.data(), imgW * imgH);
            }

            fprintf(stderr, "[TraceModule] PreprocessPreview: centerline mode "
                    "(canny=[%.0f,%.0f] dil=%d skel=%d)\n",
                    cannyLow, cannyHigh, dilRad, skelThresh);
        }
    }

    stbi_image_free(gray);

    // Apply pre-blur if enabled (same logic as normal map pre-blur)
    double normalBlur = BridgeGetTraceNormalBlur();
    if (normalBlur > 0.1 && outputMode == 1) {
        int radius = (int)(normalBlur * 2);
        if (radius < 1) radius = 1;
        if (radius > 10) radius = 10;

        std::vector<unsigned char> temp(imgW * imgH);
        for (int pass = 0; pass < 2; pass++) {
            unsigned char* src = (pass == 0) ? result.data() : temp.data();
            unsigned char* dst = (pass == 0) ? temp.data() : result.data();
            for (int y = 0; y < imgH; y++) {
                for (int x = 0; x < imgW; x++) {
                    int sum = 0, count = 0;
                    for (int dy = -radius; dy <= radius; dy++) {
                        for (int dx = -radius; dx <= radius; dx++) {
                            int ny = y + dy, nx = x + dx;
                            if (ny >= 0 && ny < imgH && nx >= 0 && nx < imgW) {
                                sum += src[ny * imgW + nx];
                                count++;
                            }
                        }
                    }
                    dst[y * imgW + x] = (count > 0) ? (unsigned char)(sum / count) : 128;
                }
            }
        }
        fprintf(stderr, "[TraceModule] PreprocessPreview: applied blur sigma=%.1f radius=%d\n",
                normalBlur, radius);
    }

    // Encode the grayscale result as PNG into memory using stbi_write_png_to_mem
    // stb_image_write doesn't have a to-memory function, so write to /tmp and read back
    const char* previewPath = "/tmp/illtool_preprocess_preview.png";
    int wrote = stbi_write_png(previewPath, imgW, imgH, 1, result.data(), imgW);
    if (!wrote) {
        BridgeSetTraceStatus("Failed to write preview PNG");
        fprintf(stderr, "[TraceModule] PreprocessPreview: stbi_write_png failed\n");
        return;
    }

    // Read the PNG file back into memory for the annotator DrawPNGImage API
    FILE* f = fopen(previewPath, "rb");
    if (!f) {
        BridgeSetTraceStatus("Failed to read preview PNG");
        return;
    }
    fseek(f, 0, SEEK_END);
    long fileSize = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::vector<unsigned char> pngData(fileSize);
    fread(pngData.data(), 1, fileSize, f);
    fclose(f);

    // Store in bridge state and activate overlay
    BridgeSetPreprocessPreviewData(pngData);
    BridgeSetPreprocessPreviewActive(true);

    // Force annotator redraw
    InvalidateFullView();

    const char* modeNames[] = {"outline", "fill", "centerline"};
    const char* modeName = (outputMode >= 0 && outputMode <= 2) ? modeNames[outputMode] : "unknown";
    char statusBuf[256];
    snprintf(statusBuf, sizeof(statusBuf), "Preview (%s) — %dx%d — click Preview again to clear",
             modeName, imgW, imgH);
    BridgeSetTraceStatus(statusBuf);
    fprintf(stderr, "[TraceModule] PreprocessPreview: %s %dx%d (%.1f KB PNG)\n",
            modeName, imgW, imgH, fileSize / 1024.0);
}

