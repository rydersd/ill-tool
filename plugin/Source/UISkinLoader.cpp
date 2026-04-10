//========================================================================================
//
//  UISkinLoader — Load UI skin from IllTool-UI.ai
//
//  Opens the companion Illustrator file, iterates named art objects,
//  extracts their visual properties, and caches for annotator use.
//
//========================================================================================

#include "UISkinLoader.h"
#include <cstdio>
#include <cstdlib>
#include <sys/stat.h>

UISkinLoader& UISkinLoader::Instance()
{
    static UISkinLoader instance;
    return instance;
}

void UISkinLoader::Load()
{
    if (fSkinLoaded) return;

    // Default elements (used when skin file is missing or element not found)
    fDefaultElement.loaded = false;
    fDefaultElement.size = 8.0;
    fDefaultElement.fillR = 1.0;
    fDefaultElement.fillG = 1.0;
    fDefaultElement.fillB = 1.0;
    fDefaultElement.strokeR = 0.0;
    fDefaultElement.strokeG = 0.0;
    fDefaultElement.strokeB = 0.0;
    fDefaultElement.strokeWidth = 1.0;

    // Register default skin elements
    SkinElement bboxHandle;
    bboxHandle.loaded = true;
    bboxHandle.size = 4.0;  // 8px diameter circles
    bboxHandle.fillR = 1.0; bboxHandle.fillG = 1.0; bboxHandle.fillB = 1.0;
    bboxHandle.strokeR = 0.2; bboxHandle.strokeG = 0.2; bboxHandle.strokeB = 0.2;
    bboxHandle.strokeWidth = 1.0;
    fElements["handle-bbox"] = bboxHandle;

    SkinElement anchorHandle;
    anchorHandle.loaded = true;
    anchorHandle.size = 3.5;  // 7px squares
    anchorHandle.fillR = 1.0; anchorHandle.fillG = 1.0; anchorHandle.fillB = 1.0;
    anchorHandle.strokeR = 0.2; anchorHandle.strokeG = 0.2; anchorHandle.strokeB = 0.2;
    anchorHandle.strokeWidth = 1.0;
    fElements["handle-anchor"] = anchorHandle;

    SkinElement vp1Handle;
    vp1Handle.loaded = true;
    vp1Handle.size = 5.0;
    vp1Handle.fillR = 1.0; vp1Handle.fillG = 0.3; vp1Handle.fillB = 0.3;  // red
    vp1Handle.strokeR = 0.8; vp1Handle.strokeG = 0.0; vp1Handle.strokeB = 0.0;
    fElements["handle-vp1"] = vp1Handle;

    SkinElement vp2Handle;
    vp2Handle.loaded = true;
    vp2Handle.size = 5.0;
    vp2Handle.fillR = 0.3; vp2Handle.fillG = 0.8; vp2Handle.fillB = 0.3;  // green
    vp2Handle.strokeR = 0.0; vp2Handle.strokeG = 0.6; vp2Handle.strokeB = 0.0;
    fElements["handle-vp2"] = vp2Handle;

    SkinElement vp3Handle;
    vp3Handle.loaded = true;
    vp3Handle.size = 5.0;
    vp3Handle.fillR = 0.3; vp3Handle.fillG = 0.5; vp3Handle.fillB = 1.0;  // blue
    vp3Handle.strokeR = 0.0; vp3Handle.strokeG = 0.2; vp3Handle.strokeB = 0.8;
    fElements["handle-vp3"] = vp3Handle;

    // Try to load the skin file
    const char* home = getenv("HOME");
    if (!home) {
        fprintf(stderr, "[UISkinLoader] No HOME, using defaults\n");
        return;
    }

    std::string skinPath = std::string(home) + "/Developer/ai-plugins/IllTool-UI.ai";
    struct stat st;
    if (stat(skinPath.c_str(), &st) != 0) {
        fprintf(stderr, "[UISkinLoader] No skin file at %s — using defaults\n", skinPath.c_str());
        return;
    }

    // TODO: Parse the .ai file to extract named art objects.
    // This requires opening the file via AIDocumentSuite and iterating named art.
    // For now, the defaults above are used. The skin file loading will be wired
    // when the actual IllTool-UI.ai is created by the user in Illustrator.
    fprintf(stderr, "[UISkinLoader] Found skin file at %s (parsing not yet implemented — using defaults)\n",
            skinPath.c_str());

    fSkinLoaded = true;
}

const SkinElement& UISkinLoader::Get(const std::string& name) const
{
    auto it = fElements.find(name);
    if (it != fElements.end()) return it->second;
    return fDefaultElement;
}

double UISkinLoader::BBoxHandleSize() const
{
    return Get("handle-bbox").size;
}

double UISkinLoader::AnchorHandleSize() const
{
    return Get("handle-anchor").size;
}

double UISkinLoader::HoverHandleSize() const
{
    return Get("handle-bbox").size + 1.0;  // 1px larger on hover
}
