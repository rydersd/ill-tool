//========================================================================================
//
//  TraceSymmetry.cpp — Symmetry axis correction for reference images
//
//  Included by TraceModule.cpp (not a separate compilation unit).
//  Contains: midline-based mirror + gradient seam blend for fixing
//  near-symmetrical Midjourney/AI-generated reference images.
//
//========================================================================================

//========================================================================================
//  GenerateSymmetryPreview — mirror + blend, write preview PNG for overlay
//========================================================================================

void TraceModule::GenerateSymmetryPreview()
{
    fprintf(stderr, "[IllTool Symmetry] GenerateSymmetryPreview: starting\n");

    // --- Get image path (prefer selected placed art, fall back to FindImagePath) ---
    std::string imgPath = FindImagePath();
    if (imgPath.empty()) {
        fprintf(stderr, "[IllTool Symmetry] No image found\n");
        BridgeSetTraceStatus("Symmetry: no image found");
        return;
    }
    fprintf(stderr, "[IllTool Symmetry] Image: %s\n", imgPath.c_str());

    // --- Load image as RGBA ---
    int w = 0, h = 0, channels = 0;
    unsigned char* pixels = stbi_load(imgPath.c_str(), &w, &h, &channels, 4);
    if (!pixels || w < 4 || h < 4) {
        fprintf(stderr, "[IllTool Symmetry] Failed to load image (%dx%d ch=%d)\n", w, h, channels);
        if (pixels) stbi_image_free(pixels);
        BridgeSetTraceStatus("Symmetry: image load failed");
        return;
    }
    fprintf(stderr, "[IllTool Symmetry] Loaded %dx%d (%d channels, forced RGBA)\n", w, h, channels);

    // --- Get parameters ---
    float axisNorm = BridgeGetSymmetryAxisX();
    int   side     = BridgeGetSymmetrySide();   // 0=left is good, 1=right is good
    float blendPct = BridgeGetSymmetryBlendPct();

    int axisX = (int)(axisNorm * w);
    if (axisX < 1) axisX = 1;
    if (axisX >= w - 1) axisX = w - 2;

    int blendWidth = (int)(blendPct * 0.01f * (float)w);
    if (blendWidth < 2) blendWidth = 2;
    if (blendWidth > w / 4) blendWidth = w / 4;

    fprintf(stderr, "[IllTool Symmetry] Axis=%d/%d, side=%s, blend=%dpx (%.1f%%)\n",
            axisX, w, side == 0 ? "left" : "right", blendWidth, blendPct);

    // --- Allocate output buffer ---
    unsigned char* out = (unsigned char*)malloc(w * h * 4);
    if (!out) {
        stbi_image_free(pixels);
        fprintf(stderr, "[IllTool Symmetry] Allocation failed\n");
        return;
    }
    memcpy(out, pixels, w * h * 4);

    // --- Mirror the selected side ---
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int srcX;
            if (side == 0) {
                // Left is good: mirror left side to right
                if (x <= axisX) {
                    srcX = x;  // keep original on left
                } else {
                    srcX = axisX - (x - axisX);  // mirror from left
                    if (srcX < 0) srcX = 0;
                }
            } else {
                // Right is good: mirror right side to left
                if (x >= axisX) {
                    srcX = x;  // keep original on right
                } else {
                    srcX = axisX + (axisX - x);  // mirror from right
                    if (srcX >= w) srcX = w - 1;
                }
            }

            int dstIdx = (y * w + x) * 4;
            int srcIdx = (y * w + srcX) * 4;
            out[dstIdx]     = pixels[srcIdx];
            out[dstIdx + 1] = pixels[srcIdx + 1];
            out[dstIdx + 2] = pixels[srcIdx + 2];
            out[dstIdx + 3] = pixels[srcIdx + 3];
        }
    }

    // --- Gradient seam blend at the axis ---
    // Blend zone: [axisX - blendWidth/2, axisX + blendWidth/2]
    // Alpha ramps from 0 (full mirror) to 1 (full original) across the blend zone
    int blendStart = axisX - blendWidth / 2;
    int blendEnd   = axisX + blendWidth / 2;
    if (blendStart < 0) blendStart = 0;
    if (blendEnd >= w) blendEnd = w - 1;

    for (int y = 0; y < h; y++) {
        for (int x = blendStart; x <= blendEnd; x++) {
            float t = (float)(x - blendStart) / (float)(blendEnd - blendStart);
            // t=0 at blendStart, t=1 at blendEnd
            // For left-good: at axis, we want to blend mirror→original going right
            // For right-good: at axis, we want to blend mirror→original going left
            float origWeight;
            if (side == 0) {
                // Left is good: right side is mirrored. Blend original back near axis on right.
                origWeight = 1.0f - t;  // more original near left, more mirror near right
            } else {
                // Right is good: left side is mirrored. Blend original back near axis on left.
                origWeight = t;  // more mirror near left, more original near right
            }

            // Smooth the transition with smoothstep
            origWeight = origWeight * origWeight * (3.0f - 2.0f * origWeight);

            int idx = (y * w + x) * 4;
            int origIdx = (y * w + x) * 4;
            for (int c = 0; c < 4; c++) {
                float mirrored = (float)out[idx + c];
                float original = (float)pixels[origIdx + c];
                out[idx + c] = (unsigned char)(mirrored * (1.0f - origWeight) + original * origWeight);
            }
        }
    }

    stbi_image_free(pixels);

    // --- Write preview PNG ---
    const char* previewPath = "/tmp/illtool_symmetry_preview.png";
    int ok = stbi_write_png(previewPath, w, h, 4, out, w * 4);
    free(out);

    if (!ok) {
        fprintf(stderr, "[IllTool Symmetry] Failed to write preview PNG\n");
        BridgeSetTraceStatus("Symmetry: preview write failed");
        return;
    }

    fprintf(stderr, "[IllTool Symmetry] Preview written: %s\n", previewPath);
    BridgeSetSymmetryPreviewPath(previewPath);

    // Load preview PNG bytes for annotator overlay
    FILE* f = fopen(previewPath, "rb");
    if (f) {
        fseek(f, 0, SEEK_END);
        long fsize = ftell(f);
        fseek(f, 0, SEEK_SET);
        std::vector<unsigned char> pngData(fsize);
        fread(pngData.data(), 1, fsize, f);
        fclose(f);
        fSymmetryPreviewData = std::move(pngData);
        fprintf(stderr, "[IllTool Symmetry] Preview loaded for overlay (%ld bytes)\n", fsize);
    }

    BridgeSetTraceStatus("Symmetry: preview ready");
    SaveDocState();
    InvalidateFullView();
}

//========================================================================================
//  ExecuteSymmetryCommit — commit the symmetry correction to placed art
//========================================================================================

void TraceModule::ExecuteSymmetryCommit()
{
    fprintf(stderr, "[IllTool Symmetry] CommitSymmetry: starting\n");

    // Use the preview path as output (already generated)
    std::string previewPath = BridgeGetSymmetryPreviewPath();
    if (previewPath.empty()) {
        fprintf(stderr, "[IllTool Symmetry] No preview to commit\n");
        BridgeSetTraceStatus("Symmetry: generate preview first");
        return;
    }

    // --- Find the image art to update (uses same logic as FindImagePath) ---
    std::string origImagePath = FindImagePath();
    if (origImagePath.empty()) {
        fprintf(stderr, "[IllTool Symmetry] No image found for commit\n");
        BridgeSetTraceStatus("Symmetry: no image found");
        return;
    }

    // fImageArtHandle is set by FindImagePath as a side effect
    AIArtHandle placedArt = fImageArtHandle;
    if (!placedArt) {
        fprintf(stderr, "[IllTool Symmetry] No art handle from FindImagePath\n");
        return;
    }

    // Determine art type (placed vs raster)
    ai::int16 artType = kAnyArt;
    ASErr err = kNoErr;
    if (sAIArt) sAIArt->GetArtType(placedArt, &artType);
    bool isPlacedArt = (artType == kPlacedArt);
    fprintf(stderr, "[IllTool Symmetry] Art type: %d (%s)\n", artType,
            isPlacedArt ? "placed" : "raster/other");

    // --- Generate output filename from original path ---
    std::string outputPath;
    {
        size_t dot = origImagePath.rfind('.');
        if (dot != std::string::npos) {
            outputPath = origImagePath.substr(0, dot) + "_sym" + origImagePath.substr(dot);
        } else {
            outputPath = origImagePath + "_sym.png";
        }
    }

    // Copy preview to output location
    std::ifstream src(previewPath, std::ios::binary);
    std::ofstream dst(outputPath, std::ios::binary);
    if (src && dst) {
        dst << src.rdbuf();
        fprintf(stderr, "[IllTool Symmetry] Output saved: %s\n", outputPath.c_str());
    } else {
        fprintf(stderr, "[IllTool Symmetry] Failed to copy preview to output\n");
        return;
    }
    src.close();
    dst.close();

    // --- Relink placed art to the corrected image ---
    CFStringRef cfNewPath = CFStringCreateWithCString(kCFAllocatorDefault,
                                                       outputPath.c_str(),
                                                       kCFStringEncodingUTF8);
    if (!cfNewPath) {
        fprintf(stderr, "[IllTool Symmetry] Failed to create CFString for output path\n");
        return;
    }
    ai::FilePath newFilePath(cfNewPath);
    CFRelease(cfNewPath);

    // --- Replace the image ---
    // Get bounds before any modification
    AIRealRect bounds;
    sAIArt->GetArtBounds(placedArt, &bounds);

    if (isPlacedArt && sAIPlaced) {
        // Try to relink placed art
        err = sAIPlaced->SetPlacedFileSpecification(placedArt, newFilePath);
        fprintf(stderr, "[IllTool Symmetry] SetPlacedFileSpecification err=%d\n", (int)err);
        if (err == kNoErr) {
            AIBoolean updated = false;
            err = sAIArt->UpdateArtworkLink(placedArt, true, &updated);
            fprintf(stderr, "[IllTool Symmetry] UpdateArtworkLink err=%d updated=%d\n",
                    (int)err, (int)updated);
        }
        if (err != kNoErr) {
            // Relink failed — fall through to re-place
            fprintf(stderr, "[IllTool Symmetry] Relink failed, falling back to re-place\n");
            sAIArt->DisposeArt(placedArt);
            PlaceImageAsLayer(outputPath, "Symmetry Corrected",
                              (double)bounds.left, (double)bounds.top,
                              (double)bounds.right, (double)bounds.bottom);
        }
    } else {
        // Raster art or unknown — delete and re-place
        fprintf(stderr, "[IllTool Symmetry] Raster art — replacing via re-place\n");
        sAIArt->DisposeArt(placedArt);
        PlaceImageAsLayer(outputPath, "Symmetry Corrected",
                          (double)bounds.left, (double)bounds.top,
                          (double)bounds.right, (double)bounds.bottom);
    }

    // Clean up state
    BridgeSetSymmetryActive(false);
    fSymmetryPreviewData.clear();
    BridgeSetSymmetryPreviewPath("");
    BridgeSetSymmetryOutputPath(outputPath);
    BridgeSetTraceStatus("Symmetry: correction applied");
    SaveDocState();
    InvalidateFullView();

    fprintf(stderr, "[IllTool Symmetry] CommitSymmetry: done\n");
}
