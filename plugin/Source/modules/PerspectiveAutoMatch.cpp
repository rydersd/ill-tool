//========================================================================================
//
//  PerspectiveAutoMatch.cpp — Auto VP detection, presets, perspective transforms
//
//  Included by PerspectiveModule.cpp (not a separate compilation unit).
//  Contains: AutoMatchPerspective (Hough + normals VP detection pipeline),
//  preset save/load/list, and perspective transform operations
//  (mirror/duplicate/paste in perspective).
//
//========================================================================================

extern IllToolPlugin* gPlugin;

//========================================================================================
//  Auto Match Perspective — detect VPs from placed reference image
//========================================================================================

void PerspectiveModule::AutoMatchPerspective()
{
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: starting\n");

    // --- Find the first placed art in the document ---
    if (!sAIMatchingArt || !sAIArt || !sAIPlaced) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: missing suites (matching=%p art=%p placed=%p)\n",
                (void*)sAIMatchingArt, (void*)sAIArt, (void*)sAIPlaced);
        return;
    }

    // Search for placed art (linked images)
    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    AIMatchingArtSpec spec;
    spec.type = kPlacedArt;
    spec.whichAttr = 0;
    spec.attr = 0;
    ASErr err = sAIMatchingArt->GetMatchingArt(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0 || !matches) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: no placed art found (err=%d count=%d)\n",
                (int)err, (int)numMatches);
        return;
    }

    // Use the first placed art
    AIArtHandle placedArt = (*matches)[0];
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: found %d placed art(s), using first\n",
            (int)numMatches);

    // --- Get the linked file path ---
    ai::FilePath filePath;
    err = sAIPlaced->GetPlacedFileSpecification(placedArt, filePath);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get file spec (err=%d)\n", (int)err);
        return;
    }

    // Convert FilePath to POSIX path via CFStringRef (avoids ai::UnicodeString linker dependency)
    CFStringRef cfPath = filePath.GetAsCFString();
    if (!cfPath) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: GetAsCFString returned null\n");
        return;
    }
    char pathBuf[2048];
    if (!CFStringGetCString(cfPath, pathBuf, sizeof(pathBuf), kCFStringEncodingUTF8)) {
        CFRelease(cfPath);
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to convert path to UTF8\n");
        return;
    }
    CFRelease(cfPath);
    std::string pathCStr(pathBuf);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: placed image path: %s\n", pathCStr.c_str());

    // --- Get the placed art bounds (artwork coordinates) ---
    AIRealRect artBounds = {0, 0, 0, 0};
    err = sAIArt->GetArtBounds(placedArt, &artBounds);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get art bounds (err=%d)\n", (int)err);
        return;
    }
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: art bounds L=%.1f T=%.1f R=%.1f B=%.1f\n",
            (double)artBounds.left, (double)artBounds.top,
            (double)artBounds.right, (double)artBounds.bottom);

    // --- Get the placed art transform matrix ---
    AIRealMatrix placedMatrix;
    err = sAIPlaced->GetPlacedMatrix(placedArt, &placedMatrix);
    if (err != kNoErr) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to get placed matrix (err=%d)\n", (int)err);
        // Fall back to using art bounds for coordinate mapping
    }

    // --- Load image into VisionEngine ---
    VisionEngine& ve = VisionEngine::Instance();
    if (!ve.LoadImage(pathCStr.c_str())) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: failed to load image\n");
        return;
    }

    int imgW = ve.Width();
    int imgH = ve.Height();
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: loaded image %dx%d\n", imgW, imgH);

    // Set up coordinate mapping for pixel <-> artwork conversion
    ve.SetArtToPixelMapping(
        (double)artBounds.left, (double)artBounds.top,
        (double)artBounds.right, (double)artBounds.bottom);

    // --- Estimate vanishing points using dual approach ---
    // Method 1: Hough line convergence (traditional)
    auto houghVPs = ve.EstimateVanishingPoints(2, 50.0, 150.0, 30);

    // Method 2: Normal direction clustering (surface-aware)
    auto normalVPs = ve.EstimateVPsFromNormals(2);

    // Method 3: Surface type analysis for confidence weighting
    auto surfaceHint = ve.InferSurfaceType(0, 0, imgW, imgH);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: surface=%d conf=%.2f angle=%.1f°\n",
            (int)surfaceHint.type, surfaceHint.confidence,
            surfaceHint.gradientAngle * 180.0 / M_PI);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: Hough found %d VPs, Normals found %d VPs\n",
            (int)houghVPs.size(), (int)normalVPs.size());

    // Combine: prefer Hough VPs (more precise position), but use normal VPs as fallback
    // or to validate Hough results. Weight by surface confidence.
    std::vector<VisionEngine::VanishingPointEstimate> vps;

    if (houghVPs.size() >= 2) {
        // Hough found enough — use them, boost confidence if normals agree
        vps = houghVPs;
        for (auto& vp : vps) {
            // Check if any normal VP has a similar angle (within 15 degrees)
            for (auto& nvp : normalVPs) {
                double angleDiff = std::abs(vp.dominantAngle - nvp.dominantAngle);
                if (angleDiff > M_PI) angleDiff = 2.0 * M_PI - angleDiff;
                if (angleDiff < M_PI / 12.0) {  // within 15 degrees
                    vp.confidence = std::min(1.0, vp.confidence * 1.5);  // boost
                    fprintf(stderr, "[IllTool PerspModule] VP angle %.1f° confirmed by normals (boosted)\n",
                            vp.dominantAngle * 180.0 / M_PI);
                    break;
                }
            }
        }
    } else if (normalVPs.size() >= 2) {
        // Hough failed but normals found planes — use normal-derived VPs
        vps = normalVPs;
        fprintf(stderr, "[IllTool PerspModule] Using normal-derived VPs (Hough insufficient)\n");
    } else if (houghVPs.size() == 1 && normalVPs.size() >= 1) {
        // Combine: one from each
        vps.push_back(houghVPs[0]);
        vps.push_back(normalVPs[0]);
        fprintf(stderr, "[IllTool PerspModule] Combining 1 Hough + 1 Normal VP\n");
    } else {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: insufficient VPs (Hough=%d Normal=%d)\n",
                (int)houghVPs.size(), (int)normalVPs.size());
        return;
    }

    if (vps.size() < 2) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: only %d VP(s) after combining, need 2\n",
                (int)vps.size());
        return;
    }

    // --- Convert VP pixel coordinates to artwork coordinates ---
    // Pixel (0,0) = top-left, artwork uses Y-up from artBounds
    double artW = (double)(artBounds.right - artBounds.left);
    double artH = (double)(artBounds.top - artBounds.bottom);  // Y-up: top > bottom
    double scaleX = artW / (double)imgW;
    double scaleY = artH / (double)imgH;

    // Convert pixel VP to artwork coordinates
    // px -> art:  artX = artBounds.left + px * scaleX
    //             artY = artBounds.top  - py * scaleY  (flip Y)
    auto pixToArt = [&](double px, double py, double& ax, double& ay) {
        ax = (double)artBounds.left + px * scaleX;
        ay = (double)artBounds.top  - py * scaleY;
    };

    double vp1ArtX, vp1ArtY, vp2ArtX, vp2ArtY;
    pixToArt(vps[0].x, vps[0].y, vp1ArtX, vp1ArtY);
    pixToArt(vps[1].x, vps[1].y, vp2ArtX, vp2ArtY);

    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 art=(%.1f, %.1f) VP2 art=(%.1f, %.1f)\n",
            vp1ArtX, vp1ArtY, vp2ArtX, vp2ArtY);

    // --- Set up perspective grid handles ---
    // For each VP, create a line from the image center toward the VP.
    // The handle1 is near the image center, handle2 extends toward the VP.
    double imgCenterPx = imgW * 0.5;
    double imgCenterPy = imgH * 0.5;
    double centerArtX, centerArtY;
    pixToArt(imgCenterPx, imgCenterPy, centerArtX, centerArtY);

    // VP1 line: from image center toward VP1
    double dir1X = vp1ArtX - centerArtX;
    double dir1Y = vp1ArtY - centerArtY;
    double len1 = std::sqrt(dir1X * dir1X + dir1Y * dir1Y);
    if (len1 < 1e-6) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 too close to center\n");
        return;
    }
    // Handle2 is 30% of the way from center to VP
    double h2_1x = centerArtX + dir1X * 0.3;
    double h2_1y = centerArtY + dir1Y * 0.3;

    // VP2 line: from image center toward VP2
    double dir2X = vp2ArtX - centerArtX;
    double dir2Y = vp2ArtY - centerArtY;
    double len2 = std::sqrt(dir2X * dir2X + dir2Y * dir2Y);
    if (len2 < 1e-6) {
        fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP2 too close to center\n");
        return;
    }
    double h2_2x = centerArtX + dir2X * 0.3;
    double h2_2y = centerArtY + dir2Y * 0.3;

    // Clear existing grid
    fGrid.Clear();
    for (int i = 0; i < 3; i++) BridgeClearPerspectiveLine(i);

    // Set VP1 (left VP)
    fGrid.leftVP.handle1.h = (AIReal)centerArtX;
    fGrid.leftVP.handle1.v = (AIReal)centerArtY;
    fGrid.leftVP.handle2.h = (AIReal)h2_1x;
    fGrid.leftVP.handle2.v = (AIReal)h2_1y;
    fGrid.leftVP.active = true;
    BridgeSetPerspectiveLine(0, centerArtX, centerArtY, h2_1x, h2_1y);

    // Set VP2 (right VP)
    fGrid.rightVP.handle1.h = (AIReal)centerArtX;
    fGrid.rightVP.handle1.v = (AIReal)centerArtY;
    fGrid.rightVP.handle2.h = (AIReal)h2_2x;
    fGrid.rightVP.handle2.v = (AIReal)h2_2y;
    fGrid.rightVP.active = true;
    BridgeSetPerspectiveLine(1, centerArtX, centerArtY, h2_2x, h2_2y);

    // Estimate horizon Y from the two VPs:
    // If both VPs are at roughly the same Y, that is the horizon.
    // Otherwise, average the VP Y coordinates.
    double avgVpY = (vp1ArtY + vp2ArtY) * 0.5;
    fGrid.horizonY = avgVpY;
    BridgeSetHorizonY(avgVpY);

    // Make grid visible
    fGrid.visible = true;
    BridgeSetPerspectiveVisible(true);

    fGrid.Recompute();
    InvalidateFullView();

    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: grid set with 2 VPs, horizon=%.1f\n",
            fGrid.horizonY);
    fprintf(stderr, "[IllTool PerspModule] AutoMatchPerspective: VP1 conf=%.2f (%d lines), VP2 conf=%.2f (%d lines)\n",
            vps[0].confidence, vps[0].lineCount, vps[1].confidence, vps[1].lineCount);
}

//========================================================================================
//  Preset Save/Load — named presets stored in document dictionary
//========================================================================================

void PerspectiveModule::SavePreset(const std::string& name)
{
    if (!sAIDictionary || !sAIArt) return;
    if (name.empty()) {
        fprintf(stderr, "[IllTool PerspModule] SavePreset: empty name\n");
        return;
    }

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) marker = CreatePerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] SavePreset: no marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    // Build key prefix: "IllToolPerspPreset_<name>_"
    std::string prefix = "IllToolPerspPreset_" + name + "_";

    // Store a marker so we can enumerate presets later
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "exists").c_str()), true);

    // Save grid values with preset prefix
    sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((prefix + "horizonY").c_str()), (AIReal)fGrid.horizonY);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "locked").c_str()), fGrid.locked);
    sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((prefix + "visible").c_str()), fGrid.visible);
    sAIDictionary->SetIntegerEntry(dict, sAIDictionary->Key((prefix + "density").c_str()), (ai::int32)fGrid.gridDensity);

    const PerspectiveLine* lines[3] = {&fGrid.leftVP, &fGrid.rightVP, &fGrid.verticalVP};
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        char idx[4]; snprintf(idx, sizeof(idx), "L%d", i);
        std::string lp = prefix + idx;

        sAIDictionary->SetBooleanEntry(dict, sAIDictionary->Key((lp + "_active").c_str()), line.active);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h1x").c_str()), line.handle1.h);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h1y").c_str()), line.handle1.v);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h2x").c_str()), line.handle2.h);
        sAIDictionary->SetRealEntry(dict, sAIDictionary->Key((lp + "_h2y").c_str()), line.handle2.v);
    }

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool PerspModule] SavePreset '%s': saved %d lines, horizon=%.0f\n",
            name.c_str(), fGrid.ActiveLineCount(), fGrid.horizonY);
}

void PerspectiveModule::LoadPreset(const std::string& name)
{
    if (!sAIDictionary || !sAIArt) return;
    if (name.empty()) return;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) {
        fprintf(stderr, "[IllTool PerspModule] LoadPreset: no marker art\n");
        return;
    }

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return;

    std::string prefix = "IllToolPerspPreset_" + name + "_";

    // Check that preset exists
    AIBoolean exists = false;
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "exists").c_str()), &exists);
    if (!exists) {
        sAIDictionary->Release(dict);
        fprintf(stderr, "[IllTool PerspModule] LoadPreset '%s': not found\n", name.c_str());
        return;
    }

    // Load grid values
    AIReal hY = 400;
    sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((prefix + "horizonY").c_str()), &hY);
    fGrid.horizonY = (double)hY;

    AIBoolean bLocked = false, bVisible = true;
    sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "locked").c_str()), &bLocked);
    fGrid.locked = bLocked;

    if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((prefix + "visible").c_str()), &bVisible) == kNoErr)
        fGrid.visible = bVisible;
    else
        fGrid.visible = true;

    ai::int32 dens = 5;
    sAIDictionary->GetIntegerEntry(dict, sAIDictionary->Key((prefix + "density").c_str()), &dens);
    fGrid.gridDensity = (int)dens;

    PerspectiveLine* lines[3] = {&fGrid.leftVP, &fGrid.rightVP, &fGrid.verticalVP};
    for (int i = 0; i < 3; i++) {
        PerspectiveLine& line = *lines[i];
        char idx[4]; snprintf(idx, sizeof(idx), "L%d", i);
        std::string lp = prefix + idx;

        AIBoolean bActive = false;
        sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key((lp + "_active").c_str()), &bActive);
        line.active = bActive;

        if (line.active) {
            AIReal val = 0;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h1x").c_str()), &val); line.handle1.h = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h1y").c_str()), &val); line.handle1.v = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h2x").c_str()), &val); line.handle2.h = val;
            sAIDictionary->GetRealEntry(dict, sAIDictionary->Key((lp + "_h2y").c_str()), &val); line.handle2.v = val;
        }
    }

    sAIDictionary->Release(dict);

    // Recompute and sync to bridge
    fGrid.Recompute();
    for (int i = 0; i < 3; i++) {
        const PerspectiveLine& line = *lines[i];
        if (line.active) {
            BridgeSetPerspectiveLine(i, line.handle1.h, line.handle1.v,
                                        line.handle2.h, line.handle2.v);
        } else {
            BridgeClearPerspectiveLine(i);
        }
    }
    BridgeSetHorizonY(fGrid.horizonY);
    BridgeSetPerspectiveLocked(fGrid.locked);
    BridgeSetPerspectiveVisible(fGrid.visible);
    InvalidateFullView();

    fprintf(stderr, "[IllTool PerspModule] LoadPreset '%s': loaded %d lines, horizon=%.0f\n",
            name.c_str(), fGrid.ActiveLineCount(), fGrid.horizonY);
}

std::vector<std::string> PerspectiveModule::ListPresets()
{
    std::vector<std::string> names;
    if (!sAIDictionary || !sAIArt) return names;

    AIArtHandle marker = FindPerspMarkerArt();
    if (!marker) return names;

    AIDictionaryRef dict = nullptr;
    ASErr err = sAIArt->GetDictionary(marker, &dict);
    if (err != kNoErr || !dict) return names;

    // Scan up to 20 well-known preset slots
    for (int i = 1; i <= 20; i++) {
        char nameBuf[32];
        snprintf(nameBuf, sizeof(nameBuf), "preset%d", i);
        std::string prefix = std::string("IllToolPerspPreset_") + nameBuf + "_exists";
        AIBoolean exists = false;
        if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(prefix.c_str()), &exists) == kNoErr && exists) {
            names.push_back(nameBuf);
        }
    }
    // Also check named presets with common names
    const char* commonNames[] = {"default", "low", "high", "bird", "worm"};
    for (const char* cn : commonNames) {
        std::string prefix = std::string("IllToolPerspPreset_") + cn + "_exists";
        AIBoolean exists = false;
        if (sAIDictionary->GetBooleanEntry(dict, sAIDictionary->Key(prefix.c_str()), &exists) == kNoErr && exists) {
            // Avoid duplicates
            bool found = false;
            for (const auto& n : names) { if (n == cn) { found = true; break; } }
            if (!found) names.push_back(cn);
        }
    }

    sAIDictionary->Release(dict);
    fprintf(stderr, "[IllTool PerspModule] ListPresets: %zu presets found\n", names.size());
    return names;
}

//========================================================================================
//  Homography math helpers (3x3 matrix operations)
//========================================================================================

/** Invert a 3x3 matrix. Returns false if singular. */
static bool InvertMatrix3x3(const double M[9], double Minv[9])
{
    double det = M[0] * (M[4] * M[8] - M[5] * M[7])
               - M[1] * (M[3] * M[8] - M[5] * M[6])
               + M[2] * (M[3] * M[7] - M[4] * M[6]);
    if (std::abs(det) < 1e-15) return false;

    double invDet = 1.0 / det;
    Minv[0] =  (M[4] * M[8] - M[5] * M[7]) * invDet;
    Minv[1] = -(M[1] * M[8] - M[2] * M[7]) * invDet;
    Minv[2] =  (M[1] * M[5] - M[2] * M[4]) * invDet;
    Minv[3] = -(M[3] * M[8] - M[5] * M[6]) * invDet;
    Minv[4] =  (M[0] * M[8] - M[2] * M[6]) * invDet;
    Minv[5] = -(M[0] * M[5] - M[2] * M[3]) * invDet;
    Minv[6] =  (M[3] * M[7] - M[4] * M[6]) * invDet;
    Minv[7] = -(M[0] * M[7] - M[1] * M[6]) * invDet;
    Minv[8] =  (M[0] * M[4] - M[1] * M[3]) * invDet;
    return true;
}

/** Apply a 3x3 homography to a 2D point. Returns the projected result. */
static AIRealPoint ApplyHomography(const double H[9], AIRealPoint pt)
{
    double x = pt.h, y = pt.v;
    double w = H[6] * x + H[7] * y + H[8];
    if (std::abs(w) < 1e-15) return pt;
    AIRealPoint result;
    result.h = (AIReal)((H[0] * x + H[1] * y + H[2]) / w);
    result.v = (AIReal)((H[3] * x + H[4] * y + H[5]) / w);
    return result;
}

/** Build a wall-plane homography (left wall or right wall). */
static bool ComputeWallHomography(const PerspectiveModule::PerspectiveGrid& grid, int plane, double matrix[9])
{
    if (!grid.ComputeFloorHomography(matrix)) return false;

    double cx = (grid.computedVP1.h + grid.computedVP2.h) * 0.5;
    double span = std::abs(grid.computedVP2.h - grid.computedVP1.h);
    if (span < 1.0) span = 1.0;
    double halfSpan = span * 0.25;

    double wallWidth = halfSpan * 0.8;
    double wallHeight = halfSpan * 1.0;
    double farScale = 0.7;

    double p0x, p0y, p1x, p1y, p2x, p2y, p3x, p3y;
    if (plane == 1) {
        // Left wall
        p0x = cx;                   p0y = grid.horizonY;
        p1x = cx - wallWidth;       p1y = grid.horizonY;
        p2x = cx - wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale;
        p3x = cx;                   p3y = grid.horizonY + wallHeight;
    } else {
        // Right wall
        p0x = cx;                   p0y = grid.horizonY;
        p1x = cx + wallWidth;       p1y = grid.horizonY;
        p2x = cx + wallWidth * farScale; p2y = grid.horizonY + wallHeight * farScale;
        p3x = cx;                   p3y = grid.horizonY + wallHeight;
    }

    double dx1 = p1x - p2x, dy1 = p1y - p2y;
    double dx2 = p3x - p2x, dy2 = p3y - p2y;
    double dx3 = p0x - p1x + p2x - p3x;
    double dy3 = p0y - p1y + p2y - p3y;

    double denom = dx1 * dy2 - dx2 * dy1;
    if (std::abs(denom) < 1e-12) return false;

    double g = (dx3 * dy2 - dx2 * dy3) / denom;
    double h = (dx1 * dy3 - dx3 * dy1) / denom;

    matrix[0] = p1x - p0x + g * p1x;
    matrix[1] = p3x - p0x + h * p3x;
    matrix[2] = p0x;
    matrix[3] = p1y - p0y + g * p1y;
    matrix[4] = p3y - p0y + h * p3y;
    matrix[5] = p0y;
    matrix[6] = g;
    matrix[7] = h;
    matrix[8] = 1.0;

    return true;
}

/** Get selected path art handles using isolation-aware matching. */
static bool GetSelectedPaths(AIArtHandle** &matches, ai::int32 &numMatches)
{
    AIMatchingArtSpec spec;
    spec.type = kPathArt;
    spec.whichAttr = kArtSelected;
    spec.attr = kArtSelected;
    ASErr err = GetMatchingArtIsolationAware(&spec, 1, &matches, &numMatches);
    if (err != kNoErr || numMatches == 0) {
        matches = nullptr;
        numMatches = 0;
        return false;
    }
    return true;
}

//========================================================================================
//  Mirror in Perspective
//========================================================================================

void PerspectiveModule::MirrorInPerspective(int axis, bool replace)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: missing suites\n");
        return;
    }

    double H[9], Hinv[9];
    if (!fGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: no selected paths\n");
        return;
    }

    bool axisVertical = (axis == 0);

    fUndoStack.PushFrame();
    int mirroredCount = 0;

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        // Transform each segment through H -> mirror -> Hinv
        std::vector<AIPathSegment> mirroredSegs(segCount);
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& mir = mirroredSegs[s];

            AIRealPoint pAnchor = ApplyHomography(Hinv, orig.p);
            if (axisVertical) pAnchor.h = -pAnchor.h;
            else              pAnchor.v = -pAnchor.v;
            mir.p = ApplyHomography(H, pAnchor);

            AIRealPoint inPt = {orig.in.h, orig.in.v};
            AIRealPoint inPersp = ApplyHomography(Hinv, inPt);
            if (axisVertical) inPersp.h = -inPersp.h;
            else              inPersp.v = -inPersp.v;
            mir.in = ApplyHomography(H, inPersp);

            AIRealPoint outPt = {orig.out.h, orig.out.v};
            AIRealPoint outPersp = ApplyHomography(Hinv, outPt);
            if (axisVertical) outPersp.h = -outPersp.h;
            else              outPersp.v = -outPersp.v;
            mir.out = ApplyHomography(H, outPersp);

            mir.corner = orig.corner;
        }

        // Reverse segment order so winding stays consistent
        std::vector<AIPathSegment> reversed(segCount);
        for (int s = 0; s < segCount; s++) {
            int ri = segCount - 1 - s;
            reversed[s].p   = mirroredSegs[ri].p;
            reversed[s].in  = mirroredSegs[ri].out;
            reversed[s].out = mirroredSegs[ri].in;
            reversed[s].corner = mirroredSegs[ri].corner;
        }

        if (replace) {
            fUndoStack.SnapshotPath(art);
            sAIPath->SetPathSegments(art, 0, segCount, reversed.data());
        } else {
            AIArtHandle newArt = nullptr;
            ASErr dupErr = sAIArt->DuplicateArt(art, kPlaceAbove, art, &newArt);
            if (dupErr == kNoErr && newArt) {
                sAIPath->SetPathSegments(newArt, 0, segCount, reversed.data());
                AIPathStyle style;
                AIBoolean hasAdvFill = false;
                if (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr) {
                    sAIPathStyle->SetPathStyle(newArt, &style);
                }
                mirroredCount++;
            }
        }
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool PerspModule] MirrorInPerspective: %s %d paths, axis=%s\n",
            replace ? "replaced" : "created", replace ? numMatches : mirroredCount,
            axisVertical ? "vertical" : "horizontal");

    InvalidateFullView();
}

//========================================================================================
//  Duplicate in Perspective
//========================================================================================

void PerspectiveModule::DuplicateInPerspective(int count, int spacing)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: missing suites\n");
        return;
    }
    if (count < 1) count = 1;
    if (count > 50) count = 50;

    double H[9], Hinv[9];
    if (!fGrid.ComputeFloorHomography(H)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: homography failed\n");
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: no selected paths\n");
        return;
    }

    int spacingMode = spacing & 0x03;
    int direction   = (spacing >> 2) & 0x03;

    double dirX = 0, dirY = 0;
    double baseOffset = 0.15;

    switch (direction) {
        case 0:  dirX = -baseOffset; dirY = 0; break;
        case 1:  dirX =  baseOffset; dirY = 0; break;
        case 2:  dirX = 0;           dirY = -baseOffset; break;
        case 3:  dirX = 0;           dirY =  baseOffset; break;
        default: dirX = baseOffset;  dirY = 0; break;
    }

    int totalCreated = 0;

    for (ai::int32 mi = 0; mi < numMatches; mi++) {
        AIArtHandle art = (*matches)[mi];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        AIPathStyle style;
        AIBoolean hasAdvFill = false;
        bool hasStyle = (sAIPathStyle->GetPathStyle(art, &style, &hasAdvFill) == kNoErr);

        // Compute centroid in perspective space for depth scaling
        AIRealPoint centroid = {0, 0};
        for (int s = 0; s < segCount; s++) {
            centroid.h += segs[s].p.h;
            centroid.v += segs[s].p.v;
        }
        centroid.h /= segCount;
        centroid.v /= segCount;
        AIRealPoint centroidPersp = ApplyHomography(Hinv, centroid);

        for (int ci = 1; ci <= count; ci++) {
            double stepScale = (double)ci;

            double perspOffX, perspOffY;
            if (spacingMode == 0) {
                perspOffX = dirX * stepScale;
                perspOffY = dirY * stepScale;
            } else {
                double depthFactor = 1.0 + stepScale * 0.15;
                perspOffX = dirX * stepScale * depthFactor;
                perspOffY = dirY * stepScale * depthFactor;
            }

            AIRealPoint newCentroidPersp = {
                (AIReal)(centroidPersp.h + perspOffX),
                (AIReal)(centroidPersp.v + perspOffY)
            };
            AIRealPoint newCentroidArt = ApplyHomography(H, newCentroidPersp);
            AIRealPoint origCentroidArt = ApplyHomography(H, centroidPersp);

            double wOrig = Hinv[6] * origCentroidArt.h + Hinv[7] * origCentroidArt.v + Hinv[8];
            double wNew  = Hinv[6] * newCentroidArt.h  + Hinv[7] * newCentroidArt.v  + Hinv[8];
            double scaleFactor = (std::abs(wOrig) > 1e-12 && std::abs(wNew) > 1e-12) ?
                                 wNew / wOrig : 1.0;
            if (scaleFactor < 0.1) scaleFactor = 0.1;
            if (scaleFactor > 5.0) scaleFactor = 5.0;

            std::vector<AIPathSegment> dupSegs(segCount);
            for (int s = 0; s < segCount; s++) {
                const AIPathSegment& orig = segs[s];
                AIPathSegment& dup = dupSegs[s];

                AIRealPoint pPersp = ApplyHomography(Hinv, orig.p);
                pPersp.h = (AIReal)(pPersp.h + perspOffX);
                pPersp.v = (AIReal)(pPersp.v + perspOffY);
                dup.p = ApplyHomography(H, pPersp);

                AIRealPoint inPersp = ApplyHomography(Hinv, orig.in);
                AIRealPoint anchorPersp = ApplyHomography(Hinv, orig.p);
                double inDx = inPersp.h - anchorPersp.h;
                double inDy = inPersp.v - anchorPersp.v;
                AIRealPoint inOffPersp = {
                    (AIReal)(anchorPersp.h + perspOffX + inDx * scaleFactor),
                    (AIReal)(anchorPersp.v + perspOffY + inDy * scaleFactor)
                };
                dup.in = ApplyHomography(H, inOffPersp);

                AIRealPoint outPersp = ApplyHomography(Hinv, orig.out);
                double outDx = outPersp.h - anchorPersp.h;
                double outDy = outPersp.v - anchorPersp.v;
                AIRealPoint outOffPersp = {
                    (AIReal)(anchorPersp.h + perspOffX + outDx * scaleFactor),
                    (AIReal)(anchorPersp.v + perspOffY + outDy * scaleFactor)
                };
                dup.out = ApplyHomography(H, outOffPersp);

                dup.corner = orig.corner;
            }

            AIArtHandle newArt = nullptr;
            ASErr dupErr = sAIArt->DuplicateArt(art, kPlaceAbove, art, &newArt);
            if (dupErr == kNoErr && newArt) {
                sAIPath->SetPathSegments(newArt, 0, segCount, dupSegs.data());
                if (hasStyle) {
                    sAIPathStyle->SetPathStyle(newArt, &style);
                }
                totalCreated++;
            }
        }
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool PerspModule] DuplicateInPerspective: created %d copies (count=%d, dir=%d, spacing=%d)\n",
            totalCreated, count, direction, spacingMode);

    InvalidateFullView();
}

//========================================================================================
//  Paste in Perspective
//========================================================================================

void PerspectiveModule::PasteInPerspective(int plane, float scale)
{
    if (!fGrid.valid) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: grid not valid\n");
        return;
    }
    if (!sAIPath || !sAIArt || !sAIPathStyle) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: missing suites\n");
        return;
    }
    if (scale < 0.01f) scale = 0.01f;
    if (scale > 10.0f) scale = 10.0f;

    double H[9], Hinv[9];
    bool gotH = false;

    if (plane == 0) {
        gotH = fGrid.ComputeFloorHomography(H);
    } else {
        gotH = ComputeWallHomography(fGrid, plane, H);
    }

    if (!gotH) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: homography failed for plane %d\n", plane);
        return;
    }
    if (!InvertMatrix3x3(H, Hinv)) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: matrix inversion failed\n");
        return;
    }

    AIArtHandle** matches = nullptr;
    ai::int32 numMatches = 0;
    if (!GetSelectedPaths(matches, numMatches)) {
        fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: no selected paths\n");
        return;
    }

    fUndoStack.PushFrame();
    int transformedCount = 0;

    // Compute global centroid
    AIRealPoint globalCentroid = {0, 0};
    int totalPoints = 0;
    for (ai::int32 i = 0; i < numMatches; i++) {
        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr((*matches)[i], kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount((*matches)[i], &segCount) != kNoErr) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments((*matches)[i], 0, segCount, segs.data()) != kNoErr) continue;

        for (int s = 0; s < segCount; s++) {
            globalCentroid.h += segs[s].p.h;
            globalCentroid.v += segs[s].p.v;
            totalPoints++;
        }
    }
    if (totalPoints > 0) {
        globalCentroid.h /= totalPoints;
        globalCentroid.v /= totalPoints;
    }

    for (ai::int32 i = 0; i < numMatches; i++) {
        AIArtHandle art = (*matches)[i];

        ai::int32 attrs = 0;
        sAIArt->GetArtUserAttr(art, kArtLocked | kArtHidden, &attrs);
        if (attrs & (kArtLocked | kArtHidden)) continue;

        ai::int16 segCount = 0;
        if (sAIPath->GetPathSegmentCount(art, &segCount) != kNoErr || segCount < 1) continue;

        std::vector<AIPathSegment> segs(segCount);
        if (sAIPath->GetPathSegments(art, 0, segCount, segs.data()) != kNoErr) continue;

        fUndoStack.SnapshotPath(art);

        std::vector<AIPathSegment> projSegs(segCount);
        double normRange = 200.0;
        for (int s = 0; s < segCount; s++) {
            const AIPathSegment& orig = segs[s];
            AIPathSegment& proj = projSegs[s];

            AIRealPoint centered = {
                (AIReal)((orig.p.h - globalCentroid.h) * scale),
                (AIReal)((orig.p.v - globalCentroid.v) * scale)
            };
            AIRealPoint uv = {
                (AIReal)(0.5 + centered.h / normRange),
                (AIReal)(0.5 + centered.v / normRange)
            };
            proj.p = ApplyHomography(H, uv);

            AIRealPoint inCentered = {
                (AIReal)((orig.in.h - globalCentroid.h) * scale),
                (AIReal)((orig.in.v - globalCentroid.v) * scale)
            };
            AIRealPoint inUV = {
                (AIReal)(0.5 + inCentered.h / normRange),
                (AIReal)(0.5 + inCentered.v / normRange)
            };
            proj.in = ApplyHomography(H, inUV);

            AIRealPoint outCentered = {
                (AIReal)((orig.out.h - globalCentroid.h) * scale),
                (AIReal)((orig.out.v - globalCentroid.v) * scale)
            };
            AIRealPoint outUV = {
                (AIReal)(0.5 + outCentered.h / normRange),
                (AIReal)(0.5 + outCentered.v / normRange)
            };
            proj.out = ApplyHomography(H, outUV);

            proj.corner = orig.corner;
        }

        sAIPath->SetPathSegments(art, 0, segCount, projSegs.data());
        transformedCount++;
    }

    if (matches) sAIMdMemory->MdMemoryDisposeHandle((AIMdMemoryHandle)matches);

    fprintf(stderr, "[IllTool PerspModule] PasteInPerspective: transformed %d paths onto plane %d (scale=%.2f)\n",
            transformedCount, plane, scale);

    InvalidateFullView();
}
