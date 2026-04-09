#pragma once

#include "IllToolSuites.h"
#include <string>
#include <map>

//========================================================================================
//  UISkinLoader — Runtime-loaded UI skin from IllTool-UI.ai
//
//  Reads named art objects from a companion Illustrator file and caches their
//  geometry/colors for use by the annotator drawing code. Falls back to
//  hardcoded defaults if the file is missing.
//
//  Named objects expected in IllTool-UI.ai:
//    handle-bbox       Circle handle for bounding box corners/midpoints
//    handle-anchor     Square handle for path anchor points
//    handle-vp1        Circle handle for VP1 (red)
//    handle-vp2        Circle handle for VP2 (green)
//    handle-vp3        Circle handle for VP3 (blue)
//    cursor-hotspot    Crosshair marker defining the cursor click point
//
//  Each named object stores:
//    - Size (width in points, used as handle radius)
//    - Fill color (RGB)
//    - Stroke color (RGB)
//    - Stroke width
//========================================================================================

struct SkinElement {
    bool   loaded = false;
    double size   = 8.0;          // handle radius in points (default)
    double fillR  = 1, fillG = 1, fillB = 1;
    double strokeR = 0, strokeG = 0, strokeB = 0;
    double strokeWidth = 1.0;
};

class UISkinLoader {
public:
    static UISkinLoader& Instance();

    /** Load skin from IllTool-UI.ai file. Safe to call multiple times (no-op if loaded). */
    void Load();

    /** Check if a skin file was loaded (vs using defaults). */
    bool IsLoaded() const { return fSkinLoaded; }

    /** Get a named skin element. Returns defaults if not found. */
    const SkinElement& Get(const std::string& name) const;

    /** Default handle sizes (used when skin not loaded). */
    double BBoxHandleSize()   const;   // circle radius for bbox
    double AnchorHandleSize() const;   // square half-size for anchors
    double HoverHandleSize()  const;   // size when hovered

private:
    UISkinLoader() = default;

    std::map<std::string, SkinElement> fElements;
    SkinElement fDefaultElement;
    bool fSkinLoaded = false;
};
