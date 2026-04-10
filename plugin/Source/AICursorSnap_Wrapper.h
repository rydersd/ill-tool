//========================================================================================
//
//  AICursorSnap_Wrapper.h — Minimal wrapper for AI Cursor Snap Suite
//
//  Declares just the types and functions needed by IllTool for custom
//  perspective-line snap constraints.  Based on the full SDK header
//  AICursorSnap.h (v16).
//
//========================================================================================

#ifndef __AICURSORSNAP_WRAPPER_H__
#define __AICURSORSNAP_WRAPPER_H__

#include "AITypes.h"
#include "AIDocumentView.h"   // AIDocumentViewHandle
#include "IAIAutoBuffer.h"
#include "IAIUnicodeString.h"

#include "AIHeaderBegin.h"

//------------------------------------------------------------------------------------
//  Suite name / version
//------------------------------------------------------------------------------------

#define kAICursorSnapSuite              "AI Cursor Snap Suite"
#define kAICursorSnapSuiteVersion16     AIAPI_VERSION(16)
#define kAICursorSnapSuiteVersion       kAICursorSnapSuiteVersion16
#define kAICursorSnapVersion            kAICursorSnapSuiteVersion

//------------------------------------------------------------------------------------
//  Constraint kind constants
//------------------------------------------------------------------------------------

enum {
    /** Single point */
    kPointConstraint = 1,
    /** A line whose angle is relative to the page coordinates */
    kLinearConstraintAbs,
    /** A line whose angle is relative to the constraint angle */
    kLinearConstraintRel
};

//------------------------------------------------------------------------------------
//  Constraint flag constants
//------------------------------------------------------------------------------------

/** Snap to constraint when shift key is down. */
#define kShiftConstraint            (1<<0L)
/** Override drawing the default annotation when a custom constraint is hit. */
#define kDrawCustomAnnotations      (1<<1L)

//------------------------------------------------------------------------------------
//  AICursorConstraint — describes one custom snap constraint
//------------------------------------------------------------------------------------

/** Callback type for custom annotation drawing (unused by IllTool, but
    required for struct layout compatibility). */
struct AICustomAnnotationLine {
    AIRealPoint startPoint;
    AIRealPoint endPoint;
};

typedef AIErr(*CustomAnnotationsCallback)(
    ai::uint32 inId,
    const AIRealPoint& inSnappedPt,
    size_t* outNumberOfLines,
    AICustomAnnotationLine** outAnnotationLines);

struct AICursorConstraint {
    ai::int32                   kind;
    ai::int32                   flags;
    AIRealPoint                 point;
    AIReal                      angle;
    ai::UnicodeString           label;
    CustomAnnotationsCallback   getCustomAnnotationDetails;

    AICursorConstraint(const ai::int32 inKind,
                       const ai::int32 inFlags,
                       const AIRealPoint& inPoint,
                       const AIReal inAngle,
                       const ai::UnicodeString& inLabel,
                       const CustomAnnotationsCallback inCb)
        : kind(inKind), flags(inFlags), point(inPoint),
          angle(inAngle), label(inLabel),
          getCustomAnnotationDetails(inCb) {}

    AICursorConstraint()
        : kind(0), flags(0), angle(kAIRealZero),
          getCustomAnnotationDetails(NULL)
    {
        point.h = kAIRealZero;
        point.v = kAIRealZero;
    }

    ~AICursorConstraint() {}
};

//------------------------------------------------------------------------------------
//  AICursorSnapSuite — only the functions IllTool needs
//------------------------------------------------------------------------------------

struct AICursorSnapSuite {
    /** Reports whether Smart Guides should be used in a given view. */
    AIAPI AIBoolean     (*UseSmartGuides)   (AIDocumentViewHandle view);

    /** Resets the snap engine — clears all custom and auto constraints. */
    AIAPI AIErr          (*Reset)            (void);

    /** Clears all custom constraints (keeps auto-generated ones). */
    AIAPI AIErr          (*ClearCustom)      (void);

    /** Replaces the current custom constraints with a new set.
        @param constraints  AutoBuffer of AICursorConstraint. */
    AIAPI AIErr          (*SetCustom)        (const ai::AutoBuffer<AICursorConstraint>& constraints);

    /** Snap cursor to constraint.
        @param view      Document view.
        @param srcpoint  Actual cursor position.
        @param event     Modifier key state.
        @param control   Smart Guide control string.
        @param dstpoint  [out] Snapped position. */
    AIAPI AIErr          (*Track)            (AIDocumentViewHandle view,
                                             const AIRealPoint& srcpoint,
                                             const AIEvent* event,
                                             const char* control,
                                             AIRealPoint* dstpoint);

    /** Snap cursor with hit-test semantics (direct selection). */
    AIAPI AIErr          (*HitTrack)         (AIDocumentViewHandle view,
                                             const AIRealPoint& srcpoint,
                                             const AIEvent* event,
                                             const char* control,
                                             AIRealPoint* dstpoint,
                                             AIBoolean magnifyAnchorPoint);

    /** Snap a rectangle to constraint. */
    AIAPI AIErr          (*TrackInRect)      (AIDocumentViewHandle view,
                                             const AIRealPoint& srcpoint,
                                             const AIEvent* event,
                                             const char* control,
                                             AIRealPoint* dstpoint,
                                             const AIRealRect* srcrect,
                                             AIRealRect* dstrect);
};

#include "AIHeaderEnd.h"

#endif // __AICURSORSNAP_WRAPPER_H__
