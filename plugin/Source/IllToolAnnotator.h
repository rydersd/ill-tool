//========================================================================================
//
//  IllTool Plugin — Annotator (overlay drawing)
//
//  Derived from Adobe Illustrator 2026 SDK Annotator sample.
//  Renders draw commands from the HTTP bridge and polygon lasso
//  overlay via AIAnnotatorDrawerSuite.
//
//========================================================================================

#ifndef __ILLTOOLANNOTATOR_H__
#define __ILLTOOLANNOTATOR_H__

#include "AIAnnotator.h"
#include "SDKErrors.h"
#include "IllToolSuites.h"

/** Annotator that renders draw commands via AIAnnotatorDrawerSuite.
    Draw commands come from two sources:
    1. HTTP bridge (external callers via POST /draw)
    2. Polygon lasso overlay (internal tool state)
*/
class IllToolAnnotator
{
public:
    IllToolAnnotator();
    virtual ~IllToolAnnotator() {}

    /** Called on every cursor move while the tool is active. */
    ASErr TrackCursor(AIToolMessage* message);

    /** Draw callback — renders all buffered draw commands. */
    ASErr Draw(AIAnnotatorMessage* message);

    /** Invalidate a rect so the annotator redraws. */
    ASErr InvalidateRect(const AIRealRect& invalRealRect);
    ASErr InvalidateRect(const AIRect& invalRect);

private:
    /** Convert artwork-coordinate rect to view-coordinate rect. */
    ASErr ArtworkBoundsToViewBounds(const AIRealRect& artworkBounds, AIRect& viewBounds);
};

#endif // __ILLTOOLANNOTATOR_H__
